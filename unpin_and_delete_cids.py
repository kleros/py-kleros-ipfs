"""
Safely remove CIDs from IPFS storage.

Workflow per CID:
  1. Download locally via SSH tunnel (backup before deletion).
  2. Delete pin from Filebase bucket.
  3. Unpin from each remote Kubo node via SSH.

Usage:
  python unpin_and_delete_cids.py --file cids.txt --bucket kleros \\
      --kubo-hosts host1 host2 --ssh-user ubuntu
  python unpin_and_delete_cids.py --dry-run Qm123... Qm456...
"""
import argparse
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

from filebase_pin_api import FilebasePinAPI
from kubo_rpc_api import KuboRPC
from logger import setup_logger

load_dotenv()

DOWNLOAD_DIR = Path("./downloads")
LOG_FILE = "/tmp/unpin_and_delete_cids.log"
logger = setup_logger("unpin-and-delete-cids", LOG_FILE)

KUBO_PORT = 5001
TUNNEL_BASE_PORT = 15001


# --- helpers -----------------------------------------------------------------

@contextmanager
def ssh_tunnel(host: str, user: str, local_port: int):
    proc = subprocess.Popen(
        ["ssh", "-N", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes",
         "-o", "ExitOnForwardFailure=yes",
         "-L", f"{local_port}:127.0.0.1:{KUBO_PORT}", f"{user}@{host}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"SSH tunnel to {host} failed: {proc.stderr.read().decode().strip()}")
        try:
            with socket.create_connection(("127.0.0.1", local_port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.3)
    else:
        proc.kill()
        raise RuntimeError(f"SSH tunnel to {host} timed out")
    logger.info("Tunnel ready → %s:%d", host, KUBO_PORT)
    try:
        yield local_port
    finally:
        proc.terminate()
        proc.wait()


def sniff_ext(data: bytes) -> str:
    for magic, ext in [(b"%PDF", ".pdf"), (b"\x89PNG", ".png"),
                       (b"\xff\xd8\xff", ".jpg"), (b"GIF8", ".gif"),
                       (b"PK\x03\x04", ".zip"), (b"<?xml", ".xml"),
                       (b"<!DOCTYPE", ".html"), (b"<html", ".html")]:
        if data[:16].startswith(magic):
            return ext
    if data[:64].lstrip().startswith((b"{", b"[")):
        return ".json"
    return ""


def download(rpc: KuboRPC, cid: str) -> bool:
    cid_dir = DOWNLOAD_DIR / cid
    if cid_dir.exists() and any(cid_dir.iterdir()):
        logger.info("Already downloaded: %s", cid)
        return True

    cid_dir.mkdir(parents=True, exist_ok=True)
    res = rpc.cat(cid, timeout=120)

    if res.status_code == 500 and "this dag node is a directory" in res.text:
        ls = rpc.ls(cid)
        for link in ls["Objects"][0]["Links"]:
            if link["Type"] != 2:
                continue
            r = rpc.cat(link["Hash"], timeout=120)
            if not r.ok:
                logger.error("cat failed: %s/%s — %s", cid, link["Name"], r.text)
                return False
            (cid_dir / link["Name"]).write_bytes(r.content)
            logger.info("Saved %s/%s (%d bytes)", cid, link["Name"], len(r.content))
        return True

    if not res.ok:
        logger.error("cat failed: %s — %s", cid, res.text)
        return False

    name = f"content{sniff_ext(res.content)}"
    (cid_dir / name).write_bytes(res.content)
    logger.info("Saved %s/%s (%d bytes)", cid, name, len(res.content))
    return True


def filebase_delete(api: FilebasePinAPI, bucket: str, cid: str, dry_run: bool) -> bool:
    res = api.get_file(bucket, cid)
    results = res.get("results", [])
    if not results:
        logger.warning("Not found in Filebase %s (already deleted?): %s", bucket, cid)
        return True  # already gone — not an error
    request_id = results[0]["requestid"]
    if dry_run:
        logger.info("[DRY RUN] Would delete %s from Filebase (%s)", cid, request_id)
        return True
    r = api.delete_pin(bucket, request_id)
    if r.ok:
        logger.info("Filebase deleted: %s", cid)
    else:
        logger.error("Filebase delete failed: %s — %s", cid, r.text)
    return r.ok


def kubo_unpin(rpc: KuboRPC, cid: str, host: str, user: str, dry_run: bool) -> bool:
    if not rpc.is_pinned(cid):
        logger.warning("Not pinned on %s: %s", host, cid)
        return True
    if dry_run:
        logger.info("[DRY RUN] Would unpin %s from %s", cid, host)
        return True
    # Run directly via SSH — HTTP times out on nodes with 500k+ pins
    r = subprocess.run(
        ["ssh", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=120",
         "-o", "BatchMode=yes", f"{user}@{host}",
         f"sudo docker exec ipfs ipfs pin rm {cid}"],
        capture_output=True, text=True, timeout=3600,
    )
    if r.returncode == 0:
        logger.info("Unpinned from %s: %s", host, cid)
        return True
    logger.error("Unpin failed on %s for %s: %s", host, cid, r.stderr.strip())
    return False


# --- main --------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cids", nargs="*", metavar="CID")
    p.add_argument("--file", "-f", metavar="PATH", help="File with one CID per line (# ignored)")
    p.add_argument("--bucket", "-b", default="kleros", help="Filebase bucket (default: kleros)")
    p.add_argument("--kubo-hosts", nargs="+", default=[], metavar="HOST")
    p.add_argument("--ssh-user", default=None, help="Required when --kubo-hosts is set")
    p.add_argument("--no-download", action="store_true", help="Skip local backup step")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    cids: list[str] = list(args.cids)
    if args.file:
        lines = Path(args.file).read_text(encoding="utf-8").splitlines()
        cids += [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    cids = list(dict.fromkeys(cids))

    if not cids:
        sys.exit("No CIDs provided.")
    if args.kubo_hosts and not args.ssh_user:
        sys.exit("--ssh-user required when --kubo-hosts is set.")
    if args.dry_run:
        logger.info("DRY RUN — no changes will be made")

    api = FilebasePinAPI(log_filepath=LOG_FILE)
    failed: list[str] = []

    # Step 1 — download (via first kubo host)
    if not args.no_download and not args.dry_run:
        if not args.kubo_hosts:
            sys.exit("--kubo-hosts required for download step (or use --no-download).")
        with ssh_tunnel(args.kubo_hosts[0], args.ssh_user, TUNNEL_BASE_PORT) as port:
            rpc = KuboRPC(api_url=f"http://127.0.0.1:{port}/api/v0", log_filepath=LOG_FILE)
            for cid in cids:
                if not download(rpc, cid):
                    logger.error("Download failed, skipping %s", cid)
                    failed.append(cid)

    # Steps 2 & 3 run on all CIDs not aborted by download failure
    safe = [c for c in cids if c not in failed]

    # Step 2 — Filebase (not found = already deleted, not a blocker)
    for cid in safe:
        if not filebase_delete(api, args.bucket, cid, args.dry_run):
            failed.append(cid)

    # Step 3 — Kubo nodes (runs on safe, independent of Filebase result)
    for i, host in enumerate(args.kubo_hosts):
        with ssh_tunnel(host, args.ssh_user, TUNNEL_BASE_PORT + i) as port:
            rpc = KuboRPC(api_url=f"http://127.0.0.1:{port}/api/v0", log_filepath=LOG_FILE)
            for cid in safe:
                if not kubo_unpin(rpc, cid, host, args.ssh_user, args.dry_run):
                    failed.append(cid)

    print(f"\nDone. {len(cids) - len(set(failed))}/{len(cids)} CIDs processed successfully.")
    if failed:
        print("Failed:", ", ".join(set(failed)))
        sys.exit(1)


if __name__ == "__main__":
    main()

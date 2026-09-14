"""
Gateway Latency Test
====================
Uploads N files to IPFS via Filebase and measures how long each one takes
to become available through a gateway. Prints a statistical report at the end.

Steps (per iteration):
  1. Generate a random JSON payload (guarantees a unique CID every run).
  2. Upload it to a Filebase bucket via the S3-compatible API.
     Filebase returns the assigned CID in the 'x-amz-meta-cid' response header.
  3. Poll the gateway in a loop until the file is returned (or timeout).
  4. Validate that the response body matches the original content.
  5. After all iterations, print a report: all delays, mean, median, std.

Requirements:
  pip install boto3 python-dotenv requests

Environment variables (in .env):
  FILEBASE_ACCESS_KEY   – Filebase S3 access key
  FILEBASE_SECRET_KEY   – Filebase S3 secret key
  FILEBASE_BUCKET       – target bucket name (default: kleros-test)
  GATEWAY_URL           – gateway base URL (default: https://cdn.kleros.link)
"""

import hashlib
import json
import math
import os
import random
import string
import time
from datetime import datetime, timezone

import boto3
from botocore.client import Config
import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
FILEBASE_ENDPOINT = "https://s3.filebase.com"
FILEBASE_ACCESS_KEY: str = os.environ["FILEBASE_ACCESS_KEY"]
FILEBASE_SECRET_KEY: str = os.environ["FILEBASE_SECRET_KEY"]
BUCKET: str = os.getenv("FILEBASE_BUCKET", "kleros-test")
GATEWAY_BASE: str = os.getenv(
    "GATEWAY_URL", "https://cdn.kleros.link").rstrip("/")

# Test settings
NUM_ITERATIONS: int = 50

# Polling settings
POLL_INTERVAL_SECONDS: float = 2.0    # time between gateway requests
TIMEOUT_SECONDS: float = 60.* 5        # give up after this long (per file)
REQUEST_TIMEOUT: float = 10.0         # per-request HTTP timeout


# ---------------------------------------------------------------------------
# Step 1 – Generate random content
# ---------------------------------------------------------------------------
def generate_payload() -> dict:
    """Return a dict with random data so every run produces a unique CID."""
    random_str = "".join(random.choices(
        string.ascii_letters + string.digits, k=32))
    return {
        "test": "gateway_latency",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "random": random_str,
    }


# ---------------------------------------------------------------------------
# Step 2 – Upload via Filebase S3 API
# ---------------------------------------------------------------------------
def upload_to_filebase(s3_client, payload: dict) -> tuple[str, bytes]:
    """
    Upload *payload* as a JSON object to Filebase and return (cid, raw_bytes).

    Filebase sets the CID in the response header 'x-amz-meta-cid' after a
    successful PutObject. We retrieve it via a HeadObject call because
    boto3 does not expose the raw response headers for PutObject.
    """
    content: bytes = json.dumps(payload, indent=2).encode("utf-8")
    object_key: str = f"latency-test-{int(time.time() * 1000)}.json"

    s3_client.put_object(
        Bucket=BUCKET,
        Key=object_key,
        Body=content,
        ContentType="application/json",
    )

    head = s3_client.head_object(Bucket=BUCKET, Key=object_key)
    cid: str | None = (
        head.get("ResponseMetadata", {}).get(
            "HTTPHeaders", {}).get("x-amz-meta-cid")
    )

    if not cid:
        cid = head.get("Metadata", {}).get("cid")

    if not cid:
        raise RuntimeError(
            "Filebase did not return a CID in the response headers. "
            f"Full HeadObject response:\n{json.dumps(head, indent=2, default=str)}"
        )

    return cid, content


# ---------------------------------------------------------------------------
# Step 3 & 4 – Poll gateway and validate content
# ---------------------------------------------------------------------------
def poll_gateway(cid: str, expected_content: bytes) -> float | None:
    """
    Poll GATEWAY_BASE/ipfs/<cid> until the file is served or timeout is reached.
    Validates that the returned body matches expected_content.

    Returns:
        float: elapsed seconds until the gateway returned HTTP 200.
        None:  if the timeout was reached without a successful response.
    """
    url = f"{GATEWAY_BASE}/ipfs/{cid}"
    expected_sha256 = hashlib.sha256(expected_content).hexdigest()
    start_time = time.monotonic()
    attempt = 0

    while True:
        attempt += 1
        elapsed = time.monotonic() - start_time

        if elapsed > TIMEOUT_SECONDS:
            print(
                f"  [gateway] TIMEOUT after {elapsed:.1f}s ({attempt} attempts). "
                "File never returned by gateway."
            )
            return None

        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)

            if response.status_code == 200:
                actual_sha256 = hashlib.sha256(response.content).hexdigest()
                if actual_sha256 == expected_sha256:
                    print(
                        f"  [gateway] OK after {elapsed:.2f}s (attempt #{attempt}) – content validated.")
                else:
                    print(
                        f"  [gateway] OK after {elapsed:.2f}s but CONTENT MISMATCH! "
                        f"expected={expected_sha256} actual={actual_sha256}"
                    )
                return elapsed

            print(
                f"  [gateway] #{attempt:>4}  {elapsed:>6.1f}s  HTTP {response.status_code}"
            )

        except requests.exceptions.Timeout:
            print(
                f"  [gateway] #{attempt:>4}  {elapsed:>6.1f}s  request timed out")
        except requests.exceptions.RequestException as exc:
            print(f"  [gateway] #{attempt:>4}  {elapsed:>6.1f}s  error: {exc}")

        time.sleep(POLL_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def compute_stats(values: list[float]) -> dict:
    n = len(values)
    mean = sum(values) / n
    sorted_v = sorted(values)
    mid = n // 2
    median = sorted_v[mid] if n % 2 else (
        sorted_v[mid - 1] + sorted_v[mid]) / 2
    variance = sum((x - mean) ** 2 for x in values) / n
    std = math.sqrt(variance)
    return {"mean": mean, "median": median, "std": std, "min": min(values), "max": max(values)}


def print_report(delays: list[float | None]) -> None:
    successful = [d for d in delays if d is not None]
    timeouts = len(delays) - len(successful)

    print("\n" + "=" * 60)
    print("  REPORT")
    print("=" * 60)
    print(f"  Total runs  : {len(delays)}")
    print(f"  Successful  : {len(successful)}")
    print(f"  Timeouts    : {timeouts}")

    if not successful:
        print("  No successful measurements to report.")
        return

    print("\n  Delays per run (seconds):")
    for i, d in enumerate(delays, 1):
        label = f"{d:.2f}s" if d is not None else "TIMEOUT"
        print(f"    Run {i:>3}: {label}")

    stats = compute_stats(successful)
    print(f"\n  Mean   : {stats['mean']:.2f}s")
    print(f"  Median : {stats['median']:.2f}s")
    print(f"  Std    : {stats['std']:.2f}s")
    print(f"  Min    : {stats['min']:.2f}s")
    print(f"  Max    : {stats['max']:.2f}s")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print(f"  IPFS Gateway Latency Test  ({NUM_ITERATIONS} iterations)")
    print(f"  Gateway : {GATEWAY_BASE}")
    print(f"  Bucket  : {BUCKET}")
    print("=" * 60)

    s3_client = boto3.client(
        "s3",
        endpoint_url=FILEBASE_ENDPOINT,
        aws_access_key_id=FILEBASE_ACCESS_KEY,
        aws_secret_access_key=FILEBASE_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )

    delays: list[float | None] = []

    for i in range(1, NUM_ITERATIONS + 1):
        print(f"\n--- Run {i}/{NUM_ITERATIONS} ---")

        payload = generate_payload()
        cid, raw_content = upload_to_filebase(s3_client, payload)
        print(f"  [upload] CID: {cid}")

        delay = poll_gateway(cid=cid, expected_content=raw_content)
        delays.append(delay)

    print_report(delays)


if __name__ == "__main__":
    main()

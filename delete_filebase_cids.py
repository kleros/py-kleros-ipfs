"""
Delete one or more CIDs from Filebase buckets by CID, idempotently.

Unlike delete_poh_user_data.delete_from_filebase (which only deletes the first
pin request found and only sees "pinned" ones), this script finds every pin
request in every status for a CID, deletes all of them, and re-checks until
the CID is confirmed gone or a small number of rounds is exhausted.

Output contract:
    stdout  a single JSON document: {"ok", "dry_run", "results": [...]}
    stderr  human readable progress and diagnostics

Exit codes:
    0  every (bucket, cid) verified absent (or, in --dry-run, every lookup succeeded)
    1  setup failure (e.g. a required FILEBASE_TOKEN_* is missing)
    2  something is not verified absent, or a per-item error occurred

Usage:
    python delete_filebase_cids.py QmFoo QmBar
    python delete_filebase_cids.py --dry-run --bucket kleros QmFoo
"""
import argparse
import json
import logging
import os
import sys
import time
from typing import Callable, List, Optional, TypedDict

import requests

from filebase_datatypes import PinStatus
from filebase_pin_api import FilebasePinAPI
from logger import setup_logger

DEFAULT_BUCKETS: List[str] = ["kleros", "poh-v2"]
ALL_STATUSES: List[PinStatus] = [
    PinStatus.QUEUED, PinStatus.PINNING, PinStatus.PINNED, PinStatus.FAILED]

MAX_ROUNDS: int = 5
ROUND_DELAY_SECONDS: float = 2.0
MAX_RETRY_ATTEMPTS: int = 5
RETRY_BASE_DELAY: float = 2.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

log_path: str = os.getenv("LOG_FILEPATH", "/var/log/py-kleros-ipfs")
log_filepath: str = os.path.join(log_path, "delete_filebase_cids.log")
logger: logging.Logger = setup_logger("delete_filebase_cids", log_filepath)

# Move this script's own console output off stdout: it must carry only the
# final JSON report.
for _handler in logger.handlers:
    if type(_handler) is logging.StreamHandler:
        _handler.setStream(sys.stderr)


class ItemResult(TypedDict):
    bucket: str
    cid: str
    found: int
    deleted: List[str]
    verified_absent: bool
    error: Optional[str]


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(error, requests.HTTPError):
        response = error.response
        return response is not None and response.status_code in RETRYABLE_STATUS_CODES
    return False


def call_with_retry(
    func: Callable, *args,
    max_attempts: int, base_delay: float, sleep_fn: Callable[[float], None],
    **kwargs,
):
    """Call func(*args, **kwargs), retrying with exponential backoff on
    transient network/HTTP errors. Any other error is raised immediately."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return func(*args, **kwargs)
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as error:
            if attempt >= max_attempts or not _is_retryable(error):
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "Retryable error on attempt %d/%d: %s. Retrying in %.1fs",
                attempt, max_attempts, error, delay)
            sleep_fn(delay)


def _find_pin_requests(
    api: FilebasePinAPI, bucket: str, cid: str,
    max_attempts: int, base_delay: float, sleep_fn: Callable[[float], None],
) -> list:
    response = call_with_retry(
        api.get_file, bucket, cid, statuses=ALL_STATUSES,
        max_attempts=max_attempts, base_delay=base_delay, sleep_fn=sleep_fn)
    return response.get("results", [])


def _delete_and_check(api: FilebasePinAPI, bucket: str, requestid: str) -> None:
    response = api.delete_pin(bucket, requestid)
    if response.status_code == 404:
        # Already gone: not an error, nothing left to do for this requestid.
        return
    response.raise_for_status()


def process_item(  # pylint: disable=too-many-arguments
    api: FilebasePinAPI, bucket: str, cid: str, dry_run: bool,
    max_rounds: int = MAX_ROUNDS, round_delay: float = ROUND_DELAY_SECONDS,
    max_attempts: int = MAX_RETRY_ATTEMPTS, base_delay: float = RETRY_BASE_DELAY,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ItemResult:
    """
    Find, delete and re-verify every pin request for one (bucket, cid).

    verified_absent is only True when a lookup succeeded and returned zero
    results. A ValueError (missing Filebase token) is a setup failure and is
    deliberately not caught here: it must abort the whole run, not be
    swallowed as a per-item error.
    """
    deleted: List[str] = []
    found = 0
    try:
        results = _find_pin_requests(
            api, bucket, cid, max_attempts, base_delay, sleep_fn)
        found = len(results)
        if not results:
            return {"bucket": bucket, "cid": cid, "found": found,
                     "deleted": deleted, "verified_absent": True, "error": None}
        if dry_run:
            return {"bucket": bucket, "cid": cid, "found": found,
                     "deleted": deleted, "verified_absent": False, "error": None}

        for round_num in range(max_rounds):
            for pin in results:
                requestid = pin["requestid"]
                call_with_retry(
                    _delete_and_check, api, bucket, requestid,
                    max_attempts=max_attempts, base_delay=base_delay, sleep_fn=sleep_fn)
                deleted.append(requestid)
            if round_num < max_rounds - 1:
                sleep_fn(round_delay)
            results = _find_pin_requests(
                api, bucket, cid, max_attempts, base_delay, sleep_fn)
            if not results:
                return {"bucket": bucket, "cid": cid, "found": found,
                         "deleted": deleted, "verified_absent": True, "error": None}

        return {"bucket": bucket, "cid": cid, "found": found,
                 "deleted": deleted, "verified_absent": False, "error": None}
    except requests.RequestException as error:
        logger.error("Error processing CID %s in bucket %s: %s", cid, bucket, error)
        return {"bucket": bucket, "cid": cid, "found": found,
                 "deleted": deleted, "verified_absent": False, "error": str(error)}


def process_all(
    api: FilebasePinAPI, buckets: List[str], cids: List[str], dry_run: bool,
) -> List[ItemResult]:
    results: List[ItemResult] = []
    for bucket in buckets:
        for cid in cids:
            logger.info("Processing bucket=%s cid=%s", bucket, cid)
            results.append(process_item(api, bucket, cid, dry_run))
    return results


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete PoH CIDs from Filebase buckets by CID, idempotently.")
    parser.add_argument("cids", nargs="+", metavar="CID")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only look up pin requests, delete nothing")
    parser.add_argument(
        "--bucket", action="append", dest="buckets", metavar="NAME",
        help="Bucket to operate on (repeatable). Defaults to kleros and poh-v2")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    buckets = args.buckets or list(DEFAULT_BUCKETS)
    cids = list(dict.fromkeys(args.cids))

    api = FilebasePinAPI(log_filepath=log_filepath)
    for _handler in api.logger.handlers:
        if type(_handler) is logging.StreamHandler:
            _handler.setStream(sys.stderr)

    try:
        results = process_all(api, buckets, cids, args.dry_run)
    except ValueError as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        return 1

    if args.dry_run:
        ok = all(item["error"] is None for item in results)
    else:
        ok = all(item["error"] is None and item["verified_absent"]
                  for item in results)

    print(json.dumps({"ok": ok, "dry_run": args.dry_run, "results": results}))

    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())

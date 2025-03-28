"""
getFilebaseCIDs.py
------------------
Iterate over a list of bucket to get the full list of CIDs in each bucket
"""

from typing import List

from filebase_pin_api import FilebasePinAPI


BUCKETS: List[str] = [
    'kleros',
    'kleros-v2',
    'kleros-websites',
    'poh-v2',
    'curate-v2',
    'escrow-v2',
    'reality-v2',
    'kleros-token-list',
    'v2-logs',
    'atlas-logs'
]


def main() -> None:
    """
    Main function that iterates over predefined buckets, retrieves all CIDs for each bucket,
    and prints the number of CIDs found in each bucket.

    BUCKETS: A predefined list of buckets to process.
    getAllCIDs(bucket): A function that takes a bucket as an argument and returns a list of CIDs.

    Returns:
        None
    """
    filebase_api = FilebasePinAPI(log_filepath="logs/get_filebase_cids.log")
    for bucket in BUCKETS:
        cids = filebase_api.get_all_cids(bucket)
        print(f"{bucket} has {len(cids)} CIDs")


if __name__ == "__main__":
    main()

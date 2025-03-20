"""
This script is used to compare the list of all the files that are currently pinned in the cluster
with the files that are already pinned in filebase. The missing files are pinned again using the filebase api
"""

import sys
import random
from typing import List

from filebase_datatypes import GetPinsResponse
from filebase_pin_api import PinStatus, FilebasePinAPI
from kubo_rpc_api import KuboRPC


def get_missed_pins(kleros_ipfs_cids, filebase_cids):
    """
    Compare two lists of IPFS CIDs and return the list of CIDs that are present
    in the first list but missing in the second list.

    Args:
        kleros_ipfs_cids (list): A list of IPFS CIDs from Kleros.
        filebase_cids (list): A list of IPFS CIDs from Filebase.

    Returns:
        list: A list of CIDs that are in kleros_ipfs_cids but not in filebase_cids.
    """
    return list(set(kleros_ipfs_cids) - set(filebase_cids))


def main(filepath, bucket_name="kleros"):
    """
    Main function to read a list of CIDs from a file, compare them with the CIDs in Filebase, 
    and pin the missing CIDs to the specified bucket.

    Args:
        filepath (str): The path to the file containing the list of CIDs.
        bucket_name (str, optional): The name of the bucket to pin the CIDs to. Defaults to "kleros".

    Raises:
        Exception: If there is an error while trying to pin a CID.

    Prints:
        The first 10 CIDs from the list.
        The number of CIDs in Kleros IPFS, in Filebase, and the number of missed CIDs in Filebase.
    """
    kubo_rpc = KuboRPC(log_filepath='update_filebase_with_local.log')
    filebase_api = FilebasePinAPI(
        log_filepath='update_filebase_with_local.log')
    bucket_name = 'kleros'
    cids: List[str] = kubo_rpc.read_pin_ls_output(filepath)
    print(cids[0:10])
    filebase_cids_pinned: GetPinsResponse = filebase_api.get_list(
        bucket_name=bucket_name, status=PinStatus.PINNED)
    filebase_cids_queued = filebase_api.get_list(
        bucket_name=bucket_name, status=PinStatus.QUEUED)
    filebase_cids_pinning = filebase_api.get_list(
        bucket_name=bucket_name, status=PinStatus.PINNING)
    filebase_cids: List[str] = [item['pin']['cid'] for item in filebase_cids_pinned['results']] \
        + [item['pin']['cid'] for item in filebase_cids_queued['results']] \
        + [item['pin']['cid'] for item in filebase_cids_pinning['results']]
    missed_cids = get_missed_pins(cids, filebase_cids)
    count = 0
    print(
        f"There are {len(cids)} in Kleros IPFS, {len(filebase_cids)} in filebase,"
        f" and {len(missed_cids)} are missed in filebase."
    )
    random.shuffle(missed_cids)
    for cid in missed_cids:
        try:
            filebase_api.pin_cid(bucket_name, cid)
            count += 1
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: E722, W0718
            print(f"Error while trying to pin CID {cid}: {e}")


if __name__ == "__main__":
    main(sys.argv[1])

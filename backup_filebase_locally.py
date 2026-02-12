"""
Script to Get the list of files from Filebase and pin those CIDs that are missed
in the local node.

This script should be executed periodically to keep a backup node with all the files
that were pinned in filebase.
"""
import os
from dotenv import load_dotenv
from typing import Dict, List
import logging

import requests
from requests.exceptions import ReadTimeout

from filebase_datatypes import PinSetType
from kubo_datatypes import PinType
from kubo_rpc_api import KuboRPC
from filebase_pin_api import FilebasePinAPI
from logger import setup_logger

load_dotenv()
log_path: str = os.getenv('LOG_FILEPATH', '/var/log/py-kleros-ipfs')
betterstack_heartbeat_url: str = os.getenv('BETTERSTACK_HEARTBEAT_URL', '')
log_filepath: str = os.path.join(log_path, 'backup_filebase_locally.log')


RPC = KuboRPC(log_filepath=log_filepath,
              log_level=logging.DEBUG)
FILEBASE_API = FilebasePinAPI(log_filepath=log_filepath,
                              log_level=logging.DEBUG)
logger: logging.Logger = setup_logger(
    name="backup-filebase-locally", log_file=log_filepath, level=logging.DEBUG)
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
    'atlas-logs',
    'kleros-scout'
]


def get_local_node_pins(filepath: str = '/data/ipfs/local_node_pins.json') -> List[str]:
    """
    Retrieve the list of pinned content identifiers (CIDs) from a local IPFS node.
    Args:
        filepath (str): The path to the JSON file containing the local node pins. Defaults to 'local_node_pins.json'.
    Returns:
        List[str]: A list of CIDs pinned on the local IPFS node.
    """

    if not os.path.exists(filepath):
        # If does't exist, create it
        RPC.pin_ls(pin_type=PinType.ALL, filepath=filepath)

    return RPC.read_pin_ls_output(filepath)


def get_filebase_pins(filepath: str = 'pins_filebase.json') -> List[str]:
    """
    Retrieve a list of unique Content Identifiers (CIDs) from a JSON file.

    Args:
        filepath (str): The path to the JSON file containing pin data. Defaults to 'pins_filebase.json'.

    Returns:
        List[str]: A list of unique CIDs.
    """
    if not os.path.exists(filepath):
        # If does't exist, throw an error, creating this file from scratch takes a lot of time
        raise FileNotFoundError(f'The filepath {filepath} was not found')

    data: Dict[str, Dict] = FILEBASE_API.load_data_from_json(filepath)
    buckets: List[str] = list(data.keys())
    cids: List[str] = []
    for _bucket in buckets:
        _pin_set: PinSetType = data[_bucket]  # type: ignore
        cids.extend(_pin_set["cids"])
    return list(set(cids))


def get_missing_cids(local_filepath: str, filebase_filepath: str) -> set[str]:
    """
    Compares the pinsets of a local node and a Filebase node, and returns the set of CIDs
    that are missing in the local node but present in the Filebase node.

    Args:
        local_filepath (str): The file path to the local node's pinset.
        filebase_filepath (str): The file path to the Filebase node's pinset.

    Returns:
        set[str]: A set of CIDs that are present in the Filebase node but missing in the local node.
    """
    local_cids: List[str] = get_local_node_pins(filepath=local_filepath)
    filebase_cids: List[str] = get_filebase_pins(filepath=filebase_filepath)
    logger.info(
        "The local pinset has %d cids, we have found %d in filebase.",
        len(local_cids), len(filebase_cids))
    missing_cids: set[str] = set(filebase_cids) - set(local_cids)
    filebase_missing_cids = set(local_cids) - set(filebase_cids)
    logger.info(
        "There are %d missing CIDs in the local node", len(missing_cids))
    if len(filebase_missing_cids) > 0:
        logger.error("Missing CIDs in filebase: %d", len(filebase_missing_cids))
        for cid in filebase_missing_cids:
            logger.error("Filebase is missing CID: %s", cid)
    return missing_cids

def main(local_node_pin_filepath: str, filebase_pins_filepath: str):
    logger.info("Backup started ----------------")
    logger.info("Updating local node pin ls")
    # recursive pins is enough to get all the pins
    RPC.pin_ls(filepath=local_node_pin_filepath,
               pin_type=PinType.RECURSIVE)

    # update Filebase pinset
    logger.info("Updating Filebase pin ls")
    for bucket in BUCKETS:
        # there is no need to get the output, we are going to read from the
        # filepath stored in the filepath
        FILEBASE_API.get_all_cids(
            bucket_name=bucket, filepath=filebase_pins_filepath)

    logger.info("Checking Missing CIDs")
    missed_cids: set[str] = get_missing_cids(local_filepath=local_node_pin_filepath,
                                            filebase_filepath=filebase_pins_filepath)

    # Add missed CIDs into local IPFS node
    n_missed_cids = len(missed_cids)
    for index, missed_cid in enumerate(missed_cids):
        logger.info("Progress: %.2f%%", index/n_missed_cids*100)
        try:
            RPC.pin_add(cid=missed_cid, timeout=2)
            logger.info("%s added to local ipfs node", missed_cid)
        except ReadTimeout:
            logger.warning("Error while trying to pin, timeout error, most probably we don't have as peer filebase nodes. "
                        "CID %s will be skipped", missed_cid)
        except Exception as e:
            logger.info("Unknown exception for cid %s", missed_cid)
            logger.info("%s", e)
    logger.info("All missed CIDs were processed")
    logger.info("Backup finished ----------------")
   

if __name__ == "__main__":
    local_node_pin_filepath: str = './local_node_pins.json'
    filebase_pins_filepath: str = './filebase_pins.json'
    
    try:
        try:
            main(local_node_pin_filepath, filebase_pins_filepath)
        except ReadTimeout as e:
            logger.warning("Backup timed out, retrying once: %s", e)
            main(local_node_pin_filepath, filebase_pins_filepath)
        if betterstack_heartbeat_url:
            try:
                requests.get(betterstack_heartbeat_url, timeout=10)
            except Exception as heartbeat_err:
                logger.error("Failed to send BetterStack heartbeat: %s", heartbeat_err)
    except Exception as e:
        logger.error("Error while running backup: %s", e)
        raise e

   

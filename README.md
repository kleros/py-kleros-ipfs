# py-kleros-ipfs

Python tools to interact with the different IPFS nodes managed by Kleros. This tools are useful to get/list/add files to
filebase or own ipfs nodes.

# How to use

In this repository there are some useful tools that can be used to interact with the Filebase Pinning service and with a IPFS node through the RPC API.

## Filebase Backup

The main objective for this repo is to have the required tools to get the list of all the CIDs stored in filebase and pinning them into a local node, so we can have a backup of all the files stored in filebase.

`backup_filebase_locally.py` is the script build for that purpose. This script will:

> this script is meant to be run in a server running a IPFS node that expose the RPC in the port 5001. Please, don't expose this port to the internet.

1. Checks the current CIDs pinned that are in the local IPFS node (`127.0.0.1:5001`) and store the information in a local file
2. Update the CIDs pinned into all the filebase buckets (please, for the first time run first the script `get_filebase_cids` because will take several minutes/hours to be created the first time).
3. Compare both lists, and check if there are missed CIDs in the local node. For each missed CID, tries to pin them to store a local copy.

## Update Filebase

This script is similar to filebase backup but in the opposite. Was used in the early days to migrate all the CIDs stored in the old ipfs cluster to filebase. This will check if there are missing CIDs in filebase and try to pin them to the `kleros` bucket.

## Metadata Checker

This is a useful script that was built to check the metadata stored in filebase for a specific CID. From this information you can get what delegate has pinned the file. Please, compare with the list of DELEGATES in `FilebasePinAPI` to check if there are missing delegates in the list. If this is true, also you will need to add the peer to the IPFS node (add them to the IPFs config file to keep a permanent connection with that peer).

## Delete Filebase CIDs

`delete_filebase_cids.py` deletes one or more CIDs from Filebase buckets by CID, idempotently. Unlike `delete_poh_user_data.py`'s Filebase step, it looks up pin requests in every status (not just `pinned`), deletes every request it finds, and re-checks (up to a few rounds) until the CID is confirmed gone. Transient errors (connection issues, 429/5xx) are retried with backoff; other errors are recorded per item and processing continues with the rest.

```
python delete_filebase_cids.py QmFoo QmBar
python delete_filebase_cids.py --dry-run --bucket kleros QmFoo
```

stdout carries a single JSON report (`{"ok", "dry_run", "results"}`); logs go to stderr and to a file under `LOG_FILEPATH`.

Exit codes: `0` everything verified absent (or, in `--dry-run`, every lookup succeeded); `1` setup failure (e.g. a missing `FILEBASE_TOKEN_*`); `2` something is not verified absent or a per-item error occurred.

## APIs

There are 2 APIs created in this repo (`KuboRPCAPI` and `FilebasePinApi`). This classes are meant to interact with a local Kubo RPC api and with the Filebase Pinning Service API. Those are helpers with what we need at this moment, is not meant to be a very extensive client for both services, just the minimum and necesary to backup files from filebase to local node and viceversa.

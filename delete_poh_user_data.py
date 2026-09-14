"""
Delete a PoH user's personal data from Filebase and report every CID that must
be unpinned from the IPFS backup nodes.

Media is resolved through the Proof of Humanity **v2** subgraph, which also
indexes legacy v1 registrations (they show up as requests with a negative
index). The standalone v1 subgraph is gone: its Studio deployment was
undeployed and its decentralized deployment has no indexer allocations.

A profile can hold SEVERAL registrations, and each one points at its own set of
files, so every request is traversed and the resulting CIDs are de-duplicated.
Only looking at the most recent request leaves the older registration's media
pinned forever.

Personal data lives in three places per registration:
    file.json   name, firstName, lastName, bio, and the media pointers
    photo       profile picture
    video       verification video

The evidence `registration.json` is deliberately KEPT: it carries no personal
data (its `name` field is the Kleros evidence title, literally "Registration")
and keeping it preserves the audit trail that a registration happened.

Output contract:
    stdout  one CID per line, nothing else - safe to consume from automation
    stderr  human readable progress and diagnostics

Exit codes:
    0  every registration resolved, requested work completed
    1  hard failure - invalid address, subgraph error, or no profile data
    2  partial - some evidence could not be resolved, see the warnings

Usage:
    python delete_poh_user_data.py 0x<address> --dry-run
    python delete_poh_user_data.py 0x<address>
"""
import argparse
import logging
import os
import sys
from logging import Logger

import requests
from dotenv import load_dotenv

from filebase_datatypes import GetPinsResponse
from filebase_pin_api import FilebasePinAPI
from logger import setup_logger

load_dotenv()

# Proof of Humanity v2 core subgraph. Mainnet holds the legacy v1 registrations.
# `or` instead of an os.getenv default: copying .env.example leaves the key
# present-and-empty, and an empty value would build a URL with no subgraph id.
POH_SUBGRAPH_ID: str = os.getenv(
    'POH_SUBGRAPH_ID') or '8oHw9qNXdeCT2Dt4QPZK9qHZNAhPWNVrCKnFDarYEJF5'
GRAPH_API_KEY: str = os.getenv('GRAPH_API_KEY', '')
POH_SUBGRAPH_URL: str = f'https://gateway.thegraph.com/api/subgraphs/id/{POH_SUBGRAPH_ID}'

CDN_BASE_URL: str = 'https://cdn.kleros.link'
BUCKET_NAMES: list[str] = ['kleros', 'poh-v2']
HTTP_TIMEOUT: int = 20

PROFILE_MEDIA_QUERY: str = """
    query ProfileMedia($id: ID!) {
      humanity(id: $id) {
        id
        nbRequests
        nbLegacyRequests
        requests(orderBy: creationTime, orderDirection: desc) {
          index
          evidenceGroup {
            evidence(orderBy: creationTime, first: 1) {
              uri
            }
          }
        }
      }
    }
"""

log_path: str = os.getenv('LOG_FILEPATH', '/var/log/py-kleros-ipfs')
log_filepath: str = os.path.join(log_path, 'delete_poh_user_data.log')

logger: Logger = setup_logger('delete_poh_user_data', log_filepath)

# The shared logger streams to stdout, which would corrupt the CID contract.
# Keep the file handler untouched and move console output to stderr.
for _handler in logger.handlers:
    if type(_handler) is logging.StreamHandler:
        _handler.setStream(sys.stderr)


class SubgraphError(RuntimeError):
    """The subgraph could not be reached or answered with an error."""


def query_subgraph(profile_id: str) -> dict:
    """
    Ask the PoH v2 subgraph for a humanity and all of its requests.

    Raises
    ------
    SubgraphError
        If the key is missing, the request fails, or the subgraph answers with
        GraphQL errors. This must never be confused with "profile has no data".
    """
    if not GRAPH_API_KEY:
        raise SubgraphError(
            'GRAPH_API_KEY is not set. The Graph gateway rejects unauthenticated queries.')

    try:
        response = requests.post(
            POH_SUBGRAPH_URL,
            json={'query': PROFILE_MEDIA_QUERY,
                  'variables': {'id': profile_id.lower()}},
            headers={'Authorization': f'Bearer {GRAPH_API_KEY}'},
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as error:
        raise SubgraphError(f'Subgraph request failed: {error}') from error

    try:
        payload = response.json()
    except ValueError as error:
        raise SubgraphError(
            f'Subgraph returned a non-JSON body (HTTP {response.status_code})') from error

    if 'errors' in payload:
        raise SubgraphError(f"Subgraph returned errors: {payload['errors']}")

    return payload.get('data') or {}


def get_evidence_uris(profile_id: str) -> list[str]:
    """
    Return the evidence URI of every registration request of a profile.

    An empty list means the profile genuinely has no registration on record.
    A dead subgraph raises instead, so the two cases stay distinguishable.
    """
    humanity = query_subgraph(profile_id).get('humanity')

    if not humanity:
        logger.info(f'No humanity found for profile {profile_id}')
        return []

    logger.info(
        f"Profile {humanity['id']} has {humanity['nbRequests']} v2 request(s) "
        f"and {humanity['nbLegacyRequests']} legacy v1 request(s)")

    uris: list[str] = []
    for request in humanity.get('requests') or []:
        evidences = (request.get('evidenceGroup') or {}).get('evidence') or []
        if not evidences:
            logger.warning(
                f"Request index {request['index']} has no evidence attached")
            continue
        uris.append(evidences[0]['uri'])

    return uris


def fetch_json(uri: str) -> dict | None:
    """Fetch a `/ipfs/...` URI through the Kleros CDN and parse it as JSON."""
    try:
        response = requests.get(f'{CDN_BASE_URL}{uri}', timeout=HTTP_TIMEOUT)
    except requests.RequestException as error:
        logger.error(f'Error fetching {uri}: {error}')
        return None

    if not response.ok:
        logger.error(f'Failed to fetch {uri}. Status {response.status_code}')
        return None

    try:
        return response.json()
    except ValueError:
        logger.error(f'{uri} is not valid JSON')
        return None


def get_cid_from_uri(uri: str) -> str:
    """
    Extract the CID from an IPFS pointer.

    Accepts every shape the registrations are known to store, because a pointer
    this function fails to parse is silently skipped by the caller and its file
    stays pinned forever:
        /ipfs/<cid>/<filename>
        ipfs://<cid>/<filename>
        https://<gateway>/ipfs/<cid>/<filename>

    Reads the segment after the `ipfs` marker wherever it sits, so CIDv0 and
    CIDv1 both work without pattern matching on the `Qm` prefix.
    """
    if not uri:
        return ''
    parts = [part for part in uri.split('/') if part and part != 'ipfs:']
    if parts and parts[0].endswith(':'):
        parts = parts[1:]
    if 'ipfs' in parts:
        marker = parts.index('ipfs')
        return parts[marker + 1] if marker + 1 < len(parts) else ''
    return parts[0] if parts else ''


def resolve_personal_data_cids(evidence_uris: list[str]) -> tuple[dict[str, str], list[str]]:
    """
    Walk every registration and collect the CIDs that hold personal data.

    Returns
    -------
    tuple[dict[str, str], list[str]]
        An insertion-ordered ``{cid: label}`` mapping (already de-duplicated,
        since content addressing makes identical files share a CID across
        registrations), and the list of evidence URIs that could not be read.
    """
    cids: dict[str, str] = {}
    unresolved: list[str] = []

    for evidence_uri in evidence_uris:
        logger.info(f'Resolving registration {evidence_uri}')
        evidence = fetch_json(evidence_uri)
        if evidence is None:
            unresolved.append(evidence_uri)
            continue

        file_uri = evidence.get('fileURI')
        if not file_uri:
            logger.error(f'{evidence_uri} has no fileURI')
            unresolved.append(evidence_uri)
            continue

        registration = fetch_json(file_uri)
        if registration is None:
            unresolved.append(evidence_uri)
            continue

        # file.json itself holds name, firstName, lastName and bio.
        for label, uri in (('file', file_uri),
                           ('photo', registration.get('photo')),
                           ('video', registration.get('video'))):
            cid = get_cid_from_uri(uri or '')
            if not cid:
                logger.warning(f'No {label} CID in {file_uri}')
                continue
            cids.setdefault(cid, label)

    return cids, unresolved


def delete_from_filebase(cids: dict[str, str]) -> int:
    """
    Remove every CID from all PoH related Filebase buckets.

    Returns the number of unpin requests that the API rejected, so the caller
    can tell a complete deletion apart from a total deletion outage. A CID that
    is simply absent from a bucket is not a failure.
    """
    api = FilebasePinAPI(log_filepath)
    failures = 0

    for bucket_name in BUCKET_NAMES:
        logger.info(f'Processing bucket: {bucket_name}')
        for cid, label in cids.items():
            pin_info: GetPinsResponse = api.get_file(bucket_name, cid)
            # An absent CID answers {"count": 0, "results": []}, which is truthy:
            # only an empty `results` proves the CID is not in this bucket.
            if not pin_info or not pin_info.get('results'):
                logger.warning(
                    f'{label} CID {cid} not found in bucket {bucket_name}')
                continue

            request_id: str = pin_info['results'][0]['requestid']
            response: requests.Response = api.delete_pin(
                bucket_name, request_id)
            if not response.ok:
                failures += 1
            logger.info(
                f"Deletion of {label} CID {cid} from {bucket_name} "
                f"{'succeeded' if response.ok else 'failed'}")

    return failures


def parse_args() -> argparse.Namespace:
    """Parse the command line arguments."""
    parser = argparse.ArgumentParser(
        description='Delete a PoH profile personal data from Filebase and list the CIDs to unpin.')
    parser.add_argument(
        'profile_id', help='Ethereum address of the PoH profile')
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Resolve and print the CIDs without deleting anything')
    return parser.parse_args()


def main(profile_id: str, dry_run: bool = False) -> int:
    """
    Resolve a profile's personal data CIDs and, unless this is a dry run,
    delete them from Filebase. Returns the process exit code.
    """
    if not profile_id.startswith('0x') or len(profile_id) != 42:
        logger.error('Invalid Ethereum address format')
        return 1

    logger.info(f'Fetching media for profile ID: {profile_id}')

    try:
        evidence_uris = get_evidence_uris(profile_id)
    except SubgraphError as error:
        logger.error(str(error))
        return 1

    if not evidence_uris:
        logger.error('No registration found for this profile')
        return 1

    cids, unresolved = resolve_personal_data_cids(evidence_uris)

    if not cids:
        logger.error('No personal data CIDs could be resolved')
        return 1

    logger.info(
        f'Resolved {len(cids)} unique CID(s) across {len(evidence_uris)} registration(s)')
    for cid, label in cids.items():
        logger.info(f'  {label}: {cid}')

    failed_deletions = 0
    if dry_run:
        logger.info('Dry run - nothing was deleted')
    else:
        failed_deletions = delete_from_filebase(cids)

    # Machine readable contract: one CID per line on stdout, nothing else.
    for cid in cids:
        print(cid)

    if failed_deletions:
        logger.error(
            f'{failed_deletions} unpin request(s) were rejected by Filebase; '
            f'those files are still pinned')

    if unresolved:
        logger.warning(
            f'{len(unresolved)} registration(s) could not be resolved and may '
            f'still hold pinned data: {unresolved}')

    # Exit 0 must mean "everything the run set out to remove is gone".
    if failed_deletions or unresolved:
        return 2

    return 0


if __name__ == '__main__':
    args = parse_args()
    sys.exit(main(args.profile_id, args.dry_run))

"""
Script to delete PoH user data (profile picture and video) from Filebase using their profile ID.
"""
import os
from logging import Logger
import sys
from typing import Tuple
import requests
from filebase_datatypes import GetPinsResponse
from filebase_pin_api import FilebasePinAPI
from logger import setup_logger

# GraphQL endpoint for PoH subgraph
POH_SUBGRAPH_URL = "https://api.studio.thegraph.com/query/61738/proof-of-humanity-mainnet/version/latest"
log_path: str = os.getenv('LOG_FILEPATH', '/var/log/py-kleros-ipfs')
log_filepath: str = os.path.join(log_path, 'delete_poh_user_data.log')


logger: Logger = setup_logger(log_filepath)


def get_profile_media(profile_id: str) -> tuple[None, None] | tuple[str, str]:
    """
    Query the PoH subgraph to get profile picture and video CIDs
    """
    query = """
        query IdQuery($id: ID!)        {
        submission(id: $id) {
          name
          status
          registered
          submissionTime
          disputed
          requests(orderBy: creationTime, orderDirection: desc, first: 1, where: {registration: true}) {
            evidence(orderBy: creationTime, first: 1) {
                URI
                id
            }
          }
        }
        }
    """

    variables = {"id": profile_id.lower()}

    try:
        response = requests.post(
            POH_SUBGRAPH_URL,
            json={'query': query, 'variables': variables},
            timeout=10
        )
        data = response.json()

        if 'errors' in data:
            logger.info(f"Error querying subgraph: {data['errors']}")
            return None, None

        submission = data.get('data', {}).get('submission')

        if not submission or not submission['requests']:
            logger.info(f"No profile found with ID: {profile_id}")
            return None, None

        evidence = submission['requests'][0]['evidence'][0]
        registration = get_data_from_registration(evidence['URI'])
        if not registration:
            logger.info("Failed to fetch registration data")
            return None, None

        return registration.get('photo'), registration.get('video')

    except Exception as e:
        logger.info(f"Error: {e}")
        return None, None


def get_data_from_registration(registration_uri: str) -> dict | None:
    """
    Fetch and parse the registration data from the given URI.
    """
    logger.info(f"Fetching registration data from {registration_uri}")
    try:
        response = requests.get(
            f'https://cdn.kleros.link{registration_uri}', timeout=10)
        if response.status_code == 200:
            fileURI = response.json().get('fileURI')
            try:
                response = requests.get(
                    f'https://cdn.kleros.link{fileURI}', timeout=10)
                if response.status_code == 200:
                    return response.json()

                logger.error(
                    f"Failed to fetch file data. Status code: {response.status_code}")
                return None
            except Exception as e:
                logger.error(f"Error fetching file data: {e}")
                return None
        logger.error(
            f"Failed to fetch registration data. Status code: {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Error fetching registration data: {e}")
        return None


def main(profile_id: str) -> Tuple[str | None, str | None]:
    """
     Main entry point for the script. Validates the Ethereum address format,
     fetches media CIDs for the given profile ID, and deletes the corresponding
     files from Filebase.

     Parameters
     ----------
     profile_id : str
         The Ethereum address of the user profile to delete media from.

     Returns
     -------
     Tuple[str, str] | Tuple[None, None]
         A tuple containing the CIDs of the deleted photo and video files.
         If no media files are found, returns (None, None).
     """

    if not profile_id.startswith('0x') or len(profile_id) != 42:
        logger.error("Invalid Ethereum address format")
        sys.exit(1)

    # Get media CIDs
    logger.info(f"Fetching media for profile ID: {profile_id}")
    photo_cid, video_cid = get_profile_media(profile_id)

    if not photo_cid and not video_cid:
        logger.info("No media files found for this profile")
        sys.exit(1)
    logger.info(
        f"Found media CIDs - Photo: {photo_cid}, Video: {video_cid}")
    # Delete files from Filebase
    api = FilebasePinAPI(log_filepath)
    bucket_names = ["kleros", "poh-v2"]

    for bucket_name in bucket_names:
        logger.info(f"Processing bucket: {bucket_name}")
        if photo_cid:
            photo_info: GetPinsResponse = api.get_file(
                bucket_name, get_cid_from_uri(photo_cid))
            if photo_info:
                logger.info(f"Deleting photo with CID: {photo_cid}")
                request_id: str = photo_info['results'][0]['requestid']
                res: requests.Response = api.delete_pin(
                    bucket_name, request_id)
                logger.info(
                    f"Photo deletion {'successful' if res.ok else 'failed'}")
            else:
                logger.warning("Photo CID not found in Filebase")

        else:
            logger.warning("Photo CID not found in Filebase")

        if video_cid:
            video_info: GetPinsResponse = api.get_file(
                bucket_name, get_cid_from_uri(video_cid))
            if video_info:
                logger.info(f"Deleting video with CID: {video_cid}")
                request_id: str = video_info['results'][0]['requestid']

                res: requests.Response = api.delete_pin(
                    bucket_name, request_id)
                logger.info(
                    f"Video deletion {'successful' if res.ok else 'failed'}")
            else:
                logger.warning("Video CID not found in Filebase")

        else:
            logger.warning("Video CID not found in Filebase")
    return (photo_cid, video_cid)


def get_cid_from_uri(uri: str) -> str:
    """
    Extract CID from a given URI.
    """
    if not uri:
        return ''
    parts = uri.split('/')
    for part in parts:
        if len(part) == 46 and part.startswith('Qm'):
            return part
    return ''


if __name__ == "__main__":
    # Get profile ID from user
    profile: str = input(
        "Enter the PoH profile ID (Ethereum address): ").strip()
    photo_cid, video_cid = main(profile)
    # Send to STDOUT to be used by ansible or other scripts
    print(photo_cid, video_cid)

"""
This file contains functions to interact with the Filebase IPFS API.
Is a wrapper to call the different methods in that api.
Docs:
https://docs.filebase.com/api-documentation/ipfs-pinning-service-api#what-is-the-ipfs-pinning-service-api
"""

import os
from datetime import datetime, timedelta, timezone
import copy
import json
import logging
from typing import Dict, List, Literal, Optional

from dotenv import load_dotenv
import requests

from filebase_datatypes import GetPinsResponse, PinSetType, PinStatus
from logger import setup_logger

# Load environment variables from .env file
load_dotenv()

# Define constants
PIN_API_URL = "https://api.filebase.io/v1/ipfs/pins"
DATE_STR_FORMAT_API = "%Y-%m-%dT%H:%M:%S.%f%z"
# Kleros IPFS addresses
# TODO: Check if the addresses are still valid
ORIGINS: List[str] = [
    "/ip4/18.119.89.142/tcp/4001/p2p/12D3KooWLzbCzkFdKFkRS5scAuezSTyBePUExBXD6qH2t4B9zPKe",
    "/ip4/18.119.89.142/udp/4001/quic/p2p/12D3KooWLzbCzkFdKFkRS5scAuezSTyBePUExBXD6qH2t4B9zPKe",
    "/ip4/3.141.144.87/tcp/4001/p2p/12D3KooWHhLwvVxSkoTGW8WUGqGJxWByojzHTo59UXQpVMpNdjHA",
    "/ip4/3.141.144.87/udp/4001/quic/p2p/12D3KooWHhLwvVxSkoTGW8WUGqGJxWByojzHTo59UXQpVMpNdjHA",
    "/ip4/194.182.164.22/tcp/4001/p2p/12D3KooWLf6HJNdv1vcYyxLJJ6EUVH9VqLheYAHufSeK54jszvQe",
    "/ip4/194.182.164.22/udp/4001/quic/p2p/12D3KooWLf6HJNdv1vcYyxLJJ6EUVH9VqLheYAHufSeK54jszvQe",
]
# Filebase IPFS nodes addresses.
DELEGATES: List[str] = [
    "/dns4/ipfs-pin-0.vin1.filebase.io/tcp/4001/p2p/12D3KooWNvyc1NoeTF6SynHuq5exmsMs7YyE1UFp9YhsiYw2px9B",
    "/dns4/ipfs-pin-1.vin1.filebase.io/tcp/4001/p2p/12D3KooWC8RkG22G2Jp7wdBtMDxG4LLn6d3sDfqtqXBytpyNhXTM",
    "/dns4/ipfs-pin-2.vin1.filebase.io/tcp/4001/p2p/12D3KooW9x6zfqWH46VYQoFDdfPuQqoc56L359NM6pQedrSHrv6R"
]


class FilebasePinAPI():
    """
    Class to interact with the Filebase Pinning Service API.
    https://docs.filebase.com/api-documentation/ipfs-pinning-service-api
    """

    def __init__(self, log_filepath: str = "filebasePinAPI.log", log_level: int = logging.INFO) -> None:
        """
        Initialize the FilebasePinAPI class.

        Args:
            log_filepath (str, optional): Path to the log file. Defaults to "filebasePinAPI.log".
            log_level (int, optional): Log level for the self.logger. Defaults to logging.INFO.
        """
        self.logger: logging.Logger = setup_logger(
            self.__class__.__name__, log_filepath, level=log_level)

    @staticmethod
    def get_token(bucket_name: str) -> str:
        """
        Get the Filebase API token for a specific bucket from environment variables.

        Args:
            bucket_name (str): The name of the bucket to get the token for.

        Returns:
            str: The Filebase API token.

        Raises:
            ValueError: If the token is not defined for the specified bucket.
        """
        token: str | None = os.getenv(
            f"FILEBASE_TOKEN_{bucket_name.upper().replace('-', '_')}", None)
        if token is None:
            raise ValueError(f"Token not defined for bucket {bucket_name}")
        return token

    def _append_to_pinset(
        self,
        pin_set: PinSetType,
        new_items: GetPinsResponse
    ) -> PinSetType:
        """
        Appends new items to the pin set and updates the metadata.

        Args:
            pin_set (PinSetType): The current pin set containing CIDs and metadata.
            new_items (GetPinsResponse): The new items to be added to the pin set.

        Returns:
            PinSetType: The updated pin set with new items and updated metadata.

        The function performs the following steps:
        1. Extends the list of CIDs in the pin set with new CIDs from the new items.
        2. Removes duplicate CIDs.
        3. Updates the count of CIDs in the pin set.
        4. Updates the first and last date of the CID list based on the new items.
        """
        pin_set["cids"].extend([item["pin"]["cid"]
                                for item in new_items["results"]])

        unique_cids = list(set(pin_set["cids"]))
        if len(pin_set["cids"]) > len(unique_cids):
            self.logger.info("Some duplicated CIDs were found, %s items duplicated items removed",
                             len(pin_set["cids"]) - len(unique_cids))
        pin_set["cids"] = unique_cids
        pin_set["count"] = len(pin_set["cids"])
        old_last_date: datetime = pin_set["last_date"]
        old_first_date: datetime = pin_set["first_date"]
        if len(new_items["results"]) > 0:
            # Update the first and last date of the CID list
            dates_str: List[str] = [item["created"]
                                    for item in new_items["results"]]
            first_date_str: str = min(dates_str)
            last_date_str: str = max(dates_str)
            last_date: datetime = datetime.strptime(
                last_date_str, DATE_STR_FORMAT_API).astimezone(tz=timezone.utc)
            first_date: datetime = datetime.strptime(
                first_date_str, DATE_STR_FORMAT_API).astimezone(tz=timezone.utc)
            self.logger.debug("Dates from the API response: First date: %s, Last date: %s",
                              first_date, last_date)
            if last_date > old_last_date:
                pin_set["last_date"] = last_date
            if first_date < old_first_date:
                pin_set["first_date"] = first_date
        return pin_set

    def _loop_get_list(  # pylint: disable=too-many-arguments
        self,
        pin_set: PinSetType,
        bucket_name: str,
        after_before_key: Literal["after", "before"],
        date: datetime,
        filepath: str,
        limit: int = 1000,
    ) -> PinSetType:
        """
        Continuously retrieves and appends pin data to the given pin set until the result count
        is less than or equal to the limit.

        Args:
            pin_set (PinSetType): The initial set of pins to which new data will be appended.
            bucket_name (str): The name of the bucket from which to retrieve pin data.
            after_before_key (Literal["after", "before"]): Determines whether to retrieve data after
                or before the given date.
            date (datetime): The reference date for retrieving pin data.
            limit (int, optional): The maximum number of items to retrieve in each API call. Defaults to 2000.

        Returns:
            PinSetType: The updated pin set with appended data.
        """
        before: None | datetime = None if after_before_key == "after" else date
        after: None | datetime = None if after_before_key == "before" else date
        keep_looping: bool = True
        old_result_count: int = 0
        while keep_looping:
            self.logger.debug(
                "Looping getlist for bucket %s, before: %s and after %s", bucket_name, before, after)
            # if after is a very old date, we are going to receive the last items created,
            # because the API returns the items in descending order
            # That's why first we get the last items, and then we get the items before the last date
            temp: GetPinsResponse = self.get_list(
                bucket_name=bucket_name,
                before=before,
                after=after,
                limit=limit
            )
            result_count = temp["count"]
            if old_result_count == 0:
                # Assigning result_count left + amount of data received
                old_result_count = result_count + len(temp["results"])
            if old_result_count - limit > result_count:
                self.logger.warning(
                    ("Seems that we have lost some CIDs in the loop, modifing after and before time and retrying"
                        "Old Count: %s, New Count: %s, limit: %s"),
                    old_result_count, result_count, limit)
                if before:
                    before += timedelta(seconds=2)
                if after:
                    after -= timedelta(seconds=2)
                continue
            # update the value for the next check
            old_result_count = result_count

            pin_set = self._append_to_pinset(pin_set=pin_set, new_items=temp)
            self.logger.debug(
                "Local PinSet count: %d, Reponse items count: %d, Response count left: %d",
                pin_set['count'], len(temp['results']), temp['count']
            )

            # Check logic to stop the loop
            if len(temp["results"]) == 0:
                keep_looping = False
                # there is nothing to do
                break
            if result_count <= limit:
                keep_looping = False
                self.logger.info(
                    "Result count is less than the limit or the response is empty."
                    " Breaking the loop, we got all the CIDs")

            # update the date to after/before with the date in the new items
            if after_before_key == "after":
                after = pin_set["last_date"]
            else:
                before = pin_set["first_date"]
            FilebasePinAPI.save_pinset_to_json(
                pin_set=pin_set, bucket_name=bucket_name, filepath=filepath)

        return pin_set

    @staticmethod
    def load_data_from_json(filepath) -> Dict[str, Dict]:
        """
        Load data from a JSON file.

        Args:
            filepath (str): Path to the JSON file.

        Returns:
            dict: The loaded JSON data.
        """
        with open(filepath, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data

    @staticmethod
    def save_data_to_json(data: Dict[str, PinSetType], filepath: str) -> None:
        """
        Save data to a JSON file.

        Args:
            data (dict): Data to save.
            filepath (str): Path where the JSON file will be saved.
        """
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

    @staticmethod
    def load_pinset_from_json(filepath: str, bucket_name: str) -> PinSetType:
        """
        Load pin set data for a specific bucket from a JSON file.

        Args:
            filepath (str): Path to the JSON file.
            bucket_name (str): Name of the bucket.

        Returns:
            dict: Pin set data with count, CIDs and last_date.
        """
        try:
            data: Dict[str, Dict] = FilebasePinAPI.load_data_from_json(
                filepath)
            pin_set: PinSetType = {
                "cids": data[bucket_name]["cids"],
                "count": data[bucket_name]["count"],
                "last_date": datetime.strptime(data[bucket_name]["last_date"], DATE_STR_FORMAT_API),
                "first_date": datetime.strptime(data[bucket_name]["first_date"], DATE_STR_FORMAT_API),
            }
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pin_set: PinSetType = {
                "count": 0,
                "cids": [],
                "last_date": datetime(2021, 1, 1, tzinfo=timezone.utc),
                "first_date": datetime(2021, 1, 1, tzinfo=timezone.utc)
            }
        return pin_set

    @staticmethod
    def save_pinset_to_json(pin_set: PinSetType, bucket_name: str, filepath: str) -> None:
        """
        Save pin set data to a JSON file.

        Args:
            pin_set (dict): Pin set data to save.
            bucket_name (str): Name of the bucket.
            filepath (str): Path where the JSON file will be saved.
        """
        # load saved data to replace new pinset from the specified bucket
        # a copy is needed to not change the date datatypes in the original pinset
        pin_set_copy: PinSetType = copy.deepcopy(pin_set)
        try:
            saved_data: Dict = FilebasePinAPI.load_data_from_json(filepath)
        except FileNotFoundError:
            saved_data: Dict = {}
        if isinstance(pin_set_copy["last_date"], datetime):
            # ignore datetime type to make it serializable for json
            pin_set_copy["last_date"] = pin_set_copy["last_date"].strftime(  # type: ignore
                DATE_STR_FORMAT_API)
        if isinstance(pin_set_copy["first_date"], datetime):
            # ignore datetime type to make it serializable for json
            pin_set_copy["first_date"] = pin_set_copy["first_date"].strftime(  # type: ignore
                DATE_STR_FORMAT_API)
        # Removing duplicates, just in case, should have duplicates
        pin_set_copy["cids"] = list(set(pin_set_copy["cids"]))
        saved_data[bucket_name] = pin_set_copy
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(saved_data, file, indent=2)

    def get_all_cids(self, bucket_name: str, filepath: str = "pin_set.json") -> List[str]:
        """
        Get a all the CIDs from a bucket and save them to a JSON file in filepath.
        If in the json file there is already some CIDs, function starts from there

        Args:
            bucket_name (str): Name of the bucket.
            filepath (str, optional): Path to the JSON file for storing pin data. Defaults to "pin_set.json".

        Returns:
            list: List of CIDs matching the filter criteria.
        """

        self.logger.info("-"*80)
        self.logger.info("Getting all CIDs from bucket %s", bucket_name)

        # Get existing data if any
        pin_set: PinSetType = FilebasePinAPI.load_pinset_from_json(
            filepath, bucket_name)
        self.logger.debug(
            "Loaded pin set from file with %d CIDs", pin_set['count'])
        if pin_set["count"] == 0:
            # If it's the first time, we need to get proper values for the dates
            temp: GetPinsResponse = self.get_list(
                bucket_name=bucket_name,
                before=None,
                after=pin_set["last_date"],
                limit=1
            )
            date_str: str = temp["results"][0]["created"]
            pin_set["first_date"] = datetime.strptime(
                date_str, DATE_STR_FORMAT_API).astimezone(tz=timezone.utc)
            # This -1 second is to guarantee that we are going to read the recovered file in the after loop
            pin_set["last_date"] = datetime.strptime(
                date_str, DATE_STR_FORMAT_API).astimezone(tz=timezone.utc) - timedelta(seconds=1)
            self.logger.debug("Pinset dates updated to values: after: %s, before: %s",
                              pin_set["last_date"], pin_set["first_date"])

        # Define a very old date as the default initial date.
        before: datetime = pin_set["first_date"]
        after: datetime = pin_set["last_date"]
        # Loop for after
        pin_set = self._loop_get_list(pin_set=pin_set, bucket_name=bucket_name,
                                      after_before_key="after", date=after, filepath=filepath)

        # Loop for before
        pin_set = self._loop_get_list(pin_set=pin_set, bucket_name=bucket_name,
                                      after_before_key="before", date=before, filepath=filepath)

        return pin_set["cids"]

    def get_list(
            self,
            bucket_name: str,
            status: Optional[PinStatus] = None,
            before: Optional[datetime] = None,
            after: Optional[datetime] = None,
            limit: int = 10000) -> GetPinsResponse:
        """
        Retrieve a list of files from a specified bucket with optional filters. The list is returned as a JSON response
        sorted by creation date in descending order.

        Args:
            bucket_name (str): The name of the bucket to retrieve files from.
            status (str, optional): Filter files by status. Defaults to None.
            before (str, optional): Filter files created before this date. Defaults to None.
            after (str, optional): Filter files created after this date. Defaults to None.
            limit (int, optional): The maximum number of files to retrieve. Defaults to 10000.

        Returns:
            dict: A GetPinResponse containing the list of files and their details.
        """
        self.logger.info(
            "Getting list of files with status: %s, before: %s, after: %s from bucket %s with limit %s",
            status, before, after, bucket_name, limit
        )
        filebase_token: str = self.get_token(bucket_name)
        headers: dict[str, str] = {"Authorization": f"Bearer {filebase_token}"}
        _before = None
        _after = None
        if isinstance(after, datetime):
            _after = after.strftime(DATE_STR_FORMAT_API)
        if isinstance(before, datetime):
            _before = before.strftime(DATE_STR_FORMAT_API)
        params = {"status": status, "before": _before,
                  "after": _after, "limit": limit}

        res: requests.Response = requests.get(
            PIN_API_URL, headers=headers, params=params, timeout=10)
        res_json: GetPinsResponse = res.json()
        return res_json

    def get_file(self, bucket_name, cid) -> GetPinsResponse:
        """
        Get information about a specific CID from a bucket.

        Args:
            bucket_name (str): Name of the bucket.
            cid (str): The CID to query.

        Returns:
            dict: Response JSON containing file information.
        """
        token: str = self.get_token(bucket_name)
        headers = {"Authorization": f"Bearer {token}"}
        params = {"cid": cid}
        res = requests.get(PIN_API_URL, headers=headers,
                           params=params, timeout=10)
        res_json = res.json()
        return res_json

    def pin_cid(self, bucket_name: str, cid: str) -> None:
        """
        Pin a CID to a specified bucket.

        Args:
            bucket_name (str): Name of the bucket.
            cid (str): The CID to pin.
        """
        token: str = self.get_token(bucket_name)
        self.logger.info("Pinning CID: %s", cid)
        headers = {"Authorization": f"Bearer {token}"}
        data = {"cid": cid, "origins": ORIGINS}
        res = requests.post(PIN_API_URL, headers=headers,
                            json=data, timeout=10)
        if res.ok:
            for delegate in res.json().get("delegates", []):
                if delegate not in DELEGATES:
                    self.logger.warning(
                        "%s is not in DELEGATES, you should add it manually to the IPFS nodes!",
                        delegate
                    )

    def delete_pin(self, bucket_name: str, requestid: str) -> requests.Response:
        """
        Delete a pin request from a bucket.

        Args:
            bucket_name (str): Name of the bucket.
            requestid (str): ID of the pin request to delete.

        Returns:
            Response: The API response from the delete request.
        """
        token: str = self.get_token(bucket_name)
        headers = {"Authorization": f"Bearer {token}"}
        res: requests.Response = requests.delete(
            f"{PIN_API_URL}/{requestid}", headers=headers, timeout=10)
        return res

    def replace_pin(self, bucket_name: str, requestid: str, cid: str) -> requests.Response:
        """
        Replace an existing pin with a new CID.

        Args:
            bucket_name (str): Name of the bucket.
            requestid (str): ID of the pin request to replace.
            cid (str): The new CID to pin.

        Returns:
            Response: The API response from the replace request.
        """
        self.logger.info("Replacing pin: %s", cid)
        token: str = self.get_token(bucket_name)
        headers = {"Authorization": f"Bearer {token}"}
        data = {"cid": cid, "origins": ORIGINS}
        res: requests.Response = requests.post(
            f"{PIN_API_URL}/{requestid}", headers=headers, json=data, timeout=10)
        return res

    def check_if_cid_exist(self, bucket_name: str, cid: str) -> bool:
        """
        Check if a CID exists in a bucket.

        Args:
            bucket_name (str): Name of the bucket.
            cid (str): The CID to check.

        Returns:
            bool: True if the file exists, False otherwise.
        """
        res: GetPinsResponse = self.get_file(bucket_name, cid)
        return res["count"] > 0

    def replace_failed(self, bucket_name: str) -> None:
        """
        Replace all failed pin requests in a bucket.

        Args:
            bucket_name (str): Name of the bucket.
        """
        failed_cids: GetPinsResponse = self.get_list(
            bucket_name, PinStatus.FAILED)
        if failed_cids["results"]:
            items = [
                {"cid": item["pin"]["cid"], "requestId": item["requestid"]}
                for item in failed_cids["results"]
            ]
            for item in items:
                try:
                    self.replace_pin(
                        bucket_name, item["requestId"], item["cid"])
                    self.logger.info("Pin replaced for cid: %s", item["cid"])
                except requests.exceptions.RequestException as e:
                    self.logger.error("Error re-pinning CID: %s", item["cid"])
                    self.logger.error(e)

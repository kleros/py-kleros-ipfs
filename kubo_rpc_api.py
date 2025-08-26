"""
Helper functions to interact with the outputs from the ipfs cli
"""
import json
from typing import List
import logging

import requests

from kubo_datatypes import IdResponse, PinAddResponse, PinLsResponse, PinType
from logger import setup_logger


TIMEOUT: int = 10  # timeout allowed for requests in seconds


class KuboRPC():
    """
    Class to interact with a Kubo RPC (IPFS) node
    """

    def __init__(
            self,
            api_url: str = "http://127.0.0.1:5001/api/v0",
            log_filepath: str = "/var/log/py-kleros-ipfs/filebasePinAPI.log",
            log_level: int = logging.INFO
    ) -> None:
        self.api_url: str = api_url
        self.logger = setup_logger(
            name=self.__class__.__name__, log_file=log_filepath, level=log_level)

    def pin_add(self, cid: str, timeout: int = TIMEOUT) -> PinAddResponse:
        """
        Pin objects to local storage.
        https://docs.ipfs.tech/reference/kubo/rpc/#api-v0-pin-add
        """
        url: str = self.api_url + "/pin/add"
        self.logger.debug("Pinning CID %s", cid)
        res: requests.Response = requests.post(url, params={
            "arg": cid,

        }, timeout=timeout)
        if res.ok:
            self.logger.info("CID %s pinned successfully", cid)
        return res.json()

    def cat(self, cid: str) -> requests.Response:
        """
        Show IPFS data from a CID
        https://docs.ipfs.tech/reference/kubo/rpc/#api-v0-cat

        The response could be a whatever the file is, so we are returning
        the response and the user should do what is needed (json, text, or anything)
        """
        url: str = self.api_url + "/cat"
        return requests.post(url, params={
            "arg": cid,
            "progress": True
        }, timeout=TIMEOUT)

    def get(self, cid: str, filepath: str) -> requests.Response:
        """
        Download a CID and store it in filepath
        https://docs.ipfs.tech/reference/kubo/rpc/#api-v0-get

        The response could be a whatever the file is, so we are returning
        the response and the user should do what is needed (json, text, or anything)
        """
        url: str = self.api_url + "/get"
        return requests.post(url, params={
            "arg": cid,
            "progress": True,
            "output": filepath
        }, timeout=TIMEOUT)

    def id(self) -> IdResponse:
        """
        Show IPFS node id info.
        https://docs.ipfs.tech/reference/kubo/rpc/#api-v0-id
        """
        url: str = self.api_url + "/id"
        res: requests.Response = requests.post(url, timeout=TIMEOUT)
        return res.json()

    def pin_ls(
            self,
            pin_type: PinType = PinType.ALL,
            quiet: bool = False,
            filepath: str | None = None,
            timeout: int = 300
    ) -> PinLsResponse:
        """
        List objects pinned to local storage.
        https://docs.ipfs.tech/reference/kubo/rpc/#api-v0-pin-ls
        """
        self.logger.info(
            'Requesting pin/ls to the daemon for pin type %s', pin_type)
        url: str = self.api_url + "/pin/ls"
        res: requests.Response = requests.post(url, params={
            "type": pin_type.value,
            "quiet": quiet,
            "progress": True
        }, timeout=timeout)

        if res.ok:
            data: PinLsResponse = res.json()
            if filepath is not None:
                with open(filepath, "w", encoding="utf-8") as file:
                    json.dump(obj=data, fp=file, indent=4)
                self.logger.info(
                    'Pin ls output saved to %s', filepath)
            return data
        raise requests.RequestException(res.text)

    @staticmethod
    def read_pin_ls_output(filepath: str) -> List[str]:
        """
        Reads the `ipfs pin ls` output from a file and extracts unique CIDs.

        Args:
            filepath (str): The path to the file containing the pin status list.

        Returns:
            list: A list of unique CIDs extracted from the file.
        """
        # get cid from the output of ipfs-cluster-ctl pins status
        with open(filepath, "r", encoding="utf-8") as file:
            content: PinLsResponse = json.load(file)
            cids = list(set(content["Keys"].keys()))
        return cids

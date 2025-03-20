"""
Datetypes module for Filebase PIN API
"""

from datetime import datetime
from enum import Enum
from typing import TypedDict, List


class PinStatus(Enum):
    """
    An enumeration representing the status of a pin operation in Filebase.

    Attributes:
        FAILED (str): Indicates that the pin operation has failed.
        QUEUED (str): Indicates that the pin operation is queued and waiting to be processed.
        PINNING (str): Indicates that the pin operation is currently in progress.
        PINNED (str): Indicates that the pin operation has been successfully completed.
    """
    FAILED = "failed"
    QUEUED = "queued"
    PINNING = "pinning"
    PINNED = "pinned"


class PinSetType(TypedDict):
    """
    A type representing a pin set data structure.

    Attributes:
        count (int): The number of CIDs in the pin set.
        cids (List[str]): List of Content Identifiers (CIDs).
        last_date (Union[str, datetime]): The last update date of the pin set.
    """
    count: int
    cids: List[str]
    last_date: datetime
    first_date: datetime


class PinData(TypedDict):
    """
    A TypedDict representing the data structure for the pin value from PinResult.

    Attributes:
        cid (str): The content identifier (CID) of the data.
        name (str): The name associated with the pinned data.
        origins (List[str]): A list of origins where the data can be found.
        meta (dict): A dictionary containing metadata related to the pinned data.
    """
    cid: str
    name: str
    origins: List[str]
    meta: dict


class PinResult(TypedDict):
    """
    Represents a single pin result from the Filebase API.
    """
    requestid: str
    status: PinStatus
    created: str
    pin: PinData
    delegates: List[str]


class GetPinsResponse(TypedDict):
    """
    Represents the response structure from the Filebase API pins endpoint.

    Attributes:
        count (int): Total number of pins in the response
        results (List[PinResult]): List of pin results
    """
    count: int
    results: List[PinResult]

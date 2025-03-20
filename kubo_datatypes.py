
"""
Datatypes defined for the KUBO RPC Api
More info in https://docs.ipfs.tech/reference/kubo/rpc
"""
from enum import Enum
from typing import List, TypedDict


class IdResponse(TypedDict):
    """
    Response from the /id endpoint
    """
    Addresses: List[str]
    AgentVersion: str
    ID: str
    Protocols: List[str]
    PublicKey: str


class PinAddResponse(TypedDict):
    """
    Response from the /pin/add endpoint
    """
    Pins: List[str]
    Progress: int


class PinLsObject(TypedDict):
    """
    Items in the array of CIDs that /pin/ls returns
    """
    Name: str
    Type: str


class PinLsResponse(TypedDict):
    """
    Response from the /pin/ls endpoint body
    According to the docs there is another object
    but during testing only this object was vound
    """
    Keys: dict[str, PinLsObject]


class PinType(Enum):
    """
    Datatype for the filter of Pin Time when listing pins
    """
    ALL = "all"
    DIRECT = "direct"
    INDIRECT = "indirect"
    RECURSIVE = "recursive"

"""
Check if a file is pinned in Filebase.
"""
import sys
from filebase_pin_api import FilebasePinAPI, GetPinsResponse


def main(cid: str, bucket_name: str) -> None:
    api = FilebasePinAPI('temp.log')
    file_info: GetPinsResponse = api.get_file(bucket_name, cid)
    print(file_info)
    if file_info and file_info['results']:
        print(f"CID {cid} is pinned in bucket {bucket_name}.")
    else:
        print(f"CID {cid} is NOT pinned in bucket {bucket_name}.")


if __name__ == "__main__":

    LOG_FILEPATH = "check_filebase_pinned.log"

    if len(sys.argv) < 2:
        print("Usage: python check_filebase_pinned.py <CID> <bucket_name>")
        sys.exit(1)

    cid = sys.argv[1]
    bucket_name = sys.argv[2] if len(sys.argv) > 2 else "kleros"
    main(cid, bucket_name)

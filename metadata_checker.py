
"""
Script to read the metadata of a pinned file in filebase.
Useful to get the delegates that are pinning this specific CID
"""
from dotenv import load_dotenv

from filebase_pin_api import FilebasePinAPI
import os

load_dotenv()
log_path: str = os.getenv('LOG_FILEPATH', '/var/log/py-kleros-ipfs')
log_filepath: str = os.path.join(log_path, 'metadata_checker.log')

filebase_api = FilebasePinAPI(log_filepath)
print(filebase_api.get_file(
    'kleros', 'QmVq2GstdkVQDNQFZMLGLFpVxwHR2abYyYgFZwh8GtkkWi'))

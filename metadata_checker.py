
"""
Script to read the metadata of a pinned file in filebase.
Useful to get the delegates that are pinning this specific CID
"""
from dotenv import load_dotenv

from filebase_pin_api import FilebasePinAPI

load_dotenv()

filebase_api = FilebasePinAPI('logs/metadata_checker.log')
print(filebase_api.get_file(
    'kleros', 'QmVq2GstdkVQDNQFZMLGLFpVxwHR2abYyYgFZwh8GtkkWi'))

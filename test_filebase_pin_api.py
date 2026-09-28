"""Tests for FilebasePinAPI.get_file error handling and status filtering."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("FILEBASE_TOKEN_KLEROS", "test-token")

from filebase_pin_api import FilebasePinAPI
from filebase_datatypes import PinStatus


class GetFileTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_filepath = os.path.join(self.tmpdir, "test.log")
        self.api = FilebasePinAPI(log_filepath=self.log_filepath)

    @patch("filebase_pin_api.requests.get")
    def test_get_file_raises_on_429(self, mock_get):
        response = MagicMock()
        response.status_code = 429
        response.json.return_value = {
            "error": {"reason": "TOO_MANY_REQUESTS", "details": "slow down"}}
        response.raise_for_status.side_effect = self._http_error(response)
        mock_get.return_value = response

        with self.assertRaises(Exception):
            self.api.get_file("kleros", "QmTest")

    @patch("filebase_pin_api.requests.get")
    def test_get_file_raises_on_401(self, mock_get):
        response = MagicMock()
        response.status_code = 401
        response.json.return_value = {
            "error": {"reason": "UNAUTHORIZED", "details": "bad token"}}
        response.raise_for_status.side_effect = self._http_error(response)
        mock_get.return_value = response

        with self.assertRaises(Exception):
            self.api.get_file("kleros", "QmTest")

    @patch("filebase_pin_api.requests.get")
    def test_get_file_passes_status_list_and_limit(self, mock_get):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"count": 0, "results": []}
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        self.api.get_file(
            "kleros", "QmTest",
            statuses=[PinStatus.QUEUED, PinStatus.PINNING,
                      PinStatus.PINNED, PinStatus.FAILED])

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["status"], "queued,pinning,pinned,failed")
        self.assertEqual(kwargs["params"]["limit"], 1000)

    @patch("filebase_pin_api.requests.get")
    def test_get_file_default_behaviour_unchanged(self, mock_get):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"count": 0, "results": []}
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        self.api.get_file("kleros", "QmTest")

        _, kwargs = mock_get.call_args
        self.assertNotIn("status", kwargs["params"])

    @staticmethod
    def _http_error(response):
        import requests
        error = requests.exceptions.HTTPError(response=response)
        return error


class DeleteFromFilebaseTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.environ["LOG_FILEPATH"] = self.tmpdir
        import importlib
        import delete_poh_user_data
        importlib.reload(delete_poh_user_data)
        self.module = delete_poh_user_data

    @patch("delete_poh_user_data.FilebasePinAPI")
    def test_failed_lookup_counts_as_failure(self, mock_api_cls):
        import requests
        mock_api = MagicMock()
        mock_api.get_file.side_effect = requests.exceptions.HTTPError("429")
        mock_api_cls.return_value = mock_api

        failures = self.module.delete_from_filebase({"QmTest": "file"})

        self.assertEqual(failures, len(self.module.BUCKET_NAMES))
        mock_api.delete_pin.assert_not_called()


if __name__ == "__main__":
    unittest.main()

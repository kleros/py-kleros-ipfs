"""Tests for delete_filebase_cids.py."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import requests

os.environ.setdefault("FILEBASE_TOKEN_KLEROS", "test-token")
os.environ.setdefault("FILEBASE_TOKEN_POH_V2", "test-token")

TMPDIR = tempfile.mkdtemp()
os.environ["LOG_FILEPATH"] = TMPDIR

import delete_filebase_cids as script  # noqa: E402


def _no_sleep(_seconds):
    pass


def _http_error(status_code):
    response = MagicMock()
    response.status_code = status_code
    return requests.exceptions.HTTPError(response=response)


class ProcessItemTests(unittest.TestCase):
    def setUp(self):
        self.api = MagicMock()

    def test_not_found_means_verified_absent_nothing_deleted(self):
        self.api.get_file.return_value = {"count": 0, "results": []}

        item = script.process_item(
            self.api, "kleros", "QmMissing", dry_run=False,
            max_rounds=5, round_delay=0, max_attempts=5, base_delay=0,
            sleep_fn=_no_sleep)

        self.assertEqual(item["found"], 0)
        self.assertEqual(item["deleted"], [])
        self.assertTrue(item["verified_absent"])
        self.assertIsNone(item["error"])
        self.api.delete_pin.assert_not_called()

    def test_two_requestids_deleted_then_verified(self):
        first_lookup = {"count": 2, "results": [
            {"requestid": "req-1"}, {"requestid": "req-2"}]}
        empty_lookup = {"count": 0, "results": []}
        self.api.get_file.side_effect = [first_lookup, empty_lookup]
        ok_response = MagicMock(status_code=202)
        ok_response.raise_for_status.return_value = None
        self.api.delete_pin.return_value = ok_response

        item = script.process_item(
            self.api, "kleros", "QmTwo", dry_run=False,
            max_rounds=5, round_delay=0, max_attempts=5, base_delay=0,
            sleep_fn=_no_sleep)

        self.assertEqual(item["found"], 2)
        self.assertCountEqual(item["deleted"], ["req-1", "req-2"])
        self.assertTrue(item["verified_absent"])
        self.assertIsNone(item["error"])
        self.assertEqual(self.api.delete_pin.call_count, 2)

    def test_429_then_success_is_retried(self):
        self.api.get_file.side_effect = [
            _http_error(429), {"count": 0, "results": []}]

        item = script.process_item(
            self.api, "kleros", "QmRetry", dry_run=False,
            max_rounds=5, round_delay=0, max_attempts=5, base_delay=0,
            sleep_fn=_no_sleep)

        self.assertIsNone(item["error"])
        self.assertTrue(item["verified_absent"])
        self.assertEqual(self.api.get_file.call_count, 2)

    def test_401_is_not_retried_and_becomes_item_error(self):
        self.api.get_file.side_effect = _http_error(401)

        item = script.process_item(
            self.api, "kleros", "QmUnauthorized", dry_run=False,
            max_rounds=5, round_delay=0, max_attempts=5, base_delay=0,
            sleep_fn=_no_sleep)

        self.assertIsNotNone(item["error"])
        self.assertFalse(item["verified_absent"])
        self.assertEqual(self.api.get_file.call_count, 1)

    def test_delete_404_is_treated_as_already_gone(self):
        first_lookup = {"count": 1, "results": [{"requestid": "req-gone"}]}
        empty_lookup = {"count": 0, "results": []}
        self.api.get_file.side_effect = [first_lookup, empty_lookup]
        gone_response = MagicMock(status_code=404)
        self.api.delete_pin.return_value = gone_response

        item = script.process_item(
            self.api, "kleros", "QmGone", dry_run=False,
            max_rounds=5, round_delay=0, max_attempts=5, base_delay=0,
            sleep_fn=_no_sleep)

        self.assertTrue(item["verified_absent"])
        self.assertIsNone(item["error"])
        self.assertEqual(item["deleted"], ["req-gone"])

    def test_still_present_after_max_rounds_is_not_verified_absent(self):
        always_present = {"count": 1, "results": [{"requestid": "req-stuck"}]}
        self.api.get_file.return_value = always_present
        ok_response = MagicMock(status_code=202)
        ok_response.raise_for_status.return_value = None
        self.api.delete_pin.return_value = ok_response

        item = script.process_item(
            self.api, "kleros", "QmStuck", dry_run=False,
            max_rounds=3, round_delay=0, max_attempts=5, base_delay=0,
            sleep_fn=_no_sleep)

        self.assertFalse(item["verified_absent"])
        self.assertIsNone(item["error"])
        # 1 initial lookup + 1 re-verification per round
        self.assertEqual(self.api.get_file.call_count, 4)

    def test_dry_run_never_calls_delete(self):
        self.api.get_file.return_value = {"count": 1, "results": [
            {"requestid": "req-1"}]}

        item = script.process_item(
            self.api, "kleros", "QmDry", dry_run=True,
            max_rounds=5, round_delay=0, max_attempts=5, base_delay=0,
            sleep_fn=_no_sleep)

        self.assertEqual(item["found"], 1)
        self.assertEqual(item["deleted"], [])
        self.assertFalse(item["verified_absent"])
        self.api.delete_pin.assert_not_called()


class MainCliTests(unittest.TestCase):
    @patch("delete_filebase_cids.FilebasePinAPI")
    def test_stdout_is_valid_json_only_and_exit_0_when_verified_absent(self, mock_api_cls):
        mock_api = MagicMock()
        mock_api.get_file.return_value = {"count": 0, "results": []}
        mock_api.logger.handlers = []
        mock_api_cls.return_value = mock_api

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = script.main(["QmSomething", "--bucket", "kleros"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["dry_run"])
        self.assertEqual(len(payload["results"]), 1)

    @patch("delete_filebase_cids.FilebasePinAPI")
    def test_exit_2_when_item_has_error(self, mock_api_cls):
        mock_api = MagicMock()
        mock_api.get_file.side_effect = _http_error(401)
        mock_api.logger.handlers = []
        mock_api_cls.return_value = mock_api

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = script.main(["QmBad", "--bucket", "kleros"])

        self.assertEqual(exit_code, 2)
        payload = json.loads(buffer.getvalue())
        self.assertFalse(payload["ok"])

    @patch("delete_filebase_cids.FilebasePinAPI")
    def test_missing_token_is_setup_failure_exit_1(self, mock_api_cls):
        mock_api = MagicMock()
        mock_api.get_file.side_effect = ValueError(
            "Token not defined for bucket kleros")
        mock_api.logger.handlers = []
        mock_api_cls.return_value = mock_api

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = script.main(["QmSomething", "--bucket", "kleros"])

        self.assertEqual(exit_code, 1)
        self.assertEqual(buffer.getvalue(), "")


if __name__ == "__main__":
    unittest.main()

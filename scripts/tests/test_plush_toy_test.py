import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "plush_toy_test", ROOT / "tools/plush_toy_test.py"
)
plush_toy_test = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(plush_toy_test)


class PlushToyTextTestCliTests(unittest.TestCase):
    def test_wave_maps_to_http_action(self):
        self.assertEqual(
            plush_toy_test.command_to_call(["wave", "--side", "left", "--times", "2"]),
            ("wave", {"side": "left", "times": 2}),
        )

    def test_eye_theme_maps_to_http_action(self):
        self.assertEqual(
            plush_toy_test.command_to_call(["eyes", "dragon-amber"]),
            ("eyes", {"theme": "dragon-amber"}),
        )

    def test_regression_order_is_safe_and_deterministic(self):
        self.assertEqual(
            [tool for tool, _ in plush_toy_test.REGRESSION_CASES],
            [
                "eyes", "wave", "wave", "wave", "hug", "cheer", "diagnostics",
            ],
        )

    @patch("urllib.request.build_opener")
    @patch("urllib.request.ProxyHandler")
    def test_loopback_requests_bypass_proxy(self, proxy_handler, build_opener):
        response = MagicMock()
        response.read.return_value = b'{"devices": []}'
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        build_opener.return_value = opener

        self.assertEqual(
            plush_toy_test.request_json("http://127.0.0.1:8003/debug/device-mcp/devices"),
            {"devices": []},
        )
        proxy_handler.assert_called_once_with({})
        build_opener.assert_called_once()

    @patch.object(plush_toy_test, "request_json", return_value={"accepted": True})
    def test_call_posts_action_to_board_local_endpoint(self, request_json):
        result = plush_toy_test.call_device_tool(
            "http://172.20.10.2:8181", "wave", {"side": "left", "times": 1}
        )

        self.assertEqual(result, {"accepted": True})
        request_json.assert_called_once_with(
            "http://172.20.10.2:8181/test/v1/actions",
            "POST",
            {"action": "wave", "arguments": {"side": "left", "times": 1}},
        )

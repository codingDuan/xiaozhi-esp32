#!/usr/bin/env python3
"""Send direct, loopback-only text commands to an online plush-toy board."""

import argparse
import json
import sys
import urllib.error
import urllib.request


DEFAULT_SERVER = "http://127.0.0.1:8003"
REGRESSION_CASES = [
    ("self.eyes.change_theme", {"theme": "dragon-amber"}),
    ("self.limbs.wave_hand", {"side": "left", "times": 1}),
    ("self.limbs.wave_hand", {"side": "right", "times": 1}),
    ("self.limbs.wave_hand", {"side": "both", "times": 1}),
    ("self.limbs.hug", {}),
    ("self.limbs.cheer", {"times": 1}),
    ("self.limbs.get_diagnostics", {}),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=DEFAULT_SERVER, help="debug bridge base URL")
    parser.add_argument("--device-id", help="online device ID; required when multiple devices are online")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("devices", help="list online devices")

    wave = subparsers.add_parser("wave", help="wave one or both arms")
    wave.add_argument("--side", choices=("left", "right", "both"), default="both")
    wave.add_argument("--times", type=int, choices=range(1, 6), default=2)

    subparsers.add_parser("hug", help="open both arms")
    cheer = subparsers.add_parser("cheer", help="wiggle both arms")
    cheer.add_argument("--times", type=int, choices=range(1, 6), default=3)
    eyes = subparsers.add_parser("eyes", help="set an eye theme")
    eyes.add_argument("theme", help="for example: dragon-amber or cat-gold")
    subparsers.add_parser("diagnostics", help="read arm driver diagnostics")
    subparsers.add_parser("run-regression", help="run the standard direct-MCP regression")
    return parser


def command_to_call(argv: list[str]) -> tuple[str, dict]:
    args = build_parser().parse_args(argv)
    if args.command == "wave":
        return "self.limbs.wave_hand", {"side": args.side, "times": args.times}
    if args.command == "hug":
        return "self.limbs.hug", {}
    if args.command == "cheer":
        return "self.limbs.cheer", {"times": args.times}
    if args.command == "eyes":
        return "self.eyes.change_theme", {"theme": args.theme}
    if args.command == "diagnostics":
        return "self.limbs.get_diagnostics", {}
    raise ValueError(f"{args.command} does not map to one MCP tool")


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=35) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {body}") from error
    except (urllib.error.URLError, json.JSONDecodeError) as error:
        raise RuntimeError(f"debug bridge request failed: {error}") from error


def select_device(server: str, requested_device_id: str | None) -> str:
    devices = request_json(f"{server.rstrip('/')}/debug/device-mcp/devices").get("devices", [])
    if requested_device_id:
        if any(device.get("device_id") == requested_device_id for device in devices):
            return requested_device_id
        raise RuntimeError(f"device {requested_device_id!r} is not online")
    if len(devices) == 1:
        return devices[0]["device_id"]
    if not devices:
        raise RuntimeError("no online device; check board Wi-Fi and local service")
    raise RuntimeError("multiple devices are online; pass --device-id")


def call_device_tool(server: str, device_id: str, tool: str, arguments: dict) -> dict:
    return request_json(
        f"{server.rstrip('/')}/debug/device-mcp/call",
        "POST",
        {"device_id": device_id, "tool": tool, "arguments": arguments},
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "devices":
            print(json.dumps(request_json(f"{args.server.rstrip('/')}/debug/device-mcp/devices"), ensure_ascii=False, indent=2))
            return 0

        device_id = select_device(args.server, args.device_id)
        if args.command == "run-regression":
            for index, (tool, arguments) in enumerate(REGRESSION_CASES, start=1):
                result = call_device_tool(args.server, device_id, tool, arguments)
                print(json.dumps({"case": index, **result}, ensure_ascii=False))
            return 0

        tool, arguments = command_to_call((argv if argv is not None else sys.argv[1:]))
        result = call_device_tool(args.server, device_id, tool, arguments)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

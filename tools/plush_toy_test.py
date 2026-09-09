#!/usr/bin/env python3
"""Send direct HTTP text commands to an idle plush-toy board."""

import argparse
import json
import sys
import urllib.error
import urllib.request


DEFAULT_DEVICE_URL = "http://172.20.10.2:8181"
REGRESSION_CASES = [
    ("eyes", {"theme": "dragon-amber"}), ("wave", {"side": "left", "times": 1}),
    ("wave", {"side": "right", "times": 1}), ("wave", {"side": "both", "times": 1}),
    ("hug", {}), ("cheer", {"times": 1}), ("diagnostics", {}),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-url", default=DEFAULT_DEVICE_URL, help="board HTTP test URL")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="read board-local test channel status")

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
        return "wave", {"side": args.side, "times": args.times}
    if args.command == "hug":
        return "hug", {}
    if args.command == "cheer":
        return "cheer", {"times": args.times}
    if args.command == "eyes":
        return "eyes", {"theme": args.theme}
    if args.command == "diagnostics":
        return "diagnostics", {}
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
        raise RuntimeError(f"board test-channel request failed: {error}") from error


def call_device_tool(device_url: str, action: str, arguments: dict) -> dict:
    return request_json(
        f"{device_url.rstrip('/')}/test/v1/actions",
        "POST",
        {"action": action, "arguments": arguments},
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            print(json.dumps(request_json(f"{args.device_url.rstrip('/')}/test/v1/status"), ensure_ascii=False, indent=2))
            return 0

        if args.command == "run-regression":
            for index, (action, arguments) in enumerate(REGRESSION_CASES, start=1):
                result = call_device_tool(args.device_url, action, arguments)
                print(json.dumps({"case": index, **result}, ensure_ascii=False))
            return 0

        action, arguments = command_to_call((argv if argv is not None else sys.argv[1:]))
        result = call_device_tool(args.device_url, action, arguments)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

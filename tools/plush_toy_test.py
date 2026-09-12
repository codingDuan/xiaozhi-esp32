#!/usr/bin/env python3
"""Send direct HTTP text commands to an idle plush-toy board."""

import argparse
import json
import sys
import urllib.error
import urllib.request


DEFAULT_DEVICE_URL = "http://172.20.10.2:8181"
REGRESSION_CASES = [
    # 每种虹膜渲染路径取一个主题：圆瞳浅巩膜、竖瞳暗巩膜、横瞳、无巩膜、
    # 照片纹理、日系画法。少了任何一条，对应的渲染分支就没人跑过。
    ("eyes", {"theme": "ocean"}), ("eyes", {"theme": "dragon-amber"}),
    ("eyes", {"theme": "cat-gold"}), ("eyes", {"theme": "void-blue"}),
    ("eyes", {"theme": "uncanny-dragon"}), ("eyes", {"theme": "anime-sky"}),
    ("wave", {"side": "left", "times": 1}),
    ("wave", {"side": "right", "times": 1}), ("wave", {"side": "both", "times": 1}),
    ("hug", {}), ("cheer", {"times": 1}),
    # 情绪联动：一次 SetEmotion 同时改眼睛并触发手势。前四条各覆盖一种手势映射，
    # angry 覆盖“刻意不动作”那一支 —— 它必须只改眼睛、手臂保持不动。
    #
    # 自发手势默认全关，这里必须先开 EMOTION 位，否则整段只能验到眼睛，
    # 手势映射根本不会执行。跑完恢复默认，免得回归改变了板子的常驻行为。
    ("gesture_modes", {"modes": 0x08}),
    ("emotion", {"emotion": "happy"}), ("emotion", {"emotion": "loving"}),
    ("emotion", {"emotion": "sad"}), ("emotion", {"emotion": "surprised"}),
    ("emotion", {"emotion": "angry"}), ("emotion", {"emotion": "neutral"}),
    ("gesture_modes", {"modes": 0x00}),
    # 触摸：先只开本地反射，验证眼睛和手臂；再开诊断位，让 status 带出原始计数。
    # 唤醒与上报两位不进回归 —— 它们会真的发起一轮对话，干扰后续用例。
    ("touch_modes", {"modes": 0x01}),
    ("simulate_touch", {"electrode": 0, "pressed": True}),
    ("simulate_touch", {"electrode": 0, "pressed": False}),
    ("touch_modes", {"modes": 0x09}),
    # 运动：同样只开本地反射与诊断。姿态按 竖→躺→倒→竖 走一圈，
    # 确认每次跨态都产生事件且能回到初态。
    ("motion_modes", {"modes": 0x01}),
    ("simulate_motion", {"kind": "shake"}),
    ("simulate_motion", {"kind": "lying"}),
    ("simulate_motion", {"kind": "inverted"}),
    ("simulate_motion", {"kind": "upright"}),
    ("motion_modes", {"modes": 0x09}),
    ("diagnostics", {}),
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
    emotion = subparsers.add_parser("emotion", help="set an emotion; drives eyes and gesture")
    emotion.add_argument("emotion", help="for example: happy, loving, sad, surprised or angry")
    gesture_modes = subparsers.add_parser("gesture-modes",
                                          help="set the spontaneous gesture mask (default 0)")
    gesture_modes.add_argument("modes", type=lambda v: int(v, 0),
                               help="bitmask: 1 listening, 2 speaking, 4 idle, 8 emotion")
    touch_modes = subparsers.add_parser("touch-modes", help="set the touch response mask")
    touch_modes.add_argument("modes", type=lambda v: int(v, 0),
                             help="bitmask: 1 reflex, 2 wake, 4 report, 8 diagnostics")
    simulate = subparsers.add_parser("simulate-touch", help="fake a touch without the sensor")
    simulate.add_argument("electrode", type=int, choices=range(0, 12), default=0, nargs="?")
    simulate.add_argument("--release", action="store_true", help="send release instead of press")
    motion_modes = subparsers.add_parser("motion-modes", help="set the motion response mask")
    motion_modes.add_argument("modes", type=lambda v: int(v, 0),
                              help="bitmask: 1 reflex, 2 wake, 4 report, 8 diagnostics")
    simulate_motion = subparsers.add_parser("simulate-motion",
                                            help="fake a motion event without moving the toy")
    simulate_motion.add_argument("kind", choices=("shake", "upright", "lying", "inverted"),
                                 default="shake", nargs="?")
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
    if args.command == "emotion":
        return "emotion", {"emotion": args.emotion}
    if args.command == "gesture-modes":
        return "gesture_modes", {"modes": args.modes}
    if args.command == "touch-modes":
        return "touch_modes", {"modes": args.modes}
    if args.command == "simulate-touch":
        return "simulate_touch", {"electrode": args.electrode, "pressed": not args.release}
    if args.command == "motion-modes":
        return "motion_modes", {"modes": args.modes}
    if args.command == "simulate-motion":
        return "simulate_motion", {"kind": args.kind}
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

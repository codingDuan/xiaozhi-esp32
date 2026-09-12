#!/usr/bin/env python3
"""Measure plush-toy I2C bus health, one trial per hardware configuration.

用途：换上拉电阻、改走线、换供电之后，用同一把尺子量总线到底有没有变好。
每跑一次叫一个 trial，结果追加到 JSONL，再用 --compare 并排比。

为什么需要专门一个脚本，而不是手工看 status：
  2026-09-11 的排查里，我们先用"边高频轮询边看丢帧率"得出「降低 I2C 时钟有效」，
  后来发现那个指标被轮询本身的总线拥塞污染了，干净重测下 100k/50k/20kHz
  三档完全无差别。这个脚本把两种测法分开测、分开报，并且强制打印置信区间，
  就是为了不让那个错误重演。
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

DEVICE_URL_ENV = "PLUSH_TOY_DEVICE_URL"
# config.h: MOTION_POLL_INTERVAL_MS 100，即运动任务每秒 10 帧。
# 空闲期总帧数由时长推算 —— 固件没有"总采样数"计数器，只有被丢弃的那个。
POLL_HZ = 10.0
MOTION_MODE_DIAG = 0x08


def request_json(url, method="GET", payload=None, timeout=20):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Board:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def status(self):
        return request_json(f"{self.base}/test/v1/status")

    def action(self, action, arguments):
        return request_json(
            f"{self.base}/test/v1/actions", "POST", {"action": action, "arguments": arguments}
        )


def wilson(successes, total):
    """Wilson score 95% 区间。小样本下比 p ± 1.96·SE 可靠，且不会越界到负数。"""
    if total == 0:
        return (0.0, 0.0, 0.0)
    z = 1.959964
    p = successes / total
    d = 1.0 + z * z / total
    centre = (p + z * z / (2 * total)) / d
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def measure_idle(board, seconds):
    """空闲期丢帧率：首尾各读一次，中间完全不打扰总线。

    这是唯一能反映总线固有质量的指标。测量期间不得有任何 HTTP 请求 ——
    一次 status 会连带触发若干次 I2C 读，把结果推高。
    """
    a = board.status()
    t0 = time.time()
    time.sleep(seconds)
    b = board.status()
    dt = time.time() - t0
    rejected = b["motion_rejected"] - a["motion_rejected"]
    total = int(round(dt * POLL_HZ))
    return {"seconds": round(dt, 1), "rejected": rejected, "frames": total}


def measure_contended(board, samples):
    """拥塞期：连续读 status，量 ReadAccel 失败率。

    accel 字段只在 Mpu6050::ReadAccel() 成功时才出现（plush_toy_board.cc），
    所以"字段缺失"就是一次读失败，这是现成的成功率探针。

    注意这是 *拥塞下* 的读失败率，与空闲丢帧率不是一回事，不要混用。
    """
    miss = 0
    done = 0
    r0 = r1 = None
    t0 = time.time()
    for _ in range(samples):
        try:
            d = board.status()
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            # HTTP 层失败不算 I2C 失败，单独计数，避免把网络问题记成总线问题。
            continue
        done += 1
        if "accel" not in d:
            miss += 1
        if r0 is None:
            r0 = d["motion_rejected"]
        r1 = d["motion_rejected"]
    dt = time.time() - t0
    out = {
        "samples": done,
        "http_failed": samples - done,
        "accel_missing": miss,
        "seconds": round(dt, 1),
    }
    if done:
        out["seconds_per_sample"] = round(dt / done, 2)
    if r0 is not None:
        out["rejected"] = r1 - r0
        out["frames"] = int(round(dt * POLL_HZ))
    return out


def run_trial(board, label, samples, idle_seconds, touch_diag):
    first = board.status()
    if not first.get("motion_present"):
        raise RuntimeError("motion_present 为 false，MPU6050 没探测到，测不了")
    if (first.get("motion_modes", 0) & MOTION_MODE_DIAG) == 0:
        raise RuntimeError(
            "motion_modes 的诊断位（0x08）没开，status 不会带出 accel 与 motion_rejected。"
            "先跑 plush_toy_test.py motion-modes 0x09"
        )

    # 触摸诊断位每次 status 会多读 24 个 MPR121 寄存器，总线负载差一大截。
    # 跨 trial 比较必须固定它，否则比的是负载不是总线。
    original_touch = first.get("touch_modes", 0)
    restore = False
    if touch_diag == "off" and original_touch != 0:
        board.action("touch_modes", {"modes": 0})
        restore = True
        print(f"  touch_modes 暂时置 0（原值 {original_touch}），跨 trial 统一总线负载")

    try:
        print(f"  [1/2] 空闲期 {idle_seconds}s，期间不打扰总线 ...")
        idle = measure_idle(board, idle_seconds)
        print(f"  [2/2] 拥塞期 {samples} 次采样 ...")
        contended = measure_contended(board, samples)
    finally:
        if restore:
            board.action("touch_modes", {"modes": original_touch})
            print(f"  touch_modes 已还原为 {original_touch}")

    return {
        "label": label,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "touch_modes_during": 0 if restore else original_touch,
        "motion_modes": first.get("motion_modes"),
        "idle": idle,
        "contended": contended,
    }


def fmt_rate(successes, total):
    if not total:
        return "n/a"
    p, lo, hi = wilson(successes, total)
    return f"{p*100:5.1f}%  [{lo*100:4.1f}, {hi*100:4.1f}]  ({successes}/{total})"


def print_trial(t):
    print(f"\n=== trial: {t['label']} ===")
    i, c = t["idle"], t["contended"]
    print(f"  空闲丢帧率    {fmt_rate(i['rejected'], i['frames'])}")
    print(f"  拥塞读失败率  {fmt_rate(c['accel_missing'], c['samples'])}")
    if "rejected" in c:
        print(f"  拥塞丢帧率    {fmt_rate(c['rejected'], c['frames'])}")
    if c.get("http_failed"):
        print(f"  HTTP 失败      {c['http_failed']} 次（不计入 I2C 指标）")
    if "seconds_per_sample" in c:
        print(f"  每次 status    {c['seconds_per_sample']}s"
              " —— 采样率上限由它决定，不是由脚本的 sleep 决定")


def compare(path):
    if not os.path.exists(path):
        sys.exit(f"没有找到 {path}，先跑几个 trial")
    trials = [json.loads(l) for l in open(path) if l.strip()]
    if not trials:
        sys.exit(f"{path} 是空的")

    print(f"\n{'label':<16} {'空闲丢帧率 [95% 区间]':<34} {'拥塞读失败率 [95% 区间]':<34}")
    print("-" * 86)
    rows = []
    for t in trials:
        i, c = t["idle"], t["contended"]
        print(f"{t['label']:<16} {fmt_rate(i['rejected'], i['frames']):<34} "
              f"{fmt_rate(c['accel_missing'], c['samples']):<34}")
        rows.append((t["label"], wilson(i["rejected"], i["frames"]),
                     wilson(c["accel_missing"], c["samples"])))

    print("\n判读：")
    best = min(rows, key=lambda r: r[1][0])
    overlapping = [r[0] for r in rows if r is not best and r[1][1] <= best[1][2]]
    if overlapping:
        print(f"  空闲丢帧率最低的是 {best[0]}，但它的区间与 {', '.join(overlapping)} 重叠，")
        print("  **不能据此认为它更好**。要么加长 --idle-seconds，要么承认这几档无差别。")
    else:
        print(f"  空闲丢帧率：{best[0]} 显著最低，区间与其余各档不重叠。")
    print("  拥塞读失败率只能同负载比较（touch_modes_during 相同），跨负载没有意义。")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device-url", default=os.environ.get(DEVICE_URL_ENV),
                   help=f"板子 HTTP 测试通道，或设 ${DEVICE_URL_ENV}；"
                        "取 IP 的方法见 main/boards/plush-toy/README.md")
    p.add_argument("--label", help='本次配置的名字，例如 "板载4.7k" 或 "面包板原状"')
    p.add_argument("--samples", type=int, default=60, help="拥塞期采样次数（默认 60）")
    p.add_argument("--idle-seconds", type=int, default=60, help="空闲期时长（默认 60）")
    p.add_argument("--touch-diag", choices=("off", "keep"), default="off",
                   help="off：测量期间关掉触摸诊断位以统一总线负载（默认）")
    p.add_argument("--record", default="i2c_trials.jsonl", help="结果追加到该 JSONL")
    p.add_argument("--compare", action="store_true", help="只打印已有结果的对比表，不测量")
    args = p.parse_args(argv)

    if args.compare:
        compare(args.record)
        return 0
    if not args.device_url:
        p.error(f"--device-url is required (or set ${DEVICE_URL_ENV})")
    if not args.label:
        p.error('--label is required：不给配置起名字，测完就分不清哪次是哪个硬件状态')

    board = Board(args.device_url)
    print(f"trial「{args.label}」开始，"
          f"预计 {args.idle_seconds + int(args.samples * 1.3)}s")
    try:
        t = run_trial(board, args.label, args.samples, args.idle_seconds, args.touch_diag)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"ERROR: 板子连不上：{e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print_trial(t)
    with open(args.record, "a") as f:
        f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"\n已追加到 {args.record}。跑完几档后用 --compare 看对比表。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj027 4c: AMS の温度・電圧、INA220（hwmon）の電流と負荷を一定の間隔で 1 行ずつ残す（行ごとに fsync。ボードが落ちても直前の行が残る）

  python3 amslog.py --out runs/g24_4c30b.ams.log --period 10 --seconds 2000
"""
import argparse
import glob
import os
import time


def chans(dev):
    """[(名前, raw の道, scale, offset)]"""
    out = []
    for raw in sorted(glob.glob(os.path.join(dev, "in_*_raw"))):
        base = raw[: -len("_raw")]
        name = os.path.basename(base)[3:]
        rd = lambda p, d: float(open(p).read()) if os.path.exists(p) else d
        out.append((name, raw, rd(base + "_scale", 1.0), rd(base + "_offset", 0.0)))
    return out


def inas():
    """[(i2c の番地, curr1_input の道)]（ボードの INA220。0x40 が VCCINT と見る）"""
    out = []
    for h in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        if open(h + "/name").read().strip() == "ina220":
            out.append(("i" + os.path.basename(os.path.realpath(h + "/device"))[-2:], h + "/curr1_input"))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--period", type=float, default=10.0)
    ap.add_argument("--seconds", type=float, default=0, help="0 = 止めるまで")
    o = ap.parse_args()
    dev = next(d for d in glob.glob("/sys/bus/iio/devices/iio:device*") if open(d + "/name").read().strip() == "xilinx-ams")
    cs = chans(dev)
    ia = inas()
    fd = os.open(o.out, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    # 温度は ℃、電圧は mV（raw + offset）× scale の値。temp は mC なので 1/1000
    os.write(fd, ("# utc load1 " + " ".join(n for n, *_ in cs) + " " + " ".join(n + "_mA" for n, _ in ia) + "\n").encode())
    t0 = time.monotonic()
    while not o.seconds or time.monotonic() - t0 < o.seconds:
        vals = []
        for name, raw, sc, off in cs:
            try:
                v = (float(open(raw).read()) + off) * sc
                vals.append(f"{v / 1000:.2f}" if name.startswith("temp") else f"{v:.0f}")
            except OSError:
                vals.append("-")
        for name, p in ia:
            try:
                vals.append(open(p).read().strip())
            except OSError:
                vals.append("-")
        line = time.strftime("%H:%M:%S", time.gmtime()) + f" {os.getloadavg()[0]:.2f} " + " ".join(vals) + "\n"
        os.write(fd, line.encode())
        os.fsync(fd)
        time.sleep(o.period)


if __name__ == "__main__":
    main()

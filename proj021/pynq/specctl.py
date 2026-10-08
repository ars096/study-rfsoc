#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj018 — 制御 PC の側の道具: specd の制御の口に命令を打つ（Python の標準ライブラリだけ）

    python3 specctl.py --host <board> STATUS
    python3 specctl.py --host <board> "SET A0.bw=256 A1.bw=8 all.shift=9" "START n=100" "SEND ON"
    python3 specctl.py --host <board>                 # 対話（1 行ずつ打つ）
    python3 specctl.py --host <board> --wait-idle 600 # 状態が IDLE になるまで待つ（試験の台本用）

終了の状態: 最後の応答が ERR なら 1
"""
import argparse
import socket
import sys
import time


class Ctl:
    def __init__(self, host, port, timeout=60.0):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.f = self.s.makefile("rwb", buffering=0)

    def cmd(self, line):
        self.s.sendall((line.strip() + "\n").encode())
        r = self.f.readline()
        if not r:
            raise ConnectionError("サーバーが切った")
        return r.decode().rstrip("\n")

    def kv(self, line):
        r = self.cmd(line)
        if not r.startswith("OK"):
            raise RuntimeError(r)
        return dict(x.split("=", 1) for x in r.split()[1:] if "=" in x)

    def close(self):
        try:
            self.cmd("BYE")
        except Exception:
            pass
        self.s.close()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=51000)
    p.add_argument("--wait-idle", type=float, default=0, help="命令の後、STATUS の state が IDLE になるまで待つ（秒の上限）")
    p.add_argument("cmds", nargs="*")
    a = p.parse_args()
    c = Ctl(a.host, a.port)
    last = "OK"
    if a.cmds:
        for line in a.cmds:
            last = c.cmd(line)
            print(f"> {line}\n{last}", flush=True)
    elif not a.wait_idle:
        for line in sys.stdin:
            if not line.strip():
                continue
            last = c.cmd(line)
            print(last, flush=True)
    if a.wait_idle:
        t_e = time.time() + a.wait_idle
        while time.time() < t_e:
            st = c.kv("STATUS")
            if st.get("state") in ("IDLE", "ERROR"):
                last = "OK" if st["state"] == "IDLE" else "ERR state=ERROR"
                print(f"state={st['state']}", flush=True)
                break
            time.sleep(1.0)
        else:
            last = "ERR timeout"
            print("待ち時間を越えた", flush=True)
    c.close()
    sys.exit(0 if last.startswith("OK") else 1)


if __name__ == "__main__":
    main()

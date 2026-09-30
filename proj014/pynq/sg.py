#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — 信号発生器（SG）を LAN の SCPI（raw socket、既定 5025 番）で操作する。追加の導入は要らない（標準の socket だけ）。

対象: Agilent / Keysight E8257D（VERSIONS.md の標準の試験音源）。SCPI の基本の命令だけを使うので、他の SCPI の SG でもたいてい動く。
**SG の宛先はリポジトリに書かない**（公開前スキャンの対象）。--sg HOST[:PORT] か、環境変数 RFSOC_SG で与える。

約束:
  - 設定したら**必ず読み返して**一致を確かめる（周波数は 1 Hz、レベルは 0.01 dB）。違えば止める
  - 出力の ON / OFF も読み返す。**道具が SG を触ったことをログに残す**（*IDN?・周波数・レベル・ON/OFF）
  - 終わったら元の出力の状態（ON / OFF）に戻す（with 文）

単体で:
  python3 sg.py --sg HOST --idn
  python3 sg.py --sg HOST --freq 3010.5 --dbm -20 --on
"""
import argparse
import os
import socket
import sys
import time


class SG:
    def __init__(self, target=None, timeout=3.0, log=print):
        target = target or os.environ.get("RFSOC_SG")
        if not target:
            raise SystemExit("SG の宛先が無い（--sg HOST[:PORT] か 環境変数 RFSOC_SG）")
        host, _, port = target.partition(":")
        self.host, self.port = host, int(port or 5025)
        self.log = log
        self.s = socket.create_connection((self.host, self.port), timeout=timeout)
        self.s.settimeout(timeout)
        self._buf = b""
        self.idn = self.query("*IDN?")
        self.log(f"SG: {self.idn}")
        self._out0 = None

    def write(self, cmd):
        self.s.sendall((cmd + "\n").encode())

    def query(self, cmd):
        self.write(cmd)
        while b"\n" not in self._buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise RuntimeError("SG が接続を切った")
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode().strip()

    def check_err(self):
        e = self.query(":SYST:ERR?")
        if not e.startswith(("+0", "0")):
            raise RuntimeError(f"SG のエラー: {e}")

    def freq(self):
        return float(self.query(":FREQ?"))          # Hz

    def power(self):
        return float(self.query(":POW?"))           # dBm

    def output(self):
        return self.query(":OUTP?").strip() in ("1", "ON")

    def set_freq_mhz(self, mhz):
        self.write(f":FREQ {mhz * 1e6:.3f} Hz")
        got = self.freq()
        if abs(got - mhz * 1e6) > 1.0:
            raise RuntimeError(f"SG の周波数が {got} Hz（要求 {mhz * 1e6} Hz）")
        self.check_err()
        self.log(f"SG: 周波数 {got / 1e6:.6f} MHz")

    def set_dbm(self, dbm):
        self.write(f":POW {dbm:.2f} dBm")
        got = self.power()
        if abs(got - dbm) > 0.01:
            raise RuntimeError(f"SG のレベルが {got} dBm（要求 {dbm} dBm）")
        self.check_err()
        self.log(f"SG: レベル {got:+.2f} dBm")

    def set_output(self, on):
        if self._out0 is None:
            self._out0 = self.output()
        self.write(f":OUTP {'ON' if on else 'OFF'}")
        time.sleep(0.05)
        if self.output() != bool(on):
            raise RuntimeError("SG の出力の ON / OFF が要求と違う")
        self.check_err()
        self.log(f"SG: 出力 {'ON' if on else 'OFF'}")

    def state(self):
        return dict(idn=self.idn, freq_hz=self.freq(), dbm=self.power(), on=self.output())

    def close(self):
        try:
            if self._out0 is not None and self.output() != self._out0:
                self.set_output(self._out0)
        finally:
            self.s.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sg", default=None, help="HOST[:PORT]（既定は環境変数 RFSOC_SG）")
    p.add_argument("--idn", action="store_true")
    p.add_argument("--freq", type=float, default=None, help="MHz")
    p.add_argument("--dbm", type=float, default=None)
    p.add_argument("--on", action="store_true")
    p.add_argument("--off", action="store_true")
    a = p.parse_args()
    sg = SG(a.sg)
    try:
        if a.freq is not None: sg.set_freq_mhz(a.freq)
        if a.dbm is not None: sg.set_dbm(a.dbm)
        if a.on: sg.set_output(True); sg._out0 = True      # 単体で ON にしたときは戻さない
        if a.off: sg.set_output(False); sg._out0 = False
        print(sg.state())
    finally:
        sg.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

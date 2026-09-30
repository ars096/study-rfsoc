#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — 信号発生器（SG）を LAN の SCPI（raw socket、既定 5025 番）で操作する。追加の導入は要らない（標準の socket だけ）。

対象: Agilent / Keysight E8257D（VERSIONS.md の標準の試験音源）。SCPI の基本の命令だけを使うので、他の SCPI の SG でもたいてい動く。
**SG の宛先はリポジトリに書かない**（公開前スキャンの対象）。--sg HOST[:PORT] か、環境変数 RFSOC_SG で与える。

約束:
  - 設定したら**必ず読み返して**一致を確かめる（周波数は 1 Hz、レベルは 0.01 dB）。違えば止める
  - 出力の ON / OFF も読み返す。**道具が SG を触ったことをログに残す**（*IDN?・周波数・レベル・ON/OFF）
  - 終わったら元の出力の状態（ON / OFF）に戻す（with 文）
  - つないだときに、**溜まっていたエラーを読み出してログに残してから消す**（*CLS）。前の操作や前面パネルのエラーで止まらないように
  - 基準（10 MHz）の状態（:ROSC:SOUR? = INT / EXT）を読んでログに残す。**「Reference unlocked」（+512 など）は止めずに警告**:
    出力は出ているが周波数が基準にロックしていない。W-1 の ch 単位の位置（8 MHz 窓で 1.95 kHz / ch）は SG と RFSoC の基準が
    同じ 10 MHz に載っていないと 1 ppm（3 GHz で 3 kHz）ずれうる。W-6（電力の比）には効かない

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
        self.warnings = []
        old = self.read_errors()
        if old:
            self.log(f"SG: つないだ時点で溜まっていたエラー {len(old)} 件（消す）: " + " / ".join(old))
        self.write("*CLS")
        self.ref = self.ref_state()
        self.log(f"SG: 基準 {self.ref}")
        self.pmin, self.pmax = self.power_range()
        self.log(f"SG: 設定できるレベル {self.pmin:+.2f} 〜 {self.pmax:+.2f} dBm")

    def power_range(self):
        # E8257D は機械式のステップ減衰器（オプション 1E1 など）が無いと下限が -20 dBm 前後。範囲外は黙って端に丸められる
        try:
            lo, hi = float(self.query(":POW? MIN")), float(self.query(":POW? MAX"))
        except (socket.timeout, OSError, ValueError):
            lo, hi = float("-inf"), float("inf")
        self.read_errors()
        return lo, hi

    WARN_CODES = ("+512", "512", "+513", "513")     # E8257D: 基準（10 MHz）のロック外れの類。出力は出ている

    def read_errors(self, nmax=32):
        out = []
        for _ in range(nmax):
            e = self.query(":SYST:ERR?")
            if e.startswith(("+0", "0")):
                break
            out.append(e)
        return out

    def ref_state(self):
        try:
            src = self.query(":ROSC:SOUR?")
        except (socket.timeout, OSError):
            return "不明（:ROSC:SOUR? に答えない）"
        e = self.read_errors()
        return f"{src}" + (f"（読んだときのエラー: {' / '.join(e)}）" if e else "")

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
        errs = self.read_errors()
        hard = []
        for e in errs:
            if e.split(",")[0].strip() in self.WARN_CODES or "Reference unlocked" in e:
                if e not in self.warnings:
                    self.warnings.append(e)
                self.log(f"SG: 警告（止めない）: {e}")
            else:
                hard.append(e)
        if hard:
            raise RuntimeError("SG のエラー: " + " / ".join(hard))

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
        if not (self.pmin - 1e-6 <= dbm <= self.pmax + 1e-6):
            raise RuntimeError(f"SG のレベル {dbm:+.2f} dBm は設定できる範囲 {self.pmin:+.2f} 〜 {self.pmax:+.2f} dBm の外"
                               "（下げたいなら SG の出口に固定減衰器を入れ、その値を記録する）")
        self.write(f":POW {dbm:.2f} dBm")
        got = self.power()
        if abs(got - dbm) > 0.01:
            e = self.read_errors()
            raise RuntimeError(f"SG のレベルが {got} dBm（要求 {dbm} dBm）" + (f"。SG のエラー: {' / '.join(e)}" if e else ""))
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
        return dict(idn=self.idn, freq_hz=self.freq(), dbm=self.power(), on=self.output(), ref=self.ref,
                    warnings=list(self.warnings))

    def close(self):
        if self.s is None:
            return
        try:
            if self._out0 is not None and self.output() != self._out0:
                self.set_output(self._out0)
        finally:
            self.s.close()
            self.s = None

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

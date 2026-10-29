#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — 測定器を LAN の SCPI（raw socket、既定 5025 番）で操作する: パワーメーター（N1913A ＋ E9300A）とプログラムアッテネータ（J7211C）。
標準の socket だけ。**宛先はリポジトリに書かない**（引数か環境変数 RFSOC_PM / RFSOC_ATT、HOST[:PORT]）。

約束（proj014 の sg.py と同じ）:
  - 設定したら**読み返して**一致を確かめる。違えば止める
  - つないだときに *IDN? と溜まっていたエラーをログに残してから消す（*CLS）
  - 道具が測定器を触ったことをログに残す

アッテネータの命令は機種・ファームウェアで違うことがあるので、既定（"ATT {db}" / "ATT?"）で読み返しが合わなければ、
プログラミングガイドの命令を set_cmd / get_cmd で渡す（例: Atten(set_cmd=":ATT {db}", get_cmd=":ATT?")）。
手で回すアッテネータなら ManualAtten（値を打つたびに確かめを求める）。

    from instr import PowerMeter, Atten
    pm = PowerMeter("<パワーメーターの IP>", freq_mhz=3000, avg=64)   # E9300A の較正係数の周波数を BPF の中心に
    pm.zero()                                                        # ノイズソースを切った状態で（入力 0 で零点を取る）
    pm.read()                                                        # dBm
    at = Atten("<アッテネータの IP>"); at.set(30.0); at.get()
"""
import os
import socket
import time


class Scpi:
    def __init__(self, target, env, timeout=10.0, log=print, name="測定器"):
        target = target or os.environ.get(env)
        if not target:
            raise SystemExit(f"{name}の宛先が無い（引数 HOST[:PORT] か 環境変数 {env}）")
        host, _, port = target.partition(":")
        self.host, self.port, self.log, self.name = host, int(port or 5025), log, name
        self.s = socket.create_connection((self.host, self.port), timeout=timeout)
        self.s.settimeout(timeout)
        self._buf = b""
        self.idn = self.query("*IDN?")
        errs = self.read_errors()
        self.write("*CLS")
        self.log(f"{name}: {self.idn}" + (f"（溜まっていたエラー: {' / '.join(errs)}）" if errs else ""))

    def write(self, cmd):
        self.s.sendall((cmd + "\n").encode())

    def query(self, cmd):
        self.write(cmd)
        while b"\n" not in self._buf:
            b = self.s.recv(4096)
            if not b:
                raise ConnectionError(f"{self.name}が切った")
            self._buf += b
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode(errors="replace").strip()

    def read_errors(self, nmax=16):
        out = []
        for _ in range(nmax):
            try:
                e = self.query("SYST:ERR?")
            except Exception:
                break
            if e.startswith("+0") or e.startswith("0,") or not e:
                break
            out.append(e)
        return out

    def check_err(self):
        e = self.read_errors()
        if e:
            raise RuntimeError(f"{self.name}のエラー: {' / '.join(e)}")

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


class PowerMeter(Scpi):
    """Keysight N1913A ＋ E9300A（−60〜+20 dBm）。READ? で平均つきの 1 回の測定（dBm）"""

    def __init__(self, target=None, freq_mhz=3000.0, avg=64, timeout=20.0, log=print):
        super().__init__(target, "RFSOC_PM", timeout, log, "パワーメーター")
        self.write("UNIT:POW DBM")
        self.write(f"SENS:FREQ {freq_mhz * 1e6:.0f}")
        self.write("SENS:AVER:STAT ON")
        self.write("SENS:AVER:COUN:AUTO OFF")
        self.write(f"SENS:AVER:COUN {int(avg)}")
        self.write("INIT:CONT OFF")
        f = float(self.query("SENS:FREQ?"))
        n = int(float(self.query("SENS:AVER:COUN?")))
        if abs(f - freq_mhz * 1e6) > 1 or n != int(avg):
            raise RuntimeError(f"パワーメーターの設定が読み返しと違う（周波数 {f} Hz・平均 {n}）")
        self.check_err()
        self.freq_mhz, self.avg = freq_mhz, avg
        self.log(f"パワーメーター: 較正係数の周波数 {f / 1e6:.1f} MHz・平均 {n} 回・単位 dBm")

    def zero(self):
        """零点を取る。**入力に信号が無い状態で**（ノイズソースの電源を切る）。数秒かかる"""
        self.write("CAL:ZERO:AUTO ONCE")
        self.query("*OPC?")
        self.check_err()
        self.log("パワーメーター: 零点を取った")

    def read(self):
        v = float(self.query("READ?"))
        if abs(v) > 1e30:
            raise RuntimeError(f"パワーメーターの値が範囲の外（{v}）")
        return v


class Atten(Scpi):
    """Keysight J7211C（0〜100 dB）。set() は読み返して ±tol dB で確かめる"""

    def __init__(self, target=None, set_cmd="ATT {db}", get_cmd="ATT?", tol=0.01, timeout=5.0, log=print):
        super().__init__(target, "RFSOC_ATT", timeout, log, "アッテネータ")
        self.set_cmd, self.get_cmd, self.tol = set_cmd, get_cmd, tol

    def get(self):
        return float(self.query(self.get_cmd))

    def set(self, db):
        self.write(self.set_cmd.format(db=f"{db:.2f}"))
        time.sleep(0.05)
        got = self.get()
        if abs(got - db) > self.tol:
            raise RuntimeError(f"アッテネータが {got} dB（要求 {db} dB）。命令の形（set_cmd / get_cmd）をプログラミングガイドで確かめる")
        self.check_err()
        return got


class ManualAtten:
    """手で回すアッテネータ（または自動のものが使えないとき）。値を変えるたびに Enter を待つ"""

    def __init__(self, log=print):
        self.log, self.v = log, None
        self.idn = "手動"

    def set(self, db):
        input(f"アッテネータを {db:.1f} dB にして Enter: ")
        self.v = db
        return db

    def get(self):
        return self.v

    def close(self):
        pass

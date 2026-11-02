#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — 測定器を LAN の SCPI（raw socket、既定 5025 番）で操作する: パワーメーター（N1913A ＋ E9300A）とプログラムアッテネータ（J7211C）、
ノイズソースの電源（KIKUSUI PMX18-2A、ADR 0024）。
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
    with noise_off():                                                # ノイズソースを切る（環境変数 RFSOC_NS）。抜けたら必ず入れ直す
        ...

ノイズソースは**いつも ON**（ADR 0024）。OFF の要る測り（CW の応答・パワーメーターの零点）だけが道具の中で切り、終わりに入れ直す。
単体で: python3 instr.py ns state|on|off（off はそのまま切っておく。戻すのは on）
"""
import atexit
import contextlib
import os
import socket
import sys
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


class NoiseSource(Scpi):
    """ノイズソースの電源 KIKUSUI PMX18-2A（LAN の SCPI）。**既定は ON**（ADR 0024）: この道具が切ったら、close（atexit）で必ず入れ直す。
    電圧・電流の上限（と OVP）は前面パネルで決めておき、道具は変えない（読み返してログに残すだけ）。
    on() は出力と電流（≧ i_min）を読み返す: 電流が流れていなければ、ノイズソースがつながっていない（陽性対照を兼ねる）。
    on()・off() は出力の電圧が落ち着くまで待ってから戻る（PMX18-2A の実測で、立ち上がり・立ち下がりとも ≒ 1 s。
    0.5 s では 3.3 V・51 mA の途中だった）。戻った直後から測りを始めてよい"""

    def __init__(self, target=None, volt=None, i_min=0.005, timeout=5.0, log=print):
        super().__init__(target, "RFSOC_NS", timeout, log, "ノイズソースの電源")
        self.i_min, self._off_by_me = i_min, False
        self.v_set = float(self.query("VOLT?"))
        if volt is not None and abs(self.v_set - volt) > 0.05:
            raise RuntimeError(f"ノイズソースの電源の設定が {self.v_set:.2f} V（期待 {volt:.2f} V）。前面パネルで確かめる")
        v, i = self.measure()
        self.log(f"ノイズソースの電源: 設定 {self.v_set:.2f} V・出力 {'ON' if self.is_on() else 'OFF'}（{v:.2f} V・{i * 1e3:.1f} mA）")
        atexit.register(self.close)

    def is_on(self):
        return self.query("OUTP?").strip().upper() in ("1", "ON")

    def measure(self):
        return float(self.query("MEAS:VOLT?")), float(self.query("MEAS:CURR?"))

    def _wait(self, done, timeout):
        """done(v, i) が 2 回続けて真になるまで読み返す。戻り値 (落ち着いたか, v, i, かかった秒)"""
        t0, n = time.time(), 0
        while True:
            v, i = self.measure()
            n = n + 1 if done(v, i) else 0
            if n >= 2 or time.time() - t0 > timeout:
                return n >= 2, v, i, time.time() - t0
            time.sleep(0.1)

    def on(self, timeout=5.0):
        self.write("OUTP ON")
        if not self.is_on():
            raise RuntimeError("ノイズソースの電源の出力が ON にならない")
        ok, v, i, dt = self._wait(lambda v, i: v >= 0.98 * self.v_set and i >= self.i_min, timeout)
        if i < self.i_min:
            raise RuntimeError(f"ノイズソースに電流が流れていない（{i * 1e3:.1f} mA < {self.i_min * 1e3:.1f} mA）。つながっているか確かめる")
        if not ok:
            raise RuntimeError(f"ノイズソースの電源が {timeout:.0f} s で立ち上がらない（{v:.2f} V・設定 {self.v_set:.2f} V）")
        self.check_err()
        self._off_by_me = False
        self.log(f"ノイズソース: ON（{v:.2f} V・{i * 1e3:.1f} mA・{dt:.1f} s）")

    def off(self, keep=False, timeout=5.0):
        """keep = True: 終わりに入れ直さない（単体の off だけ）"""
        self.write("OUTP OFF")
        if self.is_on():
            raise RuntimeError("ノイズソースの電源の出力が OFF にならない")
        self._off_by_me = not keep
        ok, v, i, dt = self._wait(lambda v, i: v <= 0.02 * self.v_set and i < self.i_min, timeout)
        if not ok:
            raise RuntimeError(f"ノイズソースの電源が {timeout:.0f} s で下がらない（{v:.2f} V・{i * 1e3:.1f} mA）")
        self.check_err()
        self.log(f"ノイズソース: OFF（{v:.2f} V・{i * 1e3:.1f} mA・{dt:.1f} s）" + ("。そのまま切っておく" if keep else ""))

    def close(self):
        try:
            if self._off_by_me and self.s.fileno() >= 0:
                self.on()
        except Exception as e:                        # 入れ直せなかったことは必ず見えるように
            self.log(f"ERROR: ノイズソースを ON に戻せなかった: {e}。手で ON にする")
        finally:
            super().close()


@contextlib.contextmanager
def noise_off(target=None, log=print):
    """with の中だけノイズソースを切る。例外・sys.exit でも抜けたら入れ直す"""
    ns = NoiseSource(target, log=log)
    try:
        ns.off()
        yield ns
    finally:
        ns.close()


def main(argv):
    if len(argv) != 2 or argv[0] != "ns" or argv[1] not in ("state", "on", "off"):
        raise SystemExit("python3 instr.py ns state|on|off（宛先は環境変数 RFSOC_NS）")
    ns = NoiseSource()
    if argv[1] == "on":
        ns.on()
    elif argv[1] == "off":
        ns.off(keep=True)
    ns.close()


if __name__ == "__main__":
    main(sys.argv[1:])

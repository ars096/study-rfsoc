#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj003 — AnaPico APSYN420 を USBTMC で叩く（試験トーンの供給）。

**Vivado サーバ上で動かす。** ボード（PYNQ）ではなくサーバへ USB-B で繋ぐ前提。
依存は標準ライブラリのみ。カーネルの usbtmc ドライバが作る `/dev/usbtmc*` へ
直接 read/write する（pyvisa も AnaPico 純正ソフトも要らない）。

    python3 apsyn.py --probe                 # 何が繋がっているか。**まずこれ**
    python3 apsyn.py --preset bin            # 100.005 MHz（成功条件 3）
    python3 apsyn.py --preset leak           # 100.000 MHz（成功条件 4）
    python3 apsyn.py --preset fold           # 600 MHz（成功条件 5）
    python3 apsyn.py --freq 100.005MHz --power -10 --on
    python3 apsyn.py --off

**ADC を壊さないための約束**: 既定の出力は -10 dBm。RFSoC4x2 の ADC 入力の
フルスケールは +1 dBm 級しかない。0 dBm を超える設定には `--force` が要る。

権限（初回だけ。root なら不要）:

    lsusb                                    # AnaPico が見えるか
    ls -l /dev/usbtmc*                       # 無ければカーネルが掴んでいない
    sudo tee /etc/udev/rules.d/99-usbtmc.rules <<'RULE'
    SUBSYSTEM=="usbmisc", KERNEL=="usbtmc*", MODE="0660", GROUP="plugdev"
    RULE
    sudo udevadm control --reload && sudo udevadm trigger
    sudo usermod -aG plugdev $USER           # 再ログインが要る

読み出しのタイムアウトはカーネルドライバ既定（約 5 秒）に任せる。標準ライブラリだけで
安全に縮める手段が無いため、ここは踏み込まない。応答が無ければ OSError で落ちる。
"""

import argparse
import glob
import os
import re
import sys

# --------------------------------------------------------------- proj003 の固定値
# adc_capture.py と一致させること。ここがズレると期待ビンの表示が嘘になる。
FS_HZ = 983.04e6            # サンプリング周波数
N_FFT = 65536               # キャプチャ長
RBW_HZ = FS_HZ / N_FFT      # ちょうど 15 kHz

DEFAULT_DBM = -10.0
MAX_SAFE_DBM = 0.0          # これを超えるには --force

# preset 名 -> (周波数 [Hz], ナイキストゾーン, 狙い)
PRESETS = {
    "bin":  (RBW_HZ * 6667, 1, "ビン中心の CW。成功条件 3 — fs の裏取りそのもの"),
    "leak": (100.0e6,       1, "ビン中心から外す。成功条件 4 — リークと窓関数"),
    "fold": (600.0e6,       2, "第 2 ナイキストゾーン。成功条件 5 — 折返し"),
}


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------- USBTMC
class Usbtmc:
    """/dev/usbtmcN への最小の口。1 回の write / read が 1 メッセージに対応する。"""

    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDWR)

    def write(self, cmd):
        os.write(self.fd, (cmd.strip() + "\n").encode("ascii"))

    def read_raw(self, chunk=4096):
        parts = []
        for _ in range(8):
            b = os.read(self.fd, chunk)
            parts.append(b)
            if not b or b.endswith(b"\n") or len(b) < chunk:
                break
        return b"".join(parts)

    def query(self, cmd):
        self.write(cmd)
        return self.read_raw().decode("ascii", "replace").strip()

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


PERM_HINT = (
    "  権限が無い。udev ルールを入れるか sudo で実行する:\n"
    "    sudo tee /etc/udev/rules.d/99-usbtmc.rules <<'RULE'\n"
    "    SUBSYSTEM==\"usbmisc\", KERNEL==\"usbtmc*\", MODE=\"0660\", GROUP=\"plugdev\"\n"
    "    RULE\n"
    "    sudo udevadm control --reload && sudo udevadm trigger"
)


def open_apsyn(path=None):
    """AnaPico を名乗る /dev/usbtmc* を探して開く。見つからなければ理由を並べて終わる。"""
    candidates = [path] if path else sorted(glob.glob("/dev/usbtmc*"))
    if not candidates:
        log("ERROR: /dev/usbtmc* が無い。")
        log("  1. lsusb で AnaPico が見えるか（見えなければケーブルか電源）")
        log("  2. 見えているのにデバイスファイルが無ければ: sudo modprobe usbtmc")
        log("  3. dmesg | tail で usbtmc がアタッチされたか")
        sys.exit(1)

    reasons = []
    for p in candidates:
        try:
            dev = Usbtmc(p)
        except PermissionError as e:
            reasons.append(f"{p}: 開けない ({e})\n{PERM_HINT}")
            continue
        except OSError as e:
            reasons.append(f"{p}: 開けない ({e})")
            continue
        try:
            idn = dev.query("*IDN?")
        except OSError as e:
            dev.close()
            reasons.append(f"{p}: *IDN? に応答しない ({e})")
            continue
        if path or "anapico" in idn.lower():
            return dev, idn
        dev.close()
        reasons.append(f"{p}: AnaPico ではない → {idn}")

    log("ERROR: APSYN420 が見つからない。")
    for r in reasons:
        log("  " + r)
    log("  --dev /dev/usbtmcN で明示すると *IDN? の判定を飛ばして開く。")
    sys.exit(1)


# ------------------------------------------------------------------- 本体
class APSYN:
    """APSYN420 の必要最小限。設定した値は必ず読み返して突き合わせる。"""

    def __init__(self, dev, idn):
        self.dev = dev
        self.idn = idn

    # -- SCPI の薄い皮
    def query(self, cmd):
        return self.dev.query(cmd)

    def write(self, cmd):
        self.dev.write(cmd)

    def errors(self):
        """エラーキューを空になるまで吸い出す。空なら []。"""
        out = []
        for _ in range(20):
            r = self.query("SYST:ERR?")
            if re.match(r"^\s*[+-]?0\s*,", r) or "no error" in r.lower():
                break
            out.append(r)
        return out

    def raise_on_error(self, what):
        errs = self.errors()
        if errs:
            log(f"ERROR: {what} で機器がエラーを返した:")
            for e in errs:
                log(f"  {e}")
            sys.exit(1)

    # -- 設定値
    @property
    def frequency(self):
        return float(self.query("FREQ?"))

    @frequency.setter
    def frequency(self, hz):
        self.write(f"FREQ {hz:.6f} Hz")

    @property
    def power(self):
        return float(self.query("POW?"))

    @power.setter
    def power(self, dbm):
        self.write(f"POW {dbm:.2f} dBm")

    @property
    def output(self):
        return self.query("OUTP?").strip() not in ("0", "OFF", "off")

    @output.setter
    def output(self, on):
        self.write("OUTP ON" if on else "OUTP OFF")

    def limits(self):
        """機器に上下限を聞く。決め打ちしないのは機種・オプションで変わるため。"""
        lim = {}
        for key, cmd in (("fmin", "FREQ? MIN"), ("fmax", "FREQ? MAX"),
                         ("pmin", "POW? MIN"), ("pmax", "POW? MAX")):
            try:
                lim[key] = float(self.query(cmd))
            except (OSError, ValueError):
                lim[key] = None
        self.errors()          # 未対応なら溜まるので掃除する
        return lim

    def reference(self):
        """基準クロックまわり（proj004 の下見。読むだけ）。"""
        out = {}
        for key, cmd in (("source", "ROSC:SOUR?"),
                         ("ext_freq", "ROSC:EXT:FREQ?"),
                         ("locked", "ROSC:LOCK?")):
            try:
                out[key] = self.query(cmd)
            except OSError:
                out[key] = None
        self.errors()
        return out

    def settle(self):
        try:
            self.query("*OPC?")
        except OSError:
            pass


# ------------------------------------------------------------------- 補助
_UNITS = {"": 1.0, "hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}


def parse_freq(s):
    """'100.005MHz' / '100.005e6' / '100005000' のどれでも受ける。"""
    m = re.fullmatch(r"\s*([0-9.eE+-]+)\s*([A-Za-z]*)\s*", s)
    if not m:
        raise argparse.ArgumentTypeError(f"周波数として読めない: {s}")
    unit = m.group(2).lower()
    if unit not in _UNITS:
        raise argparse.ArgumentTypeError(f"単位が分からない: {m.group(2)}")
    try:
        return float(m.group(1)) * _UNITS[unit]
    except ValueError:
        raise argparse.ArgumentTypeError(f"周波数として読めない: {s}")


def expected_bin(f_hz, fs_hz=FS_HZ, n=N_FFT):
    """折返しを考慮した期待ビン。adc_capture.py の analyse() と同じ計算。"""
    rbw = fs_hz / n
    f = f_hz % fs_hz
    if f > fs_hz / 2:
        f = fs_hz - f
    return int(round(f / rbw)), f


def report_expectation(f_hz, zone):
    k, f_fold = expected_bin(f_hz)
    on_center = abs(f_hz % RBW_HZ) < 1e-3 or abs(RBW_HZ - (f_hz % RBW_HZ)) < 1e-3
    log("")
    log(f"fs = {FS_HZ / 1e6:.2f} MSPS / N = {N_FFT} / 分解能 {RBW_HZ / 1e3:.3f} kHz")
    log(f"期待ビン        : {k}  (= {k * RBW_HZ / 1e6:.6f} MHz)"
        f"{'' if abs(f_fold - f_hz) < 1 else f'  ← {f_hz / 1e6:.6f} MHz の折返し先'}")
    log(f"ビン中心         : {'乗っている（リーク無し）' if on_center else '**外れている**（スカートが出る。これが正常）'}")
    log("")
    log("ボード側:")
    log(f"  sudo python3 adc_capture.py --tone {f_hz / 1e6:.6f}"
        f"{'' if zone == 1 else f' --zone {zone}'}")


# ------------------------------------------------------------------- probe
def do_probe(sg):
    log(f"*IDN?           : {sg.idn}")
    lim = sg.limits()
    if lim["fmin"] is not None and lim["fmax"] is not None:
        log(f"周波数範囲      : {lim['fmin'] / 1e6:.3f} 〜 {lim['fmax'] / 1e9:.3f} GHz")
    else:
        log("周波数範囲      : 読めない（FREQ? MIN/MAX 未対応）")
    if lim["pmin"] is not None and lim["pmax"] is not None:
        log(f"出力範囲        : {lim['pmin']:.2f} 〜 {lim['pmax']:.2f} dBm")
    else:
        log("出力範囲        : 読めない（POW? MIN/MAX 未対応）")

    log("")
    log("--- 現在の設定 ---")
    try:
        log(f"FREQ            : {sg.frequency / 1e6:.6f} MHz")
        log(f"POW             : {sg.power:.2f} dBm")
        log(f"OUTP            : {'ON' if sg.output else 'OFF'}")
    except (OSError, ValueError) as e:
        log(f"ERROR: 設定を読めない: {e}")
        sys.exit(1)

    ref = sg.reference()
    log("")
    log("--- 基準クロック（proj004 の下見。読むだけ） ---")
    for k, v in ref.items():
        log(f"{k:<16}: {v if v is not None else '(読めない)'}")

    errs = sg.errors()
    if errs:
        log("")
        log("残っていたエラー:")
        for e in errs:
            log(f"  {e}")


# --------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dev", default=None,
                   help="/dev/usbtmcN を明示する（*IDN? の判定を飛ばす）")
    p.add_argument("--probe", action="store_true",
                   help="繋がっているものと現在の設定を出して終わる")
    p.add_argument("--preset", choices=sorted(PRESETS),
                   help="proj003 の成功条件に対応する設定を一発で出す")
    p.add_argument("--freq", type=parse_freq, default=None,
                   help="周波数。'100.005MHz' / '100.005e6' / '100005000'")
    p.add_argument("--power", type=float, default=None,
                   help=f"出力 [dBm]。既定 {DEFAULT_DBM}")
    p.add_argument("--zone", type=int, default=None, choices=(1, 2),
                   help="期待ビンの表示用。adc_capture.py の --zone と揃える")
    p.add_argument("--on", dest="output", action="store_const", const=True,
                   help="RF 出力を入れる")
    p.add_argument("--off", dest="output", action="store_const", const=False,
                   help="RF 出力を切る")
    p.add_argument("--force", action="store_true",
                   help=f"{MAX_SAFE_DBM:.1f} dBm を超える出力を許す（ADC 保護の解除）")
    p.add_argument("--list-presets", action="store_true")
    args = p.parse_args()

    if args.list_presets:
        for name, (f, z, why) in sorted(PRESETS.items()):
            k, _ = expected_bin(f)
            log(f"{name:<6} {f / 1e6:>11.6f} MHz  zone {z}  bin {k:<6}  {why}")
        return

    if args.preset:
        f, z, why = PRESETS[args.preset]
        if args.freq is None:
            args.freq = f
        if args.zone is None:
            args.zone = z
        if args.output is None:
            args.output = True
        log(f"preset '{args.preset}': {why}")

    if args.zone is None:
        args.zone = 1

    # ADC 保護。指定が無ければ既定値を使い、それも含めて上限を見る。
    dbm = args.power if args.power is not None else DEFAULT_DBM
    if dbm > MAX_SAFE_DBM and not args.force:
        log(f"ERROR: {dbm:.2f} dBm は ADC のフルスケール（+1 dBm 級）に近すぎる。")
        log(f"  {MAX_SAFE_DBM:.1f} dBm 以下にするか、承知の上なら --force を付ける。")
        sys.exit(1)

    dev, idn = open_apsyn(args.dev)
    with dev:
        sg = APSYN(dev, idn)
        sg.errors()                       # 前回の残りを掃除してから始める

        if args.probe or (args.freq is None and args.power is None
                          and args.output is None):
            do_probe(sg)
            return

        log(f"*IDN?           : {sg.idn}")

        lim = sg.limits()
        if args.freq is not None:
            if lim["fmin"] is not None and not (lim["fmin"] <= args.freq <= lim["fmax"]):
                log(f"ERROR: {args.freq / 1e6:.6f} MHz は機器の範囲外 "
                    f"({lim['fmin'] / 1e6:.3f} 〜 {lim['fmax'] / 1e9:.3f} GHz)")
                sys.exit(1)
            sg.frequency = args.freq
            sg.raise_on_error("FREQ の設定")

        if args.freq is not None or args.power is not None:
            if lim["pmax"] is not None and not (lim["pmin"] <= dbm <= lim["pmax"]):
                log(f"ERROR: {dbm:.2f} dBm は機器の範囲外 "
                    f"({lim['pmin']:.2f} 〜 {lim['pmax']:.2f} dBm)")
                sys.exit(1)
            sg.power = dbm
            sg.raise_on_error("POW の設定")

        if args.output is not None:
            sg.output = args.output
            sg.raise_on_error("OUTP の設定")

        sg.settle()

        # **読み返して突き合わせる。** 設定できたことと、そう設定されたことは別。
        f_rb, p_rb, o_rb = sg.frequency, sg.power, sg.output
        log(f"FREQ            : {f_rb / 1e6:.6f} MHz")
        log(f"POW             : {p_rb:.2f} dBm")
        log(f"OUTP            : {'ON' if o_rb else 'OFF'}")

        if args.freq is not None and abs(f_rb - args.freq) > 1.0:
            log(f"WARNING: 指定 {args.freq / 1e6:.6f} MHz に対し読み返しが "
                f"{f_rb / 1e6:.6f} MHz。機器が丸めている")
        if abs(p_rb - dbm) > 0.05 and (args.freq is not None or args.power is not None):
            log(f"WARNING: 指定 {dbm:.2f} dBm に対し読み返しが {p_rb:.2f} dBm")

        sg.raise_on_error("読み返し")

        if o_rb:
            report_expectation(f_rb, args.zone)
        else:
            log("")
            log("NOTE: RF 出力は OFF のまま。--on で入れる")


if __name__ == "__main__":
    main()

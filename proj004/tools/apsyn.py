#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj004 — AnaPico APSYN420 を USBTMC で叩く（試験トーンの供給）。

**Vivado サーバ上で動かす。** ボード（PYNQ）ではなくサーバへ USB-B で繋ぐ前提。
依存は標準ライブラリのみ。カーネルの usbtmc ドライバが作る `/dev/usbtmc*` へ
直接 read/write する（pyvisa も AnaPico 純正ソフトも要らない）。

    python3 apsyn.py --probe                 # 何が繋がっているか。**まずこれ**
    python3 apsyn.py --ref ext --ref-freq 10MHz   # **外部基準に切り替える（proj004）**
    python3 apsyn.py --ref int               # 内部基準に戻す
    python3 apsyn.py --ref-out on            # **REF OUT を出す（ボードの CLK_IN へ配る）**
    python3 apsyn.py --raw-query 'SYST:HELP:HEAD?'   # 機器のコマンド一覧（対応機種のみ）
    python3 apsyn.py --preset bin            # 100.0125 MHz（ビン中心）
    python3 apsyn.py --preset leak           # 100.000 MHz（ビン中心から外す）
    python3 apsyn.py --preset fold           # 800 MHz（第 2 ゾーン → 428.8 MHz）
    python3 apsyn.py --freq 100.0125MHz --power -10 --on

**proj004 では SG の 10 MHz 基準入力を、ボードと同じ外部基準に繋ぐこと。**
繋がなければ ppm は 0 に潰れない（SG 自身の確度に置き換わるだけ）。
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
import time

# --------------------------------------------------------------- proj004 の固定値
# adc_capture.py と一致させること。ここがズレると期待ビンの表示が嘘になる。
# **proj003 の途中まで fs = 983.04 MSPS だったが、RFDC の Sampling Rate の
# 有効範囲 (1.0, 5.0) GSPS に弾かれて 1228.8 MSPS になった。** apsyn.py だけが
# 古い値のまま残っており、preset の周波数がビン中心から 0.6 ビンずれていた
# （2026-09-17 に proj004 で発見）。ここは adc_capture.py の FS_HZ と必ず一致させる。
FS_HZ = 1228.8e6            # サンプリング周波数（adc_capture.py と一致させること）
N_FFT = 65536               # キャプチャ長
RBW_HZ = FS_HZ / N_FFT      # ちょうど 18.75 kHz

DEFAULT_DBM = -10.0
MAX_SAFE_DBM = 0.0          # これを超えるには --force

# preset 名 -> (周波数 [Hz], ナイキストゾーン, 狙い)
# **fs = 1228.8 MSPS では第 1 ゾーンが DC〜614.4 MHz。** 600 MHz は第 1 ゾーンに
# 入ってしまうので、折返しを見るには 800 MHz（→ 428.8 MHz に折り返す）を使う。
PRESETS = {
    "bin":  (RBW_HZ * 5334, 1, "ビン中心の CW（100.0125 MHz）。proj003 で実証した設定"),
    "leak": (100.0e6,       1, "ビン中心から外す。リークと窓関数"),
    "fold": (800.0e6,       2, "第 2 ナイキストゾーン（→ 428.8 MHz に折返し）"),
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

    # REF OUT の綴りは機種・ファーム依存。**マニュアルが手に入らないので機器に聞く。**
    # 書いたあと SYST:ERR? が空で、かつ読み返しが一致したものを採用する。
    REF_OUT_FORMS = (
        ("ROSC:OUTP:STAT", "ROSC:OUTP:STAT?"),
        ("ROSC:OUTP:STATE", "ROSC:OUTP:STATE?"),
        ("ROSC:OUTP", "ROSC:OUTP?"),
        ("OUTP:ROSC:STAT", "OUTP:ROSC:STAT?"),
    )

    def set_ref_out(self, on, freq_hz=None):
        """基準クロックの出力（REF OUT）を入／切する。

        **APSYN420 の REF OUT は既定で出ていないことがある。** ボードの CLK_IN に
        SG の REF OUT を配る構成では、これを入れないと何も出ない
        （2026-09-17 にスペアナで無出力を確認して判明）。

        戻り値は (採用した綴り, 読み返し, 一致したか, 試して駄目だった綴り)。
        """
        want = "ON" if on else "OFF"
        tried = []

        if freq_hz is not None:
            self.errors()
            self.write(f"ROSC:OUTP:FREQ {freq_hz:.0f} Hz")
            errs = self.errors()
            if errs:
                tried.append(("ROSC:OUTP:FREQ", errs[0]))

        for setc, getc in self.REF_OUT_FORMS:
            self.errors()                      # 直前の残りを掃除してから試す
            try:
                self.write(f"{setc} {want}")
            except OSError as e:
                tried.append((setc, f"書けない: {e}"))
                continue
            errs = self.errors()
            if errs:
                tried.append((setc, errs[0]))
                continue
            try:
                rb = self.query(getc).strip()
            except OSError as e:
                # 書けたがクエリが通らない綴りもある。書けた事実は残す。
                self.errors()
                return setc, None, None, tried
            self.errors()
            ok = (rb.upper() in ("1", "ON")) == bool(on)
            return setc, rb, ok, tried

        return None, None, None, tried

    def set_reference(self, source, ext_freq_hz=10e6, settle=2.0):
        """基準クロックを内部／外部に切り替える。

        **順序が重要。** 先に外部基準の周波数を教えてから SOUR EXT にする。
        逆にすると、機器は直前の設定（出荷時は 100 MHz）で 10 MHz を掴もうとして
        ロックしない。「切り替えたのにロックしない」の大半はこれ。

        切り替え後は ROSC:LOCK? を読んで確かめる。**設定できたことと、
        そう動いていることは別。**
        """
        source = source.upper()
        if source not in ("INT", "EXT"):
            raise ValueError(source)
        if source == "EXT":
            self.write(f"ROSC:EXT:FREQ {ext_freq_hz:.0f} Hz")
            self.raise_on_error("ROSC:EXT:FREQ の設定")
        self.write(f"ROSC:SOUR {source}")
        self.raise_on_error("ROSC:SOUR の設定")
        self.settle()
        time.sleep(settle)          # PLL が引き込むまで待つ

    def reference(self):
        """基準クロックまわりを読む。"""
        out = {}
        for key, cmd in (("source", "ROSC:SOUR?"),
                         ("ext_freq", "ROSC:EXT:FREQ?"),
                         ("locked", "ROSC:LOCK?"),
                         ("out_state", "ROSC:OUTP:STAT?"),
                         ("out_freq", "ROSC:OUTP:FREQ?")):
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
    log("--- 基準クロック ---")
    for k, v in ref.items():
        log(f"{k:<16}: {v if v is not None else '(読めない)'}")
    report_reference(ref)

    errs = sg.errors()
    if errs:
        log("")
        log("残っていたエラー:")
        for e in errs:
            log(f"  {e}")


def report_reference(ref, want_ext_hz=None):
    """基準クロックの状態を読んで、proj004 として成立しているかを言う。"""
    src = (ref.get("source") or "").strip().upper()
    locked = (ref.get("locked") or "").strip()
    try:
        ext = float(ref.get("ext_freq"))
    except (TypeError, ValueError):
        ext = None

    log("")
    if src.startswith("INT"):
        log("**SG は内部基準（INT）で動いている。**")
        log("  このままだと ppm は 0 に潰れない。ppm は SG とボードの周波数差なので、")
        log("  ボードだけ外部基準にしても「SG 自身の確度」に置き換わるだけ。")
        log("  → 外部基準に切り替える: python3 apsyn.py --ref ext --ref-freq 10MHz")
        return False

    ok = True
    if ext is not None and want_ext_hz is not None and abs(ext - want_ext_hz) > 1.0:
        log(f"**ext_freq が {ext / 1e6:g} MHz のまま。** 入れている基準と違う。")
        log("  --ref-freq で実際に入れている周波数を指定すること")
        ok = False
    if locked not in ("1", "ON", "on"):
        log(f"**ROSC:LOCK? = {locked}。外部基準にロックしていない。**")
        log("  ケーブル・レベル・周波数（ext_freq）を疑う。この状態の測定は使えない")
        ok = False
    if ok:
        log(f"外部基準にロックしている（{'' if ext is None else f'{ext / 1e6:g} MHz'}）。")
        log("**ボード側も同じ基準に繋がっていれば、ppm は 0 付近に潰れるはず。**")
    return ok


# --------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dev", default=None,
                   help="/dev/usbtmcN を明示する（*IDN? の判定を飛ばす）")
    p.add_argument("--probe", action="store_true",
                   help="繋がっているものと現在の設定を出して終わる")
    p.add_argument("--ref", choices=("int", "ext"), default=None,
                   help="基準クロックを内部／外部に切り替える。"
                        "**proj004 では ext にしてボードと同じ 10 MHz を入れる**")
    p.add_argument("--ref-freq", type=parse_freq, default=10e6,
                   help="外部基準の周波数（既定 10MHz）。--ref ext のとき先に設定される")
    p.add_argument("--ref-out", choices=("on", "off"), default=None,
                   help="**REF OUT（基準クロック出力）を入／切する。** "
                        "ボードの CLK_IN に SG の REF OUT を配るなら on が要る")
    p.add_argument("--ref-out-freq", type=parse_freq, default=None,
                   help="REF OUT の周波数（機種が対応していれば）。既定は触らない")
    p.add_argument("--raw", default=None,
                   help="任意の SCPI を書く（応答を待たない）。機器を直接叩くための逃げ道")
    p.add_argument("--raw-query", default=None,
                   help="任意の SCPI を問い合わせて応答を出す（例: 'SYST:HELP:HEAD?'）")
    p.add_argument("--preset", choices=sorted(PRESETS),
                   help="proj004 の成功条件に対応する設定を一発で出す")
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

        if args.raw is not None:
            log(f"*IDN?           : {sg.idn}")
            log(f"write           : {args.raw}")
            sg.write(args.raw)
            errs = sg.errors()
            log("エラー          : " + (", ".join(errs) if errs else "なし"))
            if args.raw_query is None:
                return

        if args.raw_query is not None:
            log(f"query           : {args.raw_query}")
            try:
                log(f"応答            : {sg.query(args.raw_query)}")
            except OSError as e:
                log(f"応答            : (返ってこない: {e})")
            errs = sg.errors()
            log("エラー          : " + (", ".join(errs) if errs else "なし"))
            return

        if args.ref_out is not None:
            on = args.ref_out == "on"
            log(f"*IDN?           : {sg.idn}")
            log(f"REF OUT を {'入' if on else '切'} にする"
                + (f"（{args.ref_out_freq / 1e6:g} MHz）" if args.ref_out_freq else ""))
            used, rb, ok, tried = sg.set_ref_out(on, args.ref_out_freq)
            for form, why in tried:
                log(f"  {form:<18} 不可: {why}")
            if used is None:
                log("")
                log("ERROR: REF OUT を操作する綴りが見つからない。")
                log("  `--raw-query 'SYST:HELP:HEAD?'` でコマンド一覧が出る機種もある。")
                log("  出なければ前面パネルか AnaPico のプログラマーズマニュアルで確認する")
                sys.exit(1)
            log(f"  採用した綴り    : {used} {'ON' if on else 'OFF'}")
            log(f"  読み返し        : {rb if rb is not None else '(クエリ非対応)'}")
            if ok is False:
                log("  **読み返しが一致しない。効いていない可能性がある**")
            log("")
            log("**スペアナか周波数カウンタで REF OUT に信号が出ていることを確かめる。**")
            log("  書けたことと出ていることは別。ここを飛ばすと、ボード側で")
            log("  「PLL1 がロックしない」を延々と追うことになる。")
            if args.ref is None and args.freq is None and args.power is None \
                    and args.output is None:
                ref = sg.reference()
                log("")
                log("--- 基準クロック ---")
                for k, v in ref.items():
                    log(f"{k:<16}: {v if v is not None else '(読めない)'}")
                return

        if args.ref is not None:
            log(f"*IDN?           : {sg.idn}")
            log(f"基準クロックを {args.ref.upper()} に切り替える"
                + (f"（外部 {args.ref_freq / 1e6:g} MHz）" if args.ref == "ext" else ""))
            sg.set_reference(args.ref, args.ref_freq)
            ref = sg.reference()
            log("")
            log("--- 読み返し ---")
            for k, v in ref.items():
                log(f"{k:<16}: {v if v is not None else '(読めない)'}")
            ok = report_reference(ref, args.ref_freq if args.ref == "ext" else None)
            if args.ref == "ext" and not ok:
                sys.exit(1)
            if args.freq is None and args.power is None and args.output is None:
                return

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

#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj004 — LMK04828 の PLL1 基準を外部 10 MHz（CLK_IN の SMA）に切り替える。

使い方（ボード上で sudo が要る）:

    sudo python3 extref.py --api             # ボードの xrfclk が実際に持っている名前
    sudo python3 extref.py --show            # 出荷時の設定を読み出して意味を表示する
    sudo python3 extref.py --set stock       # 出荷時に戻す（CLKin1 = 基板の Si5395）
    sudo python3 extref.py --set 0           # CLKin0 を PLL1 の基準にする
    sudo python3 extref.py --set 1           # CLKin1（＝出荷時と同じ）
    sudo python3 extref.py --set 2           # CLKin2

**このスクリプトは書き込むだけで、書けたことを確認できない**（下記）。
効いたかどうかの判定は `adc_capture.py` で ppm を測って行う。


なぜこれが要るのか
==================

proj003 で測ったクロックのずれ **+14.92 ppm** は、ボードのクロック源の確度そのもの
である。RFSoC 4x2 の系統は

    48 MHz XO ─▶ Si5395 ─(10 MHz)─▶ LMK04828 PLL1 ─▶ 160 MHz VCXO
                                        └ PLL2 ─▶ 2457.6 MHz ─┬─ 245.76 MHz ─▶ LMX2594
                                                              └ 122.88 MHz ─▶ PL
                                     LMX2594 ─(491.52 MHz)─▶ RFDC ─▶ fs = 1228.8 MSPS

で、**先頭の 48 MHz 水晶は ±15 ppm 品**。実測 +14.92 ppm はこれで説明がつく。
LMK04828 の PLL1 の基準を、Si5395 の 10 MHz から **CLK_IN の SMA に入れた外部
10 MHz** に切り替えれば、fs の確度は外部基準のものになる。


出荷時に何が設定されているか
============================

xrfclk が書き込む `LMK04828_245.76.txt` の中身を読むと、こうなっている。

| レジスタ | 値 | 意味 |
|---|---|---|
| `0x0147` | `0x1A` | **CLKin_SEL_MODE = 1（CLKin1 manual）**／CLKin0・CLKin1 とも PLL1 へ |
| `0x0153/54` | 0x00 / 0x7D | CLKin0_R = **125** → 10 MHz / 125 = 80 kHz |
| `0x0155/56` | 0x00 / 0x7D | CLKin1_R = **125** → 10 MHz 前提 |
| `0x0157/58` | 0x03 / 0xC0 | CLKin2_R = 960 → 76.8 MHz 前提 |
| `0x0159/5A` | 0x07 / 0xD0 | PLL1_N = **2000** → 80 kHz × 2000 = 160 MHz（VCXO） |

**CLKin0 と CLKin1 は両方とも 10 MHz 前提で分周比が入っている。** 出荷時に選ばれて
いるのは CLKin1 で、ケーブルを挿さなくても PLL1 がロックする以上、**CLKin1 が基板上の
Si5395 の 10 MHz**である。したがって **CLK_IN の SMA は CLKin0 の可能性が高い**。

ただし **これは推定であって裏取りではない。** proj003 で「SMA のラベルとスライス番号の
並びが逆だった」ことを踏んでいる。**配線図の読みで設計を決めず、実信号で確かめる。**
`--set 0` と `--set 1` の両方で ppm を測れば、どちらが SMA かは一意に決まる。


`0x0147` の中身
===============

    bit [6:4] CLKin_SEL_MODE   0 = CLKin0 manual / 1 = CLKin1 manual /
                               2 = CLKin2 manual / 4 = auto
    bit [3:2] CLKin1_DEMUX     2 = PLL1 へ
    bit [1:0] CLKin0_DEMUX     2 = PLL1 へ

    0x0A = CLKin0 manual、両方 PLL1 へ
    0x1A = CLKin1 manual、両方 PLL1 へ  ← 出荷時
    0x2A = CLKin2 manual、両方 PLL1 へ

出典は Ettus Research の UHD にある LMK04828 の初期化列（`lmk_mg.py` の
`(0x147, 0x1A)  # CLKin_SEL = CLKin1 manual; CLKin1 to PLL1` と
`x4xx_sample_pll.py` の `(0x0147, 0x06)  # CLKin_SEL_MANUAL = CLKin0, ...`）。
**TI のデータシートの表そのものではなく、実機で動いている初期化列からの復元**なので、
`bit[6:4]` の上位 1 bit（auto モード側）は本 proj では使わない。


**書いた結果を読み返せない**
============================

このリポジトリは「設定したら読み返して検証する」を原則にしている（`build.tcl` が
RFDC の CONFIG でやっているのと同じ）。**LMK04828 ではそれができない。**

- `xrfclk` は SPI を書くだけで、読み出しの口を持たない
- LMK04828 の読み返しは 4 線モードで別ピンに出す方式で、そのピンが RFSoC 4x2 の
  どこへ行っているかは未確認。無理に有効化すると `Status_LD1`（PLL1 ロック LED）の
  出力を潰しかねない

そこで proj004 の検証は **2 系統の外側の証拠**で行う。

1. **ボードの PLL1 ロック LED**（LMK の `Status_LD1` が出ている。`0x015F = 0x0B` =
   PLL1 DLD → push-pull 出力）。外部基準が無いのに CLKin0 を選べば消えるはず
2. **取得波形の ppm**（`adc_capture.py`）。これが本命

**「クロックが出ている」ことは外部基準が効いている証拠にならない。** 外部基準を
失っても PLL2 は VCXO で出力を作り続ける（ホールドオーバーもある）。だから
「動いているように見える」。**ppm を測る以外に判定手段は無い。**


`xrfclk` の落とし穴
===================

`xrfclk._read_tics_output()` は、パッケージのディレクトリにある `*.txt` を
**ファイル名を `_` で 2 分割して** `チップ名_周波数.txt` と解釈する。

    chip, freq = s.lower().split('/')[-1].strip('.txt').split('_')

したがって `rfsoc4x2_lmk_CLKin0_extref_10M_....txt` のような名前のファイルを
そのディレクトリに置くと、**`set_ref_clks()` が `ValueError: too many values to
unpack` で落ちる**。CASPER 系の検証済みファイルをそのまま置くやり方は、この版では
成立しない。

そこで本スクリプトは **xrfclk のディレクトリに何も足さない**。出荷時のファイルを
その場で読み、必要なレジスタだけ差し替えて `xrfclk._write_LMK_regs()` に渡す。
**差分が何バイトなのかがコードに残る**ので、後から何を変えたのか分かる。

なお RFSoC 4x2 の PYNQ イメージは `xrfclk` にパッチが当たっており、
`_read_tics_output()` が `set_ref_clks()` のたびに走る（出荷時の Xilinx 版は初回のみ）。
"""

import argparse
import glob
import os
import re
import sys
import time

# --------------------------------------------------------------- 固定値
LMK_FREQ = 245.76          # xrfclk のファイル名に使われている周波数（LMK04828_245.76.txt）
LMX_FREQ = 491.52          # LMX2594 → RFDC の基準
VCXO_MHZ = 160.0           # LMK の外付け VCXO
PLL1_N = 2000              # 0x0159/0x015A の値。VCXO / PLL1_PD
PLL1_PD_MHZ = VCXO_MHZ / PLL1_N        # = 0.08 MHz

REG_CLKIN_SEL = 0x0147
REG_R_DIV = {0: (0x0153, 0x0154),      # (MSB[5:0], LSB)
             1: (0x0155, 0x0156),
             2: (0x0157, 0x0158)}
REG_PLL1_N = (0x0159, 0x015A)
REG_PLL1_LD = 0x015F
REG_HOLDOVER = 0x014B

DEMUX_PLL1 = 0b10
STOCK_CLKIN = 1            # 出荷時に選ばれている CLKin

SOURCE_NAME = {
    0: "CLKin0（CLK_IN の SMA と推定。**要実測**）",
    1: "CLKin1（基板上の Si5395 が出す 10 MHz と推定。出荷時の選択）",
    2: "CLKin2（出荷時は 76.8 MHz 前提の分周比。用途不明）",
}


def log(*a):
    print(*a, flush=True)


# ----------------------------------------------------- TICS ファイルの読み書き
def find_stock_lmk_file():
    """xrfclk が実際に使っている LMK04828 のレジスタファイルを探す。

    **proj004 にコピーを持たず、その場で読む。** ボードのイメージを焼き直したときに
    中身が変わっていれば、こちらも自動的に追随する。ズレたまま気づかないのが一番怖い。
    """
    try:
        import xrfclk
    except ImportError:
        raise RuntimeError(
            "xrfclk が import できない。ボード上で sudo -E $(which python3) で実行すること。"
            "手元でファイルの中身だけ見たいなら --file でパスを渡す")
    d = os.path.dirname(os.path.realpath(xrfclk.__file__))
    hits = sorted(glob.glob(os.path.join(d, "LMK04828_*.txt")))
    if not hits:
        raise RuntimeError(f"LMK04828_*.txt が {d} に無い")
    want = os.path.join(d, f"LMK04828_{LMK_FREQ}.txt")
    return want if want in hits else hits[0]


def find_stock_lmx_file():
    """LMX2594 のレジスタファイル。見つからなければ None（致命ではない）。"""
    xrfclk = _import_xrfclk()
    d = os.path.dirname(os.path.realpath(xrfclk.__file__))
    want = os.path.join(d, f"LMX2594_{LMX_FREQ}.txt")
    if os.path.exists(want):
        return want
    hits = sorted(glob.glob(os.path.join(d, "LMX2594_*.txt")))
    return hits[0] if hits else None


def read_tics(path):
    """TICS Pro の出力（1 行 1 レジスタ）を 24bit 整数の **並び順のまま** 返す。

    並び順には意味がある。先頭の `R0 (INIT) 0x000090` はリセットで、同じ 0x0000 が
    直後にもう一度出てくる。**アドレスで辞書にすると壊れる。**
    """
    regs = []
    with open(path) as f:
        for line in f:
            m = re.search(r"(0x[0-9A-Fa-f]{6})", line)
            if m:
                regs.append(int(m.group(1), 16))
    if not regs:
        raise RuntimeError(f"レジスタが 1 つも読めない: {path}")
    return regs


def split(word):
    return (word >> 8) & 0x1FFF, word & 0xFF


def join(addr, data):
    return ((addr & 0x1FFF) << 8) | (data & 0xFF)


def get_reg(regs, addr, which=-1):
    """指定アドレスの値を取り出す。複数あれば which 番目（既定は最後）。"""
    vals = [split(w)[1] for w in regs if split(w)[0] == addr]
    return vals[which] if vals else None


# ------------------------------------------------------------- 差し替え
def patch_regs(regs, clkin, ref_mhz=10.0):
    """PLL1 の基準入力を clkin に切り替えたレジスタ列を返す。

    触るのは **2 種類 3 バイトだけ**。
      - 0x0147        どの CLKin を PLL1 に入れるか
      - CLKinX_R      基準周波数 / 位相比較周波数（80 kHz）になる分周比

    **PLL1_N・VCXO・PLL2 以降は一切触らない。** 位相比較周波数を出荷時と同じ
    80 kHz に保つので、ループフィルタの定数（基板上の部品）がそのまま成立する。
    ここを変えると PLL1 の帯域が変わり、ロックしない・ロックが遅いといった症状に化ける。
    """
    if clkin not in REG_R_DIV:
        raise ValueError(f"clkin は 0/1/2: {clkin}")

    r_div = ref_mhz / PLL1_PD_MHZ
    if abs(r_div - round(r_div)) > 1e-9:
        raise ValueError(
            f"基準 {ref_mhz} MHz は位相比較周波数 {PLL1_PD_MHZ} MHz で割り切れない "
            f"(R = {r_div})。PLL1_N を変えずに済む基準周波数を使うこと")
    r_div = int(round(r_div))
    if not 1 <= r_div <= 0x3FFF:
        raise ValueError(f"R 分周 {r_div} が 14bit に収まらない")

    sel = (clkin << 4) | (DEMUX_PLL1 << 2) | DEMUX_PLL1
    msb_addr, lsb_addr = REG_R_DIV[clkin]
    want = {REG_CLKIN_SEL: sel,
            msb_addr: (r_div >> 8) & 0x3F,
            lsb_addr: r_div & 0xFF}

    out, changed = [], []
    for w in regs:
        addr, data = split(w)
        if addr in want and want[addr] != data:
            changed.append((addr, data, want[addr]))
            out.append(join(addr, want[addr]))
        else:
            out.append(w)

    missing = [a for a in want if not any(split(w)[0] == a for w in regs)]
    if missing:
        raise RuntimeError(
            "元のレジスタ列に " + ", ".join(f"0x{a:04X}" for a in missing) +
            " が無い。ファイルの版が想定と違う")
    return out, changed, r_div


# --------------------------------------------------------------- 書き込み
def _import_xrfclk():
    try:
        import xrfclk
    except ImportError:
        raise RuntimeError(
            "xrfclk が import できない。**ボード上で** sudo -E $(which python3) で実行すること")
    return xrfclk


def _set_ref_clks(xrfclk):
    """出荷時の設定を公開 API で書く。**版で関数名が変わる。**

    v3.1.1 は `set_ref_clks`、旧版は `set_ref_clk`。
    """
    for name in ("set_ref_clks", "set_ref_clk"):
        fn = getattr(xrfclk, name, None)
        if fn is not None:
            fn(lmk_freq=LMK_FREQ, lmx_freq=LMX_FREQ)
            return name
    raise RuntimeError(
        "xrfclk に set_ref_clks / set_ref_clk のどちらも無い。"
        f"使える名前: {api_names(xrfclk)}")


def api_names(xrfclk):
    return sorted(n for n in dir(xrfclk) if not n.startswith("__"))


def _devices(xrfclk, kind):
    """lmk_devices / lmx_devices を取り出す。

    **`_find_devices()` を自分で呼ばない。** 版によっては存在しないし、
    存在しても append するだけなので 2 回呼ぶとデバイスが重複して SPI を 2 度書く。
    公開 API（`set_ref_clks`）を先に通しておけば、その副作用で埋まっている。
    """
    devs = getattr(xrfclk, f"{kind}_devices", None)
    if not devs:
        raise RuntimeError(
            f"xrfclk.{kind}_devices が空。set_ref_clks() が通っていないか、"
            f"この版は別の持ち方をしている。使える名前: {api_names(xrfclk)}")
    return devs


def _writer(xrfclk, kind):
    """レジスタ列を直接書く関数を探す。無ければ名前一覧を添えて止まる。"""
    for name in (f"_write_{kind}_regs", f"write_{kind}_regs"):
        fn = getattr(xrfclk, name, None)
        if fn is not None:
            return fn, name
    return None, None


def set_clocks(clkin=None, ref_mhz=10.0, settle=2.0, verbose=True):
    """クロックを設定する。clkin=None なら出荷時のまま。

    **順序が重要。** LMK を書き換えると出力が一度乱れ、下流の LMX2594 はロックを失う。
    先に LMK を落ち着かせてから LMX を書く。逆にすると LMX が乱れた基準の上で VCO
    キャリブレーションを走らせることになり、「たまに立ち上がらない」になる。

    **この関数は Overlay() より前に呼ぶこと。** RFDC のタイルはビットストリームを
    ロードした時点で起動し、そのとき LMX の 491.52 MHz を掴む（proj003 で確認）。
    先にクロックを確定させておけば、タイルに触る必要がない。
    """
    xrfclk = _import_xrfclk()

    # **まず必ず出荷時の設定を公開 API で通す。**
    # デバイスの探索とバインドはここで済み、LMK も LMX もロックした状態になる。
    # 私有関数の名前は版で変わるが、この 1 本だけはどの版にもある。
    used = _set_ref_clks(xrfclk)
    if verbose:
        log(f"xrfclk.{used}(lmk_freq={LMK_FREQ}, lmx_freq={LMX_FREQ})   ← 出荷時の設定")

    if clkin is None:
        if verbose:
            log(f"クロック源 : **出荷時のまま**（{SOURCE_NAME[STOCK_CLKIN]}）")
        return None

    stock_path = find_stock_lmk_file()
    regs = read_tics(stock_path)
    if verbose:
        log(f"LMK のレジスタファイル : {stock_path}  ({len(regs)} 語)")
        log(f"  出荷時 0x0147 = 0x{get_reg(regs, REG_CLKIN_SEL):02X}"
            f"  → CLKin_SEL_MODE = {(get_reg(regs, REG_CLKIN_SEL) >> 4) & 0x7}")

    regs, changed, r_div = patch_regs(regs, clkin, ref_mhz)
    if verbose:
        log(f"クロック源 : {SOURCE_NAME[clkin]}")
        log(f"  基準 {ref_mhz} MHz / R = {r_div} / 位相比較 {PLL1_PD_MHZ * 1e3:.0f} kHz "
            f"/ PLL1_N = {PLL1_N} → VCXO {VCXO_MHZ} MHz")
        if changed:
            log("  差し替えたレジスタ:")
            for addr, old, new in changed:
                log(f"    0x{addr:04X}  0x{old:02X} → 0x{new:02X}")
        else:
            log("  差し替え無し（出荷時と同じ値）")

    write_lmk, lmk_fn = _writer(xrfclk, "LMK")
    if write_lmk is None:
        raise RuntimeError(
            "xrfclk にレジスタ列を直接書く関数が無い（_write_LMK_regs / write_LMK_regs）。"
            f"使える名前: {api_names(xrfclk)}")
    lmks = _devices(xrfclk, "lmk")
    for lmk in lmks:
        write_lmk(regs, lmk)
    if verbose:
        log(f"LMK04828 に {len(regs)} 語を書いた（xrfclk.{lmk_fn} × {len(lmks)} 個）")
        log(f"  PLL1 のロックを待つ: {settle} s")
    time.sleep(settle)

    # LMX2594 を書き直す。
    # **LMK を書き換えると出力が一度乱れ、下流の LMX はロックを失う。**
    # 基準周波数（245.76 MHz）は変わらないので自力で復帰しうるが、
    # 「たまに立ち上がらない」を避けるために明示的に書き直す。
    write_lmx, lmx_fn = _writer(xrfclk, "LMX")
    lmx_path = find_stock_lmx_file()
    if write_lmx is not None and lmx_path:
        lmx_regs = read_tics(lmx_path)
        lmxs = _devices(xrfclk, "lmx")
        for lmx in lmxs:
            write_lmx(lmx_regs, lmx)
        if verbose:
            log(f"LMX2594 に {len(lmx_regs)} 語を書き直した"
                f"（xrfclk.{lmx_fn} × {len(lmxs)} 個 / {os.path.basename(lmx_path)}）")
    elif verbose:
        log("WARNING: LMX を書き直す関数かレジスタファイルが見つからない。")
        log("  基準周波数は変わらないので自力で再ロックするはずだが、"
            "タイル PLL がロックしない場合はここを疑う")
    if verbose:
        log("")
        log("**ボードの PLL1 ロック LED を見ること。**")
        log("  消えていれば基準が来ていない（ケーブル・レベル・CLKin の取り違え）。")
        log("  点いていても外部基準が効いている証拠にはならない。判定は ppm で行う。")
    return regs


# --------------------------------------------------------------------- CLI
def show_api():
    """ボードの xrfclk が実際に持っているものを出す。

    **私有関数の名前は版で変わる。** 想定と違って落ちたら、まずここを見て
    このスクリプトの側を合わせる。推測で書き換えない。
    """
    xrfclk = _import_xrfclk()
    d = os.path.dirname(os.path.realpath(xrfclk.__file__))
    log(f"xrfclk    : {xrfclk.__file__}")
    log(f"version   : {getattr(xrfclk, '__version__', '(無し)')}")
    log("")
    log("--- 使える名前 ---")
    for n in api_names(xrfclk):
        v = getattr(xrfclk, n, None)
        kind = "関数" if callable(v) else type(v).__name__
        extra = ""
        if isinstance(v, (list, dict)):
            extra = f"  （要素 {len(v)} 個）"
        log(f"  {n:<24} {kind}{extra}")
    log("")
    log("--- パッケージ内のレジスタファイル ---")
    for f in sorted(glob.glob(os.path.join(d, "*.txt"))):
        log(f"  {os.path.basename(f)}")
    log("")
    log("proj004 が使うもの:")
    for want in ("set_ref_clks / set_ref_clk", "lmk_devices", "lmx_devices",
                 "_write_LMK_regs", "_write_LMX_regs"):
        names = [w.strip() for w in want.split("/")]
        ok = any(getattr(xrfclk, n, None) is not None for n in names)
        log(f"  {'OK  ' if ok else '無い'} {want}")


def show(path=None):
    """出荷時のファイルを読んで、関係するレジスタの意味を表示する。

    path を渡せば **ボードを触らずに**（xrfclk 無しでも）読める。
    手元で `clocks/LMK04828_245.76_stock.txt` を見るときに使う。
    """
    path = path or find_stock_lmk_file()
    regs = read_tics(path)
    log(f"ファイル : {path}")
    log(f"語数     : {len(regs)}")
    log("")
    sel = get_reg(regs, REG_CLKIN_SEL)
    mode = (sel >> 4) & 0x7
    log(f"0x0147 = 0x{sel:02X}")
    log(f"  CLKin_SEL_MODE = {mode}"
        + (f"  → {SOURCE_NAME.get(mode, '(manual 以外)')}" if mode in SOURCE_NAME
           else "  → manual 以外（4 = auto）"))
    log(f"  CLKin1_DEMUX   = {(sel >> 2) & 0x3}   (2 = PLL1 へ)")
    log(f"  CLKin0_DEMUX   = {sel & 0x3}   (2 = PLL1 へ)")
    log("")
    for i, (ma, la) in REG_R_DIV.items():
        r = ((get_reg(regs, ma) & 0x3F) << 8) | get_reg(regs, la)
        f_in = r * PLL1_PD_MHZ
        log(f"CLKin{i}_R = {r:>5}   → 想定入力 {f_in:g} MHz"
            f"{'   ← 出荷時の選択' if i == STOCK_CLKIN else ''}")
    n = ((get_reg(regs, REG_PLL1_N[0]) & 0x3F) << 8) | get_reg(regs, REG_PLL1_N[1])
    log("")
    log(f"PLL1_N   = {n}        → 位相比較 {PLL1_PD_MHZ * 1e3:.0f} kHz × {n} "
        f"= {n * PLL1_PD_MHZ:g} MHz（VCXO）")
    log(f"0x015F   = 0x{get_reg(regs, REG_PLL1_LD):02X}   PLL1_LD_MUX/TYPE"
        f"（ボードの PLL1 ロック LED に出ている）")
    log(f"0x014B   = 0x{get_reg(regs, REG_HOLDOVER):02X}   ホールドオーバ関係")
    log("")
    log("**ホールドオーバに注意。** 外部基準を抜いても LMK は直前の DAC 値を保持して")
    log("VCXO を走らせ続ける。抜いた瞬間に ppm が戻るとは限らない。")
    log("内部基準との比較は、**出荷時の設定を書き直して**取り直すこと。")


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--show", action="store_true",
                   help="出荷時のレジスタファイルを読んで意味を表示する（書き込まない）")
    g.add_argument("--set", dest="src", choices=("stock", "0", "1", "2"),
                   help="PLL1 の基準入力を選んで書き込む")
    g.add_argument("--api", action="store_true",
                   help="ボードの xrfclk が実際に持っている名前を出す（書き込まない）。"
                        "**版が違って落ちたときは、まずこれ**")
    p.add_argument("--ref", type=float, default=10.0,
                   help="外部基準の周波数 [MHz]（既定 10.0）")
    p.add_argument("--settle", type=float, default=2.0,
                   help="LMK を書いてから LMX を書くまでの待ち [s]")
    p.add_argument("--file", default=None,
                   help="--show で読むレジスタファイル。手元で中身を見るとき用"
                        "（例: ../clocks/LMK04828_245.76_stock.txt）")
    args = p.parse_args()

    if args.api:
        show_api()
        return

    if args.show:
        show(args.file)
        return

    clkin = None if args.src == "stock" else int(args.src)
    set_clocks(clkin, ref_mhz=args.ref, settle=args.settle)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        log(f"ERROR: {e}")
        sys.exit(1)

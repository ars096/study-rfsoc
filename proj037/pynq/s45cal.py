#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — TP の dBm 換算の較正ファイル（tp_cal.json）を読む・確かめる・換算する（numpy だけ。specd・受け側の両方が使う）

方針（README 2026-10-06）: 係数はボード（specd）に置き、START の EVENT・STATUS・GET CAL で配る。**データは生の Σx² のまま**流し、
dBm への換算は受け側で行う（係数を測り直しても、過去の記録を換算し直せる）。

  dBm（ADC の入口、SMA）= 10·log10(σ_x²) + K_adc、σ_x² = Σx² / (フレーム数 · 8192)（14 bit の LSB²、TP の 1 サンプルの平均の電力）

**ADR 0025（2026-10-29）: tp_cal.json はボードの個体の値。ボードの /etc/yatsugatake/tp_cal.json（環境変数 YATSUGATAKE_TP_CAL）にだけ置き、
リポジトリに戻さない。** 鍵はボードの印（timebase.board_id()）と ADC の道（timebase.ADC_PATH）。前の形（board の無い bits の形）は
このボードで測ったものなら `python3 s45cal.py adopt <前のファイル>` で今の形にして置く。

tp_cal.json の形:
  {"version": 1, "board": {"id": "mac:…", "src": …}（このボードの印。specd の ID の board と照らす）,
   "adc_path": 1（測った bit の ADC の道。載っている bit の道と照らす）,
   "measured_on": [...]（測った bit の記録。照合には使わない）, "unit": "dBm at ADC input (SMA)",
   "adc": {"A": {"k_db": -69.37, "valid_dbfs": [-47, -7], "provisional": true, "source": "...", "date": "2026-10-06"}, ...},
   "note": "..."}
  provisional: true = 見積もりを含む暫定（0 dBFS ≒ +5.9 dBm の正弦波の値を使ったなど）。PM を ADC の口で測って置き換えたら false
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np

DBFS0 = 10 * math.log10(8192 ** 2 / 2)          # 0 dBFS = 14 bit の満杯の正弦波の電力（LSB²）= 75.27 dB
ADCS = "ABCD"
TP_CAL_PATH = "/etc/yatsugatake/tp_cal.json"   # ADR 0025。環境変数 YATSUGATAKE_TP_CAL で替えられる


def tp_cal_path():
    return os.environ.get("YATSUGATAKE_TP_CAL") or TP_CAL_PATH


def bit_of_id(adc_id):
    """ID の adc_id（コア 0 の IF_ID、16 進 8 桁）→ (BIT_KIND, BIT_REV)"""
    v = int(str(adc_id), 16)
    return (v >> 16) & 0xFF, (v >> 8) & 0xFF


def load(path):
    with open(path) as f:
        cal = json.load(f)
    if cal.get("version") != 1 or "adc" not in cal:
        raise ValueError(f"{path}: 形が違う（version 1・adc が要る）")
    for a, c in cal["adc"].items():
        if a not in ADCS or not isinstance(c.get("k_db"), (int, float)):
            raise ValueError(f"{path}: ADC {a} の k_db が無い")
    cal["_file"] = path
    return cal


def check(cal, ids):
    """載っている bit とボードに、較正ファイルが当たるか。戻り値 (使えるか, 説明)

    ADR 0025: ファイルの board.id = 取得の ids["board"]（このボードの印）、かつファイルの adc_path = 載っている bit の ADC の道
    （timebase.adc_path_of、bit の (BIT_KIND, BIT_REV) はコア 0 の IF_ID = ids["adc"] から）。違えば使わない"""
    import timebase as TB
    if cal is None:
        return False, "較正ファイルが無い"
    got = str((ids or {}).get("adc", "")).lower()
    if got == "fake" or str((ids or {}).get("win", "")).lower() == "fake":
        return True, "偽物（ID を照らさない）"
    want_b = (cal.get("board") or {}).get("id")
    if not want_b:
        return False, "較正ファイルにボードの印が無い（ADR 0025 より前の形。このボードで測ったものなら s45cal.py adopt で今の形に）"
    have_b = (ids or {}).get("board")
    if not have_b or have_b == "-":
        return False, "このボードの印が読めない（較正ファイルを照らせない）"
    if want_b != have_b:
        return False, f"較正ファイルは別のボード（{want_b}）のもの。このボードは {have_b}"
    try:
        have = bit_of_id(got)
    except ValueError:
        return False, f"載っている bit の IF_ID が読めない（{got!r}）"
    if cal.get("adc_path") != TB.adc_path_of(have):
        return False, f"較正ファイルは ADC の道 {cal.get('adc_path')} で測った。載っている bit {have} は道 {TB.adc_path_of(have)}"
    return True, "ok"


def adopt(src, dst, board):
    """前の形（bits の一覧）のファイルに、このボードの印と ADC の道を付けて dst に置く。**このボードで測ったファイルにだけ使う**"""
    import timebase as TB
    cal = load(src)
    cal.pop("_file", None)
    paths = {TB.adc_path_of(tuple(int(x) for x in b)) for b in cal.get("bits", [])}
    if "adc_path" in cal:
        paths.add(int(cal["adc_path"]))
    if len(paths) != 1:
        raise ValueError(f"{src}: ADC の道が 1 つに決まらない（{sorted(paths) or 'bits も adc_path も無い'}）")
    cal["adc_path"] = paths.pop()
    if cal.get("bits"):
        cal["measured_on_bits"] = cal.pop("bits")
    cal["board"] = board
    cal["adopted"] = dict(src=os.path.basename(src), date=time.strftime("%Y-%m-%d"))
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    if os.path.exists(dst):
        bak = f"{dst}.{time.strftime('%Y%m%d-%H%M%S')}"
        os.rename(dst, bak)
        print(f"前の較正ファイルを {bak} に残した")
    with open(dst + ".tmp", "w") as f:
        json.dump(cal, f, ensure_ascii=False, indent=1)
    os.replace(dst + ".tmp", dst)
    load(dst)
    print(f"{dst} を書いた（ボード {board['id']}・ADC の道 {cal['adc_path']}）。specd を起動し直すと効く")
    return cal


def sigma2(e):
    """TP の区切り（s45proto.TP_E の配列）→ σ_x²（LSB²）"""
    return e["sum"].astype(np.float64) / (e["nfr"].astype(np.float64) * 8192.0)


def dbm(s2, cal, adc):
    """σ_x² → dBm（ADC の入口）。cal が無い・その ADC が無ければ NaN"""
    c = (cal or {}).get("adc", {}).get(adc)
    if c is None:
        return np.full(np.shape(s2), np.nan)
    return 10 * np.log10(np.maximum(np.asarray(s2, np.float64), 1e-30)) + float(c["k_db"])


def dbfs(s2):
    return 10 * np.log10(np.maximum(np.asarray(s2, np.float64), 1e-30)) - DBFS0


def main(argv=None):
    import timebase as TB
    p = argparse.ArgumentParser(description="TP の dBm の較正ファイル（ADR 0025）: show = このボードの印と照らす・adopt = 前の形を今の形にして置く")
    p.add_argument("cmd", choices=("show", "adopt"))
    p.add_argument("src", nargs="?", help="adopt: 前の形のファイル（このボードで測ったもの）")
    p.add_argument("--write", default=tp_cal_path(), help="置き場所")
    a = p.parse_args(argv)
    b = TB.board_id()
    if a.cmd == "show":
        print(f"このボードの印: {b['id'] if b else '読めない'}")
        if not os.path.exists(a.write):
            print(f"較正ファイル {a.write} が無い（TP の dBm は出ない。dBFS は出る）")
            return 1
        cal = load(a.write)
        same = b is not None and (cal.get("board") or {}).get("id") == b["id"]
        print(f"較正ファイル {a.write}: ボード {(cal.get('board') or {}).get('id', '無い')}（{'このボード' if same else '別のボードか前の形'}）・"
              f"ADC の道 {cal.get('adc_path', '-')}・K " + "・".join(f"{x} {c['k_db']:+.3f}{'（暫定）' if c.get('provisional') else ''}"
                                                                for x, c in sorted(cal["adc"].items())))
        return 0 if same else 1
    if not a.src:
        p.error("adopt には前の形のファイルが要る")
    if b is None:
        print("ERROR: このボードの印が読めない"); return 1
    adopt(a.src, a.write, b)
    return 0


if __name__ == "__main__":
    sys.exit(main())

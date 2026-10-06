#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — TP の dBm 換算の較正ファイル（tp_cal.json）を読む・確かめる・換算する（numpy だけ。specd・受け側の両方が使う）

方針（README 2026-10-06）: 係数はボード（specd）に置き、START の EVENT・STATUS・GET CAL で配る。**データは生の Σx² のまま**流し、
dBm への換算は受け側で行う（係数を測り直しても、過去の記録を換算し直せる）。

  dBm（ADC の入口、SMA）= 10·log10(σ_x²) + K_adc、σ_x² = Σx² / (フレーム数 · 8192)（14 bit の LSB²、TP の 1 サンプルの平均の電力）

tp_cal.json の形:
  {"version": 1, "bit_id_win": "00170100", "unit": "dBm at ADC input (SMA)",
   "adc": {"A": {"k_db": -69.37, "valid_dbfs": [-47, -7], "provisional": true, "source": "...", "date": "2026-10-06"}, ...},
   "note": "..."}
  provisional: true = 見積もりを含む暫定（0 dBFS ≒ +5.9 dBm の正弦波の値を使ったなど）。PM を ADC の口で測って置き換えたら false
"""
import json
import math

import numpy as np

DBFS0 = 10 * math.log10(8192 ** 2 / 2)          # 0 dBFS = 14 bit の満杯の正弦波の電力（LSB²）= 75.27 dB
ADCS = "ABCD"


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
    """載っている bit の ID と較正ファイルの bit_id_win を照らす（timebase の CAL と同じく、違えば使わない）。戻り値 (使えるか, 説明)"""
    if cal is None:
        return False, "較正ファイルが無い"
    want = str(cal.get("bit_id_win", "")).lower()
    got = str((ids or {}).get("win", "")).lower()
    if got == "fake":
        return True, "偽物（ID を照らさない）"
    if want and want != got:
        return False, f"bit の ID が違う（較正 {want}・載っている {got}）"
    return True, "ok"


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

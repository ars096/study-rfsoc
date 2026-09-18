#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj008 — timebase.py の時刻計算を実機なしで検証する。

**本題は符号である。** proj007 は `delay` の符号を逆に立てて、
**当たった 10 回の測定では出ず、予言を外した対照実験で初めて**露見させた。
2026-09-18、proj008 の README でも同じ場所を `+` で書いていた。
**この向きは式を読んでも間違いに気づけない**ので、機械に見張らせる。

決め手になる試験は 1 つ:
**「PPS のエッジが乗っているサンプル」を時刻に直すと、その PPS 自身の UTC に戻る。**
符号が逆なら 2 倍ずれるので必ず落ちる。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pynq"))

import timebase as tb                 # noqa: E402

FAILED = []


def check(cond, name, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}   {detail}")
        FAILED.append(name)


print("定数")
check(tb.BEATS_PER_SEC == 153_600_000, "1 秒 = 153,600,000 ビートちょうど",
      str(tb.BEATS_PER_SEC))
check(tb.FS_HZ % tb.SPW == 0, "fs はビートで割り切れる")

print("samples_to_ns")
check(tb.samples_to_ns(tb.FS_HZ) == 10**9,
      "**1 秒ぶんのサンプルは厳密に 10^9 ns**", str(tb.samples_to_ns(tb.FS_HZ)))
check(tb.samples_to_ns(0) == 0, "0 サンプルは 0 ns")
check(tb.samples_to_ns(768) == 625, "768 サンプルは厳密に 625 ns")
check(tb.samples_to_ns(8) == 7, "1 ビート 6.5104 ns は最近接の 7 ns へ",
      str(tb.samples_to_ns(8)))
# 1 秒を積み上げても誤差が溜まらないこと（丸めが各回独立でないこと）
check(tb.samples_to_ns(tb.FS_HZ * 3600) == 3600 * 10**9,
      "**1 時間ぶんでも厳密**（丸め誤差が溜まらない）")

print("utc_second_of_last_pps")
check(tb.utc_second_of_last_pps(1000.5) == 1000, "x.5 で読めば x")
check(tb.utc_second_of_last_pps(1000.01) == 1000, "x.0 側に 0.49 ずれても x")
check(tb.utc_second_of_last_pps(1000.99) == 1000, "x+1 側に 0.49 ずれても x")

print("sample_time_ns — **符号**")
# 錨: UTC 1000 秒ちょうどに来た PPS が、ビート 500 でスタンプされた。
# proj008 の実測では、その PPS のエッジは ADC のバッファ上で
# **PL のスタンプより 213 ns 後ろ**（= +262 サンプル）に現れる。
# したがって「添字 262 のサンプル」を時刻に直すと、**PPS 自身の UTC 1000 秒**に戻るはず。
CAL = 213.16
t = tb.sample_time_ns(1000, 500, beat=500, i=262, cal_ns=CAL)
check(t == 1000 * 10**9,
      "**PPS のエッジが乗るサンプルは、その PPS の UTC に戻る**（符号が正しい）",
      f"{t}（期待 {1000 * 10**9}、差 {t - 1000 * 10**9} ns）")
# 符号を逆に立てたらどうなるかを明示的に見せる（落ちることの確認）
t_wrong = tb.sample_time_ns(1000, 500, beat=500, i=262, cal_ns=-CAL)
check(abs(t_wrong - 1000 * 10**9) > 400,
      "符号を逆にすると 2 倍（約 426 ns）ずれる —— **この試験は符号に敏感**",
      f"{t_wrong - 1000 * 10**9} ns")

print("sample_time_ns — 積み上げ")
t0 = tb.sample_time_ns(1000, 500, beat=500, i=0, cal_ns=0.0)
t1 = tb.sample_time_ns(1000, 500, beat=500 + tb.BEATS_PER_SEC, i=0, cal_ns=0.0)
check(t1 - t0 == 10**9, "1 秒先のビートは厳密に 10^9 ns 先", str(t1 - t0))
t2 = tb.sample_time_ns(1000, 500, beat=500, i=tb.SPW, cal_ns=0.0)
t3 = tb.sample_time_ns(1000, 500, beat=501, i=0, cal_ns=0.0)
check(t2 == t3, "**1 ビート進む = 8 サンプル進む**（どちらの数え方でも同じ）")
tneg = tb.sample_time_ns(1000, 500, beat=499, i=0, cal_ns=0.0)
check(tneg < t0, "錨より前のビートは錨より前の時刻になる（負の差でも壊れない）")

print("pps_is_consistent")
check(tb.pps_is_consistent(5, 5 * tb.BEATS_PER_SEC) is True, "ちょうど合えば True")
check(tb.pps_is_consistent(5, 5 * tb.BEATS_PER_SEC + 1) is False,
      "**1 ビートでもずれれば False**（『だいたい合っている』を許さない）")
check(tb.pps_is_consistent(5, 4 * tb.BEATS_PER_SEC) is False,
      "PPS を 1 発取りこぼせば False")

print("CAL の表")
check(0x00080001 in tb.CAL, "proj008 の MAGIC の定数を持っている")
for magic, c in tb.CAL.items():
    for k in ("l_adc_minus_d_pps_ns", "unc_ns", "epoch_residual_ns",
              "tile_residual_ns", "source"):
        check(k in c, f"0x{magic:08x} に {k} がある")
    check(c["source"].strip() != "", f"0x{magic:08x} の出どころが書いてある")

# ---------------------------------------------------------------- 拒否の経路
# **「答えを返さない」は、一度も走らなければ働かない。**
# 偽の PPS で全分岐を通す。実機では起こしにくい状態（locked が落ちる等）ほど、
# ここで通しておく価値が高い。
FLAGS_OK = 0x01 | 0x20 | 0x40          # alive | adc_rstn | locked


class FakePPS:
    def __init__(self, magic=0x00080001, **over):
        self._magic = magic
        self.d = dict(epoch=1, count=100, stamp=1000,
                      flags=FLAGS_OK, beat=1000, interval=tb.BEATS_PER_SEC,
                      t_start=1000, cstamp=0, glitch_trig=0, glitch_comp=0)
        self.d.update(over)

    def check_magic(self):
        return self._magic

    def snapshot(self):
        return dict(self.d)


def expect_refusal(fn, name, detail=""):
    try:
        fn()
    except tb.TimebaseError:
        check(True, name)
    except Exception as e:                       # noqa: BLE001
        check(False, name, f"TimebaseError 以外が出た: {type(e).__name__} {e}")
    else:
        check(False, name, f"**拒否しなかった** {detail}")


print("require_mid_second")
check(abs(tb.require_mid_second(1000.5) - 0.5) < 1e-9, "x.5 は通る")
expect_refusal(lambda: tb.require_mid_second(1000.02), "x.0 の近くは拒否する")
expect_refusal(lambda: tb.require_mid_second(1000.98), "x+1 の近くは拒否する")

print("Timebase — 拒否の経路")
expect_refusal(lambda: tb.Timebase(FakePPS(magic=0x00070002)),
               "**知らない MAGIC のビットストリームには時刻を貼らない**")

tbi = tb.Timebase(FakePPS())
expect_refusal(lambda: tbi.time_of_ns(1000, 0),
               "錨が無ければ答えない")

def _mk(**over):
    o = tb.Timebase(FakePPS(**over))
    o._anchor = dict(epoch=1, count=100, stamp=1000, utc_sec=1000)
    return o

ok = _mk()
check(ok.time_of_ns(1000, 0) == 1000 * 10**9 - 213,
      "健全なら答える（較正 213 ns を引いた値）", str(ok.time_of_ns(1000, 0)))

expect_refusal(lambda: _mk(epoch=2).time_of_ns(1000, 0),
               "**原点が変わったら答えない**（錨より前のビートは別の原点）")
expect_refusal(lambda: _mk(flags=FLAGS_OK & ~0x40).time_of_ns(1000, 0),
               "**MMCM がロックしていなければ答えない**")
expect_refusal(lambda: _mk(flags=FLAGS_OK & ~0x01).time_of_ns(1000, 0),
               "**PPS が来ていなければ答えない**（黙って外挿しない）")
expect_refusal(lambda: _mk(flags=FLAGS_OK & ~0x20).time_of_ns(1000, 0),
               "ADC ドメインのリセットが解除されていなければ答えない")

# PPS 数とビート差の不整合。count は 5 増えたのに stamp は 4 秒ぶんしか進んでいない
expect_refusal(
    lambda: _mk(count=105, stamp=1000 + 4 * tb.BEATS_PER_SEC).time_of_ns(1000, 0),
    "**PPS を取りこぼしたら答えない**（1 ビートでも合わなければ拒否）")
# 1 ビートだけずれている場合も拒否すること
expect_refusal(
    lambda: _mk(count=105, stamp=1000 + 5 * tb.BEATS_PER_SEC + 1).time_of_ns(1000, 0),
    "**1 ビートのずれでも拒否する**（『だいたい合っている』を許さない）")
# 整合していれば答える
okc = _mk(count=105, stamp=1000 + 5 * tb.BEATS_PER_SEC)
check(okc.time_of_ns(1000, 0) == 1000 * 10**9 - 213,
      "整合していれば答える（PPS が 5 発進んでも錨は同じ）")

class BoomPPS(FakePPS):
    """snapshot が **このモジュールの知らない例外**を投げる（pps.EpochChanged 相当）。"""
    def snapshot(self):
        raise RuntimeError("読んでいる最中に時刻の原点が変わった")


boom = tb.Timebase(BoomPPS())
boom._anchor = dict(epoch=1, count=100, stamp=1000, utc_sec=1000)
expect_refusal(lambda: boom.time_of_ns(1000, 0),
               "**知らない型の例外も TimebaseError に変えて拒否する**"
               "（呼ぶ側の except をすり抜けさせない）")

print("accuracy_ns")
a = tb.Timebase(FakePPS()).accuracy_ns()
check(a["applied_ns"] == 213.16, "適用した値を返す")
check(a["total_ns"] > a["applied_unc_ns"], "補正し残した量の合計を返す")
check("proj007" in a["source"] and "proj008" in a["source"], "出どころを返す")

print("")
if FAILED:
    print(f"**{len(FAILED)} 件 FAIL**: {', '.join(FAILED)}")
    sys.exit(1)
print("ALL PASS（時刻層）")

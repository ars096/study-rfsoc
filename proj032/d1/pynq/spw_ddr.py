#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj032 D-1 — SpW の窓の PFB の履歴を PL DDR4 に置く形の読み書きが入るかを測る（ボードの上で。proj032d1.bit・.hwh と同じ場所に置く）。

  sudo python3 spw_ddr.py [--bit proj032d1.bit] [--out spw_ddr.json] [--sec 10]

形（README の案 D・構成 H 14・E 3・S 6）:
  DDR の道に載る窓の帯域の和は ADC ごとに 256 MHz、4 ADC で 1024 MS/s。履歴は I/Q 8 bit（2 B / 標本）で、標本 1 個につき書き 1 回 ＋ 読み 4 フレーム
  → 書き 2.048 GB/s ＋ 読み 8.192 GB/s = 10.24 GB/s
  窓は 4 ADC × 14 = 56 本。窓ごとの区画（5 フレーム × 8 KiB = 40 KiB を 64 KiB に切り上げ）を順に書き、読みは 1 フレーム 8 KiB ずつ
  書き手: 流れ 56 本・BL 16 拍（1 KiB = 窓ごとのチップ内の溜め）、読み手: 流れ 56 本・BL_R 128 拍（8 KiB）
  （実際は 1 窓の 4 フレームを続けて読むので、毎回 8 KiB で跳ぶこの形は実際より厳しい側）

試験（各 --sec 秒、UI クロックの拍で数える）:
  P0 下ごしらえ: 区画の全体を ONE_PASS で書く（読みの照合の相手）
  P1 本番の形: 目標の速さで同時に → 達した速さ ≧ 目標の 99.9 %・不一致 0・FLAGS 0（合否）
  P2 余裕: 目標 × 1.25・× 1.5・× 1.75 で同じ（どこまで追いつくか。情報）
  P3 上限: 速さの上限なしで同時（この形での天井。情報）
  P4 形の振り: 書きの BL 8・32 拍、読みの BL_R 64・256 拍、流れ 16・112 本で、本番の速さ（情報）
  P5 片方を目標に固定し、もう片方を上限なしに（ddr_tg の許可は BL ＋ 2 拍で頭打ちなので、DDR が一時待たせると許可が捨てられ、
     P1 の達した速さは溜めの深さ BL ＋ 2 拍の設計の値になる。P5 は溜めが十分深いときの上限: 読み 8.192 固定で書ける量、書き 2.048 固定で読める量）
予言（README）: P1 は通過（proj028 の順の読み書きで同時 17.66 GB/s、本番の形の 4.68 ＋ 4.77 は誤り 0）。
  ただし 1 KiB の書きのバーストで跳ぶと行の開け閉めが増え、天井は順の運転より下がる見込み（P3 は 12〜16 GB/s と置く）
"""
import argparse
import json
import sys

from ddr_bw import BEAT, F_UI, bring_up

KIB = 1024


def rate(gbs):
    """GB/s → WR_RATE・RD_RATE（65536 = 毎拍）"""
    return min(65536, round(gbs * 1e9 / (BEAT * F_UI) * 65536))


def p5(tg, res, go, TW, TR, a):
    # P5: 片方を目標に、もう片方は上限なし（WR_RATE・RD_RATE = 65536 は rate(None) の扱いで）
    for bl, blr in ((16, 128), (32, 128), (64, 128), (16, 64)):
        go("P5 読み固定・BL %d・BL_R %d" % (bl, blr), 100.0, TR, bl=bl, blr=blr, seconds=min(a.sec, 3.0))
        go("P5 書き固定・BL %d・BL_R %d" % (bl, blr), TW, 100.0, bl=bl, blr=blr, seconds=min(a.sec, 3.0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bit", default="proj032d1.bit")
    ap.add_argument("--out", default="spw_ddr.json")
    ap.add_argument("--sec", type=float, default=10.0)
    ap.add_argument("--only-p5", action="store_true", help="P0 と P5 だけ")
    ap.add_argument("--only-p12", action="store_true", help="P0・P1・P2 だけ（--bl で書きのバースト長を振る）")
    ap.add_argument("--bl", type=int, default=16, help="P1・P2 の書きのバースト長（拍。16 = 1 KiB）")
    a = ap.parse_args()
    tg, res = bring_up(a.bit)
    dur = int(a.sec * F_UI)
    NS, REG = 56, 64 * KIB
    TW, TR = 2.048, 8.192                  # GB/s
    span = NS * REG
    seed = 0x5B320001

    def go(name, tw, tr, bl=16, blr=128, ns=NS, reg=REG, seconds=None):
        d = dur if seconds is None else int(seconds * F_UI)
        r = tg.run(tw is not None, tr is not None, 0, max(span, ns * reg), seed, bl=bl, blr=blr,
                   wrate=rate(tw) if tw else 65536, rrate=rate(tr) if tr else 65536, dur=d,
                   nsw=ns, regw=reg, nsr=ns, regr=reg)
        okw = tw is None or r["wr_gbs"] >= 0.999 * tw
        okr = tr is None or r["rd_gbs"] >= 0.999 * tr
        ok = okw and okr and r["rd_err"] == 0 and r["flags"] == 0
        print("%-26s 書き %6.3f（目標 %s）・読み %6.3f（目標 %s）・合計 %6.3f GB/s・WR_WAIT/拍 %.3f・不一致 %d・FLAGS %d → %s"
              % (name, r["wr_gbs"], "%.3f" % tw if tw else "なし", r["rd_gbs"], "%.3f" % tr if tr else "なし",
                 r["wr_gbs"] + r["rd_gbs"], r["wr_wait"] / max(r["cyc"], 1), r["rd_err"], r["flags"], "○" if ok else "×"))
        res.setdefault("runs", []).append(dict(r, name=name, tw=tw, tr=tr, bl=bl, blr=blr, ns=ns, reg=reg, ok=bool(ok)))
        return ok

    # P0 下ごしらえ（順に 1 周。区画の全部を同じ SEED で）
    w = tg.run(True, False, 0, span * 2, seed, bl=256, one=True)
    print("P0 下ごしらえ: %d MiB を書いた（%.2f GB/s）" % (span * 2 // (1 << 20), w["wr_gbs"]))
    if a.only_p5:
        p5(tg, res, go, TW, TR, a)
        with open(a.out, "w") as f:
            json.dump(res, f, indent=1)
        print("書いた: %s" % a.out)
        return
    # P1 本番の形
    p1 = go("P1 本番の形（BL %d）" % a.bl, TW, TR, bl=a.bl)
    # P2 余裕
    for m in (1.25, 1.5, 1.75):
        go("P2 × %.2f（BL %d）" % (m, a.bl), TW * m, TR * m, bl=a.bl)
    if a.only_p12:
        res["p1_ok"] = bool(p1)
        with open(a.out, "w") as f:
            json.dump(res, f, indent=1)
        print("P1（合否）: %s" % ("通過" if p1 else "不合格"))
        return
    # P3 上限
    r = tg.run(True, True, 0, span, seed, bl=16, blr=128, dur=int(min(a.sec, 3.0) * F_UI), nsw=NS, regw=REG, nsr=NS, regr=REG)
    print("%-26s 書き %6.3f・読み %6.3f・合計 %6.3f GB/s・不一致 %d" % ("P3 上限なし（同時）", r["wr_gbs"], r["rd_gbs"],
                                                         r["wr_gbs"] + r["rd_gbs"], r["rd_err"]))
    res.setdefault("runs", []).append(dict(r, name="P3 上限なし"))
    # P4 形の振り
    for bl, blr, ns in ((8, 128, NS), (32, 128, NS), (16, 64, NS), (16, 256, NS), (16, 128, 16), (16, 128, 112)):
        go("P4 BL %d・BL_R %d・流れ %d" % (bl, blr, ns), TW, TR, bl=bl, blr=blr, ns=ns, seconds=min(a.sec, 3.0))
    p5(tg, res, go, TW, TR, a)
    res["p1_ok"] = bool(p1)
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
    print("P1（合否）: %s" % ("通過" if p1 else "不合格"))
    print("書いた: %s" % a.out)
    sys.exit(0 if p1 else 1)


if __name__ == "__main__":
    main()

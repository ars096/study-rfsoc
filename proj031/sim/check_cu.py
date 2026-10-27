#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj031 P-1 — tb_g24_cu の判定と入力の生成。

  python3 sim/check_cu.py gen <出力の hex>      4096 行 × 576 bit（pynq/g24cu.py の words を行ごとに 144 桁で）
  python3 sim/check_cu.py check <tb.log>        通るべき条件を全部見る（陽性対照はどこかで落ちる）。最後に「結果:」の行
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "pynq"))
import g24cu  # noqa: E402

LO = os.path.join(ROOT, "src", "g24", "g24_coef_lo.hex")
HI = os.path.join(ROOT, "src", "g24", "g24_coef_hi.hex")


def gen(out):
    r = g24cu.rows(LO, HI)
    w = g24cu.words(r)
    with open(out, "w") as f:
        for row in w:
            f.write("".join(f"{int(x):08x}" for x in row[::-1]) + "\n")
    print(f"書いた: {out}（CRC 0x{g24cu.crc(r):08X}）")


def check(log):
    kv = {}
    for ln in open(log):
        s = ln.split()
        if len(s) >= 2:
            kv[s[0]] = s[1:]
    crc = g24cu.crc(g24cu.rows(LO, HI))
    items = []

    def chk(name, cond, got):
        items.append((name, bool(cond), got))

    if "DONE" not in open(log).read():
        print("tb が最後まで走っていない"); print("結果: 不合格"); return 1
    chk("リセット中に ready を出さない", kv["RST_READY"][0] == "0", kv["RST_READY"][0])
    chk("ID 0x63750001", kv["ID"][0] == "63750001", kv["ID"][0])
    chk("COEF_CRC が模型の値", int(kv["COEF_CRC"][0], 16) == crc, kv["COEF_CRC"][0])
    chk("DATA の読み返し", kv["DATA17"][0] == kv["DATA17_WANT"][0], kv["DATA17"][0])
    st = int(kv["STAT"][0], 16)
    chk("VERIFY の後 OK 1・VERIFY 中 0・終えた 1・不一致 0", (st & 0xF) == 0b0101, f"0x{st:02X}")
    chk("取れた CRC が COEF_CRC", int(kv["CRC"][0], 16) == crc, kv["CRC"][0])
    chk("NROW 4096", kv["NROW"][0] == "4096", kv["NROW"][0])
    chk("出口の数（2・3 フレーム目）", kv["N_OUT"] == ["8192", "8192"], " ".join(kv["N_OUT"]))
    # tb の数え方は LAT − 1（LAT 5 の g24_coef が 4 と出る）。LAT 3 = g24_coef より 2 拍短く、一定
    lat, lbad, lref = int(kv["LAT"][0]), int(kv["LAT"][1]), int(kv["LAT_REF"][0])
    chk("遅れが g24_coef（LAT 5）より 2 短い（LAT 3）・一定", lref - lat == 2 and lbad == 0, f"cu {lat}・ref {lref}・揺れ {lbad}")
    chk("走りの間 ok_out 1", kv["NOK"][0] == "0", kv["NOK"][0])
    chk("g24_coef と違う m 0 / 4096", kv["MISMATCH"][0] == "0", kv["MISMATCH"][0])
    se = int(kv["STAT_END"][0], 16)
    chk("最後の STAT も OK 1", se & 1 == 1, f"0x{se:02X}")
    for name, ok, got in items:
        print(f"  {'OK' if ok else 'NG'}  {name}: {got}")
    if "FIRST_MIS" in kv:
        print("  最初の違い: " + " ".join(kv["FIRST_MIS"]))
    print(f"  VERIFY の拍 {kv['VERIFY_CYC'][0]}・STAT_PRE {kv['STAT_PRE'][0]}")
    allok = all(ok for _, ok, _ in items)
    print("結果: 全部通過" if allok else "結果: 不合格")
    return 0 if allok else 1


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        gen(sys.argv[2])
    else:
        sys.exit(check(sys.argv[2]))

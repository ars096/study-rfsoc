#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""tp_core の単体試験の入力を作り、結果を判定する（proj013 rev1）。

    python3 sim/check_tp.py gen   OUT     # OUT/tp_valid.hex・tp_beat.hex・tp_cmd.hex と OUT/tp_defs（iverilog の -P）
    python3 sim/check_tp.py check OUT

**模型は RTL の写しではなく、仕様（src/common/tp_core.v の冒頭）から書く**:
  区切りはフレームの頭にだけ置き、(a) 起動の後の最初のビート (b) RUN の F0 = RUN の時点の fin + 2 (c) 区切りが今の TP_N に達した
  のどれかで新しい区切りを始める（(c) は「今の TP_N 以上」）。和は x = (16 bit) >>> 2 の二乗の和。FLAGS は冒頭の表
判定:
  A. 閉じた区切りの数（TP_WP）が模型と一致
  B. リングバッファに残る最後の min(WP, 512) 個が、和・最初のフレーム・フレーム数・FLAGS まで 1 bit も違わない
  C. TP_F0 が最後の RUN の fin + 2（試験台が実際に見た値）と一致。TP_N / TP_NEFF / TP_PARAM / TP_STAT / 番地の外（DEAD_BEEF）
  D. 試験が意図した場面を本当に通ったか（在るべきものの確認）: F0 の直前に隙間があった区切り・短い区切り・
     リングバッファの一巡・隙間の FLAG・最大振幅（x = −8192）のビート
"""
import os
import sys
import numpy as np

M = 512            # 1 フレームのビート
L = 16             # 1 ビートのサンプル
TPN0 = 512         # TPN_DEFAULT（試験台の -P で与える）。proj017: 本番の既定 512 フレーム = 1.024 ms（proj013〜016 の sim は 3）
DEPTH = 512
OVR_TH = 32764     # proj017: FLAGS[4] の振り切れのしきい値（tp_core の OVR_TH）


def gen(out):
    rng = np.random.default_rng(13)
    valid = []                  # クロックごと
    beats = []                  # ビート（16 サンプルの int16）
    cmds = []                   # (クロック, 種類, 値)
    st = {"m": 0, "fin": 0}

    def head_next():
        return st["m"] == 0

    def beat():
        r = rng.random()
        if r < 0.0005:
            b = np.full(L, -32768, dtype=np.int64)           # 最大の二乗（x = −8192）
        else:
            b = (rng.integers(-8190, 8191, L) * 4)           # proj017: |x16| ≦ 32760（振り切れのしきい値 32764 の手前）
            if r < 0.0010:
                b[int(rng.integers(0, L))] = 32764           # proj017: しきい値ちょうど（FLAGS[4] が立つ。陽性対照の > では立たない）
            elif r < 0.0015:
                b[int(rng.integers(0, L))] = -32764          # 負の側のしきい値ちょうど（立つ。陽性対照の < では立たない）
            elif r < 0.0020:
                b[int(rng.integers(0, L))] = 32760 * (1 if r < 0.00175 else -1)   # しきい値の 1 つ手前（立たない）
        beats.append(b)
        valid.append(1)
        st["m"] += 1
        if st["m"] == M:
            st["m"] = 0
            st["fin"] += 1

    def gap(n):
        valid.extend([0] * n)

    def frames(nf, pgap=0.001, f0=None):
        """nf フレーム流す。f0 のフレームの頭の直前には必ず 3 クロックの隙間を入れる（F0 の判定の急所）。"""
        end = st["fin"] + nf
        while st["fin"] < end:
            if head_next() and f0 is not None and st["fin"] == f0:
                gap(3)
            elif rng.random() < pgap:
                gap(int(rng.integers(1, 4)))
            beat()

    def cmd(kind, val):
        # **フレームの頭の直前 8 クロックには命令を置かない**（RUN の直後 2 クロックの頭は旧い TP_N で判定されうる。
        # tp_core の冒頭の注意。仕様として決めていない場面を試験にしない）
        while M - st["m"] <= 8 or st["m"] == 0:
            beat()
        cmds.append((len(valid), kind, val))
        beat()

    gap(20)                                     # 起動の後、最初のビートまでの待ち（隙間の FLAG に数えない）
    # **RUN で始まる区切りと短い区切りは、リングバッファに残る最後の 512 個の中に置く**（初版は TP_N = 1 の 530 個を最後に置き、
    # 陽性対照の食い違いが窓の外に出て見えなかった）
    frames(1030)                                # 自走（TP_N = 512 の既定で 2 区切り ＋ 端。proj017。A の個数がこの既定に依る）
    cmd(1, 1)                                   # TP_N = 1 を書く（RUN までは効かない）
    frames(1)
    cmd(2, 0); f0a = st["fin"] + 2              # RUN。**cmd() の後の fin は RUN の時点と同じ**（フレームの途中で打つので）
    frames(530, f0=f0a)                         # TP_N = 1 で 530 個（リングバッファが一巡する）
    cmd(1, 4)
    frames(1)
    cmd(2, 0); f0b = st["fin"] + 2
    frames(14, f0=f0b)                          # TP_N = 4。F0 の直前の短い区切り（2 フレーム・TP_N 1）と F0 の区切りが窓に入る
    gap(5)
    frames(1)                                   # 最後の区切りを閉じる

    with open(os.path.join(out, "tp_valid.hex"), "w") as f:
        f.write("\n".join(str(v) for v in valid) + "\n")
    with open(os.path.join(out, "tp_beat.hex"), "w") as f:
        for b in beats:
            u = [(int(s) & 0xFFFF) for s in b]
            f.write("".join("%04x" % u[i] for i in range(L - 1, -1, -1)) + "\n")
    with open(os.path.join(out, "tp_cmd.hex"), "w") as f:
        for c, kd, v in cmds:
            f.write("%08x%02x%08x\n" % (c, kd, v))
        for _ in range(64 - len(cmds)):                  # 試験台の cmem[0:63] を埋める（readmemh の警告を出さない）
            f.write("%018x\n" % 0)
    with open(os.path.join(out, "tp_defs"), "w") as f:
        f.write("-Ptb_tp_core.NCYC=%d -Ptb_tp_core.NBEAT=%d -Ptb_tp_core.TPN=%d\n" % (len(valid), len(beats), TPN0))
    np.save(os.path.join(out, "tp_meta.npy"), np.array([len(valid), len(beats), f0a, f0b], dtype=np.int64))
    print("gen: クロック %d / ビート %d（%d フレーム）/ F0 %d, %d" % (len(valid), len(beats), len(beats) // M, f0a, f0b))


def load(out):
    valid = [int(l) for l in open(os.path.join(out, "tp_valid.hex"))]
    beats = []
    for l in open(os.path.join(out, "tp_beat.hex")):
        l = l.strip()
        u = [int(l[4 * (L - 1 - i):4 * (L - i)], 16) for i in range(L)]
        beats.append([v - 65536 if v >= 32768 else v for v in u])
    cmds = []
    for l in open(os.path.join(out, "tp_cmd.hex")):
        l = l.strip()
        c, kd, v = int(l[0:8], 16), int(l[8:10], 16), int(l[10:18], 16)
        if kd == 0:
            break
        cmds.append((c, kd, v))
    return valid, beats, cmds


def model(valid, beats, cmds):
    """仕様どおりの区切り。戻り値: 閉じた区切りのリスト・最後の F0・r_tpn・tp_n・見た場面"""
    bins = []
    cur = None                  # 今の区切り: dict
    started = False
    boot = True
    pend = None
    r_tpn, tp_n = TPN0, TPN0
    m, fin, bi = 0, 0, 0
    last_f0 = (1 << 48) - 1
    ci = 0
    seen = {"gap_before_f0": 0, "short": 0, "maxbeat": 0, "gapflag": 0, "ovr_edge": 0}
    gap_since_tlast = False
    for c, v in enumerate(valid):
        fin_c = fin                 # そのクロックの立ち上がりで RTL が見る fin（このクロックのビートで進む前）
        # 命令はそのクロックの入力と同じ立ち上がりで効く。RUN は「そのクロックの fin」から F0 を決める
        run_now = False
        while ci < len(cmds) and cmds[ci][0] == c:
            _, kd, val = cmds[ci]
            if kd == 1:
                r_tpn = val
            elif kd == 2:
                run_now = True
            ci += 1
        if v:
            b = beats[bi]; bi += 1
            if m == 0:
                neff = tp_n if tp_n else 1
                new = (not started) or (pend is not None and fin == pend) or (cur is not None and cur["nf"] >= neff)
                if new:
                    if cur is not None:
                        bins.append(cur)
                    runflag = pend is not None and fin == pend
                    if runflag:
                        pend = None
                        if gap_since_tlast:
                            seen["gap_before_f0"] += 1
                    cur = {"sum": 0, "f0": fin, "nf": 0, "n": neff, "run": runflag, "gap": False, "boot": boot, "ovr": False,
                           "edge_p": False, "edge_n": False}
                    boot = False
                    started = True
                cur["nf"] += 1
            s = sum((x >> 2) ** 2 for x in b)
            if min(b) == -32768 and max(b) == -32768:
                seen["maxbeat"] += 1
            cur["sum"] += s
            if max(b) >= OVR_TH or min(b) <= -OVR_TH:
                cur["ovr"] = True
                # しきい値ちょうどの値だけで立った区切りを、正負それぞれ数える（D の判定は窓の中だけ）
                if max(b) == OVR_TH and min(b) > -OVR_TH:
                    cur["edge_p"] = True
                if min(b) == -OVR_TH and max(b) < OVR_TH:
                    cur["edge_n"] = True
            gap_since_tlast = False
            m += 1
            if m == M:
                m = 0
                fin += 1
        else:
            if cur is not None:
                cur["gap"] = True
            gap_since_tlast = gap_since_tlast or (m == 0)
        if run_now:
            pend = fin_c + 2
            last_f0 = pend
            tp_n = r_tpn
    return bins, last_f0, r_tpn, tp_n, seen


def entry(b):
    flags = (1 if b["nf"] != b["n"] else 0) | (2 if b["run"] else 0) | (4 if b["gap"] else 0) | (8 if b["boot"] else 0) | (16 if b["ovr"] else 0)
    return (b["sum"] & 0xFFFFFFFF, b["sum"] >> 32, b["f0"] & 0xFFFFFFFF, (flags << 24) | b["nf"])


def check(out, posctl=False):
    nfail = 0
    fails = []

    def judge(ok, msg):
        nonlocal nfail
        print(("OK   " if ok else "NG   ") + msg)
        if not ok:
            nfail += 1
            fails.append(msg[:2])

    valid, beats, cmds = load(out)
    regs, slots, runf0 = {}, {}, []
    nbeat_tb = None
    for l in open(os.path.join(out, "tp_out.txt")):
        t = l.split()
        if t[0] == "REG":
            regs[t[1]] = int(t[2])
        elif t[0] == "SLOT":
            # 書かれていない slot は x（BRAM の初期値を持たせていない）。-1 として比べる
            slots[int(t[1])] = tuple(int(x) if x.isdigit() else -1 for x in t[2:6])
        elif t[0] == "RUNF0":
            runf0.append(int(t[2]))
        elif t[0] == "BEATS":
            nbeat_tb = int(t[1])
    judge(nbeat_tb == len(beats), "試験台が流したビート %s = 入力 %d" % (nbeat_tb, len(beats)))

    # 模型の F0 は「RUN のクロックの fin + 2」。命令の立ち下がりで試験台が見た fin + 2 と一致すること（模型と試験台の整合）
    bins, last_f0, r_tpn, tp_n, seen = model(valid, beats, cmds)
    meta = np.load(os.path.join(out, "tp_meta.npy"))
    judge(runf0 == [int(meta[2]), int(meta[3])], "RUN の F0（試験台）%s = gen の予定 %s" % (runf0, [int(meta[2]), int(meta[3])]))

    wp = regs.get("TP_WP")
    judge(wp == len(bins), "A. TP_WP = %s（模型 %d）" % (wp, len(bins)))
    nchk = min(len(bins), DEPTH)
    bad = []
    for i in range(len(bins) - nchk, len(bins)):
        want = entry(bins[i])
        got = slots[i % DEPTH]
        if got != want:
            bad.append((i, want, got))
    judge(len(bad) == 0, "B. リングバッファの最後の %d 個が 1 bit も違わない（食い違い %d 個）" % (nchk, len(bad)))
    for i, want, got in bad[:5]:
        print("       個 %d: 期待 %s / 実際 %s" % (i, want, got))

    f0 = regs.get("TP_F0_LO", 0) | (regs.get("TP_F0_HI", 0) << 32)
    judge(f0 == runf0[-1], "C. TP_F0 = %d（最後の RUN の fin + 2 = %d）" % (f0, runf0[-1]))
    judge(regs.get("TP_N") == r_tpn and regs.get("TP_NEFF") == (tp_n or 1),
          "C. TP_N = %s / TP_NEFF = %s（期待 %d / %d）" % (regs.get("TP_N"), regs.get("TP_NEFF"), r_tpn, tp_n or 1))
    judge(regs.get("TP_PARAM") == (512 << 16) | (16 << 8) | 2, "C. TP_PARAM = %08x" % regs.get("TP_PARAM", 0))
    judge(regs.get("TP_STAT") == 2, "C. TP_STAT = %s（期待 2: 区切りの途中・F0 待ちでない）" % regs.get("TP_STAT"))
    judge(regs.get("TP_7") == 0xDEADBEEF, "C. 番地の外（0x11C）は DEAD_BEEF（在ってはいけないものが読めない）")

    # D. 場面を本当に通ったか
    nshort = sum(1 for b in bins if b["nf"] != b["n"])
    nrun = sum(1 for b in bins if b["run"])
    ngap = sum(1 for b in bins if b["gap"])
    judge(seen["gap_before_f0"] == 2, "D. F0 の頭の直前に隙間があった RUN が 2 回（%d）" % seen["gap_before_f0"])
    judge(nrun == 2 and nshort >= 1, "D. F0 で始まった区切り %d・短い区切り %d" % (nrun, nshort))
    tail = bins[len(bins) - nchk:]
    judge(any(b["run"] for b in tail) and any(b["nf"] != b["n"] for b in tail),
          "D. 最後の %d 個（リングバッファに残る窓）の中に F0 で始まった区切りと短い区切りがある" % nchk)
    judge(len(bins) > DEPTH, "D. リングバッファが一巡した（%d > %d）" % (len(bins), DEPTH))
    judge(ngap >= 1 and seen["maxbeat"] >= 1, "D. 隙間の FLAG %d 個・最大振幅のビート %d" % (ngap, seen["maxbeat"]))
    # proj017: 振り切れの FLAG[4]。窓の中に立つ区切りと立たない区切りの両方があり、しきい値ちょうどの値だけで立った区切りもある
    novr = sum(1 for b in tail if b["ovr"])
    # しきい値ちょうど（+32764 / −32764）の値だけで立った区切りが、リングに残る窓の中に正負とも在ること（B の照合がそこを通る）
    nep = sum(1 for b in tail if b["ovr"] and b["edge_p"] and not b["edge_n"])
    nen = sum(1 for b in tail if b["ovr"] and b["edge_n"] and not b["edge_p"])
    judge(0 < novr < len(tail) and nep >= 1 and nen >= 1,
          "D. 振り切れの FLAG: 最後の %d 個のうち %d 個・+32764 だけで立った区切り %d・−32764 だけで立った区切り %d" % (len(tail), novr, nep, nen))
    if posctl == "ovr":
        # 陽性対照（TP_OVR_POSCTL）: しきい値ちょうど（+32764）を見落とすはず → B が落ち、D は通る
        ok = "B." in fails and not any(f == "D." for f in fails)
        print("陽性対照（振り切れ）: B の食い違い %s / D の不通過 %s" % ("B." in fails, any(f == "D." for f in fails)))
        print("結果: %s" % ("全部通過（陽性対照が落ちるべきところで落ちた）" if ok else "陽性対照が落ちなかった（見張りが効いていない）"))
        return 0 if ok else 1
    if posctl:
        # 陽性対照（TP_POSCTL）: F0 の頭の直前の隙間で F0 を見落とすはず → A か B が落ち、D（場面を通ったか）は通る
        ok = any(f in ("A.", "B.") for f in fails) and not any(f == "D." for f in fails)
        print("陽性対照: A・B の食い違い %s / D の不通過 %s" % (any(f in ("A.", "B.") for f in fails), any(f == "D." for f in fails)))
        print("結果: %s" % ("全部通過（陽性対照が落ちるべきところで落ちた）" if ok else "陽性対照が落ちなかった（見張りが効いていない）"))
        return 0 if ok else 1
    print("結果: %s" % ("全部通過" if nfail == 0 else "%d 件失敗" % nfail))
    return nfail


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        gen(sys.argv[2])
    else:
        pc = sys.argv[3] if len(sys.argv) > 3 else ""
        sys.exit(1 if check(sys.argv[2], posctl=("ovr" if pc == "ovr" else pc == "posctl")) else 0)

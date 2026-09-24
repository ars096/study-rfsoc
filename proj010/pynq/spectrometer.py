#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj010 — 分光計（ADC → 8192 点 FFT → 電力 → 積分）を動かし、判定する。

PL の spec_core が 1 フレーム 8192 サンプル（2.000 µs）ごとに FFT して電力を積み、
N_ACC フレームごとに 1 ダンプ（4096 ch × 64 bit）を閉じる。PS は AXI4-Lite で
凍っている面を読むだけ。レジスタの意味は src/spec_core.v の冒頭が正。

**周波数軸（ゾーン 2）: ch k は IF = 4096 − 0.5·k MHz。**ch 0 が 4096 MHz、ch 4095 が 2048.5 MHz。
スペクトルは反転している（proj009 と同じ）。

使い方（ボード上で sudo が要る）:

    sudo python3 spectrometer.py --clkin 0 --probe                  # 判定 0: 流れているか・フレームの速さ
    sudo python3 spectrometer.py --clkin 0 --golden --tone 3000.25  # 判定 2: 同じフレームを numpy と照合
    sudo python3 spectrometer.py --clkin 0 --tone 3000.25           # 判定 1: 線がどの ch に立つか
    sudo python3 spectrometer.py --clkin 0 --radiometer --ndump 50  # 判定 3: σ/μ = 1/√(Δν·τ)
    sudo python3 spectrometer.py --clkin 0 --radiometer --nacc 5000,50000,500000 --ndump 30
    sudo python3 spectrometer.py --clkin 0 --ndump 100 --save run.npz   # 記録

1PPS が ADC に入ったまま（SG なし）でできるもの:

    sudo python3 spectrometer.py --clkin 0 --tick 60                     # 判定 7: PPS の縁で積分の連続性を見る
    sudo python3 spectrometer.py --clkin 0 --nacc 500000 --ndump 60 --peaks 30   # 判定 8: 固定の線（60 s 積分）

**トーンを 0.5 MHz の倍数に置くと ch の中心に立つ**（3000.0 MHz → ch 2192）。
0.25 MHz ずらすと ch の境目に落ち、矩形窓の落ち込み（−3.92 dB）が見える。

**レベルを測るときは `--sg-dbm` と `--atten-db` を必ず付ける**（proj003 → proj005 の教訓）。
"""

import argparse
import sys
import time

import numpy as np

BITFILE = "proj010.bit"
FS_HZ = 4096.0e6
NFFT = 8192
NCH_OUT = 4096
DF_HZ = FS_HZ / NFFT              # 0.5 MHz
T_FRAME = NFFT / FS_HZ            # 2.000 µs
ID_EXPECT = 0x00100001

LMK_FREQ = 245.76
LMX_FREQ = 491.52
TILE, SLICE, BLOCK = 2, 0, 0      # ADC_B = Tile 226 / slice 0 → PYNQ の blocks[0]（VERSIONS.md）

# ---- レジスタ（src/spec_core.v の冒頭と対）----
R_ID, R_PARAM, R_CTRL, R_NACC, R_NDUMP, R_SHIFT = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14
R_FLAGS, R_SEQ, R_FIN_LO, R_FIN_HI, R_FOUT_LO, R_FOUT_HI = 0x18, 0x1C, 0x20, 0x24, 0x28, 0x2C
R_DUMP_K, R_DUMP_N, R_DUMP_F0_LO, R_DUMP_F0_HI, R_DUMP_SAT = 0x30, 0x34, 0x38, 0x3C, 0x40
R_SNAP_F_LO, R_SNAP_F_HI, R_BANK, R_RUN_F0_LO, R_RUN_F0_HI = 0x44, 0x48, 0x4C, 0x50, 0x54
SNAP_BASE, SPEC_BASE = 0x4000, 0x8000
CTRL_RUN, CTRL_STOP, CTRL_CLR = 1 << 0, 1 << 1, 1 << 8

FLAG_NAMES = ["レーンの出力 valid が不揃い", "レーンの XK_INDEX が不揃い", "レーンの入力 ready が不揃い",
              "IP が入力を受けなかった（サンプル落ち）", "入力に隙間", "IP の TLAST 事象",
              "IP の data_in_channel_halt", "XK_INDEX が 1 ずつ進まない"]


def log(*a):
    print(*a, flush=True)


def ch_of_if(f_mhz, zone=2):
    """IF [MHz] → ch（小数）。ゾーン 2 は fs − f に折り返る。"""
    fa = FS_HZ / 1e6 - f_mhz if zone == 2 else f_mhz
    return fa / (DF_HZ / 1e6)


def if_of_ch(k, zone=2):
    fa = np.asarray(k) * DF_HZ / 1e6
    return FS_HZ / 1e6 - fa if zone == 2 else fa


# --------------------------------------------------------------------- spec_core
class Spec:
    """spec_core の AXI4-Lite。**読んだ中身は seqlock で 1 つのダンプのものと保証する。**"""

    def __init__(self, mmio, slow=False):
        self.m = mmio
        self.slow = slow

    def rd(self, a):
        return self.m.read(a)

    def wr(self, a, v):
        self.m.write(a, int(v))

    def rd64(self, lo, hi):
        l = self.rd(lo)                      # LO を読むと HI が固定される（FIN / FOUT）
        return (self.rd(hi) << 32) | l

    def block(self, base, nwords):
        """32 bit 語を nwords 個読む。既定は numpy で一括（速い）。--slow-read で 1 語ずつ。"""
        if self.slow:
            return np.array([self.rd(base + 4 * i) for i in range(nwords)], dtype=np.uint32)
        i0 = base // 4
        return np.array(self.m.array[i0:i0 + nwords], dtype=np.uint32)

    def flags(self):
        return self.rd(R_FLAGS)

    def meta(self):
        return dict(
            seq=self.rd(R_SEQ), k=self.rd(R_DUMP_K), n=self.rd(R_DUMP_N),
            f0=(self.rd(R_DUMP_F0_HI) << 32) | self.rd(R_DUMP_F0_LO),
            sat=self.rd(R_DUMP_SAT),
            snap_f=(self.rd(R_SNAP_F_HI) << 32) | self.rd(R_SNAP_F_LO),
            bank=self.rd(R_BANK), flags=self.rd(R_FLAGS))

    def run(self, nacc, ndump, shift):
        self.wr(R_NACC, nacc)
        self.wr(R_NDUMP, ndump)
        self.wr(R_SHIFT, shift)
        seq0 = self.rd(R_SEQ)
        self.wr(R_CTRL, CTRL_RUN)
        return seq0

    def stop(self):
        self.wr(R_CTRL, CTRL_STOP)

    def wait_dump(self, seq_prev, timeout):
        t0 = time.time()
        while True:
            s = self.rd(R_SEQ)
            if s != seq_prev:
                return s
            if time.time() - t0 > timeout:
                return None
            time.sleep(0.001)

    def read_dump(self, with_snap=False, tries=5):
        """凍っている面を読む。**SEQ が読む前後で同じなら 1 つのダンプ。**違えば読み直す。"""
        for _ in range(tries):
            m = self.meta()
            w = self.block(SPEC_BASE, 2 * NCH_OUT)
            spec = w[0::2].astype(np.uint64) | (w[1::2].astype(np.uint64) << np.uint64(32))
            snap = None
            if with_snap:
                s = self.block(SNAP_BASE, NFFT // 2)
                snap = np.empty(NFFT, dtype=np.int16)
                snap[0::2] = (s & 0xFFFF).astype(np.uint16).view(np.int16)
                snap[1::2] = (s >> 16).astype(np.uint16).view(np.int16)
            if self.rd(R_SEQ) == m["seq"]:
                return m, spec, snap
        raise RuntimeError("読み出しのあいだに毎回ダンプが閉じた。積分時間に対して読み出しが遅すぎる")


def flag_text(f):
    return "なし" if f == 0 else " / ".join(n for i, n in enumerate(FLAG_NAMES) if f >> i & 1)


# --------------------------------------------------------------------- 起動（proj009 の adc_capture.py から）
def setup_clocks(clkin="stock", ref_mhz=10.0):
    if clkin != "stock":
        import extref
        extref.set_clocks(int(clkin), ref_mhz=ref_mhz)
        return
    import xrfclk
    fn = getattr(xrfclk, "set_ref_clks", None) or getattr(xrfclk, "set_ref_clk", None)
    if fn is None:
        log("ERROR: xrfclk に set_ref_clks / set_ref_clk のどちらも無い")
        sys.exit(1)
    log(f"xrfclk.{fn.__name__}(lmk_freq={LMK_FREQ}, lmx_freq={LMX_FREQ})   ← 出荷時のクロック源")
    fn(lmk_freq=LMK_FREQ, lmx_freq=LMX_FREQ)


def check_tile(rfdc, zone):
    """タイルは Overlay の時点で動いている。**触らずに確かめ、ゾーンだけ設定して読み返す。**"""
    tile = rfdc.adc_tiles[TILE]
    block = tile.blocks[BLOCK]
    lock = tile.PLLLockStatus
    st = block.BlockStatus
    log(f"Tile {224 + TILE} / slice {SLICE}: PLLLockStatus = {lock}（2 = locked）/ "
        f"SamplingFreq = {st.get('SamplingFreq')} GSPS")
    if lock != 2 or abs(st.get("SamplingFreq", 0) * 1e9 - FS_HZ) > 1e3:
        log("ERROR: タイル PLL がロックしていないか、fs が違う")
        sys.exit(1)
    block.NyquistZone = zone
    if block.NyquistZone != zone:
        log(f"ERROR: NyquistZone が {block.NyquistZone} のまま（要求 {zone}）")
        sys.exit(1)
    log(f"NyquistZone = {zone}")
    return block


# --------------------------------------------------------------------- 判定
def probe(sp):
    """判定 0: 流れているか。fin − fout が一定か。フレームが 1 秒に 500,000 進むか。"""
    ident, prm = sp.rd(R_ID), sp.rd(R_PARAM)
    log(f"ID = {ident:08x}（期待 {ID_EXPECT:08x}） / PARAM = {prm:08x}"
        f"（log2 N = {prm & 0xFF} / log2 レーン = {prm >> 8 & 0xFF} / QW = {prm >> 16 & 0xFF} / IW = {prm >> 24}）")
    ok = ident == ID_EXPECT
    fin0, t0 = sp.rd64(R_FIN_LO, R_FIN_HI), time.time()
    time.sleep(1.0)
    fin1, t1 = sp.rd64(R_FIN_LO, R_FIN_HI), time.time()
    rate = (fin1 - fin0) / (t1 - t0)
    log(f"FIN  {fin0} → {fin1}（{rate:,.0f} フレーム/s、期待 {1 / T_FRAME:,.0f}。PS 側の時計で測るので ±0.1 % 程度）")
    ok &= abs(rate * T_FRAME - 1) < 5e-3

    # **FIN と FOUT は別々の AXI4-Lite 読み出しで、間に数十 µs（= 十数フレーム）空く。**
    # 1 回ずつ読んで差を取ると、パイプラインの深さではなく「読み出しの間隔」を測ってしまう
    # （2026-09-19 の初回: FIN − FOUT = −9 → −11。負になるのは FOUT を後で読んでいるため）。
    # FIN → FOUT → FIN と挟んで読めば、FOUT を読んだ瞬間の FIN は前後の 2 つの間にある。
    # 何度も挟んで区間を狭め、深さ L を [下限, 上限] で出す。**時間をおいて 2 回測り、区間が重なれば一定**。
    def depth(n=300):
        lo, hi = -10**9, 10**9
        for _ in range(n):
            a = sp.rd64(R_FIN_LO, R_FIN_HI)
            o = sp.rd64(R_FOUT_LO, R_FOUT_HI)
            b = sp.rd64(R_FIN_LO, R_FIN_HI)
            lo, hi = max(lo, a - o), min(hi, b - o)
        return lo, hi
    d0 = depth()
    time.sleep(5.0)
    d1 = depth()
    log(f"パイプラインの深さ FIN − FOUT（挟み読みの区間）: [{d0[0]}, {d0[1]}] → 5 s 後 [{d1[0]}, {d1[1]}] フレーム")
    cons = d0[0] <= d0[1] and d1[0] <= d1[1]
    same = cons and max(d0[0], d1[0]) <= min(d0[1], d1[1])
    log(f"  区間が成り立つ（下限 ≦ 上限）: {'OK' if cons else '**NG**（カウンタの読み方か意味が想定と違う）'} / "
        f"2 回が重なる = 一定: {'OK' if same else '**NG**（IP がフレームを落としたか、足した）'}")
    ok &= same
    f = sp.flags()
    log(f"FLAGS = {f:02x}（{flag_text(f)}）")
    ok &= f == 0
    # 一括読み出しと 1 語ずつの読み出しが一致するか（MMIO の読み方の確認）
    a = Spec(sp.m, slow=False).block(SPEC_BASE, 64)
    b = Spec(sp.m, slow=True).block(SPEC_BASE, 64)
    log(f"一括読み出しと 1 語ずつの読み出し: {'一致' if np.array_equal(a, b) else '**不一致**（--slow-read を使う）'}")
    ok &= np.array_equal(a, b)
    log(f"判定 0: {'OK' if ok else '**NG**'}")
    return ok


def golden(sp, shift, tone):
    """判定 2: N_ACC = 1 のダンプと、同じフレームのスナップショットを numpy で FFT したものが一致するか。"""
    seq0 = sp.run(1, 1, shift)
    if sp.wait_dump(seq0, 1.0) is None:
        log("ERROR: 1 フレームのダンプが閉じない")
        return False
    m, spec, snap = sp.read_dump(with_snap=True)
    log(f"DUMP: seq {m['seq']} / F0 {m['f0']} / N {m['n']} / SAT {m['sat']} / SNAP_F {m['snap_f']} / "
        f"FLAGS {m['flags']:02x}")
    ok = m["snap_f"] == m["f0"]
    log(f"SNAP_F == DUMP_F0: {'OK' if ok else '**違う**（スナップショットが別のフレーム）'}")
    ok &= bool(np.all(snap & 3 == 0))
    x = (snap.astype(np.int64) >> 2).astype(float)
    X = np.fft.fft(x)[:NCH_OUT]
    ref = np.abs(X) ** 2 / 4.0 ** shift
    hw = spec.astype(float)
    good = ref < 0.9 * (2 ** 17 - 1) ** 2                # 飽和した ch は除く
    # 許容は「2 LSB ＋ 同じ k1（= k mod 512 とその鏡像）の組の最大振幅 × 3e-5」。
    # ひねり係数の丸めの誤差はレーン FFT の出力 Y_p[k1] に比例し、Y_p[k1] には k1 を共有する ch が全部乗る。
    # **強い線は 512 ch おきの ch に −100 dBc 級の誤差を落とす**（sim の SHIFT 4 で確認。sim/check.py）
    full = np.abs(np.fft.fft(x)) / 2.0 ** shift
    grp = full.reshape(-1, 512).max(axis=0)              # [k1]
    k1 = np.arange(NCH_OUT) % 512
    gmax = np.maximum(grp[k1], grp[(512 - k1) % 512])
    d = np.abs(np.sqrt(hw) - np.sqrt(ref))[good]
    # **FFT IP の内部の丸め**（unscaled でも各段のひねり係数の積を入力の LSB で丸める）は、後段の変換で
    # √(残りの点数) 倍に増幅され、**入力の大きさに依らない絶対量**として出る。512 点の基数 2 を各段で丸める
    # 模型（2026-09-19）では、|X| の差の平均 ≒ 8 LSB・最大（4096 ch 中）≒ 45〜65 LSB（SHIFT 0 のとき）。
    # 初回の実機は 9.5 / 61 で、模型と合った。sim のモデルは倍精度の FFT で丸めないので、この項が無かった。
    fl_mean, fl_max = 8.0 / 2 ** shift, 65.0 / 2 ** shift
    tol_max = 2.0 * fl_max + 2.0 + 3e-5 * gmax[good]
    w = int(np.argmax(d / tol_max))
    log(f"振幅の差（SHIFT 後の LSB）: 平均 {d.mean():.2f}（IP の丸めの模型 {fl_mean:.2f}）/ "
        f"最大 {d.max():.2f}（模型 {fl_max:.1f}）/ 差/許容 の最大 {(d / tol_max)[w]:.2f}（{good.sum()} ch）")
    ok &= bool(d.mean() < 2.0 * fl_mean + 1.0) and bool(np.all(d < tol_max))
    xs = x.std()
    log(f"スナップショット: std {xs:.1f}（14 bit の LSB）/ max|x| {np.abs(x).max():.0f}")
    if tone is not None:
        k = int(np.argmax(hw[1:])) + 1
        log(f"最大の ch = {k}（IF {if_of_ch(k):.3f} MHz）/ トーンの期待 ch = {ch_of_if(tone):.2f}")
    return ok


def spectrum_report(spec, m, tone, sg_dbm, atten_db, shift):
    n = max(m["n"], 1)
    p = spec.astype(float) / n                             # 1 フレームあたりの電力（SHIFT 後）
    k = int(np.argmax(p[1:])) + 1
    floor = np.median(p)
    log(f"ダンプ: seq {m['seq']} / k {m['k']} / N {m['n']}（{m['n'] * T_FRAME * 1e3:.1f} ms）/ "
        f"SAT {m['sat']} / FLAGS {m['flags']:02x}（{flag_text(m['flags'])}）")
    log(f"最大の ch = {k}（IF {if_of_ch(k):.3f} MHz）: {10 * np.log10(p[k] / floor):.2f} dB（中央値比）")
    # 振幅（14 bit の LSB）へ戻す: |X| = √p · 2^shift、正弦波 A → |X| = A·N/2
    amp14 = np.sqrt(p[k]) * 2 ** shift * 2 / NFFT
    dbfs = 20 * np.log10(amp14 / 8192)
    log(f"  線の振幅 ≒ {amp14:.1f} LSB（14 bit）= {dbfs:.2f} dBFS（ch の中心に乗っている場合。境目なら最大 −3.92 dB）")
    if tone is not None:
        kt = ch_of_if(tone)
        log(f"  トーン {tone} MHz の期待 ch = {kt:.2f} → 実際 {k}（{'OK' if abs(k - kt) <= 0.5 else '**違う**'}）")
        if sg_dbm is not None:
            log(f"  レベルの帳簿: SG {sg_dbm:+.2f} dBm − 減衰 {atten_db:.1f} dB = ADC 入力 {sg_dbm - atten_db:+.2f} dBm"
                f" → 0 dBFS 換算 {sg_dbm - atten_db - dbfs:+.2f} dBm（VERSIONS.md: +5.8 dBm）")
    return k


def radiometer(sp, nacc_list, ndump, shift):
    """判定 3: 雑音の ch ごとの σ/μ が 1/√(Δν·τ) になるか。

    Δν は矩形窓の等価雑音帯域 = 1 ch = 0.5 MHz。τ = N_ACC × 2 µs。
    **連続する 2 ダンプの差**で σ を取る（利得のゆっくりした変化を消すため）: σ/μ = std(d)/μ/√2。
    外れ方で原因が分かれる: 大きい → デッドタイム・相関・利得の速い揺れ / 小さい → 同じ中身を 2 度積んでいる。
    """
    ok = True
    log("")
    log("   N_ACC      τ[ms]   期待 σ/μ     実測 σ/μ（中央値）  比     共通利得を除いた比  SAT   FLAGS")
    for nacc in nacc_list:
        tau = nacc * T_FRAME
        seq = sp.run(nacc, ndump, shift)
        specs = []
        for i in range(ndump):
            s = sp.wait_dump(seq, tau * 3 + 1.0)
            if s is None:
                log(f"ERROR: ダンプ {i} が閉じない")
                return False
            m, spec, _ = sp.read_dump()
            if m["seq"] != seq + 1 and i > 0:
                log(f"  NOTE: ダンプを {m['seq'] - seq - 1} 個読み落とした（読み出しが遅い）")
            seq = m["seq"]
            specs.append(spec.astype(float))
        a = np.array(specs)
        # 両端（直流付近と ch 4095 側）と強い線を除く
        sel = np.zeros(NCH_OUT, bool)
        sel[50:NCH_OUT - 50] = True
        sel &= a.mean(axis=0) < np.median(a.mean(axis=0)) * 3
        # **1PPS が ADC に入っているときの対策。**PPS の縁（毎秒 2 回、広帯域）を含むダンプだけ全 ch が
        # 持ち上がる。そのダンプと、それを含む差を外す。τ ≧ 1 s ならどのダンプも同じ数の縁を含むので外れない
        tot = a[:, sel].sum(axis=1)
        bad = _outliers(tot)
        if bad.any():
            log(f"  NOTE: 全 ch の和が外れたダンプを {bad.sum()} / {len(bad)} 個外した（PPS の縁と見る）")
        keep = ~bad
        mu = a[keep].mean(axis=0)
        pair = keep[1:] & keep[:-1]
        d = np.diff(a, axis=0)[pair]
        if len(d) < 2:
            log("ERROR: 外れを除いたら差が 2 個未満になった。--ndump を増やす")
            return False
        r = (d[:, sel].std(axis=0) / mu[sel] / np.sqrt(2))
        got = float(np.median(r))
        want = 1 / np.sqrt(DF_HZ * tau)
        ratio = got / want
        # **全 ch に共通の利得の揺れを除いた比。**2026-09-19・24（1PPS が ADC に入ったまま）、全 ch が一緒に 0.25 % 揺れ、
        # ch ごとの比が一様に 1.17 倍になった。各ダンプを静かな ch の和で割ると 1.03 倍に戻った（tick_analyze の 7）。
        # 判定はこちらで行う: 分光計の積分（デッドタイム・二度積み）を見る試験で、アナログの利得の揺れは別の項目。
        # **利得は ch ごとの比の中央値で取る（和ではなく）。**和で取ると、間欠的な混信（2026-09-24 の 823 MHz）が
        # 載る ch の揺れが利得に入り、割ると全 ch に配られる（1 s で 1.63 → 1.86 と悪化した）
        g = np.median(a[:, sel] / a[keep][:, sel].mean(axis=0), axis=1)
        an = a / g[:, None]
        mun = an[keep].mean(axis=0)
        dn = np.diff(an, axis=0)[pair]
        ratio_n = float(np.median(dn[:, sel].std(axis=0) / mun[sel] / np.sqrt(2))) / want
        log(f"  {nacc:>8}  {tau * 1e3:>8.1f}   {want:.3e}    {got:.3e}           {ratio:5.3f}  {ratio_n:5.3f}"
            f"              {m['sat']:>5}  {m['flags']:02x}")
        ok &= abs(ratio_n - 1) < 0.1 and m["flags"] == 0
    return ok


def _outliers(x, nsig=8.0):
    """中央値と MAD から外れ（上側だけ）を出す。雑音の揺れに対して nsig 倍を越えたもの"""
    med = np.median(x)
    sig = 1.4826 * np.median(np.abs(x - med))
    if sig == 0:
        return np.zeros(len(x), bool)
    return (x - med) > nsig * sig


def tick(sp, nacc, seconds, shift, save=None):
    """判定 7: ADC に入っている 1PPS の縁を分光計で見て、**積分が外部の時計と整合して途切れないか**を確かめる。

    PPS（100 µs 幅）の縁は広帯域なので、縁を含むダンプだけ全 ch の和が持ち上がる。ダンプは隙間なく並ぶので、
    **持ち上がるダンプの間隔は 1 s / τ ダンプちょうど**（N_ACC = 50000 なら 10 ダンプ）で、秒の中の位置
    （フレーム番号 mod 500,000）も動かない。フレームを 1 つでも落とせば、秒内の位置がずれる。
    読み出しが追いつかずにダンプを飛ばした場合は、DUMP_K の飛びとして出る（判定から外す）。
    """
    tau = nacc * T_FRAME
    ndump = int(round(seconds / tau))
    fps = int(round(1 / T_FRAME))                   # 500,000 フレーム/s
    seq = sp.run(nacc, 0, shift)
    rows = []                                       # (k, f0, 全 ch の和)
    specs = []
    t0 = time.time()
    while len(rows) < ndump:
        s = sp.wait_dump(seq, tau * 3 + 1.0)
        if s is None:
            log("ERROR: ダンプが閉じない")
            return False
        m, spec, _ = sp.read_dump()
        seq = m["seq"]
        rows.append((m["k"], m["f0"], float(spec[50:NCH_OUT - 50].astype(float).sum()), m["flags"], m["sat"]))
        if save:
            specs.append(spec.astype(np.float32))
    sp.stop()
    k = np.array([r[0] for r in rows])
    f0 = np.array([r[1] for r in rows], dtype=np.int64)
    tot = np.array([r[2] for r in rows])
    flags = [r[3] for r in rows]
    sat = np.array([r[4] for r in rows], dtype=np.int64)
    gaps = int(np.sum(np.diff(k) != 1))
    log(f"τ = {tau * 1e3:.1f} ms × {len(rows)} ダンプ（{time.time() - t0:.1f} s）/ 読み落とし {gaps} 箇所"
        f"（DUMP_K の飛び。読み出しが遅いだけで、積分の連続性とは別）")
    if np.any(np.diff(f0) != np.diff(k) * nacc):
        log("**NG: DUMP_F0 の間隔が DUMP_K × N_ACC と合わない**（ダンプの帳簿が壊れている）")
        return False
    if save:
        np.savez(save, k=k, f0=f0, tot=tot, sat=sat, spec=np.array(specs), nacc=nacc, shift=shift)
        log(f"saved: {save}")
    # **全 ch の和の揺れ方を先に見る。**雑音だけなら揺れは 1/√(帯域·τ) で、隣り合うダンプは無相関
    # （差の揺れ = √2 × 揺れ）。ゆっくり動く（利得・較正・外来の干渉）なら差の揺れのほうがずっと小さい。
    # 2026-09-19 の初回は揺れが期待の 110 倍で、縁が外れとして立たなかった
    med0 = np.median(tot)
    sd = tot.std() / med0
    sdd = np.diff(tot).std() / med0 / np.sqrt(2)
    log(f"全 ch の和の揺れ: σ {sd:.2e} / 隣との差から見た σ {sdd:.2e}（比 {sdd / sd:.2f}。1 なら白い揺れ、"
        f"小さければゆっくり動いている）/ 期待 {1 / np.sqrt(FS_HZ / 2 * tau):.2e}")
    # ゆっくりした動きを除いてから縁を探す（前後 5 ダンプの中央値を引く）
    base = np.array([np.median(tot[max(0, i - 5):i + 6]) for i in range(len(tot))])
    res = tot - base
    bad = _outliers(res)
    med = np.median(tot)
    sig = 1.4826 * np.median(np.abs(res - np.median(res)))
    # 隣り合う外れは 1 つの事象（縁がダンプの境目にかかった）として先頭を取る
    ev = [i for i in np.where(bad)[0] if i == 0 or not bad[i - 1]]
    log(f"全 ch の和: 中央値 {med:.4e} / ゆっくりした動きを除いた揺れ（MAD 換算）{sig / med:.2e}")
    log(f"外れたダンプ: {int(bad.sum())} 個 → 事象 {len(ev)} 個（期待 約 {len(rows) * tau:.0f} 個 = 1 秒に 1 回）")
    if len(ev) < 2:
        log("**PPS の縁が見えない。**ADC_B に 1PPS が来ているか、縁が雑音に埋もれているか（減衰が大きすぎる）")
        return False
    for i in ev[:12]:
        log(f"  k {k[i]:>7}  F0 {f0[i]:>12}  秒内の位置 {f0[i] % fps:>7} フレーム  "
            f"超過 {res[i] / med * 100:+.3f} %（{res[i] / sig:.0f} σ）")
    phase = np.array([f0[i] % fps for i in ev])
    # 秒内の位置は 1 ダンプ（nacc フレーム）の粒度で決まる。縁が境目をまたげば 1 ダンプ揺れうる
    spread = int(phase.max() - phase.min())
    dd = np.diff([k[i] for i in ev])
    per = 1 / tau
    log(f"事象の間隔（ダンプ数）: {sorted(set(dd.tolist()))}（期待 {per:g}）")
    log(f"秒内の位置の広がり: {spread} フレーム（期待 0。縁が境目にかかれば {nacc} まで）")
    ok = spread <= nacc and all(f == 0 for f in flags)
    if abs(per - round(per)) < 1e-9:
        ok &= all(d % int(round(per)) == 0 for d in dd)
    log(f"FLAGS: {'すべて 0' if all(f == 0 for f in flags) else '**0 でないダンプがある**'}")
    return ok


# ボード内のクロック（proj009 の adc_capture.py の表から）。無入力で立つ線の出どころを当てる
KNOWN_CLOCKS = [
    ("LMX2594 → RFDC 基準", 491.52e6), ("LMK04828 → LMX 基準", 245.76e6), ("LMK04828 → PL 基準", 122.88e6),
    ("DSP / clk_adc2 = fs/16", 256.0e6), ("ADC ドメイン = fs/12", FS_HZ / 12), ("MMCM の VCO", 1024.0e6),
    ("インタリーブ fs/8", 512.0e6), ("PS pl_clk0", 100.0e6), ("LMK の VCXO", 160.0e6), ("RF SYSREF", 7.68e6),
    # 2026-09-24 の判定 8 で ch 60・120・140・160・220・240・260・280（第 1 ゾーンで 30〜140 MHz の 10 MHz おき）に
    # 線が並んだ。外部基準（CLK_IN の 10 MHz）の高調波の回り込みと見る（--clkin stock との比較で確かめる）
    ("外部基準 10 MHz", 10.0e6),
]


def identify(k, tol_ch=1.0):
    """ch k（第 1 ゾーンに折り返した 0〜2048 MHz の位置）に落ちるクロックの高調波を探す。次数の低いものを優先"""
    best = None
    for name, f in KNOWN_CLOCKS:
        for h in range(1, 33):
            fa = (f * h) % FS_HZ
            fa = min(fa, FS_HZ - fa)
            kk = fa / DF_HZ
            if abs(kk - k) <= tol_ch and (best is None or h < best[0]):
                best = (h, f"{name}{' × %d' % h if h > 1 else ''}（ch {kk:.2f}）")
    return best[1] if best else ""


def peaks(spec, n, m):
    """細い線（周りの床から飛び出した ch）を大きい順に出す。**何も入れていないのに立つ線 = 固定のバーディー**"""
    p = spec.astype(float) / max(m["n"], 1)
    half = 16
    pad = np.pad(p, half, mode="edge")
    base = np.array([np.median(pad[i:i + 2 * half + 1]) for i in range(NCH_OUT)])
    r = p / np.maximum(base, 1e-30)
    order = [i for i in np.argsort(r)[::-1] if 2 <= i < NCH_OUT - 2][:n]
    log("")
    log(f"細い線（床比の大きい順・上位 {n}）")
    log("    ch     IF[MHz]   床比[dB]   候補")
    for i in order:
        log(f"  {i:>5}  {if_of_ch(i):>9.2f}  {10 * np.log10(r[i]):>8.2f}   {identify(i)}")


# --------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=BITFILE)
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"),
                   help="LMK の PLL1 の基準。0 = CLK_IN（外部 10 MHz）")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--zone", type=int, default=2, choices=(1, 2))
    p.add_argument("--settle", type=float, default=5.0, help="Overlay 後に待つ秒（背景較正の収束。proj009）")
    p.add_argument("--shift", default="auto", help="Z 29 bit → 18 bit の右シフト。auto = スナップショットの std から決める")
    p.add_argument("--nacc", default="50000", help="1 ダンプのフレーム数（2 µs 単位）。カンマ区切りで複数（--radiometer）")
    p.add_argument("--ndump", type=int, default=1)
    p.add_argument("--tone", type=float, default=None, help="入れた CW の IF [MHz]")
    p.add_argument("--sg-dbm", type=float, default=None)
    p.add_argument("--atten-db", type=float, default=0.0)
    p.add_argument("--probe", action="store_true")
    p.add_argument("--golden", action="store_true")
    p.add_argument("--radiometer", action="store_true")
    p.add_argument("--tick", type=float, default=None, metavar="SEC",
                   help="判定 7: ADC に入っている 1PPS の縁を SEC 秒ぶん見る（--nacc の最初の値を使う）")
    p.add_argument("--peaks", type=int, default=0, help="通常の測定の後、細い線を上位 N 個出す")
    p.add_argument("--save", default=None, help="スペクトルとメタデータを .npz で残す")
    p.add_argument("--slow-read", action="store_true", help="MMIO を 1 語ずつ読む")
    args = p.parse_args()
    if args.atten_db < 0:
        log("ERROR: --atten-db は正の値で書く（10 dB の減衰なら 10）")
        sys.exit(2)

    from pynq import Overlay
    import xrfdc                                  # **Overlay() より前に import する**（VERSIONS.md）
    setup_clocks(args.clkin, args.ref)
    ol = Overlay(args.bitfile)
    log(f"Overlay: {args.bitfile}")
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない（DefaultIP のまま）")
        sys.exit(1)
    check_tile(ol.rfdc, args.zone)
    if args.settle > 0:
        log(f"背景較正の収束を待つ: {args.settle} s")
        time.sleep(args.settle)

    sp = Spec(ol.spec_core_0.mmio, slow=args.slow_read)
    sp.stop()
    sp.wr(R_CTRL, CTRL_CLR)                       # 立ち上がりの隙間で立ったフラグを消す

    if args.probe:
        sys.exit(0 if probe(sp) else 1)

    # SHIFT: 雑音の成分の σ が SHIFT 後に 2^9 付近になるように選ぶ（強い線が 18 bit に収まる余地を残す）
    if args.shift == "auto":
        sp.run(1, 1, 0)
        time.sleep(0.01)
        _, _, snap = sp.read_dump(with_snap=True)
        sx = (snap.astype(np.int64) >> 2).std()
        sz = sx * np.sqrt(NFFT / 2)                    # 成分あたり
        shift = int(max(0, min(15, np.ceil(np.log2(max(sz, 1) / 512)))))
        log(f"SHIFT = {shift}（auto: 入力 std {sx:.1f} LSB → 成分の σ {sz:.0f} → {sz / 2 ** shift:.0f} LSB）")
    else:
        shift = int(args.shift)

    ok = True
    if args.golden:
        ok &= golden(sp, shift, args.tone)
    elif args.radiometer:
        ok &= radiometer(sp, [int(v) for v in args.nacc.split(",")], max(args.ndump, 3), shift)
    elif args.tick is not None:
        ok &= tick(sp, int(args.nacc.split(",")[0]), args.tick, shift, args.save)
    else:
        nacc = int(args.nacc.split(",")[0])
        seq = sp.run(nacc, args.ndump, shift)
        keep = []
        for i in range(args.ndump):
            if sp.wait_dump(seq, nacc * T_FRAME * 3 + 1.0) is None:
                log("ERROR: ダンプが閉じない")
                sys.exit(1)
            m, spec, _ = sp.read_dump()
            seq = m["seq"]
            keep.append((m, spec))
        m, spec = keep[-1]
        spectrum_report(spec, m, args.tone, args.sg_dbm, args.atten_db, shift)
        if args.peaks > 0:
            # 何ダンプも取ったなら全部を足して床を下げてから探す
            tot = np.sum([sp_.astype(np.float64) for _, sp_ in keep], axis=0)
            mm = dict(m, n=sum(x["n"] for x, _ in keep))
            peaks(tot, args.peaks, mm)
        ok &= m["flags"] == 0
        if args.save:
            np.savez(args.save, spec=np.array([s for _, s in keep]),
                     meta=np.array([[mm["seq"], mm["k"], mm["n"], mm["f0"], mm["sat"], mm["flags"]]
                                    for mm, _ in keep], dtype=np.int64),
                     meta_cols=np.array(["seq", "k", "n", "f0", "sat", "flags"]),
                     if_mhz=if_of_ch(np.arange(NCH_OUT), args.zone), shift=shift,
                     clkin=args.clkin, tone=np.nan if args.tone is None else args.tone,
                     sg_dbm=np.nan if args.sg_dbm is None else args.sg_dbm, atten_db=args.atten_db)
            log(f"saved: {args.save}")
    sp.stop()
    log("")
    log(f"RESULT {'OK' if ok else 'NG'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj003 — ADC_A の生サンプルを取得して FFT する。

使い方（ボード上で sudo が要る）:

    sudo python3 adc_capture.py --probe            # 何が見えているかだけ出す
    sudo python3 adc_capture.py --tone 100.0125    # 既定の検証（ビン中心のトーン）
    sudo python3 adc_capture.py --tone 100.0       # ビン中心から外す（リークを見る）
    sudo python3 adc_capture.py --tone 800.0 --zone 2   # 第 2 ナイキストゾーン
    sudo python3 adc_capture.py --save cap.npy     # 生サンプルを残す

**--probe は実機で最初に打つコマンド。** タイル・ブロックの番号の付き方と、
14bit サンプルのビット寄せが、ここで初めて確定する。
"""

import argparse
import sys
import time

import numpy as np

FS_HZ = 1228.8e6        # build.tcl の fs_gsps と一致させること
SPW = 8                 # AXI4-Stream 1 語あたりのサンプル数（build.tcl の spw）
N_DEFAULT = 65536
TILE = 2                # RF-ADC Tile 226
BLOCK = 0               # ADC_A = Tile 226 slice 0（ADC_B は slice 2）
BITFILE = "proj003.bit"

LMK_FREQ = 245.76
LMX_FREQ = 491.52

CTRL_ARM = 1 << 31
STATUS_BUSY = 1 << 0
STATUS_DONE = 1 << 1


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------- 起動
def setup_clocks():
    """LMK04828 / LMX2594 を設定する。

    関数名は xrfclk の版で変わる（v3.1.1 は set_ref_clks、旧版は set_ref_clk）。
    どちらでも動くように実体を探す。
    """
    import xrfclk
    fn = None
    for name in ("set_ref_clks", "set_ref_clk"):
        fn = getattr(xrfclk, name, None)
        if fn is not None:
            break
    if fn is None:
        log("ERROR: xrfclk に set_ref_clks / set_ref_clk のどちらも無い")
        log(f"  使える名前: {[n for n in dir(xrfclk) if not n.startswith('_')]}")
        sys.exit(1)
    log(f"xrfclk.{fn.__name__}(lmk_freq={LMK_FREQ}, lmx_freq={LMX_FREQ})")
    fn(lmk_freq=LMK_FREQ, lmx_freq=LMX_FREQ)


def start_tile(rfdc, fs_hz, zone, restart=False, pll_config=False):
    """タイルの状態を確かめる。**すでに動いていれば触らない。**

    ビットストリームをロードした時点でタイルは起動し、PLL もロックしている
    （2026-09-16 に確認: PLLLockStatus = 2 / SamplingFreq = 1.2288）。
    そこへ DynamicPLLConfig や StartUp をかけると、動いている状態をわざわざ
    壊しにいくことになる。**既定は検証のみ。** 明示的に指示されたときだけ触る。
    """
    tile = rfdc.adc_tiles[TILE]
    block = tile.blocks[BLOCK]

    if pll_config:
        # fs = 1228.8 = VCO 9830.4 / OutDiv 8、refclk 491.52 = VCO / 20
        log(f"DynamicPLLConfig(1, {LMX_FREQ}, {fs_hz / 1e6})")
        tile.DynamicPLLConfig(1, LMX_FREQ, fs_hz / 1e6)
    if restart:
        log("tile.ShutDown() → StartUp()")
        tile.ShutDown()
        tile.StartUp()
        time.sleep(0.2)

    try:
        tile.SetupFIFO(True)
    except Exception as e:                      # noqa: BLE001
        log(f"WARNING: SetupFIFO が失敗した: {e}")

    lock = tile.PLLLockStatus
    log(f"PLLLockStatus = {lock}  (2 = locked) / ClockSource = {_try(tile, 'ClockSource')}")
    if lock != 2:
        log("ERROR: タイル PLL がロックしていない。")
        log("  1. xrfclk.set_ref_clks() を呼んだか")
        log("  2. LMX が 491.52 MHz を出しているか")
        log("  3. --pll-config / --restart で作り直してみる")
        sys.exit(1)

    st = block.BlockStatus
    log(f"BlockStatus = {st}")
    got_fs = st.get("SamplingFreq")
    if got_fs is not None and abs(got_fs * 1e9 - fs_hz) > 1e3:
        log(f"ERROR: 実際の fs = {got_fs} GSPS が要求 {fs_hz / 1e9} GSPS と違う")
        sys.exit(1)
    log(f"fs (実機) = {got_fs} GSPS")

    try:
        block.NyquistZone = zone
        log(f"NyquistZone = {block.NyquistZone}")
    except Exception as e:                      # noqa: BLE001
        log(f"WARNING: NyquistZone を設定できない: {e}")
    return tile, block


def fifo_flags(block):
    """RFDC の FIFO オーバーフローを見る。

    ブロックに GetIntrStatus は無い（2026-09-16 に確認）。
    BlockStatus の IsFIFOFlagsAsserted が立てば取りこぼしが起きている。
    **これが記録の不連続を検出できる唯一の手段。**
    """
    try:
        st = block.BlockStatus
        return st.get("IsFIFOFlagsAsserted")
    except Exception as e:                      # noqa: BLE001
        return f"(読めない: {e})"


def _api(obj, keep):
    """オブジェクトが実際に持つ名前のうち、関係しそうなものだけ出す。"""
    return sorted(n for n in dir(obj)
                  if not n.startswith("_")
                  and any(k.lower() in n.lower() for k in keep))


def _try(obj, name):
    try:
        v = getattr(obj, name)
        return v() if callable(v) else v
    except Exception as e:                      # noqa: BLE001
        return f"(読めない: {type(e).__name__}: {e})"


def probe(ol, rfdc):
    try:
        import xrfclk
        log("=== xrfclk ===")
        log(f"  {[n for n in dir(xrfclk) if not n.startswith('_')]}")
        log("")
    except Exception as e:                      # noqa: BLE001
        log(f"xrfclk が import できない: {e}")

    log("=== ip_dict ===")
    for k in sorted(ol.ip_dict):
        log(f"  {k}")

    log("")
    log("=== オーバーレイの属性 ===")
    for name in ("rfdc", "dma_adc", "gpio_capture"):
        log(f"  ol.{name}: {type(getattr(ol, name, None))}")

    log("")
    log("=== RFdc オブジェクト ===")
    log(f"  type = {type(rfdc)}")
    log(f"  API  = {_api(rfdc, ['tile', 'mts', 'reset', 'startup', 'clk'])}")

    log("")
    log("=== ADC タイル ===")
    try:
        tiles = rfdc.adc_tiles
    except Exception as e:                      # noqa: BLE001
        log(f"  adc_tiles が読めない: {e}")
        return
    log(f"  タイル数 = {len(tiles)}")
    for ti, tile in enumerate(tiles):
        log(f"  --- adc_tiles[{ti}]  (= Tile {224 + ti}) ---")
        if ti == TILE:
            log("    API = " + str(_api(tile, ["pll", "startup", "fifo", "block",
                                               "reset", "shutdown", "clock", "status"])))
        for attr in ("PLLLockStatus", "ClockSource"):
            log(f"    {attr} = {_try(tile, attr)}")
        try:
            blocks = tile.blocks
            log(f"    blocks の数 = {len(blocks)}")
            for bi, b in enumerate(blocks):
                mark = "   ← 使う予定" if (ti == TILE and bi == BLOCK) else ""
                log(f"      blocks[{bi}] BlockStatus = {_try(b, 'BlockStatus')}{mark}")
                if ti == TILE and bi == BLOCK:
                    log("      blocks[%d] API = %s" % (bi, _api(
                        b, ["mixer", "nyquist", "intr", "status", "nco", "cal"])))
        except Exception as e:                  # noqa: BLE001
            log(f"    blocks が読めない: {e}")

    log("")
    log("**確かめること**")
    log("  1. adc_tiles[2] の blocks が 0/2 で並ぶのか 0/1 に詰まるのか")
    log("     （Vivado 側では ADC_A = Tile 226 slice 0 / ADC_B = slice 2 で確定）")
    log("  2. PLLLockStatus / SetupFIFO / StartUp / DynamicPLLConfig が API 一覧にあるか")
    log("  3. ADC_A に信号を入れて取得し、どの blocks[] に乗るかで最終確認する")


# ------------------------------------------------------------------- 取得
def capture(ol, n_samples, block=None):
    """ゲートを arm して n_samples 取る。DMA を先に張ってから arm する。"""
    from pynq import allocate

    if n_samples % SPW:
        raise ValueError(f"サンプル数は {SPW} の倍数にすること: {n_samples}")
    n_beats = n_samples // SPW
    if n_beats >= 1 << 24:
        raise ValueError(f"ビート数が 24bit に収まらない: {n_beats}")

    gpio = ol.gpio_capture
    dma = ol.dma_adc
    try:
        gpio.channel1.setdirection("out")
        gpio.channel2.setdirection("in")
    except Exception:                           # noqa: BLE001
        pass
    if block is not None:
        log(f"取得前  IsFIFOFlagsAsserted = {fifo_flags(block)}")

    buf = allocate(shape=(n_samples,), dtype=np.int16)

    gpio.channel1.write(n_beats, 0xFFFFFFFF)            # arm は 0 のまま
    st = gpio.channel2.read()
    if st & STATUS_BUSY:
        log(f"WARNING: ゲートが busy のまま始まる (status=0x{st:08x})")

    # **順序が重要。** 先に DMA を張り、それから arm する。
    # 逆にするとゲートが先に流し始め、DMA が受ける前に FIFO が溢れて
    # 記録の先頭が欠ける。
    dma.recvchannel.transfer(buf)
    gpio.channel1.write(n_beats | CTRL_ARM, 0xFFFFFFFF)

    t0 = time.time()
    try:
        dma.recvchannel.wait()
    except Exception as e:                      # noqa: BLE001
        st = gpio.channel2.read()
        log(f"ERROR: DMA が完了しなかった: {e}")
        log(f"  gate status = 0x{st:08x} "
            f"(busy={bool(st & STATUS_BUSY)}, done={bool(st & STATUS_DONE)})")
        log("  done=0 かつ busy=0 なら、ゲートが一度も起動していない → GPIO の配線か arm のビット")
        log("  busy=1 のままなら、RFDC から tvalid が出ていない → タイルの起動と clk_adc")
        raise
    dt = time.time() - t0

    gpio.channel1.write(n_beats, 0xFFFFFFFF)            # arm を落とす
    st = gpio.channel2.read()
    log(f"取得 {n_samples} サンプル / {dt * 1e3:.1f} ms / gate status = 0x{st:08x}")
    if not st & STATUS_DONE:
        log("WARNING: ゲートの done が立っていない。記録が途中で切れている可能性がある")

    if block is not None:
        f = fifo_flags(block)
        log(f"取得後  IsFIFOFlagsAsserted = {f}")
        if f:
            log("  **RFDC がサンプルを落としている。記録が不連続。**")
            log("  下流が詰まっている（FIFO / DMA / HP ポートの帯域）")

    out = np.array(buf)
    buf.freebuffer()
    return out


def analyse(x, fs_hz, tone_hz, window):
    n = len(x)
    rbw = fs_hz / n
    amax = int(np.max(np.abs(x)))
    log("")
    log(f"サンプル数      : {n}  ({n / fs_hz * 1e6:.2f} us)")
    log(f"分解能 fs/N     : {rbw / 1e3:.3f} kHz")
    log(f"max|x|          : {amax}")
    # **ビット寄せは値の刻みで確定する。** 14bit を 16bit の上位に寄せていれば
    # 下位 2bit は常に 0 になり、全サンプルが 4 の倍数になる。
    nz = np.abs(x[x != 0])
    step = int(np.gcd.reduce(nz)) if len(nz) else 0
    full_scale = 32768.0
    if step >= 4:
        log(f"値の刻み        : {step}  → 14bit を 16bit の **上位に寄せている**"
            f"（下位 {int(np.log2(step))} bit は常に 0）")
    elif step == 1:
        log("値の刻み        : 1  → 16bit をそのまま使っている（LSB 揃え）")
        full_scale = 8192.0 if amax <= 8192 else 32768.0
    else:
        log(f"値の刻み        : {step}")
    log(f"平均            : {np.mean(x):.2f}   標準偏差: {np.std(x):.2f}")
    if amax == 0:
        log("ERROR: 全サンプルが 0。タイル / ブロックの取り違えか、タイルが起動していない")
        return
    if np.std(x) == 0:
        log("ERROR: 値が一定。ストリームが止まっている")
        return

    xf = x.astype(np.float64)
    if window == "hann":
        w = np.hanning(n)
    elif window == "none":
        w = np.ones(n)
    else:
        raise ValueError(window)
    cg = np.sum(w) / n                       # コヒーレントゲイン

    spec = np.fft.rfft(xf * w) / (n / 2 * cg)
    mag = np.abs(spec)
    freqs = np.fft.rfftfreq(n, 1 / fs_hz)

    k = int(np.argmax(mag[1:]) + 1)
    peak_dbfs = 20 * np.log10(max(mag[k], 1e-12) / full_scale)

    # ---- サブビンの周波数推定 ----
    # 信号発生器とボードのクロックは独立なので、ピークはビン中心に乗らない。
    # **そのずれは両者の周波数差そのもの**で、外部基準クロック（proj004）が
    # 効いたかどうかを判定する量になる。Hann 窓の 3 点補間で求める。
    delta = 0.0
    if 0 < k < len(mag) - 1:
        a3, b3, c3 = mag[k - 1], mag[k], mag[k + 1]
        den = a3 + 2 * b3 + c3
        if den > 0:
            delta = 2.0 * (c3 - a3) / den
    f_est = (k + delta) * rbw

    log("")
    log(f"ピーク          : bin {k} = {freqs[k] / 1e6:.6f} MHz / {peak_dbfs:.2f} dBFS")
    log(f"サブビン補間    : bin {k + delta:.4f} = **{f_est / 1e6:.6f} MHz**")

    if tone_hz:
        # 折返しを考慮した期待値
        f_fold = tone_hz % fs_hz
        if f_fold > fs_hz / 2:
            f_fold = fs_hz - f_fold
        zone_in = int(tone_hz // (fs_hz / 2)) + 1
        log(f"期待値          : {f_fold / 1e6:.6f} MHz "
            f"（入力 {tone_hz / 1e6:.6f} MHz / 第 {zone_in} ナイキストゾーン）")

        # **ビン番号の一致では判定しない。** SG とボードのクロックは独立なので、
        # 高い周波数では ppm 級のずれが 1 ビットを超える（800 MHz で 15 ppm は
        # 12 kHz = 0.64 ビン）。サブビン推定値との差を ppm で見る。
        sign = -1.0 if (tone_hz % fs_hz) > fs_hz / 2 else 1.0
        d_hz = sign * (f_est - f_fold)
        ppm = d_hz / tone_hz * 1e6
        log(f"  ずれ          : {d_hz:+.1f} Hz  = **{ppm:+.2f} ppm**")
        if abs(ppm) < 100:
            log(f"  → 一致。fs = {fs_hz / 1e6:.3f} MSPS が裏付けられた"
                f"{'（折返しも確認）' if zone_in > 1 else ''}")
            log("    このずれは SG とボードのクロックの周波数差。")
            log("    **proj004（外部 10 MHz 基準）で減るべき量。**")
        else:
            log("  → **100 ppm を超えている。fs の思い込みか、ゾーンの読み違い**")
            log(f"    実測 fs ≈ {f_fold * n / (k + delta) / 1e6:.3f} MSPS")

    # ピーク近傍を除いたノイズフロア
    mask = np.ones(len(mag), dtype=bool)
    mask[max(0, k - 8):k + 9] = False
    mask[0] = False
    floor = 20 * np.log10(max(np.median(mag[mask]), 1e-12) / full_scale)
    log(f"ノイズフロア    : {floor:.2f} dBFS (中央値) / ピークとの差 {peak_dbfs - floor:.1f} dB")

    # ---- 高調波 ----
    # **dBc が入力レベルに追従するかどうかで、歪みの出どころが分かる。**
    # 入力を 10 dB 下げて dBc が 20 dB 下がれば ADC の圧縮。変わらなければ
    # 入力波形そのものの歪み。奇数次だけが 1/n で並べば方形波。
    log("")
    log("高調波（基本波に対する dBc）:")
    log("  n   bin        周波数       実測      方形波なら   ゾーン")
    for h in range(2, 10):
        f_h = f_est * h
        zone_h = int(f_h // (fs_hz / 2)) + 1
        fh = f_h % fs_hz
        if fh > fs_hz / 2:
            fh = fs_hz - fh
        kh = int(round(fh / rbw))
        if not 0 < kh < len(mag) - 1:
            continue
        lo = max(1, kh - 2)
        kh = int(np.argmax(mag[lo:kh + 3]) + lo)
        dbc = 20 * np.log10(max(mag[kh], 1e-12) / max(mag[k], 1e-12))
        sq = f"{20 * np.log10(1.0 / h):8.2f}" if h % 2 else "       —"
        log(f"  H{h}  {kh:>6}  {freqs[kh] / 1e6:>11.5f} MHz  {dbc:>8.2f}  {sq}"
            f"     {zone_h}{'  ← 折返し' if zone_h > 1 else ''}")
    log("  奇数次が「方形波なら」の値に一致していれば、歪みは ADC ではなく")
    log("  入力波形そのもの（方形波）。ADC は正しく再現している。")

    log("")
    log("上位 5 本:")
    for kk in np.argsort(mag[1:])[::-1][:5] + 1:
        d = 20 * np.log10(max(mag[kk], 1e-12) / full_scale)
        log(f"  bin {kk:>6}  {freqs[kk] / 1e6:>12.6f} MHz  {d:>8.2f} dBFS")


# --------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=BITFILE)
    p.add_argument("--nsamples", type=int, default=N_DEFAULT)
    p.add_argument("--tone", type=float, default=None,
                   help="入力した CW の周波数 [MHz]。期待ビンと突き合わせる")
    p.add_argument("--zone", type=int, default=1, choices=(1, 2))
    p.add_argument("--window", default="hann", choices=("hann", "none"))
    p.add_argument("--fs", type=float, default=FS_HZ / 1e6, help="サンプリング周波数 [MSPS]")
    p.add_argument("--save", default=None, help="生サンプルを .npy で保存する")
    p.add_argument("--load", default=None,
                   help="保存した .npy を読んで解析するだけ（ボードを触らない）")
    p.add_argument("--probe", action="store_true", help="構成を出して終わる")
    p.add_argument("--no-clk", action="store_true", help="xrfclk を触らない")
    p.add_argument("--restart", action="store_true",
                   help="タイルを ShutDown → StartUp する（既定は触らない）")
    p.add_argument("--pll-config", action="store_true",
                   help="DynamicPLLConfig でタイル PLL を設定し直す（既定は触らない）")
    args = p.parse_args()

    # 保存したデータの解析だけなら、ボードにも PYNQ にも触らない。
    # **取り直さずに解析を変えられる**ので、窓関数や期待周波数を変えて
    # 何度でも見直せる。
    if args.load:
        x = np.load(args.load)
        log(f"loaded: {args.load}  ({len(x)} サンプル)")
        analyse(x, args.fs * 1e6, args.tone * 1e6 if args.tone else None, args.window)
        return

    from pynq import Overlay

    # **xrfdc は Overlay() より前に import する。**
    # PYNQ のドライバは import した時点で VLNV に登録される仕組みなので、
    # これを忘れると ol.rfdc が素の DefaultIP のままになり adc_tiles が生えない
    # （2026-09-16 に踏んだ）。
    import xrfdc

    if not args.no_clk:
        setup_clocks()

    ol = Overlay(args.bitfile)
    log(f"Overlay: {args.bitfile}")

    rfdc = ol.rfdc
    log("")
    log("=== RFDC のドライバ ===")
    log(f"  ol.rfdc の型   = {type(rfdc)}")
    try:
        log(f"  .hwh の VLNV   = {ol.ip_dict['rfdc']['type']}")
    except Exception as e:                      # noqa: BLE001
        log(f"  .hwh の VLNV が読めない: {e}")
    log(f"  xrfdc の bindto = {getattr(xrfdc.RFdc, 'bindto', '(不明)')}")

    bound = isinstance(rfdc, xrfdc.RFdc)
    if not bound:
        log("")
        log("ERROR: RFDC に xrfdc のドライバが当たっていない（DefaultIP のまま）。")
        log("  1. import xrfdc を Overlay() より前に書いたか")
        log("  2. 上の VLNV と bindto を見比べる。**版が食い違うと当たらない**")
        if not args.probe:
            sys.exit(1)

    if args.probe:
        probe(ol, rfdc)
        return

    fs_hz = args.fs * 1e6
    _, block = start_tile(rfdc, fs_hz, args.zone,
                          restart=args.restart, pll_config=args.pll_config)

    x = capture(ol, args.nsamples, block)

    if args.save:
        np.save(args.save, x)
        log(f"saved: {args.save}")

    analyse(x, fs_hz, args.tone * 1e6 if args.tone else None, args.window)


if __name__ == "__main__":
    main()

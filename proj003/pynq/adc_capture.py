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
    import xrfclk
    log(f"xrfclk.set_ref_clk(lmk_freq={LMK_FREQ}, lmx_freq={LMX_FREQ})")
    xrfclk.set_ref_clk(lmk_freq=LMK_FREQ, lmx_freq=LMX_FREQ)


def start_tile(rfdc, fs_hz, zone):
    """タイルを起動して PLL のロックを確かめる。ロックしなければ止める。"""
    tile = rfdc.adc_tiles[TILE]
    try:
        # source=1 は内蔵 PLL。単位は MHz
        # fs = 1228.8 = VCO 9830.4 / OutDiv 8、refclk 491.52 = VCO / 20
        tile.DynamicPLLConfig(1, LMX_FREQ, fs_hz / 1e6)
    except Exception as e:                      # noqa: BLE001
        log(f"WARNING: DynamicPLLConfig が失敗した: {e}")
        log("  ビットストリームに焼かれた設定のまま続行する")

    tile.SetupFIFO(True)
    tile.StartUp()
    time.sleep(0.1)

    lock = tile.PLLLockStatus
    log(f"PLLLockStatus = {lock}  (2 = locked)")
    if lock != 2:
        log("ERROR: タイル PLL がロックしていない。")
        log("  1. xrfclk.set_ref_clk() を呼んだか")
        log("  2. LMX が 491.52 MHz を出しているか")
        log("  3. build.tcl の VCO 計算（8.5〜13.2 GHz）を外していないか")
        sys.exit(1)

    block = tile.blocks[BLOCK]
    try:
        block.NyquistZone = zone
        log(f"NyquistZone = {block.NyquistZone}")
    except Exception as e:                      # noqa: BLE001
        log(f"WARNING: NyquistZone を設定できない: {e}")
    return tile, block


def probe(ol, rfdc):
    log("--- ip_dict ---")
    for k in sorted(ol.ip_dict):
        log(f"  {k}")
    log("--- ADC タイルとブロック ---")
    for ti, tile in enumerate(rfdc.adc_tiles):
        try:
            en = [bi for bi, b in enumerate(tile.blocks) if _block_enabled(b)]
        except Exception as e:                  # noqa: BLE001
            en = f"(読めない: {e})"
        log(f"  adc_tiles[{ti}]  (= Tile {224 + ti})  有効なブロック: {en}")
    log("")
    log("**ADC_A に信号を入れた状態で取得し、どのブロックに乗るかで裏を取ること。**")
    log("RefMan A6 では ADC_A / ADC_B が Tile 226、ADC_C / ADC_D が Tile 224。")


def _block_enabled(block):
    for attr in ("BlockStatus", "MixerSettings"):
        try:
            getattr(block, attr)
            return True
        except Exception:                       # noqa: BLE001
            continue
    return False


# ------------------------------------------------------------------- 取得
def capture(ol, n_samples):
    """ゲートを arm して n_samples 取る。DMA を先に張ってから arm する。"""
    from pynq import allocate

    if n_samples % SPW:
        raise ValueError(f"サンプル数は {SPW} の倍数にすること: {n_samples}")
    n_beats = n_samples // SPW
    if n_beats >= 1 << 24:
        raise ValueError(f"ビート数が 24bit に収まらない: {n_beats}")

    gpio = ol.gpio_capture
    dma = ol.dma_adc

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

    out = np.array(buf)
    buf.freebuffer()
    return out


def check_overflow(block):
    """RFDC の FIFO オーバーフローを見る。取りこぼしを検出できる唯一の手段。"""
    for attr in ("IntrStatus", "GetIntrStatus", "FIFOStatus"):
        try:
            v = getattr(block, attr)
            v = v() if callable(v) else v
            log(f"RFDC {attr} = {v}")
            return
        except Exception:                       # noqa: BLE001
            continue
    log("NOTE: RFDC の割り込み状態を読む口が見つからなかった（取りこぼしは検出できない）")


# ------------------------------------------------------------------- 解析
def analyse(x, fs_hz, tone_hz, window):
    n = len(x)
    rbw = fs_hz / n
    amax = int(np.max(np.abs(x)))
    log("")
    log(f"サンプル数      : {n}  ({n / fs_hz * 1e6:.2f} us)")
    log(f"分解能 fs/N     : {rbw / 1e3:.3f} kHz")
    log(f"max|x|          : {amax}")
    log(f"  → 14bit を 16bit のどこに寄せているか: "
        f"{'MSB 揃え（±32768 級）' if amax > 8192 else 'LSB 揃え（±8192 級）'}の可能性")
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
    full_scale = 32768.0 if amax > 8192 else 8192.0
    peak_dbfs = 20 * np.log10(max(mag[k], 1e-12) / full_scale)

    log("")
    log(f"ピーク          : bin {k} = {freqs[k] / 1e6:.6f} MHz / {peak_dbfs:.2f} dBFS")

    if tone_hz:
        # 折返しを考慮した期待値
        f_fold = tone_hz % fs_hz
        if f_fold > fs_hz / 2:
            f_fold = fs_hz - f_fold
        k_exp = int(round(f_fold / rbw))
        log(f"期待値          : bin {k_exp} = {k_exp * rbw / 1e6:.6f} MHz "
            f"（入力 {tone_hz / 1e6:.6f} MHz の折返し先）")
        if k == k_exp:
            log("  → 一致。fs = {:.3f} MSPS が裏付けられた".format(fs_hz / 1e6))
        else:
            log(f"  → **ずれ {k - k_exp} bin**。fs の思い込みを疑う。"
                f"実測 fs ≈ {tone_hz / (k * rbw) * fs_hz / 1e6:.3f} MSPS")

    # ピーク近傍を除いたノイズフロア
    mask = np.ones(len(mag), dtype=bool)
    mask[max(0, k - 8):k + 9] = False
    mask[0] = False
    floor = 20 * np.log10(max(np.median(mag[mask]), 1e-12) / full_scale)
    log(f"ノイズフロア    : {floor:.2f} dBFS (中央値) / ピークとの差 {peak_dbfs - floor:.1f} dB")

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
    p.add_argument("--probe", action="store_true", help="構成を出して終わる")
    p.add_argument("--no-clk", action="store_true", help="xrfclk を触らない")
    args = p.parse_args()

    from pynq import Overlay

    if not args.no_clk:
        setup_clocks()

    ol = Overlay(args.bitfile)
    log(f"Overlay: {args.bitfile}")

    rfdc = ol.rfdc
    if args.probe:
        probe(ol, rfdc)
        return

    fs_hz = args.fs * 1e6
    _, block = start_tile(rfdc, fs_hz, args.zone)

    x = capture(ol, args.nsamples)
    check_overflow(block)

    if args.save:
        np.save(args.save, x)
        log(f"saved: {args.save}")

    analyse(x, fs_hz, args.tone * 1e6 if args.tone else None, args.window)


if __name__ == "__main__":
    main()

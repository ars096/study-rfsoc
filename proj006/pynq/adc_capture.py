#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj006 — ADC 4ch の生サンプルを同時に取得して FFT する。

proj005 の測定器を **4ch 同時取得**に広げたもの。解析の中身は proj003 から変えていない。

**4ch は 512 bit の 1 本のストリームに束ねてある**（build.tcl の axis_combiner）。
1 ビートに 4ch ぶんが乗るので、取得の同時性はハードの構造で保証されていて、
ソフト側で揃える余地がない。`capture()` の戻り値は (4, N) の配列。

**取得長は FIFO の深さで頭打ちになる**（1ch あたり 65536 サンプル）。
4ch フルレートは 9.83 GB/s で HP ポートが受けきれないため、
`n_beats <= FIFO 深さ` を守ることで溢れないことを保証する設計にしてある。

使い方（ボード上で sudo が要る）:

    sudo python3 adc_capture.py --probe                        # 何が見えているかだけ出す
    sudo python3 adc_capture.py --clkin 0 --tone 100.0125      # 4ch 全部を解析する
    sudo python3 adc_capture.py --clkin 0 --tone 100.0125 --ch 2   # ch2 だけ
    sudo python3 adc_capture.py --clkin stock --tone 100.0125  # 内部基準（Si5395）
    sudo python3 adc_capture.py --clkin 0     --tone 100.0125  # CLK_IN の SMA（推定）
    sudo python3 adc_capture.py --clkin 1     --tone 100.0125  # 出荷時と同じ CLKin1
    sudo python3 adc_capture.py --tone 800.0 --zone 2          # 第 2 ナイキストゾーン
    sudo python3 adc_capture.py --save cap.npy                 # 生サンプルを残す

**レベルを測るときは `--sg-dbm` と `--atten-db` を必ず付ける。**
経路の減衰量を記録していないと、あとから絶対レベルの帳簿が再構成できなくなる
（proj003 でこれを踏み、proj005 で 54 dB 合わなくなった）。

    sudo python3 adc_capture.py --clkin 0 --tone 100.0125 --sg-dbm 0 --atten-db 10

3 条件を続けて測って表にするなら `extref_test.py`。
SMA のラベルとチャネルの対応を埋めるなら `slice_map.py`。
タイル間のサンプルずれとその再現性を測るなら `tile_offset.py`（proj006 の本測定）。

**`--clkin` は Overlay() より前に効かせる。** クロックを確定させてからビットストリームを
ロードするので、タイルに触る必要がない（proj003 の「動いているタイルには触らない」）。

**--probe は実機で最初に打つコマンド。** タイル・ブロックの番号の付き方と、
14bit サンプルのビット寄せが、ここで初めて確定する。
"""

import argparse
import sys
import time

import numpy as np

FS_HZ = 1228.8e6        # build.tcl の fs_gsps と一致させること
SPW = 8                 # 1ch あたり AXI4-Stream 1 語のサンプル数（build.tcl の spw）
N_DEFAULT = 65536
BITFILE = "proj006.bit"

# **並びは build.tcl の chans と同じ順序でなければならない。**
# axis_combiner の S00 が 512 bit 語の最下位に来るので、ch0 が最初の SPW サンプル。
# **SMA のラベル（ADC_A/B/C/D）はここに書かない。**proj003 で「SMA のラベルと
# スライス番号の並びが逆」を踏んでいる。対応は slice_map.py で実測して埋める。
CHANS = [(0, 0), (0, 2), (2, 0), (2, 2)]     # (tile index, slice)
NCH = len(CHANS)

# build.tcl の fifo_depth。**越えると FIFO が溢れて記録が不連続になる。**
# proj005 までは「MM 側の帯域 > ストリームの帯域」で保証していたが、
# 4ch（9.83 GB/s）ではそれが成り立たないので、取得長そのもので保証している。
MAX_BEATS = 8192

# proj003 で ADC_B と実測した組。probe の注目先の既定値としてだけ使う。
TILE, BLOCK = CHANS[2]

LMK_FREQ = 245.76
LMX_FREQ = 491.52

# ボード内のクロック。無入力で立つスパーの出どころを突き止めるための表。
# **分光計としては固定周波数のバーディーになるので、素性を記録しておく。**
KNOWN_CLOCKS = [
    ("fs（サンプリング）", 1228.8e6),
    ("LMX2594 → RFDC 基準", 491.52e6),
    ("LMK04828 → LMX 基準", 245.76e6),
    ("LMK04828 → PL 基準", 122.88e6),
    ("AXIS (fs/8)", 153.6e6),
    ("clk_adc2 (fs/16)", 76.8e6),
    ("PS pl_clk0", 100.0e6),
    ("PS pl_clk1", 175.0e6),
    ("RF SYSREF", 7.68e6),
    ("Si5395 自走 PL クロック", 100.0e6),
]


def identify(f_hz, fs_hz, tol_hz):
    """周波数が既知のクロック（の高調波・折返し）と一致するかを調べる。"""
    best = None
    for name, f0 in KNOWN_CLOCKS:
        for h in range(1, 9):
            fa = (f0 * h) % fs_hz
            if fa > fs_hz / 2:
                fa = fs_hz - fa
            if fa < tol_hz:
                continue      # 直流に折り返すものは意味がない（fs の整数倍など）
            d = abs(fa - f_hz)
            # 次数の低い説明を優先する。同じ周波数を高調波でも説明できることがある。
            key = (h, d)
            if d <= tol_hz and (best is None or key < best[0]):
                best = (key, f"{name}{' × %d' % h if h > 1 else ''}")
    return best[1] if best else ""


CTRL_ARM = 1 << 31
STATUS_BUSY = 1 << 0
STATUS_DONE = 1 << 1


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------- 起動
def setup_clocks(clkin="stock", ref_mhz=10.0):
    """LMK04828 / LMX2594 を設定する。

    clkin = "stock" なら出荷時のまま（xrfclk の素の呼び出し）。
    0 / 1 / 2 なら `extref.py` で PLL1 の基準入力を選び直す。

    **出荷時の経路はわざと別実装で残してある。** 外部基準の側が動かなかったときに、
    「クロック設定の書き方を変えたせい」なのか「基準そのもの」なのかを切り分けられる
    ようにするため。
    """
    if clkin != "stock":
        import extref
        extref.set_clocks(int(clkin), ref_mhz=ref_mhz)
        return

    import xrfclk
    # 関数名は xrfclk の版で変わる（v3.1.1 は set_ref_clks、旧版は set_ref_clk）。
    fn = None
    for name in ("set_ref_clks", "set_ref_clk"):
        fn = getattr(xrfclk, name, None)
        if fn is not None:
            break
    if fn is None:
        log("ERROR: xrfclk に set_ref_clks / set_ref_clk のどちらも無い")
        log(f"  使える名前: {[n for n in dir(xrfclk) if not n.startswith('_')]}")
        sys.exit(1)
    log(f"xrfclk.{fn.__name__}(lmk_freq={LMK_FREQ}, lmx_freq={LMX_FREQ})"
        "   ← 出荷時のクロック源（基板の Si5395）")
    fn(lmk_freq=LMK_FREQ, lmx_freq=LMX_FREQ)


def start_tile(rfdc, fs_hz, zone, ti=None, si=None, restart=False, pll_config=False):
    """タイルの状態を確かめる。**すでに動いていれば触らない。**

    ビットストリームをロードした時点でタイルは起動し、PLL もロックしている
    （2026-09-16 に確認: PLLLockStatus = 2 / SamplingFreq = 1.2288）。
    そこへ DynamicPLLConfig や StartUp をかけると、動いている状態をわざわざ
    壊しにいくことになる。**既定は検証のみ。** 明示的に指示されたときだけ触る。
    """
    if ti is None:
        ti = TILE
    if si is None:
        si = BLOCK
    tile = rfdc.adc_tiles[ti]
    block = tile.blocks[si]
    log("")
    log(f"--- Tile {224 + ti} / slice {si} ---")

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


def start_tiles(rfdc, fs_hz, zone, restart=False, pll_config=False):
    """CHANS の全チャネルぶん確かめる。

    **どれか 1 つでも起動していなければ axis_combiner は 1 ビートも出さない。**
    データが 1 バイトも来ないという症状になるので、ここで全部見ておく方が
    切り分けが早い。これは axis_combiner の仕様であって、意図した失敗の仕方である。

    restart / pll_config は**タイル単位の操作**なので、同じタイルに 2 回かけない。
    """
    blocks = []
    touched = set()
    for ti, si in CHANS:
        first = ti not in touched
        _, b = start_tile(rfdc, fs_hz, zone, ti, si,
                          restart=(restart and first),
                          pll_config=(pll_config and first))
        touched.add(ti)
        blocks.append(b)
    return blocks


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
    log("  1. Tile 224 と Tile 226 の両方で PLLLockStatus = 2 になっているか")
    log("     （片方でも落ちていれば axis_combiner は 1 ビートも出さない）")
    log("  2. blocks が 0/2 で並ぶのか 0/1 に詰まるのか")
    log("  3. SMA のラベルとチャネルの対応は **slice_map.py で実測して埋める**")
    log("     ここに書いてある CHANS は Vivado 側の並びであって、SMA の並びではない")


# ------------------------------------------------------------------- 取得
def capture(ol, n_samples, blocks=None):
    """ゲートを arm して **1ch あたり** n_samples 取る。DMA を先に張ってから arm する。

    戻り値は **(NCH, n_samples) の配列**。

    1 ビート = 512 bit = NCH x SPW サンプルで、ch0 が最下位に来る。int16 で読むと
    [ch0 の SPW サンプル][ch1 の SPW サンプル]... が n_beats 回くり返す並びになる。
    **この並びは build.tcl の chans の順序に依存している。**片方を変えたら両方直すこと。
    """
    from pynq import allocate

    if n_samples % SPW:
        raise ValueError(f"サンプル数は {SPW} の倍数にすること: {n_samples}")
    n_beats = n_samples // SPW
    if n_beats > MAX_BEATS:
        raise ValueError(
            f"ビート数 {n_beats} が FIFO の深さ {MAX_BEATS} を越える"
            f"（1ch あたり最大 {MAX_BEATS * SPW} サンプル）。"
            " **越えると FIFO が溢れて記録が不連続になる。**"
            " 伸ばすなら build.tcl の fifo_depth と MAX_BEATS を両方上げること")

    gpio = ol.gpio_capture
    dma = ol.dma_adc
    try:
        gpio.channel1.setdirection("out")
        gpio.channel2.setdirection("in")
    except Exception:                           # noqa: BLE001
        pass
    if blocks:
        log("取得前  IsFIFOFlagsAsserted = "
            + " / ".join(f"ch{i}:{fifo_flags(b)}" for i, b in enumerate(blocks)))

    buf = allocate(shape=(n_beats * NCH * SPW,), dtype=np.int16)

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
        log("  **4ch では axis_combiner が全 SI の valid を待つ。**")
        log("  1 タイルでも起動していなければ 1 ビートも出ない。上の Tile ごとの")
        log("  PLLLockStatus / BlockStatus を先に見ること")
        raise
    dt = time.time() - t0

    gpio.channel1.write(n_beats, 0xFFFFFFFF)            # arm を落とす
    st = gpio.channel2.read()
    log(f"取得 {n_samples} サンプル x {NCH} ch / {dt * 1e3:.1f} ms / "
        f"gate status = 0x{st:08x}")
    if not st & STATUS_DONE:
        log("WARNING: ゲートの done が立っていない。記録が途中で切れている可能性がある")

    if blocks:
        fl = [fifo_flags(b) for b in blocks]
        log("取得後  IsFIFOFlagsAsserted = "
            + " / ".join(f"ch{i}:{f}" for i, f in enumerate(fl)))
        if any(f for f in fl if isinstance(f, int) and f):
            log("  **RFDC がサンプルを落としている。記録が不連続。**")
            log("  n_beats が FIFO の深さを越えていないか（MAX_BEATS）を先に見る")

    # [beat][ch][sample] の順に並んでいるので、ch を先頭に持ち替える。
    out = np.array(buf).reshape(n_beats, NCH, SPW).transpose(1, 0, 2).reshape(NCH, -1)
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
    # **そのずれは両者の周波数差そのもの**で、外部基準クロック（proj005）が
    # 効いたかどうかを判定する量になる。Hann 窓の 3 点補間で求める。
    delta = 0.0
    if 0 < k < len(mag) - 1:
        a3, b3, c3 = mag[k - 1], mag[k], mag[k + 1]
        den = a3 + 2 * b3 + c3
        if den > 0:
            delta = 2.0 * (c3 - a3) / den
    f_est = (k + delta) * rbw

    # 呼び出し側（extref_test.py）が条件間で比べるための数値。
    result = {"n": n, "rbw_hz": rbw, "bin": k, "f_est_hz": f_est,
              "peak_dbfs": None, "ppm": None, "d_hz": None,
              "max_abs": amax, "std": float(np.std(x))}

    log("")
    result["peak_dbfs"] = peak_dbfs
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
        result["ppm"] = ppm
        result["d_hz"] = d_hz
        log(f"  ずれ          : {d_hz:+.1f} Hz  = **{ppm:+.2f} ppm**")
        if abs(ppm) < 100:
            log(f"  → 一致。fs = {fs_hz / 1e6:.3f} MSPS が裏付けられた"
                f"{'（折返しも確認）' if zone_in > 1 else ''}")
            log("    このずれは SG とボードのクロックの周波数差。")
            log("    **SG とボードを同じ 10 MHz に繋げば 0 に潰れる。**")
            log("    proj003 の内部基準での実測は +14.92 ppm（48 MHz XO の確度）。")
        else:
            log("  → **100 ppm を超えている。fs の思い込みか、ゾーンの読み違い**")
            log(f"    実測 fs ≈ {f_fold * n / (k + delta) / 1e6:.3f} MSPS")

    # ピーク近傍を除いたノイズフロア
    mask = np.ones(len(mag), dtype=bool)
    mask[max(0, k - 8):k + 9] = False
    mask[0] = False
    floor = 20 * np.log10(max(np.median(mag[mask]), 1e-12) / full_scale)
    log(f"ノイズフロア    : {floor:.2f} dBFS (中央値) / ピークとの差 {peak_dbfs - floor:.1f} dB")

    # ---- 高調波（期待周波数が与えられたときだけ）----
    # **dBc が入力レベルに追従するかどうかで、歪みの出どころが分かる。**
    # 入力を 10 dB 下げて dBc が 20 dB 下がれば ADC の圧縮。変わらなければ
    # 入力波形そのものの歪み。奇数次だけが 1/n で並べば方形波。
    if tone_hz:
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
    log("上位のピーク（既知クロックとの照合つき）:")
    shown = []
    for kk in np.argsort(mag[1:])[::-1] + 1:
        if any(abs(int(kk) - p) < 4 for p in shown):
            continue          # 同じ山の裾は 1 本にまとめる
        shown.append(int(kk))
        d = 20 * np.log10(max(mag[kk], 1e-12) / full_scale)
        who = identify(freqs[kk], fs_hz, 3 * rbw)
        log(f"  bin {kk:>6}  {freqs[kk] / 1e6:>12.6f} MHz  {d:>8.2f} dBFS  {who}")
        if len(shown) >= 8:
            break
    log("  **既知クロックと一致するものは回り込み。** 分光計では固定周波数の")
    log("  バーディーになるので、素性と強さを記録しておく。")

    return result


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
    p.add_argument("--ch", type=int, default=None, choices=tuple(range(NCH)),
                   help="解析するチャネル。省略すると 4ch 全部を解析する")
    p.add_argument("--sg-dbm", type=float, default=None,
                   help="信号発生器の出力設定 [dBm]。**経路の減衰量とあわせて記録するため**")
    p.add_argument("--atten-db", type=float, default=0.0,
                   help="SG と ADC の間の減衰量 [dB]（正の値）。アッテネータ・分配器の損失の合計")
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"),
                   help="LMK04828 の PLL1 基準入力。stock = 出荷時（基板の Si5395）")
    p.add_argument("--ref", type=float, default=10.0,
                   help="外部基準の周波数 [MHz]（--clkin 0/1/2 のとき）")
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
        xs = np.load(args.load)
        if xs.ndim == 1:
            xs = xs[None, :]                     # proj005 以前の 1ch の .npy
        log(f"loaded: {args.load}  shape={xs.shape}")
        for i in range(xs.shape[0]):
            log("")
            log(f"================ ch{i} ================")
            analyse(xs[i], args.fs * 1e6,
                    args.tone * 1e6 if args.tone else None, args.window)
        return

    from pynq import Overlay

    # **xrfdc は Overlay() より前に import する。**
    # PYNQ のドライバは import した時点で VLNV に登録される仕組みなので、
    # これを忘れると ol.rfdc が素の DefaultIP のままになり adc_tiles が生えない
    # （2026-09-16 に踏んだ）。
    import xrfdc

    if not args.no_clk:
        setup_clocks(args.clkin, args.ref)

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
    blocks = start_tiles(rfdc, fs_hz, args.zone,
                         restart=args.restart, pll_config=args.pll_config)

    xs = capture(ol, args.nsamples, blocks)

    if args.save:
        np.save(args.save, xs)
        log(f"saved: {args.save}  shape={xs.shape}")

    # **まず 4ch を 1 つの表にする。**どの ch に信号が乗っているかは、
    # FFT を見るまでもなく max|x| と std で分かる。slice_map.py はこれを自動化したもの。
    log("")
    log("=== チャネルの要約 ===")
    log("  ch  tile/slice    max|x|       std")
    for i, (ti, si) in enumerate(CHANS):
        log(f"  {i}   {224 + ti}/{si}       "
            f"{int(np.max(np.abs(xs[i]))):>7}  {np.std(xs[i]):>9.1f}")

    main_ch = 0 if args.ch is None else args.ch
    targets = range(NCH) if args.ch is None else [args.ch]
    r = None
    for i in targets:
        ti, si = CHANS[i]
        log("")
        log(f"================ ch{i}  (Tile {224 + ti} / slice {si}) ================")
        ri = analyse(xs[i], fs_hz, args.tone * 1e6 if args.tone else None, args.window)
        if i == main_ch:
            r = ri

    # **1 行にまとめて出す。** 条件を変えて何度も走らせるので、端末を遡らずに
    # 比べられるようにしておく。
    # **経路の減衰量を記録する。** proj003 では減衰器の値がどこにも残っておらず、
    # proj005 で正弦波源と突き合わせたときに絶対レベルの帳簿が 54 dB 合わなかった
    # （2026-09-17 に判明）。相対変化しか信用できない記録になる。
    if r and r.get("peak_dbfs") is not None and args.sg_dbm is not None:
        adc_in = args.sg_dbm - args.atten_db
        fs_dbm = adc_in - r["peak_dbfs"]
        log("")
        log(f"レベルの帳簿    : SG {args.sg_dbm:+.2f} dBm − 減衰 {args.atten_db:.1f} dB "
            f"= **ADC 入力 {adc_in:+.2f} dBm**")
        log(f"  0 dBFS 換算   : **{fs_dbm:+.2f} dBm**（ピーク {r['peak_dbfs']:.2f} dBFS から逆算）")
        log("  実測の基準値は VERSIONS.md を見る。大きく食い違うなら経路の申告が違う")

    if r and r.get("ppm") is not None:
        lvl = ""
        if args.sg_dbm is not None:
            lvl = (f"  sg={args.sg_dbm:+.1f}dBm  atten={args.atten_db:.1f}dB"
                   f"  adc_in={args.sg_dbm - args.atten_db:+.1f}dBm")
        log("")
        log(f"RESULT  ch={main_ch}  clkin={args.clkin}  tone={args.tone} MHz  "
            f"f_est={r['f_est_hz'] / 1e6:.6f} MHz  "
            f"ppm={r['ppm']:+.3f}  peak={r['peak_dbfs']:.2f} dBFS{lvl}")


if __name__ == "__main__":
    main()

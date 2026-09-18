#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj009 — fs 4096 MSPS・第 2 ナイキストで ADC の生サンプルを取って FFT する。

proj006 の測定器を **fs 4096 MSPS / まず 1ch（ADC_B）** にしたもの。
RFDC は 1 語 12 サンプル（341.33 MHz）で出し、PL の入口のギアボックスで **1 語 16 サンプル
（256 MHz）** に詰め替えてから取得する。**ここで見る SPW は詰め替えた後の 16。**
解析の骨格は proj003 から変えていない。proj009 で足したのは 3 つ:

  1. **ナイキストゾーンの既定を 2 にし、設定後に読み返す。**違えば止める
  2. **16 並列の並び順の検査**（`lane_check`）。並びを誤ると k·fs/16 ± f にイメージが立つ。
     それらしいスペクトルは出てしまうので、トーンの純度で判定する（判定 4）
  3. 既知クロックの表を 4096 MSPS 用に差し替えた

**ゾーン 2 はスペクトルが反転する。**入力 f は 4096 − f に見える（2.2 GHz → 1896 MHz）。
analyse() の期待値はこれを計算して突き合わせる。

**取得長は FIFO の深さで頭打ちになる**（1ch で最大 131072 サンプル = 32 us）。
1ch で 8.192 GB/s は HP ポートが受けきれないので、`n_beats <= FIFO 深さ` で溢れないことを保証する。

使い方（ボード上で sudo が要る）:

    sudo python3 adc_capture.py --probe                                  # 何が見えているかだけ出す
    sudo python3 adc_capture.py --clkin 0 --tone 3000.0625               # 判定 2（ゾーン 2）
    sudo python3 adc_capture.py --clkin 0 --tone 3000.0625 --sg-dbm 0 --atten-db 10
    sudo python3 adc_capture.py --clkin 0 --tone 1000.0625 --zone 1      # 対照（ゾーン 1）
    sudo python3 adc_capture.py --save cap.npy                           # 生サンプルを残す
    python3 adc_capture.py --load cap.npy --tone 3000.0625               # 取り直さずに解析し直す

**トーンを 62.5 kHz の倍数に置くとビン中心に立つ**（3000.0625 MHz = 48001 × 62.5 kHz）。
SG とボードが同じ 10 MHz を共有していれば、サブビン補間のずれは 0 になるのが正しい。

**レベルを測るときは `--sg-dbm` と `--atten-db` を必ず付ける。**
経路の減衰量を記録していないと、あとから絶対レベルの帳簿が再構成できなくなる（proj003 → proj005）。

**`--clkin` は Overlay() より前に効かせる。** クロックを確定させてからビットストリームを
ロードするので、タイルに触る必要がない（proj003 の「動いているタイルには触らない」）。
"""

import argparse
import sys
import time

import numpy as np

FS_HZ = 4096.0e6        # build.tcl の fs_gsps と一致させること
SPW = 16                # 1ch あたり AXI4-Stream 1 語のサンプル数（build.tcl の spw）
N_DEFAULT = 65536       # 16 us。分解能 4096 MHz / 65536 = 62.5 kHz ちょうど
BITFILE = "proj009.bit"

# **並びは build.tcl の chans と同じ順序でなければならない。**
# nch > 1 なら axis_combiner の S00 が語の最下位に来るので、ch0 が最初の SPW サンプル。
# SMA との対応は VERSIONS.md（proj006 で実測）: (2, 0) = Tile 226 / slice 0 = **ADC_B**。
# 4ch に戻すときは [(0, 0), (0, 2), (2, 0), (2, 2)]（build.tcl の chans と同じ順）。
CHANS_BY_NCH = {
    1: [(2, 0)],                                 # proj009.bit     : ADC_B のみ
    4: [(0, 0), (0, 2), (2, 0), (2, 2)],         # proj009_4ch.bit : ch0..3 = ADC_D, C, B, A
}
SMA = {(2, 0): "ADC_B", (2, 2): "ADC_A", (0, 0): "ADC_D", (0, 2): "ADC_C"}   # VERSIONS.md（proj006 で実測）
CHANS = CHANS_BY_NCH[1]                          # (tile index, slice)。set_layout() が書き換える
NCH = len(CHANS)

# build.tcl の fifo_depth。**越えると FIFO が溢れて記録が不連続になる。**
# 1ch でも 8.192 GB/s で HP ポート（128 bit）を越えるので、取得長そのもので保証する。
MAX_BEATS = 8192

# probe の注目先の既定値としてだけ使う。
TILE, SLICE = CHANS[0]


def set_layout(ol, nch_override=None):
    """**チャネル数をビットストリームから読む。**

    1ch 版（proj009.bit）と 4ch 版（proj009_4ch.bit）で語の並びが違う。ソフト側の定数で
    持つと、ビットストリームを取り違えたときに**それらしいが間違った ch 分けの波形**が出る。
    DMA の語幅（.hwh）÷（SPW × 16 bit）がチャネル数そのものなので、そこから決める。
    """
    global CHANS, NCH, TILE, SLICE, BLOCK
    nch = None
    try:
        prm = ol.ip_dict["dma_adc"]["parameters"]
        for k in ("C_S_AXIS_S2MM_TDATA_WIDTH", "c_s_axis_s2mm_tdata_width"):
            if k in prm:
                nch = int(prm[k]) // (SPW * 16)
                break
    except Exception as e:                      # noqa: BLE001
        log(f"WARNING: .hwh から DMA の語幅が読めない: {e}")
    if nch_override is not None:
        if nch is not None and nch != nch_override:
            log(f"ERROR: --nch {nch_override} だが、ビットストリームは {nch} ch（DMA の語幅から）")
            sys.exit(1)
        nch = nch_override
    if nch not in CHANS_BY_NCH:
        log(f"ERROR: チャネル数が決まらない（{nch}）。--nch 1 か 4 を指定すること")
        sys.exit(1)
    CHANS = CHANS_BY_NCH[nch]
    NCH = len(CHANS)
    TILE, SLICE = CHANS[2] if NCH == 4 else CHANS[0]     # probe の注目先は ADC_B
    BLOCK = block_index(SLICE)
    log(f"チャネル構成 : {NCH} ch（" + " / ".join(
        f"ch{i}={SMA[c]}" for i, c in enumerate(CHANS)) + "）")


def block_index(slice_no):
    """**Vivado のスライス番号 → PYNQ の `blocks[]` の添字。**

    この 2 つは一致しない。

    - Vivado（`build.tcl`）は **物理スライス番号**で呼ぶ。デュアルタイルでは 0 と 2
    - `xrfdc` の `blocks[]` は **有効なものを 0 から詰めて**並べる。つまり 0 と 1

    **2026-09-17 に実機で確定した**（`--probe`）。
    `blocks[2]` / `blocks[3]` は `ADC 2 block 2 not available in XRFdc_GetBlockStatus`
    で落ちる。proj003 から「0/2 で並ぶのか 0/1 に詰まるのか」を持ち越していた宿題の答え。

    proj005 までは slice 0 しか使っていなかったので 0 → 0 で一致し、**問題が表に出なかった。**
    4ch にした途端に効いてくる種類の食い違いである。
    """
    return slice_no // 2


BLOCK = block_index(SLICE)

LMK_FREQ = 245.76
LMX_FREQ = 491.52

# ボード内のクロック。無入力で立つスパーの出どころを突き止めるための表。
# **分光計としては固定周波数のバーディーになるので、素性を記録しておく。**
KNOWN_CLOCKS = [
    ("fs（サンプリング）", 4096.0e6),
    ("タイル PLL の VCO", 12288.0e6),
    ("LMX2594 → RFDC 基準", 491.52e6),
    ("LMK04828 → LMX 基準", 245.76e6),
    ("LMK04828 → PL 基準", 122.88e6),
    ("DSP ドメイン / clk_adc2 (fs/16)", 256.0e6),
    ("ADC ドメイン (fs/12)", 4096.0e6 / 12),
    ("MMCM の VCO", 1024.0e6),
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


QUIET = False     # --repeat の途中は analyse() の詳細を出さない


def log(*a):
    if not QUIET:
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


def start_tile(rfdc, fs_hz, zone, ti=None, si=None, restart=False, pll_config=False,
               cal_mode=None):
    """タイルの状態を確かめる。**すでに動いていれば触らない。**

    ビットストリームをロードした時点でタイルは起動し、PLL もロックしている
    （2026-09-16 に確認: PLLLockStatus = 2 / SamplingFreq = 1.2288）。
    そこへ DynamicPLLConfig や StartUp をかけると、動いている状態をわざわざ
    壊しにいくことになる。**既定は検証のみ。** 明示的に指示されたときだけ触る。
    """
    if ti is None:
        ti = TILE
    if si is None:
        si = SLICE
    bi = block_index(si)                 # **スライス番号をそのまま渡さない**
    tile = rfdc.adc_tiles[ti]
    block = tile.blocks[bi]
    log("")
    log(f"--- Tile {224 + ti} / slice {si} （PYNQ では blocks[{bi}]）---")

    # ここで一度触って、添字が合っているかを確かめる。
    # **合っていないと "block N not available" で落ちる。**
    try:
        _ = block.BlockStatus
    except Exception as e:                       # noqa: BLE001
        log(f"ERROR: adc_tiles[{ti}].blocks[{bi}] が読めない: {e}")
        log("  Vivado のスライス番号（0/2）と PYNQ の blocks[] の添字（0/1）は**別物**。")
        log("  block_index() の変換と、build.tcl の chans を突き合わせること")
        sys.exit(1)

    if pll_config:
        # fs = 4096.0 = VCO 12288.0 / M 3、refclk 491.52 = VCO / 25
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

    # **ゾーンは設定して読み返す。違えば止める。**
    # ゾーンを取り違えても FFT はそれらしいスペクトルを返す（周波数軸が裏返るだけ）。
    # ゾーン 2 用の較正が当たらないと、レベルもゾーン 1 のつもりで読むことになる。
    try:
        block.NyquistZone = zone
        got_zone = block.NyquistZone
    except Exception as e:                      # noqa: BLE001
        log(f"ERROR: NyquistZone を設定・読み出しできない: {e}")
        sys.exit(1)
    log(f"NyquistZone = {got_zone}（要求 {zone}）")
    if got_zone != zone:
        log(f"ERROR: NyquistZone が {got_zone} のまま。要求 {zone} が効いていない")
        sys.exit(1)

    # **較正モードは毎回表示する。**PG269: Mode 1 は観測周波数（折り返し後）が
    # 0.4 fs〜fs/2、Mode 2 は 0〜0.4 fs に最適化されている。
    # IF 2.1〜4.0 GHz は折り返すと 96〜1996 MHz = 0.02〜0.49 fs で、**両方にまたがる。**
    # インタリーブのイメージ（f ± m·fs/8）の強さはこれで変わりうる（proj009 で調査中）。
    if cal_mode is not None:
        try:
            block.CalibrationMode = cal_mode
        except Exception as e:                  # noqa: BLE001
            log(f"ERROR: CalibrationMode を設定できない: {e}")
            sys.exit(1)
    log(f"CalibrationMode = {_try(block, 'CalibrationMode')}"
        f"{'' if cal_mode is None else f'（要求 {cal_mode}）'} / CalFreeze = {_try(block, 'CalFreeze')}")
    return tile, block


def start_tiles(rfdc, fs_hz, zone, restart=False, pll_config=False, cal_mode=None):
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
                          pll_config=(pll_config and first),
                          cal_mode=cal_mode)
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
    log("  1. 使うタイルで PLLLockStatus = 2、SamplingFreq = 4.096 になっているか")
    log("     （タイル PLL の M = 3 は proj009 で初めて使う設定）")
    log("  2. blocks は **0/1 に詰まる**（2026-09-17 に確定）。")
    log("     Vivado のスライス番号 0/2 とは別物。block_index() が変換する。")
    log("     blocks[2] / blocks[3] が not available なら、それが正常")
    log("  3. SMA のラベルとチャネルの対応は VERSIONS.md が正（proj006 で実測済み）")


# ------------------------------------------------------------------- 取得
def capture(ol, n_samples, blocks=None):
    """ゲートを arm して **1ch あたり** n_samples 取る。DMA を先に張ってから arm する。

    戻り値は **(NCH, n_samples) の配列**。

    1 ビート = NCH x SPW x 16 bit（1ch・SPW 16 で 256 bit）で、ch0 が最下位に来る。int16 で読むと
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
        log("  **複数 ch では axis_combiner が全 SI の valid を待つ。**")
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


def lane_check(mag, freqs, k, fs_hz, rbw, spw=SPW):
    """**16 並列の並び順の検査**（proj009 の判定 4）。

    1 語の中でサンプルの順序を取り違えると、信号に周期 spw の変調がかかり、
    **f ± m·fs/spw（m = 1..spw−1）にイメージ**が立つ。取り違えの程度によっては
    トーンと同じ桁になる。それでもピークは正しい位置に立つので、ピークだけ見ていると気づけない。

    **奇数の m（fs/16 の奇数倍）に −20 dBc 級で立てば並び順の誤り。**偶数の m は
    ADC 自身の 8 並列インタリーブ（副 ADC の不整合）で立つので、別の列に出す。
    実機（2026-09-18）では偶数 m が −55〜−65 dBc、奇数 m は −63〜−69 dBc
    （奇数 m にも他のスプリアスが偶然重なるので、0 にはならない）。
    戻り値は (奇数 m の最悪 dBc, 偶数 m の最悪 dBc)。
    """
    f0 = freqs[k]
    worst = {1: -999.0, 0: -999.0}
    rows = []
    for m in range(1, spw):
        for sgn in (+1, -1):
            f = (f0 + sgn * m * fs_hz / spw) % fs_hz
            if f > fs_hz / 2:
                f = fs_hz - f
            kk = int(round(f / rbw))
            if not 2 < kk < len(mag) - 3 or abs(kk - k) < 4:
                continue
            lo = kk - 2
            kk = int(np.argmax(mag[lo:kk + 3]) + lo)
            dbc = 20 * np.log10(max(mag[kk], 1e-12) / max(mag[k], 1e-12))
            rows.append((m, sgn, kk, dbc))
            worst[m % 2] = max(worst[m % 2], dbc)
    log("")
    log(f"並び順の検査（f ± m·fs/{spw} のイメージ。**並び順の誤りは奇数 m に −20 dBc 級で立つ**。"
        "偶数 m は ADC の 8 並列インタリーブ）:")
    for m, sgn, kk, dbc in sorted(rows, key=lambda r: -r[3])[:6]:
        log(f"  m={m:>2}{'+' if sgn > 0 else '-'}  bin {kk:>6}  {freqs[kk] / 1e6:>11.5f} MHz  {dbc:>8.2f} dBc"
            f"{'' if m % 2 == 0 else '   ← 奇数'}")
    log(f"  最悪: 奇数 m {worst[1]:.1f} dBc / 偶数 m {worst[0]:.1f} dBc")
    if worst[1] > -40.0:
        log("  **ERROR 相当: 奇数 m のイメージが −40 dBc を越えている。並び順を疑う**")
    else:
        log("  → 並び順の誤りの兆候なし（奇数 m が −40 dBc 未満）")
    return worst[1], worst[0]


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

    if tone_hz:
        odd, even = lane_check(mag, freqs, k, fs_hz, rbw)
        result["lane_odd_dbc"] = odd
        result["lane_even_dbc"] = even

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
    p.add_argument("--zone", type=int, default=2, choices=(1, 2),
                   help="ナイキストゾーン。IF 2〜4 GHz は 2（既定）。**設定後に読み返して違えば止める**")
    p.add_argument("--window", default="hann", choices=("hann", "none"))
    p.add_argument("--fs", type=float, default=FS_HZ / 1e6, help="サンプリング周波数 [MSPS]")
    p.add_argument("--save", default=None, help="生サンプルを .npy で保存する")
    p.add_argument("--load", default=None,
                   help="保存した .npy を読んで解析するだけ（ボードを触らない）")
    p.add_argument("--probe", action="store_true", help="構成を出して終わる")
    p.add_argument("--ch", type=int, default=None, choices=(0, 1, 2, 3),
                   help="解析するチャネル。省略すると全チャネルを解析する"
                        "（4ch 版の並び: ch0=ADC_D / ch1=ADC_C / ch2=ADC_B / ch3=ADC_A）")
    p.add_argument("--nch", type=int, default=None, choices=(1, 4),
                   help="チャネル数。省略するとビットストリーム（DMA の語幅）から読む")
    p.add_argument("--sg-dbm", type=float, default=None,
                   help="信号発生器の出力設定 [dBm]。**経路の減衰量とあわせて記録するため**")
    p.add_argument("--cal-mode", type=int, default=None, choices=(1, 2),
                   help="RF-ADC の較正モード。省略すると触らない（現在値は必ず表示する）")
    p.add_argument("--repeat", type=int, default=1,
                   help="同じ条件で N 回取り、1 行ずつ出す（較正の収束・再現性を見る）")
    p.add_argument("--interval", type=float, default=5.0, help="--repeat の間隔 [s]")
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

    # **減衰量は正の値で書く。**2026-09-18 に -10 と書いて ADC 入力を 20 dB 高く
    # 見積もった（SG -10 dBm − (−10 dB) = 0 dBm）。黙って通すと帳簿が狂う。
    if args.atten_db < 0:
        log(f"ERROR: --atten-db {args.atten_db} は負。減衰量は正の値で書くこと"
            f"（10 dB の減衰なら --atten-db 10）")
        sys.exit(2)

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

    set_layout(ol, args.nch)
    if args.ch is not None and args.ch >= NCH:
        log(f"ERROR: --ch {args.ch} はこのビットストリーム（{NCH} ch）に無い")
        sys.exit(2)

    if args.probe:
        probe(ol, rfdc)
        return

    fs_hz = args.fs * 1e6
    blocks = start_tiles(rfdc, fs_hz, args.zone,
                         restart=args.restart, pll_config=args.pll_config,
                         cal_mode=args.cal_mode)

    # ---- 繰り返し（1 行ずつ）----
    # **較正が収束していくか、条件を変えたときに何が動くかを並べて見るため。**
    # 最後の 1 回だけを下で詳しく解析する。
    if args.repeat > 1:
        global QUIET
        log("")
        log(f"=== {args.repeat} 回くり返す（間隔 {args.interval} s）===")
        print("   #   経過[s]  peak[dBFS]  奇数m[dBc]  偶数m[dBc]    ppm      FIFO", flush=True)
        t_start = time.time()
        for k in range(args.repeat):
            if k:
                time.sleep(args.interval)
            QUIET = True
            try:
                xs = capture(ol, args.nsamples, blocks)
                sel = args.ch if args.ch is not None else int(np.argmax([np.std(c) for c in xs]))
                rr = analyse(xs[sel], fs_hz,
                             args.tone * 1e6 if args.tone else None, args.window) or {}
            finally:
                QUIET = False
            fl = fifo_flags(blocks[0])
            print(f"  {k:>2}  {time.time() - t_start:>7.1f}  {rr.get('peak_dbfs', float('nan')):>10.2f}"
                  f"  {rr.get('lane_odd_dbc', float('nan')):>10.1f}  {rr.get('lane_even_dbc', float('nan')):>10.1f}"
                  f"  {rr.get('ppm') if rr.get('ppm') is not None else float('nan'):>+7.3f}  {fl}", flush=True)
    else:
        xs = capture(ol, args.nsamples, blocks)

    if args.save:
        np.save(args.save, xs)
        log(f"saved: {args.save}  shape={xs.shape}")

    # **まずチャネルを 1 つの表にする。**どの ch に信号が乗っているかは、
    # FFT を見るまでもなく max|x| と std で分かる。
    log("")
    log("=== チャネルの要約 ===")
    log("  ch  SMA    tile/slice    max|x|       std")
    for i, (ti, si) in enumerate(CHANS):
        log(f"  {i}   {SMA[(ti, si)]}  {224 + ti}/{si}       "
            f"{int(np.max(np.abs(xs[i]))):>7}  {np.std(xs[i]):>9.1f}")

    # 省略時は**信号が一番大きい ch** を RESULT 行の主役にする（トーンを入れた SMA）
    main_ch = int(np.argmax([np.std(c) for c in xs])) if args.ch is None else args.ch
    targets = range(NCH) if args.ch is None else [args.ch]
    r = None
    for i in targets:
        ti, si = CHANS[i]
        log("")
        log(f"================ ch{i} = {SMA[(ti, si)]}  (Tile {224 + ti} / slice {si}) ================")
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
        log(f"RESULT  ch={main_ch}({SMA[CHANS[main_ch]]})  clkin={args.clkin}  tone={args.tone} MHz  "
            f"f_est={r['f_est_hz'] / 1e6:.6f} MHz  "
            f"ppm={r['ppm']:+.3f}  peak={r['peak_dbfs']:.2f} dBFS  "
            f"lane_odd={r.get('lane_odd_dbc', float('nan')):.1f}dBc  "
            f"lane_even={r.get('lane_even_dbc', float('nan')):.1f}dBc  "
            f"cal_mode={_try(blocks[0], 'CalibrationMode')}{lvl}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj007 — 1PPS の受信確認と、ビートカウンタの読み出し。

PL 側（`src/pps_capture.v`）は 153.6 MHz のビートカウンタを自走させ、
PPS のエッジでその値をラッチしている。**1 秒 = 153,600,000 ビートちょうど**
（fs = 1,228,800,000 が整数だから成立する）。

このスクリプトでできること:

    # まず配線と極性を確かめる（GPIO の識別子・alive・グリッチ）
    sudo -E $(which python3) pps.py --probe --clkin 0

    # 残差を積んで周波数確度を測る。**proj004 の CW 法より 2〜3 桁良い**
    sudo -E $(which python3) pps.py --watch 120 --clkin 0

    # 極性を決める（パルス幅が分かっているとき。45m の 1PPS なら仕様値を入れる）
    sudo -E $(which python3) pps.py --pol-check --width 0.020 --clkin 0

**判定はレジスタの見た目ではなく、数字で行う。** proj004 で
「基準が切れても PLLLockStatus は 2 のまま 90 ppm ずれていた」を踏んでいる。
`--watch` は ppb を出すので、外部 10 MHz が効いているかもここで分かる。
"""

import argparse
import time

import adc_capture as ac

log = ac.log

# ---- PL と合わせる定数。build.tcl の beats_sec / src/pps_capture.v と一致させること ----
SPW = ac.SPW
FS_HZ = ac.FS_HZ
BEATS_PER_SEC = int(round(FS_HZ / SPW))        # = 153,600,000
BEAT_NS = 1e9 / (FS_HZ / SPW)                  # = 6.5104 ns
MAGIC = 0x00070001

# gpio_time_ctrl ch2 の制御ビット
CTRL_SNAP = 1 << 0
CTRL_SEL_SHIFT = 1
CTRL_POL = 1 << 5

# gpio_time_stat ch2 のフラグ
FLAG_ALIVE = 1 << 0        # 1.5 秒以内に PPS が来ている（TRIG 経路）
FLAG_LATE = 1 << 1         # arm した時点で start_at が過去だった
FLAG_ARMED = 1 << 2        # 予約を待っている
FLAG_ACK = 1 << 3          # スナップショットが取れた
FLAG_CALIVE = 1 << 4       # COMP 経路にも PPS が来ている

# セレクタ
SEL = {
    "beat_lo": 0, "beat_hi": 1,
    "stamp_lo": 2, "stamp_hi": 3,
    "count": 4, "interval": 5,
    "tstart_lo": 6, "tstart_hi": 7,
    "cstamp": 8, "glitch": 9,
    "magic": 15,
}


class PPS:
    """gpio_time_ctrl / gpio_time_stat の薄いラッパ。

    **64 bit の値は必ず snapshot() 経由で読む。** 32 bit を 2 回読むと
    その間にカウンタが進んで桁が裂ける。PL 側は snap の立ち上がりで
    全部を影レジスタへ写し、snap_ack で写し終わりを返す。
    """

    def __init__(self, ol):
        self.c = ol.gpio_time_ctrl
        self.s = ol.gpio_time_stat
        for ch, d in ((self.c.channel1, "out"), (self.c.channel2, "out"),
                      (self.s.channel1, "in"), (self.s.channel2, "in")):
            try:
                ch.setdirection(d)
            except Exception:                     # noqa: BLE001
                pass
        self._ctrl2 = 0
        self._w2(0)

    # ---- 下位 ----
    def _w2(self, val):
        self._ctrl2 = val & 0xFFFFFFFF
        self.c.channel2.write(self._ctrl2, 0xFFFFFFFF)

    def _sel(self, name):
        v = (self._ctrl2 & ~(0xF << CTRL_SEL_SHIFT)) | (SEL[name] << CTRL_SEL_SHIFT)
        self._w2(v)
        return self.s.channel1.read()

    # ---- 公開 ----
    def flags(self):
        return self.s.channel2.read()

    def set_pol(self, pol):
        """PPS のどちらのエッジを採用するか。**極性は RefMan から確定できない。**

        0 = PL 側の立ち上がり / 1 = 立ち下がり。切り替えた直後は、
        直前に採用したエッジからブランキング窓（0.5 秒）が効くので、
        **2 秒ほど待ってから読むこと。**
        """
        self._w2((self._ctrl2 & ~CTRL_POL) | (CTRL_POL if pol else 0))

    def write_start_at(self, beat):
        """予約する発火ビート（下位 32 bit）。**arm より前に書く。**"""
        self.c.channel1.write(int(beat) & 0xFFFFFFFF, 0xFFFFFFFF)

    def check_magic(self):
        got = self._sel("magic")
        if got != MAGIC:
            raise RuntimeError(
                f"gpio_time_stat から MAGIC が読めない: 0x{got:08x}（期待 0x{MAGIC:08x}）。"
                " GPIO の結線かビットストリームが proj007 でない")
        return got

    def snapshot(self, timeout=0.2):
        """全カウンタを一括ラッチして読む。戻り値は dict。"""
        self._w2(self._ctrl2 | CTRL_SNAP)
        t0 = time.time()
        while not (self.flags() & FLAG_ACK):
            if time.time() - t0 > timeout:
                self._w2(self._ctrl2 & ~CTRL_SNAP)
                raise RuntimeError(
                    "snap_ack が返らない。ctrl_aclk 側か pps_capture の結線を疑う")
        d = {
            "beat": self._sel("beat_lo") | (self._sel("beat_hi") << 32),
            "stamp": self._sel("stamp_lo") | (self._sel("stamp_hi") << 32),
            "count": self._sel("count"),
            "interval": self._sel("interval"),
            "t_start": self._sel("tstart_lo") | (self._sel("tstart_hi") << 32),
            "cstamp": self._sel("cstamp"),
        }
        g = self._sel("glitch")
        d["glitch_trig"] = g & 0xFFFF
        d["glitch_comp"] = (g >> 16) & 0xFFFF
        d["flags"] = self.flags()
        self._w2(self._ctrl2 & ~CTRL_SNAP)
        t0 = time.time()
        while self.flags() & FLAG_ACK:
            if time.time() - t0 > timeout:
                break
        return d

    def next_start(self, k=2, offset=0):
        """次の PPS から k 秒後（＋offset ビート）の予約ビートを返す。

        **k を 1 にしない。** ソフトが GPIO を叩き終える前に時刻が過ぎると
        late になる。2〜3 秒あれば PS の負荷が高くても余裕がある。
        """
        d = self.snapshot()
        if not (d["flags"] & FLAG_ALIVE):
            raise RuntimeError("PPS が来ていない（alive = 0）。--probe で先に確かめる")
        return (d["stamp"] + k * BEATS_PER_SEC + offset) & 0xFFFFFFFF, d


def fmt_flags(f):
    names = [(FLAG_ALIVE, "alive"), (FLAG_LATE, "late"), (FLAG_ARMED, "armed"),
             (FLAG_ACK, "ack"), (FLAG_CALIVE, "comp_alive")]
    on = [n for b, n in names if f & b]
    return f"0x{f:02x} [{' '.join(on) if on else '-'}]"


# ------------------------------------------------------------------- 表示
def wait_epoch(p, t_ovl, timeout=10.0):
    """**時刻の原点（aresetn の解除）がいつだったかを測る。**

    原点は Overlay のロードではない。`pps_capture/aresetn` は
    `rst_adc/peripheral_aresetn` で、その `dcm_locked` は `clk_wiz_adc/locked`、
    さらにその入力は RFDC の `clk_adc2` である。
    **RFDC のタイル 2 が立ち上がって MMCM がロックするまでリセットは解けない。**
    `pps.py` は `adc_capture.py` と違ってタイルに触らないので、起動は
    Overlay のあと非同期に進む。

    2026-09-17 の実機で `beat_count = 2` が出たのがこれ。python が snap を
    立てて ack を待っている最中にリセットが解除され、snap が既に H だったため
    同期器の 3 クロック目に一度だけスナップが打たれた。
    `MAGIC` が読めていたのは `rdata` が ctrl_aclk 側でリセットを持たないためで、
    **「MAGIC が読める」はリセットが解けている証拠にならない。**

    リセット中は `snap_ack` が返らないので `snapshot()` が例外を投げる。
    **それをリセットの観測に使う。**
    """
    t0 = time.time()
    waited = False
    while True:
        try:
            d = p.snapshot(timeout=0.05)
            break
        except RuntimeError:
            waited = True
            if time.time() - t0 > timeout:
                raise RuntimeError(
                    "aresetn が解除されない。clk_wiz_adc の locked（= RFDC の "
                    "clk_adc2）を疑う。adc_capture.py --probe でタイルの "
                    "PLLLockStatus を先に確かめること")
            time.sleep(0.01)

    now = time.time()
    age = d["beat"] * BEAT_NS / 1e9          # リセット解除からの経過 [s]
    rel = (now - age) - t_ovl                # Overlay から解除までの時間 [s]
    log(f"時刻の原点     : Overlay の {rel * 1e3:+.0f} ms 後に aresetn が解除された"
        f"（現在 {age * 1e3:.0f} ms 経過）")
    if waited:
        log("  リセットが解けるまで待った（snap_ack が返らなかった）")
    if age < 0.010:
        log("  **原点が今この瞬間である。** 以後の beat_count はここからの相対値。")
        log("  `beat_count` を絶対時刻に直すときの基準は Overlay ではなくこの時刻")
    return d


def check_beat(p, dt=0.5):
    """ビートカウンタが本当に走っているかを 2 回のスナップショットで確かめる。

    **PPS の受信を語る前に必ずここを通す。** スナップショットが更新されて
    いなければ beat も stamp も interval も全部が嘘になるが、値そのものは
    「それらしく」見えるので気づけない。

    2026-09-17 の初回の実機で `beat_count = 2` が出た。ack は立っていたので
    スナップ機構は動いており、1 回読むだけでは正常と区別がつかなかった。
    **「動いている証拠」は値の大きさではなく、進み方で取る。**
    """
    ta = time.time()
    a = p.snapshot()
    time.sleep(dt)
    tb = time.time()
    b = p.snapshot()
    el = tb - ta
    dbeat = b["beat"] - a["beat"]
    exp = el * BEATS_PER_SEC
    log(f"カウンタの確認 : {el * 1e3:.1f} ms で {dbeat:,} ビート進んだ"
        f"（期待 {exp:,.0f}）")

    if dbeat <= 0:
        log("")
        log("**スナップショットが更新されていない。上の値はすべて信用できない。**")
        log("  beat も stamp も interval も、リセット直後の 1 回を読み続けている。")
        log("  順に確かめる:")
        log("    1. gpio_time_ctrl ch2 bit0（snap）が pps_capture に届いているか")
        log("    2. aresetn が解除されたあとに snap が立ち上がっているか")
        log("       （リセット解除の時点で snap が H だと、その 2〜3 クロック後に")
        log("        一度だけ打たれ、以後 python が立てても立ち上がりにならない）")
        log("    3. flags の ack は立つので、**ack はスナップの鮮度を保証しない**")
        return False

    err = (dbeat - exp) / exp
    if abs(err) > 0.05:
        log("")
        log(f"**進み方が期待と {err * 100:+.1f} % ずれている。**")
        log("  aclk が 153.6 MHz で回っていない疑い。")
        log("  Clocking Wizard の出力と RFDC の Outclk_Freq を build のログで確かめる")
        return False

    log(f"  → カウンタは走っている（誤差 {err * 100:+.2f} %）。時刻の実体は生きている")
    return True


def do_probe(p, t_ovl):
    p.check_magic()
    log(f"MAGIC          : 0x{MAGIC:08x}  （GPIO の結線は正しい）")
    log("  **これはリセットが解けている証拠にはならない。**"
        " rdata は ctrl_aclk 側でリセットを持たない")
    d = wait_epoch(p, t_ovl)

    # ---- **PPS の判定はリセット解除から最低 2.5 秒待ってから行う** ----
    #
    # 2026-09-17、ここが無いまま「PPS が来ていない」と誤判定した。
    # 時刻の原点は Overlay ではなく MMCM のロックで、旧版はその直後
    # （beat_count = 2、つまり 13 ns 後）に判定していた。
    # **1 Hz の信号なので、その時点では最初のエッジがまだ来ていない。**
    # `t_age` はリセット時に MISS_BEATS で初期化されるので alive は 0 になり、
    # **ケーブルを挿していないときと出力が一字一句同じになる。**
    # 「来ていない」と「まだ来ていない」を区別できる形にしておくこと。
    need = 2.5
    age = d["beat"] * BEAT_NS / 1e9
    if age < need:
        log(f"  PPS の判定には原点から最低 {need} s 要る（1 Hz なので）。"
            f"あと {need - age:.1f} s 待つ")
        time.sleep(need - age)
        d = p.snapshot()
    log(f"flags          : {fmt_flags(d['flags'])}")
    log(f"beat_count     : {d['beat']}  （Overlay ロードからの経過 = "
        f"{d['beat'] * BEAT_NS / 1e9:.3f} s）")
    log(f"pps_count      : {d['count']}")
    log(f"pps_stamp      : {d['stamp']}")
    log(f"pps_interval   : {d['interval']}  （期待 {BEATS_PER_SEC}）")
    log(f"comp_stamp(32) : {d['cstamp']}")
    log(f"glitch         : trig {d['glitch_trig']} / comp {d['glitch_comp']}")
    log("")

    # **ここを通らなければ PPS の話をしない。** 上の値の意味が決まらない
    if not check_beat(p):
        return
    log("")

    if not (d["flags"] & FLAG_ALIVE):
        log("**PPS が来ていない。** 順に確かめる:")
        log("  1. ケーブルが `PPS Clk` の SMA に挿さっているか（ADC_x や CLK_IN ではない）")
        log("  2. **信号が来ているか**をオシロかスペアナで測る")
        log("     （proj004 で SG の REF OUT が出ていなかった件と同じ順序。")
        log("      レジスタを疑う前に信号を測る）")
        log("  3. **極性ではない。** 1 Hz のパルス列なら極性がどちらでも")
        log("     XOR 出力の立ち上がりは毎秒ちょうど 1 回ある。極性で変わるのは")
        log("     タイムスタンプが立ち上がり側か立ち下がり側かだけ。")
        log("     **glitch も 0 = ブランキング窓の中にすら遷移が無い**ので、")
        log("     PL のピンがそもそも動いていない")
        log("  4. `--level` でピンの静止レベルを読む（再ビルド不要）。")
        log("     そこからコンパレータの閾値か結線かを切り分ける")
        return
    if not (d["flags"] & FLAG_CALIVE):
        log("**TRIG 経路だけが受かっていて、COMP 経路が動いていない。**")
        log("  IRIG_COMP_OUT はオープンドレイン。基板のプルアップが無い可能性がある。")
        log("  src/pps.xdc の `set_property PULLUP true` を有効にして焼き直す")
    dc = (d["cstamp"] - (d["stamp"] & 0xFFFFFFFF)) & 0xFFFFFFFF
    if dc > (1 << 31):
        dc -= 1 << 32
    log(f"COMP − TRIG    : {dc} ビート = {dc * BEAT_NS:.2f} ns")
    log("  **0 か ±1 ビートなら「シュミットトリガの遅延は 6.5 ns 未満」までしか言えない。**")
    log("  それが正常。大きく離れていたら波形が汚れている（glitch も見る）")


def do_level(p, settle=0.7):
    """**PL のピンが静止しているとき、その静止レベルを読む。**

    `pps_capture` にピンの生の値を読むレジスタは無い。しかし極性 `pol` は
    **同期器の手前で XOR されている**ので、`pol` を反転させると XOR 出力に
    必ず 1 回だけ遷移が起きる。その遷移が立ち上がりになるのは

        pol 0 → 1 のとき : ピンが L
        pol 1 → 0 のとき : ピンが H

    に限られる。**pol を往復させてどちらで計数が進むかを見れば、ピンの静止
    レベルが分かる。** 再ビルドは要らない。

    待ち時間はブランキング（0.5 秒）より長く取る。短いとグリッチ扱いで
    捨てられ、計数ではなく glitch のほうが進む。
    """
    # **まず「pol を触るまでもなく動いていないか」を見る。**
    # ピンが動いていれば pol の反転ぶんと本物のエッジが混ざり、
    # 往復の計数が 1,0,1,0 にならず読めなくなる（2026-09-17 に踏んだ）。
    a = p.snapshot()
    time.sleep(1.5)
    b = p.snapshot()
    if b["count"] != a["count"] or b["cstamp"] != a["cstamp"]:
        log("**ピンは動いている。** pol を触るまでもなく計数が進んでいる")
        log(f"  1.5 s で t_count が {b['count'] - a['count']} 回進んだ"
            f"（comp_stamp {'変化あり' if b['cstamp'] != a['cstamp'] else 'なし'}）")
        log("  **--level は静止しているときの道具である。** --probe をやり直すこと")
        return

    log("極性を往復させてピンの静止レベルを読む（再ビルド不要）")
    log(f"  各段 {settle} s 待つ（ブランキング 0.5 s より長く）")
    log("")
    log("  遷移       t_count Δ   comp_stamp   t_glitch Δ")
    log("  " + "-" * 48)

    p.set_pol(0)
    time.sleep(settle)
    prev = p.snapshot()
    obs = []
    for pol in (1, 0, 1, 0):
        p.set_pol(pol)
        time.sleep(settle)
        d = p.snapshot()
        dt = d["count"] - prev["count"]
        dc = 1 if d["cstamp"] != prev["cstamp"] else 0
        dg = d["glitch_trig"] - prev["glitch_trig"]
        log(f"  {1 - pol} → {pol}      {dt:>6}      "
            f"{'変化あり' if dc else 'なし    '}     {dg:>6}")
        obs.append((pol, dt, dc))
        prev = d

    log("")
    for name, idx in (("TRIG (AH13)", 1), ("COMP (AJ13)", 2)):
        up = sum(o[idx] for o in obs if o[0] == 1)   # 0 → 1 で計数 = ピンは L
        dn = sum(o[idx] for o in obs if o[0] == 0)   # 1 → 0 で計数 = ピンは H
        if up and not dn:
            log(f"  {name}: **L で静止している**")
        elif dn and not up:
            log(f"  {name}: **H で静止している**")
        elif up and dn:
            log(f"  {name}: 両方で計数した。ピンは動いている"
                f"（PPS が来ている。--probe をやり直す）")
        else:
            log(f"  {name}: **どちらでも計数しない。**"
                f" pol（gpio_time_ctrl ch2 bit5）が PL に届いていないか、"
                f" 入力経路が切れている")
    log("")
    log("読み方:")
    log("  TRIG が L で静止 → シュミットトリガが一度も反転していない。")
    log("    コンパレータが振れていない = 閾値に届いていないか、信号が")
    log("    コンパレータまで来ていない。**SMA と基板側を疑う順序**")
    log("  COMP が H で静止 → オープンドレインにプルアップが在って、")
    log("    コンパレータが一度も引き落としていない（上と同じ結論）")
    log("  COMP が L で静止 → プルアップが無くて浮いているか、常時引かれている。")
    log("    src/pps.xdc の PULLUP を有効にして焼き直すと切り分けられる")
    log("  **両方が同じ向きの結論になるはず**（同じコンパレータから出ている）。")
    log("  食い違ったら、ピン割り当て（AH13 / AJ13）の前提から疑う")


def do_watch(p, seconds, period):
    """PPS の残差を積んで周波数確度を出す。

    **これが proj007 の本題のひとつ。** proj004 の CW + サブビン補間は
    53.3 µs のキャプチャが限界で 15 ppb だった。ここは時間を掛けるほど良くなる。
    """
    p.check_magic()
    d0 = p.snapshot()
    if not (d0["flags"] & FLAG_ALIVE):
        raise RuntimeError("PPS が来ていない。--probe で先に確かめる")
    log(f"基準: pps_count={d0['count']} stamp={d0['stamp']}")
    log("")
    log("  経過[s]  受信数  interval[beat]   残差[beat]   確度[ppb]  glitch")
    log("  " + "-" * 62)
    t0 = time.time()
    last = None
    while time.time() - t0 < seconds:
        time.sleep(period)
        d = p.snapshot()
        n = d["count"] - d0["count"]
        if n <= 0:
            continue
        # **スタンプの差で測る。** 秒数はホスト時計ではなく PPS の数で数える
        # （ホスト時計の誤差が混ざると、測っているものが変わってしまう）
        db = d["stamp"] - d0["stamp"]
        resid = db - n * BEATS_PER_SEC
        ppb = resid / (n * BEATS_PER_SEC) * 1e9
        log(f"  {n:7d}  {d['count']:6d}  {d['interval']:14d}  {resid:11d}  "
            f"{ppb:10.4f}  {d['glitch_trig']}/{d['glitch_comp']}")
        last = (n, resid, ppb, d)
    log("")
    if last is None:
        log("**PPS が 1 発も増えなかった。** 配線か極性を疑う")
        return
    n, resid, ppb, d = last
    log(f"確定: {n} 秒ぶん / 残差 {resid} ビート = {resid * BEAT_NS:.1f} ns")
    log(f"      確度 {ppb:+.4f} ppb  （分解能 = 1 ビート / {n} 秒 "
        f"= {BEAT_NS / n:.4f} ppb）")
    log("")
    log("**読み方。** 45m の 1PPS と 10 MHz が同じ標準から出ているなら、")
    log("残差は積んでも増えないはず。**フラットであること自体が検証**になる。")
    log("ドリフトするなら、どちらかが思っているものと違う")
    log("（proj004: 外部基準を挿さずに CLKin0 を選ぶと +90.68 ppm ずれた。")
    log(" そのとき PLLLockStatus は 2 のまま、DMA も波形も正常だった）。")
    if d["glitch_trig"] or d["glitch_comp"]:
        log("")
        log(f"**グリッチがある（trig {d['glitch_trig']} / comp {d['glitch_comp']}）。**")
        log("  ブランキング窓（0.5 秒）の中に余分なエッジが来ている。")
        log("  波形のリンギングか、終端の不整合を疑う")


def do_pol_check(p, width_s):
    """極性を決める。**パルス幅が分かっていることが前提。**

    立ち上がりと立ち下がりの両方でスタンプを取り、その差を見る。
    pol=0 が真の立ち上がりなら差はパルス幅に、そうでなければ
    (1 秒 − パルス幅) になる。
    """
    p.check_magic()
    out = {}
    for pol in (0, 1):
        p.set_pol(pol)
        # **切り替え直後はブランキングが効く。**2 秒待つ
        time.sleep(2.5)
        d = p.snapshot()
        if not (d["flags"] & FLAG_ALIVE):
            raise RuntimeError(f"pol={pol} で PPS を受けられない")
        out[pol] = d
        log(f"  pol={pol}  stamp={d['stamp']}  interval={d['interval']} "
            f"({d['interval'] * BEAT_NS / 1e6:.3f} ms)")
    p.set_pol(0)
    delta = (out[1]["stamp"] - out[0]["stamp"]) % BEATS_PER_SEC
    ms = delta * BEAT_NS / 1e6
    log("")
    log(f"pol=0 → pol=1 の位相差: {delta} ビート = {ms:.3f} ms")
    log(f"その補数              : {(BEATS_PER_SEC - delta) * BEAT_NS / 1e6:.3f} ms")
    log("")
    log(f"与えたパルス幅        : {width_s * 1e3:.3f} ms")
    tol = max(0.05 * width_s, 1e-4) * 1e3
    if abs(ms - width_s * 1e3) < tol:
        log("→ **pol=0 が真の立ち上がり。** そのまま使う")
    elif abs((BEATS_PER_SEC - delta) * BEAT_NS / 1e6 - width_s * 1e3) < tol:
        log("→ **pol=1 が真の立ち上がり。** 以後 --pol 1 を付ける")
        log("  （LMV7235 はオープンドレインなので反転していておかしくない）")
    else:
        log("→ **どちらとも言えない。** パルス幅の申告値が違うか、")
        log("  余分なエッジを拾っている（glitch を見る）")
        log(f"  glitch: trig {out[0]['glitch_trig']} / comp {out[0]['glitch_comp']}")


# ------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=ac.BITFILE)
    p.add_argument("--probe", action="store_true", help="配線と受信の確認（既定）")
    p.add_argument("--watch", type=float, default=None,
                   help="この秒数ぶん残差を積んで確度を出す")
    p.add_argument("--period", type=float, default=5.0, help="--watch の表示間隔 [s]")
    p.add_argument("--level", action="store_true",
                   help="ピンの静止レベルを読む（PPS が受からないときの切り分け）")
    p.add_argument("--pol-check", action="store_true", help="極性を判定する")
    p.add_argument("--width", type=float, default=0.020,
                   help="1PPS のパルス幅 [s]（--pol-check に使う）")
    p.add_argument("--pol", type=int, default=0, choices=(0, 1),
                   help="採用するエッジ。0 = 立ち上がり")
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--no-clk", action="store_true", help="xrfclk を触らない")
    args = p.parse_args()

    from pynq import Overlay
    import xrfdc                                   # noqa: F401  Overlay より前に import

    if not args.no_clk:
        ac.setup_clocks(args.clkin, args.ref)
    ol = Overlay(args.bitfile)
    t_ovl = time.time()
    log(f"Overlay: {args.bitfile}")

    pps = PPS(ol)
    pps.set_pol(args.pol)
    if args.pol:
        time.sleep(2.5)     # 極性を変えた直後はブランキングが効く

    if args.level:
        do_level(pps)
    elif args.pol_check:
        do_pol_check(pps, args.width)
    elif args.watch:
        do_watch(pps, args.watch, args.period)
    else:
        do_probe(pps, t_ovl)


if __name__ == "__main__":
    main()

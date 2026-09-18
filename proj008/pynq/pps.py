#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj008 — 1PPS の受信確認と、ビートカウンタの読み出し（proj007 から MAGIC のみ変更）。

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
MAGIC = 0x00080001        # proj008 rev1（RTL は proj007 rev2 と同一）

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
FLAG_ADCRSTN = 1 << 5      # ADC ドメインが aresetn 解除済み（rev2）
FLAG_LOCKED = 1 << 6       # clk_wiz_adc がロックしている（rev2）

# セレクタ
SEL = {
    "beat_lo": 0, "beat_hi": 1,
    "stamp_lo": 2, "stamp_hi": 3,
    "count": 4, "interval": 5,
    "tstart_lo": 6, "tstart_hi": 7,
    "cstamp": 8, "glitch": 9,
    "epoch": 10,
    "magic": 15,
}


class EpochChanged(RuntimeError):
    """**時刻の原点が変わった**（rev2）。

    `aresetn` が入り直すと `beat_count` は 0 に戻り、それ以前に読んだ
    `beat_count` / `stamp` / `t_start` との繋がりが切れる。
    **そのとき値そのものは正常に見える**ので、例外で止めないと
    絶対時刻だけが静かにずれた観測ができあがる。
    """


class PPS:
    """gpio_time_ctrl / gpio_time_stat の薄いラッパ。

    **64 bit の値は必ず snapshot() 経由で読む。** 32 bit を 2 回読むと
    その間にカウンタが進んで桁が裂ける。PL 側は snap の立ち上がりで
    全部を影レジスタへ写し、snap_ack で写し終わりを返す。
    """

    def __init__(self, ol):
        self.ol = ol                  # --epoch-test で rfdc のタイルを叩くため
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

    def epoch(self):
        """**beat_count の原点の通し番号**（rev2）。

        0 = まだ一度も `aresetn` が解除されていない（beat_count は動いていない）。
        MMCM がロックを外す・RFDC のタイルを起動し直す、のいずれでも +1 される。
        **変わったら、それ以前に読んだ beat_count / stamp / t_start は
        別の原点の値なので捨てる。**
        """
        return self._sel("epoch")

    def check_magic(self):
        got = self._sel("magic")
        if got != MAGIC:
            raise RuntimeError(
                f"gpio_time_stat から MAGIC が読めない: 0x{got:08x}（期待 0x{MAGIC:08x}）。"
                " GPIO の結線かビットストリームが proj008 でない")
        return got

    def snapshot(self, timeout=0.2, check_epoch=True):
        """全カウンタを一括ラッチして読む。戻り値は dict。"""
        # **原点が変わっていないことを前後で確かめる（rev2）。**
        # スナップショット自体は一瞬で整合するが、その前に読んだ値との
        # 繋がりは原点が変わると切れる。**壊れた時刻は正常な時刻に見える**ので、
        # 気づく口をここに置く。
        ep0 = self._sel("epoch") if check_epoch else None
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

        if check_epoch:
            ep1 = self._sel("epoch")
            d["epoch"] = ep1
            if ep1 != ep0:
                raise EpochChanged(
                    f"読んでいる最中に時刻の原点が変わった（epoch {ep0} → {ep1}）。"
                    "beat_count は 0 に戻っている。MMCM がロックを外したか、"
                    "RFDC のタイルを起動し直した")
            if ep1 == 0:
                raise EpochChanged(
                    "aresetn がまだ一度も解除されていない（epoch = 0）。"
                    "beat_count は動いていない")
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
             (FLAG_ACK, "ack"), (FLAG_CALIVE, "comp_alive"),
             (FLAG_ADCRSTN, "adc_rstn"), (FLAG_LOCKED, "locked")]
    on = [n for b, n in names if f & b]
    return f"0x{f:02x} [{' '.join(on) if on else '-'}]"


# ------------------------------------------------------------------- 表示
def wait_epoch(p, t_ref, timeout=10.0, label="Overlay"):
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
    rel = (now - age) - t_ref                # 起点から解除までの時間 [s]
    log(f"時刻の原点     : {label} の {rel * 1e3:+.0f} ms 後に aresetn が解除された"
        f"（現在 {age * 1e3:.0f} ms 経過）")
    log(f"  epoch = {d['epoch']} / {fmt_flags(d['flags'])}")
    if d["epoch"] > 1:
        log(f"  **原点は既に {d['epoch']} 回張り直されている。**"
            " RFDC のタイル起動か MMCM のロック外れ。")
        log("  これ自体は異常ではないが、**この epoch より前に読んだ時刻は無効**")
    if waited:
        log("  リセットが解けるまで待った（snap_ack が返らなかった）")
    if age < 0.010:
        log("  **原点が今この瞬間である。** 以後の beat_count はここからの相対値。")
        log("  `beat_count` を絶対時刻に直すときの基準は Overlay ではなくこの時刻")
    return d


def wait_ready(p, t_ref, need=2.5, label="Overlay"):
    """**リセットの解除を待ち、さらに PPS が 2 回来るまで待ってから返す。**

    `--probe` `--watch` `--pol-check`、`pps_delay.py` は全部これを通す。
    時刻の原点は Overlay ではなく MMCM のロックなので、原点からの経過が
    1 秒に満たないうちに `alive` を見ると **必ず 0 になる**。
    2026-09-17、ここを通していなかった `--probe` が「PPS が来ていない」と
    誤判定し、`--watch` が同じ理由で例外を投げた。

    **RFDC のタイルを起動したあとも必ずこれを通す。** タイルを起動すると
    `clk_adc` が立ち上がり直して MMCM がロックを外し、`aresetn` が再アサート
    される。**エポックはそこで 0 に戻る。** 2026-09-17、`pps_delay.py` が
    `start_tiles()` の直後に `next_start()` を呼んで `alive = 0` で落ちた。
    """
    d = wait_epoch(p, t_ref, label=label)
    age = d["beat"] * BEAT_NS / 1e9
    if age < need:
        log(f"  PPS の判定には原点から最低 {need} s 要る（1 Hz なので）。"
            f"あと {need - age:.1f} s 待つ")
        time.sleep(need - age)
        d = p.snapshot()
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

    # **2 つのスナップショットの間で原点が変わっていないこと。**
    # snapshot() 単体の検査は「読んでいる最中」しか見ない。**またいだ変化は
    # ここでしか捕まらない**（差分が負や巨大な値になって「カウンタが止まった」
    # と誤診する）
    if a["epoch"] != b["epoch"]:
        log(f"**2 回のスナップショットの間で原点が変わった"
            f"（epoch {a['epoch']} → {b['epoch']}）。**")
        log("  beat_count は 0 に戻っている。進み方の比較は成立しない")
        return False

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
    d = wait_ready(p, t_ovl)
    log(f"flags          : {fmt_flags(d['flags'])}")
    log(f"beat_count     : {d['beat']}  （Overlay ロードからの経過 = "
        f"{d['beat'] * BEAT_NS / 1e9:.3f} s）")
    log(f"epoch          : {d['epoch']}  （時刻の原点の通し番号）")
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
    if d["glitch_trig"] or d["glitch_comp"]:
        log("  **glitch が立っている。波形が汚れている疑い。**"
            " 下の解釈より先にこちらを潰す")
    elif abs(dc) <= 1:
        log("  0 か ±1 ビート。**「差は 6.5 ns 未満」までしか言えない**が、それが正常")
    elif dc > 0:
        log("  **COMP が TRIG より遅れている。これは想定内で、原因は立ち上がりの鈍さ。**")
        log("  IRIG_COMP_OUT はオープンドレインなので、L → H は基板のプルアップ抵抗と")
        log("  容量の RC で決まる。シュミットトリガ側はプッシュプルなので速い。")
        log("  **comp_alive が立っている時点で、基板にプルアップが在ることは確定している**")
        log("  → 立ち上がりのタイムスタンプは TRIG 側を使う。COMP は波形の健全性の監視に回す")
    else:
        log("  **COMP が TRIG より進んでいる。** 想定と逆。ピン割り当て")
        log("  （AH13 = TRIG / AJ13 = COMP）の前提から疑う")


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


def do_epoch_test(p, t_ovl, src_tile=2, ctl_tile=0, settle=2.0):
    """**rev2 が働くところを実際に見る。**

    `aresetn` を意図的に落とす。確実なのは **MMCM の源になっているタイルを
    止めること**で、`build.tcl` の `wiz_src_tile` は 2（Tile 226 の `clk_adc2`）。

    **対照を置く。** Tile 224（インデックス 0）は MMCM の源ではないので、
    同じように止めても `epoch` は変わらないはずである。
    片方だけ見ると「止めたら何か起きた」で終わるが、対照を並べれば
    **「MMCM の源だから起きた」**まで言える。
    proj006 で `get_timing_paths` の偽陽性を対照で切り分けたのと同じ型。

    **注意: Overlay の読み直しはこの試験に使えない。** PL を焼き直すと
    `rst_ctrl` も落ちて **epoch カウンタ自身が 0 に戻る**ので、
    読み直しの前後でどちらも 1 に見える。**epoch は PL の再構成を検出できない。**
    これは仕組み上の限界で、回避策は無い（検出したいなら PS 側で
    Overlay のロード回数を数える）。
    """
    log("**この試験は意図的に aresetn を落とす。** 観測中に実行しないこと")
    log("")
    d0 = wait_ready(p, t_ovl)
    log("")
    log(f"起点 : epoch = {d0['epoch']} / beat_count = {d0['beat']:,} / "
        f"{fmt_flags(d0['flags'])}")
    log("")

    def cycle(idx, what):
        tile = p.ol.rfdc.adc_tiles[idx]
        ep0 = p.epoch()
        b0 = p.snapshot()["beat"]
        log(f"---- {what}: adc_tiles[{idx}]（Tile {224 + idx}）----")
        tile.ShutDown()
        time.sleep(0.5)
        f_down = p.flags()
        log(f"  停止中      : {fmt_flags(f_down)}")
        tile.StartUp()
        # ロックが戻るのを待つ
        t0 = time.time()
        while not (p.flags() & FLAG_LOCKED):
            if time.time() - t0 > 10.0:
                log("  **locked が戻らない。** ここで止める")
                return None
            time.sleep(0.05)
        time.sleep(settle)
        ep1 = p.epoch()
        b1 = p.snapshot()["beat"]
        log(f"  再起動後    : epoch {ep0} → {ep1} / "
            f"beat_count {b0:,} → {b1:,}")
        log(f"                {fmt_flags(p.flags())}")
        return {"ep0": ep0, "ep1": ep1, "b0": b0, "b1": b1, "down": f_down}

    ctl = cycle(ctl_tile, "対照（MMCM の源ではないタイル）")
    if ctl is None:
        return
    log("")
    src = cycle(src_tile, "本番（MMCM の源のタイル）")
    if src is None:
        return

    log("")
    log("---- 判定 ----")
    ok = True

    if ctl["ep1"] == ctl["ep0"] and ctl["b1"] > ctl["b0"]:
        log(f"  対照: epoch は {ctl['ep0']} のまま、beat_count も進み続けた。"
            " **このタイルは MMCM の源ではない**")
    else:
        ok = False
        log("  **対照でも epoch が動いた／beat が戻った。**")
        log("    build.tcl の wiz_src_tile の前提が違う。どちらが源かを見直す")

    if src["down"] & FLAG_LOCKED:
        ok = False
        log("  **停止中も locked が立っていた。** MMCM の源が別のタイルにある疑い")
    else:
        log("  本番: 停止中に locked が落ちた。**MMCM の源であることが直接見えた**")

    if src["ep1"] == src["ep0"] + 1 and src["b1"] < src["b0"]:
        log(f"  本番: **epoch が {src['ep0']} → {src['ep1']} に増え、"
            f"beat_count は {src['b0']:,} → {src['b1']:,} に戻った**")
    else:
        ok = False
        log(f"  **期待と違う**（epoch {src['ep0']} → {src['ep1']} / "
            f"beat {src['b0']:,} → {src['b1']:,}）")

    log("")
    log("**epoch を見ていなかったら何が起きていたか。**")
    stale = d0["stamp"]
    now = p.snapshot()["beat"]
    dt = (now - stale) * BEAT_NS / 1e9
    log(f"  起点で読んだ pps_stamp = {stale:,} を、いまの beat_count = {now:,} と")
    log(f"  同じ原点のものとして扱うと、経過時間は {dt:+.3f} s になる。")
    log("  **実際には原点が張り直されているので、この数字に意味は無い。**")
    log("  値は出る。エラーにもならない。**epoch を見ない限り区別できない**")

    log("")
    log("=== " + ("PASS" if ok else "FAIL") + " ===")


def do_watch(p, t_ovl, seconds, period):
    """PPS の残差を積んで周波数確度を出し、**長時間の持続性を見張る。**

    **これが proj007 の本題のひとつ。** proj004 の CW + サブビン補間は
    53.3 µs のキャプチャが限界で 15 ppb だった。ここは時間を掛けるほど良くなる。

    **proj008 の判定 6 はこれを数時間〜一晩まわす。** そのために足したもの:

    - **`epoch` を毎回見る。** 判定 6 の本題は「原点が勝手に変わらないか」である。
      変われば `stamp` が 0 に戻り、残差は巨大な数字になる。**それを「残差が悪い」と
      読むと、原因がまるで違うほうへ行く。** 原点が変わったら**そう言って**基準を打ち直す
    - **`flags` の遷移を記録する。** `alive` / `locked` / `comp_alive` が落ちた瞬間が
      分かれば、あとで他の事象と突き合わせられる
    - **壁時計を出す。** 一晩の記録は、他の出来事と時刻で突き合わせるためにある
    - **最悪値を溜める。** 8640 行を目で追わないで済むように、末尾でまとめる

    長時間走らせるときは `--period 60` にしてファイルへ落とす:

        sudo -E $(which python3) pps.py --watch 43200 --period 60 --clkin 0 \
             2>&1 | tee watch_$(date +%Y%m%d_%H%M).log
    """
    p.check_magic()
    d0 = wait_ready(p, t_ovl)
    if not (d0["flags"] & FLAG_ALIVE):
        raise RuntimeError("PPS が来ていない。--probe で先に確かめる")

    def _stamp():
        return time.strftime("%H:%M:%S")

    # 残差の基準。**原点が変わったら打ち直す**（打ち直した事実は記録する）
    base = dict(count=d0["count"], stamp=d0["stamp"], epoch=d0["epoch"],
                t=time.time())
    log(f"基準: pps_count={base['count']} stamp={base['stamp']} "
        f"epoch={base['epoch']}  [{_stamp()}]")
    log("")
    log("  時刻      経過[s]  受信数  interval[beat]  残差[beat]  確度[ppb]  ep  glitch")
    log("  " + "-" * 76)

    t0 = time.time()
    last = None
    prev_flags = d0["flags"]
    events = []                 # (壁時計, 種別, 説明)
    worst = dict(resid=0, ppb=0.0)
    seg_best = []               # エポック区間ごとの (秒数, 残差, ppb)
    n_epoch_changes = 0
    n_read_errors = 0
    g0 = (d0.get("glitch_trig", 0), d0.get("glitch_comp", 0))

    while time.time() - t0 < seconds:
        time.sleep(period)
        try:
            d = p.snapshot()
        except EpochChanged as e:
            # **読んでいる最中に変わった。**これ自体が判定 6 の観測対象なので、
            # 例外で落とさずに事象として記録して続ける
            n_read_errors += 1
            events.append((_stamp(), "epoch", f"読み出し中に原点が変わった: {e}"))
            log(f"  [{_stamp()}] **読み出し中に原点が変わった。** 基準を打ち直す")
            time.sleep(2.5)
            try:
                d = p.snapshot()
            except EpochChanged:
                log(f"  [{_stamp()}] **連続して変わっている。** MMCM を疑う")
                continue
            base = dict(count=d["count"], stamp=d["stamp"], epoch=d["epoch"],
                        t=time.time())
            n_epoch_changes += 1
            continue

        # ---- flags の遷移 ----
        if d["flags"] != prev_flags:
            gone = [n for b, n in ((FLAG_ALIVE, "alive"), (FLAG_CALIVE, "comp_alive"),
                                   (FLAG_LOCKED, "locked"), (FLAG_ADCRSTN, "adc_rstn"))
                    if (prev_flags & b) and not (d["flags"] & b)]
            came = [n for b, n in ((FLAG_ALIVE, "alive"), (FLAG_CALIVE, "comp_alive"),
                                   (FLAG_LOCKED, "locked"), (FLAG_ADCRSTN, "adc_rstn"))
                    if not (prev_flags & b) and (d["flags"] & b)]
            if gone or came:
                msg = ("落ちた: " + ",".join(gone) if gone else "") + \
                      ("  戻った: " + ",".join(came) if came else "")
                events.append((_stamp(), "flags", msg))
                log(f"  [{_stamp()}] **flags が変わった** {fmt_flags(d['flags'])}  {msg}")
            prev_flags = d["flags"]

        # ---- 原点が変わっていないか（**判定 6 の本題**）----
        if d["epoch"] != base["epoch"]:
            n_epoch_changes += 1
            events.append((_stamp(), "epoch",
                           f"{base['epoch']} → {d['epoch']}（{time.time() - base['t']:.0f} 秒もった）"))
            log(f"  [{_stamp()}] **時刻の原点が変わった（epoch {base['epoch']} "
                f"→ {d['epoch']}）。**")
            log(f"       それまで {time.time() - base['t']:.0f} 秒もっていた。"
                "**この時点より前の絶対時刻は無効。** 基準を打ち直す")
            if last:
                seg_best.append(last[:3])
            base = dict(count=d["count"], stamp=d["stamp"], epoch=d["epoch"],
                        t=time.time())
            last = None
            continue

        n = d["count"] - base["count"]
        if n <= 0:
            continue
        # **スタンプの差で測る。** 秒数はホスト時計ではなく PPS の数で数える
        db = d["stamp"] - base["stamp"]
        resid = db - n * BEATS_PER_SEC
        ppb = resid / (n * BEATS_PER_SEC) * 1e9
        if abs(resid) > abs(worst["resid"]):
            worst = dict(resid=resid, ppb=ppb)
        gt = d["glitch_trig"] - g0[0]
        gc = d["glitch_comp"] - g0[1]
        log(f"  {_stamp()}  {n:7d}  {d['count']:6d}  {d['interval']:14d}  "
            f"{resid:10d}  {ppb:9.4f}  {d['epoch']:2d}  {gt}/{gc}")
        last = (n, resid, ppb, d)

    log("")
    if last:
        seg_best.append(last[:3])

    # ---- まとめ（**8640 行を目で追わないで済むように**）----
    log("=" * 60)
    log(f"**まとめ**  {seconds / 3600:.2f} 時間ぶん  [{_stamp()} まで]")
    log("=" * 60)
    log(f"  時刻の原点が変わった回数 : **{n_epoch_changes}**"
        + ("   ← **0 なら判定 6 は通っている**" if n_epoch_changes == 0 else ""))
    log(f"  読み出し中の原点変化     : {n_read_errors}")
    log(f"  最悪の残差               : {worst['resid']} ビート "
        f"= {worst['resid'] * BEAT_NS:.1f} ns（{worst['ppb']:+.4f} ppb）")
    if last:
        n, resid, ppb, d = last
        log(f"  最終区間                 : {n} 秒 / 残差 {resid} ビート "
            f"= {resid * BEAT_NS:.1f} ns / {ppb:+.4f} ppb")
        log(f"  グリッチ（累積）         : trig {d['glitch_trig'] - g0[0]} "
            f"/ comp {d['glitch_comp'] - g0[1]}")
    if len(seg_best) > 1:
        log(f"  区間の数                 : {len(seg_best)}（原点が変わるたびに切れる）")
    log("")
    if events:
        log("**事象（壁時計つき。他の出来事と突き合わせるためにある）**")
        for ts, kind, msg in events:
            log(f"  [{ts}] {kind}: {msg}")
        log("")
    else:
        log("**事象なし。** 原点も flags も一度も動かなかった")
        log("")

    if last is None:
        log("**PPS が 1 発も増えなかった。** 配線か極性を疑う")
        return
    n, resid, ppb, d = last

    log("**読み方。** 45m の 1PPS と 10 MHz が同じ標準から出ているなら、")
    log("残差は積んでも増えないはず。**フラットであること自体が検証**になる。")
    log("ドリフトするなら、どちらかが思っているものと違う")
    log("（proj004: 外部基準を挿さずに CLKin0 を選ぶと +90.68 ppm ずれた。")
    log(" そのとき PLLLockStatus は 2 のまま、DMA も波形も正常だった）。")
    log("")
    log("**判定 6（proj008）の読み方。**")
    log("  原点が変わった回数が **0** なら、絶対時刻は最初の錨のまま通っている。")
    log("  1 回でもあれば、**その時点で絶対時刻は無効になっている** —— 大きさの")
    log("  問題ではなく、**秒単位でずれる**。timebase.py はこれを例外で返す。")
    log("  **要求 100 µs に対する余裕は、ホールドオーバの質で決まる**")
    log(f"  （外部 10 MHz で {abs(ppb):.4f} ppb なら "
        f"{abs(ppb) * 86400 / 1e9 * 1e6:.1f} µs/日）。")
    if d["glitch_trig"] or d["glitch_comp"]:
        log("")
        log(f"**グリッチがある（trig {d['glitch_trig']} / comp {d['glitch_comp']}）。**")
        log("  ブランキング窓（0.5 秒）の中に余分なエッジが来ている。")
        log("  波形のリンギングか、終端の不整合を疑う")


def do_pol_check(p, t_ovl, width_s):
    """極性を決める。**パルス幅が分かっていることが前提。**

    立ち上がりと立ち下がりの両方でスタンプを取り、その差を見る。
    pol=0 が真の立ち上がりなら差はパルス幅に、そうでなければ
    (1 秒 − パルス幅) になる。
    """
    p.check_magic()
    wait_ready(p, t_ovl)
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
    p.add_argument("--epoch-test", action="store_true",
                   help="**意図的に aresetn を落として epoch が増えるのを見る。**"
                        "観測中に実行しないこと")
    p.add_argument("--src-tile", type=int, default=2,
                   help="MMCM の源のタイル（build.tcl の wiz_src_tile）")
    p.add_argument("--ctl-tile", type=int, default=0,
                   help="対照に使うタイル（MMCM の源ではないほう）")
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

    if args.epoch_test:
        do_epoch_test(pps, t_ovl, args.src_tile, args.ctl_tile)
    elif args.level:
        do_level(pps)
    elif args.pol_check:
        do_pol_check(pps, t_ovl, args.width)
    elif args.watch:
        do_watch(pps, t_ovl, args.watch, args.period)
    else:
        do_probe(pps, t_ovl)


if __name__ == "__main__":
    main()

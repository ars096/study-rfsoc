#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj007 — コンパレータ経路の遅延を ADC の時間軸で測る。

**proj007 の機能で proj007 を較正する。**

1PPS を 2 分配し、片方を `PPS Clk` の SMA へ、もう片方を減衰させて ADC 入力へ入れる。
**両方を繋ぐこと。** `PPS Clk` だけでは ADC 側が無入力になり、雑音のピークを
エッジと取り違えたまま「結果」が出る（2026-09-17 に踏んだ）。
`--ch 0` は **ADC_D** の SMA（proj006 の実測表: ch0 = Tile 224 / slice 0）。
予約発火（`start_at`）で **次の PPS の少し前から** 取得を始めると、エッジが
取得窓のど真ん中に入る。ADC は 0.814 ns 刻みなので、エッジの位置が直接読める。

    PL のタイムスタンプ − ADC が見たエッジ = コンパレータ経路の遅延 ＋ ケーブル長差

使い方（ボード上）:

    sudo -E $(which python3) pps_delay.py --ch 0 --trials 10 --clkin 0 --atten-db 20

**注意が 2 つある。**

1. **バラン（MABA-011118）は 10 MHz〜10 GHz で DC 結合ではない。**
   パルスの平坦部は垂れる。だがエッジは高周波成分なので通り、微分されて
   鋭いスパイクになる — タイミング測定にはかえって好都合である。
   「方形波が方形に見えない」で慌てないこと。
2. **減衰器は入れすぎない。まず 0 dB から始める。**
   「0 dBFS ≒ +5.8 dBm なので TTL は飽和する」は**平坦部の話で、ここには効かない**。
   バランが低周波を落とすため ADC に届くのはエッジの微分だけで、その高さは
   立ち上がりの速さで決まる。2026-09-17 の実測では 2.5 V / 立ち上がり 250 ns 級の
   1PPS を 20 dB で入れたときの適否は 2026-09-17 時点で未測定である
   （このとき ADC 側に分配していなかった）。**SNR を見ながら減らす。**
   **減衰量は必ず申告する**（proj005 で決めた規約）。

分解能について正直に書いておく。PL のタイムスタンプは 1 ビート = **6.51 ns 粒度**で、
ADC 側は 0.814 ns である。すべてが同じ 10 MHz にロックしていると PPS のエッジは
ビート境界に対して毎回同じ位置に落ちるので、**この 6.51 ns の量子化誤差は
回数を増やしても平均で消えない**。分光計にとっては 9 桁小さい量なので問題にならない。
"""

import argparse
import time

import numpy as np

import adc_capture as ac
import pps as pps_mod

log = ac.log
SAMP_NS = 1e9 / ac.FS_HZ            # = 0.8138 ns


def find_edge(x, frac=0.5, center=None, half=None):
    """微分されたパルスの立ち上がり位置を返す（サンプル単位・小数）。

    **argmax をそのまま使わない。** ピークの位置は波形の形で動く。
    ピークまで遡って **振幅が frac を横切る点**を線形内挿で取る方が、
    信号源やケーブルを替えても意味が変わらない。

    **探索は予測位置の周りに限る（center / half）。**
    2026-09-17、窓全体の argmax を取っていたため、**ADC 入力に何も繋がって
    いない状態でも「測定結果」が出た。** 実測位置は 65536 サンプルの窓じゅうに
    散らばり、平均 +4716 ns / 標準偏差 13324 ns という数字まで計算された。
    1 回だけ予測の近く（−233 ns）に来たのも偶然である。
    **「値が出た」ことを測定が成立した証拠にしない。**
    雑音のピークは必ずどこかに在り、argmax は必ず何かを返す。
    期待する遅延は 45 ns 級なので、±5 µs も見れば 100 倍以上の余裕がある。
    **窓を絞ることで結果は偏らない。偏るとすれば窓が狭すぎるときだけで、
    それは「窓の端に張り付く」という分かる形で出る。**
    """
    a = np.abs(x.astype(np.float64))
    n = a.size
    if center is None or half is None:
        lo, hi = 0, n
    else:
        lo = max(0, int(center) - int(half))
        hi = min(n, int(center) + int(half) + 1)
    pk = lo + int(np.argmax(a[lo:hi]))
    th = a[pk] * frac
    i = pk
    while i > lo and a[i] > th:
        i -= 1
    if i == pk:
        return float(pk), pk, a[pk]
    # a[i] <= th < a[i+1]
    d = a[i + 1] - a[i]
    off = 0.0 if d == 0 else (th - a[i]) / d
    return i + off, pk, a[pk]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=ac.BITFILE)
    p.add_argument("--ch", type=int, default=0, choices=tuple(range(ac.NCH)),
                   help="1PPS を入れた ch（512bit 語の並び。SMA の逆順）")
    p.add_argument("--trials", type=int, default=10)
    p.add_argument("--nsamples", type=int, default=ac.MAX_BEATS * ac.SPW)
    p.add_argument("--k", type=int, default=2, help="何秒先の PPS を狙うか")
    p.add_argument("--frac", type=float, default=0.5, help="エッジ判定の振幅比")
    p.add_argument("--win-us", type=float, default=5.0,
                   help="予測位置の周り ±この時間だけを探す [us]。"
                        "期待する遅延は 45 ns 級なので既定で 100 倍以上の余裕がある")
    p.add_argument("--atten-db", type=float, default=0.0,
                   help="ADC 入力までの減衰量 [dB]。**記録のために必ず申告する**")
    p.add_argument("--pol", type=int, default=0, choices=(0, 1))
    p.add_argument("--zone", type=int, default=1, choices=(1, 2))
    p.add_argument("--fs", type=float, default=ac.FS_HZ / 1e6)
    p.add_argument("--no-clk", action="store_true",
                   help="**xrfclk を触らない。** LMK/LMX の設定は PL と独立なので、"
                        "一度 --clkin 0 で書けば以後は残る。"
                        "「クロックの位相はそのまま、Overlay だけ焼き直し」を作るため")
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--epochs", type=int, default=1,
                   help="**エポックを N 回張り直して、そのたびに測る。**"
                        "較正定数が装置の定数かエポックごとの定数かを分ける")
    p.add_argument("--src-tile", type=int, default=2,
                   help="MMCM の源のタイル（build.tcl の wiz_src_tile）。"
                        "--epochs > 1 のとき、これを止めて新しいエポックを作る")
    p.add_argument("--save", default=None, help="1 回目の波形を .npy で残す")
    args = p.parse_args()

    from pynq import Overlay
    import xrfdc                                   # noqa: F401

    if args.no_clk:
        # **小数部が「起動ごと」に引き直される原因の切り分けに使う。**
        # 起動ごとに変わるものは xrfclk の LMK/LMX 再設定（491.52 MHz の
        # 10 MHz に対する位相が引き直される）と Overlay の焼き直しの 2 つ。
        # ここを飛ばせば後者だけを変えられる。
        log("**xrfclk を触らない（--no-clk）。** 直前の --clkin 0 の設定が残っている前提")
        log("  残っていなければ基準は出荷時（内部 Si5395）のままになる。")
        log("  **判定は ppm で行う** — pps.py --watch で確かめられる")
    else:
        ac.setup_clocks(args.clkin, args.ref)
    ol = Overlay(args.bitfile)
    log(f"Overlay: {args.bitfile}")
    blocks = ac.start_tiles(ol.rfdc, args.fs * 1e6, args.zone)
    t_tiles = time.time()

    pps = pps_mod.PPS(ol)
    pps.check_magic()
    pps.set_pol(args.pol)

    # **Overlay とタイル起動を終えても、まだ PPS は 1 回も来ていない。**
    # リセット解除は Overlay の直後で、そこから start_tiles() の 177 ms しか
    # 経っていない。1 Hz なので `alive` は 0 のままである。
    # ここを通さずに next_start() を呼ぶと「PPS が来ていない」で落ちる
    # （2026-09-17 に踏んだ）。
    #
    # **当初これを「start_tiles() がリセットを起こしてエポックが 0 に戻る」と
    # 診断したが、誤りだった。** rev2 で epoch を読むと 1 のままで、
    # タイル起動はリセットを起こしていない。**対策が動くことは、
    # 診断が正しいことの証拠にならない。**
    d_ready = pps_mod.wait_ready(pps, t_tiles, label="タイル起動")
    epoch0 = d_ready["epoch"]

    n_beats = args.nsamples // ac.SPW
    offset = -(n_beats // 2)        # PPS が取得窓の真ん中に来るようにする
    log("")
    log(f"取得長 {args.nsamples} サンプル/ch = {n_beats} ビート "
        f"({args.nsamples / ac.FS_HZ * 1e6:.1f} us)")
    log(f"PPS は窓の中央（先頭から {-offset * pps_mod.BEAT_NS / 1e3:.1f} us）に来る予定")
    log(f"減衰量 {args.atten_db:.1f} dB / ch{args.ch} / pol={args.pol}")
    log("")

    def run_trials(epoch0, tag):
        """1 エポックぶんの試行。戻り値はサンプル単位の遅延のリスト。"""
        results = []
        for t in range(args.trials):
            start_at, d = pps.next_start(k=args.k, offset=offset)
            # **予測する PPS のビートは 64 bit で持つ。**start_at は下位 32 bit だけ
            pps_beat = d["stamp"] + args.k * pps_mod.BEATS_PER_SEC
            x = ac.capture(ol, args.nsamples, blocks=None, start_at=start_at, pps=pps)
            snap = pps.snapshot()
            # **試行をまたいで原点が変わっていないこと。**
            # 変わっていれば pps_beat の予測が別の原点の値になり、
            # **遅延ではなく原点の差を測ってしまう**（しかも値は出る）
            if snap["epoch"] != epoch0:
                log(f"  [{t}] **時刻の原点が変わった（epoch {epoch0} → {snap['epoch']}）。**")
                log("       この試行以降は無効。RFDC のタイルか MMCM を疑う")
                break
            if (snap["t_start"] & 0xFFFFFFFF) != start_at:
                log(f"  [{t}] **t_start が start_at と違う** "
                    f"({snap['t_start'] & 0xFFFFFFFF} != {start_at})。発火の設計が壊れている")
                continue
            if snap["flags"] & pps_mod.FLAG_LATE:
                log(f"  [{t}] late。--k を増やす")
                continue

            # PL が言う PPS の位置（取得窓の先頭からのサンプル数）
            pred = (pps_beat - snap["t_start"]) * ac.SPW
            ch = x[args.ch]
            half = int(round(args.win_us * 1e-6 * ac.FS_HZ))
            meas, pk, amp = find_edge(ch, args.frac, center=pred, half=half)
            dbfs = 20 * np.log10(max(amp, 1e-9) / 32768.0)
            # **雑音は窓の外から取る。** 信号の在る所を混ぜない。
            # MAD からガウス相当の σ に直す（外れ値に強い）
            outside = np.abs(np.concatenate([ch[:max(0, pred - half)],
                                             ch[pred + half:]]).astype(np.float64))
            noise = float(np.median(outside)) * 1.4826 if outside.size else 0.0
            snr = 20 * np.log10(max(amp, 1e-9) / max(noise, 1e-9))
            delay = meas - pred
            results.append(delay)
            flag = ""
            if amp >= 32700:
                flag = "  **飽和している。減衰器を足す**"
            elif snr < 12.0:
                flag = "  **SNR 不足。減衰器を減らす**"
            elif abs(meas - pred) > 0.9 * half:
                flag = "  **窓の端に張り付いた。--win-us を広げる**"
            log(f"  [{t:2d}] 予測 {pred:8.0f} / 実測 {meas:9.2f} サンプル  "
                f"差 {delay:+9.2f} = {delay * SAMP_NS:+9.2f} ns  "
                f"ピーク {dbfs:6.1f} dBFS / SNR {snr:5.1f} dB{flag}")
            if t == 0 and tag == 0 and args.save:
                np.save(args.save, x)
                log(f"      {args.save} に保存")
        return results

    # ---- エポックごとに測る ----
    #
    # **較正定数が装置の定数なのか、エポックごとの定数なのかを分ける。**
    # 実行内のばらつきは 0.4 ns 級しかないので、1 回の測定では絶対に見えない。
    # Overlay を焼き直すのではなく **MMCM の源のタイルを止めて新しいエポックを
    # 作る**（pps.py --epoch-test と同じ手）。こうするとビットストリームは同一の
    # まま原点だけが変わるので、**版の違いと原点の違いが混ざらない。**
    per_epoch = []
    for e in range(args.epochs):
        if args.epochs > 1:
            log(f"==== epoch {epoch0}（{e + 1} / {args.epochs}）====")
        r = run_trials(epoch0, e)
        if len(r) >= 2:
            per_epoch.append((epoch0, np.array(r)))
        else:
            log(f"  **epoch {epoch0} は試行が {len(r)} 回しか成立しなかった**")
        if e == args.epochs - 1:
            break

        # 次のエポックを作る
        log("")
        log(f"---- adc_tiles[{args.src_tile}] を止めて新しいエポックを作る ----")
        tile = ol.rfdc.adc_tiles[args.src_tile]
        tile.ShutDown()
        time.sleep(0.5)
        if pps.flags() & pps_mod.FLAG_LOCKED:
            log("  **停止中も locked が立っている。** --src-tile が違う")
            break
        tile.StartUp()
        t0 = time.time()
        while not (pps.flags() & pps_mod.FLAG_LOCKED):
            if time.time() - t0 > 10.0:
                log("  **locked が戻らない。** ここで止める")
                break
            time.sleep(0.05)
        blocks = ac.start_tiles(ol.rfdc, args.fs * 1e6, args.zone)
        d_ready = pps_mod.wait_ready(pps, time.time(), label="タイル再起動")
        epoch0 = d_ready["epoch"]
        log("")

    results = list(per_epoch[0][1]) if per_epoch else []


    log("")

    # ---- エポックをまたいだ比較（--epochs > 1 のとき）----
    if len(per_epoch) >= 2:
        log("---- エポックごとの平均 ----")
        log("  epoch   試行   平均 [ns]   実行内 σ [ns]")
        log("  " + "-" * 44)
        mus = []
        sds = []
        for ep, arr in per_epoch:
            mu = arr.mean() * SAMP_NS
            sd = arr.std() * SAMP_NS
            mus.append(mu)
            sds.append(sd)
            log(f"  {ep:>5}   {len(arr):>4}   {mu:>9.2f}   {sd:>11.2f}")
        mus = np.array(mus)
        sds = np.array(sds)
        within = float(sds.mean())
        between = float(mus.std(ddof=1))
        span = float(mus.max() - mus.min())
        log("")
        log(f"  実行内のばらつき（σ の平均）      : {within:.2f} ns")
        log(f"  エポック間のばらつき（平均の σ）  : {between:.2f} ns")
        log(f"  エポック間の幅                    : {span:.2f} ns")
        log("")
        # 各エポックの平均の標準誤差。これより十分大きければ本物
        sem = within / np.sqrt(np.mean([len(a) for _, a in per_epoch]))
        log(f"  平均の標準誤差（実行内から）      : {sem:.2f} ns")
        if between > 3 * sem:
            log("")
            log("  → **較正定数はエポックごとである。** エポック間のばらつきが")
            log("    実行内から予想される標準誤差より有意に大きい。")
            log("    `L_adc − D_pps` は装置の定数ではなく、**原点を張り直すたびに")
            log("    取り直さなければならない**。epoch はその印として使える")
        else:
            log("")
            log("  → **エポック間に有意な差は出なかった。** 較正定数は")
            log("    エポックに依らないと言える（この試行数の範囲で）。")
            log("    rev1 と rev2 で 1.52 ns 動いた件は、**ビットストリームの")
            log("    違いのほうを疑う**")
        log("")

    if len(results) < 2:
        log("**測定が成立していない。** 上のメッセージを見る")
        return
    a = np.array(results)
    if len(per_epoch) >= 2:
        log(f"（以下は epoch {per_epoch[0][0]} のぶんだけ。"
            f"エポックをまたいだ比較は上の表を見る）")
    log(f"試行 {len(a)} 回")
    log(f"遅延  平均 {a.mean() * SAMP_NS:+.2f} ns / 標準偏差 {a.std() * SAMP_NS:.2f} ns "
        f"/ 幅 {(a.max() - a.min()) * SAMP_NS:.2f} ns")
    log(f"      （サンプル単位: 平均 {a.mean():+.2f} / 標準偏差 {a.std():.2f}）")
    log("")
    log("**符号の読み方。** delay = meas − pred。")
    log("  正 = **ADC のバッファ上でエッジが PL のスタンプより後ろに現れる**。")
    log("  バッファの添字は RFDC のデータパスを通ったあとの beat に揃っているので、")
    log("  **ADC のレイテンシが効く**:")
    log("")
    log("      delay = L_adc − D_pps + (τ_ADCケーブル − τ_PPSケーブル)")
    log("")
    log("      L_adc : RFDC のデータパスのレイテンシ")
    log("      D_pps : コンパレータ＋シュミットトリガ＋同期器（2 ビート）")
    log("")
    log("  **2026-09-17、ここを逆に立てて「コンパレータ単独の遅延」だと思い込み、")
    log("  データシートの 45 ns 級と合わないと悩んだ。** ケーブルを入れ替える")
    log("  対照実験で符号が予想と逆に動いて発覚した。")
    log("  **外れた予言のほうが、当たった測定より多くを教えた。**")
    log("")
    log("  **分解する必要はない。** 「バッファの添字 i のサンプルは何時のものか」に")
    log("  答えるのに要るのは L_adc と D_pps の**差**だけである。")
    log("")
    # **整数ビートと小数部に分けて出す。**
    # 2026-09-17 の実測で、エポック間のばらつきは **ビートの整数倍**であり、
    # 小数部は 0.17 ns で揃うことが分かった。分けて出さないと、
    # 26 ns の幅が「ばらついている」としか見えない
    _m = float(a.mean())
    _frac = _m % ac.SPW
    _nb = int(round((_m - _frac) / ac.SPW))
    log(f"**整数ビートと小数部に分ける。** {_nb} ビート + {_frac:.2f} サンプル")
    log("  エポック間で動くのは **整数ビートだけ**（2026-09-17 の実測: 33/34/35/37）。")
    log("  小数部は物理的な位相で、全エポックを通じて 0.2 ns 以内に揃う。")
    log("  **未知数が整数なので、エポックあたり 1 回の測定で厳密に決まる。**")
    log("")

    log(f"**量子化の下限は 1 ビート = {pps_mod.BEAT_NS:.2f} ns。**")
    log("  すべてが同じ 10 MHz にロックしていると、この誤差は回数を増やしても消えない。")
    log("  標準偏差がこれより十分小さければ、測れているのは固定の遅延である。")
    log("")
    log("**ケーブル長差の除き方。** 2 分配器の 2 本を入れ替えてもう一度測る。")
    log("  ケーブル項だけが符号を変えるので、**2 回の和の半分**が L_adc − D_pps、")
    log("  **差の半分**がケーブル長差そのものになる。")
    log("  2026-09-17 の実測: 205.29 / 221.03 ns → 差の半分 7.87 ns（2 m ぶん）")
    log("  = 3.94 ns/m = **短縮率 0.85**。発泡ポリエチレンの同軸として妥当。")
    log(f"  **1 ns ≒ 25 cm ≒ {1.0 / SAMP_NS:.2f} サンプル**（VF 0.66 なら 20 cm）。")
    log("")
    log("**残る系統誤差はビート量子化である。** PL のスタンプはビート境界に量子化")
    log("  されるので 0〜6.51 ns の固定バイアスが乗る。**入れ替えても消えない**")
    log("  （両方に同じだけ乗るので、和の半分にも残る）。")
    log(f"  減衰量 {args.atten_db:.1f} dB と経路の構成を README に残す（proj005 の規約）")


if __name__ == "__main__":
    main()

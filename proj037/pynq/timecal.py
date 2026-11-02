#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""ADR 0023 — ボードの時刻の較正ファイル（time_cal.json）を測って作る。設置の後に、ユーザーがボードごとに 1 回

1PPS の縁を RAW の流れの生サンプルで見る測り（widef2.py、判定 F-2 の (a) と陽性対照 (p)）を、**Overlay を載せ直して --loads 回**
繰り返し、ADC ごとの M = adc_to_core − pps_det（形 (a)）の平均を較正ファイルに書く。Overlay ごとに 4 ADC がそろって
≒ 1 ビート動く件（timing.md の持ち越し）があるので、1 回でなく何回かの平均にし、そのばらつきを bound_ns に入れる。

**できたファイルはボードにだけ置く（リポジトリに戻さない）。** 既定の置き場所は timebase.TIME_CAL_PATH（/etc/yatsugatake/time_cal.json、
環境変数 YATSUGATAKE_TIME_CAL で替えられる）。鍵はボードの印（timebase.board_id()）で、別のボードでは当たらない。

**配線 P**（docs/user/calibration.md）: 1PPS を分配器で PPS Clk（入口の LPF の手前）と ADC_A〜D に。分配器から ADC までのケーブルは
同じ長さのものを使う（ケーブルの差は M にそのまま入る）。SAM45-Wide の .bit で、ボード直、root、**specd を止めてから**:

    sudo -E $(which python3) timecal.py --clkin 0 --ref 10                 # 測って書く（≒ 5 回 × 1 分）
    sudo -E $(which python3) timecal.py --from timecal-<日時>/load*.f2.json   # 測った記録から作り直す（測らない）
    python3 timecal.py --show                                               # 今の較正ファイルとこのボードの印

合格（ファイルを書く条件）: 各回が widef2 の 1 回の線（4 ADC × --n 試行とも縁・σ ≦ 0.4 ビート・(p) で縁が見えない）を通り、
ADC ごとの回の間のばらつき（最大 − 最小）≦ --max-spread（既定 2 ビート）。
bound_ns = max(5, 切り上げ(ばらつきの半分 ＋ 2 ns))。2 ns はスタンプの量子化（±0.5 ビート）の分。
"""
import argparse
import datetime
import glob
import json
import math
import os
import subprocess
import sys
import time

import timebase as TB

NS_PER_BEAT = 3.90625
HERE = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def combine(paths, max_spread=2.0):
    """widef2 の .f2.json（Overlay 1 回ずつ）→ (較正ファイルの中身 or None, 通ったか)"""
    runs = [json.load(open(p)) for p in paths]
    ids = {r.get("if_id") for r in runs}
    if len(ids) != 1 or None in ids:
        log(f"ERROR: 回によって bit が違うか、if_id の無い記録がある（{sorted(map(str, ids))}）")
        return None, False
    v = int(ids.pop(), 16)
    key = ((v >> 16) & 0xFF, (v >> 8) & 0xFF)
    ok = True
    a2c, spread, per_load = {}, {}, [{} for _ in runs]
    for adc in range(4):
        xs = [r["adc"].get(str(adc)) for r in runs]
        if any(x is None for x in xs):
            log(f"  {'ABCD'[adc]}: 測っていない回がある"); ok = False; continue
        good = [x["mean"] is not None and x["n"] == x["n_trial"] and x["std"] <= 0.4 and x["p_seen"] == 0 for x in xs]
        ms = [x["mean"] for x in xs if x["mean"] is not None]
        for i, x in enumerate(xs):
            per_load[i][str(adc)] = x["mean"]
        if not all(good) or not ms:
            log(f"  {'ABCD'[adc]}: 1 回の線を通らない回がある（{sum(good)}/{len(xs)} 回が通過）"); ok = False; continue
        d = max(ms) - min(ms)
        m = sum(ms) / len(ms)
        a2c[str(adc)] = round(m * NS_PER_BEAT, 2)
        spread[str(adc)] = round(d, 3)
        g = d <= max_spread
        ok &= g
        log(f"  {'ABCD'[adc]}: " + "・".join(f"{x:+.2f}" for x in ms) + f" ビート → M = {m:.2f} ビート = {m * NS_PER_BEAT:.1f} ns・"
            f"ばらつき {d:.2f}（≦ {max_spread}）: {'OK' if g else 'NG'}")
    if not ok:
        return None, False
    bound = max(5.0, float(math.ceil(max(spread.values()) / 2 * NS_PER_BEAT + 2.0)))
    return dict(version=TB.TIME_CAL_VERSION, kind="yatsugatake-time-cal", form="a", pps_det_ns=0.0, adc_to_core_ns=a2c, bound_ns=bound,
                adc_path=TB.adc_path_of(key), measured_on=dict(bit_kind=key[0], bit_rev=key[1], if_id=f"{v:08x}",
                                                               bitfile=runs[0].get("bitfile")),
                loads=per_load, spread_beats=spread, records=[os.path.basename(p) for p in paths],
                note=f"timecal.py、Overlay {len(runs)} 回の平均、形 (a)（pps_det 0・adc_to_core = M）"), True


def write_cal(d, path, board):
    d = dict(d, board=board, date=datetime.date.today().isoformat(), t=time.time())
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        bak = f"{path}.{time.strftime('%Y%m%d-%H%M%S')}"
        os.rename(path, bak)
        log(f"前の較正ファイルを {bak} に残した")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    TB.load_time_cal(path)                               # 書いたものが読めること
    log(f"較正ファイルを書いた: {path}（ボード {board['id']}・bound_ns {d['bound_ns']}）")


def show(path):
    b = TB.board_id()
    log(f"このボードの印: {b['id'] if b else '読めない'}{'（' + b['src'] + '）' if b else ''}")
    if not os.path.exists(path):
        log(f"較正ファイル {path} が無い（時刻の較正は暫定 = 開発の値）")
        return 1
    c = TB.load_time_cal(path)
    same = b is not None and c["board"]["id"] == b["id"]
    log(f"較正ファイル {path}: ボード {c['board']['id']}（{'このボード' if same else '別のボード'}）・{c['date']}・道 {c['adc_path']}・"
        f"bound_ns {c['bound_ns']}・M（ns）" + "・".join(f"{'ABCD'[k]} {v - c['pps_det_ns']:.1f}" for k, v in sorted(c["adc_to_core_ns"].items())))
    return 0 if same else 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default="proj023.bit", help="SAM45-Wide の .bit（RAW の流れで測る）")
    p.add_argument("--clkin", default="stock")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--lmx-pwr", type=int, default=3)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--path", default="trig", choices=("trig", "comp"))
    p.add_argument("--n", type=int, default=5, help="1 回（Overlay 1 つ）の ADC ごとの試行")
    p.add_argument("--loads", type=int, default=5, help="Overlay を載せ直す回数")
    p.add_argument("--max-spread", type=float, default=2.0, help="ADC ごとの回の間のばらつきの線 [ビート]")
    p.add_argument("--outdir", default=None, help="測りの記録の置き場所（既定 timecal-<日時>）")
    p.add_argument("--write", default=TB.time_cal_path(), help="較正ファイルの置き場所")
    p.add_argument("--dry-run", action="store_true", help="測って判定するが、較正ファイルは書かない")
    p.add_argument("--from", dest="from_", nargs="+", default=None, help="測った記録（.f2.json）から作る（測らない）")
    p.add_argument("--show", action="store_true", help="今の較正ファイルとこのボードの印を見る")
    a = p.parse_args()
    if a.show:
        sys.exit(show(a.write))
    if a.from_:
        paths = sorted(x for g in a.from_ for x in glob.glob(g))
    else:
        out = a.outdir or time.strftime("timecal-%Y%m%d-%H%M%S")
        os.makedirs(out, exist_ok=True)
        log(f"配線 P（1PPS を PPS Clk と ADC_A〜D に）で、Overlay {a.loads} 回 × ADC 4 × {a.n} 試行。記録は {out}/")
        paths = []
        for k in range(a.loads):
            o = os.path.join(out, f"load{k}")
            cmd = [sys.executable, os.path.join(HERE, "widef2.py"), "--bitfile", a.bitfile, "--clkin", a.clkin, "--ref", str(a.ref),
                   "--lmx-pwr", str(a.lmx_pwr), "--settle", str(a.settle), "--path", a.path, "--adc", "0,1,2,3", "--n", str(a.n), "--out", o]
            log(f"---- {k + 1}/{a.loads} 回目（Overlay を載せ直す）----")
            r = subprocess.run(cmd)                      # 回ごとに別のプロセス（リング・Overlay を持ち越さない）
            if r.returncode not in (0, 2) or not os.path.exists(o + ".f2.json"):
                log(f"ERROR: {k + 1} 回目の測りが止まった（終了コード {r.returncode}）。配線 P・specd が止まっているかを確かめる")
                sys.exit(1)
            paths.append(o + ".f2.json")
    if not paths:
        log("ERROR: 記録が無い"); sys.exit(1)
    log(f"{len(paths)} 回の平均")
    d, ok = combine(paths, a.max_spread)
    if not ok:
        log("結果: 失敗（較正ファイルは書かない。今の較正はそのまま）"); sys.exit(2)
    if a.dry_run:
        log(f"結果: 通過（--dry-run なので書かない）: {json.dumps(d['adc_to_core_ns'])}・bound_ns {d['bound_ns']}"); sys.exit(0)
    board = TB.board_id()
    if board is None:
        log("ERROR: このボードの印が読めない（eth0 の MAC）。較正ファイルの鍵が作れない"); sys.exit(1)
    write_cal(d, a.write, board)
    log("結果: 通過。specd を起こし直すと ID の tcal=board・GET CAL に値が出る")


if __name__ == "__main__":
    main()

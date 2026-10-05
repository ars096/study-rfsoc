#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj018 — specd の中身の確かめ（実機・SG）。s45client で繋ぎ、予言と合否を 1 つずつ出す（Jupyter で 1 セルずつ）

PL なしの試験（test_fake.sh）は運び（CRC・番号・ACK）だけを確かめ、スペクトルの中身は乱数だった。ここで実機の信号で確かめる:

  C-1 周波数軸の向き   SG の CW が予言の IF の ch に立つ（窓 0: 256 MHz・窓 1: 8 MHz）。SG を動かして、山が同じ向きに同じだけ動く
  C-2 設定が効く       8 窓に別々の幅・IF・SHIFT を入れ、記録の頭・START の EVENT・周波数軸の幅が全部その値
  C-3 ADC と窓の対応   SG を 1 本の ADC だけに入れ、山がその ADC の窓にだけ出る
  C-4 SHIFT            同じ CW の山の電力の比が 4^(S2 − S1)（±0.1 dB）、飽和 0
  C-5 時刻             ダンプの間隔が UTC で 40.96 ms ちょうど・DUMP_T で N_ACC·L ちょうど、TP の区切りが 1.024 ms ちょうど、
                       UTC がボードの時計と 1 秒以内（ボードの時計は錨の秒の元なので、桁の誤りを見るだけ）

    from s45client import S45
    import s45fcheck as F
    s = S45("<board>")
    r1 = F.c1(s, f_sg=3000.5, adc="A")       # SG 3000.5 MHz を ADC_A に
    r2 = F.c1(s, f_sg=3001.5, adc="A", ref=r1)  # SG を +1 MHz 動かしてから。r1 との差が +1 MHz
    F.c2(s); F.c3(s, f_sg=3000.5, adc="A"); F.c4(s, f_sg=3000.5, adc="A"); F.c5(s)

判定の約束（README の規約）: argmax は必ず何かを返すので、**山 / 中央値 ≧ 30 dB を先に確かめてから**位置を読む。
SG が分光計と同じ 10 MHz の基準に繋がっていなければ、周波数に ppm の誤差が乗る（許容に 2 ppm を足してある）。
"""
import time

import numpy as np

KEYS = [f"{a}{w}" for a in "ABCD" for w in "01"]
BW_OF_NS = {1: 256, 2: 128, 3: 64, 4: 32, 5: 16, 6: 8}
PEAK_MIN_DB = 30.0


def _say(ok, msg):
    print(f"  {'OK' if ok else 'NG'}  {msg}")
    return bool(ok)


def _mean_per_frame(d, key):
    sp = d.spec(key)
    return sp.mean(0) / d.meta(key)["nacc"][-1]


def _peak(d, key):
    """(山の IF, 山の値, 山 / 中央値 [dB], ch の幅 [MHz])。山は 3 点の放物線で ch の間を補う"""
    y = _mean_per_frame(d, key)
    f = d.freq(key)
    i = int(np.argmax(y))
    med = float(np.median(y))
    snr = 10 * np.log10(y[i] / med) if med > 0 else np.inf
    df = f[1] - f[0]
    fi = f[i]
    if 0 < i < len(y) - 1 and y[i - 1] > 0 and y[i + 1] > 0:
        a, b, c = np.log(y[i - 1]), np.log(y[i]), np.log(y[i + 1])
        den = a - 2 * b + c
        if den < 0:
            fi = f[i] + 0.5 * (a - c) / den * df
    return float(fi), float(y[i]), float(snr), float(df)


def _set_adc_windows(s, adc, if0, if1, bw0=256, bw1=8, shift=9):
    a = adc.upper()
    s.set(**{f"{a}0_if": if0, f"{a}0_bw": bw0, f"{a}0_shift": shift, f"{a}1_if": if1, f"{a}1_bw": bw1, f"{a}1_shift": shift})


def _health(d, keys):
    ok = True
    for k in keys:
        m = d.meta(k)
        h = int(np.bitwise_or.reduce(m["health"])) if len(m) else 0
        sat = int(m["sat"].sum()) if len(m) else 0
        if h or sat:
            ok = _say(False, f"{k}: 健全性 {h:#x}・飽和 {sat}") and ok
    return ok


# ---------------------------------------------------------------- C-1
def c1(s, f_sg, adc="A", ref=None, n=10, off0=37.3, off1=1.1):
    """SG の CW（f_sg MHz）を ADC adc に入れて呼ぶ。窓 0 = 256 MHz（中心 f_sg + off0）・窓 1 = 8 MHz（中心 f_sg + off1）に置き、
    山の IF が f_sg に一致すること。ref = 前の c1 の戻り値（SG を動かした後）なら、山の動きが SG の動きと同じ向き・同じ量"""
    a = adc.upper()
    print(f"C-1 周波数軸: SG {f_sg} MHz → ADC_{a}。窓 {a}0 = 256 MHz（中心 {f_sg + off0}）・{a}1 = 8 MHz（中心 {f_sg + off1}）")
    _set_adc_windows(s, a, f_sg + off0, f_sg + off1)
    d = s.acquire(n)
    out = dict(f_sg=f_sg, peaks={}, snr={})
    ok = _health(d, [a + "0", a + "1"])
    for w in "01":
        k = a + w
        fp, _, snr, df = _peak(d, k)
        out["peaks"][k] = fp
        out["snr"][k] = snr
        if not _say(snr >= PEAK_MIN_DB, f"{k}: 山 / 中央値 {snr:.1f} dB（≧ {PEAK_MIN_DB} で信号が来ている）"):
            ok = False
            continue
        tol = 1.5 * abs(df) + 2e-6 * f_sg
        ok = _say(abs(fp - f_sg) <= tol, f"{k}: 山の IF {fp:.5f} MHz・予言 {f_sg} MHz・差 {(fp - f_sg) * 1e3:+.2f} kHz"
                  f"（許容 ±{tol * 1e3:.1f} kHz = 1.5 ch ＋ 2 ppm、ch {abs(df) * 1e3:.3f} kHz）") and ok
    if ref is not None:
        dsg = f_sg - ref["f_sg"]
        for k, fp in out["peaks"].items():
            if k in ref["peaks"]:
                if min(out["snr"][k], ref["snr"][k]) < PEAK_MIN_DB:
                    ok = _say(False, f"{k}: どちらかの回に信号が無い（山 / 中央値 < {PEAK_MIN_DB} dB）ので、山の動きは比べられない")
                    continue
                dm = fp - ref["peaks"][k]
                df = 256 / 4096 if k.endswith("0") else 8 / 4096
                ok = _say(np.sign(dm) == np.sign(dsg) and abs(dm - dsg) <= 1.5 * df + 4e-6 * f_sg,
                          f"{k}: SG の動き {dsg * 1e3:+.2f} kHz → 山の動き {dm * 1e3:+.2f} kHz（同じ向き・同じ量のはず）") and ok
    print(f"C-1: {'通過' if ok else '失敗'}")
    out["ok"] = ok
    return out


# ---------------------------------------------------------------- C-2
def c2(s, n=5):
    """8 窓に別々の設定（幅 6 通り ＋ 2・IF・SHIFT 8〜11）を入れ、記録の頭・START の EVENT・周波数軸が全部その値"""
    print("C-2 設定が効く: 8 窓に別々の幅・IF・SHIFT")
    bws = [256, 128, 64, 32, 16, 8, 256, 8]
    want = {}
    kw = {}
    for j, k in enumerate(KEYS):
        ifc = 2600.0 + 97.0 * j + 0.3
        sh = 8 + j % 4
        want[k] = dict(bw=bws[j], if_mhz=ifc, shift=sh)
        kw.update({f"{k}_bw": bws[j], f"{k}_if": ifc, f"{k}_shift": sh})
    s.set(**kw)
    g = s.get()
    d = s.acquire(n)
    st = [e for e in d.events if e.get("ev") == "START"]
    ok = _say(len(st) == 1, f"START の EVENT {len(st)} 個")
    ev = {w["key"]: w for w in st[-1]["wins"]} if st else {}
    tint = float(g["tint"])
    for k in KEYS:
        w = want[k]
        m = d.meta(k)
        if not len(m):
            ok = _say(False, f"{k}: 記録が無い"); continue
        ns = int(m["ns"][-1]); bw = BW_OF_NS.get(ns)
        L = 4096 << (ns - 1)
        nacc_p = int(round(tint * 256e6 / L))
        f = d.freq(k)
        span = f.max() - f.min()
        e = ev.get(k, {})
        good = (bw == w["bw"] and int(m["shift"][-1]) == w["shift"] and abs(m["if_mhz"][-1] - w["if_mhz"]) <= w["bw"] / 4096
                and int(m["nacc"][-1]) == nacc_p and abs(span - w["bw"] * 4095 / 4096) < 1e-6
                and e.get("ns") == ns and e.get("shift") == w["shift"] and e.get("nacc") == nacc_p
                and g[f"{k}.bw"] == w["bw"] and g[f"{k}.shift"] == w["shift"])
        ok = _say(good, f"{k}: 幅 {bw}（{w['bw']}）・SHIFT {int(m['shift'][-1])}（{w['shift']}）・IF {m['if_mhz'][-1]:.4f}（{w['if_mhz']}）・"
                  f"N_ACC {int(m['nacc'][-1])}（{nacc_p}）・周波数軸の幅 {span:.4f} MHz・EVENT ns {e.get('ns')} shift {e.get('shift')}") and ok
    s.set(**{f"{k}_shift": 9 for k in KEYS})
    print(f"C-2: {'通過' if ok else '失敗'}（SHIFT は 9 に戻した。幅・IF はそのまま）")
    return ok


# ---------------------------------------------------------------- C-3
def c3(s, f_sg, adc="A", n=10, leak_max_db=10.0):
    """SG の CW を ADC adc の 1 本だけに入れて呼ぶ。8 窓とも f_sg を含む位置に置き、山がその ADC の窓にだけ出る"""
    a = adc.upper()
    print(f"C-3 ADC と窓の対応: SG {f_sg} MHz を ADC_{a} だけに。8 窓とも f_sg を含む位置に")
    kw = {}
    for k in KEYS:
        kw.update({f"{k}_if": f_sg + (37.3 if k.endswith("0") else 1.1), f"{k}_bw": 256 if k.endswith("0") else 8, f"{k}_shift": 9})
    s.set(**kw)
    d = s.acquire(n)
    ok = True
    for k in KEYS:
        _, _, snr, _ = _peak(d, k)
        if k[0] == a:
            ok = _say(snr >= PEAK_MIN_DB, f"{k}: 山 / 中央値 {snr:.1f} dB（入れた ADC。≧ {PEAK_MIN_DB}）") and ok
        else:
            ok = _say(snr <= leak_max_db, f"{k}: 山 / 中央値 {snr:.1f} dB（入れていない ADC。≦ {leak_max_db}、雑音の山だけのはず）") and ok
    print(f"C-3: {'通過' if ok else '失敗'}")
    return ok


# ---------------------------------------------------------------- C-4
def c4(s, f_sg, adc="A", s1=9, s2=11, n=25, tol_db=0.1):
    """同じ CW を SHIFT s1 と s2 で取り、山の電力の比が 4^(s2 − s1)。山の ch は前後 1 ch まで足して（ch の間の CW でも比は同じ）"""
    a = adc.upper()
    print(f"C-4 SHIFT: SG {f_sg} MHz → ADC_{a}、SHIFT {s1} と {s2}。予言: 比 {4 ** (s2 - s1)}（{10 * np.log10(4.0 ** (s2 - s1)):.2f} dB）")
    _set_adc_windows(s, a, f_sg + 37.3, f_sg + 1.1, shift=s1)
    res = {}
    ok = True
    for sh in (s1, s2, s1):                  # s1 を 2 回: SG の揺らぎの見積もり（1 回目と 3 回目の差）
        s.set(**{f"{a}0_shift": sh, f"{a}1_shift": sh})
        d = s.acquire(n)
        ok = _health(d, [a + "0", a + "1"]) and ok
        for w in "01":
            k = a + w
            y = _mean_per_frame(d, k)
            i = int(np.argmax(y))
            snr = 10 * np.log10(y[i] / np.median(y))
            if snr < PEAK_MIN_DB:
                ok = _say(False, f"{k}（SHIFT {sh}）: 山 / 中央値 {snr:.1f} dB。信号が来ていないので比は読まない")
            res.setdefault(k, []).append(float(y[max(0, i - 1):i + 2].sum()))
    for k, (p1, p2, p1b) in res.items():
        r = 10 * np.log10(p1 / p2)
        pred = 10 * np.log10(4.0 ** (s2 - s1))
        drift = 10 * np.log10(p1b / p1)
        ok = _say(abs(r - pred) <= tol_db + abs(drift), f"{k}: SHIFT {s1}/{s2} の山の比 {r:.3f} dB・予言 {pred:.3f} dB・差 {r - pred:+.3f} dB"
                  f"（許容 ±{tol_db} ＋ SG の揺らぎ {abs(drift):.3f} dB）") and ok
    s.set(**{f"{a}0_shift": 9, f"{a}1_shift": 9})
    print(f"C-4: {'通過' if ok else '失敗'}（SHIFT は 9 に戻した）")
    return ok


# ---------------------------------------------------------------- C-5
def c5(s, n=50):
    """時刻: ダンプの間隔（UTC・DUMP_T）、TP の区切り、UTC とボードの時計"""
    print(f"C-5 時刻: {n} ダンプ")
    g = s.get()
    tint = float(g["tint"])
    d = s.acquire(n)
    t_host = time.time()
    ok = True
    for k in KEYS:
        m = d.meta(k)
        if len(m) < 2:
            ok = _say(False, f"{k}: 記録が {len(m)} 個"); continue
        L = 4096 << (int(m["ns"][-1]) - 1)
        du = np.diff(m["utc_ns"]); dtb = np.diff(m["dump_t"]); dk = np.diff(m["k"])
        good = np.all(dk == 1) and np.all(dtb == int(m["nacc"][-1]) * L) and np.all(du == int(round(tint * 1e9)))
        ok = _say(good, f"{k}: DUMP_K の間隔 {set(dk.tolist())}・DUMP_T の間隔 {set(dtb.tolist())}（{int(m['nacc'][-1]) * L}）・"
                  f"UTC の間隔 {set(du.tolist())} ns（{int(round(tint * 1e9))}）") and ok
    m = d.meta("A0")
    lag = t_host - (m["utc_ns"][-1] / 1e9 + tint)
    ok = _say(m["utc_ns"][-1] > 0 and -1.0 < lag < 5.0, f"A0 の最後のダンプの終わりの UTC と、受けた後のボードの時計の差 {lag:+.3f} s（0〜数秒のはず）") and ok
    for i, a in enumerate("ABCD"):
        e = d.tp(a)
        if len(e) < 2:
            ok = _say(False, f"TP {a}: {len(e)} 区切り"); continue
        dt_ = np.diff(e["t_beat"]); du = np.diff(e["utc_ns"])
        ok = _say(np.all(dt_ == 262144) and np.all(du == 1_024_000), f"TP {a}: {len(e)} 区切り、間隔 {set(dt_.tolist())} ビート・"
                  f"{set(du.tolist())} ns（262144・1024000）") and ok
    print(f"C-5: {'通過' if ok else '失敗'}")
    return ok

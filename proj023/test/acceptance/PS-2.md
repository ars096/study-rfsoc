# PS-2 — specd の 10 分の運転（欠け・CRC・1 周の重さ）

- **前提**: 共通の前提。specd（ボードで `python3 specd.py --clkin 0 --ref 10 --bits bits.json`、制御 PC から）。配線 N（PATT 13 dB で固定）
- **手順**:

```bash
python3 specctl.py --host $B "SET A0.bw=256 A1.bw=8 all.shift=9" "START n=0" "SEND ON"
python3 specrecv.py --host $B --out ps2.s45 --seconds 600 --json ps2.json
python3 specctl.py --host $B STATUS STOP
```

- **合格**（測る前に決めた条件）:
  - 受け側: CRC・欠け・説明のない欠け・dup・kgap・tdev・tp_gap 0、照合 通過
  - STATUS: miss・bdrop・r_bad・pl_drop・pl_crc・tp_lost・tp_rec_lost 0、loop_slow 0、**loop_p99_ms ≦ 11.5**（TP の跳ねの見張り込み）
  - tp_ovr 0・tp_dbfs ≒ −12.5
  - tp_jump は**数を記録するだけ**（合格の条件にしない。入力の安定さに依る。2026-10-14 に測った後で外した: 10 分で 4 ADC 計 43 回の跳ねが、B2b の前の見張りで読み直しても 40 回中 37 回同じ個に出て、入力の山と分かった）
- **陽性対照**: なし（跳ねの見張りの陽性対照は [PS-3](PS-3.md)）
- **記録**: **最終の bit・B2b の後の PS で通過（2026-10-14、`ps2`）**: SPEC 118,841・欠け・CRC 0、miss・pl_drop・pl_crc・tp_lost 0、loop_p99 11.0 ms・loop_slow 0・tp_ovr 0、tp_jump 8,14,6,15（入力の山、proj021 README「最終の bit で未だった判定を回す」）

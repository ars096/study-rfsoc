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
  - tp_ovr 0・tp_jump 0,0,0,0・tp_dbfs ≒ −12.5
- **陽性対照**: なし（跳ねの見張りの陽性対照は [PS-3](PS-3.md)）
- **記録**: proj021 README「手順 2-5 → 実機（S25-3）」の specrecv 10 分（2026-10-14 通過、B2 の前の PS）と「B2 → 実機 3 回目」（10 分、p99 13.2 ms は B2b の前）。**B2b の後の PS で 10 分は未**（2 分で p99 11.5 ms）

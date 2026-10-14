# S — specd の SNAP（RAW の流れの生サンプル。S-1〜S-4）

- **前提**: 共通の前提。specd（ボードで `python3 specd.py --clkin 0 --ref 10 --bits bits.json`、制御 PC から）。配線 N
- **手順**:

```bash
python3 s45snap.py --host $B --adc ABCD --n 16 --every 20 --out snap_xxx
```

- **合格**（測る前に決めた条件）:
  - 4 ADC とも道具の判定が OK: 16 塊、S-1 間隔（dump_t の差）、S-2 中身（下位 2 bit が 0・振り切れ 0・dBFS ≒ −12.5）、S-4 UTC の刻み 20 ms
  - 受けた記録の照合: CRC・欠け 0
- **陽性対照**: S-3（`--sg` に SG の周波数、配線 S）で SG の山が予言の周波数に出る（任意）
- **記録**: proj021 README「手順 2-5 → 実機（S25-3）」の SNAP の行（2026-10-14 通過: −12.4〜−12.6 dBFS・振り切れ 0）

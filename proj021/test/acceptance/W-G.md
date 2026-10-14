# W-G — 窓のスペクトル = スナップショット（PFB の出口）の numpy FFT

- **前提**: 共通の前提。ボード直（root、specd を止めてから）。配線 N
- **手順**:

```bash
python3 window.py --clkin 0 --ref 10 --golden --w 256
python3 window.py --clkin 0 --ref 10 --golden --w 8
```

- **合格**（測る前に決めた条件）:
  - 道具の許容（量子化から出す）を超えた ch 0（4,096 ch）
  - スナップショットのフレーム SNAP_F = ダンプの DUMP_F0
- **陽性対照**: なし
- **記録**: proj021 README「手順 2-5 → 実機（S25-3）」の P-2 の行（2026-10-14 通過、W 256: 最悪の差 1.4 / 許容 2.9）。W 8 は 2-2d（最悪 1.4 / 許容 2.4）

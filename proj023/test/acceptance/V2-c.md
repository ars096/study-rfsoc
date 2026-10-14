# V2-c — W-G をレコードの道（REC_CTRL の ONE | SNAP）で

- **前提**: 共通の前提。ボード直（root、specd を止めてから）。配線 N
- **手順**:

```bash
python3 plring.py --clkin 0 --ref 10 --golden
```

- **合格**（測る前に決めた条件）:
  - 8 窓とも SHIFT 7 で、道具の許容を超えた ch 0
  - RAW の流れは飛ばす（スペクトルが無い）
  - REC_CNT が出したレコードの数・DROP 0
- **陽性対照**: なし（[W-G](W-G.md) と同じ比べ）
- **記録**: proj021 README「手順 2-5 → 実機（S25-3）」の V2-c の行（2026-10-14 通過: 最悪の差 1.3〜1.4、REC_CNT 17・DROP 0）

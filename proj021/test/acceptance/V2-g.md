# V2-g — リングの溢れとキャッシュ（陽性対照）・soak

- **前提**: 共通の前提。ボード直（root、specd を止めてから）。配線 N
- **手順**:

```bash
python3 plring.py --clkin 0 --ref 10 --soak 60
python3 plring.py --clkin 0 --ref 10 --soak 20 --pause 3     # 陽性対照: 溢れ
python3 plring.py --clkin 0 --ref 10 --soak 20 --no-inval    # 陽性対照: キャッシュ
```

- **合格**（測る前に決めた条件）:
  - `--soak 60`: 13 流れ（DDC 8・RAW・TP 4）で SEQ の飛び 0・DROP_CNT 0・REC_LATE 0・CRC・尾の不一致 0、PEAK ≦ 5 %
  - `--pause 3`: **SEQ の飛び = DROP_CNT > 0**、CRC の不一致 0
  - `--no-inval`: CRC の不一致（または古い行）> 0
- **陽性対照**: 上の 2 つ（`--pause`・`--no-inval`）がこの判定の陽性対照
- **記録**: soak は proj021 README「手順 2-5 → 実機（S25-3）」の `plring --soak 60` の行（2026-10-14 通過、PEAK 0.9 %）。**陽性対照 2 つは最終の bit で未**（2-2a の bit で通過、2026-10-10: 飛び 2,211 = DROP 2,211）

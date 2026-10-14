# V2-f — 5.1 の見張り（DUMP_T − m·BASE が一定）を DDC 8 本で

- **前提**: 共通の前提。ボード直（root、specd を止めてから）。配線 N
- **手順**:

```bash
python3 s45v2f.py --clkin 0 --ref 10            # 60 s × 2 RUN
python3 s45v2f.py --clkin 0 --ref 10            # もう一度（Overlay・SRST からやり直す）
python3 s45v2f.py --clkin 0 --ref 10 --posctl   # 陽性対照
```

- **合格**（測る前に決めた条件）:
  - DDC 8 本（NS 1〜8）の r − G = 138 / 188 / 277 / 450 / 788 / 1454 / 2776 / 5410 ビート、2 回の RUN と Overlay のやり直しで同じ
  - RAW は DUMP_T の間隔のずれ 0・SEQ の飛び 0（5.1 の見張りには入れない）
- **陽性対照**: `--posctl`: 1 回目の RUN の途中で A0 を tint の格子 ＋ G で RUN し直すと、A0 だけ r_bad 1・束ねを止めた
- **記録**: proj021 README「手順 2-5 → 実機（S25-3）」の V2-f の行（2026-10-14 通過、2 回）。陽性対照は 2-4 の bit（2026-10-13、S24-3）

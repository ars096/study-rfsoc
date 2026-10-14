# V2-e — TP のレコード = AXI4-Lite の TP のリング（bit 単位）

- **前提**: 共通の前提。ボード直（root、specd を止めてから）。配線 N
- **手順**:

```bash
python3 plring.py --clkin 0 --ref 10 --tpcompare
```

- **合格**（測る前に決めた条件）:
  - 4 ADC とも TP のレコード ≒ 300 個、AXI4-Lite の TP のリングと照らせた個 ≧ 500、**不一致 0**
  - SEQ の飛び 0、DUMP_T の式（ANCH_T からの式）の外れ 0
- **陽性対照**: なし
- **記録**: **最終の bit で通過（2026-10-14）**: 4 ADC ともレコード 304 個・照らした個 509〜511・不一致 0・SEQ の飛び 0・DUMP_T の式の外れ 0・CRC 0、REC_CNT 1,216・DROP 0。2-2d の bit でも同じ値（2026-10-13）

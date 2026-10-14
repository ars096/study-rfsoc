# V2-d — LOAD で proj020 ↔ proj021 を往復し、錨・道具が切り替わる

- **前提**: 共通の前提。specd（ボードで `python3 specd.py --clkin 0 --ref 10 --bits bits.json`、制御 PC から）。配線 N。ボードに proj020 の道具一式（bit・hwh・pynq）があり、`bits.json` に proj020・proj021 の 2 項目
- **手順**:

```bash
python3 specrecv.py --host $B --out v2d.s45 --seconds 300 --json v2d.json &
python3 specctl.py --host $B BITS ID "SEND ON"
python3 specctl.py --host $B "LOAD bit=proj020" ID STATUS "START n=50"
sleep 5
python3 specctl.py --host $B "LOAD bit=proj021" ID STATUS "START n=50"
wait
```

- **合格**（測る前に決めた条件）:
  - LOAD 1 回 ≦ 30 s
  - proj020 のとき: ID が win_id 00200100・adc_id 0020a100・time_id 00207101、time_ok=1、記録は版 1
  - proj021 に戻ったとき: ID が win_id 02030000・adc_id 02020301・time_id 02020302、time_ok=1、STATUS に pl_*（pl_drop・pl_crc 0）、START の EVENT に proto 2・fmt f32・read ring
  - どの START も STOP は「n に達した」・8 窓 × 50・miss 0、TP の anch_dev 0・gap 0
  - 受け側: SPEC 800（2 回 × 8 窓 × 50）・版 1 と 2 が両方、CRC・欠け・説明のない欠け・dup・kgap・tdev・tp_gap 0、照合 通過
- **陽性対照**: なし（受け側に版 1・2 の両方が出ること自体が、道具が切り替わった証拠）
- **記録**: **最終の bit で未**。2-3d の bit で通過（2026-10-13、LOAD 17.4〜20.8 s）

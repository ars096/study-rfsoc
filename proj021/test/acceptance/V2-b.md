# V2-b — 10.24 ms で 30 分（欠け・CRC・PS の負荷）

- **前提**: 共通の前提。specd（ボードで `python3 specd.py --clkin 0 --ref 10 --bits bits.json`、制御 PC から）。配線 N。**終わったら必ず STOP**（RUN のまま残すと specd の溜まりが溢れる）
- **手順**:

```bash
python3 specctl.py --host $B "SET tint=0.01024 fmt=f32 A0.bw=256 A1.bw=8 all.shift=9" "START n=0" "SEND ON"
python3 specrecv.py --host $B --out v2b.s45 --seconds 1800 --json v2b.json
python3 specctl.py --host $B STATUS STOP
```

- **合格**（測る前に決めた条件）:
  - 受け側: SPEC ≒ 8 × 175,800（1,800 s / 10.24 ms）、**CRC・欠け・説明のない欠け・kgap・tdev・tp_gap 0**、記録は全部 版 2、照合 通過
  - STATUS: miss・bdrop・r_bad・pl_drop・pl_crc・tp_lost・tp_rec_lost 0。loop_slow（1 周が tint を越えた回数）は数えるだけ: tint 10.24 ms では毎周越えるのが普通で、まとめて読んで追いつけばよい（取りこぼしは miss・kgap・tdev で見る）
  - STATUS の行を必ず残す（2-3b・2-3c では残っていなかった）
- **陽性対照**: specd を `--posctl-ring-stall 8` で起こし、40 s 受ける: kgap 8（8 窓 × 1 回）・EVENT BDROP・tdev 0（2-3b の S23b-4）
- **記録**: **最終の bit で未**。2-3c の bit で通過（2026-10-13、SPEC 1,411,586・22.4 GB、欠け 0。1 周 15.4〜17.3 ms で 2 tint ぶんずつ読んで追いつく）

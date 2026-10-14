# PS-3 — TP の跳ねの見張り（EVENT TP_JUMP・step_db）

- **前提**: 共通の前提。specd（ボードで `python3 specd.py --clkin 0 --ref 10 --bits bits.json`、制御 PC から）。配線 N（プログラムアッテネータを使う）。PC での試験 `python3 test_tpjump.py`・`bash test_fake.sh tpjump` が通っていること
- **手順**:

```bash
python3 specrecv.py --host $B --out ps3.s45 --seconds 120 --json ps3.json | tee ps3.log &
python3 specctl.py --host $B "SEND ON" "START n=0"
sleep 40
python3 -c "from instr import Atten; a = Atten(); a.set(14.0); print('PATT', a.get())"
sleep 40
python3 -c "from instr import Atten; a = Atten(); a.set(13.0); print('PATT', a.get())"
sleep 30; python3 specctl.py --host $B STATUS STOP; wait
grep TP_JUMP ps3.log
```

- **合格**（測る前に決めた条件）:
  - 4 ADC とも跳ね 2 回（PATT を 14 dB にした時・13 dB に戻した時）、STATUS の tp_jump 2,2,2,2
  - **step_db −0.94 / +0.94 ± 0.03**（アッテネータの 1 dB の段の実際の値 0.945）、ovr false、n 400〜700
  - `db`（ずれの最大）は PATT の切り替えの瞬断で −46〜−49 dB（J7211C の性質。≒ 3 ms 入力が途切れる）
  - PATT 固定の運転では跳ね 0（[PS-2](PS-2.md)）
- **陽性対照**: この判定そのもの（入れた段差が出る）。PATT 固定で 0 が負の側
- **記録**: proj021 README「B2 → B2b の実機」（2026-10-14 通過、`rb8`: step_db −0.938〜−0.940 / +0.9386〜+0.9398）

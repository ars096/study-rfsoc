#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj018 — PL なし（specd.py --fake）での通信・溜まり・照合の試験と陽性対照。どこの Linux でも回る（numpy だけ）
#   bash test_fake.sh all          # 全部（≒ 2 分）
#   bash test_fake.sh basic|corrupt|gap|drop|skip|reconnect|stall
# 判定は各試験の最後の「判定: OK / NG」。全部の終わりに「test_fake: 全部通過」
cd "$(dirname "$0")"
OUT=${OUT:-/tmp/s45test}; mkdir -p "$OUT"
PORTC=${PORTC:-51100}; PORTD=${PORTD:-51101}
NG=0

srv() {   # srv <名前> <specd の追加の引数...>
  python3 specd.py --fake --cpu -1 --rt 0 --ctrl-port $PORTC --data-port $PORTD "${@:2}" > "$OUT/$1.specd.log" 2>&1 &
  SP=$!
  for i in $(seq 50); do python3 -c "import socket; socket.create_connection(('127.0.0.1', $PORTC)).close()" 2>/dev/null && return; sleep 0.1; done
  echo "サーバーが起動しない"; cat "$OUT/$1.specd.log"; exit 1
}
ctl() { python3 specctl.py --port $PORTC "$@"; }
rcv() { python3 specrecv.py --port $PORTD --report 0 "$@"; }
js() { python3 -c "import json,sys; print(json.load(open('$1'))['summary']['$2'])"; }
stop_srv() { kill -TERM $SP 2>/dev/null; wait $SP 2>/dev/null; }
judge() { if [ "$1" = 1 ]; then echo "判定: OK  $2"; else echo "判定: NG  $2"; NG=$((NG+1)); fi; }

t_basic() {   # 100 ダンプ × 8 窓を全部受け、CRC・番号・DUMP_K・DUMP_T・TP の連続が通る
  echo "== basic"; srv basic
  ctl "SET A0.bw=128 B1.bw=32 all.shift=9" "START n=100" "SEND ON" > /dev/null
  rcv --seconds 7 --json "$OUT/basic.json" > "$OUT/basic.recv.log"
  local s=$(js "$OUT/basic.json" spec) u=$(js "$OUT/basic.json" unexplained) c=$(js "$OUT/basic.json" crc_bad)
  stop_srv
  judge $([ "$s" = 800 ] && [ "$u" = 0 ] && [ "$c" = 0 ] && grep -q "照合: 通過" "$OUT/basic.recv.log" && echo 1) "SPEC $s（期待 800）・説明のない欠け $u・CRC 不一致 $c"
}
t_corrupt() { # 陽性対照: seq が 50 の倍数の記録を CRC の後に 1 bit 反転 → 受け側の CRC 不一致が 50 個ごとに 1 つ
  echo "== corrupt（陽性対照）"; srv corrupt --posctl-corrupt 50
  ctl "START n=100" "SEND ON" > /dev/null
  rcv --seconds 7 --json "$OUT/corrupt.json" > "$OUT/corrupt.recv.log"
  local c=$(js "$OUT/corrupt.json" crc_bad) last=$(js "$OUT/corrupt.json" last_seq)
  stop_srv
  judge $([ "$c" = $((last / 50)) ] && [ "$c" -gt 0 ] && echo 1) "CRC 不一致 $c（期待 $((last / 50))）"
}
t_gap() {     # 陽性対照: seq が 50 の倍数の記録を黙って捨てる → 説明のない欠けが同じ数
  echo "== gap（陽性対照）"; srv gap --posctl-gap 50
  ctl "START n=100" "SEND ON" > /dev/null
  rcv --seconds 7 --json "$OUT/gap.json" > "$OUT/gap.recv.log"
  local u=$(js "$OUT/gap.json" unexplained) last=$(js "$OUT/gap.json" last_seq)
  stop_srv
  judge $([ "$u" = $((last / 50)) ] && [ "$u" -gt 0 ] && grep -q "照合: 失敗" "$OUT/gap.recv.log" && echo 1) "説明のない欠け $u（期待 $((last / 50))）・照合は失敗のはず"
}
t_drop() {    # P-4: 溜まり 4 MiB（≒ 0.5 秒ぶん）で 5 秒送らない → 溢れた分は DROP。欠け = DROP の範囲、説明のない欠け 0
  echo "== drop（P-4）"; srv drop --buf-mb 4
  ctl "START n=150" > /dev/null; sleep 5
  ctl "SEND ON" > /dev/null
  rcv --seconds 6 --json "$OUT/drop.json" > "$OUT/drop.recv.log"
  local g=$(js "$OUT/drop.json" gaps) d=$(js "$OUT/drop.json" declared) u=$(js "$OUT/drop.json" unexplained)
  local sd=$(ctl STATUS | tr ' ' '\n' | grep '^drop=' | cut -d= -f2)
  stop_srv
  judge $([ "$g" -gt 0 ] && [ "$g" = "$d" ] && [ "$u" = 0 ] && [ "$g" = "$sd" ] && echo 1) "欠け $g・DROP の範囲 $d・説明のない欠け $u・サーバーの drop $sd"
}
t_skip() {    # SEND ON from=now: 溜まっていた分は SKIP（seq 0 の EVENT）で範囲を言ってから捨てる
  echo "== skip"; srv skip
  ctl "START n=150" > /dev/null; sleep 2
  ctl "SEND ON from=now" > /dev/null
  rcv --seconds 6 --json "$OUT/skip.json" > "$OUT/skip.recv.log"
  local u=$(js "$OUT/skip.json" unexplained) ev=$(grep -c '"ev": "SKIP"' "$OUT/skip.recv.log")
  stop_srv
  judge $([ "$u" = 0 ] && [ "$ev" = 1 ] && echo 1) "SKIP の EVENT $ev・説明のない欠け $u（受け側は SKIP の後から繋いだので欠けとしては見えない）"
}
t_reconnect() { # P-5 と受け側の切断: 受け側を 2 回に分けて繋ぎ、2 回目は記録の頭から続く。制御は毎回つなぎ直している
  echo "== reconnect（P-5）"; srv reconnect
  ctl "START n=150" "SEND ON" > /dev/null
  rcv --seconds 2.5 --out "$OUT/re.s45" > /dev/null; rm -f "$OUT/re.s45"
  rcv --seconds 2.5 --out "$OUT/re.s45" > /dev/null; sleep 0.5
  rcv --seconds 4 --out "$OUT/re2.s45" > /dev/null
  cat "$OUT/re.s45" "$OUT/re2.s45" > "$OUT/re_all.s45"; rm -f "$OUT/re.s45" "$OUT/re2.s45"
  ctl STATUS > "$OUT/reconnect.status"
  stop_srv
  local ok=0
  # 2 回目と 3 回目の受けを続けたファイルは、間に欠けが無い（1 回目の受けの後ろ、切った時に送りかけた記録も送り直される）
  python3 specrecv.py --file "$OUT/re_all.s45" --json "$OUT/reconnect.json" > "$OUT/reconnect.recv.log" && ok=1
  local g=$(js "$OUT/reconnect.json" gaps)
  judge $([ $ok = 1 ] && [ "$g" = 0 ] && grep -q "state=IDLE" "$OUT/reconnect.status" && echo 1) "2 回に分けた受けを続けて照合: 欠け $g・照合 $([ $ok = 1 ] && echo 通過 || echo 失敗)"
}
t_stall() {   # 陽性対照（取得の側）: 窓 A0 の読み出しを 50 ms 止める → サーバーの miss と受け側の DUMP_K の飛びが立つ
  echo "== stall（陽性対照）"; srv stall --fake-stall 20
  ctl "START n=100" "SEND ON" > /dev/null
  rcv --seconds 7 --json "$OUT/stall.json" > "$OUT/stall.recv.log"
  local kg=$(js "$OUT/stall.json" kgap) miss=$(ctl STATUS | tr ' ' '\n' | grep '^miss=' | cut -d= -f2)
  stop_srv
  judge $([ "$kg" -gt 0 ] && [ "$miss" -gt 0 ] && echo 1) "受け側の DUMP_K の飛び $kg・サーバーの miss $miss（どちらも > 0 のはず）"
}

case "${1:-all}" in
  all) t_basic; t_corrupt; t_gap; t_drop; t_skip; t_reconnect; t_stall ;;
  *) "t_$1" ;;
esac
if [ $NG = 0 ]; then echo "test_fake: 全部通過"; else echo "test_fake: NG $NG 件"; exit 1; fi

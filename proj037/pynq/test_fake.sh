#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj018 — PL なし（specd.py --fake）での通信・溜まり・照合の試験と陽性対照。どこの Linux でも回る（numpy だけ）
#   bash test_fake.sh all          # 全部（≒ 2 分）
#   FAST=--fast bash test_fake.sh all   # proj029: 2G の SPEC の記録を C で
#   bash test_fake.sh basic|corrupt|gap|drop|skip|reconnect|stall|shm|net …（t_ の後の名前）
# 判定は各試験の最後の「判定: OK / NG」。全部の終わりに「test_fake: 全部通過」
cd "$(dirname "$0")"
OUT=${OUT:-/tmp/s45test}; mkdir -p "$OUT"
PORTC=${PORTC:-51100}; PORTD=${PORTD:-51101}
NG=0
FAST=${FAST:-}    # proj029 1: FAST=--fast bash test_fake.sh で、2G の SPEC の記録を C の道（s45fast）で通す

srv() {   # srv <名前> <specd の追加の引数...>
  python3 specd.py --fake --cpu -1 --rt 0 --ctrl-port $PORTC --data-port $PORTD $FAST "${@:2}" > "$OUT/$1.specd.log" 2>&1 &
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

t_f32() {     # proj021 2-3c: fmt=both（同じ束を u64 と float32 で）→ 組 800、float32 = 最も近い丸め、差 ≦ 0.5 ulp。v2 の記録だけ
  echo "== f32（s45proto v2）"; srv f32
  ctl "SET fmt=both" "START n=100" "SEND ON" > /dev/null
  rcv --seconds 7 --json "$OUT/f32.json" > "$OUT/f32.recv.log"
  local p=$(js "$OUT/f32.json" f32_pairs) b=$(js "$OUT/f32.json" f32_bad) e=$(js "$OUT/f32.json" f32_maxulp) v=$(js "$OUT/f32.json" ver) k=$(js "$OUT/f32.json" kgap)
  stop_srv
  judge $([ "$p" = 800 ] && [ "$b" = 0 ] && [ "$k" = 0 ] && python3 -c "import sys; sys.exit(0 if float('$e') <= 0.5 else 1)" && grep -q "照合: 通過" "$OUT/f32.recv.log" && echo 1) \
    "組 $p（期待 800）・不一致 $b・最大 $e ulp・DUMP_K の飛び $k・版 $v"
}
t_f32p() {    # 陽性対照: float32 を 0 へ切り捨て → 組ごとに不一致（f32_bad = 組の数）
  echo "== f32p（陽性対照）"; srv f32p --posctl-f32-trunc
  ctl "SET fmt=both" "START n=50" "SEND ON" > /dev/null
  rcv --seconds 5 --json "$OUT/f32p.json" > "$OUT/f32p.recv.log"
  local p=$(js "$OUT/f32p.json" f32_pairs) b=$(js "$OUT/f32p.json" f32_bad)
  stop_srv
  judge $([ "$p" -gt 0 ] && [ "$b" = "$p" ] && grep -q "照合: 失敗" "$OUT/f32p.recv.log" && echo 1) "組 $p・不一致 $b（全部であるべき）"
}
t_v1() {      # proj021 2-3c: --proto 1（今までの v1）でも basic と同じに通る
  echo "== v1（--proto 1）"; srv v1 --proto 1
  ctl "START n=100" "SEND ON" > /dev/null
  rcv --seconds 7 --json "$OUT/v1.json" > "$OUT/v1.recv.log"
  local s=$(js "$OUT/v1.json" spec) v=$(js "$OUT/v1.json" ver)
  stop_srv
  judge $([ "$s" = 800 ] && grep -q "照合: 通過" "$OUT/v1.recv.log" && echo 1) "SPEC $s（期待 800）・版 $v"
}

t_load() {    # proj021 2-3d: LOAD で bit を往復。受けは切らずに続け、番号は続く・説明のない欠け 0・EVENT LOAD 2・bad は元に戻る
  # 往復の相手の道具は LOAD_PEER（例: study-rfsoc の proj020/pynq = s45proto 版 1）。無ければ同じ sw/pynq を別の名前で（版 2 だけ）
  echo "== load（2-3d）"
  local B="$OUT/bits"; mkdir -p "$B"; echo p21 > "$B/p21.bit"; echo peer > "$B/peer.bit"
  local peer="$PWD" want="2"
  if [ -n "$LOAD_PEER" ]; then peer="$(cd "$LOAD_PEER" && pwd)" || { judge 0 "LOAD_PEER $LOAD_PEER が無い"; return; }; want="1 2"; fi
  printf '{"default": "proj021", "bits": {"proj021": {"bit": "p21.bit", "pydir": "%s"}, "peer": {"bit": "peer.bit", "pydir": "%s"}, "bad": {"bit": "peer.bit", "pydir": "/nonexistent"}}}' \
    "$PWD" "$peer" > "$B/bits.json"
  srv load --bits "$B/bits.json" --boot-timeout 30
  ctl "START n=20" "SEND ON" > /dev/null
  rcv --seconds 14 --json "$OUT/load.json" > "$OUT/load.recv.log" &
  local R=$!
  sleep 3; ctl "LOAD bit=peer" "START n=10" > "$OUT/load.ctl1"
  sleep 2; ctl "LOAD bit=bad" > "$OUT/load.ctl2"
  ctl "LOAD bit=proj021" "START n=10" > "$OUT/load.ctl3"
  wait $R
  stop_srv
  local s=$(js "$OUT/load.json" spec) u=$(js "$OUT/load.json" unexplained) d=$(js "$OUT/load.json" dup) v=$(js "$OUT/load.json" ver)
  local ev=$(grep -c '"ev": "LOAD"' "$OUT/load.recv.log")
  judge $([ "$s" = 320 ] && [ "$u" = 0 ] && [ "$d" = 0 ] && [ "$ev" = 2 ] && grep -q "ERR LOAD bad" "$OUT/load.ctl2" && grep -q "OK bit=peer" "$OUT/load.ctl1" \
          && python3 -c "import sys; v=$v; sys.exit(0 if all(v.get(k) for k in '$want'.split()) else 1)" && echo 1 || echo 0) \
    "SPEC $s（期待 320）・説明のない欠け $u・送り直しとみなした記録 $d・EVENT LOAD $ev・版 $v（求める版: $want$([ -z "$LOAD_PEER" ] && echo '。LOAD_PEER なし: 版をまたぐ往復は見ていない')）・bad は元に戻る"
}

t_tpjump() {  # proj021 B2: TP の跳ねの見張り。tpjump の単体試験 ＋ 偽物の TP の 500 個ごとに +0.21 dB → STATUS の tp_jump・EVENT TP_JUMP = 入れた数。入れなければ 0
  echo "== tpjump（B2）"
  python3 test_tpjump.py > "$OUT/tpjump.unit.log"; local u=$?
  tail -1 "$OUT/tpjump.unit.log"
  srv tpjump --posctl-tp-jump 500
  ctl "START n=100" "SEND ON" > /dev/null
  rcv --seconds 7 --json "$OUT/tpjump.json" > "$OUT/tpjump.recv.log"
  local st=$(ctl STATUS)
  stop_srv
  local tj=$(echo "$st" | tr ' ' '\n' | grep '^tp_jump=' | cut -d= -f2) tp=$(echo "$st" | tr ' ' '\n' | grep '^tp=' | cut -d= -f2)
  local want=$(python3 -c "print(','.join(str((int(x) - 1) // 500) for x in '$tp'.split(',')))")
  local nev=$(grep -c '"ev": "TP_JUMP"' "$OUT/tpjump.recv.log")
  local wsum=$(python3 -c "print(sum(int(x) for x in '$want'.split(',')))")
  srv tpjump0
  ctl "START n=50" "SEND ON" > /dev/null
  rcv --seconds 5 --json "$OUT/tpjump0.json" > "$OUT/tpjump0.recv.log"
  local tj0=$(ctl STATUS | tr ' ' '\n' | grep '^tp_jump=' | cut -d= -f2)
  stop_srv
  judge $([ $u = 0 ] && [ "$tj" = "$want" ] && [ "$nev" = "$wsum" ] && [ "$tj0" = "0,0,0,0" ] && echo 1) \
    "単体 $([ $u = 0 ] && echo 通過 || echo 失敗)・tp_jump $tj（期待 $want、TP $tp）・EVENT TP_JUMP $nev（期待 $wsum）・入れないとき $tj0"
}

t_idle() {    # proj021: 何も受けていない受けを 15 s 置いても specd が切らない（ACK の待ちの時間切れで切っていた。V2-d の NG）
  echo "== idle"; srv idle
  ctl "SEND ON" > /dev/null
  rcv --seconds 25 --json "$OUT/idle.json" > "$OUT/idle.recv.log" &
  local rp=$!
  sleep 15
  ctl "START n=20" > /dev/null
  wait $rp
  local s=$(js "$OUT/idle.json" spec) drop=$(ctl STATUS | tr ' ' '\n' | grep '^data_drop=' | cut -d= -f2)
  stop_srv
  judge $([ "$s" = 160 ] && grep -q "照合: 通過" "$OUT/idle.recv.log" && echo 1 || echo 0) "15 s 待った後の START n=20: SPEC $s（期待 160）・data_drop $drop"
}

t_wide() {    # proj023: Wide（--wide、SLICE の流れ）。C は B 4 で流れ 1 が空 → 7 本 × 30 ダンプ。kind 2・log2 B・IF の軸・DUMP_T の進み 2048·nacc
  echo "== wide"; rm -f "$OUT/wide.s45"; srv wide --wide
  ctl "SET tint=0.04096 A.b=1 B.b=2 C.b=4 D.b=1 B0.s0=1000 B1.s0=4096 C0.s0=0 D1.s0=12288 all.shift=7 fmt=both" "GET" "START n=30" "SEND ON" > "$OUT/wide.ctl.log"
  rcv --seconds 6 --out "$OUT/wide.s45" --json "$OUT/wide.json" > "$OUT/wide.recv.log"
  local s=$(js "$OUT/wide.json" spec) fp=$(js "$OUT/wide.json" f32_pairs) fb=$(js "$OUT/wide.json" f32_bad)
  stop_srv
  local ax=$(python3 - "$OUT/wide.s45" <<'EOF'
import sys, numpy as np, s45proto as P, s45acq as A
f = open(sys.argv[1], "rb").read(); o = 0; seen = {}; ng = 0
while o < len(f):
    rt, pl, crc, seq = P.parse_header(f[o:o + 24]); ver = P.header_ver(f[o:o + 24])
    d = P.decode(rt, f[o + 24:o + 24 + pl], ver); o += 24 + pl
    if rt != P.T_SPEC or d["fmt"] != P.FMT_F32:
        continue
    key = f"{'ABCD'[d['core']]}{d['s']}"
    want = dict(A0=(1, 0), A1=(1, 4096), B0=(2, 1000), B1=(2, 4096), C0=(4, 0), D0=(1, 0), D1=(1, 12288))[key]
    b, s0 = want
    ifx = d["if_mhz"] + (np.arange(4096) - 2047) * d["df_hz"] / 1e6        # 受け側の式（s45client.freq）
    ref = A.w_if_mhz(s0, 4095 - np.arange(4096), b)                        # 送る i ↔ 流れの ch 4095 − i
    ng += (d["kind"] != 2 or d["ns"] != {1: 0, 2: 1, 4: 2}[b] or d["nch"] != 4096 or float(np.max(np.abs(ifx - ref))) > 1e-6
           or not np.all(np.diff(ifx) > 0) or d["nacc"] != 5120)
    seen[key] = seen.get(key, 0) + 1
print(f"{len(seen)}:{ng}")
EOF
)
  judge $([ "$s" = 420 ] && [ "$fp" = 210 ] && [ "$fb" = 0 ] && [ "$ax" = "7:0" ] && grep -q "照合: 通過" "$OUT/wide.recv.log" && grep -q "C1.b=4" "$OUT/wide.ctl.log" && echo 1 || echo 0) \
    "SPEC $s（期待 420 = 7 本 × 30 × u64・f32）・組 $fp・不一致 $fb・流れ:軸の NG $ax（期待 7:0）"
}
t_widep() {   # proj023 陽性対照: B 4 の流れ 1（空）に s0 を書くのは拒まない（使わない）が、B 2 で s0 が範囲の外なら SET が ERR
  echo "== widep（陽性対照）"; srv widep --wide
  local r1=$(ctl "SET B.b=2 B0.s0=12288") r2=$(ctl "SET A0.b=3") r3=$(ctl "SET A.s0=5")
  stop_srv
  judge $(echo "$r1" | grep -q "^ERR" && echo "$r2" | grep -q "^ERR" && echo "$r3" | grep -q "^ERR" && echo 1 || echo 0) "範囲の外の s0・B 3・コアの s0 が ERR（$r1 / $r2 / $r3）"
}

t_widesnap() {  # proj023 4g: Wide の SNAP（IDLE で ADC_B を 4 個）→ SNAP 4・EVENT SNAP / SNAP_END。陽性対照: RUN の間の SNAP は ERR STATE
  echo "== widesnap"; srv widesnap --wide
  local r1=$(ctl "SNAP adc=B n=4 every=20") r2=$(ctl "START n=0" "SNAP adc=A n=1" "STOP")
  ctl "SEND ON" > /dev/null
  rcv --seconds 4 --json "$OUT/widesnap.json" > "$OUT/widesnap.recv.log"
  local sn=$(js "$OUT/widesnap.json" snap)
  stop_srv
  judge $([ "$sn" = 4 ] && echo "$r1" | grep -q "^OK n=4" && echo "$r2" | grep -q "ERR STATE" && grep -q "SNAP_END" "$OUT/widesnap.recv.log" && echo 1 || echo 0) \
    "SNAP $sn（期待 4）・応答 $(echo $r1 | tr '\n' ' ')・RUN の間の SNAP $(echo "$r2" | grep -o 'ERR STATE' | head -1)"
}

t_widekind() {    # SAM45-Wide の M5: bits.json の項目の "kind": "wide" だけで Wide の取得が起きる（--wide なし）。
  # 陽性対照: kind の無い項目へ LOAD すると Fine の取得に戻り、Wide の SET のキー（A.b）が ERR になる
  echo "== widekind"
  local B="$OUT/bitsk"; mkdir -p "$B"; echo w > "$B/w.bit"; echo f > "$B/f.bit"
  printf '{"default": "w", "bits": {"w": {"bit": "w.bit", "pydir": "%s", "kind": "wide"}, "f": {"bit": "f.bit", "pydir": "%s"}}}' \
    "$PWD" "$PWD" > "$B/bits.json"
  srv widekind --bits "$B/bits.json" --boot-timeout 30
  local r1=$(ctl "SET A.b=2 B0.s0=1000" "GET")
  local r2=$(ctl "LOAD bit=f" "SET A.b=2")
  local r3=$(ctl "SET A0.bw=128")
  stop_srv
  judge $(echo "$r1" | grep -q "^OK" && echo "$r1" | grep -q "A0.b=2" && echo "$r2" | grep -q "ERR" && echo "$r3" | grep -q "^OK" && echo 1 || echo 0) \
    "kind wide: $(echo "$r1" | grep -o 'A0.b=[0-9]*' | head -1)（期待 A0.b=2）・kind なしへ LOAD した後の A.b: $(echo "$r2" | grep -o 'ERR[^>]*' | head -1 | cut -c1-40)・A0.bw: $(echo "$r3" | grep -o '^OK' | head -1)"
}

t_shm() {     # 既知の制限 3: 送信が時間切れで抜けた後に specd を止めても、溜まり（/dev/shm/psm_*）を残さない（参照が残って close が BufferError → unlink に届かなかった）
  echo "== shm"
  local before=$(ls /dev/shm | grep '^psm_' | sort)
  srv shm --send-timeout 2
  local mine=$(comm -13 <(echo "$before") <(ls /dev/shm | grep '^psm_' | sort))
  ctl "START n=0" "SEND ON" > /dev/null
  # 読まない受け手: つないだまま黙る → specd の sendall が時間切れの OSError で抜ける
  python3 -c "import socket,time; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096); s.connect(('127.0.0.1', $PORTD)); time.sleep(5)"
  local to=$(grep -c '送れない' "$OUT/shm.specd.log")
  stop_srv
  local left=0; [ -n "$mine" ] && [ -e "/dev/shm/$mine" ] && left=1
  [ -n "$mine" ] && rm -f "/dev/shm/$mine"
  judge $([ -n "$mine" ] && [ "$to" -ge 1 ] && [ $left = 0 ] && echo 1 || echo 0) "溜まり ${mine:-（見つからない）}・送信の時間切れ $to 回・止めた後に $([ $left = 1 ] && echo 残った || echo 消えた)"
}

t_g21() {     # proj024 3c: 2G-1（--g21、FULL の流れ A0 の 1 本・131072 ch）。kind 1・nch・src・IF の軸・DUMP_T の進み 16384·nacc・TP の欄は src と A だけ
  echo "== g21"; rm -f "$OUT/g21.s45"; srv g21 --g21
  ctl "SET tint=0.04096 src=C shift=7 fmt=both" "GET" "START n=30" "SEND ON" > "$OUT/g21.ctl.log"
  rcv --seconds 6 --out "$OUT/g21.s45" --json "$OUT/g21.json" > "$OUT/g21.recv.log"
  local s=$(js "$OUT/g21.json" spec) fp=$(js "$OUT/g21.json" f32_pairs) fb=$(js "$OUT/g21.json" f32_bad)
  stop_srv
  local ax=$(python3 - "$OUT/g21.s45" <<'EOF'
import sys, numpy as np, s45proto as P, s45acq as A
from s45client import if_axis
f = open(sys.argv[1], "rb").read(); o = 0; n = ng = ngp = 0; tps = set()
for _ in range(10**6):
    if o >= len(f):
        break
    rt, pl, crc, seq = P.parse_header(f[o:o + 24]); ver = P.header_ver(f[o:o + 24])
    d = P.decode(rt, f[o + 24:o + 24 + pl], ver); o += 24 + pl
    if rt == P.T_TP:
        tps.add(d["adc"])
    if rt != P.T_SPEC or d["fmt"] != P.FMT_F32:
        continue
    i = np.arange(131072)
    ifx = if_axis(d)                                                     # 受け側の式（s45client.if_axis）
    ref = A.g_if_mhz(131071 - i)                                         # 送る i ↔ ch 131071 − i
    ng += (d["kind"] != 1 or d["ns"] != 0 or d["nch"] != 131072 or d["core"] != 0 or d["s"] != 0 or d["src"] != 2 or d["nacc"] != 640
           or d["df_hz"] != 15625.0 or d["bit_kind"] != 11 or d["data"].size != 131072
           or float(np.max(np.abs(ifx - ref))) > 1e-6 or not np.all(np.diff(ifx) > 0))
    ngp += float(np.max(np.abs(ifx - A.g_if_mhz(131072 - i)))) > 1e-6  # 陽性対照: 1 ch ずらした軸 → 全部 NG のはず
    n += 1
print(f"{n}:{ng}:{ngp}:{''.join('ABCD'[a] for a in sorted(tps))}")
EOF
)
  judge $([ "$s" = 60 ] && [ "$fp" = 30 ] && [ "$fb" = 0 ] && [ "$ax" = "30:0:30:AC" ] && grep -q "照合: 通過" "$OUT/g21.recv.log" && grep -q "src=C" "$OUT/g21.ctl.log" && grep -q "shift=7" "$OUT/g21.ctl.log" && echo 1 || echo 0) \
    "SPEC $s（期待 60 = 30 × u64・f32）・組 $fp・不一致 $fb・f32 の数:NG:陽性対照の NG:TP の ADC $ax（期待 30:0:30:AC）"
}
t_g21p() {    # proj024 3c 陽性対照: 範囲の外の src・SHIFT、A0 以外の流れ、BASE の倍数でない tint は ERR
  echo "== g21p（陽性対照）"; srv g21p --g21
  local r1=$(ctl "SET src=E") r2=$(ctl "SET shift=16") r3=$(ctl "SET A1.shift=7") r4=$(ctl "SET tint=0.03") r5=$(ctl "SET src=B shift=3" "GET")
  stop_srv
  judge $(echo "$r1" | grep -q "^ERR" && echo "$r2" | grep -q "^ERR" && echo "$r3" | grep -q "^ERR" && echo "$r4" | grep -q "^ERR" \
          && echo "$r5" | grep -q "src=B" && echo "$r5" | grep -q "shift=3" && echo 1 || echo 0) "src=E・shift=16・A1.shift・tint=0.03 が ERR、src=B shift=3 は通る（$(echo $r1 | tr -d "\n") / $(echo $r3 | tr -d "\n")）"
}

t_g21cli() {  # proj024 3c: 受け側の s45client で 2G-1 の偽物から acquire(20)。A0 だけを数えて時間切れにならない・手元の溜めは 15 個（keep 500 × 4096 / 131072）・軸は 131072 個の昇順
  echo "== g21cli"; srv g21cli --g21
  local r=$(timeout 40 python3 - $PORTC $PORTD <<'EOF'
import sys, numpy as np
from s45client import S45
s = S45("127.0.0.1", ctrl_port=int(sys.argv[1]), data_port=int(sys.argv[2]))
try:
    d = s.acquire(20, src="B")
    sp, f = d.spec("A0"), d.freq("A0")
    c = s.check()
    print(f"{sp.shape[0]}:{sp.shape[1]}:{f.size}:{int(np.all(np.diff(f) > 0))}:{c['unexplained']}:{c['crc_bad']}")
finally:
    s.close()
EOF
)
  stop_srv
  judge $([ "$r" = "15:131072:131072:1:0:0" ] && echo 1 || echo 0) "手元のダンプ:ch:軸:昇順:説明のない欠け:CRC $r（期待 15:131072:131072:1:0:0）"
}

g22_check() {   # g22_check <記録> <期待の src0> <期待の src1>: f32 の数:NG:陽性対照の NG:TP の ADC:窓ごとの数
  python3 - "$1" "$2" "$3" <<'EOF'
import sys, numpy as np, s45proto as P, s45acq as A
from s45client import if_axis
f = open(sys.argv[1], "rb").read(); o = 0; n = ng = ngp = 0; tps = set(); per = {0: 0, 1: 0}
want = {0: int(sys.argv[2]), 1: int(sys.argv[3])}
i = np.arange(65536)
ref = A.g2_if_mhz(65535 - i)                                             # 送る i ↔ ch 65535 − i
for _ in range(10**6):
    if o >= len(f):
        break
    rt, pl, crc, seq = P.parse_header(f[o:o + 24]); ver = P.header_ver(f[o:o + 24])
    d = P.decode(rt, f[o + 24:o + 24 + pl], ver); o += 24 + pl
    if rt == P.T_TP:
        tps.add(d["adc"])
    if rt != P.T_SPEC or d["fmt"] != P.FMT_F32:
        continue
    ifx = if_axis(d)
    c = d["core"]
    ng += (c not in (0, 1) or d["kind"] != 1 or d["ns"] != 0 or d["nch"] != 65536 or d["s"] != 0 or d["src"] != want.get(c, -1)
           or d["nacc"] != 1280 or d["df_hz"] != 31250.0 or d["bit_kind"] != 10 or d["data"].size != 65536
           or float(np.max(np.abs(ifx - ref))) > 1e-6 or not np.all(np.diff(ifx) > 0))
    ngp += float(np.max(np.abs(ifx - A.g2_if_mhz(65536 - i)))) > 1e-6  # 陽性対照: 1 ch ずらした軸 → 全部 NG のはず
    per[c] = per.get(c, 0) + 1; n += 1
print(f"{n}:{ng}:{ngp}:{''.join('ABCD'[a] for a in sorted(tps))}:{per[0]}/{per[1]}")
EOF
}
t_g22() {     # proj025 3c: 2G-2（--g22、FULL の流れ A0・B0 の 2 本・65536 ch）。core・src・nch・IF の軸・DUMP_T の進み 8192·nacc・TP の欄は FULL の C・D ＋ コアの A・B
  echo "== g22"; rm -f "$OUT/g22.s45"; srv g22 --g22
  ctl "SET tint=0.04096 A0.src=C B0.src=D shift=7 fmt=both" "GET" "START n=30" "SEND ON" > "$OUT/g22.ctl.log"
  rcv --seconds 6 --out "$OUT/g22.s45" --json "$OUT/g22.json" > "$OUT/g22.recv.log"
  local s=$(js "$OUT/g22.json" spec) fp=$(js "$OUT/g22.json" f32_pairs) fb=$(js "$OUT/g22.json" f32_bad)
  stop_srv
  local ax=$(g22_check "$OUT/g22.s45" 2 3)
  judge $([ "$s" = 120 ] && [ "$fp" = 60 ] && [ "$fb" = 0 ] && [ "$ax" = "60:0:60:ABCD:30/30" ] && grep -q "照合: 通過" "$OUT/g22.recv.log" \
          && grep -q "A0.src=C" "$OUT/g22.ctl.log" && grep -q "B0.src=D" "$OUT/g22.ctl.log" && grep -q "B0.shift=7" "$OUT/g22.ctl.log" && echo 1 || echo 0) \
    "SPEC $s（期待 120 = 30 × 2 窓 × u64・f32）・組 $fp・不一致 $fb・f32 の数:NG:陽性対照の NG:TP の ADC:A0/B0 $ax（期待 60:0:60:ABCD:30/30）"
}
t_g22same() { # proj025 3c: E-4 の偽物版。2 コアに同じ ADC（B）→ 2 窓とも src 1、TP の欄は B（コア 0 の FULL）と A（コア 0 のコアの TP）の 2 本
  echo "== g22same"; rm -f "$OUT/g22same.s45"; srv g22same --g22
  ctl "SET A0.src=B B0.src=B fmt=f32" "START n=20" "SEND ON" > "$OUT/g22same.ctl.log"
  rcv --seconds 5 --out "$OUT/g22same.s45" --json "$OUT/g22same.json" > "$OUT/g22same.recv.log"
  stop_srv
  local ax=$(g22_check "$OUT/g22same.s45" 1 1)
  judge $([ "$ax" = "40:0:40:AB:20/20" ] && grep -q "照合: 通過" "$OUT/g22same.recv.log" && echo 1 || echo 0) "f32 の数:NG:陽性対照の NG:TP の ADC:A0/B0 $ax（期待 40:0:40:AB:20/20）"
}
t_g22p() {    # proj025 3c 陽性対照: 範囲の外の src・SHIFT、流れの無い窓（A1・C0）、窓なしの src、BASE の倍数でない tint は ERR。同じ ADC は通る
  echo "== g22p（陽性対照）"; srv g22p --g22
  local r1=$(ctl "SET A0.src=E") r2=$(ctl "SET shift=16") r3=$(ctl "SET A1.shift=7") r4=$(ctl "SET C0.src=A") r5=$(ctl "SET src=B") r6=$(ctl "SET tint=0.03") \
        r7=$(ctl "SET A0.src=B B0.src=B A0.shift=3" "GET")
  stop_srv
  local e=0; for r in "$r1" "$r2" "$r3" "$r4" "$r5" "$r6"; do echo "$r" | grep -q "ERR" && e=$((e+1)); done
  judge $([ $e = 6 ] && echo "$r7" | grep -q "A0.src=B" && echo "$r7" | grep -q "B0.src=B" && echo "$r7" | grep -q "A0.shift=3" && echo "$r7" | grep -q "B0.shift=7" && echo 1 || echo 0) \
    "ERR $e 個（期待 6: A0.src=E・shift=16・A1.shift・C0.src・src・tint=0.03）、A0.src=B B0.src=B A0.shift=3 は通る（$(echo $r5 | tr -d "\n")）"
}
t_g22cli() {  # proj025 3c: 受け側の s45client で 2G-2 の偽物から acquire(40)。A0・B0 の 2 窓を数えて時間切れにならない・手元の溜めは 31 個（keep 500 × 4096 / 65536）・軸は 65536 個の昇順
  echo "== g22cli"; srv g22cli --g22
  local r=$(timeout 60 python3 - $PORTC $PORTD <<'EOF'
import sys, numpy as np
from s45client import S45
s = S45("127.0.0.1", ctrl_port=int(sys.argv[1]), data_port=int(sys.argv[2]))
try:
    d = s.acquire(40, **{"A0.src": "C", "B0.src": "A"})
    out = []
    for k in ("A0", "B0"):
        sp, f = d.spec(k), d.freq(k)
        out.append(f"{sp.shape[0]}:{sp.shape[1]}:{f.size}:{int(np.all(np.diff(f) > 0))}")
    c = s.check()
    print("/".join(out) + f":{c['unexplained']}:{c['crc_bad']}")
finally:
    s.close()
EOF
)
  stop_srv
  judge $([ "$r" = "31:65536:65536:1/31:65536:65536:1:0:0" ] && echo 1 || echo 0) "A0 / B0 の 手元のダンプ:ch:軸:昇順、説明のない欠け:CRC $r（期待 31:65536:65536:1/31:65536:65536:1:0:0）"
}

g24_check() {   # proj027 3c: g24_check <記録> <期待の src0〜3（"3210" のように）>: f32 の数:NG:陽性対照の NG:TP の ADC:窓ごとの数
  python3 - "$1" "$2" <<'EOF'
import sys, numpy as np, s45proto as P, s45acq as A
from s45client import if_axis
G = A.G4_GEOM
f = open(sys.argv[1], "rb").read(); o = 0; n = ng = ngp = 0; tps = set(); per = {c: 0 for c in range(4)}
want = {c: int(x) for c, x in enumerate(sys.argv[2])}
i = np.arange(32768)
ref = G.if_mhz(32767 - i)                                               # 送る i ↔ ch 32767 − i
for _ in range(10**6):
    if o >= len(f):
        break
    rt, pl, crc, seq = P.parse_header(f[o:o + 24]); ver = P.header_ver(f[o:o + 24])
    d = P.decode(rt, f[o + 24:o + 24 + pl], ver); o += 24 + pl
    if rt == P.T_TP:
        tps.add(d["adc"])
    if rt != P.T_SPEC or d["fmt"] != P.FMT_F32:
        continue
    ifx = if_axis(d)
    c = d["core"]
    ng += (c not in range(4) or d["kind"] != 1 or d["ns"] != 0 or d["nch"] != 32768 or d["s"] != 0 or d["src"] != want.get(c, -1)
           or d["nacc"] != 2560 or d["df_hz"] != 62500.0 or d["bit_kind"] != 3 or d["data"].size != 32768
           or float(np.max(np.abs(ifx - ref))) > 1e-6 or not np.all(np.diff(ifx) > 0))
    ngp += float(np.max(np.abs(ifx - G.if_mhz(32768 - i)))) > 1e-6     # 陽性対照: 1 ch ずらした軸 → 全部 NG のはず
    per[c] = per.get(c, 0) + 1; n += 1
print(f"{n}:{ng}:{ngp}:{''.join('ABCD'[a] for a in sorted(tps))}:{'/'.join(str(per[c]) for c in range(4))}")
EOF
}
t_g24() {     # proj027 3c: 2G-4（--g24、FULL の流れ A0〜D0 の 4 本・32768 ch）。core・src・nch・IF の軸・nacc 640·n_sum・TP の欄は FULL の 4 本
  echo "== g24"; rm -f "$OUT/g24.s45"; srv g24 --g24
  ctl "SET tint=0.04096 A0.src=D B0.src=C C0.src=B D0.src=A shift=7 fmt=both" "GET" "START n=30" "SEND ON" > "$OUT/g24.ctl.log"
  rcv --seconds 8 --out "$OUT/g24.s45" --json "$OUT/g24.json" > "$OUT/g24.recv.log"
  local s=$(js "$OUT/g24.json" spec) fp=$(js "$OUT/g24.json" f32_pairs) fb=$(js "$OUT/g24.json" f32_bad)
  stop_srv
  local ax=$(g24_check "$OUT/g24.s45" 3210)
  judge $([ "$s" = 240 ] && [ "$fp" = 120 ] && [ "$fb" = 0 ] && [ "$ax" = "120:0:120:ABCD:30/30/30/30" ] && grep -q "照合: 通過" "$OUT/g24.recv.log" \
          && grep -q "A0.src=D" "$OUT/g24.ctl.log" && grep -q "D0.src=A" "$OUT/g24.ctl.log" && grep -q "D0.shift=7" "$OUT/g24.ctl.log" && echo 1 || echo 0) \
    "SPEC $s（期待 240 = 30 × 4 窓 × u64・f32）・組 $fp・不一致 $fb・f32 の数:NG:陽性対照の NG:TP の ADC:A0/B0/C0/D0 $ax（期待 120:0:120:ABCD:30/30/30/30）"
}
t_g24same() { # proj027 3c: 4 コアに同じ ADC（B）→ 4 窓とも src 1、TP の欄は B（コア 0 の FULL）と A・C・D（コア 0・2・3 のコアの TP）
  echo "== g24same"; rm -f "$OUT/g24same.s45"; srv g24same --g24
  ctl "SET A0.src=B B0.src=B C0.src=B D0.src=B fmt=f32" "START n=20" "SEND ON" > "$OUT/g24same.ctl.log"
  rcv --seconds 6 --out "$OUT/g24same.s45" --json "$OUT/g24same.json" > "$OUT/g24same.recv.log"
  stop_srv
  local ax=$(g24_check "$OUT/g24same.s45" 1111)
  judge $([ "$ax" = "80:0:80:ABCD:20/20/20/20" ] && grep -q "照合: 通過" "$OUT/g24same.recv.log" && echo 1 || echo 0) "f32 の数:NG:陽性対照の NG:TP の ADC:A0/B0/C0/D0 $ax（期待 80:0:80:ABCD:20/20/20/20）"
}
t_g24p() {    # proj027 3c 陽性対照: 範囲の外の src・SHIFT、流れの無い窓（A1・E0）、窓なしの src、BASE の倍数でない tint は ERR。同じ ADC は通る
  echo "== g24p（陽性対照）"; srv g24p --g24
  local r1=$(ctl "SET A0.src=E") r2=$(ctl "SET shift=16") r3=$(ctl "SET A1.shift=7") r4=$(ctl "SET E0.src=A") r5=$(ctl "SET src=B") r6=$(ctl "SET tint=0.03") \
        r7=$(ctl "SET A0.src=B D0.src=B C0.shift=3" "GET")
  stop_srv
  local e=0; for r in "$r1" "$r2" "$r3" "$r4" "$r5" "$r6"; do echo "$r" | grep -q "ERR" && e=$((e+1)); done
  judge $([ $e = 6 ] && echo "$r7" | grep -q "A0.src=B" && echo "$r7" | grep -q "D0.src=B" && echo "$r7" | grep -q "C0.shift=3" && echo "$r7" | grep -q "D0.shift=7" && echo 1 || echo 0) \
    "ERR $e 個（期待 6: A0.src=E・shift=16・A1.shift・E0.src・src・tint=0.03）、A0.src=B D0.src=B C0.shift=3 は通る（$(echo $r5 | tr -d "\n")）"
}
t_g24cli() {  # proj027 3c: 受け側の s45client で 2G-4 の偽物から acquire(80)。A0〜D0 の 4 窓を数えて時間切れにならない・手元の溜めは 62 個（keep 500 × 4096 / 32768）・軸は 32768 個の昇順
  echo "== g24cli"; srv g24cli --g24
  local r=$(timeout 90 python3 - $PORTC $PORTD <<'EOF'
import sys, numpy as np
from s45client import S45
s = S45("127.0.0.1", ctrl_port=int(sys.argv[1]), data_port=int(sys.argv[2]))
try:
    d = s.acquire(80, **{"A0.src": "C", "B0.src": "A", "C0.src": "D", "D0.src": "B"})
    out = []
    for k in ("A0", "B0", "C0", "D0"):
        sp, f = d.spec(k), d.freq(k)
        out.append(f"{sp.shape[0]}:{sp.shape[1]}:{f.size}:{int(np.all(np.diff(f) > 0))}")
    c = s.check()
    print("/".join(out) + f":{c['unexplained']}:{c['crc_bad']}")
finally:
    s.close()
EOF
)
  stop_srv
  local w="62:32768:32768:1"
  judge $([ "$r" = "$w/$w/$w/$w:0:0" ] && echo 1 || echo 0) "A0〜D0 の 手元のダンプ:ch:軸:昇順、説明のない欠け:CRC $r（期待 $w/$w/$w/$w:0:0）"
}

t_g2f() {     # proj037 X-1: 2G-1-Fine（--g2f、STAGE2 の流れ A0 の 1 本・3,670,016 ch）。tint 573.44 ms（n_sum 2）・fmt both・n=10。
  # kind 5・bit_kind 12・nch・nacc 320・IF の軸 i·df（昇順）・中身 = 2·基準 ＋ (2c0 ＋ 1)（32 本の組み立ての位置まで）・k の連続・BDROP 1（チャンク 0 の束、理由 N）
  echo "== g2f"; rm -f "$OUT/g2f.s45"; srv g2f --g2f
  ctl "SET tint=0.57344 shift=7 fmt=both" "GET" "START n=10" "SEND ON" > "$OUT/g2f.ctl.log"
  rcv --seconds 12 --out "$OUT/g2f.s45" --json "$OUT/g2f.json" > "$OUT/g2f.recv.log"
  local s=$(js "$OUT/g2f.json" spec) fp=$(js "$OUT/g2f.json" f32_pairs) fb=$(js "$OUT/g2f.json" f32_bad) kg=$(js "$OUT/g2f.json" kgap) td=$(js "$OUT/g2f.json" tdev)
  stop_srv
  local ax=$(python3 - "$OUT/g2f.s45" <<'PYEOF'
import sys, numpy as np, s45proto as P, s45acq as A
from s45client import if_axis
f = open(sys.argv[1], "rb").read(); o = 0; n = ng = ngp = ngd = ngdp = 0; ks = []; bd = []; sa = None
fbase = np.random.default_rng(3).integers(1 << 40, 1 << 41, A.F_NCH, dtype=np.uint64)   # FakeG2FBackend と同じ基準
i = np.arange(A.F_NCH)
for _ in range(10**6):
    if o >= len(f):
        break
    rt, pl, crc, seq = P.parse_header(f[o:o + 24]); ver = P.header_ver(f[o:o + 24])
    d = P.decode(rt, f[o + 24:o + 24 + pl], ver); o += 24 + pl
    if rt == P.T_EVENT:
        if d.get("ev") == "START":
            sa = d["start_at"]
        if d.get("ev") == "BDROP":
            bd.append(d["why"])
        continue
    if rt != P.T_SPEC:
        continue
    if d["fmt"] == P.FMT_RAW:
        c0 = (d["dump_t"] - sa) // A.F_DUMP_BEATS
        want = 2 * fbase + np.uint64(2 * c0 + 1)
        ngd += not np.array_equal(d["data"], want)
        sw = want.copy(); sw[:A.F_NKEEP], sw[A.F_NKEEP:2 * A.F_NKEEP] = want[A.F_NKEEP:2 * A.F_NKEEP], want[:A.F_NKEEP]
        ngdp += not np.array_equal(d["data"], sw)                       # 陽性対照: 荒い ch 0 と 1 を入れ替えた期待 → 全部 NG のはず
        continue
    ifx = if_axis(d)
    ref = i * (A.F_DF_HZ / 1e6)
    ng += (d["kind"] != 5 or d["nch"] != A.F_NCH or d["core"] != 0 or d["s"] != 0 or d["src"] != 0 or d["nacc"] != 320 or d["n_sum"] != 2
           or abs(d["df_hz"] - A.F_DF_HZ) > 1e-9 or d["bit_kind"] != 12 or d["data"].size != A.F_NCH
           or float(np.max(np.abs(ifx - ref))) > 1e-6 or not np.all(np.diff(ifx) > 0) or (d["dump_t"] - sa) % (2 * A.F_DUMP_BEATS))
    ngp += float(np.max(np.abs(ifx - (i + 1) * (A.F_DF_HZ / 1e6)))) > 1e-6   # 陽性対照: 1 ch ずらした軸 → 全部 NG のはず
    ks.append(d["k"]); n += 1
cont = int(ks == list(range(ks[0], ks[0] + len(ks)))) if ks else 0
print(f"{n}:{ng}:{ngp}:{ngd}:{ngdp}:{cont}:{','.join(bd)}")
PYEOF
)
  judge $([ "$s" = 20 ] && [ "$fp" = 10 ] && [ "$fb" = 0 ] && [ "$kg" = 0 ] && [ "$td" = 0 ] && [ "$ax" = "10:0:10:0:10:1:N" ] && grep -q "照合: 通過" "$OUT/g2f.recv.log" && grep -q "tint=0.57344" "$OUT/g2f.ctl.log" && echo 1 || echo 0) \
    "SPEC $s（期待 20）・組 $fp・不一致 $fb・DUMP_K の飛び $kg・DUMP_T の外れ $td・f32 の数:NG:軸の陽性対照の NG:中身の NG:中身の陽性対照の NG:k の連続:BDROP $ax（期待 10:0:10:0:10:1:N）"
}
t_g2fp() {    # proj037 X-1 陽性対照（SET）: 286.72 ms の倍数でない tint・n_sum 1（51.2 MB/s で予算を越える）・src=B は ERR。tint=0.86016（n_sum 3）は通る
  echo "== g2fp（陽性対照）"; srv g2fp --g2f
  local r1=$(ctl "SET tint=0.04096") r2=$(ctl "SET tint=0.28672") r3=$(ctl "SET src=B") r4=$(ctl "SET tint=0.86016" "GET")
  stop_srv
  judge $(echo "$r1" | grep -q "^ERR" && echo "$r2" | grep -q "^ERR" && echo "$r2" | grep -q "予算" && echo "$r3" | grep -q "^ERR" \
          && echo "$r4" | grep -q "tint=0.86016" && echo 1 || echo 0) "tint=0.04096・tint=0.28672・src=B が ERR、tint=0.86016 は通る（$(echo $r1 | tr -d "\n" | cut -c1-70) / $(echo $r2 | tr -d "\n" | cut -c1-70) / $(echo $r3 | tr -d "\n" | cut -c1-60)）"
}
t_g2fdrop() { # proj037 X-1 陽性対照（組み立て）: --posctl-s2-drop 4 で 4 ダンプに 1 つ荒い ch 5 を落とす → 組み立てが捨て（理由 並び）、束が欠ける（DUMP_K の飛び > 0）
  echo "== g2fdrop（陽性対照）"; srv g2fdrop --g2f --posctl-s2-drop 4
  ctl "SET tint=0.57344" "START n=6" "SEND ON" > /dev/null
  rcv --seconds 12 --json "$OUT/g2fdrop.json" > "$OUT/g2fdrop.recv.log"
  local kg=$(js "$OUT/g2fdrop.json" kgap) s=$(js "$OUT/g2fdrop.json" spec)
  stop_srv
  local why=$(grep -o "'asm_drop': [0-9]*, 'asm_why': {[^}]*}" "$OUT/g2fdrop.specd.log" | tail -1)
  judge $([ "$kg" -gt 0 ] && echo "$why" | grep -q "並び" && echo 1 || echo 0) "DUMP_K の飛び $kg（> 0 のはず）・SPEC $s・組み立て $why"
}
t_net() {     # 2G-4 の M5（判定 NET、INTERFACE 4.5）: float32 でも予算 30 MB/s を越える tint は SET で断り、設定は変わらない。
  # 2G-4・2G-2 は 10.24 ms（51.2 MB/s）が ERR・20.48 ms（25.6）が OK、2G-1 も同じ。Fine・Wide は 10.24 ms（12.8）で OK
  echo "== net"
  srv net24 --g24
  local a1=$(ctl "SET tint=0.01024" "GET" | grep -v "^>") a2=$(ctl "SET tint=0.02048" "GET" | grep -v "^>")
  stop_srv; srv net22 --g22
  local b1=$(ctl "SET tint=0.01024" | grep -v "^>") b2=$(ctl "SET tint=0.02048" | grep -v "^>")
  stop_srv; srv net21 --g21
  local c1=$(ctl "SET tint=0.01024" | grep -v "^>") c2=$(ctl "SET tint=0.02048" | grep -v "^>")
  stop_srv; srv netf
  local f1=$(ctl "SET tint=0.01024" | grep -v "^>")
  stop_srv; srv netw --wide
  local w1=$(ctl "SET tint=0.01024" | grep -v "^>")
  stop_srv
  judge $(echo "$a1" | head -1 | grep -q "^ERR" && echo "$a1" | grep -q "予算 30 MB/s" && echo "$a1" | grep -q "^OK tint=0.04096" && echo "$a2" | head -1 | grep -q "^OK$" && echo "$a2" | grep -q "^OK tint=0.02048" \
          && echo "$b1" | grep -q "^ERR" && echo "$b2" | grep -q "^OK" && echo "$c1" | grep -q "^ERR" && echo "$c2" | grep -q "^OK" \
          && echo "$f1" | grep -q "^OK" && echo "$w1" | grep -q "^OK" && echo 1 || echo 0) \
    "2G-4 の 10.24 ms: $(echo "$a1" | head -1 | cut -c1-60)・GET は $(echo "$a1" | grep -o 'tint=[0-9.]*' | head -1)（期待 0.04096 のまま）・20.48 ms 後の GET $(echo "$a2" | grep -o 'tint=[0-9.]*' | head -1)、2G-2 $(echo $b1 | cut -c1-3)/$(echo $b2 | cut -c1-2)・2G-1 $(echo $c1 | cut -c1-3)/$(echo $c2 | cut -c1-2)・Fine $(echo $f1 | cut -c1-2)・Wide $(echo $w1 | cut -c1-2)"
}
t_netp() {    # net の陽性対照: 照合を外した specd（--net-budget-mbs 0）では 2G-4 の 10.24 ms が通る
  echo "== netp（陽性対照）"; srv netp --g24 --net-budget-mbs 0
  local r=$(ctl "SET tint=0.01024" "GET" | grep -v "^>")
  stop_srv
  judge $(echo "$r" | head -1 | grep -q "^OK$" && echo "$r" | grep -q "^OK tint=0.01024" && echo 1 || echo 0) "照合なしで SET tint=0.01024: $(echo "$r" | head -1 | cut -c1-40)・GET $(echo "$r" | grep -o 'tint=[0-9.]*' | head -1)（期待 0.01024）"
}

case "${1:-all}" in
  all) t_basic; t_corrupt; t_gap; t_drop; t_skip; t_reconnect; t_stall; t_f32; t_f32p; t_v1; t_load; t_tpjump; t_idle; t_shm; t_wide; t_widep; t_widesnap; t_widekind; t_g21; t_g21p; t_g21cli; t_g22; t_g22same; t_g22p; t_g22cli; t_g24; t_g24same; t_g24p; t_g24cli; t_g2f; t_g2fp; t_g2fdrop; t_net; t_netp ;;
  *) "t_$1" ;;
esac
if [ $NG = 0 ]; then echo "test_fake: 全部通過"; else echo "test_fake: NG $NG 件"; exit 1; fi

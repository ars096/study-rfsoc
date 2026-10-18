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

t_load() {    # proj021 2-3d: LOAD で proj020 の道具（s45proto v1）↔ proj021（v2）を往復。受けは切らずに続け、番号は続く・説明のない欠け 0・版 1 と 2 の両方
  echo "== load（2-3d）"
  local B="$OUT/bits"; mkdir -p "$B"; echo p21 > "$B/p21.bit"; echo p20 > "$B/p20.bit"
  printf '{"default": "proj021", "bits": {"proj021": {"bit": "p21.bit", "pydir": "%s"}, "proj020": {"bit": "p20.bit", "pydir": "%s"}, "bad": {"bit": "p20.bit", "pydir": "/nonexistent"}}}' \
    "$PWD" "$(cd ../../proj020/pynq && pwd)" > "$B/bits.json"
  srv load --bits "$B/bits.json" --boot-timeout 30
  ctl "START n=20" "SEND ON" > /dev/null
  rcv --seconds 14 --json "$OUT/load.json" > "$OUT/load.recv.log" &
  local R=$!
  sleep 3; ctl "LOAD bit=proj020" "START n=10" > "$OUT/load.ctl1"
  sleep 2; ctl "LOAD bit=bad" > "$OUT/load.ctl2"
  ctl "LOAD bit=proj021" "START n=10" > "$OUT/load.ctl3"
  wait $R
  stop_srv
  local s=$(js "$OUT/load.json" spec) u=$(js "$OUT/load.json" unexplained) d=$(js "$OUT/load.json" dup) v=$(js "$OUT/load.json" ver)
  local ev=$(grep -c '"ev": "LOAD"' "$OUT/load.recv.log")
  judge $([ "$s" = 320 ] && [ "$u" = 0 ] && [ "$d" = 0 ] && [ "$ev" = 2 ] && grep -q "ERR LOAD bad" "$OUT/load.ctl2" && grep -q "OK bit=proj020" "$OUT/load.ctl1" \
          && python3 -c "import sys; v=$v; sys.exit(0 if v.get('1') and v.get('2') else 1)" && echo 1) \
    "SPEC $s（期待 320）・説明のない欠け $u・送り直しとみなした記録 $d・EVENT LOAD $ev・版 $v・bad は元に戻る"
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

case "${1:-all}" in
  all) t_basic; t_corrupt; t_gap; t_drop; t_skip; t_reconnect; t_stall; t_f32; t_f32p; t_v1; t_load; t_tpjump; t_idle; t_wide; t_widep; t_widesnap; t_g21; t_g21p; t_g21cli ;;
  *) "t_$1" ;;
esac
if [ $NG = 0 ]; then echo "test_fake: 全部通過"; else echo "test_fake: NG $NG 件"; exit 1; fi

#!/bin/bash
# proj027 4c-b: 4c（tint 10.24 ms で 30 分）を AMS の記録つきで。受けを先に、命令を後に。STATUS を 1 分ごと
# 温度のどれかが 95 ℃ を越えたら STOP（README の中止の条件）。specd は先に起こしておく
cd /home/xilinx/proj027 || exit 1   # root の ~ は /root（4c-b の 1 回目はここで外れた）
R=runs/g24_4c30b
python3 amslog.py --out $R.ams.log --period 10 --seconds 2300 &
sleep 120                                   # 待機の値を 2 分
python3 specrecv.py --host 127.0.0.1 --seconds 1950 --json $R.json > $R.recv.log 2>&1 &
RP=$!
sleep 3
python3 specctl.py --host 127.0.0.1 "SET A0.src=A B0.src=B C0.src=C D0.src=D shift=7 tint=0.01024 fmt=f32" "START n=0" "SEND ON" > $R.ctl.log 2>&1
for m in $(seq 1 30); do
  sleep 60
  echo "== $m 分 $(date -u +%H:%M:%S)" >> $R.status.log
  python3 specctl.py --host 127.0.0.1 STATUS >> $R.status.log 2>&1
  hot=$(tail -n 1 $R.ams.log | awk '{for (i = 3; i <= 5; i++) if ($i + 0 > 95) print $i}')
  if [ -n "$hot" ]; then echo "== 中止: 温度 $hot ℃ $(date -u +%H:%M:%S)" >> $R.status.log; break; fi
done
sync
python3 specctl.py --host 127.0.0.1 STOP >> $R.ctl.log 2>&1
sleep 5
echo "== STOP の後 $(date -u +%H:%M:%S)" >> $R.status.log
python3 specctl.py --host 127.0.0.1 STATUS >> $R.status.log 2>&1
wait $RP
echo done > $R.done
sync

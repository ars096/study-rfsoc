# proj029（2G の取得の熱い所を C に）への引き継ぎ

2026-10-23、proj025（2G-2）の会話から。**新しい会話の最初に、この文書・[`LESSONS.md`](../LESSONS.md)・[`proj025/README.md`](../proj025/README.md) の「4c の 1 周の内訳」と「閉じた後の追補 5」を読む。**
番号 proj029 は INDEX に確保済み（ディレクトリはまだ無い。`cp -r template proj029` から起こす）。

## 1. 約束（どの会話でも同じ。proj024 の引き継ぎから変わった所に ★）

- コミット: `git -c user.name="<作者>" -c user.email="<作者のアドレス>" commit`（作者は直前のコミットと同じにする。アドレスは本文に書かない）、メッセージは日本語、末尾は `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` だけ。
  **Claude-Session の行・URL は入れない。push はしない（開発者がする）**。status・log は `git --no-optional-locks`。**`git commit -- <パス>` でパスを指定する**（同じ作業ツリーに proj028 の会話もコミットする）
- ★ Claude がコンピュータ側のシェル（Vivado サーバの `~/git` を接続したもの）から git を触ると、後片づけの lock（`.git/*.lock`・`objects/*/tmp_obj_*`・`gc.log.lock`）が残ることがある。
  コミットは `git -c gc.auto=0 …`、終わったら `find .git -maxdepth 3 -name "*.lock"` で確かめ、自分が残したものだけを（削除の許可をもらって）消す
- リポジトリ（study-rfsoc）は公開。**ホスト名・SG やボードのアドレス・個人のパス・Host ID・データの口の相手の IP を書かない**。コミットの前に公開前スキャン
  （`cd ~/git/rfsoc && python3 -I ../YATSUGATAKE/tools/prepublish_scan.py --quiet`。12 桁のビート数が「MAC・Host ID」に誤検知されるのは既知）。
  ★ specd の STATUS（`data_client`・`data_drop`）と specd のログには受け手の IP が出る。`runs/` に残すときは `<host>` に置き換えてから
- ボードのコマンドは root で `python3 xxx.py …`。ボードは `$B`、SG は `$SG`、PATT は `instr.Atten()`（環境変数 `RFSOC_ATT`）。送るのは `scp … xilinx@$B:~/projNNN/` の形。
  ★ この会話の作業用のシェルからはボード・SG に届かない。ボードの操作は開発者が PC の端末で打ち、記録（`runs/`）を Claude が読む分担
- ★ specd の受けは **命令（SET・SEND ON・START）を先に、受け（specrecv）を後に**（受けを先に起こすと `--seconds` が START より前に切れる。proj025 4a で踏んだ）
- 予言を先に書き、陽性対照を付け、結果で予言の当たり・外れを README に残す

## 2. 目的と、決まっていること

**目的**: 2G（2G-1・2G-2）の取得（ボードの PS、`s45acq.py`）の熱い所を C にして、**tint 10.24 ms（n_sum 1、BITS.md の 2G の dt）を 1 プロセスで余裕をもって回す**。
開発者の判断（2026-10-23）: 「C にする（1）」か「プロセスを分ける（2）」のうち、実測（下の 3.）を見て **1**。

- 範囲は熱い所だけ: **リングの読み（`plring.Ring.read`）〜 束ね（`Bundler.add`）〜 SPEC の記録（`Acq._spec_record_full`）〜 溜まりへの写し（`Acq._put` → `s45ring.put`）**。制御・時刻・TP・STATUS は Python に残す（proj025 の会話の勧め。変えてよい）
- **出す記録は今と bit 単位で同じ**（s45proto v2、`SPEC2_H`・u64 と f32・CRC）。今の Python の道が正解になる。test_fake（PL なし 23 試験、`pynq/test_fake.sh`）と、同じ入力で Python と C の出力を照らす試験で確かめる
- CRC は `zlib.crc32`（CRC-32、IEEE の多項式）。ARMv8 の CRC32 命令（CRC32B/H/W/X。CRC32C 系ではない）と同じ
- 土台: タグ **proj025-m0** の `proj025/pynq/`（G22Backend・FakeG22Backend・`--loop-log-ms`）と、その後の `timebase.py`（CAL[0x0025_0100] 入り、f3af4a8）。
  bit は `proj025/build/proj025.bit`（sha256 `de3ee453…cf30bf9`、ボードの `~/proj025/` にある）。RTL・bit は変えない見込み（PS だけの試行）

## 3. 測った数（proj025、ボードの A53、Python 1 本・CPU 3・SCHED_FIFO・mallopt あり）

**tint 10.24 ms（n_sum 1）の実測**（proj025 追補 5、`--loop-log-ms 0.1` で全部の周の段の時間の和 / BASE）:

| 1 BASE（10.24 ms）あたり | src C・D（TP 4 本） | src A・B（TP 2 本） |
|---|---|---|
| リングの読み（invalidate・CRC・写し。レコード 1 個 ≒ 0.6〜0.8 ms） | 3.97 ms | 3.69 ms |
| 振り分け | 1.39 ms | 0.71 ms |
| **窓の記録（束ね ＋ SPEC の記録 2 本。1 本 3.7 ms）** | **7.48 ms** | **7.36 ms** |
| TP | 0.20 ms | 0.15 ms |
| **計** | **13.06 ms（127 %）** | **11.93 ms（116 %）** |

- 遅れると 1 周が抱える BASE が増えて 1 周が 600 ms まで伸び、リング 64 MiB が満ちて PL で落ちる（pl_drop 8）
- **SPEC の記録 1 本（65,536 ch）3.7 ms が最大**: 逆順の写し（`[::-1]`）・`P.f32_round`（u64 → float64 → float32）・`SPEC2_H.pack`・`P.crc32`（256 KiB）・溜まりへの写しで、同じ配列を何度もなめている
- tint 40.96 ms（n_sum 4）の 30 分（proj025 4c）は取りこぼし 0 だが、TP 4 本で 1 BASE ≒ 8.7 ms（85 %）。**1 周の時間（loop_max）は余裕の物差しにならない**（LESSONS、proj025 4c）。余裕は loops / dumps か、段の時間の和 / BASE で読む
- 2G-1（proj024 3d、`pynq/bench_g21.py`）: PL なしの台本で 1 BASE 平均 6.2〜6.5 ms（61〜63 %、記録 1 本 = 131,072 ch）。裾の 60 ms 級は malloc の mmap → `mallopt` で消えた

## 4. 別の制約（C にしても残る。開発者の判断）

- **送り出し**: dt 10.24 ms の float32 は 2 窓 × 256 KiB / 10.24 ms ≒ **51 MB/s**。ボードの送り出しは TCP で ≒ 220 Mbit/s（≒ 27 MB/s）で頭打ち（proj021 README の C3）。
  取得が間に合っても、全 ch を 10.24 ms ごとに送ることはできない。送り出しの上限を上げる・ネットワークでは束ねる・ch を減らす のどれか（INTERFACE 8. の 10 の未決と同じもの）
- A53 は 4 コア。specd の本体（送り出し）・取得（CPU 3）・ほかで分け合う

## 5. 最初の一手の案（proj025 の会話の勧め）

1. 小さく測る: ボードの上で **SPEC の記録 1 本（65,536 ch の u64 → 逆順・float32・CRC・写し）を C の関数 1 つで**行い、今の 3.7 ms と比べる（ctypes か cffi。ボードの gcc の有無を先に確かめる）。
   同じ入力で Python の `_spec_record_full` と bytes が一致することを陽性対照つきで（1 ch だけ値を変えると不一致になる）
2. 効けば、リングの読み（invalidate の後の CRC と写し）と束ねの足し算を同じ関数に寄せる（1 回のなめ）
3. 段の時間は specd の `--loop-log-ms` で今と同じ形で出せる（周ごとの SPEC の記録の本数つき）。PL なしの 1 周の台本は `bench_g21.py` を 2G-2 に直すと使える

## 6. proj025 から持ち越した片づけ（開発者）

- `git push origin main` と `git push origin proj025-m0`
- 配線が **配線 P**（1PPS を ADC_A〜D にも分配。proj025 4d・追補 5）のまま。普段の配線（ノイズソース → … → 4 分配器 → ADC）に戻す。PATT は 13 dB
- ボードの `~/proj025/` には較正入りの timebase.py（f0204e9a…）・`--loop-log-ms` 入りの s45acq.py・specd.py が送ってある

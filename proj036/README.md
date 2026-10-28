# proj036 — 2G の束ね（ネットワークの tint > 10.24 ms）の取得を C の道に

日付: 2026-10-28（起こし）
土台: study-rfsoc 4d48989 の `proj031/pynq/`（`git ls-files` の追跡ファイル）と `proj031/tools/loopsum.py`・`amslog.py` を写した。bit は **proj031 rev 2 のまま**（`~/proj031/proj031.bit`、PROJ 0x0031_0200）。RTL・bit は変えない。仕様は YATSUGATAKE 7f6eb8b（予算 1 ボード 30 MB/s、interface 4.5）
状態: 進行中

着手の前に [`../LESSONS.md`](../LESSONS.md) を全部読む（知見の全部は [`../docs/lessons_all.md`](../docs/lessons_all.md)）。

## 目的

ネットワークの予算を 30 MB/s にした（2026-10-28）ので、2G はネットワークの tint 20.48 ms（n_sum 2、25.6 MB/s）で送れる。
ところが n_sum ≧ 2 の取得は proj029 の C の道（`--fast-ring` は n_sum 1 だけ）を通らず、**リングの読み（写す・zlib の CRC）と束ね（numpy）が Python** で、
proj035 L-1 の内訳では 30.72 ms（n_sum 3）で 1 周 26 ms（85 %）、20.48 ms（n_sum 2）では ≒ 20 ms（98 %）の見込みで入らない。
**n_sum ≧ 2 の FULL の束ねを C にして、20.48 ms・30.72 ms を余裕をもって回す。出す記録は今と bit 単位で同じ**（今の Python の道が正解）。

## 作り（2026-10-28）

- `s45fast.c` に `s45_ring_acc`: PL のリングの上の SPEC のレコード（LazyRec、写さない）を 1 回なめて、PL の CRC（頭 ＋ 中身）を取りながら器へ **first なら写す・でなければ足す**（u64、FFT の ch の順のまま。逆順と丸めは記録のときに今の `s45_spec_f32` / `s45_spec_u64`）
- `Bundler(n_sum, pl_nacc, fast=, posctl=)`: fast があれば n_sum ≧ 2 の LazyRec を C で器へ。器は窓ごとに 1 つで使い回す（束を返した周のうちに記録を作る `_loop_once` の並びに頼る）。**PL の CRC が合わない 1 本を含む束は丸ごと捨てる**（理由 "CRC"、ring_crc ＋1・読み落とし ＋1）。今の道ではその 1 本を pump で捨てて束が欠けで捨てられるので、出る記録は同じ
- `--fast-ring` の窓（lazy_wins）を n_sum ≧ 2 の FULL にも広げる。新しい選択は足さない（`--fast-ring` の意味が広がる）。陽性対照 `--posctl-noacc`（足さずに写す）
- 器の確保は窓ごと 256 KiB（2G-4）〜 1 MiB（2G-1）× 1

## 手順

- **P-1 PL なしの照合**（`pynq/test_bund_fast.py`、この PC）: n_sum 2・3 × fmt f32・u64・both で Python の道・`--fast`・`--fast-ring` の記録が頭・中身・CRC まで bytes で同じ。束の頭のずれ・DUMP_N の違い・CRC の壊れの捨て方が同じ。端をまたいで何周も。陽性対照（足さずに写す・1 バイト壊す）は落ちる。今までの `test_ring_fast.py`・`test_s45fast.py`・`test_fake.sh` も通る
- **R-1 1 周の内訳**（ボード、2G-4・0x0102・`--prefault --fast --fast-ring --loop-log-ms 0.1`、この PC へ送る）: tint 30.72・20.48・10.24 ms を 60 s ずつ。`tools/loopsum.py` で出口の記録 1 本あたり
- **R-2 レベル**（`tools/level.py`）: 平均 / nacc が tint 10.24・20.48・30.72 で同じ。`--posctl-noacc` で 1 / n_sum に落ちる
- **R-3 30 分**（tint 20.48 ms、25.6 MB/s でこの PC へ）

## 予言（2026-10-28、走らせる前に書く）

- P-1: 全部通る（バイトの並べ替えは無く、和を取る場所が numpy → C に移るだけ）
- R-1（出口の記録 1 本あたり）: 今（proj035 L-1、30.72 ms）はリングの読み 11.6・振り分け 4.3・窓の記録 8.1・TP 2.2 = 26.2 ms。
  リングの読みから写しと zlib の CRC が消え（LazyRec）、束ねの numpy が C の 1 回のなめ（CRC の命令 ＋ 足し、256 KiB で ≒ 0.2〜0.4 ms）になる。
  **30.72 ms: 計 10〜18 ms（33〜59 %）、20.48 ms: 計 8〜14 ms（39〜68 %）、10.24 ms: proj029 と同じ（≒ 6 ms）**。振り分け・TP・記録（spec_f32）・put は変わらない
- R-2: 平均 / nacc は 3 つの tint で相対 1e-3 以内で同じ（雑音の揺れの分だけ）、noacc の 30.72 ms は 1/3（0.333 ± 0.01）
- R-3: miss・kgap・pl_drop・pl_crc・pl_err 0、受けの CRC・欠け 0、照合 通過、25.6 MB/s

## 結果

-

## 結論・次にやること

-

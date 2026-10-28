# proj036 — 2G の束ね（ネットワークの tint > 10.24 ms）の取得を C の道に

日付: 2026-10-28（起こし）
土台: study-rfsoc 4d48989 の `proj031/pynq/`（`git ls-files` の追跡ファイル）と `proj031/tools/loopsum.py`・`amslog.py` を写した。bit は **proj031 rev 2 のまま**（`~/proj031/proj031.bit`、PROJ 0x0031_0200）。RTL・bit は変えない。仕様は YATSUGATAKE 7f6eb8b（予算 1 ボード 30 MB/s、interface 4.5）
状態: **完了**（2026-10-28。2G-4 を tint 20.48 ms・24.8 MB/s で 30 分、取りこぼし 0・照合 通過。1 周 13.4 ms / 20.48 ms = 65 %）

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

### P-1 PL なしの照合（2026-10-28、この PC とボード）: 全部通過

- `test_bund_fast.py`: n_sum 2・3 × fmt f32・u64・both で、Python の道・`--fast`・`--fast-ring` の記録 12〜24 本が頭・中身・CRC まで bytes で同じ。`--fast-ring` で写した残り 0・ring_crc 0
- 捨て方: 束の頭のずれ（997 から）・DUMP_N の違い（"N"）・欠けの BDROP の理由と記録が今の道と同じ。CRC の壊れ（1 バイト）はその束を記録せず ring_crc 1・読み落とし 1 で今の道と同じ
- 陽性対照: 足さずに写す（`--posctl-noacc`）は 12 本とも今の道と違う。端をまたいで何周も（PAD）・器を使い回しても同じ
- 1 回目は 2 つ落ちた: 試験台の偽のリング（8 MiB）に 12 MiB 書いて古いレコードを上書きしていた・何周も回す試験で周ごとに SEQ を 1 から振り直していた（試験台の誤り。C の道 = Python の道の照合は 1 回目から通っていた）
- 今までの `test_ring_fast.py`・`test_s45fast.py`・`test_fake.sh`（全部）も通過。ボード（CRC は命令）でも `test_bund_fast.py`・`test_ring_fast.py` が通過

### R-1・R-2 1 周の内訳とレベル（2026-10-28 05:1x、2G-4 proj031 rev 2・AXI_MAX_PIPELINE 0x0102・`--prefault --fast --fast-ring --loop-log-ms 0.1`・src ABCD・SHIFT 7・f32、受けはこの PC、60 s ずつ specd を起こし直して）

| tint | 送り出し | 計（出口の記録 1 本あたり） | 予言 | 今の道 | miss・照合 |
|---|---|---|---|---|---|
| 30.72 ms | 16.3 MB/s | **18.5 ms（60 %）**: リングの読み 2.1・振り分け 4.4・窓の記録 9.4・TP 2.6 | 10〜18 | 26.2（85 %、proj035 L-1） | 0・通過 |
| **20.48 ms** | 24.4 MB/s | **13.4 ms（65 %）**: 1.4・2.9・7.4・1.7 | 8〜14 | ≒ 20（98 %、見込み） | 0・通過 |
| 10.24 ms | 41.1 MB/s | 7.5 ms（73 %）: 0.7・1.4・4.6・0.8 | ≒ 6 | 6.2（proj029、受けはボードの上） | 0・通過（loop_slow 655） |
| 30.72 ms・`--posctl-noacc` | 16.3 MB/s | 17.0 ms | | | 0・通過 |

- リングの読みは 11.6 → 2.1 ms（写しと zlib の CRC が消えた）。束ねは記録 1 本あたり 0.84 → 1.15 ms（CRC を取るなめが束ねの中に移った）。30.72 ms は予言の上の端を少し外れ、20.48 ms は中
- 10.24 ms は予算（30 MB/s）の外の参考。受けがこの PC（送り出しの CPU が乗る）なので proj029（受けはボードの上）より 1.3 ms 多い
- **R-2 レベル（平均 / nacc）**: 陽性対照（足さずに写す）はふつうの 0.330〜0.332 倍（予言 1/3 ± 0.01、当たり）
  - 予言の「3 つの tint で 1e-3 以内」は、specd を起こし直した 3 回の比べでは **1.6 % 違って外れた**（Overlay の載せ直しの段。proj028 F-6 で知っていたのに予言に入れなかった）
  - **1 回の読み込みの中で tint を 10.24 → 30.72 → 20.48 → 10.24 → 30.72 → 20.48 ms と切り替える（各 20 s、前に 2 分空回し）と ±4e-4 以内**（10.24 ms の 2 回の平均に対する比 0.9995〜1.0004、4 コアとも。ゆっくりした漂い −0.08 % / 2 分の分）→ 当たり


### R-3 tint 20.48 ms で 30 分（2026-10-28 05:33〜06:04、R-1 と同じ構成、受けはこの PC）: 通過

- miss 0・kgap 0・pl_drop 0・pl_crc 0・pl_err 0・loop_slow 1・1 周の最長 23.2 ms・リングの山 4.2 MB、30 分を通して AXI_MAX_PIPELINE 0x0102 のまま
- 受け: 44.6 GB（24.8 MB/s）・SPEC 355,080 本・CRC 0・欠け 0・照合 通過（予言どおり）

## 結論・次にやること

- **n_sum ≧ 2 の FULL の束ねを C にした**（`s45_ring_acc`、`--fast-ring` の意味を n_sum ≧ 2 に広げた）。出す記録は今の Python の道と bit 単位で同じ（P-1）
- **2G-4 は予算 30 MB/s のネットワークの tint 20.48 ms で回る**: 1 周 13.4 ms（65 %）、30 分で取りこぼし 0。30.72 ms は 18.5 ms（60 %、今の道は 85 %）
- 外れた予言: 30.72 ms の計（18.5、予言 10〜18 の上を少し外れた。束ねの中の CRC のなめを軽く見た）・tint をまたぐレベルの比べ（Overlay を載せ直すと 1.6 % の段。1 回の読み込みの中では ±4e-4）
- 次: **YATSUGATAKE の 2G-4 の移植（M0〜）**。M5 で 2G の PS を `sw/pynq` に一本化するときの写し元は proj036 の `pynq/`（proj031 の PS ＋ この束ね）
- 知見: `docs/lessons_all.md` に足した

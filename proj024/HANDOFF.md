# proj024 の引き継ぎ（2G-1 の RTL、2026-10-17 夜の会話から。2d の後に更新）

新しい会話の最初に、この文書・[`README.md`](README.md)（とくに「2G-1 の作り」「RTL（2G-1）」の節）・[`../LESSONS.md`](../LESSONS.md)・
[`../docs/handoff_proj024.md`](../docs/handoff_proj024.md)（proj023 の会話からの引き継ぎ。**7. の追記**が RTL を始めてよい根拠）を読む。
進み具合と決めたことの正は README。ここには「どこから再開するか」と「この会話で分かった作業の型」だけを書く。

## 0. 再開する前に（この会話の終わりで片づいていないこと）

- 2c のコミット（956aa56）は 2026-10-17 夜の 2 つ目の会話で済ませた。2d・2e・2f の build.tcl は同じ会話（10/17 夜〜10/18 朝）でコミットした（push はしていない。西村さんがする）
- `proj023/pynq/` の追跡していないファイル（v2b.json・v2bp.json・snap23.snap.npz）は proj023 の会話のもの。触らない
- **コンピュータ側のシェルが「起動中」のまま返らないとき**: アプリの裏の仮想環境が古いまま止まっていることがある。
  ウィンドウを開き直すだけでは直らない。アプリを終了し、残ったプロセス（仮想環境を含む）を止めてから起動し直す（10/17 夜は 10/9 から動いていたものが止まっていた）

## 1. 今どこにいるか

2G-1（1 ADC × 262144 点、131072 ch、BIT_KIND 11）の**手順 2f（.bit）まで済み**。全部、単体の sim で模型と bit 単位で一致し、陽性対照は落ちた。

| 手順 | 部品 | sim | 状態 |
|---|---|---|---|
| 1a | `src/g21/g21_coef.v`（PFB の係数の線形補間、LAT 5） | `make sim-g21c` | 済み |
| 1b | `src/g21/g21_tw.v`（ひねり係数の 2 つの表の積、LAT 6） | `make sim-g21t` | 済み |
| 1c | `src/g21/g21_pfb.v`・`g21_pfb_core.v`（wide_pfb を 16384 ビートに、入力を 3 クロック遅らせる） | `make sim-g21p` | 済み |
| 1d | `src/g21/g21_chain.v`（Y の丸め・cmul SH 18・dft16・電力、束ねなし） | `make sim-g21ch` | 済み |
| 2a | `sim/lane_fft_g21_model.v`（レーン FFT 16384 点・bit 反転順の行動模型） | `make sim-lane` | 済み |
| 2b | `src/g21/g21_acc.v`（FULL の積分器、URAM 48） | `make sim-g21a` | 済み |
| 2c | `src/g21/g21_spec.v`（分光の本体、流れ 1 本）。**2d で SHIFT を RUN で取り込むように直した** | `make sim-g21s`（1 本 4 分前後） | 済み（2d で回し直した） |
| 2d | `src/g21/g21_core.v`（FULL の流れのブロック・SPEC のレコード 1 MiB・FULL の TP・SRC）＋ rec_fr の NCH・tp_core の F0_EXT | `make sim-recfr`・`make sim-g21core`（1 本 10〜18 分） | 済み |
| 2e | `src/g21/g21_s45_core.v`（コア 1 個: core_cmn ＋ g21_core（s 0）＋ raw_core（s 1、0x4400）＋ rec_arb。axis_sel4 は外に 2 個、D-14） | `make sim-g21s45`（2 本で 20 分前後） | 済み |
| 2f | `build.tcl`（proj023 を写して直した）・`src/board/`・`make build` | Vivado サーバ（1 時間前後） | 済み: **build-PE/（Performance_Explore、WNS +0.0018 ns）が実機に載せる .bit**。既定の戦略は −0.110 ns |

写し元は **567fda2**（proj023 の RTL の凍結）。`src/common/` は 567fda2 の proj023/src/common を写したもの。直すときは 2G の側で直す。
2d で `src/common/` を 2 つ直した（rec_fr の NCH・tp_core の F0_EXT と宣言の位置）。どちらも既定の引数では 567fda2 と同じ振る舞い（rec_fr は sim-recfr で確かめた）。Wide に戻すかはマージのときに決める。

## 2. 次にやること（3. PS → 4. 実機）

- **3. PS**: specd の FULL（NCH 131072・1 MiB のレコード）、取得を C に（D-11、Python 1 本では 102.4 MB/s が回らない）。リングの大きさ（INTERFACE 8. の 11 の前半）
- **4. 実機**: build-PE/ の proj024.bit・.hwh（sha256 は README）。`scp build-PE/proj024.bit build-PE/proj024.hwh …`（**build/ の閉じていない .bit と取り違えない**）
- PS への注意（2d・2e で分かった）: **FULL の SHIFT は RUN で効く**。FULL の TP は流れのブロックの 0x100〜（レコードの s = 0）。RAW は s = 1（0x4400）で、自分の SRC を持つ（FULL と同じ ADC を見るなら両方に書く）。
  TP の DUMP_T とデータの T のずれは経路ごと（コアの TP +1・FULL −1・RAW 0 ビート）→ D_S の表に
- 次に .bit を作り直すとき（急がない）: s45_ring_0 の空いた入口を xlconstant で縛る（BD 41-759）・build.tcl で vivado.log の本体の CRITICAL WARNING も拾う・
  積分器の URAM の読みと PFB の履歴の BRAM のカスケードに段を足して余裕を作る（今は 1.8 ps。RTL を変えたら 2b・2c 以降の sim を回し直す）

各手順は今までと同じ型で: **予言を README に書いてから走らせる → 結果と当たり・外れを書く → INDEX の proj024 の行を更新 → コミット**。

## 3. sim の回し方（この会話で決めた）

- **iverilog はこの PC にも Vivado サーバにも無い**。作業用のクラウドの環境に oss-cad-suite を入れて回した（apt は届かない。GitHub の YosysHQ/oss-cad-suite-build のその日のリリースの linux-x64 の tgz を落とし、`bin/iverilog`・`bin/vvp`・`lib/` を取り出す。Icarus 14.0 devel）
- ファイルはこの PC の `proj024/` を正とし、クラウドへは写しを置いて回す。**vvp は proj024 の直下から起動する**（hex の相対パス。出力のディレクトリから起動したら読めずに x で回った — この会話で 1 回やった）
- `make sim-…` は「結果: 全部通過」と陽性対照の「結果: 不合格」の両方を見て判定する（make の成功を信用しない）
- 長い sim（2c は 4 分前後）は裏で回して待つ
- クラウドの環境はコア 2 個。sim-g21core の 3 本を同時に回すと 1 本 18 分前後（1 MiB のレコードを出す 131k クロックが長い）。make は変種を `&` で並べて `wait` する形にした（G21CORE_V で選べる）
- クラウドで `pkill -f <パターン>` を使わない（自分のシェルのコマンド行にも当たって落ちる）。`ps` で pid を見て kill する

## 4. この会話で分かったこと（README に書いた。RTL の続きで効く）

- **番地のずれは値の比べで見えにくい**: 係数の番地の 1 ずれは PFB の出口で 25 %、ひねり係数の 1 ずれは鎖の出口で 67 %（全 0 のフレームでは 0 %）しか違いが出ない。見張り（coef_mis・tw_mis）はどの場合も立った → **本番でも見張りを残す**（LESSONS に足した）
- **IP の手前で 1 ビート落ちても、スペクトルにはほとんど出ない**（2c の陽性対照: 床の比が 0.04 % 動くだけ、A2 は違う 0）。捕まえるのは flags だけ
- **tb のレイテンシの数えは起点を揃える**: 1a の tb は番地を取り込んだ次のクロックから、1b の tb は番地を置いたクロックから数えていて、予言を 1 つ取り違えた。RTL の LAT は wide_coef_rom（LAT 2）と同じ数え（取り込んだクロックを 1）で書いてある: g21_coef 5・g21_tw 6
- bit 反転順では、フレームの最初の k1 = 0・最後の k1 = 16383（bitrev(16383) = 16383）なので、フレームの頭・最後は k1 で数えられる
- 前半・後半の係数の表は、どちらも番地 a = m >> 2 と b = 4095 − a で引く（1 ビートで 4 読み = 2 ポート × 2）
- （2d）rec_fr は NCH 4096 の決め打ちだった。NCH を引数にし、旧版（`sim/rec_fr_ref.v`）と並べる等価性の sim で、NCH 4096 では全部の出口が同じことを確かめた
- （2d）2c の g21_spec は SLICE の「SHIFT は WRST で」を持ち込んでいた。tb が WRST と RUN で同じ値を渡していたので sim を通った。RUN で取り込むように直し、tb_g21_core で RUN の前と後の RUN_SHIFT を読む
- （2d）g21_acc の読みは rd_c から 4 クロック = rec_fr の LAT 5 そのもの（wide_core と同じく fr_ch を直に繋ぐ）。1 段足すと中身が 1 ch ずれる（陽性対照）
- （2d）FULL の TP は 512 ビートの小フレームを T の格子で数え、F0 = FULL の RUN_F0 × 32。TP のレコードの DUMP_T = SPEC の DUMP_T（65,536）で揃うことを sim で見た
- （2d）sim で TP の周期を縮めると、1 MiB の SPEC が出口を塞ぐ間に TP の溜め 2 面が溢れる（tb の作りもの。実際は 20 倍の余裕）。判定は捨てた数の帳尻で
- （2e）axis_sel4 の出口は 1 段のレジスタなので、FULL の入口は T に対して 1 ビート遅れる（Wide の SLICE は自分の ADC を直に受けていた）。tb はブロックデザインと同じく axis_sel4 を外に置き、ずれを {−1, 0, +1} から探して予言と照らす

## 5. 約束（どの会話でも同じ。docs/handoff_proj024.md の 1. と同じ）

- コミット: `git -c user.name="Atsushi Nishimura" -c user.email="atsushi.nishimura@nao.ac.jp" commit`、メッセージは日本語、末尾は `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` だけ。
  **Claude-Session の行・URL は入れない。push はしない**。status・log は `git --no-optional-locks`。コミットの前に公開の確かめ（ホームのパス・IP アドレス・ホスト名・メールなどの grep）
- INTERFACE.md・BITS.md は proj023 の会話の持ち物（D-9・D-10 は入った）。LESSONS.md・docs/lessons_all.md は足すだけ
- Vivado サーバとボードは共有。使う前に西村さんと順番を決める
- この PC のシェルでは、git が一時ファイル（tmp_obj・HEAD.lock）を消せずに残すことがある（削除の許可が無いとき）。残ったら次の git が止まるので、許可をもらって消す（この会話の終わりには消した）

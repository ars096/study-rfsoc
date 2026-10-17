# proj024 の引き継ぎ（2G-1 の RTL、2026-10-17 夜の会話から）

新しい会話の最初に、この文書・[`README.md`](README.md)（とくに「2G-1 の作り」「RTL（2G-1）」の節）・[`../LESSONS.md`](../LESSONS.md)・
[`../docs/handoff_proj024.md`](../docs/handoff_proj024.md)（proj023 の会話からの引き継ぎ。**7. の追記**が RTL を始めてよい根拠）を読む。
進み具合と決めたことの正は README。ここには「どこから再開するか」と「この会話で分かった作業の型」だけを書く。

## 0. 再開する前に（この会話の終わりで片づいていないこと）

- **コミットが 1 つ残っている**: 2c の結果（README・INDEX の追記）と 2c の新しいファイルは、コンピュータ側のシェルが落ちたためコミットしていない。
  README と INDEX は追記済み（ファイルの書き戻しで反映した）。新しい会話で最初に `git status` を見て、次をコミットする:

  ```bash
  cd ~/git/rfsoc
  git add INDEX.md proj024/README.md proj024/Makefile proj024/src/g21/g21_spec.v proj024/sim proj024/HANDOFF.md
  git -c user.name="Atsushi Nishimura" -c user.email="atsushi.nishimura@nao.ac.jp" commit \
    -m "proj024: 2c g21_spec（分光の本体）と単体の sim、引き継ぎ（HANDOFF.md）" \
    -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```
  コミットの前に `.git/*.lock` が残っていないかを見る（シェルが落ちたとき git には触れていない見込み）。
- push はしていない（西村さんがする）。この会話のコミットは db5efdf 〜 8349bc7 と上の 1 つ。proj023 の会話のコミットも間に入っている
- `proj023/pynq/` の追跡していないファイル（v2b.json・v2bp.json・snap23.snap.npz）は proj023 の会話のもの。触らない

## 1. 今どこにいるか

2G-1（1 ADC × 262144 点、131072 ch、BIT_KIND 11）の RTL の**手順 2c まで済み**。全部、単体の sim で模型と bit 単位で一致し、陽性対照は落ちた。

| 手順 | 部品 | sim | 状態 |
|---|---|---|---|
| 1a | `src/g21/g21_coef.v`（PFB の係数の線形補間、LAT 5） | `make sim-g21c` | 済み |
| 1b | `src/g21/g21_tw.v`（ひねり係数の 2 つの表の積、LAT 6） | `make sim-g21t` | 済み |
| 1c | `src/g21/g21_pfb.v`・`g21_pfb_core.v`（wide_pfb を 16384 ビートに、入力を 3 クロック遅らせる） | `make sim-g21p` | 済み |
| 1d | `src/g21/g21_chain.v`（Y の丸め・cmul SH 18・dft16・電力、束ねなし） | `make sim-g21ch` | 済み |
| 2a | `sim/lane_fft_g21_model.v`（レーン FFT 16384 点・bit 反転順の行動模型） | `make sim-lane` | 済み |
| 2b | `src/g21/g21_acc.v`（FULL の積分器、URAM 48） | `make sim-g21a` | 済み |
| 2c | `src/g21/g21_spec.v`（分光の本体、流れ 1 本） | `make sim-g21s`（1 本 4 分前後） | 済み（コミット待ち、0.） |
| **2d** | `g21_core`（wide_core を写す） | | **次** |
| 2e | `g21_s45_core`（wide_s45_core を写す） | | |
| 2f | build.tcl・ブロックデザイン（proj023 を写す） | | |

写し元は **567fda2**（proj023 の RTL の凍結）。`src/common/` は 567fda2 の proj023/src/common をそのまま写したもの（35 個）。直すときは 2G の側で直す。

## 2. 次にやること（2d・2e）

決めることは全部決まっている（README の「決めること」と手順 2 の D-12・D-13）:
- **2d `g21_core`**: wide_core の流れのブロックを **KIND 1 FULL** 1 本に（NCH 131072・FRAME_BEATS 16384・PARAM・SRC は書き換えられる流れ [31]）。
  - **D-12: FULL の流れの TP は SRC で選んだ ADC の入力で測る**（INTERFACE 2.5 の 0x100〜、SAM45-Fine の FULL と同じ形。proj021 2-2d）
  - rec_fr は流れ 1 本・**レコード 1 MiB**（131072 ch × 8 B）。rec_fr の数え（バイト数・語数）の幅が 1 MiB を受けられるかを確かめる（INTERFACE 8. の 11）
  - DUMP_T = K_F ＋ 16384·DUMP_F0、F0 の格子 32 フレーム（g21_spec の GF_L2 5）
  - BIT_KIND 11・語 4・語 7 は INTERFACE の FULL の約束どおり（語 7 = 0）
- **2e `g21_s45_core`**: core_cmn ＋ g21_core ＋ axis_sel4（SRC、D-8）＋ rec_arb、**D-13: RAW の流れを s = 1 に置く**（Wide のコア 0 と同じ形）
- 2f: build.tcl（コア 1 個・IP は lane_fft_g21 = 16384 点・bit 反転順、S-1・S-2 の設定）。最初は既定の戦略（S-2 で IP の内部の余裕は +1.7 ns 以上）
- その後: 3. PS（specd の FULL・NCH 131072、取得を C に: D-11）/ 4. 実機

各手順は今までと同じ型で: **予言を README に書いてから走らせる → 結果と当たり・外れを書く → INDEX の proj024 の行を更新 → コミット**。

## 3. sim の回し方（この会話で決めた）

- **iverilog はこの PC にも Vivado サーバにも無い**。作業用のクラウドの環境に oss-cad-suite を入れて回した（apt は届かない。GitHub の YosysHQ/oss-cad-suite-build のその日のリリースの linux-x64 の tgz を落とし、`bin/iverilog`・`bin/vvp`・`lib/` を取り出す。Icarus 14.0 devel）
- ファイルはこの PC の `proj024/` を正とし、クラウドへは写しを置いて回す。**vvp は proj024 の直下から起動する**（hex の相対パス。出力のディレクトリから起動したら読めずに x で回った — この会話で 1 回やった）
- `make sim-…` は「結果: 全部通過」と陽性対照の「結果: 不合格」の両方を見て判定する（make の成功を信用しない）
- 長い sim（2c は 4 分前後）は裏で回して待つ

## 4. この会話で分かったこと（README に書いた。RTL の続きで効く）

- **番地のずれは値の比べで見えにくい**: 係数の番地の 1 ずれは PFB の出口で 25 %、ひねり係数の 1 ずれは鎖の出口で 67 %（全 0 のフレームでは 0 %）しか違いが出ない。見張り（coef_mis・tw_mis）はどの場合も立った → **本番でも見張りを残す**（LESSONS に足した）
- **IP の手前で 1 ビート落ちても、スペクトルにはほとんど出ない**（2c の陽性対照: 床の比が 0.04 % 動くだけ、A2 は違う 0）。捕まえるのは flags だけ
- **tb のレイテンシの数えは起点を揃える**: 1a の tb は番地を取り込んだ次のクロックから、1b の tb は番地を置いたクロックから数えていて、予言を 1 つ取り違えた。RTL の LAT は wide_coef_rom（LAT 2）と同じ数え（取り込んだクロックを 1）で書いてある: g21_coef 5・g21_tw 6
- bit 反転順では、フレームの最初の k1 = 0・最後の k1 = 16383（bitrev(16383) = 16383）なので、フレームの頭・最後は k1 で数えられる
- 前半・後半の係数の表は、どちらも番地 a = m >> 2 と b = 4095 − a で引く（1 ビートで 4 読み = 2 ポート × 2）

## 5. 約束（どの会話でも同じ。docs/handoff_proj024.md の 1. と同じ）

- コミット: `git -c user.name="Atsushi Nishimura" -c user.email="atsushi.nishimura@nao.ac.jp" commit`、メッセージは日本語、末尾は `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` だけ。
  **Claude-Session の行・URL は入れない。push はしない**。status・log は `git --no-optional-locks`。コミットの前に公開の確かめ（ホームのパス・IP アドレス・ホスト名・メールなどの grep）
- INTERFACE.md・BITS.md は proj023 の会話の持ち物（D-9・D-10 は入った）。LESSONS.md・docs/lessons_all.md は足すだけ
- Vivado サーバとボードは共有。使う前に西村さんと順番を決める
- この PC のシェルでは、git が一時ファイル（tmp_obj・HEAD.lock）を消せずに残すことがある（削除の許可が無いとき）。残ったら次の git が止まるので、許可をもらって消す（この会話の終わりには消した）

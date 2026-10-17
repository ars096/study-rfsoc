# proj024（YATSUGATAKE 2G のモデル）への引き継ぎ

2026-10-17、proj023（SAM45-Wide）の会話から。**新しい会話の最初に、この文書・[`LESSONS.md`](../LESSONS.md)・[`INTERFACE.md`](../INTERFACE.md)・[`BITS.md`](../BITS.md) の 2G の行を読む。**
詳しい経緯は [`proj023/README.md`](../proj023/README.md)（手順 4b〜4d）と [`docs/lessons_all.md`](lessons_all.md)。

## 1. 約束（どの会話でも同じ）

- コミット: `git -c user.name="Atsushi Nishimura" -c user.email="atsushi.nishimura@nao.ac.jp" commit`、メッセージは日本語、末尾は `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` だけ。
  **Claude-Session の行・URL は入れない。push はしない（西村さんがする）**。status・log は `git --no-optional-locks`
- リポジトリ（study-rfsoc）は公開。**ホスト名・SG やボードのアドレス・個人のパス・Host ID・データの口の相手の IP を書かない**（「Vivado サーバ」と書く）。コミットの前に公開の確かめ（grep）
- ボードのコマンドは root で `python3 xxx.py …`。ボードは `$B`、SG は `$SG`（`--sg $SG`）。送るのは `scp build-PE/projNNN.bit build-PE/projNNN.hwh pynq/*.py xilinx@$B:~/projNNN/` の形
- Makefile は直接書き換えにくい置き場所にあるので、Vivado サーバの側で python の読み書きで直す（proj023 の会話の手順）
- 予言を先に書き、陽性対照を付け、結果で予言の当たり・外れを README に残す（proj023 の README の形）

## 2. 2 つの会話の分担（ぶつからないように）

| もの | 持ち主 | proj024 の会話ですること |
|---|---|---|
| `INTERFACE.md`・`BITS.md` | **proj023 の会話**（Wide を閉じるまで） | 直したいことは `proj024/README.md` に「INTERFACE.md の変更案」として書き、proj023 の会話（か西村さん）が入れる |
| `LESSONS.md`・`docs/lessons_all.md` | 両方（足すだけ。消さない） | 2G の知見を足す。同じ行を同時に書き換えない |
| `proj023/` | proj023 の会話 | **読むだけ**。使う部品は proj024 に写してから変える（proj023 は proj021-m0 から写した。同じ形） |
| Vivado サーバ・ボード | 共有 | モデルの間は使わない。ビルド・実機に進む前に西村さんと順番を決める（ビルドは 1 回 ≒ 数時間、Performance_Explore） |

土台にする commit: **この文書を足した commit**（proj023 の V2-b の陽性対照の後）。proj024 の README の頭に、写した commit の番号を書く。
proj023 を閉じるときに、proj021 と同じく注釈つきのタグ（`proj023-m0` の案）と、bit・hwh の sha256・資源・WNS・CDC の表を残す（YATSUGATAKE の移植の M0。proj021 の README「移植元を決める」）。

## 3. proj023 で決まったこと（2G の土台になるもの）

**インターフェース v2 の SLICE の分は確定**（2026-10-17、INTERFACE.md に書き戻した）:
- コアの FFT_N（0x80: 実効の log2 N・書いた値・log2 N_PHYS）、流れの S0（0x100）・S0_CUR（0x104）・S0_STEP（0x108）、レコードの語 4（log2 NFFT・log2 B）と語 7（S0_CUR）
- **SHIFT はコアに 1 つ**（WRST で流れ 0 の値を取り込む。D-8）
- **フレームの頭を T の格子に置く（D-2）**: 起動の口を T ≡ K_F − K_OPEN で開け、F0 を 256 フレームの格子に寄せる → **r = DUMP_T mod BASE = 2·G が RTL の定数**（V2-f で Overlay 4 回、V2-b で 30 分）。proj021 の FULL のように Overlay ごとに変わらない
- specd（`--wide`）: SET `A.b`・`A.shift`・`A0.s0`、SPEC v2 の kind 2 は「ns の欄 = log2 B・IF の昇順・if_mhz = 送る 2047 番目の IF・df_hz」で、受け側は IF = if_mhz ＋ (i − 2047)·df
- 判定は Wide で全部通った: H-2（ch → IF、境目の比 ±0.06 dB）・H-4（30 回の切り替え）・H-3 の V2-a（10.24 ms × 4 = 40.96 ms が整数で一致）・V2-b（7 本・40.96 ms・30 分で欠け 0、loop_slow 0）・V2-e・V2-f。V2-c は Wide では外した

**作りの決め（D-7）**: Wide はモードごとに FFT の長さを切り替えず、**32768 点の固定長 ＋ 電力の後に B 個の ch を束ねる**。切り替えで IP を作り直さないので、起動の 1 回でフレームの頭がそろい、r が定数になった。2G の「1 / 2 / 4 ADC × 131072 / 65536 / 32768 ch」も、**資源を固定にして割り当てを替える**形を最初に考える価値がある（決めてはいない）

**使える部品**（proj023 の `src/common/`・`model/`・`pynq/`）:
- RTL: `wide_pfb.v`（T = 4、URAM の履歴）・`wide_spec.v`（16 レーンの FFT・待ち行列・診断）・`wide_chain.v`（ひねり係数・dft16・束ね）・`wide_acc.v`・`wide_core.v`（流れのブロック × 2・ARM_*・DUMP_H）・`core_cmn.v`（コアの共通・TP・TANCH）・`wide_s45_core.v`・rec_fr・s45_ring・time_core
- 模型: `model/wide_model.py`（sim の golden の元）・`model/bin_resp.py`（束ねた ch の応答）・`tools/estimate.py`（資源の見積もり）
- PS: `wide.py`（モード・S0・レコードだけで ch → IF）・`wide_v2.py`（V2-a・e・f）・`s45acq.py` の WideBackend・`test_fake.sh`（PL なし 15 試験）

## 4. 2G で初めて決めること（proj023 では決められない。proj024 の最初に並べる）

| # | 項目 | 今わかっていること |
|---|---|---|
| 1 | **ch が 4096 を越える** | 1 本の流れで 32768〜131072 ch。INTERFACE の「S0 ≦ N/2 − 4096」、PS の `NCH = 4096`・`s45proto.IF_ORDER`（4096 固定）・`s45client` の `P.NCH` を一般化する。s45proto v2 の nch の欄は u32 で形は足りる |
| 2 | **ADC の数（1 / 2 / 4）で中身が変わる** | 使わないコア・流れの自己記述（NSTREAM か NCH 0 の空の流れか）。2.1 の「空の流れ」の約束が使えるか |
| 3 | **FFT の大きさと資源** | 1 ADC で 262144 点（131072 ch）。Wide は 4 × 32768 点で DSP 2,720（63.7 %）・BRAM 75.7 %・WNS +0.001 ns（余裕ほぼ 0）。積分器は 131072 ch × 64 bit × 2 面 = 16 Mbit。`tools/estimate.py` で先に数える |
| 4 | **ネットワークの予算**（INTERFACE 8. の 10、**未決・西村さんの判断**） | 2G は float32 で 51.2 MB/s（10.24 ms）。今の予算 17.7 MB/s（ボードの送り出しが TCP で 25 MB/s で頭打ち）を越える。「PL は 10.24 ms、ネットワークは束ねて送る」と読み替えるか、ch を減らすか |
| 5 | **PS の取得**（8. の 4・6） | Python ＋ numpy の 1 本は ≒ 114 MB/s で、2G は 10.24 ms に対して 94 %（proj021 M-5）。取得を C にするか（ARMv8 の CRC 命令・和・丸め・CRC を 1 回のなめで）、複数のプロセスに。CRC を全部見るか間引くか |
| 6 | **リングとレコードの大きさ** | 1 レコード 131072 × 8 = 1 MiB。32 MiB のリングは ≒ 0.3 s しか持たない（Wide は 1.5 s）。CMA の大きさと合わせて |
| 7 | **時刻の補正** | 2G の D_S・1.5·L（L はその FFT のフレーム）。**Wide は D_S = 0・D_eff = 1.5·L**（2026-10-17、`proj023` の `sim-wds`。tb_wide_ds・check_ds の型がそのまま使える）。要点: RAW は口のビートに 1 クロック前の T を付け、axis_sel4 の 1 段がそれを打ち消す → 2G で RAW・全帯域の入口の段数を変えたら D_S が動く |
| 8 | **dt と束ね** | BITS.md の 2G は dt 10.24 ms（n_sum 1）。PL のダンプ = BASE のまま、束ねは specd（INTERFACE 5.1）で同じに扱えるか |

## 5. 2G で踏みそうな穴（proj023 で踏んだもの。LESSONS.md に載せた）

- **realtime の FFT IP は流し始めの直後に 1 回 tready を下げる**（最初のビートの直後）。m を T から決める作り（D-2）では、IP の手前に待ち行列を置いて tready を守る。**行動模型にもこの振る舞いを入れる**（入れなかったので sim を通った。proj014・proj023 で 2 回）
- **IP の出口の k1 で引く ROM はコアごとに**（共有のひねり係数 ROM でタイル 224 のコアだけ tw_mis。IP の遅れがコアで揃う保証は無い。原因はビルドごとの違いの疑いで未解決）。T だけで引く ROM は共有してよい
- タイミング: 4 ADC × 大きな FFT は `-1` で余裕が無い。`IMPL=Performance_Explore`（build-PE/）が要った。共有の ROM の配りの 1 段は DSP の A レジスタに吸われる（dont_touch）
- 判定の期待は **PS が書いた値**から取る（DUT の読み返しから取ると、効かなかった設定でもつじつまが合う）
- SG（E8257D）は 3.94 GHz で **−10 dBm 以下が unleveled**（`:POW?` は設定値を返すので気づけない）。0 dBm 以上 ＋ 固定減衰器。sg.py が ON の間に見張る
- CW の判定は「CW が見えているか（中央値との比）」を先に見る（雑音だけの隣り合う 2 ch は同じ高さで、境目の判定が誤って通った）
- 束ねた ch の雑音は B に比例する。判定の線は B で変わる

## 6. proj023 の会話で続けること（proj024 の会話からは触らない）

- INTERFACE.md の SLICE の分の書き戻し（2026-10-17 済み）
- F-2（1PPS が来ている。adc_to_core を測る）→ INTERFACE 5.2 の表（Wide の D_S は 2026-10-17 に済み: 0）
- Wide の SNAP（RAW の流れを specd に）・H-1 の掃引の道具・タイミングの余裕・（任意）ビルド 10 回目の IP の位相の調べ（9589032 の作り直し）
- proj023 を閉じるときのタグと表（2. の M0）

## 7. 追記（2026-10-17、proj023 の会話から）

- **D-9・D-10 を INTERFACE.md・BITS.md に入れた**（西村さんの決め）: BIT_KIND は 2G-4 = 3・2G-2 = 10・2G-1 = 11。流れは KIND 1 FULL・NCH 32768 / 65536 / 131072・FRAME_BEATS 4096 / 8192 / 16384。
  BITS.md の「各 bit の中の行はレジスタで」に 2G の例外を書いた。リングの大きさ（INTERFACE 8. の 11）とネットワークの予算（8. の 10）は未決のまま
- 2G の RTL は**データの道の部品（新しいモジュール）と単体の sim から**始めてよい（インターフェースに触らない）。コアの外側（流れのブロック・レコード・build.tcl）は、
  proj023 の RTL の凍結の決め（ビルド 11、567fda2 の RTL）を待ってから写す

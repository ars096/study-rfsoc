# proj015 — 狭帯域の窓に 4・2 MHz を足し（8 通りの幅）、4 ADC × 4 窓に広げる

日付: 2026-09-30
状態: **進行中**（rev1: `-2` +0.007 ns・`-1` −0.767 ns。`-1` の最悪経路の 4 群（スナップショットの書き込み・pfb の ch の選択・final の和・hist のリセット）に段を足した **rev2 は sim の回帰が全部通過**。次は rev2 のビルド）

## 目的

**bit ③（狭帯域の窓）を最終の形にする。**

- 幅に **4 MHz・2 MHz** を足す（256〜2 MHz の 8 通り、分光点数は 4096 のまま → ch 幅 976.6 Hz・488.3 Hz）
- **ddc_core を時分割**して、窓 1 つの DSP を減らす（16 窓を入れる前提）
- **4 ADC × 4 窓（16 窓）**。粗い PFB は ADC ごとに共有する
- **total power を 4 ADC すべてで**（spec_core の外に独立に置く）
- **全帯域の分光（spec_core）を試験用に 1 本だけ残し**、4 ADC のどれにつなぐかを選べるようにする（W-6・W-3 の ADC 側の線の見分け・W-1b のため）
- 速度グレード `-1` で閉じること（proj013・014 と同じ）

土台は proj014（rev2 = ID 0x0014_0200、W-0〜W-9 の道具）。`git ls-files proj014` の追跡ファイルを複製した。

## 着手の前に決めたこと（2026-09-30）

| | 決定 | 読み |
|---|---|---|
| 幅を足す方法 | **light（半帯域）を 2 段足す**（NS = 7 → 4 MHz、NS = 8 → 2 MHz）。分光点数は 4096 のまま | light・final の仕様は入力レートに対する比なので**係数は今のまま**（`win_coef.vh` は変わらない）。見送った案: 8 MHz のまま FFT を 8192 / 16384 点に（メモリと読み出しが 2〜4 倍。16 窓すべてだと URAM・読み出しの時間が足りない → proj016 で「窓を減らして点数を増やす」として検討） |
| FFT の入力の小数 G | **NS ≧ 7 で G = 5**（NS ≦ 6 は 4 のまま） | 下の「模型の下見」。N1 の誤差は 1/W で増える。G = 5 で −1 dBFS の CW の余裕は 7 → 約 1 dB（ADC の頭打ちが先に来る） |
| ddc の時分割 | **proj015 でやる** | light の 2 段目以降は、7 段ぶんを合わせても乗算の負荷が ≒ 10 DSP（10 × (1/2 + … + 1/64)）。時分割なしで 16 窓 ＋ 全帯域 1 本は ≒ 95 % で入らない |
| total power | **4 ADC すべて**（spec_core の外に独立の tp を 4 個） | 西村さんの要望（2026-09-30） |
| 全帯域の分光 | **1 本だけ・4096 点のまま・RTL は変えない**（ID の定数だけ）。4 ADC から 1 本を選ぶ | total power では W-3 の ADC 側の線の見分けと W-1b ができない。bit ② との切り替えでは同時に測れず、数秒のアナログの揺らぎ（≒ 0.4 %）が効く。点数を 1/4 にしても浮くのは ≒ 100 DSP（2 %）で、proj011〜013 で確かめた物差しの来歴が切れるほうが高くつく。ビルドで厳しければ survey で数えてから見直す |

## 着手してから決めること

- **pfb_core を共有部分と窓ごとの部分に分ける形**: 今は 1 本の ch k だけを出す。分岐の和（192）・dft16f（64）を ADC ごとに 1 つ、ch の選択と実数化（8）・(−j)^(km) を窓ごとに。dft16f の 16 本の出口を 4 窓に配る
- **ADC ごとの上位（例 `win4_core`）に 4 窓・PFB・tp・AXI をまとめるか**: 窓ごとに AXI を持つと SmartConnect の M が 16 本を超える。ADC ごとなら M は RFDC ＋ 4 ＋ spec_core ≒ 6 本
- **tp の区切りを何に揃えるか**: proj013 の tp は spec_core の RUN の F0 に揃えていた。独立させると揃える相手が要る（ADC ごとの窓の RUN か、共通の RUN か、1PPS か）
- **ギアボックスの制御**: proj014 は spec_core_1 がギアボックスを握っていた。spec_core を 1 本にすると、残りの 3 本は ADC ごとの上位が握る
- **全帯域の選択**: 4:1 の AXIS の切り替え（静的なレジスタ ＋ リセット）。切り替えは RUN の外だけ
- **スナップショット**: 窓ごと（8 × 16 = 128 BRAM）か ADC ごとに 1 つ（8 × 4 = 32）か。ADC ごとなら「どの窓を撮るか」のレジスタが要る
- **ddc の時分割の単位**: 窓の中だけで共有するか、1 ADC の 4 窓をまたいで共有するか（4 窓とも狭い幅のときだけ効く）

## 模型の下見（2026-09-30、Mac、既存の `win_model.py`・`win_fixed.py` の WIDTHS を差し替えて。リポジトリは変えていない）

`win_model.py`（係数は今のまま: PFB T = 3・light L = 4・final L = 17）:

| W | 置き場所 | 平坦さ p-p | 主以外の最悪 | 時間領域 |
|---|---|---|---|---|
| 4 MHz | 89 | 0.021 dB | −61.0 dB | 一致 |
| 2 MHz | 89 | 0.020 dB | −61.0 dB | 一致 |

`win_fixed.py`（N1: −47 dBFS の雑音で誤差 ≦ 1e-3）:

| W | N1（G = 4） | N1（G = 5） | 飽和（N2・C1、G = 5） |
|---|---|---|---|
| 4 MHz | 1.02e-3（NG） | ≦ 5.4e-4 | 0 |
| 2 MHz | 2.1e-3（NG） | 5.4e-4 | 0 |

- **罠: `win_model.design()` は PFB の通過域を `WIDTHS[0]` から決める**（`fp_pfb = DMAX + USE * WIDTHS[0]`）。WIDTHS を [4, 2] に差し替えると PFB が短く設計され（64 DSP / ADC）、別の連鎖を試すことになる。
  手順 1 で WIDTHS に 4・2 を足すときは **256 を先頭に残し**、`make coef` の生成物が proj014 と 1 byte も違わないことを確かめる

## 資源の見当（予言。手順ごとに実測で置き換える）

DSP（bit ③ = 4 ADC × 4 窓 ＋ 全帯域 1 本 ＋ tp 4 個）:

| | DSP | 根拠 |
|---|---|---|
| 粗い PFB（共有）| 256 × 4 = **1024** | proj014 の pfb 264 から実数化 8 を窓の側へ |
| 窓 1 つ | 実数化 8 ＋ ddc **72** ＋ FFT 30 = **110** × 16 = **1760** | ddc（手順 2 の形）: NCO 8 ＋ light 1 段目 10（hb2）・2 段目 6・3 段目 4・4〜7 段目 2 ずつ（hb2s）＋ final 36（NS = 1 は 256 MHz 窓の全レートなので共有しない）。着手の前の見当 64 は light 2〜7 段目を 1 組の乗算で回す形で、段ごとに持つ手順 2 の形より 8 多い。**時分割なしなら 114 ＋ 38 = 152 / 窓 → 合計 ≒ 4060（95 %）で入らない** |
| 全帯域 1 本（spec_core） | **504** | proj013 と同一（中の tp 24 を含む） |
| tp × 4（独立） | **96** | proj013 の tp_core 24 / 個 |
| 合計 | **≒ 3380（79 %）**（着手の前は 3260） | ±10 % の幅で読む。`make ooc-ddc` で ddc を数えてから置き換える |

- BRAM: 窓ごとに溜め 8・FFT 15・NCO 4、スナップショットを ADC ごとに 1 つなら 16 × 27 ＋ 4 × 8 = **464**、ほかに spec_core 1 本とギアボックスの FIFO。**≒ 550〜650（50〜60 %）**
- URAM: 積分 2 × 16 = **32**（＋ spec_core 側）
- 100 ms ごとの読み出し（AXI4-Lite、proj012 の実測 ≒ 15 MB/s）: 16 窓 × 32 KiB = 512 KiB → **≒ 34 ms**。積分を短くする（proj016）なら DMA が要る
- `-1`: proj014 rev1 は +0.086 ns。窓が 16 倍になるので**閉じない恐れを前提に**、最悪経路の群（proj013 の A〜E か窓の中か）を分ける道具（`make worst-paths`）から入る

## 手順（予定）

1. **4・2 MHz を窓 1 つのまま足す**: 模型（WIDTHS に 4・2、256 を先頭のまま）→ `ddc_core` の light を 7 段・WNS を 4 bit（win_core の WNS・PARAM[11:8]・WCUR[11:8]）・NS ≧ 7 で G = 5 → sim（sim-ddc・sim-win・sim-top を 8 通りの幅に）→ ID を 0x0015_xxxx に
2. **ddc_core の時分割**: 値は変えない。sim-ddc・sim-win をそのまま回帰試験に（陽性対照つき）。DSP を survey か OOC で数える
3. **pfb_core を共有部分と窓ごとの部分に分ける**: 1 ADC の 4 窓（別々の k・d・NS）を模型と bit 単位で照合
4. **4 ADC × 4 窓・tp × 4・全帯域 1 本（切り替えつき）**: build.tcl。結線の照合（両側・陽性対照）を 16 窓ぶんに
5. ビルド（`-2` / `-1`）→ 実機

## 判定（案）

- **窓 1 つ・8 通りの幅**: proj014 の W-0〜W-9 を 4・2 MHz にも（W-1 は ch 488 Hz なので、ボードと SG を同じ 10 MHz に載せるのが前提。**CW が PLL の近傍の位相雑音で数 ch に広がらないか**を新しく見る）
- **4 ADC × 4 窓**: 16 窓すべてで W-0・W-G・W-1・W-6（全帯域を切り替えて）・W-5
- **新しい判定の候補**: 窓どうしの独立（同じ ADC の別の窓に CW が出ない。重なる置き方は除く）・ADC 間の漏れ（proj012 の型）・16 窓の開始のずれ・tp × 4 の TP-0（パーセバル）と読み落とし・読み出しが 100 ms に収まること

## 複製したときに変えたこと（2026-09-30）

- `build.tcl` の `set proj` と `Makefile` の DCP の場所を proj015 に（**proj014 と同じ名前の .bit を作らない**）
- `pynq/spectrometer.py` の BITFILE を proj015.bit に
- `program.tcl` の bitname を proj015 に。**proj014 の program.tcl は proj013 のまま**だった（`make prog` が build/proj013.bit を探す。proj014 は PYNQ で書き込んでいたので表に出なかった）
- RTL の ID と PS 側の期待値は手順 1 で直した（win_core 0x0015_0100・spec_core 0x0015_01CC）。各ファイルの冒頭の「proj014 —」の説明は、中身を変えたものから順に直す

## やったこと

- 2026-09-30: proj014 から複製。目的・決めたこと・資源の見当を書いた。模型の下見（上）
- **手順 1: 4・2 MHz を窓 1 つのまま足した**（2026-09-30）
  - 模型: `win_model.py` の WIDTHS に 4・2（**PFB の設計を `WIDTHS[0]` から `max(WIDTHS)` に**。値は同じ 256 で、`make coef` の生成物 `win_coef.vh`・`nco_rom.v` は proj014 と 1 byte も違わない）。
    平坦さの予算の light の段数を 5 → 7 に（0.03 + 7 × 0.005 + 0.03 = 0.095 dB。light の実際の平坦さは 0.0017 dB）。
    `win_fixed.py` に `G_HI = 5`・`G_NS = 7` と `gz(cfg, ns)`（陽性対照は G・G_HI とも 0）
  - `ddc_core.v`: light を 7 段（`NL`）、`ns` を 4 bit（1..8）、**NS ≧ GNS（7）で z の丸めを G = GH（5）に**（静的な選択）。陽性対照の `-DDDC_POSCTL_G`（G の切り替えを外す）
  - `win_core.v`: WNS を [3:0]（範囲外は WRST で 1）、PARAM を [11:8] NS・**[15:12] G**、WCUR を [11:8] NS。ID 0x0015_0100
  - sim: sim-ddc を NS 1..8（入力を 4 倍にして NS 8 でも出力 472 個）、sim-win を NS 1..8（NS 7・8 は入力 4 倍）、
    **sim-win-g（陽性対照: G の切り替えを外すと NS 7・8 だけ落ちる）** を sim-win-all に。
    sim-top に**レジスタの読み返し**（WNS 7・8・9・0 を書いて WRST → WCUR・PARAM の NS と G。9・0 は 1 に丸まる）と ID の判定を足した
  - sim の道具の誤り: tb_ddc の入力の後の待ちが 60 クロックで、**NS 8 の最後の 1 個が間に合わず「出力 471 / 模型 472」で落ちた**（値は全部一致）。
    段ごとのレイテンシが 8 段ぶん積もるため。400 クロックに（tb_win も 100 → 400）
  - PS 側: `window.py` の幅の表に 4・2、`g_of(ns)`・**`pred_ratio(ns, SHIFT_full, SHIFT_win)`（W-6 の予言 64·4^(G−4)·4^ΔSHIFT。G = 5 で 4 倍）**を
    winlin・winresp・winsweep でも使う。WRST の後に PARAM の NS・G も照合。proj014 rev2 の .bit を載せたら止める。
    `winwrst.py` の幅に 4・2、`winwidths.sh narrow`（4・2 MHz の 4 通り）
  - **履歴の注意**: 手順 1 の変更は、同じ時間に proj014 を進めていた別のセッションのコミット（`dfd953e`・`4fdaf06`、題は proj014 の W-9）に
    まとめて入って push された（`commit -a` の類）。中身は sim で確かめたものと md5 で一致。**proj015 の手順 1 の差分は `git diff 20f1d87 4fdaf06 -- proj015`** で見る

- **手順 2: ddc_core の light 2〜7 段目を時分割にした**（2026-09-30）
  - `src/hb2s.v`（新規）: hb2 と同じ項・同じ係数・同じ丸めで、乗算 M 個を C クロック使い回す。出力が揃った組で前置加算した L + 1 項と係数を「項の列」に取り込み、
    毎クロック先頭の M 項を掛けて足し、列を M 項ずつ送る（mux を作らない）。**整数の和なので足す順が違っても bit 単位で同じ**。
    前提（組の間隔 ≧ C）が破れたら ovr を立て、前の計算を打ち切る。組の間隔がちょうど C なら、最後のクロックと次の取り込みが重なって間に合う
  - ddc_core: light の j 段目（j ≧ 2）を hb2s、C = min(2^(j−1), L + 1 = 5)（2 段目 C 2・M 3、3 段目 C 4・M 2、4〜7 段目 C 5・M 1）。
    組の間隔は構造で決まる（pfb_core は 1 クロックに 1 組まで・各段は 1 組で 1 サンプル・pair2 は 2 サンプルで 1 組）。
    使っている段の ovr を ovr_cnt に数え、win_core の **FLAGS[10]・0x88 DDC_OVR** に出す（構造で起きないはずの見張り）。パラメータ TS = 0 で手順 1 の形（`make ooc-ddc` の比べ）
  - sim: **sim-hb2s**（hb2 と hb2s を同じ入力で並べ、light の C 1・2・4・5・8、final の C 2・4・18。満杯の区間で飽和の経路も通す）、
    **sim-win-ts**（陽性対照: 2 段目の C を 3 にすると追い越しが立ち、2 段目を使う NS 3..8 だけ落ちる）。
    tb_ddc・tb_win は z の末尾に「# sat S ovr O」を書き、check_ddc・check_win が ovr = 0 を判定
  - 道具の誤り 2 件（sim-hb2s の初版）: (1) 組の間隔がちょうど C のとき、最後のクロックの積を「次の取り込みと重なる」として捨てていた（ovr が 1/4 の組で立った）→ 重なっても掛けるように
    (2) tb が hb2 の出力を溜めた配列と hb2s の出力を同じクロックで比べていて、C = 1・2（レイテンシが hb2 と同じか短い）で全部「不一致」になった → 両方溜めて最後に比べる
  - `tools/ooc_ddc.tcl`（`make ooc-ddc`）: ddc_core を TS = 0・1 で OOC 合成して DSP・LUT・FF・BRAM を数える（Vivado サーバ）

- **手順 3: pfb_core を NW 窓で共有**（2026-09-30）
  - 分岐の和（192）・16 点 DFT（64）は ADC ごとに 1 つ、ch の選択・実数化（8）・(−j)^(k·m')・丸めは窓ごと。ポートは窓ごとに束ねた（NW = 1 なら proj014 と同じ幅）
  - **窓ごとの始まり**: 窓 w は w_rst[w] を下ろした後の最初の valid なビート（q ≧ 5、窓の 7 ビートが埋まってから）を q_s とし、m' = m − (2q_s − 10) で数える。
    **窓 w の出力は x[8·m_s:] を模型に与えたものと bit 単位で同じ**。(−j)^(k·m') の偶奇も窓ごとに数える。rst と w_rst を同時に下ろせば q_s = 5 で proj014 と同じ
  - **proj014 の潜在の誤り**: ok = (q ≧ 6)・(q ≧ 5) を 32 bit の q で比べていて、**256 MHz で 16.8 秒ごとに q が巻き戻ると 6 ビート（12 フレーム）の間 ok が落ちる**。
    窓の z がそこで 12 フレームぶん途切れて糊付けされ、NCO の位相もずれる（1 フレームの FFT が乱れる程度。100 ms の積分では見えない大きさ）。
    proj015 は ok と偶奇を窓ごとの飽和する数えで作り、q は q_start の報告だけに使う。**sim-pfbm の QW = 8 の変種（4096 ビートで 16 回巻き戻る）で通過**
  - WRST は共有の PFB を止めない（窓の ddc・wspec と、pfb の窓 w の始まり待ちだけ）。w_rst の間は、運んでいる途中の印も消す
- **手順 4（RTL）: win_core を 1 ADC × NW 窓に**（2026-09-30）
  - 番地 20 bit = 1 MiB: 窓 w = 0x20000·w（proj014 の win_core と同じ並び）、ADC の共通 = 0x80000（ID 0x0015_A100・NW・SNAP_SEL・TP_RUN・TFIN・GB_K・FULL_SEL・GB_STAT・ADC_STAT、
    total power のレジスタ 0x80100– とリング 0x82000–）。窓ごとに 0x8C WSTART（始まりのビート）・0x90 WIDX
  - **スナップショットは ADC で 1 つ**（wspec_core の SNAP = 0 で書き込みを外へ）。SNAP_SEL の窓だけが書き、他の窓の範囲は 0 を返す
  - **total power は ADC ごと**（tp_core をそのまま）。区切りの物差しは ADC のビートの数（8192 サンプル = 2 µs のフレーム）で、TP_RUN で F0 = TFIN + 2 に揃う。窓の WRST とは無関係
  - **ギアボックスの制御は win_core_i**: gb_hold 0・gb_adj 0・gb_dn_rstn = aresetn を 1 段・gb_k = GB_K（既定 2）。GRST は無い（窓の経路は valid なビートだけで進むので起動の途切れに強い）
  - `src/axis_sel4.v`（新規）: 4 本の ADC の流れから全帯域の分光（spec_core_0）へ 1 本。選ぶのは win_core_0 の FULL_SEL。gb_stat・adc_stat も同じ選びで spec_core_0 へ
- **build.tcl（4 ADC × 4 窓・全帯域 1 本）を書いた**（2026-09-30、**Vivado で未実行**）: 変更点は build.tcl の冒頭。
  win_core_i（NW = 4）・gb_bc_i（ch ごと）・full_sel（axis_sel4）・spec_core_0。SmartConnect の M は 6 本（RFDC・win_core × 4・spec_core_0）、win_core の窓 1 MiB。
  結線の照合に win_core_i・gb_bc_i と共有のネット（full_sel）を足し、**spec_core_0 の gb_* の出口がどこにもつながっていないこと**も見る。陽性対照は win_core_0/gb_hold に

### ビルドの予言（proj015 rev1 = 4 ADC × 4 窓 ＋ spec_core_0、測る前に書く）

| | 予言 | 根拠 |
|---|---|---|
| DSP48E2 | **≒ 3290（77 %）**（± 5 %） | win_core 696 × 4（PFB 256 ＋ (実数化 8 ＋ ddc 72 ＋ FFT 30) × 4 ＋ tp 24）＋ spec_core_0 504 |
| BRAM | **≒ 500〜600（46〜56 %）** | 窓ごとに 溜め 8・FFT 15・NCO 4 = 27 × 16 = 432、スナップショット 8 × 4、tp のリング 2 × 4、spec_core_0 ≒ 80 |
| URAM | **≒ 32〜34** | 積分の二面 2 × 16（proj014 で URAM に載った）＋ spec_core_0 |
| LUT | **≒ 60〜75 %** | proj014 の窓 1 つ ＋ 18k を 16 窓ぶん（PFB の共有で減る）＋ spec_core 1 本 ≒ 45k。**いちばん危ない** |
| FF | **≒ 45〜60 %** | 同じ見当（proj014 の窓 1 つ ＋ 25k） |
| WNS `-2` / `-1` | **閉じない恐れが大きい** | 窓が 16 倍・LUT が 6 割を超える。負なら `make worst-paths` で群を分ける（proj013 の A〜E か、win_core の中か、full_sel か） |
| 結線の照合 | 問題 0・陽性対照 OK | ch ごとの表 ＋ 共有のネット |

### ビルドの結果（proj015 rev1、2026-10-01、Vivado サーバ）

| | 予言 | 結果 | |
|---|---|---|---|
| DSP48E2 | ≒ 3290（± 5 %） | **3416（80.0 %）** | 範囲の中（上の端）。**予言の表の足し算の誤り**: 696 は tp を含まない数で、win_core 1 個は 696 ＋ 24 = 720（build.tcl の予言 3380 はこちら）。実測は win_core 728 × 4（**4 個とも同じ**）＋ spec_core_0 504 |
| └ win_core_0 の中 | pfb 288・ddc 72・wspec 30・tp 24 | **288・72・32・24** | wspec だけ +2 / 窓（FFT 30 の外の 2。電力の二乗か積分の加算が DSP に載った。proj013 の教訓の型）→ 窓 4 つで +8 = 728 |
| └ spec_core_0 | 504 | **504** | 当たり（lane_fft 21 × 16 = 336 も当たり） |
| BRAM | 500〜600 | **553（51.2 %）**（RAMB36 257・RAMB18 592） | 範囲の中 |
| URAM | 32〜34 | **32** | 当たり（積分の二面 2 × 16） |
| LUT | 60〜75 % | **282,016（66.3 %）** | 範囲の中 |
| FF | 45〜60 % | **442,395（52.0 %）** | 範囲の中 |
| CRITICAL WARNING | — | なし（`-2`） | |
| CDC | proj014 と同じ型 | CDC-3 88・CDC-6 4・CDC-15 3137・Critical 0 | proj014 の CDC-3 92・CDC-6 8 から減った（spec_core が 4 → 1 本・SmartConnect の M の相手が変わった）。分類の中身は未確認 |
| WNS / WHS `-2` | 閉じない恐れ | **+0.007 / +0.010 ns** | 閉じた（余裕はほぼ 0） |
| WNS / WHS `-1` | 閉じない恐れが大きい | **−0.767 / +0.010 ns** | **閉じない**。上位 5 本は −0.767〜−0.719 で、全部 DSP ドメイン（clk_out2）の中。0.77 ns は周期の 20 % で、配置のばらつき（±0.1〜0.2 ns）では説明できない → 構造の経路と読む（未確認） |

- 見当（未確認、`make worst-paths` で確かめる）: (a) pfb_core の窓ごとの ch の選択 — dft16f の出口 16 本 × 26 bit を 4 窓 × 2（k と 16 − k）が 16:1 で選び、
  同じクロックで A・B の加算（27 bit）。DSP の出口のファンアウトも 8 倍 (b) 実数化の係数 POST_WR[k] の選択（ファブリックの mux → cmul の DSP の入口。proj013 の群 A の型）
  (c) win_core の読み出しの 4 窓の mux（レジスタの case 37 通り × 4 → rdata を 1 クロック）(d) proj013 からの群（A〜E）

### `-1` の最悪経路（`make worst-paths PART=xczu48dr-ffvg1517-1-e`、2026-10-01）と rev2 の直し

上位 200 本すべてが slack < 0.3 ns（件数は下限）。型は配線 168 / スキュー 32。照合の問題 0 件。階層で束ねると:

| 群 | 最悪 | 件数 | 経路 | 見当との比べ | rev2 の直し |
|---|---|---|---|---|---|
| S（スナップショット） | **−0.767** | 17 | win_core_3 の g_w[3].u_ws の fin → 共有の snap_mem（BRAM） | **外れ（見当に無かった）** | wspec の fin == sn_next（48 bit、CARRY8）→ SNAP_SEL の 4 窓の選び → BRAM の書き込みの入口が 1 クロックだった → **書き込みを 2 段のレジスタで受ける**（窓ごと → 選び → 記憶） |
| P（pfb の ch の選択） | −0.726 | 44 + 20 + 18 + 18 | u_pfb の dft16f の出口 → 窓ごとの ai（A の加算）/ u_post（cmul の DSP の入口） | **当たり**（見当 (a)・(b)） | 16:1 の選択の後に 1 段、B の後に 1 段（cmul の入口を DSP の前のファブリックの加算から離す）、係数 POST_WR[k] もレジスタで受ける。pfb の LAT 18 → 20 |
| F（final の和） | −0.689 | 33 + 32 | ddc の u_final: DSP の出口 mr → 4 項の部分和 gr → 5 項の和 sr（CARRY8 7〜9 段） | **外れ（見当に無かった）** | hb2 の和を **2 項ずつの木**に（18 → 9 → 5 → 3 → 2 → 1、1 段ごとにレジスタ）。値は同じ |
| R（リセット） | −0.678 | 6 + 4 | rst_dsp（ファンアウト 105 の複製）→ u_pfb の hist | 外れ | **hist をリセットしない**（q ≧ 5 の前のフレームは ok = 0。分岐の和の飽和の数えは xw の段で「valid なビートで q ≧ 6」を立てて R の段まで運んだ門で止める） |
| C（proj013 の群 C） | −0.648 | 2 | gb_gate_0 → gb_fifo_0 | proj014 の `-1` では +0.086 | 触らない（IP の中。混雑で悪くなったと読む） |
| A（proj013 の群 A） | −0.675 / −0.632 | 1 / 2 | spec_core_0 の中・g_tw[5].u_mul → u_dft | proj014 の `-1` では +0.144 | 触らない（spec_core は RTL を変えない方針） |
| W（win_core の上位） | −0.655 / −0.622 | 2 / 1 | win_core_0/inst → u_pfb、win_core_0/inst の中 | 見当 (b)・(c) の一部 | 係数の選び（c_k → POST_WR）は P で直る。読み出しの mux は様子を見る |

- **読み**: 直した 4 群（S・P・F・R）は、どれも「組み合わせの段が 1 クロックに収まらない」形（段 6〜9、配線 72〜98 %）で、配置のばらつきでは説明できない。
  群 C・A は proj014 までは `-1` で正の余裕があった経路で、LUT 66 % の混雑で配線が伸びたと読む（未確認）
- **rev2 の予言（測る前に書く）**: 直した 4 群は `-1` の上位から消える。**`-1` の WNS は −0.3〜+0.1 ns**（残るのは群 C・A と、混雑で伸びる配線。rev1 で群 C・A が −0.63〜−0.68 だったので、
  混雑が少し解けても負のまま残る恐れがある）。DSP・BRAM は同じ、FF は +2k 前後（段のレジスタ: pfb 4 窓 × 2 フレーム × (26 × 4 ＋ 27 × 2) ビット ≒ 1.3k × 4 ADC、hb2 の木）。
  負のままなら、次の手は (1) 実装の戦略（Performance_Explore など。build.tcl の引数で）(2) 群 C・A の経路に Pblock・物理最適化 (3) spec_core の方針を見直す
- **rev2 の sim（2026-10-01、クラウドの作業環境）: 全部通過**。sim-pfb（16 通り）・sim-pfb-p・sim-pfbm（3 変種）・sim-pfbm-p（窓 3 の 2 区切りだけ NG）・sim-hb2s（一致 8・陽性対照 2）・
  sim-win（8 通り）・sim-top（総合: 全部通過、ID 0x0015_0200）・sim-ddc（32 通り、追い越し 0）。win_core の ID を 0x0015_0200・ADC の共通を 0x0015_A200 に
- sim-win4 は 4 窓の z・スナップショット・total power の中身が全部一致したが、**窓 0・1・2 が模型より 1 個多い**で NG と出た。tb の「# W」の印を z の前に書いていたので、
  w_rst が立ったクロックに出ていた z（リセットの前の設定で作られたもの）が印の後に紛れた（rev2 で pfb・hb2 のレイテンシが変わって、たまたまそのクロックに z が来た）。
  印の後の最初の 1 個を除くと 3 窓とも全部一致・スナップショットも一致 → tb は z を書いてから印を書くように直した（回し直し中）
- `make IMPL=<戦略>`（build.tcl が impl_1 の strategy を設定して読み返す。OUTDIR は build-<大文字> 例 build-PE）を足した。`-1` が rev2 でも閉じないときの次の手

### 実機の .bit を `-1` でビルドする（2026-10-01、西村さんの判断: RFSoC4x2 の FPGA は `-1` と仮定して進める）

- これまで実機に載せていたのは `-2`（board_part ＋ プリセット）の build/ で、`-1` は「閉じるか」の判定だけだった。**`-2` の配置配線は `-1` の遅延で閉じている保証が無い**
  （rev1 は同じ RTL で `-2` +0.007 / `-1` −0.767 ns）。board_part を当てると part が `-2` に引き戻される（WARNING: Project 1-153）ので、`-1` のビルドに PS のプリセットが無かった
- **`tools/dump_ps_preset.tcl`（`make ps-preset`）**: board_part の在る `-2` のプロジェクトで apply_board_preset した PS と、board_part の無い `-1` のプロジェクトで作っただけの PS の
  CONFIG.* を比べ、違うものを `-1` の PS に当てて読み返し、一致したものを `src/ps_preset.tcl` の `ps_preset`、一致しないもの（導出される・読み出し専用）を `ps_preset_derived` に書く
- **build.tcl**: 既定の part を `-1` に。`-1` で `src/ps_preset.tcl` が在れば、PS を作った直後に `ps_preset` を当てて全部読み返す（1 つでも違えば止める）。`ps_preset_derived` も読み返して違う数を出す。
  BUILD_TAG の [30] は「PS にプリセット（board_part か ps_preset.tcl）」。ps_preset.tcl が無ければ従来どおりの検証ビルド（[30] = 0、実機に使わない）
- **Makefile**: `make` → build/（`-1`）。`-2` は `PART=xczu48dr-ffvg1517-2-e` → build-2-e/。`timing-check` は `make` と同じ（互換）
- 手順: Vivado サーバで `make ps-preset` → `src/ps_preset.tcl` を見てコミット → `make`。**済み**（下）
- 確かめたいこと: `-1` ＋ ps_preset の .bit で PYNQ が PS を正しく動かす（Overlay・クロック・DDR）。`-2` の build-2-e/ の .hwh の PS の設定と比べる

### `-1` ＋ PS のプリセットのビルド（2026-10-01〜02、Vivado サーバ）

**PS のプリセット（`make ps-preset`、ae35bc7）**: 違う CONFIG のうち、当てる 225 個・導出される 13 個・`-1` の上限で外した 4 組 22 個
（DDR の 2 組: DDR4-2400 は `-1` で不可、ADMA_REF・LPD_SWITCH: 533 MHz が上限 500 MHz を超える）。導出される 13 個は DDR（800 MHz・上位 2 GB が無効）と、
外した組に引きずられた RPLL・DP・IOU_SWITCH の分周。**どれも FSBL が設定するもの**で、PYNQ が Overlay で書き換えるのは PL クロックの分周だけ
（PL0 は IOPLL ÷ 15 = 100 MHz でプリセットどおり）。ビルドのログ: `PS PRESET : 当てた 225 個のうち違う 0 個 / 導出される 13 個のうち違う 13 個`

**合成が Vivado ごと落ちる（segfault）**: 4 回のビルドで 7 個の OOC の run（win_core・gb_*・rst_dsp）。落ちる run は毎回違い、
スタックは synth_design の後片付け（`HARTNDb::resetGlobals` → `sta::LibertyCell::~LibertyCell`）か、並列合成の task_worker。OOM・MCE の跡は無い。
Vivado 2024.1 の不具合と読み、build.tcl で受ける（a11f6fa まで）: OOC の run を先に作って回し、**run のディレクトリの印**（`.vivado.end.rst` / `.vivado.error.rst`）で
状態を読み、runme.log に落ちた印（`Abnormal program termination` / `segfault in`）のある run だけを最大 2 回回し直す。
- 踏んだ穴: **Vivado の run のオブジェクトをリストから取り出すと名前の文字列になり、`get_property` が受け付けない**
  （`Invalid option value '…_synth_1' specified for 'object'`）。run は名前で持ち、Vivado へは `[get_runs $n]` をその場で渡す。
  `get_board_parts` の結果も close_project の後に文字にすると `null` になった（4656fa5）

**タイミング（`-1`、clk_out2 = 256 MHz）**:

| 版 | 実装の戦略 | WNS | WHS | 備考 |
|---|---|---|---|---|
| rev1 | 既定 | −0.767 | | 群 S・P・F・R |
| rev2 | 既定 | −0.199 | 0.000 | 予言 −0.3〜+0.1。worst-paths: 200 本中 191 本が配線の型、win_core 4 個・spec_core・SmartConnect に散る |
| rev2 | Performance_ExplorePostRoutePhysOpt | −0.041 | +0.010 | build-PEPRPO/ |
| rev2 | Performance_NetDelay_high | −0.839 | +0.010 | build-PND/。かえって悪い |
| **rev3** | **Performance_ExplorePostRoutePhysOpt** | **0.000** | **0.000** | 予言 −0.02〜+0.08 の下端。**閉じた（余裕は無い）**。CRITICAL WARNING なし |

- rev3（e274e7e、ID 0x0015_0300 / 0x0015_A300）: rev2 の worst-paths の群のうち 3 つを RTL で区切った（値は同じ）。
  X: 読み出しの候補を毎クロック 1 段のレジスタで受ける（応答が 1 クロック遅れる）／Y: LO の読みで HI を固定するのを ar_go の 1 クロック後に ar_addr で／
  W: wspec で SHIFT を受け直す（max_fanout 16）
- 資源（rev3）: DSP 3416（80.0 %）・BRAM 553（51.2 %）・URAM 32・LUT 69.0 %・FF 55.8 %。rev2 から LUT +0.7 k・FF +1.3 k
- sim（rev3）: sim-wspec（クラウド）・sim-top・sim-win4（Vivado サーバ、2026-10-02）とも「結果: 全部通過」。sim-win4 は rev3 の ID（0x0015_0300・0x0015_A300）の読み返しを含む

### 実機（rev3、build-PEPRPO/、2026-10-02）

- **PS のクロック**（Overlay の後）: `Clocks.fclk0_mhz` = 99.999（PL0_REF_CTRL = IOPLL ÷ 15 ÷ 1、IOPLL の FBDIV 90 = 1500 MHz、.hwh の ACT_FREQMHZ 99.999985）。
  `cpu_mhz` = 1199.988（FSBL の設定。Overlay で変わらない。1200 MHz は `-1` の APU の上限でもある）。.hwh の DDR は 400 MHz（`-1` で外した組の印。実際の DDR は FSBL）
- **W-0**（`window.py --probe`、16 窓）: 16 窓とも `RESULT OK`・NG 0。ID 0x0015_0300、BUILD 0x50c0000{0..3}（プリセット あり・`-1`・窓・ch = ADC の番号）
- **W-G**（`--golden`、雑音）: 1 回目は SHIFT 4（`--shift` を付けず既定）で **16 窓 ＋ 8・4・2 MHz とも NG 1**（4096 ch のうち 18 ch ほどが許容を超えた。
  最悪 ch 365: 差 2.8 / 振幅 156。スナップショットのフレーム = ダンプの f0 は一致）。枠のずれなら proj014 の 2 回目のようにほぼ全 ch が大きく外れるはずなので、
  **判定の条件の違い**と読んだ: proj014 は `--shift 7` で通していた。SHIFT が 3 小さいと比べる値が 8 倍に拡大され、FFT IP の中の丸め（numpy の倍精度に無い）が許容を超える
- 予言（測る前）: `--shift 7` で 20 回とも超えた ch 0・最悪の差 ≦ 1.5。**結果: 一致**。16 窓 × 256 MHz・ADC_B の窓 0〜3 × 8・4・2・4 MHz の 20 回とも `RESULT OK`・
  超えた ch 0・最悪の差 1.3〜1.4（振幅 3〜62）。→ window.py の `--golden` の既定の SHIFT を 7 にした（`--shift` で上書きできる）
- **W-1・W-1b・W-6**（16 窓 × 256 MHz、SG 3010.5 MHz・−20 dBm を雑音源と混ぜて 4 ADC に、ボードと SG は水素メーザー由来の 10 MHz、SHIFT 11 / 8）:
  - 1 回目は **SG の宛先（RFSOC_SG）を root のシェルに入れ忘れ**、CW が無いまま測った: 16 窓とも窓の最大の ch が 3072 MHz（k·fs/8 の線）か 2949.125 MHz、
    全帯域の「山」は 2168〜2174 ch を動き、W-6 は 0.22〜2.2 にばらつく（雑音の山どうしの比）。**窓の誤りなら 16 窓・4 ADC でそろって外れることはない**と読んで SG を疑った
  - 予言（測る前）: W-1 は 16 窓とも ch 3928、W-1b ±3 kHz、W-6 ±0.1 dB、飽和 0。**結果: 一致**。16 窓とも `RESULT OK`、W-1 は ch 3928（IF 3010.500000 MHz）、
    W-1b は +2.18〜+2.51 / −2.19〜−2.51 kHz（全帯域の推定の床。proj014 の +2.2 kHz と同じ）、W-6 は −0.017〜0.000 dB（比 0.9961〜1.0000）
- **8・4・2 MHz**（ADC_B の窓 0〜2、IF 3010、同じ SG）: 3 つとも `RESULT OK`・飽和 0。W-1 は予言の ch（8 MHz 3840・4 MHz 3584・2 MHz 3072、IF 3010.500000 MHz）、
  W-1b は ±2.35 kHz、W-6 は 8 MHz +0.011 dB（比 1.003）・**4 MHz +0.002 dB（比 4.001、予言 4）・2 MHz +0.003 dB（比 4.002、予言 4）**。
  **NS ≧ 7 で FFT の入力の小数 G を 5 にした分（4^(G−4) = 4）が、予言どおり電力の比に出た**。ダンプの FLAGS[4]（IP に待たされた）は proj014 の 8 MHz と同じ（判定の外）
- **4・2 MHz の W-2・W-3・W-5**（`sh winwidths.sh narrow`: 4・3050 / 2・2980 / 4・4090 / 2・2050）: 7 / 8 が通過。**2 MHz・IF 2050（窓の上端が fs/2 の 1 MHz 手前）の W-2 だけ NG**
  （p-p 1.22 dB・模型との差 0.69 dB。回し直しても 1.31 / 0.98 dB で再現）。点ごとに見ると、**外れたのは全帯域の ch のちょうど境目（f / 0.5 MHz の端数 0.50）の 4 点だけ**
  （ν = −0.75・−0.25・+0.25・+0.75 MHz で −0.10・+0.52・+0.46・−0.69 dB）、残りの 51 点は模型と ±0.04 dB 以内。
  読み: W-2 の基準は全帯域の最寄りの ch を 1/sinc²(端数) で戻した値で、境目では −3.9 dB の谷を戻す。fs/2 の近くでは実数の入力の像（2·fs/2 − f、7 ch ほど先）の漏れが
  同じ ch に重なり（振幅比 ≈ 0.07 → ±0.6 dB）、戻し方が狂う。IF 2980 の 2 MHz は境目の点を含むが像が遠く通過、proj014 の 8 MHz・IF 2052 は CW を全帯域の格子に置いていた
  （境目の点が無い）。**窓の側ではなく W-2 の基準の問題** → winsweep.py は全帯域の ch の端数 |df| > 0.4 の点を置かない（4 点減る）

## 結果

### 手順 1（2026-09-30、クラウドの作業環境: iverilog 12.0・numpy 2.4.4）

| 試験 | 結果 |
|---|---|
| `make coef` | proj014 と同じ生成物（`cmp` で一致、Mac） |
| `make model`（8 通りの幅） | **全部通過**。4 MHz: 平坦さ 0.021 dB・主以外 −61.0 dB、2 MHz: 0.020 dB・−61.0 dB（どちらも 89 か所）。層 2 も一致 |
| `make fixed` | **全部通過**。N1 誤差 4 MHz 2.7〜2.8e-4・2 MHz 5.4〜5.5e-4（G = 5）、8 MHz 5.1〜5.2e-4（G = 4）。飽和 0。C1 の線 ≦ −85 dBc |
| `make fixed-posctl` | 陽性対照: N1 が 24 件落ちた（G・G_HI = 0）→ 通過 |
| `make sim-ddc` | **32 通り（NS 1..8 × d 2 × 途切れ 2）とも 1 LSB も違わない**。NS 7: 984 個・NS 8: 472 個 |
| `make sim-ddc-p` | 陽性対照（NCO の番地をずらす）: 32 件とも不一致 → 通過 |
| `make sim-win` | **8 通りとも一致**（NS 7: 216 個・NS 8: 88 個） |
| `make sim-win-g` | 陽性対照（G の切り替えを外す）: 落ちたのは NS 7・8 だけ → 通過 |
| `make sim-top`（NS 1、AXI 越し） | **総合: 全部通過**。z 52,682 個が一致・ダンプ 3 個が bit 単位・ID 0x00150100・WNS 7 / 8 → NS 7 / 8・G 5、9 / 0 → NS 1・G 4 |

- NS 8 の出力が NS 6 と同じ数（入力 4 倍・幅 1/4）なので、2 MHz でも照合の点数は proj014 の 8 MHz と同じ

### 手順 2（2026-09-30、同じ作業環境）

| 試験 | 結果 |
|---|---|
| `make sim-hb2s` | **一致 8 通り**（light C 1・2・4・5・8、final C 2・4・18。20,000 組、飽和の回数も同じ）・**陽性対照 2 通り**（C 4・間隔 3、C 2・間隔 1）で ovr が立って不一致 → 通過 |
| `make sim-ddc` | **32 通りとも一致・時分割の追い越し 0** |
| `make sim-win` | **8 通りとも一致・追い越し 0** |
| `make sim-win-ts` | 陽性対照: 落ちたのは NS 3..8 だけ（追い越し 1541 回）→ 通過 |
| `make sim-top`（NS 1） | 総合: 全部通過（FLAGS[10] = 0 も含む。NS 1 は light を使わないので hb2s は通らない） |

- TS パラメータ（既定 1）を足した後に sim-ddc（32 通り・追い越し 0）・sim-win（8 通り）を回し直して通過
- **`make ooc-ddc`（Vivado サーバ、2026-09-30）: TS 0 = 114・TS 1 = 72 DSP で予言どおり**。1 回目の表は 1026・648 と出たが、合成後の DSP48E2 が 9 個の下位セル（DSP_ALU・DSP_MULTIPLIER など）に展開されていて、`ARITHMETIC.DSP.*` で数えると 1 個が 9 に出ていた（1026 / 9 = 114、648 / 9 = 72）。LUT・FF も 0 と出た → report_utilization の表から読むように直した（取り直せば LUT・FF も出る）
- **資源（見当）**: 時分割なしの ddc は light 2 段ぶん +20 DSP（94 → 114）。ビルドはしていない（手順 2 の時分割と合わせてから）

### 手順 3・4（2026-09-30、クラウドの作業環境）

| 試験 | 結果 |
|---|---|
| `make sim-pfb`（NW = 1 の回帰、16 通り）・`sim-pfb-p` | 通過・陽性対照が落ちた |
| `make sim-pfbm`（4 窓: k 5・0・16・9、始まり q_s 5・5・301・100 → 打ち直し 900） | **3 変種（途切れ なし / あり、ビートの番号 8 bit）とも全部の区切りが模型と一致**。打ち直しで切れた区切りのフレーム数も範囲内 |
| `make sim-pfbm-p`（陽性対照: 偶奇を窓の始まりで揃えない） | q_s が偶数の窓 3 の 2 つの区切りだけ NG（q_s が奇数の窓・k ≡ 0 (mod 4) の窓は合う）→ 通過 |
| `make sim-win`（新しい pfb_core で 8 通り） | 通過 |
| `make sim-top`（NW = 1、AXI 越し。共有のスナップショットの経路も通る） | **総合: 全部通過** |
| `make sim-win4`（1 ADC × 4 窓、AXI 越し、1 時間級） | 1 回目: **4 窓とも z が模型と bit 単位で一致**（窓 0・1・2 は入力の途中の WRST から、窓 3 は入力の前から）・**窓 1 のスナップショット（SNAP_SEL 1）= z のフレーム 7**・選んでいない窓 0 の範囲は 0・**total power 12 個とも Σx² が一致し、TP_RUN の後は F0 41 + 8n に揃う**・レジスタも全部 OK。ただし道具の誤り 2 件で判定が NG / 止まった（下）→ 直して回し直し中 |

- sim-win4 の道具の誤り: (1) **ハードのリセットの後、窓は既定の設定（WK 0・WNS 1）で回っている**ので、z の記録の頭に WRST の前の z が入り、模型と頭が合わなかった
  （z の中で模型の頭を探すと、WRST の後の全部が一致した）→ tb が窓の w_rst の立ち上がりで「# W」を書き、照合は最後の「# W」の後だけ
  (2) total power のリングの書いていない番地が sim では x で、読み込みで止まった → TP_WP の個数だけ読む

## 結論・次にやること

- [x] 手順 1: 4・2 MHz（模型・固定小数点・sim。ビルドは手順 2 と合わせて）
- [x] 手順 2: ddc_core の時分割（sim。DSP は `make ooc-ddc` で数える）
- [x] 手順 3: pfb_core を共有部分と窓ごとの部分に分ける（sim-pfbm。proj014 の 16.8 秒の巻き戻りも直した）
- [x] 手順 4（RTL と sim）: 1 ADC × 4 窓・ADC の total power・共有のスナップショット（sim-win4）
- [x] 手順 4（ビルド）: rev3 ＋ Performance_ExplorePostRoutePhysOpt で `-1` が WNS 0.000 ns（build-PEPRPO/）
- [x] rev3 の sim-top・sim-win4（全部通過）
- [x] PS 側（書いた、実機は未）: window.py などを win_core_i の窓 w（0x20000·w）と --adc / --win に、spectrometer.py を spec_core_0 ＋ FULL_SEL に
- [ ] 実機: 16 窓の W-0・W-G・W-1・W-6、4・2 MHz の W-2〜W-7、窓どうし・ADC 間の漏れ、読み出しの時間
- [ ] 手順 5: ビルド → 実機
- **proj016 以降の候補**（2026-09-30、西村さん）:
  - **窓を減らして分光点数を増やす**（例: 8 MHz × 16384 点 × 窓 1 つ / ADC）。1 ADC のメモリは「窓の数 × 点数」でほぼ決まる（16384 点で窓 1 つあたり BRAM ≒ 128・URAM 8 の見当）。FFT IP の 8192 / 16384 点は先に `make survey` で数える
  - **最小積分時間を 0.1 秒より短くする**（場合によっては分光点数を減らす）。読み出し（今は AXI4-Lite で 16 窓 ≒ 34 ms / 100 ms）が先に律速になる → DMA

## 再現手順

```bash
make model          # 仕様の模型（numpy だけ）
make fixed          # 固定小数点の模型
make sim-all        # sim を全部と陽性対照。各ログの「結果: 全部通過」で読む
make                # 合成〜ビットストリーム（Vivado サーバ）
make timing-check   # `-1` でも閉じるか
```

環境は [`../VERSIONS.md`](../VERSIONS.md)、詰まったときは
[`../proj001/docs/runbook.md`](../proj001/docs/runbook.md)。

# proj021 — インターフェース v2 を SAM45-Fine の上で（手順 0 測る・1 群 C・2 v2）

日付: 2026-10-08（起こし）
状態: 進行中（手順 0）

## 目的

**リポジトリの根元の [`INTERFACE.md`](../INTERFACE.md)（v2、2026-10-08 決定）を SAM45-Fine（proj020 = PFB T = 4 の窓）の上で作り、9 本の bit で使い回せる PL ↔ PS ↔ 制御 PC の約束が実機で成り立つことを確かめる。**

- 作るもの: 流れとコア・自己記述（INTERFACE の 2.・3.）、PL が書くリングと尾の CRC（4.）、TP と SNAP のレコード（4.6）、PL のダンプ 10.24 ms・specd の束ねと時刻（5.1・5.2）、LOAD、s45proto v2（float32）
- **proj021 の最後の形を、製品リポジトリへの移植の土台にする**（2026-10-08 の相談。proj020 からは移さない）。製品リポジトリへの移植では構成替えだけを行い、合否は「proj021 と同じものができること」（sim の bit 単位の一致・CDC の分類ごとの件数・BRAM・DSP。WNS では見ない）

経緯: 2026-10-08 の決定「次の proj021 はインターフェース v2 を SAM45-Fine の上で作る」（リポジトリ外の作業記録）・INTERFACE.md の 2.〜5. の決定・同日の相談（リポジトリを 2 つに分ける・変更は一度に一つ）

## 手順（変更は一度に一つ。手順ごとに commit を分ける）

| 手順 | 中身 | PL | 確かめること |
|---|---|---|---|
| **0** | PL を変えずに、PS とネットワークの量を測る（proj020.bit のまま） | 変えない | M-1〜M-5（下）。リングの大きさ・CRC を全部確かめるか間引くか・HP0 か HPC0 か・予算を決める |
| **1a** | ソースを共通部分と bit 個別に分ける（構成替えだけ。ID も変えない） | 同じ RTL | **build-PE の WNS・WHS が proj020 と小数 6 桁まで同じ**（+0.047121 / +0.009645）・CDC の分類ごとの件数・BRAM・DSP。実機には載せない |
| **1b** | 群 C を直す（gb_fifo と gb_gate の間に AXI4-Stream のレジスタスライス） | ギアボックスだけ | G-1〜G-4（下） |
| **2** | v2 | 流れ・リング・自己記述 | 判定 V2-a〜V2-g（下）・F-2 |

手順 1b と 2 で `-1` が閉じなかったとき、原因をその手順の変更だけに絞れるよう、1b のビルドと確かめを 2 の RTL より先に終える。

## 手順 0 — 測る（PL は proj020.bit のまま）

**測る前に予言を書く。** 外れた予言は残す。

| 判定 | 何を | 道具 | 予言（2026-10-08） | 決まること |
|---|---|---|---|---|
| M-1 | 1 GbE の実効（ボード → ダウンロード PC、TCP） | iperf3 30 s × 5 回（`-R` も） | 110〜117 MB/s（940 Mbit/s 前後） | 予算 = 実測の 70 %（INTERFACE 4.5）。SpW6（76.8 MB/s）が入るか |
| M-2 | ボードの CMA の大きさと、allocate で取れる最大 | `grep Cma /proc/meminfo`・allocate を倍々に | 未知（見当なし） | リングの大きさ（目安: 1 s 以上の止まりを吸収。SAM45-Fine 32 MiB・256M 256 MiB） |
| M-3 | allocate したバッファを numpy で読む速さ（キャッシュあり＋invalidate / キャッシュなし） | `pynq/bench_ps.py`（新規） | キャッシュありは 1 GB/s 以上、キャッシュなしは数百 MB/s 以下 | HP0（キャッシュあり＋invalidate）か HPC0（一方向のコヒーレンシ）か。205 MB/s を読めるか |
| M-4 | CRC-32（zlib.crc32）の速さ | 同上 | 300〜600 MB/s（A53 で zlib は CRC 命令を使わない見当） | 全部のレコードで確かめるか、間引くか（INTERFACE 4.6） |
| M-5 | 束ね（u64 の和）＋ float32 への丸め ＋ 送り出しの 1 周 | 同上（SAM45-Fine の 8 流れ × 4096 ch と、256M の 4 流れ × 65536 ch を模して） | SAM45-Fine は 10.24 ms に対して 1 ms 以下、256M は 3〜6 ms | specd の取得を Python のまま行けるか（proj018 の「C に移す基準」と同じ考え方） |

- M-3〜M-5 は PL を使わない（allocate したバッファに試験の値を書いて読む）。ボードで specd を止めて測る
- 結果の書き方は判定の表の形（下の「判定の書き方」）

## 手順 1a — ソースの分け方（案）

製品リポジトリへほぼ機械的に写せるように、proj021 の中で分けて置く。**proj021 の自己完結は保つ**（上の階層を参照しない）。

| 置き場 | 中身（案） | 理由 |
|---|---|---|
| `src/common/` | time_core・dstamp・adc_ev・gb_adc・gb_gate・tp_core・spec_core（cmul・dft16・tw_rom）・win_core・pfb_core・ddc_core（hb2・hb2s・pair2・nco_rom）・wspec_core・axis_sel4、v2 で足すもの（流れのブロック・リングの司令・切り替え器） | どの bit も使う、または使いうる |
| `src/sam45fine/` | このbit の組み立て（コアごとの流れの並び・BIT_KIND = 2・NW・N_ACC の既定）・pfb4_rom / win_coef（係数の表、原型を変える bit が出たら分ける）・fft_cfg.tcl | bit ごとに変わる |
| `src/board/`（案） | timing.xdc・pps.xdc・ps_preset.tcl | ボード（RFSoC4x2）に固有で、bit に依らない |

- 境目の決め方: **「別の bit で中身が変わるか」**。迷ったら sam45fine に置き、2 本目の bit（SAM45-Wide）で共通に上げる
- 1a は構成替えだけなので、**ID・BUILD_TAG・係数も含めて RTL は proj020 と同じ**。WNS が小数 6 桁まで同じなら、構成替えで何も変わっていない（同じ RTL の作り直しは WNS まで再現する、の規約）

## 手順 1b — 群 C

proj020 の README「ビルド rev1」: 群 C = gb_gate の armed → `armed & gb_dn の tready` → gb_fifo（XPM の FIFO）の読み出しの許可 enb、**ファンアウト 780**（768 bit の出口レジスタ）。

- 直し方（案）: ch ごとに gb_fifo と gb_gate の間に AXI4-Stream のレジスタスライスを 1 段（build.tcl で置き、照合を足す）。enb を駆動するのが LUT の AND ではなくスライスの FF になり、複製が効きやすくなる
- 起動の対策（proj011 rev6）への影響: 起動の後、スライスが 2 語を先に取り込み、FIFO に K 語溜まるまで gb_gate が止める。溜まる語は K ＋ 2、FIFO の余裕は K − 1 語のまま（見込み。sim と実機で確かめる）
- ギアボックスの遅れが 1〜2 ビート変わり、adc_to_core（M）が数 ns 動く → F-2 は手順 2 の Overlay でどのみち測り直す

| 判定 | 何を | 合格 |
|---|---|---|
| G-1 | `make sim-gearbox`（tb_gearbox.v。起動の空振りの陽性対照を含む） | 全部通過・陽性対照が立つ |
| G-2 | ビルド（`-1`、既定と PE） | 群 C の経路の最悪 slack が proj020 の −0.063 から改善する（**予言は 1b に着手するときに書く**）。CDC の分類ごとの件数が proj020 と同じ（スライスは同じクロックの中なので増えない） |
| G-3 | 実機: GRST による起動を多数回（proj011 rev6 の道具） | 空振り（gb_stat の under）0・TLAST 事象 0。回数は 1b に着手するときに決める（まれな事象は起動の回数で数える） |
| G-4 | 実機: INJ の陽性対照 | 見張りが立つ |

## 手順 2 — v2 の判定

INTERFACE.md の 9. の (a)〜(g) を、製品リポジトリの `test/acceptance/` にそのまま移せる形で書く（下の「判定の書き方」）。中身は手順 2 に着手するときに埋める。

| 判定 | 中身（INTERFACE 9.） |
|---|---|
| V2-a | 同じ設定の 2 窓（PL で 10.24 ms と 40.96 ms）で、specd が束ねた 4 個 = PL の 1 個が整数で一致 |
| V2-b | F-4 を 10.24 ms で 30 分: 読み落とし 0・DROP_CNT 0・CRC の不一致 0・PEAK・PS の負荷 |
| V2-c | proj020 の P-1・P-2（W-G を REC_CTRL の ONE \| SNAP で）・P-5 の回帰 |
| V2-d | LOAD で proj020.bit ↔ proj021.bit を往復し、錨・CAL が切り替わる |
| V2-e | TP のレコードと AXI4-Lite の TP のリングが、同じ区切りで bit 単位で一致 |
| V2-f | 5.1 の見張り（DUMP_T − m·BASE が一定）が FULL・DDC の全部の流れで通る |
| V2-g | 陽性対照: PS の読みをわざと止めて溢れさせ、DROP_CNT と SEQ の飛びが一致する／キャッシュを捨てずに読む変種で CRC の不一致が立つ |

同時にやること（INTERFACE 8.）: spec_core（FULL）の F0 を時刻の格子に寄せる（8. の 8）・sim-wdelay を PFB 入りの RTL で出し直す（8. の 9）・F-2

## 判定の書き方（`test/acceptance/` に移せる形）

判定 1 つにつき、次の 6 項目を書く。**環境に依る値（ホスト名・IP アドレス・パス）は書かない**（公開を前提にする）。

| 項目 | 中身 |
|---|---|
| ID | M-1・G-2・V2-a など（製品リポジトリでも同じ ID を使う） |
| 前提 | 載せる .bit（ID・rev）・接続（SG・減衰器・ケーブル。VERSIONS.md の規約）・specd の設定 |
| 手順 | 実行するコマンド（道具と引数） |
| 合格 | 数値の条件。**測る前に書く** |
| 陽性対照 | 見張りが壊れていないことの確かめ（あれば） |
| 記録 | 結果のファイル（runs/）と README の結果の行 |

## 検討事項（決定ではない）

1. **製品の版を .bit に貼る場所**（2026-10-08 の相談の 2.）
   - 今の IF_ID には BIT_KIND・BIT_REV があり、BUILD には build.tcl の指紋（プリセット・速度グレード・ch）がある。**リリースのタグや commit は無い**
   - **RTL の定数（BUILD_TAG のような generic）に commit を入れると、commit ごとに配置が組み替わり「同じ RTL の作り直しは WNS まで再現する」が崩れる**
   - 案: **USR_ACCESSE2**（UltraScale+ の構成の原語）。write_bitstream の `BITSTREAM.CONFIG.USR_ACCESS` で 32 bit を焼き込み、PL は USR_ACCESSE2 の出力をコアの共通部の予約の番地で読むだけ。値は配置・配線の後に入るので、配置を変えない（確かめる: 同じ RTL で USR_ACCESS だけ違う 2 本の WNS が一致すること）
   - 32 bit に何を入れるか（commit の短いハッシュ 28 bit ＋ 汚れ 1 bit など）、bits.json の sha256 との役割分担、IF_ID の BIT_REV との関係は、製品リポジトリのリリースの手順と合わせて決める
2. 1a の境目（common / sam45fine / board）の細部は、SAM45-Wide（2 本目）で見直す

## やったこと

- 2026-10-08: proj020 の追跡されているファイルを複製（`runs/` と README を除く。RTL・build.tcl・Makefile・pynq は proj020 のまま、ID も 0x0020 系のまま）。README を起こした

## 結果

（まだ）

## 結論・次にやること

- 手順 0: `pynq/bench_ps.py` を書き、M-1〜M-5 を測る

## 公開について

study-rfsoc は公開リポジトリ。commit・push の前に、公開前のスキャン（リポジトリ外の手順書）の全項目を機械的に行う。
**コミットメッセージに `Claude-Session:` の行や URL を入れない**（`Co-Authored-By` の行は可）。

## 再現手順

手順 0 は PL を変えないので、ビルドは要らない（proj020 の build-PE の .bit・.hwh を使う）。手順 1a 以降で書く。

環境は [`../VERSIONS.md`](../VERSIONS.md)、詰まったときは [`../proj001/docs/runbook.md`](../proj001/docs/runbook.md)。

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

### 手順 0 の測り方（2026-10-08）

ボードは PL を変えない（proj020 の Overlay が載っていてもいなくてもよい。M-2〜M-5 は PL に触らない）。

**0. 前準備**

```bash
# Mac
scp proj021/pynq/bench_ps.py xilinx@<board>:~/proj021/

# 制御 PC: specd を止める（同じ A53 を取り合うと数が意味を持たない）
python3 specctl.py --host <board> SHUTDOWN confirm=1

# ボード: 止まったこと・測るときの状態を残す
pgrep -af 'specd|s45acq' || echo "止まっている"
mkdir -p ~/proj021/runs && cd ~/proj021
{ uname -a; grep -i cma /proc/meminfo; free -m
  cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
  pip list 2>/dev/null | grep -i -E '^pynq|^numpy'; } > runs/m0_env.txt 2>&1
```

**1. M-1（1 GbE の実効）** — 運転と同じ経路（同じスイッチ・ケーブル・ダウンロード PC の NIC）で測る

```bash
# ダウンロード PC
iperf3 -s

# ボード（iperf3 が無ければ sudo apt install iperf3）
for i in 1 2 3 4 5; do iperf3 -c <PC> -t 30 -J > runs/m1_tx_$i.json; done       # ボード → PC（送り出しの向き。これが予算）
for i in 1 2 3 4 5; do iperf3 -c <PC> -t 30 -R -J > runs/m1_rx_$i.json; done    # PC → ボード（参考）
for f in runs/m1_*.json; do python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(sys.argv[1], round(d['end']['sum_received']['bits_per_second']/8e6,1), 'MB/s')" $f; done
```

**2. M-2〜M-5（1 回目）**

```bash
sudo -E $(which python3) bench_ps.py --out runs/bench_ps_1.json 2>&1 | tee runs/bench_ps_1.log
```

**3. 陽性対照（CRC の見張りが働くこと）**

```bash
sudo -E $(which python3) bench_ps.py --only m5 --corrupt --m5-rep 3 --out runs/bench_ps_corrupt.json 2>&1 | tee runs/bench_ps_corrupt.log
```

合格: どの構成でも「不一致 3」（壊したレコード 1 つ × 3 周）。0 なら見張りが壊れている（他の結果も読まない）

**4. リングを大きくしたとき（invalidate がバッファ全体にかかる重さ）**

```bash
# 2026-10-08: 256 は CMA（128 MiB）を越えて落ちた（手順の誤り）。invalidate の重さは M-3 から読む
sudo -E $(which python3) bench_ps.py --only m3 m5 --buf-mib 256 --out runs/bench_ps_256m.json 2>&1 | tee runs/bench_ps_256m.log
```

**5. 間引いたときの見当と、2 回目（揺れを見る）**

```bash
sudo -E $(which python3) bench_ps.py --only m5 --no-crc --out runs/bench_ps_nocrc.json 2>&1 | tee runs/bench_ps_nocrc.log
sudo -E $(which python3) bench_ps.py --out runs/bench_ps_2.json 2>&1 | tee runs/bench_ps_2.log
```

**6. 後片付け**: 制御 PC から specd を起動し直す（`sudo -E $(which python3) specd.py --clkin 0 --ref 10`）。runs/ を Mac へ持ち帰り、下の決め方で結果の表を埋める

**決め方（測る前に書く、2026-10-08）**

| 決めること | 規則 |
|---|---|
| ネットワークの予算 | M-1 のボード → PC の 5 回の中央値 × 0.7。SpW6（float32 で 76.8 MB/s）が入らなければ、BITS.md の制限に SpW6 を足す |
| リングの大きさ | 1 s 以上の止まりを吸収（SAM45-Fine 32 MiB・256M 256 MiB）。M-2 の allocate の最大がそれに届かなければ、CMA を広げる（ボードの設定）か目安を下げる |
| HP0 か HPC0 か | 4. の 256 MiB で M-5 の 256m の p99 が 5 ms（BASE の半分）以下なら HP0（キャッシュあり＋invalidate）。超えるなら HPC0（一方向のコヒーレンシで invalidate を要らなくする）か、範囲を絞った invalidate を自分で書く |
| CRC を全部で確かめるか | 2. の M-5 で全構成の p99 が 5 ms 以下なら全部。超える構成は間引き、5. の --no-crc との差で間引きの率を決める |
| 取得を Python のままにするか | M-5 で全構成の平均が 10.24 ms の 50 % 以下・最大が 10.24 ms 未満なら Python のまま（proj018 の「C に移す基準」と同じ考え方）。超えるなら取得の環を C に |
| 陽性対照 | 3. で不一致 3 が出なければ、ほかの結果を使わない |

**記録**: runs/m0_env.txt・m1_*.json・bench_ps_*.json / .log。README の結果に、M-1〜M-5 の値と上の決め方で決まったことを書く

## 手順 1a — ソースの分け方

製品リポジトリへほぼ機械的に写せるように、proj021 の中で分けて置く。**proj021 の自己完結は保つ**（上の階層を参照しない）。

| 置き場 | 中身 | 理由 |
|---|---|---|
| `src/common/` | time_core・dstamp・adc_ev・gb_adc・gb_gate・tp_core・spec_core（cmul・dft16・tw_rom）・win_core・pfb_core・ddc_core（hb2・hb2s・pair2・nco_rom）・**win_coef.vh**（粗い PFB と DDC の係数。pfb_core・ddc_core が include する）・wspec_core・axis_sel4、v2 で足すもの（流れのブロック・リングの司令・切り替え器） | どの bit も使う、または使いうる |
| `src/sam45fine/` | **pfb4_rom.v**（窓の精細 PFB T = 4 の係数。4096 点に結びつく）・**fft_cfg.tcl**、v2 で足すこの bit の組み立て（コアごとの流れの並び・BIT_KIND = 2） | bit ごとに変わる |
| `src/board/` | timing.xdc・pps.xdc・ps_preset.tcl | ボード（RFSoC4x2）に固有で、bit に依らない |

- 境目の決め方: **「別の bit で中身が変わるか」**。迷ったら sam45fine に置き、2 本目の bit（SAM45-Wide）で共通に上げる
- 2026-10-08 に分けた（commit 8264e62。`git mv` とパスの書き換え。RTL の中の変更はコメントの中のパスだけ。include の場所は `src/common`）。build.tcl の `set proj proj020` は変えていない（出力は proj020.bit のまま。1a は実機に載せない）
- 1a は構成替えだけなので、**ID・BUILD_TAG・係数も含めて RTL は proj020 と同じ**。**予言: build-PE の WNS・WHS が proj020 と小数 6 桁まで同じ（+0.047121 / +0.009645）**。同じなら、構成替えで何も変わっていない（同じ RTL の作り直しは WNS まで再現する、の規約）

### 1a の確かめ方

クラウドの iverilog で: Makefile・build.tcl・tools・pynq が指す `src/…` の 26 個がすべて在ること、sim の 25 ターゲットが iverilog でコンパイルできること、`make sim-gb`（全部通過）・`sim-time`（全部通過）・`sim-time-p`（陽性対照が落ちる）・`sim-tp`（全部通過）を確かめた（2026-10-08）。

Vivado サーバで（proj020 の build-PE/ と比べる。**実機には載せない**）:

```bash
cd ~/git/rfsoc && git pull && cd proj021 && pwd       # proj021 にいることを確かめる
make IMPL=Performance_Explore > /dev/null 2>&1 &       # → build-PE/
make > /dev/null 2>&1 &                                # → build/（既定の戦略。proj020 は −0.063）
wait
key() { grep -E 'TIMING \(確定\)|DSP48E2 全体|BRAM|URAM|^  (Unsafe|Unknown|Safely|No Common|Total)|CRITICAL WARNING' "$1" ; }
diff <(key ../proj020/build-PE/vivado.log) <(key build-PE/vivado.log) && echo "build-PE: 同じ"
diff <(key ../proj020/build/vivado.log)    <(key build/vivado.log)    && echo "build: 同じ"
```

合格: `diff` が何も出さない（WNS・WHS・CDC の分類ごとの件数・DSP・BRAM・URAM・CRITICAL WARNING が proj020 と同じ）。違ったら、どの行がどう違うかを残す（構成替えで何かが変わった証拠）

## 手順 1b — 群 C

proj020 の README「ビルド rev1」: 群 C = gb_gate の armed → `armed & gb_dn の tready` → gb_fifo（XPM の FIFO）の読み出しの許可 enb、**ファンアウト 780**（768 bit の出口レジスタ）。

**直し方（2026-10-08、commit dc69360）**: BD に IP を足すのではなく、**gb_gate.v の入口に 2 語のスキッドバッファ**（全部をレジスタで受ける AXI4-Stream のスライスと同じ働き）を書いた。
gb_fifo の m_axis_tready = `~v1`（FF そのもの）、armed は出口の valid にだけ効く、データの出口も FF。BD・build.tcl の配線は変えていない（gb_gate のポートは同じ）。
RTL に書いたので、起動の試験（sim-gb）がそのまま新しい形を通る。

- gb_stat[15:0]（空振り）は「出口（スキッド）が空なのに下流が欲しい」で数える（proj020 までは「FIFO が空」。どちらも下流の空振り）
- ID: win_core 0x0021_0100 / 0x0021_A100、spec_core 0x0021_01xx、time_core 0x0021_7101（中身は proj020 と同じ）。proj の名前も proj021（出力は proj021.bit）
- PS: spectrometer・window・timebase・specd の ID と .bit の名前を 0x0021 系に。**timebase.CAL 0x0021_7101 は未較正**（F-2 で測る）。tp_cal.json に 00210100 は足していない（specd は TP の dBm を出さない。TP の経路の利得は同じなので、確かめてから足す）
- sim の ID の照合（tb_time・tb_t4adc・tb_tsys・tb_top・check・check_top・check_win4）を 0x0021 系に。Makefile の `DCP` の既定が `proj016.runs` のままだったのを、proj の名前に依らない形に直した（`make worst-paths` で群 C を見るのに要る）

**予言（2026-10-08、1b の RTL を書く前）**: (1) 群 C は `-1`・既定の戦略で上位 200 本から消えるか、残っても最悪 slack ≧ +0.05 ns (2) 全体の WNS は既定で −0.07〜+0.05 ns（壁は残る u_pfb・u_ws、配置の運 ±0.1）、PE で 0〜+0.1 ns (3) CDC の分類ごとの件数は proj020 と同じ (4) FF が ≒ +6,100（768 bit × 2 段 × 4 ch）、LUT・BRAM・DSP・URAM は同じ (5) sim-gearbox の起動の試験は K ≧ 2 で途切れた起動 0（K 0 は今と同じく起きる） (6) ギアボックスの遅れ +2 語（+6 ビート ≒ +23 ns）、FIFO の余裕（残量の最小）は同じ

**sim（クラウドの iverilog 12、2026-10-08）**:

| sim | 結果 |
|---|---|
| sim-gb（K 0 / 2 / 4。K 2 を足した） | **全部通過**。K 0 の陽性対照は proj020 と同じ数（bit 2 +800 ps で 5 / 12、+1800 ps で 7 / 12、ばらばらで 5 / 12、途切れる語はどれも語 3）、K 2・4 は 0 / 12。古い gb_gate（proj020）でも同じ表（K 2 を足した tb で） |
| 遅れと余裕（tb に表示を足した一時の試験、同じ遅延の組） | 出口の遅れ（書き込みの通し番号 − 出口の通し番号）: K 0 / 2 / 4 で **3 / 6 / 8 語**（proj020 の gb_gate は 2 / 4 / 6）→ 運転の K 2 で **+2 語 = +6 ビート ≒ +23 ns**（予言 (6) どおり）。FIFO の残量の最小: **2 / 4（proj020 は 1 / 3）＝ 余裕が 1 語増えた**（予言 (6) の「同じ」は外れ、良い向き。スキッドが FIFO から先に 1 語引くぶん、FIFO の中に語が残る） |
| sim-time・sim-time-p | 通過・陽性対照が落ちる（ID 0x0021_7101） |
| sim-t4adc・sim-spec-all | （回している） |

| 判定 | 何を | 合格 |
|---|---|---|
| G-1 | `make sim-gb` | 上の表（**通過**） |
| G-2 | ビルド（`-1`、既定と PE）・`make worst-paths` | 予言 (1)〜(4) |
| G-3 | 実機: Overlay の読み込み直し 50 回（`pynq/gbboot.py`。**proj015 から GRST は無い**ので、起動は Overlay でしか起こせない） | 全部の回・4 ADC で armed・空振り 0・dwell の間に増えない・RFDC の valid の落ち 0・GB_K 2 |
| G-4 | 実機の陽性対照: `make GB_K=0` のビルドで同じく 50 回（**proj020 の README の G-4「INJ」は spec_core の入口に注入するもので、gb_gate を通らないのでやめた**） | 空振りのある起動が 1 回以上（proj011〜012 の K 0 と同じ形）。出なければ G-3 を「起動の途切れが無い」とは読まない |

**ビルド（Vivado サーバ、2026-10-08、dc69360）**:

| 戦略 | WNS | WHS | 予言 | 読み |
|---|---|---|---|---|
| 既定（build/） | **+0.007796** | +0.009534 | −0.07〜+0.05 | 当たり。**既定の戦略で `-1` が閉じた**（proj020 は −0.063186） |
| Performance_Explore（build-PE/） | **−0.128548** | +0.005292 | 0〜+0.1 | **外れ**。proj020 では PE が既定より +0.11 良かったが、今回は −0.14 悪い。戦略の良し悪しは配置の運の幅（±0.1）の中で入れ替わる → PE を「良い戦略」として固定しない |

- 実機には **build/（既定）** を載せる（閉じたほう）。群 C が消えたかは `make worst-paths` で見る（WNS は構造の指紋にならない）

### 1b のビルドと実機

```bash
# Vivado サーバ
cd ~/git/rfsoc && git pull && cd proj021 && pwd
make IMPL=Performance_Explore > /dev/null 2>&1 &        # → build-PE/（実機に載せる候補）
make > /dev/null 2>&1 &                                 # → build/（既定。群 C の比べ）
wait
grep BUILD_TAG build-PE/vivado.log | head -2            # 今の RTL が焼けたこと
grep -E 'TIMING \(確定\)' build/vivado.log build-PE/vivado.log
make worst-paths                                        # build/ の上位 200 本 → build/worst_paths/（群 C が残るか）
make GB_K=0 IMPL=Performance_Explore > /dev/null 2>&1 & # → build-k0-PE/（G-4 の陽性対照。実機の測定には使わない）

# ボード（build-PE の .bit・.hwh と pynq/ を送る。.bit は proj021.bit、陽性対照は proj021_k0.bit に名前を変えて）
sudo -E $(which python3) gbboot.py --loads 50 --clkin 0 --ref 10 --out runs/g3
sudo -E $(which python3) gbboot.py --loads 50 --clkin 0 --ref 10 --bitfile proj021_k0.bit --expect-k 0 --out runs/g4
```

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
- 2026-10-08: 手順 1a（構成替え、8264e62）→ Vivado サーバで build-PE の WNS / WHS が proj020 と小数 6 桁まで同じ（+0.047121 / +0.009645）、既定の戦略も −0.063186 / +0.009660。DSP 2600・BRAM 305（RAMB36 129・RAMB18 352）・URAM 56・LUT 48.16 %・CDC-3 105 / CDC-6 5 / CDC-15 3137・CRITICAL WARNING なしも proj020 と同じ → **1a 通過**（構成替えで何も変わっていない）
- 2026-10-08: 手順 1b（gb_gate のスキッド・ID 0x0021、dc69360）。sim-gb 通過（上の 1b の節）
- 2026-10-08: `pynq/bench_ps.py`（M-2〜M-5）を書いた。PYNQ の無い計算機で `--no-pynq --quick` が通ること、陽性対照（`--corrupt` で 1 バイト壊すと M-5 の不一致が周ごとに 1 件、`--no-crc` では 0 件）を確かめた。ボードではまだ走らせていない

## 結果

### 手順 0（2026-10-08、1 回目。specd を止めて、root で `bench_ps.py`）

| 判定 | 結果 | 予言 | 読み |
|---|---|---|---|
| M-1 ボード → PC | **25.3 MB/s**（5 回とも 25.3、202 Mbit/s） | 110〜117 MB/s | **外れ**。PC → ボード（`-R`）は 51.6〜52.1 MB/s。値が揃いすぎていて、線路ではなく何かの天井に当たっている。**どの経路（eth0 か USB の網か）で測ったか・リンクの速さ・CPU の周波数をまだ確かめていない** → 予算は保留 |
| M-2 CMA | CmaTotal 128 MiB（空き 116〜119 MiB）。allocate は 64 MiB まで取れ、128 MiB で失敗 | 見当なし | SAM45-Fine の目安 32 MiB は入る。256M の目安 256 MiB は入らない（CMA を広げる必要。256M を作るときに） |
| M-3 キャッシュあり | sum 2166〜2184 MB/s・copy 1999〜2008 MB/s・**invalidate だけ 4.65 ms / 64 MiB（0.073 ms / MiB）** | 1 GB/s 以上 | 当たり |
| M-3 キャッシュなし | sum 81.0 MB/s・copy 152.6〜152.9 MB/s | 数百 MB/s 以下 | 当たり（予言より 1 桁遅い）。**キャッシュなしは SAM45-Fine（25.7 MB/s）でも読むだけで A53 の 1/3 を使う → 使わない** |
| M-4 CRC-32 | 普通のメモリ 349.5〜349.6 MB/s・キャッシュあり 340.2〜340.3・キャッシュなし 55.8 | 300〜600 MB/s | 当たり |
| M-5 sam45fine（8 流れ × 4096 ch、n_sum 4） | 1 BASE 平均 3.88〜3.89 ms・p99 4.48〜4.50・最大 4.49〜4.51 ms（10.24 ms の 38 %）。CRC なしで 2.79・3.38・3.41 ms | 1 ms 以下 | **外れ**。データの量（263 KB / BASE）だけで見積もり、A53 の Python のレコードごとの手間を見ていなかった。差し引き: CRC 1.09 ms（量から 0.77 ms）・M-5 のバッファ（10.5 MiB）全体の invalidate ≒ 0.76 ms・残り ≒ 2.0 ms がレコード 8 個の Python の手間 |
| M-5 2g・256m・spw6（1 回目） | **出ていない**（ログが sam45fine の行で終わり、`→ runs/…` の行も無い。2 回とも同じ） | — | 解放した後のバッファを指す view が残っていた疑い。bench_ps.py を直して（構成ごと・faulthandler・解放の前に view を手放す）測り直した → 下 |
| 陽性対照（`--corrupt --m5-rep 3`） | 4 構成とも不一致 3 | 3 | 通過 |

**M-5 の測り直し**（直した bench_ps.py、`--only m5`。CRC あり）:

| 構成 | 1 BASE あたり | 平均 | p99 | 最大 | 10.24 ms に対して |
|---|---|---|---|---|---|
| sam45fine（8 × 4096、n_sum 4） | 0.26 MB | 3.88 ms | 4.49 | 4.50 | 38 % |
| 2g（2 × 65536、n_sum 1） | 1.05 MB | 9.62 | 9.73 | 10.08 | **94 %** |
| 256m（4 × 65536、n_sum 2） | 2.10 MB | 15.82 | 19.79 | 20.18 | **155 %** |
| spw6（24 × 8192、n_sum 1） | 1.57 MB | 19.56 | 19.69 | 19.78 | **191 %** |

- 当てはめ: 時間 ≒ 0.20 ms × レコードの数 ＋ 8.8 ms × MB（sam45fine と 2g から。spw6 の予言 18.5 ms / 実測 19.6）。**Python ＋ numpy の 1 本では全部で ≒ 114 MB/s**。重いのは量の側で、うち CRC（入りの確かめと送り出し）が半分前後
- **A53 は 4 コアあるが、この測りは 1 本**。2g より上は、取得を C にする（ARMv8 の CRC 命令・和と丸めと CRC を 1 回のなめで）か、流れをいくつかのプロセスに分けるかが要る（その bit を作るとき）

**M-1 の切り分け**（ボード → PC、宛先は事務の LAN の PC）:

| 測り | 結果 | 読み |
|---|---|---|
| TCP 1 本 | 25.3 MB/s・再送 0・cwnd 最大 239 KB・RTT 平均 4.8 ms | 同じ LAN で RTT 4.8 ms は長い → どこかに列ができている（落とされてはいない） |
| TCP 4 本（`-P 4`） | 合計 210 Mbit/s（52.6 × 4） | 1 本の窓の頭打ちではなく、全体の天井 |
| UDP 900 Mbit/s | 28.9 MB/s（231 Mbit/s）・損失 0 % | **送る側がそもそも 231 Mbit/s しか出せていない**（経路で捨てられたなら損失が出る）→ ボードの NIC の出口が ≒ 210〜230 Mbit/s で絞られている |
| PC → ボード（`-R`） | 51.6 MB/s・再送 10,894 | 受ける向きは 2 倍出るが、落とされている |
| ボードの CPU | iperf3 2.3 %・96.8 % 空き | CPU の頭打ちではない |
| リンク | eth0・1000 Mb/s・全二重 | 交渉は 1 GbE |

- 疑い（未確認）: スイッチからの PAUSE（フロー制御）・スイッチのポートの帯域制限・NIC のドライバ／PHY の問題・qdisc。**直結（ボード ↔ PC）か別のポートで測れば、ボード側かスイッチ側かが分かる**
- 1 ボードの予算の方針（案、2026-10-08 の相談）: 複数のボードを 1 台のダウンロード PC で受けるので、**1 ボード 100〜200 Mbps**が目安かもしれない → INTERFACE.md の 8. の 10。この予算なら、ボードの送り出しの頭打ち（≒ 230 Mbit/s）は差し支えない
- 予算（今の経路）: 25.3 × 0.7 = **17.7 MB/s**。SAM45-Fine（float32 で 3.2 MB/s）には足りる。2G・512M・SpW（51.2 MB/s 以上）は、この天井を外すまで入らない。**proj021 は止めない**（ネットワークの調べは別に進める）

**M-6（範囲を絞った invalidate）**: PYNQ 3.1.1 の `XrtDevice.invalidate(bo, offset, ptr, size)` は offset・size を**受け取るが使わず**、`bo.sync(FROM_DEVICE)` でバッファ全体を同期していた（M-3 の 0.073 ms / MiB はこれ）。pyxrt の `bo.sync(向き, size, offset)` を直に呼ぶと範囲を絞れた:

| 大きさ | 64 KiB | 256 KiB | 1 MiB | 4 MiB | 16 MiB | 64 MiB | PYNQ の全体（64 MiB） |
|---|---|---|---|---|---|---|---|
| 時間 | 0.039 ms | 0.053 ms | 0.105 ms | 0.323 ms | 1.181 ms | 4.618 ms | 4.65 ms |

- ≒ 0.03 ms ＋ 0.072 ms / MiB。SAM45-Fine の 1 BASE（0.26 MB）で ≒ 0.05 ms、256m（2.1 MB）で ≒ 0.18 ms
- **決定（2026-10-08、手順 0 で先に書いた基準「0.26 MB で 0.1 ms 以下」を満たした）: HP0 ＋ 範囲を絞った invalidate**（specd が [R, W) だけを `bo.sync(FROM_DEVICE, size, offset)`。端で 2 回に分ける）
  **理由**: PS のコヒーレンシの設定（HPC0・CCI・AxCACHE）に触らずに済む。費用は M-5 に対して 1〜2 %
  **見送った案**: HPC0（キャッシュの扱いは要らなくなるが、PS の設定と PL の AXI の属性を正しく揃える必要があり、揃っていなくても黙って動く形の失敗になりうる）
  **確かめ残り**: 範囲を絞っても PL が書いた中身が正しく見えるか（古い行が残らないか）は PL が要る → 手順 2 の V2-g（invalidate を飛ばす変種で CRC の不一致が立ち、正しく呼べば立たない）
  **注意**: PYNQ の `invalidate()` は使わない（全体を同期し、リングが大きいほど重い）。PYNQ の版が変わったら M-6 を測り直す

- **手順の誤り**: 4.（`--buf-mib 256`）は CMA（128 MiB）を越えるので allocate で落ちた。手順を書いたときに M-2 の結果を待たずに 256 を置いた。invalidate の重さはバッファの大きさに比例する（M-3 の 0.073 ms / MiB）ので、4. は M-3 から読む
- **決め方への当てはめ**: CRC を全部確かめるのは sam45fine だけ（p99 4.49 ≦ 5 ms）。取得を Python のままにするのも sam45fine だけ（平均 38 %・最大 4.50 ms）。**proj021（SAM45-Fine）は Python・CRC 全部で進める**。2g・256m・spw6 は Python の 1 本では回らない（上）
- **HP0 か HPC0 か**: 決め方の 4. は測れなかったが、M-3 から、PYNQ の invalidate（範囲を指定できずバッファ全体）を BASE ごとに呼ぶと、リング 32 MiB で 2.3 ms / BASE（23 %）かかる。新しく来た分だけなら SAM45-Fine で 0.26 MB ≒ 0.02 ms。**全体の invalidate は使えない → HPC0 か、範囲を絞った invalidate を自分で書くか**（未決）

## 結論・次にやること

- 手順 0 の残り:
- 別に進める: ボードの送り出しが ≒ 220 Mbit/s で絞られる件。iperf3 10 s の前後の `ethtool -S eth0`: tx_frames +175,294・tx_octets +266 MB（26.6 MB/s）、**PAUSE と誤りの数えは 0 のまま**、qdisc は mq ＋ pfifo_fast（普通）、`ethtool -a` は未対応。UDP の損失 0 % と合わせて、**ボードの NIC が自分で ≒ 220 Mbit/s でしか出していない**と読む（スイッチなら捨てるので損失か再送が出る）。TSO は使えない（`tx-tcp-segmentation: off [fixed]`、GSO・チェックサム・scatter-gather は on）。リングは TX・RX とも 512（最大 4096・8192）、`ethtool -c` は未対応。**10 s の送り出しで eth0 の割り込みが +182,000（18.2 k/s）、全部 CPU0**。送ったフレーム 17.5 k/s ＋ 受けた ACK 4.4 k/s とほぼ同じで、**フレームごとに割り込みが 1 回**（まとめていない）。≒ 18 k フレーム / s（57 µs / フレーム）に何かの関所がある見当。UDP 900 Mbit/s を `-l 1400` と `-l 8000`（1 回の送信が 6 フレームに分かれる）で: **28.4 / 28.5 MB/s、損失 0 %**。送信 1 回ごとの手間ではなく、**NIC から出るフレーム（≒ 20 k / s）か量（≒ 230 Mbit/s）で頭打ち**。次: `-l 200`（小さいフレームでもフレームの数が同じならフレームごと、量が同じなら量ごと）・直結。**装置の問題としてトラブル記録に移して別に追う**

## 公開について

study-rfsoc は公開リポジトリ。commit・push の前に、公開前のスキャン（リポジトリ外の手順書）の全項目を機械的に行う。
**コミットメッセージに `Claude-Session:` の行や URL を入れない**（`Co-Authored-By` の行は可）。

## 再現手順

手順 0 は PL を変えないので、ビルドは要らない（proj020 の build-PE の .bit・.hwh を使う）。手順 1a 以降で書く。

環境は [`../VERSIONS.md`](../VERSIONS.md)、詰まったときは [`../proj001/docs/runbook.md`](../proj001/docs/runbook.md)。

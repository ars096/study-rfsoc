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

ボードの手順は **root のシェル**で、ボードのアドレスを `$B`、ダウンロード PC のアドレスを `$S` に入れて書く（2026-10-08 から）。

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
scp proj021/pynq/bench_ps.py xilinx@$B:~/proj021/

# 制御 PC: specd を止める（同じ A53 を取り合うと数が意味を持たない）
python3 specctl.py --host $B SHUTDOWN confirm=1

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

# ボード（iperf3 が無ければ apt install iperf3）
for i in 1 2 3 4 5; do iperf3 -c <PC> -t 30 -J > runs/m1_tx_$i.json; done       # ボード → PC（送り出しの向き。これが予算）
for i in 1 2 3 4 5; do iperf3 -c <PC> -t 30 -R -J > runs/m1_rx_$i.json; done    # PC → ボード（参考）
for f in runs/m1_*.json; do python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(sys.argv[1], round(d['end']['sum_received']['bits_per_second']/8e6,1), 'MB/s')" $f; done
```

**2. M-2〜M-5（1 回目）**

```bash
python3 bench_ps.py --out runs/bench_ps_1.json 2>&1 | tee runs/bench_ps_1.log
```

**3. 陽性対照（CRC の見張りが働くこと）**

```bash
python3 bench_ps.py --only m5 --corrupt --m5-rep 3 --out runs/bench_ps_corrupt.json 2>&1 | tee runs/bench_ps_corrupt.log
```

合格: どの構成でも「不一致 3」（壊したレコード 1 つ × 3 周）。0 なら見張りが壊れている（他の結果も読まない）

**4. リングを大きくしたとき（invalidate がバッファ全体にかかる重さ）**

```bash
# 2026-10-08: 256 は CMA（128 MiB）を越えて落ちた（手順の誤り）。invalidate の重さは M-3 から読む
python3 bench_ps.py --only m3 m5 --buf-mib 256 --out runs/bench_ps_256m.json 2>&1 | tee runs/bench_ps_256m.log
```

**5. 間引いたときの見当と、2 回目（揺れを見る）**

```bash
python3 bench_ps.py --only m5 --no-crc --out runs/bench_ps_nocrc.json 2>&1 | tee runs/bench_ps_nocrc.log
python3 bench_ps.py --out runs/bench_ps_2.json 2>&1 | tee runs/bench_ps_2.log
```

**6. 後片付け**: 制御 PC から specd を起動し直す（`python3 specd.py --clkin 0 --ref 10`）。runs/ を Mac へ持ち帰り、下の決め方で結果の表を埋める

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
| sim-t4adc | **全部通過**（8 窓・TP 4 本が同じクロックに RUN、ID 0x0021_0100・0x0021_7101。9 分 22 秒） |
| `make sim-all`（Vivado サーバ、2026-10-08） | **全部通過**。「失敗」の 3 行はどれも陽性対照で、落ちるべきところで落ちた: tb_time の失敗 6 件（sim-time-p）・`[n2] wstamp` の失敗 8 件と `build-sim-wstamp-posctl` の「失敗（通過 0 / 1）」（sim-wstamp-p。Makefile の約束で「成否は結果: 失敗」）。sim-wstamp 本体は 4 変種とも通過、sim-t4adc・sim-wgrid とその陽性対照、spec_core の変種・sim-gb・sim-tp も通過（ID の照合 check.py を含む） |
| sim-top・sim-win4・sim-tsys | **まだ**（sim-all に入っていない。ID の照合を 0x0021 に直したので回す） |

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
- **worst-paths（1b の dcp、`proj021.runs` を読んだことを確かめた）**:
  - 既定（build/、WNS +0.008）: **群 C（gb_gate → gb_fifo）は最悪の 14 群（slack ≦ +0.080）に出てこない** → 予言 (1)「消えるか ≧ +0.05」どおり。いちばん際どいのは win_core_1 の窓 1 の wspec（u_ws、+0.008、21 本。proj020 からある電力・積分の経路）、次に gb_dn_0 → full_sel（+0.023、8 本）・spec_core_0 の g_bin[7] の m_re（+0.045）
  - PE（build-PE/、WNS −0.129）: **群 C ではない**。最悪は **win_core_0 の上の階層 → 窓 1 の ddc（u_ddc）146 本・−0.129**、ほかに win_core_3 の ddc・u_pfb・u_ws が −0.09〜−0.13。win_core の上の階層から ddc へのファンアウトの経路が、この配置では伸びた。**手順 2 で資源を足したときの次の壁の候補**として残す（PE は実機に載せない）
  - G-2: **通過**（群 C は消えた。CDC-3 105 / CDC-6 5 / CDC-15 3137 は proj020 と同じ = 新しい乗り換えなし。スキッドは同じクロックの中）
- FF（CLB Registers）: 329,546（proj020 322,408 から **+7,138**。予言 +6,100 より 1,000 多い。enb を駆動する FF の複製の分か → worst-paths で見る）。BUILD_TAG 0x50a00000（spec_core_0、プリセットあり・`-1`）
- **手順の誤り（2026-10-08）**: 1 回目の `make worst-paths` は、Makefile の `DCP` の既定を `*.runs` で拾う形に直していたため、同じ build/ に残っていた **1a の proj020.runs の dcp を読んだ**（出力の WNS −0.063・`gb_gate_3/armed_reg → gb_fifo_3 … enb（780）` は proj020 / 1a のもの。1b の結果ではない）。
  `DCP` は build.tcl の `set proj` の名前で指定し、dcp がちょうど 1 個であることを確かめる形に直した。**ビルドのディレクトリに古い proj の成果物を残さない**（1a の build/・build-PE/ の proj020.* と vivado/proj020.runs は消す。結果は上に残してある）

**実機（2026-10-08、`gbboot.py`、Overlay の読み込み 50 回ずつ、各 ≒ 9 分）**:

| 判定 | bit | 結果 | 読み |
|---|---|---|---|
| **G-3** | build/ の proj021.bit（K 2） | **50 / 50 回とも 4 ADC で OK**: armed・GB_K 2・開始のときの FIFO の残量 2・その後の最小 2（sim の残量の最小 2 と同じ）・空振り 0（dwell 5 s の後も 0）・RFDC の valid の落ち 0・ID 0x0021_A100 | **通過** |
| **G-4**（陽性対照） | build-k0-PE/ の proj021_k0.bit（K 0） | **50 回のうち 13 回で空振り**。13 回とも **ADC_A だけ・ちょうど 1 回**で、dwell の間に増えない（1 → 1）。残量の最小は 0 | **見張りは働いている**。「起動の直後に 1 回だけ途切れる」は proj011 rev6 の見立て（gray の遅いビット）と同じ形。ADC_A だけなのは、この配置で ADC_A の gray のどれかのビットの配線が遅いと読む（配置ごとに変わる） |

- G-3 の 0 / 50 は、同じ回数の G-4 の 13 / 50（ADC_A）と並べて読む。率 0.26 の事象が 50 回で 0 回になる確率は 0.74^50 ≒ 3 × 10⁻⁷。**ただし G-3 と G-4 は別の配置**なので、「K 2 の bit の ADC_A にも同じ遅いビットがある」ことまでは言えない（言えるのは、K 2 の bit で 200 回の起動に途切れが無いこと）
- **1b 通過**（G-1〜G-4）。残り: sim-top・sim-win4・sim-tsys（ID の照合を 0x0021 に直した長い sim）

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

# Vivado サーバ → ボード（**build/（既定）** を載せる。glob で送らず名前を指定する）
scp build/proj021.bit build/proj021.hwh xilinx@$B:~/proj021/
scp build-k0-PE/proj021.bit xilinx@$B:~/proj021/proj021_k0.bit
scp build-k0-PE/proj021.hwh xilinx@$B:~/proj021/proj021_k0.hwh
scp pynq/*.py pynq/tp_cal.json xilinx@$B:~/proj021/

# ボード（root。specd を止めてから）
cd ~/proj021
python3 gbboot.py --loads 50 --clkin 0 --ref 10 --out runs/g3
python3 gbboot.py --loads 50 --clkin 0 --ref 10 --bitfile proj021_k0.bit --expect-k 0 --out runs/g4
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

**proj022（SAM45-Wide の模型）から返ってきたこと（2026-10-09）**:
1. SLICE に要る点数 N と最初の ch → **INTERFACE に書いた**: コアの共通部 0x80 FFT_N（コアの SLICE の流れで共通、WRST で効く）、流れのブロック 0x100 S0・0x104 S0_CUR・0x108 S0_STEP、
   レコードの頭の語 7 の上位 = S0_CUR（予約だった場所。rec_ver・IF_VER は上げない）。**SAM45-Fine の RTL は変えない**（SLICE が無い。0x80 は 0、語 7 の上位は 0 のまま）
2. KIND は 1 つの bit の間で変わらない → **INTERFACE 2.1 に書いた**。SAM45-Wide は 3 モードとも SLICE、出すものの無い流れは NCH = 0 の「空の流れ」
3. フレームの頭のビートを 4 ADC で T の格子に揃える（係数・ひねり係数を 4 ADC で共有するため）→ **8. の 8（F0 を格子に寄せる）の作り方として、その手順の設計で扱う**: 案はフレームの頭 = T ≡ 0（mod FRAME_BEATS）で FFT の入口を開け、
   フレームの頭の T mod FRAME_BEATS を読めるレジスタで sim・実機とも 0 を確かめる。揃えられない構成のために、ADC ごとのずれ（ビート）を読める道も残す
4. 量は SAM45-Fine と同じ（4 ADC × 2 × 4096 ch / 40.96 ms）。リングと rec_fr はそのまま使える

### 手順 2-1 — 流れのブロックと自己記述（設計と予言、2026-10-09。RTL を書く前）

**変えるのは番地と自己記述だけ**。窓・全帯域の中身（スペクトル・帳簿・時刻・TP）は変えない。読み出しは AXI4-Lite のまま。

**決めたこと（2026-10-09 の相談）**:
- **仮の読み窓を残す**: 2-1 ではコアの番地を 1 MiB のままにし、`0x80000`〜 に今のスペクトル・スナップショットの記憶を**約束の外**として残す（2-1 だけで実機の回帰まで確かめるため）。2-2（リング）で外し、64 KiB に縮める
- **FULL は包むモジュールに入れる**: 新しい `s45_core.v` が今の `win_core`（コアの共通 ＋ DDC の流れ）と、`FULL = 1` のときだけ `spec_core`（FULL の流れ）を中に持つ。中に 1 → 2 の AXI4-Lite の振り分け（応答 1 つずつ、全部レジスタで受ける）。BD のセルは `s45_core_0`〜`3` の 4 個（`spec_core_0` のセルは無くなる）。axis_sel4 は外のまま、選んだ流れを `s45_core_0` の 2 本目の入力へ。選ぶのは FULL の流れの SRC（今の FULL_SEL）

**コアの番地（2-1。1 MiB）**:

| 範囲 | 中身 |
|---|---|
| 0x00000–0x000FF | コアの共通（INTERFACE 2.4）。0x20〜 は今の表 A を **+0x10 ずらしたもの**（0x30 の FULL_SEL は SRC に移ったので予約） |
| 0x00100–0x001FF | TP のレジスタ（今と同じ並び） |
| 0x02000–0x03FFF | TP のリング（今と同じ） |
| 0x04000 + 0x400·s | 流れ s のブロック（INTERFACE 2.5）。DDC が s = 0, 1、FULL が s = 2（コア 0 だけ） |
| **0x80000 + 0x20000·s**（s = 0, 1） | **仮の読み窓（約束の外。2-2 で外す）**: 今の win_core の窓 s と同じ中の並び（+0x08000 スナップショット・+0x10000 スペクトル） |
| **0xC0000–0xCFFFF**（コア 0） | **仮の読み窓**: 今の spec_core と同じ中の並び（+0x2000 全帯域の TP のリング・+0x4000 スナップショット・+0x8000 スペクトル）。全帯域の TP のレジスタは +0x1100 |
| **0xE0000** | **仮**: SNAP_SEL（窓のスナップショットを書く流れ。2-2 で REC_CTRL の SNAP に替わる） |
| ほか | 約束の範囲（0x00000–0x0FFFF）の予約は 0 を返す。仮の範囲の空きは 0xDEADBEEF（今と同じ） |

**コアの共通部の値（SAM45-Fine）**: IF_ID = 0x0202_0101（IF_VER 2・BIT_KIND 2 = SAM45-Fine・BIT_REV 1・CORE_KIND 1）／PROJ = 0x0021_0200（手順 2 の rev）／NSTREAM = 3（コア 0）・2（コア 1〜3）／CAPS = 0（レコードはまだ無い）／BASE_BEATS = 2,621,440／BUILD は今の BUILD_TAG／CORE_PORT = ADC の番号・タイル（0..3）・スライス（build.tcl の chans から）。time_core も IF_ID 0x0202_0102（CORE_KIND 2）・PROJ 0x0021_0200（0x5C）

**流れのブロックへの移し方**（今の番地 → INTERFACE 2.5 の番地。意味は変えない）:

| 2.5 | DDC（今の win_core の窓） | FULL（今の spec_core） |
|---|---|---|
| 0x00 SID | 新（KIND 3・s） | 新（KIND 1・s = 2） |
| 0x04 PARAM | [7:0] 12 / [11:8] 今の WNS / [15:12] 今の G（種類に固有）/ [23:16] 64 / [31:24] 0 | [7:0] 13 / [15:8] FFT_CFG（旧 ID の下位 8 bit）/ [23:16] 64 / [31:24] 0 |
| 0x08〜0x1C CTRL・N_ACC・N_DUMP・SHIFT・FLAGS・SEQ | 同じ番地 | 同じ番地。CTRL の [9]〜[11]（診断を消す・SRST・GRST）は FULL の診断として残す。[12] WRST・[13] ARM_WRST は **SRC と CFG_ID を取り込むだけ**（FULL にはリセットする窓の経路が無い） |
| 0x20 NCH・0x24 FRAME_BEATS | 4096・2048 << WNS（今効いている） | 4096・512 |
| 0x28 SRC | [3:0] = コアの ADC、[31] = 0 | [3:0] 今効いている入力 / [31] = 1。書いた値は次の WRST で効く（**今の FULL_SEL は書いた瞬間に効く。ここだけ振る舞いが変わる**） |
| 0x2C CFG_ID・0x30 RUN_CFG・0x34 WRST_CFG・0x38 RUN_SHIFT | 0x94・0x98・0x9C・0xB8 | 0xC0・0xC4・新（WRST で取り込んだ CFG_ID）・0xE0 |
| 0x3C DUMP_K・0x40/44 DUMP_F0・0x48 DUMP_N・0x4C DUMP_SAT | 0x30・0x38/3C・0x34・0x40 | 同じ |
| 0x50/54 DUMP_T・0x58 DUMP_H・0x5C DUMP_CFG・0x60/64 RUN_T | 0xA0/A4・0xA8・0xAC・0xB0/B4 | 0xC8/CC・0xD0・0xD4・0xD8/DC |
| 0x68/6C RUN_F0・0x70/74 FIN・0x78/7C FOUT | 0x50/54・0x20/24・0x28/2C | 同じ |
| 0x80 NFFT_MIN_MAX | [7:0] 最小 12 / [15:8] 最大 12 | 13 / 13 |
| 0x84 REC_CTRL・0x88 REC_LATE | 0（2-2 で） | 0 |
| 0x100〜（種類に固有） | WK・WDPHI・WNS・WCUR・WCUR_DPHI・WSTART・NS_MIN_MAX（新、1..8）・WRST_T = 0x100 から 4 バイトずつ（今の 0x58・0x5C・0x60・0x64・0x68・0x8C・新・0x78） | なし |
| 0x200〜（診断、約束の外） | PFB_SAT・DDC_SAT・WS_STALL・WS_RDY0・DDC_OVR・WRST_CNT・SNAP_F_LO/HI・BANK | 今の 0x58〜0xB4 を 0x200〜0x25C に（DIAG_*・BUILD・SRST_*・ST_*・GB_K・ST_N・INJ・GRST_*・RAW_*・GB_STAT・ADC_STAT・INJ_CNT）、SNAP_F_LO/HI・BANK を 0x260〜 |

- 消すもの（INTERFACE 2.5）: 窓ごとの ID・BUILD・WIDX（SID・コアの共通へ）、表 A の ID・NW・BUILD（IF_ID・NSTREAM・BUILD へ）、FULL_SEL（FULL の SRC へ）。SNAP_SEL・SNAP_F・BANK は 2-2 まで仮に残す（上）
- **PS**: `pynq/s45core.py`（新）が .hwh の `s45_core_i`・`time_core_0` を名前で引き、IF_ID・CORE_PORT・NSTREAM・SID を読んで流れの表を作る（PORT の重複・IF_VER の不一致で止まる）。window・timetest・s45acq・spectrometer の TP と全帯域はこの表の番地で動く形に。**timebase.CAL の鍵は time_core の PROJ（0x0021_0200）に**（IF_ID は bit の種類と版しか持たないので）。照合を ID の数値でしていた道具（winsweep など、specd と判定に使わないもの）は 2-1 では直さず、古い bit 用として残す（README に一覧）

**予言**:
1. sim: 窓・全帯域のスペクトル・帳簿・時刻は **bit 単位で 1b と同じ**。長い sim（sim-top・sim-win4・sim-tsys・sim-t4adc・sim の spec_core）は tb の番地を直しただけで通る
2. 新しい sim-regmap（コア 0 と 1 の全部の約束のレジスタを読み、表どおりの値・書けるものは書いて読み返す・予約は 0）が通る。陽性対照: 番地を 1 つずらした変種で落ちる
3. 資源: DSP・BRAM・URAM は同じ。LUT +500〜+2,000（番地の振り分けと SID・定数の読み）、FF +300〜+1,000（振り分けのレジスタ）。spec_core_0 の 1 個ぶんの SmartConnect の M が減るので、SmartConnect は少し減る
4. 時間: 既定で WNS −0.10〜+0.05（壁は今の u_ws・ddc のまま。振り分けは全部レジスタで受けるので新しい壁にしない）。**s45_core_0 の読みの選びが 1 段増える経路が上位に出たら、その段を足す**
5. CDC の分類ごとの件数は 1b と同じ（乗り換えは足さない）
6. 実機: P-1・P-2（W-G）・全帯域の golden・P-5 が 1b と同じに通る（PS は自己記述で番地を引く）。AXI4-Lite の読み 1 回は 3〜4 クロック遅い（≒ 20 クロックのうち。振り分けは全部のコアの入口にあるので、窓も同じ）

**判定（2-1）**:

| ID | 何を | 合格 |
|---|---|---|
| S21-1 | `make sim-regmap`（新）と陽性対照 | 予言 2 |
| S21-2 | `make sim-all`・sim-top・sim-win4・sim-tsys（番地を直した tb） | 全部通過（予言 1） |
| S21-3 | ビルド（既定・PE）・`make worst-paths`・CDC | 予言 3〜5 |
| S21-4 | 実機: `s45core.py --list`（自己記述の表）・P-1・P-2・全帯域の golden・P-5（specd 経由） | 表が上と同じ・P-* が 1b と同じ |

**実装（2026-10-09）**:

- RTL: `src/common/s45_core.v`（新。振り分け・win_core・FULL = 1 で spec_core）、`win_core.v`（番地・自己記述。full_sel の出口は s45_core へ）、`spec_core.v`（番地・SRC・WRST・ARM_WRST、src_sel の出口）、`time_core.v`（IF_ID・PROJ）。窓・全帯域・TP の中身の論理には触っていない
  - **FULL = 1 は NW ≦ 2 のときだけ**（0xC0000 は窓 2 の仮の読み窓と重なる。s45_core の initial で止める。2-2 で仮の読み窓が無くなれば外れる）
- build.tcl: セル s45_core_i・CORE_PORT・BIT_KIND・PROJ、spec_core_0 のセルと SmartConnect の M を 1 本減らす、結線と番地の照合・資源の数え（`s45_core_0/inst/g_full.u_full`・`s45_core_i/inst/u_win`）。`tools/worst_paths.tcl` の束ねの深さ 4 → 5（u_win の 1 段）
- sim: **sim-regmap（新、S21-1）**と陽性対照 sim-regmap-p、tb_regmap の読みを `pynq/test_regmap.py` に通して PS の定数を確かめる。tb_t4adc・tb_top・tb_win4 は s45_core 越しに v2 の番地で、tb_tsys は s45_core（FULL = 1）1 個に旧番地 → v2 の表（xa）で、tb_spec_core は spec_core の中の番地の表（xs）で。check.py・check_top.py・check_win4.py の ID の照合を SID・IF_ID に。sim-t-all に sim-regmap を足した
- PS: `pynq/s45core.py`（新。discover・表・`--list`）。window・spectrometer（Spec に base・lbase、open_full_stream）・timetest（open_all・select_full）・timebase（IF_ID・CAL の鍵 = PROJ）・s45acq・s45cal（PROJ で照らす）・fine・gbboot（.hwh の名前で旧と v2 を見分ける）・winwrst を v2 の番地に。**直していないもの**: win16.py（proj015 の 4 ADC × 4 窓専用。SAM45-Fine では使わない）

**sim（クラウドの iverilog 12、2026-10-09）**:

| sim | 結果 |
|---|---|
| **sim-regmap（S21-1）** | **全部通過（176 項目）**。陽性対照 sim-regmap-p（tb の流れのブロックの番地を 4 バイトずらす）は **95 件で落ちた**。tb の読みを `pynq/test_regmap.py` に通して **PS の定数（s45core・window・spectrometer・timetest・timebase）も通過（76 項目）**。1 回目は tb の CORE_PORT の書き間違い（ADC_B を 0x2001 と書いた。正は 0x0201 = タイル 2・スライス 0）を test_regmap が拾った（RTL・build.tcl の式は正しい） |
| sim-t4adc・sim-t4adc-p | 通過・陽性対照が落ちた（s45_core × 4 越し、v2 の番地。8 窓・TP 4 本が同じクロックに RUN） |
| sim-top | **全部通過**（s45_core 越し、仮の読み窓で 3 ダンプ × 4096 ch を読み、**模型と bit 単位で一致**・スナップショット = PFB の模型。予言 1 どおり） |
| sim-win4 | **全部通過**（NW 4・FULL 0 の s45_core。SID・WIDX・SNAP_SEL・TP、無い流れは 0） |
| sim-tsys | **全部通過**（s45_core（FULL = 1）1 個に窓と全帯域、旧番地 → v2 の表で。同時開始・DUMP_T・SHIFT と CFG の取り込み・健全性・TANCH・予約の WRST） |
| sim（spec_core、7-0-0・7-0-1） | 全部通過（spec_core の中の番地の表で。FULL の診断の SRST・GRST・INJ・起動の見張り） |
| sim-time・sim-time-p | 通過（IF_ID 0x0202_0102・PROJ）・陽性対照が落ちた（6 件） |
| `make sim-all`（Vivado サーバ、2026-10-09） | **全部通過**。spec_core の 5 変種・sim-gb・sim-tp と陽性対照・sim-win-all（pfb・ddc・win・hb2s・wspec と陽性対照）・sim-t-all（sim-regmap と test_regmap・sim-t4adc・sim-time・sim-wstamp・sim-wgrid と陽性対照）。「失敗」の行は陽性対照（sim-time-p 6 件・sim-wstamp-p 8 件）だけ |
| sim-tsys-p | 落ちるべきところで落ちた（NG 1 件 = RUN の間の SHIFT が RUN の値でない。窓 0・全帯域とも） |
| **sim-win-ts（陽性対照）の判定の道具の誤り** | 陽性対照の RTL で NS 6 の出力が 0 個になり、`check_win.py` が空のファイルで落ちて（IndexError）「結果:」の行を出していなかった。**proj020 から持ってきた道具の誤りで、2-1 の変更とは関係ない**（pfb・ddc は触っていない）。空のときに列を揃えるよう直し、同じ出力を判定し直して **落ちた NS [3..8] = 期待どおり → 通過** |

- 気にしておくこと（ビルド）: s45_core_1〜3 の FULL の入口（s_axis_full・full_gb_stat・full_adc_stat）はつながない。IP Integrator が 0 に結ぶはずだが、**CRITICAL WARNING が出たら定数のセルで結ぶ**（1b までは CRITICAL WARNING なし）

**ビルド（Vivado サーバ、2026-10-09、5bce26e）**:

| 戦略 | WNS | WHS | 予言 4（−0.10〜+0.05） | 読み |
|---|---|---|---|---|
| 既定（build/） | **−0.001950** | +0.005200 | 当たり | `-1` で 2 ps 足りない（1b の既定は +0.008） |
| Performance_Explore（build-PE/） | **+0.002742** | +0.006773 | 当たり | **閉じた** → 実機には build-PE/ を載せる（1b の PE は −0.129） |

- 戦略の良し悪しが 1b と入れ替わった（1b: 既定 +0.008・PE −0.129 → 2-1: 既定 −0.002・PE +0.003）。どちらも配置の運の幅（±0.1）の中。**余裕はほぼ 0** のまま
- 資源（予言 3）: DSP 2600・BRAM 305・URAM 56 は 1b と同じ（当たり）。LUT 206,787 / 206,905（1b 206,593 から +194 / +312。予言 +500〜+2,000 より少ない）、FF 328,177 / 329,780（1b 329,546 から −1,369 / +234。予言 +300〜+1,000 は既定で外れ。SmartConnect の M が 1 本減った分と配置ごとの複製の差と読む）。DSP の内訳は FULL 504・u_win 524 × 4・u_pfb 272・ddc 72・ws 42・tp 24
- CDC（予言 5）: CDC-6 5・CDC-15 3137 は 1b と同じ。**CDC-3 は 105 → 91（−14）**。1b の SmartConnect の CDC-3 は M ごとにちょうど 14 本（m01〜m06）で、2-1 は spec_core_0 の M が無くなった分だけ減った（smc_ctrl の CDC-3 86 → 72）。新しい乗り換えは無い → 予言 5 の「同じ」は外れだが、理由は構造で説明できる
- 結線の照合: 照合した行 101 / 問題 0 件 / 陽性対照 OK（spec_core_* のセルが無い、を含む）
- **worst-paths（2026-10-09）**: 振り分け（s45_core の q_* と 1 → 2 の口）は既定・PE とも上位 200 本に無い → **予言 4「新しい壁にしない」は当たり**。上位は前からある壁:
  - 既定（−0.002）: ADC_A の u_pfb の中（CARRY8 を含む 10 段、32 本）・ADC_C の u_ws の URAM の読み（−0.001）・**ADC_A 窓 1 の `c_ns` → u_ddc の DSP の CEA2（ファンアウト 1830、+0.000）**（1b の PE の −0.129 と同じ「win_core の上の階層 → ddc」）。仮の読み窓の `ax_ch` → `rq_w`（+0.005）・`snap_sel` → `swd2`（+0.010）も出る（1b からある経路。2-2 で仮の読み窓と一緒に消える）
  - PE（+0.003）: **ADC ドメインの gb_up_1（axis_dwidth_converter）の state_reg → r0_data（ファンアウト 195、段 0・配線 96 %、16 本）**。次に FULL の fin → snap_mem（+0.017）・`c_ns` → u_ddc（+0.017）・u_pfb・u_ws（+0.019〜）
  - 200 本とも slack < 0.3 ns（壁の厚さは WP_N を増やして数える）
  - **2-2 の候補**: `c_ns`（WRST でしか変わらない）を ddc の側で 1 段受けて複製する（値は変わらない）。u_pfb の段は遅れが変わるので sim-wdelay の出し直し（INTERFACE 8. の 9）と一緒に
- **CRITICAL WARNING [BD 41-759] × 3**（予言どおりの気にしておくこと）: s45_core_1〜3 の s_axis_full_tvalid・full_gb_stat・full_adc_stat がつながっておらず、Vivado が 0 に結んだ。働きは正しい（FULL = 0 のコアはこの入口を使わない）が、「CRITICAL WARNING なし」の規約から外れる → **2-2 で定数のセルで結ぶ**（今ビルドし直すと配置が組み替わり、閉じた PE を失うので直さない）。ほかの CRITICAL WARNING は既定の Timing 38-282（WNS が負）だけ

**実機（2026-10-09、build-PE/ の proj021.bit）**:

**2-1 の実機の判定（S21-4）は全部通過**（自己記述の表・P-0〜P-5・全帯域の golden）。残り: Vivado サーバの `make sim-all`・sim-tsys-p（予言 1・2 の残りの sim）

| 判定 | 結果 | 読み |
|---|---|---|
| S21-4 `s45core.py --list` | **表どおり**: IF_ID 0x0202_0101（4 コア）・time_core 0x0202_0102・PROJ 0x0021_0200・NSTREAM 3 / 2 / 2 / 2・CAPS 0・BASE_BEATS 2,621,440・CORE_PORT（A タイル 2 スライス 2 / B 2・0 / C 0・2 / D 0・0 = VERSIONS.md の実測）・SID 0x0203_0s00（DDC）・0x0201_0200（FULL）・FRAME_BEATS 4096（NS 1）/ 512・SRC 0〜3 と FULL 0x8000_0000・FULL の PARAM の FFT_CFG 0x07 | 通過 |
| P-0 `timetest.py --t0 --seconds 30` | TRIG 30 個 ±0 ビート・COMP ±1（平均 +0.033）・GLITCH / BAD / MISS 0 | 通過（open_all の自己記述・time_core の IF_ID・CAL の鍵 PROJ の道） |
| P-1 `window.py --probe`（A0 W 256・D1 W 8） | z が流れる・飽和 0・ダンプ 3 個。FLAGS は A0 0、D1 は [4] だけ（1 フレームに 1 クロック待たされる。proj014 からの性質） | 通過（D1 は s45_core_3 の流れ 1 を CORE_PORT で引いた） |
| P-2 `window.py --golden`（W 256・8） | 超えた ch 0、最悪の差 1.3 / 1.4（proj020 は 1.4）、SNAP_F = DUMP_F0 | 通過（仮の読み窓のスペクトル・スナップショット） |
| 全帯域の golden `spectrometer.py --ch A --golden` | SNAP_F = DUMP_F0・差/許容の最大 0.40・起動の見張りの途切れ 0・gb_gate K 2 空振り 0 | 通過（**FULL の流れの SRC → WRST → SRST の道を初めて実機で**） |
| P-3 `window.py --tone 3010.5 --w6 --w 256`（−20 dBm、SHIFT 11 / 全帯域 8） | W-1 ch 3928（予言 3928）・W-1b 窓と全帯域の推定 IF の差 −0.59 kHz・**W-6 −0.054 dB（予言 −0.043、許容 ±0.1。proj020 は −0.046）**・隣の ch −59.0・−51.0・−51.0・−59.1 dB（proj020 −59.8・−51.4・−51.5・−59.8） | 通過 |
| P-4 `timetest.py --t1 --seconds 120` | **13 コアとも RUN_T = START_AT + 1**（FULL の ARM を含む）・9 流れ × 2930 ダンプで DUMP_T の k·N·L からのずれ 0・健全性なし | 通過 |
| P-5 `s45resp.py`（specd 経由、`--dbm -0.9 --span 0 --kch 1 --nsub 32`、`runs/resp_p21.resp.{json,npz,chan.png,band.png}`） | 8 窓とも **半 ch −2.998〜−3.001 dB・−3 dB 幅 0.9998〜0.9999 ch・ref 0.99139〜0.99146**（proj020 の resp_p20c: −2.999〜−3.001・0.9999・0.99141〜0.99150）。隣の ch −44.9〜−53.4 dB・≧ 1.5 ch −44.5〜−56.8 dB は proj020 と 0.4 dB 以内（試験音の裾が床、proj020 と同じ読み） | 通過（specd の取得 s45acq の新しい読み口で、8 窓の対応も中身も 1b と同じ） |

- P-3 の 1 回目は CW が来ていなかった（ADC に 1PPS を配線したまま。窓の最大は IF 3072 MHz の k·fs/8 の線）、2 回目は −1 dBm・SHIFT 4 で窓の山が 6250 / 6250 フレーム飽和（proj020 の P-3 1 回目と同じ。隣の ch も 0.1 dB 以内で同じ）。3 回目を proj020 の 2 回目と同じ条件で通した
- **手順の誤り（2026-10-09）**: 1 回目の `s45core.py --list` は Overlay の直後にコアを読み、PS ごと止まった（再起動）。コアは DSP ドメイン（RFDC のタイルのクロック → Clocking Wizard）にあり、MMCM のロック・rst_dsp の明けの前に AXI4-Lite を読むと SmartConnect が応答を待ち続ける。window.py などは `check_tiles` と待ち（--settle）の後に読むが、s45core.py の `--list` だけ抜けていた → 同じ手順を入れた（6061fb6）。**DSP ドメインのコアを読む道具は、必ず check_tiles と待ちの後に読む**

### 2-1 のビルドと実機

```bash
# Vivado サーバ（1b の build/・build-PE/ は比べるために名前を変えて残す。同じ proj021 の名前なので、残すと worst-paths が混ざる）
cd ~/git/rfsoc && git pull && cd proj021 && pwd
mv build build-1b; mv build-PE build-1b-PE
make sim-all > sim-all.log 2>&1 &                       # 残りの sim（成否は各ログの「結果:」）
make sim-tsys-p > /dev/null 2>&1 &                      # → build-sim-tsys-posctl/check.log が「失敗」になること（陽性対照）
make IMPL=Performance_Explore > /dev/null 2>&1 &        # → build-PE/
make > /dev/null 2>&1 &                                 # → build/（既定）
wait
grep -E 'TIMING \(確定\)' build/vivado.log build-PE/vivado.log
grep -c 'CRITICAL WARNING' build/vivado.log build-PE/vivado.log
grep -E 's45_core_|FULL の流れ|DSP48E2' build/vivado.log | head -20   # CORE_PORT・FULL・資源の数え（FULL 504・u_win 520）
grep -E '照合した行|陽性対照' build/vivado.log                       # 結線の照合（spec_core_* のセルが無い、を含む）
make worst-paths                                                       # 束ねの深さ 5（s45_core_i/inst/u_win/…）

# Vivado サーバ → ボード（WNS の良い方。glob で送らず名前を指定する）
scp build/proj021.bit build/proj021.hwh xilinx@$B:~/proj021/
scp pynq/*.py pynq/tp_cal.json xilinx@$B:~/proj021/

# ボード（root。specd を止めてから）。S21-4
cd ~/proj021
python3 s45core.py --list --clkin 0 --ref 10                           # 自己記述の表（上の「コアの共通部の値」と同じこと）
python3 timetest.py --clkin 0 --ref 10 --t0 --seconds 30               # P-0: IF_ID・PROJ・PPS
python3 window.py --clkin 0 --ref 10 --probe --adc 0 --win 0           # P-1（A0）
python3 window.py --clkin 0 --ref 10 --probe --adc 3 --win 1 --w 8     # P-1（D1）
python3 window.py --clkin 0 --ref 10 --golden --w 256                  # P-2（W-G）
python3 window.py --clkin 0 --ref 10 --golden --w 8
python3 spectrometer.py --clkin 0 --ref 10 --ch A --golden             # 全帯域の golden（FULL の SRC → WRST → SRST の道）
python3 window.py --clkin 0 --ref 10 --tone 3010.5 --w6 --w 256        # P-3（W-6: 窓 / 全帯域。FULL を窓の ADC に選ぶ道）
python3 timetest.py --clkin 0 --ref 10 --t1 --seconds 120              # P-4（F-1: 13 コアが START_AT + 1 で RUN）
# P-5: specd を proj021.bit で起こし、s45resp.py（proj020 の P-5 と同じ配置・レベル）
```



### 手順 2-2a — リングと SPEC のレコード（設計と予言、2026-10-09。RTL を書く前）

**変えるのは「スペクトルを PS へ運ぶ道」を足すことだけ**。窓・全帯域の中身（スペクトル・帳簿・時刻・TP）は変えない。今の AXI4-Lite の読み（仮の読み窓）は残し、**同じ SEQ のスペクトルをレコードと AXI4-Lite の両方で読んで bit 単位で比べる**のが 2-2a の判定の芯。

**決めたこと（2026-10-09 の相談）**:
- **2-2 を 3 つに分ける**: 2-2a リングの芯 ＋ 書き手 ＋ SPEC のレコード（このページ）／2-2b TP のレコード（V2-e）／2-2c SNAP のレコード ＋ 仮の読み窓を外して 64 KiB に
- **書き手は自作**（Verilog の AXI4 の書き手。iverilog で sim できる。DataMover は使わない）
- **持ち越しの 2 つは 2-2a と同じビルドで**（commit は分ける。sim は bit 単位で同じ）: (1) s45_core_1〜3 の FULL の入力（s_axis_full_tvalid・full_gb_stat・full_adc_stat）を定数で縛る（CRITICAL WARNING BD 41-759 を消す）／(2) c_ns（ファンアウト 1,830）を 1 段のレジスタの複製で ddc に配る（max_fanout）

**全体の形**:

```
s45_core_i ─┬─ u_win（DDC の流れ 0, 1）──┐ 読みの口を借りる
            ├─ g_full.u_full（FULL、コア 0）┤
            └─ u_rec（レコードの組み立て）──── m_axis_rec（64 bit、tlast・tuser = 捨てる）──┐
                                                                                              │ ×4（コア 0〜3）
s45_ring_0（新、CORE_KIND 3）: 4 本の入口 → レコード単位の順番回し → CRC-32 → 自作 AXI4 の書き手（128 bit）→ PS の S_AXI_HP0 → DDR
```

**レコードの組み立て（u_rec。コアに 1 個、s45_core.v の中）**:
- 流れ s ごとに **SEQ が進んだ（バンクが切り替わった）**ことを見る。REC_CTRL（流れのブロック 0x84）の [0] ALL が立っていれば毎回、[1] ONE が立っていれば 1 回だけ（出したら PL が [1] を 0 に戻す）「出す予定」にする。[2] SNAP は 2-2c まで書けるが効かない
- 予定のある流れを順番に回し（コアの中の順番回し）、1 本ずつ **凍ったバンク**を ch の順（0〜4095）に読んで 64 bit の AXIS に流す。ヘッダ 8 語（下）→ 本体 4096 語、最後の語で tlast
  - DDC（wspec_core）: 凍ったバンクの読みの口（rd_ch）を借りる。今の AXI4-Lite の読みと同じ口なので、**u_rec が読んでいる間は仮の読み窓の AXI4-Lite の読みを待たせる**（arready を下げる。最長 4096 + 数十クロック ≈ 16 µs）。逆に AXI4-Lite の読みの途中では u_rec は始めない
  - FULL（spec_core）: `acc_rd[ar_bank][k2]` の番地 axi_k1 を借りる（ch k = k2·512 + k1。k2 が外、k1 が内の順に回す）。待たせ方は同じ
  - 読みの番地はレジスタで受けてから口に入れる（u_ws の読みの口の選びを新しい壁にしない）
- **ヘッダは SEQ が進んでから数クロック待って**、その流れの DUMP_*（DUMP_K・F0・T・N・SAT・H・CFG）・RUN_SHIFT などを取り込む（今の AXI4-Lite で読める値と同じもの）
- **読み終わる前に同じ流れの SEQ がもう一度進んだら**（凍ったバンクが上書きされた）、最後の語に tuser = 1（捨てる）を立てて REC_LATE（0x88）を +1。予定が立ったまま次の切り替わりまでに読み始められなかったときも REC_LATE を +1（古い予定は捨て、新しい切り替わりの予定に置き換える）。**リングの DROP_CNT も +1**（読み始めなかった方は 1 クロックの知らせ rec_late で、読みかけの方は tuser = 1 で数える。1 回の捨てで 1 回だけ）（INTERFACE 4.1 の「出し切り」: REC_LATE と DROP_CNT の両方を増やす。PS から見て DROP_CNT ＝ SEQ の飛びの合計になる）。**出たレコードは必ず 1 つの SEQ の、壊れていないスペクトル**
- 時間の見積り: 1 本の読みは 4096 クロック ＝ 16 µs（256 MHz）。コア 0 は 3 本なので最悪 48 µs、リングの入口で 4 コアを待つと最悪 ≈ 9 本 × 16 µs ≈ 150 µs。10.24 ms のダンプには十分。N_ACC が小さくダンプが ≈ 150 µs より短い設定では REC_LATE が増える（それは約束どおり。PS は SEQ の飛びで分かる）

**レコード（INTERFACE 3. のとおり。u64 の little endian）**:

| 語 | 中身 |
|---|---|
| ヘッダ w0 | magic "S45R"（0x52353453）／rec_ver 1／type（1 SPEC）／core（CORE_PORT の ADC 番号）／s |
| w1 | SEQ（32 bit）\| DUMP_K（32 bit） |
| w2 | DUMP_F0（64 bit） |
| w3 | DUMP_T（64 bit） |
| w4 | log2NFFT \| NS \| SHIFT \| G \| fmt \| src \| DUMP_H16 |
| w5 | DUMP_N \| DUMP_SAT |
| w6 | DUMP_CFG \| FLAGS |
| w7 | 本体のバイト数（32,768）／予約 0 |
| 本体 | 4096 × u64（ch の順。今の AXI4-Lite の LO・HI と同じ 64 bit） |
| しっぽ w0 | magic "S45E"（0x45353453）\| SEQ |
| w1 | CRC-32（zlib と同じ式。ヘッダ ＋ 本体の 32,832 バイト）|
| w2〜w7 | 0 |

1 レコード = 64 + 32,768 + 64 = **32,896 バイト**（64 の倍数）。しっぽはリングの書き手が付ける（u_rec は送らない）。

**リング（s45_ring_0。新しい `src/common/s45_ring.v`）**:
- クロックは DSP（clk_out2 = 256 MHz）。PS の S_AXI_HP0_FPD（128 bit）の saxihp0_fpd_aclk も clk_out2。**ファブリックの中の乗り換えは足さない**（HP0 の乗り換えは PS の中）
- 入口 4 本（コア 0〜3 の m_axis_rec）を **レコード単位で順番に回す**（レコードの途中で入口を替えない）
- レコードの頭で空きを見る: `SIZE − (W − R) ≥ 32,896 ＋（リングの端までに入らなければ、端までの PAD）`。足りなければ **そのレコードを丸ごと捨てる**（入口からは読み切る）→ DROP_CNT +1。PAD は type 0 のヘッダ 1 個（w7 = 端までのバイト数。INTERFACE 4.4）で、端までを埋めて先頭に戻る（PAD には尾を付けない。端までの残りは読み飛ばす）
- 書き手: 128 bit の AXI4（INCR、awcache 0011、awprot 000）。バーストは最長 16 拍（256 バイト）で、**4 KiB の境を越えない**（レコードは 64 バイト境から始まるので、最初のバーストは次の 256 バイト境まで）。入口の 64 bit を 2 語ずつ束ね、FIFO（BRAM、512 × 128 bit）にためてからバーストを出す。書き終わり（しっぽまで）を **BRESP が全部 OKAY で返ってから W を進める**（W はレコードの頭の位置から 32,896 だけ一度に進む。途中の W は PS に見せない）
- tuser = 1（捨てる）で終わったレコードは、書いたぶんを無かったことにする（W を進めない。REC_CNT は数えず DROP_CNT を +1）
- BRESP が OKAY でなければ ERR_STAT に記録して CTRL の [2] ERR を立て、書くのを止める（EN を 0 → 1 で戻す）
- CRC-32 は入口の 64 bit を 1 クロック 1 語で計算（反転入力・反転出力の zlib と同じ式、レジスタで 1 段受ける）
- レジスタ（AXI4-Lite、4 KiB）:

| 番地 | 名前 | 中身 |
|---|---|---|
| 0x00 | IF_ID | {2, BIT_KIND, BIT_REV, 3}（CORE_KIND 3 = リング） |
| 0x04 | CTRL | W: [0] EN・[1] RST（EN = 0 のときだけ。W・R・数を 0 に）／R: [0] EN・[1] busy・[2] ERR（粘着） |
| 0x08/0C | BASE_LO/HI | リングの物理番地（64 バイト境。PS は 4 KiB 境で取る）。EN = 0 のときだけ書ける |
| 0x10 | SIZE | バイト数（2 の冪、64 KiB〜1 GiB）。EN = 0 のときだけ書ける |
| 0x14 | W | PL が書き終えた位置（32 bit の単調増加のバイト数。番地は BASE + W mod SIZE） |
| 0x18 | R | PS が読み終えた位置（PS が書く。同じ数え方） |
| 0x1C | DROP_CNT | 捨てたレコードの数（空きなし ＋ 出し切れず（rec_late の知らせ・tuser = 1）。飽和） |
| 0x20 | REC_CNT | 書き終えたレコードの数（PAD を除く） |
| 0x24 | PEAK | W − R の最大（RST で 0） |
| 0x28 | ERR_STAT | 最初の誤り: [1:0] BRESP・[31:6] そのレコードの頭の位置（W の [31:6]） |
| 0x2C | PROJ | 0x0021_0200（INTERFACE 4.2 の予約の場所に足す。time_core の 0x5C と同じ） |

- EN = 0 にしたら、今書いているレコードは書き終えてから止まる（busy が 0 になったら止まった）。EN = 0 の間に来たレコードは入口から読み捨てる（数えない）
- **INTERFACE 4.3 の道具（約束の外）は DataMover だったが、自作の書き手に替える**（2026-10-09 の相談。iverilog で sim でき、空きの判定・PAD・W の更新と一体で書ける）。PS から見える約束（4.1・4.2）は変えない
- コアの共通部の CAPS の [0]（DMA のレコード）を 1 に（[1] TP・[2] SNAP は 2-2b・2-2c で）。NSTREAM などは変えない

**PS（2-2a では判定の道具だけ。specd は 2-3）**:
- `pynq/plring.py`（新。**名前は s45ring.py にしない**: proj018 の PS の溜まり `s45ring.py` を specd・s45acq が使っている）: .hwh から `s45_ring_0` を引き、連続した 32 MiB を取って BASE・SIZE・EN。W まで読んだら **その範囲だけキャッシュを捨てて**（HP0 は coherent でない）読み、magic・SEQ・CRC を確かめ、R を書く
- `--compare`: 流れごとに N_ACC を長く（ダンプ ≈ 1 s）し、REC_CTRL の ONE で 1 レコード出させ、**次の切り替わりの前に**同じ流れの仮の読み窓を AXI4-Lite で読んで、SEQ が同じ・本体が bit 単位で同じことを確かめる（全部の流れ: DDC 8 本 ＋ FULL 1 本）
- `--soak`: ALL で 10.24 ms を N 秒。DROP_CNT・CRC の不一致・流れごとの SEQ の飛び・REC_LATE・PEAK を数える

**持ち越しの 2 つ**:
1. build.tcl: s45_core_1〜3 の s_axis_full_tvalid・full_gb_stat・full_adc_stat を xlconstant（0）につなぐ。RTL は変えない（FULL = 0 のコアでは使っていない入口）
2. win_core: `c_ns` を ddc に配るためだけのレジスタ `c_ns_d`（max_fanout = 64）を足し、ddc の ns はそれを使う。**1 クロック遅れる**が、c_ns は WRST の中でしか変わらず、ddc が動き出すのはその後なので、出てくるスペクトルは同じ（sim-top・sim-win4・sim-t4adc が bit 単位で同じことで確かめる）。PARAM・FRAME_BEATS などの読みは今の c_ns のまま

**予言**:
1. sim: 新しい sim-ring（s45_core 2 個（コア 0 は FULL 入り）＋ s45_ring ＋ ランダムに止まる AXI のメモリ）で、出てきたレコードが **同じ SEQ の AXI4-Lite の読みと bit 単位で同じ**（DDC 2 本・FULL 1 本）。Python の zlib.crc32 と CRC が一致、SEQ が流れごとに連続、W − R・REC_CNT・PEAK が数え直しと合う、バーストが 4 KiB の境を越えない・16 拍以下
2. sim の陽性対照（3 つ）: (a) 確かめる側で CRC を 1 bit 反転 → 不一致が立つ／(b) 小さいリング（64 KiB）で R を進めない → DROP_CNT ＝ SEQ の飛びの数／(c) N_ACC = 1 → REC_LATE > 0、REC_LATE の和 ≦ DROP_CNT で、それでも **出たレコードは全部 bit 単位で正しい**
3. 回帰: sim-all（sim-top・sim-win4・sim-t4adc・sim-tsys・sim-regmap ほか）が bit 単位で 2-1 と同じ。sim-regmap は REC_CTRL・REC_LATE・CAPS とリングのレジスタを足す
4. 資源: DSP・URAM は同じ。BRAM +2〜+4（書き手の FIFO）。LUT +3,000〜+6,000（u_rec 4 個・リング・CRC・SmartConnect の M 1 個）、FF +3,000〜+6,000
5. 時間: 既定で WNS −0.10〜+0.05。壁は今の u_pfb・u_ws のまま。**新しく上位に出るなら u_ws の読みの番地の選び（u_rec の番地）か CRC の XOR の木**。出たらその段にレジスタを足す。c_ns の経路（ファンアウト 1,830）は上位から消える
6. CRITICAL WARNING: BD 41-759（s45_core_1〜3 の FULL の入口が空き）が 0 になる
7. CDC: smc_ctrl の M が 1 個増える（リングの AXI4-Lite）ので CDC-3 が 1 個の M ぶん（≈ 14）増えて ≈ 105。ほかの分類は同じ（HP0 はファブリックの乗り換えを足さない）
8. 実機: 全部の流れでレコード ＝ AXI4-Lite（bit 単位）、10.24 ms の ALL を 60 s で DROP_CNT 0・CRC の不一致 0・SEQ の飛び 0・REC_LATE 0。PEAK はリングの数 % 以下。キャッシュを捨てずに読む変種で CRC の不一致が立つ（V2-g の半分）

**判定**:

| 判定 | 中身 |
|---|---|
| S22a-1 | sim-ring が通る（予言 1）。陽性対照 (a)〜(c) が予言どおり落ちる・数が合う（予言 2） |
| S22a-2 | sim-all・sim-tsys-p・sim-regmap が通る（予言 3。持ち越し 2 の c_ns の複製を含めて bit 単位で同じ） |
| S22a-3 | ビルド: WNS ≥ 0（既定か PE の良い方）・WHS ≥ 0・BD 41-759 が 0・結線の照合・CDC の分類（予言 4〜7） |
| S22a-4 | 実機: 2-1 の P-0〜P-3 の回帰（仮の読み窓のまま）＋ `plring.py --compare`（全部の流れ）＋ `--soak`（60 s）＋ キャッシュを捨てない陽性対照（予言 8） |

**commit の順**: README（これ）→ 持ち越し 1（build.tcl）→ 持ち越し 2（c_ns）→ u_rec と REC_CTRL・REC_LATE → s45_ring と sim-ring → build.tcl（リング・HP0）→ PS の道具 → ビルドと実機の結果

**実装（2026-10-09）**:
- `src/common/rec_fr.v`（新）: レコードの組み立て。win_core に 1 個（流れ NW 本）、spec_core に 1 個（FULL）。HOLD = 8 クロック・FIFO 32 語（分散 RAM）。
  読みの口は持ち主の AXI4-Lite の読みと同じ（win_core: `ax_ch`・`ax_bank`、spec_core: `axi_k1`・`ar_bank`）。`fr_gnt` の間は arready を下げる
- `src/common/rec_arb.v`（新）: レコード単位の順番回し（スキッド 2 語）。s45_core（DDC と FULL の 2 本）と s45_ring（コア 4 本）
- `src/common/s45_ring.v`（新）: リング。ヘッダ 8 語を受けてから空きを判定 → [PAD] → 頭 → 本体 → 尾（CRC-32）→ 2 語を 1 拍に束ねて FIFO（512 × 128 bit）→
  バースト（≦ 16 拍、256 バイト境）。W は BRESP を全部受けてから進める。入口の tlast と長さが合わない壊れたレコードも、書き手の拍の数を崩さずに捨てる
- win_core・spec_core: REC_CTRL（0x84）・REC_LATE（0x88）・CAPS = 1・頭の w1..w6 を DUMP_* から組む。s45_core: 2 本を rec_arb で束ねて `m_axis_rec`・`rec_drop`
- build.tcl: `s45_ring_0`（NIN = nch）・PS の S_AXI_HP0_FPD（GP2、128 bit、saxihp0_fpd_aclk = DSP のクロック）・smc_ctrl の M0(2+nch)・
  レコードの道 4 本と rec_drop を shared_nets・sh_intf の表に（照合も同じ表）。アドレス: リングの 4 KiB を重なりの照合に、`s45_ring_0/m_axi` から HP0_DDR_LOW が見えることを確かめる
- PS: `pynq/plring.py`（新）。名前は s45ring.py にしない（proj018 の PS の溜まり `s45ring.py` を specd・s45acq が使っている）

**手順の誤り（2026-10-09、sim で見つけた）**:
- rec_fr の読みの遅れ LAT を 4 と数えていた（rd_ch → 番地 → rd1 → rd2 → fr_data は 5）。sim-ring の短い試しで、レコードの本体が凍ったバンクから **1 語ずれて**いた（AXI4-Lite の 16 ch と DUMP_* の照合は通っていた: 照合の相手を「凍ったバンクを直に写したもの」にしていたので見つかった）。LAT = 5 に直した
- sim-ring の late の変種を DDC の N_ACC 1（4096 クロック）にしていて、4096 語の読み出しが 1 本も間に合わず、**レコードが 1 個も出なかった**（REC_LATE だけが増える）。N_ACC 2（8192 クロック、3 本の読み出し 12,300 クロックが追いつかない）にした
- PS の道具を最初 `s45ring.py` の名前で書き、proj018 の同名の溜まり（specd が使う）を上書きしかけた（commit の前に気づいて戻した）

**sim の結果（2026-10-09、クラウドの iverilog 12）**:

| sim | 結果 |
|---|---|
| 持ち越し 2（c_ns の複製）の回帰: sim-top・sim-win4・sim-t4adc・sim-wgrid・sim-wstamp・sim-regmap | 全部通過（bit 単位で 2-1 と同じ） |
| sim-regmap（CAPS = 1・REC_CTRL の書き読み・REC_LATE を足して） | 通過（186 項目）・test_regmap 76 項目 |
| sim-ringu（S22a-1 予言 2 (a)(b)） | base: 92 / 96 レコード（来なかった 4 = 捨てるべき tuser の 4）・PAD 3 個・CRC は zlib と一致 / noread（64 KiB で R を進めない）: DROP_CNT 48 = 来なかった 45 ＋ rec_drop 3 / berr: SLVERR で ERR・ERR_STAT・以後は書かない / flip: 92 件全部 NG（陽性対照）|
| sim-ring all（予言 1） | 12 レコード（流れ 0: 5・流れ 1: ONE で 1・FULL: 6）の**本体が凍ったバンクと、頭が AXI4-Lite の DUMP_* と bit 単位で一致**。AXI4-Lite の仮の読み窓の 16 ch × 16 回も一致（rec_fr が口を持っている間は待たされる道）。REC_LATE 0・DROP 0・SEQ の飛び 0・ONE は 1 個出して 0 に戻る。バースト 1,554 本で 4 KiB の境・16 拍の見張りは 0 件 |
| sim-ring late（予言 2 (c)） | DDC の N_ACC 2（8192 クロック）: REC_LATE 18 = DROP_CNT 18、出た 12 レコード（流れ 0: 1・FULL: 11）は全部正しい。flip: 12 件全部 NG |

- late の偏り（FULL はほぼ全部出て、DDC はほとんど出ない）は、win_core の rec_fr の出口が s45_core の rec_arb で FULL と順番になり、
  FULL のレコード（4,104 語）の間は読みが止まる（FIFO 32 語）ため。読み出しの時間が実質「同じコアの全部の流れの読み出しの和」になる。
  10.24 ms のダンプ（262 万クロック）には全部の流れの和（9 本 × 4,100 ≈ 37,000 クロック）でも十分で、運転には効かない。
  N_ACC = 1 の試験（W-G・golden）は ONE で 1 本ずつ出すので当たらない

### 2-2a のビルドと実機

**ビルドの結果（2026-10-09〜10、5 回）**: 閉じたのは **5 回目の Performance_ExtraTimingOpt（`build-PETO/`）WNS +0.022 ns・WHS +0.010 ns**。

| 回 | 直したもの（前の回の最悪から） | 既定 | PE | ほか |
|---|---|---|---|---|
| 1 | — | 配線の途中で止めた（WNS −0.7 ns 前後） | 同左 | 上位は全部 s45_ring の CRC（for 文の CRC が 13 段の LUT の鎖） |
| 2 | CRC を展開した XOR の式に・語を 1 段受ける・書き手の番地と長さを 2 段に・空きと PEAK を前もって | −0.223（3,316 終点） | −0.019（39） | 上位に s45_ring は無くなった。既定の最悪は wspec の y → 飽和 → DSP の B、PE は ddc の最終段の 48 bit の丸め |
| 3 | wspec の q_* を DSP に取り込ませない（dont_touch）・hb2 の丸めを木の入口へ | −0.305（3,094） | −0.507（13,676） | PEPRPO −0.495・PETO −0.077（57）。上位 200 本は配線の型が 9 割、u_pfb の 4 項の和 → cmul の DSP が半分、rec_fr の SEQ の比べ（8 段）。PE は rst_dsp → DSP の CE、RFADC → gb_up まで負け、南向きの長い配線の混み 5 |
| 4（5 回目のビルド） | dft16f・dft16 の段 1 を DSP に取り込ませない・rec_fr の比べを 1 段受ける・コアとリングのリセットを中で 3 段受けて配る・仮の読み窓の sn2 を布の FF に | — | −0.013 | **PETO +0.022**（混み 4） |

- **読み**: 2-1 が既定・PE とも ±0.003 ns のぎりぎりで、2-2a の LUT +1 ポイント（206.8k → 209.5k）で配置の当たり外れ（PE で −0.02〜−0.5）に飲まれた。効いたのは (1) Vivado が飽和・和の後のレジスタを DSP に取り込み、論理が DSP の入口（セットアップ ≒ 0.3 ns）へ直に入る形を止めたこと（wspec・u_pfb・FULL の u_dft の 3 か所で同じ型）、(2) 混みを避ける戦略（PETO）。**既定と PE を比べるだけでは足りず、戦略を 3〜4 本並べて回すのを今後の型にする**
- 予言 5（WNS −0.10〜+0.05、新しい壁は u_ws の番地の選びか CRC）: CRC は**当たり**（1 回目）。u_ws の番地の選び（rec_fr の口）は上位に出なかった。代わりに既存の壁（DSP の取り込み）が混みで表に出た
- 予言 4（資源）: DSP・URAM 同じは**当たり**、BRAM +2（305 → 307）は**当たり**、LUT +2.7k（予言 +3〜6k）、FF +8.3k（予言 +3〜6k、リセットの複製と dont_touch で増えた）
- 予言 6: BD 41-759 は 0（**当たり**）。CRITICAL WARNING 5（2-1 は 10 / 8）
- 予言 7（CDC-3 が ≈ 14 増えて ≈ 105）: **105（当たり**、91 → 105）。CDC-6 5・CDC-15 3,137 は 2-1 と同じ
- 結線の照合 115 行・問題 0・陽性対照 OK。RING DMA: `s45_ring_0/m_axi` → HP0_DDR_LOW（2 GiB）、リングのレジスタ 0xA0040000 + 4 KiB
- sim（この版）: sim-ring（all・late・flip）・sim-regmap・sim-win-all・sim-top・sim-tsys・sim-ringu 通過


```bash
# Vivado サーバ（2-1 の build/・build-PE/ は比べるために名前を変えて残す）
cd ~/git/rfsoc && git pull && cd proj021 && pwd
mv build build-2-1; mv build-PE build-2-1-PE
make sim-all > sim-all.log 2>&1 &                       # sim-ringu を含む（成否は各ログの「結果:」・build-sim-ringu/check.log の「総合:」）
make sim-ring > /dev/null 2>&1 &                        # 1〜2 時間 → build-sim-ring/check.log の「総合:」
make sim-tsys > /dev/null 2>&1 &                        # FULL を含む系の回帰（1〜2 時間）
make IMPL=Performance_Explore > /dev/null 2>&1 &        # → build-PE/
make > /dev/null 2>&1 &                                 # → build/（既定）
wait
grep -E 'TIMING \(確定\)' build/vivado.log build-PE/vivado.log
grep -c 'CRITICAL WARNING' build/vivado.log build-PE/vivado.log
grep -c 'BD 41-759' build/vivado.log build-PE/vivado.log              # 0 であること（持ち越し 1）
grep -E 's45_ring_0|RING ADDR|RING DMA' build/vivado.log | head
grep -E '照合した行|陽性対照' build/vivado.log
tail -n 1 build-sim-ringu/check.log build-sim-ring/check.log build-sim-tsys/check.log
make worst-paths

# Vivado サーバ → ボード（WNS の良い方）
scp build-PETO/proj021.bit build-PETO/proj021.hwh xilinx@$B:~/proj021/   # 閉じたのは PETO
scp pynq/*.py pynq/tp_cal.json xilinx@$B:~/proj021/

# ボード（root。specd を止めてから）。S22a-4
cd ~/proj021
grep Cma /proc/meminfo                                                  # 32 MiB のリングが取れること
python3 s45core.py --list --clkin 0 --ref 10                            # CAPS が 0x001 に
python3 timetest.py --clkin 0 --ref 10 --t0 --seconds 30                # P-0
python3 window.py --clkin 0 --ref 10 --probe --adc 0 --win 0            # P-1
python3 window.py --clkin 0 --ref 10 --golden --w 256                   # P-2
python3 window.py --clkin 0 --ref 10 --tone 3010.5 --w6 --w 256 --shift 11 --shift-full 8   # P-3（SG −20 dBm）
python3 plring.py --clkin 0 --ref 10 --compare                          # 9 本: レコード = AXI4-Lite（bit 単位）
python3 plring.py --clkin 0 --ref 10 --soak 60                          # ALL・10.24 ms: DROP 0・CRC 0・SEQ の飛び 0・REC_LATE 0
python3 plring.py --clkin 0 --ref 10 --soak 20 --no-inval               # 陽性対照: CRC の不一致が立つ
python3 plring.py --clkin 0 --ref 10 --soak 20 --pause 3                # 陽性対照: DROP_CNT = SEQ の飛び > 0
```

**実機（2026-10-10、`build-PETO` の bit。S22a-4）**: **全部通過**。入力はノイズソース ＋ SG を分配器で 4 ADC へ（PATT・分配器 3 段）、1PPS あり

| 手順 | 結果 |
|---|---|
| CMA | CmaFree 118 MB（32 MiB のリングが取れる） |
| `s45core.py --list` | 4 コアとも CAPS 0x001。ほかは 2-1 と同じ |
| P-0（`timetest --t0`、30 s） | 通過（TRIG・COMP とも生きていて、間隔 ±1 ビート以内、GLITCH・MISS 0） |
| P-1（`--probe`、ADC_A の窓 0） | 通過（ダンプ 3 個・各 6,250 フレーム、FLAGS 0、pfb・ddc の飽和 0） |
| P-2（`--golden --w 256`） | 通過（numpy の FFT との最悪の差 1.4 / 許容 4.7、スナップショットのフレーム = ダンプの f0） |
| P-3（`--tone 3010.5 --w6`、SG +20 dBm） | 通過: W-1 ch 3928（予言どおり、+0.10 ppm）・W-1b 窓と全帯域の差 +6.55 kHz・**W-6 −0.055 dB**（2-1 は −0.054）。1 回目の −20 dBm は CW がノイズに埋もれて NG（窓の「山」の隣との差 −0.1 dB = 山が無い）。2-1 は SG を ADC に直結、今回は分配器 3 段と PATT を通ってノイズソースと合わさるので、+20 dBm でも ADC の飽和 0 |
| `plring.py --compare` | **通過**: 9 本（DDC 8・FULL 1）とも ONE のレコードの頭 6 語・本体 4096 語が同じ SEQ の AXI4-Lite の読みと bit 単位で一致。ONE は 1 個出して 0 に戻る。REC_CNT 9・DROP 0・ERR 0。BASE 0x78600000・SIZE 32 MiB・範囲の invalidate（pyxrt の bo.sync）が効く |
| `plring.py --soak 60` | **通過**: 9 本とも 5,859 レコード。SEQ の飛び 0・DROP_CNT 0・REC_LATE 0・CRC の不一致 0・尾の不一致 0。PEAK 657,920 B（2.0 %）。1 回の読み（範囲の invalidate ＋ 全部の CRC ＋ 写し）中央 5.4 ms・p99 9.0 ms・最大 9.1 ms（5,500 回、10.24 ms × 9 本に追いつく） |
| `--soak 20 --no-inval`（陽性対照） | 通過: 2 個目のレコードの頭が古い行（初めに書いた 0）のまま見えた（magic 0x0）。**1 回目は道具がこれを例外で止め、REC_CTRL を ALL のままバッファを返して Segmentation fault**（`plring.py` を直した: magic の不一致も「古い行」として数える・閉じるとき REC_CTRL を 0 にし busy が落ちてから返す） |
| `--soak 20 --pause 3`（陽性対照） | 通過: **SEQ の飛び 2,211 = DROP_CNT 2,211**、PEAK 100 %（リングが満ちて丸ごと捨てた）、CRC の不一致 0・REC_LATE 0 |

- 予言 8: 全部**当たり**（PEAK は 2 %）。INTERFACE 8. の 6 の残り（PS が全部のレコードで CRC を確かめられるか）は、SAM45-Fine の量（9 本 × 10.24 ms）で **確かめられる**（1 回の読み 5〜9 ms）
- 判定 S22a-1〜4 は全部通過 → **2-2a 通過**。次は 2-2b（TP のレコード、V2-e）

### 手順 2-2b — TP のレコード（設計と予言、2026-10-10。RTL を書く前）

**足すのは「TP の個をレコード（type 2、INTERFACE 4.6）にしてリングへ出す道」だけ**。TP の区切り・和・FLAGS・AXI4-Lite の TP のリング（0x2000〜）は変えない。
判定の芯は V2-e: **同じ個が、レコードと AXI4-Lite の TP のリングで bit 単位で一致する**。

**作り方（`tp_core` に `REC = 1` で足す。win_core の TP だけ。FULL の流れ（spec_core）の TP は今のまま AXI4-Lite だけ）**:
- 個がリングに書かれるクロック（今の `e_we`）に、個の 16 バイト・その個の番号（TP_WP）・最初のフレームの番号（48 bit）・**その区切りの最初のビートの T** を受ける。
  T は区切りの頭を決めた s0 のクロックの `t_loc` を取っておき、個と一緒に渡す（TANCH の ANCH_T と同じ物差し）
- 区切り方（INTERFACE 4.6 の「細部は proj021」をこう決める）:
  1. 1 レコード = K 個（TP_REC_CTRL の [12:8]、既定 10 = 10.24 ms。1〜16）
  2. **F0 で始まった個（FLAGS[1]）の前で必ず区切る**（RUN の後のレコードは F0 + K·TP_N·m に揃う）
  3. **短い個（FLAGS[0]）の後で必ず区切る**
  → 1・2・3 のどれかで閉じたレコードは K 個未満のことがある（DUMP_N で分かる）
- 頭: w0 = {s 0xFF, core, type 2, ver 1, "S45R"}、w1 = SEQ（最初の個の番号）、w2 = DUMP_F0（最初の個の最初のフレーム、48 bit）、w3 = DUMP_T、w5 = DUMP_N、w7 = 中身のバイト数（16·DUMP_N を 64 の倍数に切り上げ。10 個で 192）、ほかは 0
- 中身: 個をリングと同じ 16 バイト（和 u64・F0 の下位 32・FLAGS | フレーム数）で並べ、64 の倍数まで 0 で詰める
- 溜め: レコード 2 面（分散 RAM）。出口が詰まって 2 面とも埋まっているときに次のレコードが始まったら、**そのレコードは丸ごと捨てて** TP_REC_LATE +1・リングの DROP_CNT +1（rec_drop）。
  PS は SEQ の飛び（前の SEQ ＋ DUMP_N ≠ 次の SEQ）で分かる
- 出口: win_core の中で SPEC のレコード（rec_fr）と rec_arb（2 本）でレコード単位に束ねる。s45_core・s45_ring は変えない
- レジスタ（TP のレジスタの続き。REC = 0 の FULL の TP では今どおり 0xDEADBEEF）: **0x11C TP_REC_CTRL**（RW: [0] EN・[12:8] K。既定 0x0A00）・**0x120 TP_REC_LATE**（R）
- コアの共通の CAPS = 0x003（[1] TP をレコードで）
- PS: `plring.py --tpcompare`（4 ADC の TP のレコードを数秒集め、AXI4-Lite の TP のリング（512 個、TP_WP の seqlock）と個の番号で突き合わせて bit 単位で比べる。SEQ の飛び 0、DUMP_F0 の下位 = 最初の個の F0、
  **DUMP_T = ANCH_T + (DUMP_F0 − ANCH_F)·512**（TANCH で錨を取り、その間に GAP_CNT が増えていなければ厳密）。`--soak` にも TP のレコードを混ぜる

**予言**:
1. sim（新しい sim-tprec: 今の sim-tp の試験台 ＋ REC = 1・出口の止まりをランダムに・途中に長い止まりを 1 回）: 出たレコードの個が、模型（check_tp.py の区切りの模型）と bit 単位で一致。
   区切りの規則 1〜3 のとおりに分かれ、DUMP_F0・DUMP_T（試験台のクロックの番号）が模型と一致。長い止まりで捨てたレコードの数 = TP_REC_LATE = rec_drop の数 = SEQ の飛びから数えた数
2. 陽性対照: 「F0 で始まった個の前で区切らない」変種（-DTP_REC_POSCTL）→ 区切りの照合が落ちる
3. 回帰: sim-tp・sim-tp-p（REC = 0 の tp_core は今と同じ）・sim-regmap（CAPS 3・TP_REC の 2 本）・sim-ring（TP のレコードが混ざっても SPEC のレコードは全部正しい）
4. 資源: LUT +1,000〜+2,000（4 コア）、FF +1,500〜+3,000、BRAM 0（溜めは分散 RAM）、DSP・URAM 同じ
5. 時間: 2-2a の PETO（+0.022）と同じ戦略の組で回し、少なくとも 1 本で閉じる。新しい壁は無い見込み（TP の個は 512 クロックに 1 個より遅い）
6. 実機: `--tpcompare` で 4 ADC とも個が bit 単位で一致・SEQ の飛び 0・DUMP_T の式が ±0 ビート。`--soak 60` で TP のレコード 4 × 5,859 個・DROP 0

**判定**:

| 判定 | 中身 |
|---|---|
| S22b-1 | sim-tprec が通る（予言 1）。陽性対照（予言 2）が落ちる |
| S22b-2 | 回帰（予言 3） |
| S22b-3 | ビルド: どれかの戦略で WNS ≥ 0・WHS ≥ 0・結線の照合・CDC の分類は 2-2a と同じ |
| S22b-4 | 実機（予言 6） = **V2-e** |


**実装（2026-10-10）**: `tp_core` に `REC`（win_core は 1、FULL の spec_core は 0）。個の 16 バイトと番号（TP_WP）・最初のフレーム（48 bit）・区切りの最初のビートの T を受けて、
溜め 2 面（分散 RAM、16 個 × 128 bit × 2）にレコードを組む。win_core で rec_arb（2 本）により SPEC のレコードと束ね、rec_drop は [NW] に足した。
レジスタ 0x11C TP_REC_CTRL・0x120 TP_REC_LATE（REC = 0 では今どおり 0xDEADBEEF）。CAPS 3。PS: `plring.py --tpcompare`、`--soak` に TP のレコードを混ぜた

**sim（クラウド、iverilog 12）**:

| sim | 結果 |
|---|---|
| sim-tprec（予言 1） | 通過: TP のレコード 46 個の頭（SEQ・F0・**T**・DUMP_N・バイト数）と中身が模型と bit 単位で一致。長い止まり（60,000 クロック）で捨てた 10 = TP_REC_LATE 10 = rec_drop 10。K 個未満のレコード 2・F0 で始まったレコード 2 |
| sim-tprec-p（予言 2） | 落ちた（F0 の前で区切らない変種で、レコードの頭が模型の区切りとずれる） |
| sim-tp（REC = 0 の回帰） | 通過 |
| sim-regmap | 通過（190 項目: CAPS 3・TP_REC_CTRL の既定 0x0A00・TP_REC_LATE 0 を足した） |
| sim-ring（TP のレコードを混ぜた版） | 通過（Vivado サーバ）: TP のレコード 18 個が模型と一致・SEQ の飛び 0、SPEC のレコードも全部正しい |

### 2-2b のビルドと実機

```bash
cd ~/git/rfsoc && git pull && cd proj021
mkdir -p old && mv build-PETO old/build-2-2a-PETO; mv build-PE old/build-2-2a-PE 2>/dev/null
make sim-all > sim-all.log 2>&1 &                       # sim-tprec・sim-tprec-p を含む
make sim-ring > /dev/null 2>&1 &                        # TP のレコードを混ぜた版
make IMPL=Performance_ExtraTimingOpt JOBS=14 > /dev/null 2>&1 &
make IMPL=Performance_Explore JOBS=14 > /dev/null 2>&1 &
wait
grep -E 'TIMING \(確定\)' build-PETO/vivado.log build-PE/vivado.log
tail -n 1 build-sim-tprec/check.log build-sim-tprec-posctl/check.log build-sim-ring/check.log

# ボード（閉じた方の bit。specd を止めてから）。S22b-4 = V2-e
python3 s45core.py --list --clkin 0 --ref 10                            # CAPS が 0x003 に
python3 plring.py --clkin 0 --ref 10 --tpcompare                        # 4 ADC: TP のレコードの個 = AXI4-Lite の TP のリング・SEQ の飛び 0・DUMP_T の式
python3 plring.py --clkin 0 --ref 10 --compare                          # 2-2a の回帰
python3 plring.py --clkin 0 --ref 10 --soak 60                          # SPEC 9 本 ＋ TP 4 本: 取りこぼし 0
```

ビルドの結果（2026-10-10）:

| 実装 | WNS | WHS | 備考 |
|---|---|---|---|
| Performance_ExtraTimingOpt（build-PETO） | −0.078 ns（165 端点） | — | 閉じない |
| Performance_Explore（build-PE） | −0.0045 ns（1 端点: gb_dn_1 → u_aev） | — | 閉じない |
| build-PE → `make physopt OUTDIR=build-PE`（build-PE-po） | **+0.011 ns** | **+0.010 ns** | 配線後の phys_opt_design（AggressiveExplore で閉じた）|

- **2-2b の bit は build-PE-po**。`make physopt` は配線の済んだ dcp を開き、`phys_opt_design` を AggressiveExplore → AggressiveFanoutOpt → AlternateReplication → Explore の順に、WNS・WHS がともに 0 以上になるまで掛けて bit を書く（`tools/postroute_physopt.tcl`）。数 ps の残りは作り直しより安い
- RTL は 2-2b の実装のまま（ビルドのための RTL の変更は無し）

```bash
scp build-PE-po/proj021.bit build-PE-po/proj021.hwh xilinx@$B:~/proj021/
scp pynq/*.py xilinx@$B:~/proj021/
```

**実機（2026-10-10、`build-PE-po` の bit。S22b-4 = V2-e）**: **全部通過**。入力は 2-2a と同じ（ノイズソース ＋ SG を分配器で 4 ADC へ）

| 手順 | 結果 |
|---|---|
| `s45core.py --list` | 4 コアとも CAPS **0x003**。NSTREAM・流れの表は 2-1・2-2a と同じ |
| `plring.py --tpcompare`（V2-e） | **通過**: 4 ADC とも TP のレコード 298 個、AXI4-Lite の TP のリング（512 個）と重なった個 509〜511 個が **bit 単位で一致**（不一致 0）。SEQ の飛び 0・**DUMP_T の式（ANCH_T + (F0 − ANCH_F)·512）の外れ 0**（GAP_CNT 0 → 0）・CRC 0。リングの REC_CNT 1,192（= 298 × 4）・DROP 0・ERR 0。「リングの外」は AXI4-Lite のリングが既に上書きした古い個（照らせないだけ） |
| `plring.py --compare`（2-2a の回帰） | 通過: 9 本とも SPEC のレコード = AXI4-Lite（bit 単位）。REC_CNT 9・DROP 0・ERR 0 |
| `plring.py --soak 60` | **通過**: SPEC 9 本は各 5,860、**TP 4 本は各 5,865**。SEQ の飛び 0・DROP_CNT 0・REC_LATE 0・CRC の不一致 0・尾の不一致 0。PEAK 924,928 B（2.8 %）・REC_CNT 76,208・ERR 0 |

- 予言 6: **当たり**。TP のレコードは予言の 5,859 より 6 多い 5,865。SEQ の飛び 0（個は欠けていない）なので、区切りの規則 2・3（F0 で始まった個の前・短い個の後）で閉じた K 個未満のレコードが混ざった分と見る（`--soak` は DUMP_N の分布を出していないので、内訳は未確認）
- **PS の読みの重さ**: 1 回の読み 中央 14.7 ms・p99 14.9 ms・最大 15.1 ms（3,160 回）。60 s のうち読みに使った時間は 2-2a の ≒ 30 s（5,500 × 5.4 ms）から **≒ 46 s（77 %）**に増えた（1 回あたり 2-2a ≒ 10 レコード → ≒ 24 レコード。TP のレコードは小さいが、Python のレコードごとの処理が効く）。追いついてはいるが、2-3（specd）では CRC と写しを C か numpy の一括処理にする
- 判定 S22b-1〜4 は全部通過 → **2-2b 通過**。次は 2-2c（SNAP のレコード ＋ 仮の読み窓を外して 64 KiB に）

### 手順 2-2c — SNAP のレコード（設計と予言、2026-10-10。RTL を書く前）

**足すのは「スナップショットを SPEC のレコードの直後にレコード（type 4、INTERFACE 4.6）で出す道」だけ**。スナップショットの書き方（どのフレームを残すか）・スペクトル・TP は変えない。
判定の芯は 2-2a と同じ型: **同じダンプのスナップショットが、レコードと仮の読み窓（AXI4-Lite）で bit 単位で一致する**。その上で V2-c（W-G をレコードで）。

**計画を 1 つ変える: 仮の読み窓を外して 64 KiB に縮めるのは 2-2c ではなく、specd がリングを読むようになった後（2-3 の後、「2-2d」）にする**。
- 今、仮の読み窓を読んでいる道具: s45acq（specd のスペクトルと SNAP）・window（P-1・P-2・P-3）・spectrometer（全帯域の golden・FULL の TP）・timetest（P-0・P-5）・fine・plring の `--compare`。
  2-2c で外すと **specd が 2-3 まで動かず**、P-* の回帰と「レコード = AXI4-Lite」の照合（2-2a〜2-2c の判定の芯）も同時に失う
- 外すのは「番地を縮める」「SNAP_SEL を消す」「FULL の TP の置き場所を決める」（FULL の TP は今 0xC1100・0xC2000 にしか無い）を含む別の変更で、PS の道具の書き換えとまとめて 1 手順にする方が、変更を一度に一つに保てる

**作り方（rec_fr に「SNAP の相」を足す。win_core・spec_core は読みの口に切り替えを足すだけ）**:
- REC_CTRL の [2] SNAP が立った流れは、**出す SPEC のレコード（ALL でも ONE でも）の直後に、同じダンプのスナップショットを type 4 のレコードで出す**。
  INTERFACE の「ONE で出すダンプに付ける」は使い方（PS は ONE | SNAP = 6 を書く）で、ALL | SNAP は試験に使う。SNAP だけ（ALL・ONE なし）はレコードを出さず、下の「書く流れ」を決めるだけ
- 頭: w0 = {s, core, type 4, ver 1, "S45R"}、w1〜w6 = **組の SPEC と同じ**（SEQ・DUMP_K・DUMP_F0・DUMP_T…）、w7 = 中身のバイト数（DDC 32,768・FULL 16,384）
- 中身（INTERFACE 4.6 の「今の 0x08000・0x4000 と同じ」）:
  - DDC: PFB の出口（FFT の入力）4096 個。u64 の語 i = {im（32 bit に符号拡張）, re（同）}（仮の読み窓の 0x08000 + 8i の re・+4 の im と同じ並び）
  - FULL: ADC の生サンプル 8192 個（16 bit）。u64 の語 j = サンプル 4j〜4j+3（仮の読み窓の 0x4000〜 と同じバイトの並び）
- 読み方: rec_fr は SPEC を出し終えても口（gnt）を返さず、続けて同じ口でスナップショットの記憶を読む（`rd_snap` で切り替え）。
  DDC は今の仮の読み窓と同じく `ax_ch`・`ax_bank` → `sn1` → `sn2`（スペクトルの `sp_data` と同じ遅れ）、FULL は `snap_ra` → `snap_rd1` → `snap_rd2` と 64 bit の選び（スペクトルの k2 と同じ遅れ）。LAT 5 のまま
- **上書きの見張り（ここが SPEC と違う）**: スナップショットはダンプの**最初**のフレームを残すので、ダンプ k の面は、ダンプ k+2 の最初のフレームで上書きされる。
  これは **SEQ が動くより前**（DDC はダンプ k+1 が閉じる前、FULL は FFT の遅れぶんさらに前）なので、SPEC の見張り（SEQ が動いたら捨てる）では拾えない。そこで:
  - 流れの持ち主が `snap_ok`（その流れの読みの面のスナップショットのフレーム番号 = DUMP_F0、DDC は加えて下の「書いた流れ」の札が揃っている）を 1 段のレジスタで出す
  - SNAP の相の**頭**で `snap_ok` を見る（違えば最初から捨てる相: tuser = 1）。**最後の語を取り込んだ 2 クロック後**にもう一度見て、違えば tuser = 1。最後の語はこの見張りが済むまで出口に出さない
  - 上書きは「番号を替える → 書く」の順（DDC は番号から書き込みまで 10 クロック前後、FULL は同じクロック）なので、取り込み終わった後に番号が変わっていなければ、読んだ語は上書きの前
  - 捨てたら REC_LATE +1（SPEC が出たのに SNAP が出なかったとき）。tuser = 1 なのでリングの DROP_CNT +1（INTERFACE 4.1 の「出すべきで出なかったレコードの数」）。SPEC を捨てたダンプの SNAP も同じ相を通して tuser = 1 にする（数えを合わせるため。REC_LATE は SPEC の 1 回だけ）
- **DDC のスナップショットの記憶は ADC（コア）で 1 つ**（今のまま）。書く流れ = **SNAP の立った最も小さい s**、どれも立っていなければ今の仮の SNAP_SEL（今の道具がそのまま動く）。
  記憶の面ごとに「書いた流れ・番地 0 から 4095 まで途切れずに書き切った」の札を持ち、`snap_ok` に入れる（書く流れを途中で替えた面は出さない）。
  **同じコアの 2 本に SNAP を立てると、大きい s の方の SNAP は出ない**（REC_LATE・DROP_CNT。PS は 1 本ずつ立てる）
- CAPS = 0x007（[2] SNAP をレコードで）。番地・レジスタは足さない
- **PS の手順**: SNAP を立ててから 1 ダンプ以上待って ONE を書く（`--snapcompare`）か、RUN の前に ONE | SNAP を書く（`--golden`）。スナップショットはダンプの最初のフレームなので、
  書く流れがそのダンプの頭で決まっていないと札が揃わず出ない（INTERFACE 4.6 に足した）
- PS: `plring.py --snapcompare`（流れごとに ダンプ ≈ 1 s・ONE | SNAP で SPEC と SNAP を 1 組出させ、次の上書きの前に仮の読み窓のスナップショットを AXI4-Lite で読んで bit 単位で比べる。
  頭 w1..w6 = 組の SPEC、SNAP_F（診断）= DUMP_F0）・`--golden`（V2-c: 9 本とも N_ACC 1・N_DUMP 1・ONE | SNAP で 1 組出し、window・spectrometer の W-G・全帯域の golden と同じ判定を**レコードだけで**）

**予言**:
1. sim-ring（新しい MODE = snap。流れ 0 と FULL を ALL | SNAP、流れ 1 に途中で ONE | SNAP を 1 回。ダンプは DDC N_ACC 8・FULL N_ACC 64 で SPEC ＋ SNAP の読みが間に合う長さ）:
   SNAP のレコードが、SEQ が進んだときに記憶から直に写したスナップショット（S 行）と bit 単位で一致、頭 w1..w6 = 同じ SEQ の SPEC、流れ 0・FULL は SPEC の数 = SNAP の数。
   **流れ 1 の ONE | SNAP は SPEC だけ出て SNAP は出ない**（書く流れは 0）→ REC_LATE1 = 1・DROP_CNT = 1。ほかの REC_LATE 0
2. 陽性対照: snap を `-DREC_SNAP_NOCHK`（`snap_ok` を見ない変種）で → 流れ 1 の SNAP（書いていない窓）が出て、写したスナップショットの無い SNAP として照合が落ちる。
   late（DDC N_ACC 2・FULL N_ACC 16）にも流れ 0 と FULL に SNAP を足す: 「出たレコードは全部正しい」のまま（DDC の SNAP は SPEC を読み終える前に上書きが始まるので頭の見張りで捨てる。
   どちらの見張りで捨てたかの数を出す）。**終わりの見張り（読んでいる途中の上書き）が sim で起きるかは筋書き次第**で、起きなければそう書く
3. 回帰: sim-ring all（SNAP を立てない流れのレコードは 2-2b と同じ）・sim-regmap（CAPS 7）・sim-top・sim-win4（SNAP_SEL の道は同じ）・sim-tprec・sim-ringu
4. 資源: LUT +300〜+1,000、FF +300〜+800、BRAM・DSP・URAM 同じ
5. 時間: 新しい経路は rec_fr の相の切り替えと `snap_ok` の 48 bit の比べ（1 段で受ける）。2-2b と同じ戦略の組 ＋ `make physopt`
6. 実機: `--snapcompare` で 9 本とも一致（SNAP_F = DUMP_F0・頭 = SPEC）、`--golden` で 8 窓と全帯域が P-2・全帯域の golden と同じ許容で通る。`--compare`・`--tpcompare`・`--soak 60` と P-2（仮の読み窓の W-G）は 2-2b と同じ

**判定**:

| 判定 | 中身 |
|---|---|
| S22c-1 | sim-ring の snap・late が通る（予言 1・2）。陽性対照 snap-nochk が落ちる |
| S22c-2 | 回帰（予言 3） |
| S22c-3 | ビルド: どれかの戦略（＋ physopt）で WNS ≥ 0・WHS ≥ 0・結線の照合・CDC の分類は 2-2a と同じ |
| S22c-4 | 実機（予言 6）: `--snapcompare`・`--golden`（= **V2-c の W-G**）・回帰 |

**実装（2026-10-10）**: `rec_fr` に SNAP の相（`SNAP`・`NSN`、入力 `rec_snap`・`snap_ok`、出力 `rd_snap`）。win_core はスナップショットの書く窓の選び（SNAP の最も小さい s、無ければ SNAP_SEL）・
面ごとの札（`t_own`・`t_nx`・`t_run`・`t_ok`）・窓ごとの `snok`・`fr_data` の切り替え（`sn2` を {im, re} の 32 bit に符号拡張）。spec_core は `snap_ra` を rec_fr の口にも・64 bit の選び（`fr_sb*`）・`snok`。
CAPS 7。PS: `plring.py --snapcompare`・`--golden`（`window.wg_cmp`・`spectrometer.golden_cmp`・`shift_of_snap` を切り出して共用。window・spectrometer の振る舞いは同じ）

**sim**: sim-regmap 通過（クラウド、190 項目、CAPS 7）。sim-ring（all・late・snap・snap-nochk・flip）は Vivado サーバで

### 2-2c のビルドと実機

```bash
cd ~/git/rfsoc && git pull && cd proj021
mkdir -p old && mv build-PE-po old/build-2-2b-PE-po; mv build-PE old/build-2-2b-PE; mv build-PETO old/build-2-2b-PETO 2>/dev/null
make sim-all > sim-all.log 2>&1 &                       # 回帰（sim-regmap の CAPS 7 を含む）
make sim-ring > /dev/null 2>&1 &                        # all・late・snap・snap-nochk（1〜2 時間）
make IMPL=Performance_ExtraTimingOpt JOBS=14 > /dev/null 2>&1 &
make IMPL=Performance_Explore JOBS=14 > /dev/null 2>&1 &
wait
grep -E 'TIMING \(確定\)' build-PETO/vivado.log build-PE/vivado.log
tail -n 1 sim-all.log; cat build-sim-ring/check.log
# 閉じなかった方が数 ps なら: make physopt OUTDIR=build-PE（→ build-PE-po）

# ボード（閉じた bit。specd を止めてから）。S22c-4
python3 s45core.py --list --clkin 0 --ref 10                            # CAPS が 0x007 に
python3 plring.py --clkin 0 --ref 10 --snapcompare                      # 9 本: SNAP のレコード = 仮の読み窓のスナップショット
python3 plring.py --clkin 0 --ref 10 --golden                           # V2-c: W-G（8 窓）と全帯域の golden をレコードだけで
python3 plring.py --clkin 0 --ref 10 --compare                          # 回帰
python3 plring.py --clkin 0 --ref 10 --tpcompare
python3 plring.py --clkin 0 --ref 10 --soak 60
python3 window.py --clkin 0 --ref 10 --golden --w 256                   # P-2（仮の読み窓の W-G。SNAP_SEL の道）
```

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
3. **SAM45-Fine の FULL の流れと RFI の見張り**（2026-10-09 の相談。採否は決めた。手順の番号は 2-2 の後に振る）
   - 背景: フロアマップ（`make floorplan`、1b の dcp）で、FULL（spec_core_0）は置かれたプリミティブの約 15 万 / 63 万（≒ 24 %）・DSP 504 / 2600（19 %）、クロック領域の Y0〜Y2 の大部分。BITS.md の SAM45-Fine は「4 ADC × 2 窓」で、全帯域は製品に入っていない。今 FULL に頼っているのは F-2（1PPS の縁を ADC の生サンプルで見る）・specd の SNAP・W-6 / W-1b / 全帯域の golden（開発の確かめ）
   - **(1) 採用: FULL を「生サンプルの流れ」に替える**。選んだ ADC の生サンプル 8192 個を取るだけ（BRAM 数個、FFT なし）。v2 の枠でスナップショット専用の KIND として足し、PS は自己記述（NSTREAM・KIND）で分かれる。F-2 と SNAP はこれで足りる。W-6・W-1b は TP との比（P-8 の型）と SG の絶対周波数で代える。**2-1・2-2 の間は FULL を残す**（今の回帰と v2 の FULL の流れの確かめに使う。変更は一度に一つ）。spec_core の RTL は SAM45-Wide・2G・512M の全帯域で使うので共通部品として残る
   - **(2) 採用: TP の跳ねの見張り（specd）**。ADC 1 本の TP（≒ 2 GHz、1.024 ms）の列から秒程度の移動中央値を引き、局所の MAD による k·σ を越える跳ねに印を付ける。R の 5〜10 dB の段差はスキャンの状態（CFG_ID に ON / OFF / R を入れ、DUMP_CFG で見る）で除く。雲・仰角の変化は移動中央値で消える。OVR_CNT・DUMP_H[4]（ADC の振り切れ）と合わせて出す
     - 感度の見積もり: 熱雑音は 1/√(B·τ) = 7×10⁻⁴（1.024 ms）・2×10⁻⁴（10 ms）、実際は利得の揺らぎ 10⁻⁴〜10⁻³ が効く → 全帯域の電力の ≒ 10⁻³（−30 dB）以上の突発的なもの。窓の ch に直すと 256 MHz 窓で ch の雑音の ≒ 30 倍、2 MHz 窓で ≒ 4000 倍。弱く居座るスプリアスは TP では見えない（下の判断で問題にしない）
   - **(3) 不採用: 粗い PFB（128 MHz × 17）の ch ごとの TP**。それなりに資源を食うので、科学観測の機能に回す。判断（2026-10-09）:
     - 観測中に問題になるのは ADC が溢れるほどの強い RFI で、それは全帯域の TP（と OVR_CNT）で検出できる
     - ADC が溢れない程度の RFI は、(a) 窓の外にいれば窓の中のスペクトルに影響しない、(b) 窓の中にいれば観測者から通報してもらい、観測所がメンテナンス時間に対処する（原因究明は観測時間外に Wide モードで）
     - 常時いるスプリアスは ON − OFF で消える

## やったこと

- 2026-10-08: proj020 の追跡されているファイルを複製（`runs/` と README を除く。RTL・build.tcl・Makefile・pynq は proj020 のまま、ID も 0x0020 系のまま）。README を起こした
- 2026-10-08: 手順 1a（構成替え、8264e62）→ Vivado サーバで build-PE の WNS / WHS が proj020 と小数 6 桁まで同じ（+0.047121 / +0.009645）、既定の戦略も −0.063186 / +0.009660。DSP 2600・BRAM 305（RAMB36 129・RAMB18 352）・URAM 56・LUT 48.16 %・CDC-3 105 / CDC-6 5 / CDC-15 3137・CRITICAL WARNING なしも proj020 と同じ → **1a 通過**（構成替えで何も変わっていない）
- 2026-10-08: 手順 1b（gb_gate のスキッド・ID 0x0021、dc69360）。sim-gb・sim-all 通過、既定の戦略で `-1` が閉じた（+0.008）・群 C は消えた・CDC は同じ、実機で G-3（50 回 OK）・G-4（陽性対照 13 / 50）→ **1b 通過**（上の 1b の節）
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

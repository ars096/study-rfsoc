# RFSoC4x2 再開ランブック

RFSoC4x2 で電波分光計の開発を再開するための立ち上げ手順。
まず「PS を一切使わない LED 点滅」で工具箱とボードの生存を確認し、
そこから PYNQ オーバーレイの型に移る。各ステップに合否判定を付けてあるので、
詰まった場所が切り分けられる。

初版 2026-09-11（proj001 の作業記録から）。**環境が変わったら更新する生き物として扱う。**

## 版の固定

| | 値 | 備考 |
|---|---|---|
| Board | RealDigital RFSoC 4x2 | XCZU48DR / FFVG1517 |
| Part | `xczu48dr-ffvg1517-2-e` | BSP board_files の宣言値 |
| Vivado | 2023.2 | Phase 1 は問題なし。2024.1 への移行を検討中 |
| PYNQ image | v3.1.1 (Carlisle) | Vivado 2024.1 前提 |
| Board files | RealDigitalOrg/RFSoC4x2-BSP | Vivado 2024.1 前提 |
| License | Vivado ML Enterprise | ZU48DR は無償の Standard では対象外 |

Vivado 版と PYNQ イメージ版がずれると、RF Data Converter のドライバ互換で必ず苦しむ。
STEP 3〜5 の PL only LED は IP も board file も使わないので 2023.2 で問題ない。

## 全体の道筋

| | 内容 |
|---|---|
| **Phase 1（済）** | 光らせる。ツールチェーン・ライセンス・ケーブル・ボード・ピン定義を同時に検証 |
| **Phase 2** | PYNQ から叩く。Zynq MPSoC + AXI GPIO。制御系の疎通と `.hwh` の流儀 |
| **Phase 3** | 分光計へ。RFDC → PFB/FFT → 積分 → 読み出し |

---

## STEP 0 — サーバ環境とケーブル経路の棚卸し

### Vivado の実体を探す

GUI が起動していても `vivado` がシェルの PATH に無いのが普通。GUI はランチャや
デスクトップエントリから絶対パスで起動されているだけで、ログインシェルの環境とは無関係。

```bash
# GUI が動いているならプロセスから実体が分かる
ps -ef | grep -i '[v]ivado' | head -3

# よくある場所を総ざらい（他バージョンの有無も見る）
ls -d /tools/Xilinx/Vivado/*/ /opt/Xilinx/Vivado/*/ /opt/xilinx/Vivado/*/ \
      /usr/local/Xilinx/Vivado/*/ 2>/dev/null

# 絶対パスで版を確認（source は不要）
/tools/Xilinx/Vivado/2023.2/bin/vivado -version
```

> **`settings64.sh` を `.bashrc` に書かない**
>
> `bin/vivado` は起動スクリプト自身が `LD_LIBRARY_PATH` などを組み立てるので、
> **絶対パスで叩くだけで動く。**
>
> 一方 `source settings64.sh` を `.bashrc` に入れると、Xilinx 同梱の古い `libstdc++` や
> `libcrypto` が `LD_LIBRARY_PATH` の先頭に入り、`git` / `ssh` / `python` が突然壊れる。
> 原因が Vivado だと気づくまで確実に時間を溶かすので、**Makefile 側でインストール先を持つ**
> のが正解（STEP 4）。

### ライセンスとケーブル

```bash
echo "$XILINXD_LICENSE_FILE"
lsusb | grep -iE 'future|ftdi|0403:'
ls /tools/Xilinx/Vivado/2023.2/bin/hw_server
```

ケーブルドライバが未導入なら一度だけ（要 root）:

```bash
cd <Vivado>/data/xicom/cable_drivers/lin64/install_script/install_drivers
sudo ./install_drivers
```

> **物理接続の注意**
>
> RFSoC4x2 の `PROG UART` microUSB は FTDI FT2232 で、JTAG と UART を兼ねている。
> `hw_server` は *ボードが刺さっているマシン* で動く必要があり、
> **macOS 版の hw_server は存在しない。**
>
> 取り得る構成は 2 つ。**(a)** ボードを Vivado サーバ本体の USB に刺す（一番楽）。
> **(b)** ボードは別の Linux 機に刺し、そちらで `hw_server -d` を起動して Vivado から
> `connect_hw_server -url <host>:3121` で繋ぐ。

**判定**: `vivado -version` が 2023.2 を返し、`lsusb` に FTDI が現れ、Hardware Manager で
`open_hw_target` が `xczu48dr` を 1 個見つける。

---

## STEP 0b — ライセンス

RFSoC の ZU48DR は **無償の Vivado ML Standard の対象外**。Standard のインストーラでは
RFSoC デバイスがグレーアウトして選択すらできず、合成には Vivado ML Enterprise の
ライセンスが必要。再開プロジェクトではここが最初の実質的な関門になりやすい。

> エラーが `part not found` ではなく
> `Failed to get the license ... device 'xczu48dr'` なら、
> **インストール自体は ZU48DR のデバイスファイルを含んでいる。**
> デバイスサポートの問題は消え、残りはライセンスの権利範囲だけに絞られる。

### 3 つの原因を切り分ける

License Manager の表は列が多いが、見るべきは 3 列だけ。
**Expiration Date**・**Version Limit**・**Host IDs Match**。

| 原因 | 見分け方 | 対処 |
|---|---|---|
| Host ID が一致しない | `Host IDs Match` が `No` | **rehost（再発行）** — 再申請ではない |
| 期限切れ | `Expiration Date` が過去日 | 更新。ただし `Permanent` の行が別にあればそちらを使う |
| version cap が古い | `Version Limit` < 使う Vivado の要求値 | 該当する旧 Vivado を使う / 更新 |
| そもそも無い | `Synthesis` feature が一覧に出ない | AUP donation program に申請 |

**この 3 つは独立**で、どれか 1 つでも欠けると同じエラーになる。
赤い列が複数あることがあるので、**1 つ見つけて納得しない**。

### Version Limit の読み方

各 Vivado リリースは「リリース年月」に相当するライセンス版を要求する。

| Vivado | 要求するライセンス版 |
|---|---|
| 2023.2 | 2023.10 |
| 2024.1 | 2024.05 |
| 2024.2 | 2024.11 |
| 2025.1 | 2025.05 |

したがって、たとえば `Version Limit` が `2024.12` でも `2025.01` でも **実務上の上限は同じ**で、
どちらも Vivado 2024.2 まで。**ライセンスが新しくなっても使える Vivado が新しく
なるとは限らない。**

### Host ID が一致しない場合 — rehost

Nodelocked ライセンスは特定マシンの MAC アドレスに紐付いている。
**サーバを入れ替えた / 別のマシンで作業している / NIC が変わった**と一致しなくなる。
数年ぶりの再開なら、これが最も起こりやすい。

```bash
LMU=$XILINX_VIVADO/bin/unwrapped/lnx64.o/lmutil
$LMU lmhostid
$LMU lmhostid -ether
ip -o link show | awk '{print $2, $(NF-2)}'
```

| 結果 | 意味 | 対処 |
|---|---|---|
| 一覧の中に存在する | その NIC が down、または仮想 IF に隠れている | `ip link set <if> up`。無料・即時 |
| 存在しない | 別マシン、または NIC 交換済み | rehost する |

#### どの Host ID を選ぶか — ここが一番重要

rehost の回数には制限がある場合があるので、**次の座席移動でもマシン更新でも
生き残る MAC** を選ぶ。

| 候補 | 判断 | 理由 |
|---|---|---|
| オンボード NIC（`enp6s0` 等） | **これを使う** | M/B に実装されている。座席が変わっても OS を入れ替えても不変 |
| `docker0` / `virbr0` / `br-*` | 使わない | Docker 再インストールやブリッジ再作成で MAC が変わる |
| USB LAN アダプタ | 使わない | 紛失・故障・流用のいずれかで必ず失われる |
| `lo` | 使えない | 全マシン共通の `00:00:00:00:00:00` |

入力形式は **区切り無し・小文字**（例: `00:00:5e:00:53:af` → `00005e0053af`）。

#### 手順

サイト: <https://account.amd.com/en/forms/license/license-form.html>
（Vivado License Manager の *Manage License* 画面からもリンクされている）

1. ライセンスを生成したアカウントでログインする
2. **Manage Licenses** タブを開く。上段の表に生成済みライセンス、行を選ぶと下段に中身
3. 対象の行を選ぶ。`Permanent` / Version Limit の大きい側。迷ったら **View** で中身を確認
4. **Modify License** → **System Information**
5. Host ID を書き換える。ドロップダウンで種別（Ethernet MAC）を選び、テキスト欄に入力
6. **Next** を 2 回 → **Accept** で Affidavit of Destruction に同意

> **手続き後、何が発行されたかを必ず確認する**
>
> rehost を申請しても、既存の行が書き換わるのではなく
> **別の期限付きライセンスが新規に発行される場合がある。**
> 合成は通るようになるので成功したように見えるが、License Manager を見ると
> もとの行は古い Host ID のまま `No` が残っていることがある。
>
> つまり **期限付きライセンスで動いているだけで、恒久ライセンスは未復旧**という状態。
> 手続き後は必ず表を開き直し、対象の行が `Yes` になったかを確認する。

`Modify License` が出ない場合は、詳細表示の **Delete** でライセンスファイルを削除すると
entitlement がアカウントに戻り、新しい Host ID で再生成できる。

#### 新しい .lic を入れる

Vivado は `~/.Xilinx` 配下の `.lic` を**すべて**読む。古いファイルが残っていると
License Manager の表が数十行に膨らんで読みにくくなるので、退避してから入れる。

```bash
ARC=~/.Xilinx/archive-$(date +%Y%m%d)
mkdir -p "$ARC" && mv ~/.Xilinx/*.lic "$ARC"/
cp ~/Downloads/Xilinx.lic ~/.Xilinx/
```

**判定**: `Synthesis` 行が、期限が未来（または `Permanent`）・`Version Limit` が使う
Vivado 以上・`Host IDs Match` が `Yes` の 3 条件をすべて満たしている。

### 待っている間に進められること

Hardware Manager は **合成ライセンスを必要としない**。ボードの疎通確認、JTAG チェーンに
デバイスが居ることの確認、cable driver の検証は今すぐできる（`make id`）。
ただし **速度グレードは JTAG からは読めない**（IDCODE に入っていない）。

---

## STEP 1 — board files を入れて part 文字列を確定する

```bash
mkdir -p ~/opt && cd ~/opt
git clone https://github.com/RealDigitalOrg/RFSoC4x2-BSP.git

mkdir -p ~/.Xilinx/Vivado
cat >> ~/.Xilinx/Vivado/Vivado_init.tcl <<'EOF'
set_param board.repoPaths [list $::env(HOME)/opt/RFSoC4x2-BSP/board_files]
EOF
```

確認（`vivado -mode tcl`）:

```tcl
get_board_parts *rfsoc4x2*
#=> realdigital.org:rfsoc4x2:part0:1.0
```

part 文字列は暗記せず board file から引く:

```bash
grep -roh 'xczu48dr[a-z0-9-]*' ~/opt/RFSoC4x2-BSP/board_files/ | sort -u
#=> xczu48dr-ffvg1517-2-e
```

---

## STEP 2 — ピンの一次情報

下表はリファレンスマニュアル Rev A5 由来。**BSP の XDC を一次情報として突き合わせる。**

```bash
grep -rinE 'LED|SYS_CLK|100M|PB[0-3]' ~/opt/RFSoC4x2-BSP --include='*.xdc'
```

| 信号 | PACKAGE_PIN | IOSTANDARD | 備考 |
|---|---|---|---|
| PL_USER_LED0 | AR11 | LVCMOS18 | 緑・単色 |
| PL_USER_LED1 | AW10 | LVCMOS18 | |
| PL_USER_LED2 | AT11 | LVCMOS18 | |
| PL_USER_LED3 | AU10 | LVCMOS18 | |
| PL_USER_PB0–3 | AV12 / AV10 / AW9 / AT12 | LVCMOS18 | 押しボタン |
| PL_USER_SW0–3 | AN13 / AU12 / AW11 / AV11 | LVCMOS18 | スライドスイッチ |
| SYS_CLK_100M_P | AM15 | LVDS | 100 MHz・Si5395 生成 |
| SYS_CLK_100M_N | 要確認 | LVDS | AM16 / AN15 で記載揺れ |

ここで重要なのは **SYS_CLK_100M が Si5395 から出ている自走クロック**であること。
PS が起動していなくても PL に 100 MHz が入る。これが「JTAG だけで光る」最小構成を
成立させる。

---

## STEP 3 — PS を使わない最小の RTL

`../src/blink.v` と `../src/blink.xdc` を参照（proj001 の実物）。

100 MHz を 27bit カウンタで分周し `cnt[26:23]` を LED へ。`cnt[26]` は 0.671 s ごとに
反転（周期 1.34 s ≒ 0.75 Hz）で、隣の LED はその倍速。
**目で見て分周が効いていると分かる並びにしておく**と切り分けが速い。

**判定**: まだビルドしない。`IOSTANDARD` が全ポートに付いていること、`create_clock` が
1 本だけあることを目で確認する。UltraScale+ は IOSTANDARD 未指定のポートが 1 つ
あるだけで implementation が落ちる。

---

## STEP 4 — スクリプトでビルドする

`../build.tcl` / `../Makefile` を参照。再開の初日から非プロジェクトモードの Tcl で回す。
プロジェクトディレクトリは巨大かつ再現性がないので git に入れず、
**ソースとスクリプトだけをコミットする。**

> **速度グレードは推測しない — そして JTAG では分からない**
>
> `part` は `-1` と `-2` でタイミング解析の厳しさが変わる。
> **実機より速いグレードを指定すると解析が楽観的になり、合成は通るのに実機で落ちる。**
> LED カウンタなら影響は無いが、分光計では致命的。
>
> **JTAG からは読めない。** IDCODE にはデバイス種別しか入っておらず、
> Hardware Manager が報告するのは `xczu48dr` まで。`get_property PART` も同様。
>
> 権威ある情報源は 2 つだけ — **(a)** BSP の board file が宣言している part 文字列、
> **(b)** チップ上面の刻印。
>
> 刻印は発注型番（OPN）形式で `XCZU48DR-<S>FFVG1517<T>`、デバイス名の**直後**の数字が
> 速度グレード。一方 Vivado の part 文字列は `xczu48dr-ffvg1517-<S>-<t>` で
> **3 番目のフィールド**。位置が違うので読み替えを間違えやすい。
>
> 実測（2026-09-11）: BSP は `xczu48dr-ffvg1517-2-e`（**-2**）を宣言。
> RefMan Rev A5 本文には `-1` と読める記載があり食い違う。決着は刻印。

**判定**: `make` が `build/proj001.bit` を生成し、`timing.rpt` の WNS が正、
`drc.rpt` に critical が無い。

---

## STEP 5 — JTAG で書き込んで光らせる

```bash
make        # 合成〜bit 生成
make prog   # JTAG 書き込み
```

BOOT スイッチを JTAG 側にして電源投入。PS を使っていないので Linux が上がって
いなくても LED は動く。

> **ファン**: RFSoC はアイドルでもよく発熱する。ヒートシンク／ファンが回っていることを
> 確認してから電源を入れる。`OVERTEMPSHUTDOWN ENABLE` は保険であって冷却の代わりではない。

### 成功時のログの読み方

```
Opening hw_target .../xilinx_tcf/Xilinx/<serial>   ← ケーブルを掴んだ
is not programmed (DONE status = 0)                ← 書き込み前の状態
End of startup status: HIGH                        ← コンフィグ完了
```

最後に出る `no supported debug core(s) in it` は ILA を入れていないという通知で、
**エラーではない。**

### `There is no current hw_target` が出たら

hw_server と cs_server の起動には成功していて、**JTAG target が 1 つも
見つかっていない**状態。

```bash
lsusb | grep -iE 'future|ftdi|0403'   # (1) FTDI が見えているか
lsusb -t; ls -l /dev/ttyUSB*          # (2) どのドライバが掴んでいるか
ls -l /etc/udev/rules.d/ | grep -iE 'xilinx|digilent|ftdi'   # (3) udev ルール
```

| (1) の結果 | 意味 | 対処 |
|---|---|---|
| 何も出ない | USB まで届いていない | 電源 / ポート / ケーブル / 接続先マシン |
| `0403:6010` が出る | USB は OK。ドライバ層の問題 | ケーブルドライバを入れる |

**(1) が空の場合** — 順に確認する:

1. ボードの電源が入っているか（12 V バレルジャックと電源スイッチ、電源 LED）
2. **microUSB が `PROG UART` と書かれたポートに入っているか。**
   RFSoC4x2 には `USB DEVICE` という**見た目の同じ microUSB ポートが別にあり**、
   こちらに挿しても JTAG は出ない（`lsusb` にも FTDI が現れない）。**実際にここで詰まった**
3. そのケーブルはデータ用か。充電専用の microUSB ケーブルは `lsusb` に何も出さない
4. ボードは本当にこのマシンに繋がっているか

**(1) は出るが target が見えない場合** — FT2232 は 2 チャネル構成で、片方が JTAG、
もう片方が UART。カーネルの `ftdi_sio` が**両方**を掴むと JTAG 側が奪われる
（`/dev/ttyUSB*` が 2 個見えていたらこの状態）。

```bash
cd $XILINX_VIVADO/data/xicom/cable_drivers/lin64/install_script/install_drivers
sudo ./install_drivers
sudo udevadm control --reload-rules && sudo udevadm trigger
```

実行後、**USB ケーブルを一度抜き差しする。** udev ルールは接続時に適用される。

**判定 — Phase 1 完了**: LED0 が約 1.3 秒周期、LED3 がその 8 倍速で点滅する。
ここでツールチェーン・ライセンス・ケーブル・ボード・ピン定義の 5 つが同時に検証できた。

---

## STEP 6 — PYNQ オーバーレイ版に作り直す

同じ LED を Zynq MPSoC + AXI GPIO 経由で Python から叩く。分光計で実際に使う型は
こちらなので、ここまでやって初めて「再開できた」と言える。

### 「新しい Vivado のほうが有利か」への答え

**この種のプロジェクトでは「新しい」より「合っている」が優先する。**
狙う版は最新ではなく **Vivado 2024.1** — BSP と RFSoC-PYNQ v3.1.1 がどちらも
前提にしている版。

1. **RFDC IP と `xrfdc` ドライバのレジスタマップが一致していなければならない。**
   ずれたときの壊れ方は「動かない」ではなく **「静かに違う値を読む」**。
   スペクトルが出ているのに校正が合わない形で数週間溶ける
2. **観測装置のツールチェーンは凍結したい。** 3 年後に同じリポジトリから同じ
   ビットストリームが出ることに価値がある
3. **参考にできる設計例が特定の版に紐付いている。** BSP、base overlay、チュートリアル
4. **ライセンスに上限がある。** 手元の `Version Limit` が対応範囲を決める（STEP 0b の表）

新しい版が本当に効くのは **タイミング収束（QoR）** の 1 点だけ。PFB + FFT を高い
サンプルレートで詰めて配置配線が厳しくなったときには効くが、それは「困ってから動かす」話。

> **Vivado 2026.1 以降は体系が変わっている**
>
> AMD は 2026.1 から tier ベース（Basic / Core / Pro / Enterprise / Gold）に移行し、
> **無償の Basic tier でも起動時にライセンスファイルが必要**になった。
> 「あとで最新に上げればいい」が以前より重い操作になっている。

| やること | 2023.2 のまま | 判断 |
|---|---|---|
| PL only の LED（STEP 3–5） | 問題なし | そのまま進める |
| board file 読み込み | 警告は出るが概ね通る | 試す価値あり |
| AXI GPIO の overlay | `.hwh` の解析は版に寛容。動く見込み | 試す価値あり |
| RF Data Converter（分光計本体） | レジスタマップが `xrfdc` と食い違う危険 | **2024.1 を用意する** |

Vivado は複数版を同一マシンに共存させられる。`XILINX_VIVADO` を差し替えるだけで切り替わる。

### ブロックデザイン

project mode で開き、board part に `rfsoc4x2` を選ぶ。`Zynq UltraScale+ MPSoC` を置いて
*Run Block Automation*、`AXI GPIO` を All Outputs / width 4 で追加、
*Run Connection Automation* で `pl_clk0` と AXI 接続を張る。GPIO 出力を Make External して
`led` にリネームし、XDC には LED 4 本だけ書く（クロックは PS から来るので
`create_clock` 不要）。

**BD は `.xpr` ではなく `write_bd_tcl` の出力をコミットする。**

### PYNQ に渡すファイル

`.bit` と `.hwh` を **同じ basename で同じディレクトリに**置く。

```bash
find . -name '*.hwh'
# => ./<proj>.gen/sources_1/bd/<bd>/hw_handoff/<bd>.hwh

mkdir -p overlay
cp ./<proj>.runs/impl_1/<bd>_wrapper.bit              overlay/blink.bit
cp ./<proj>.gen/sources_1/bd/<bd>/hw_handoff/<bd>.hwh overlay/blink.hwh

scp overlay/blink.* xilinx@<board-ip>:~/jupyter_notebooks/blink/
```

```python
from pynq import Overlay
import time

ol   = Overlay("blink.bit")
gpio = ol.axi_gpio_0

gpio.write(0x04, 0x0)          # TRI: 全ビット出力

for i in range(32):
    gpio.write(0x00, i & 0xF)  # DATA
    time.sleep(0.2)
```

**判定 — Phase 2 完了**: `Overlay()` が例外なく通り（= `.hwh` が正しく対応している）、
Python から書いた値のとおりに LED のパターンが変わる。

---

## ハマりどころ

00・01 は proj001 で実際に踏んだもの。

### 00. `vivado: No such file or directory`

GUI が起動していてもシェルの PATH には入っていない。対処は `source settings64.sh` では
なく、**Makefile に `XILINX_VIVADO` としてインストール先を書く**。`.bashrc` で source すると
Xilinx 同梱の古い共有ライブラリが `LD_LIBRARY_PATH` の先頭に来て `git` / `ssh` / `python`
が壊れ、原因の切り分けに何時間もかかる。

### 01. `A valid license was not found for ... device 'xczu48dr'`

ZU48DR は無償の Vivado ML Standard の対象外。ただし `part not found` ではなくこのエラーなら
デバイスファイルは入っている — 権利範囲だけの問題。License Manager で
**Expiration Date・Version Limit・Host IDs Match の 3 つを見る**。数年ぶりの再開で最も多いのは
`Host IDs Match = No`（NIC の変更）で、これは再申請ではなく rehost で直る。

### 01b. `There is no current hw_target`

hw_server は起動しているのに JTAG target が 0 個。`lsusb` に FTDI `0403:6010` が出るかで
二分できる。**出ない場合の実績 1 位は挿すポートの間違い** — `USB DEVICE` と `PROG UART` は
同じ microUSB が隣接しており、前者では FTDI が一切現れない。
`open_hw_target` を裸で書かず `get_hw_targets` の中身を出力する `program.tcl` にしておけば、
このエラー自体が出なくなる。

### 02. PS クロックの罠 — 「書けたのに光らない」

Zynq MPSoC IP を置いた設計で `pl_clk0` を使うと、そのクロックは **PS が構成されるまで
出力されない。** SD ブートせずに JTAG で bit を書いただけでは PL は無クロックのまま静止し、
配線ミスと区別がつかない。JTAG 単体で光らせたいなら自走 SYS_CLK_100M を使う。
Zynq 入りの設計を JTAG で書くなら、SD から PYNQ を起動した状態で書き込む。

### 03. BOOT スイッチの位置

SD カードスロット脇の `BOOT` スライドスイッチが JTAG / SD を選ぶ。PL only の JTAG 試験は
JTAG 側、PYNQ オーバーレイは SD 側。切り替えたら必ず電源を入れ直す。

### 04. LVDS 終端の二重指定

`DIFF_TERM_ADV` で内部 100 Ω を有効にするのが HP バンクの基本だが、基板側に外部終端が
あると二重終端になって振幅が足りなくなる。BSP の XDC に記述があればそれを正とする。

### 05. `.hwh` の basename 不一致

`Overlay("blink.bit")` は同じディレクトリの `blink.hwh` を探す。`design_1.hwh` のままだと
読み込みで失敗する。コピー時に必ず揃える。

### 06. 版の混在

Vivado 2023.2 でビルドした RFDC 入りオーバーレイを別世代の PYNQ イメージに載せると、
`xrfdc` のレジスタマップ差で動かない／静かに誤動作する。

### 07. Vivado の GUI をリモートで使う苦痛

X11 転送は実用に耐えないことが多い。VNC か（サーバが対応していれば）リモートデスクトップを
立てておく。ただしビルドをスクリプト化しておけば、GUI が必要なのは BD を触るときだけになる。

---

## 分光計に入る前に決めておくこと

### サンプリングクロックの供給経路

オンボードの PLL（LMK / LMX 系）で自走させるのか、観測所の 10 MHz 基準に同期させるのか。
天文観測なら後者が前提になるはずで、外部基準入力の経路とクロックチップの設定を最初に
決めておかないと、RFDC のタイル構成ごと作り直しになる。**これが構成全体に最も波及する。**

### 帯域・チャンネル数・積分時間の目標値

ここから PFB の分岐数、FFT 長、積分器のビット幅と BRAM 量が一意に決まる。逆に決まって
いないとブロック構成を選べない。

### 読み出し経路

積分後のスペクトルが小さければ BRAM + AXI-Lite で足りる。ダンプ間隔を詰める／生データも
見たいなら DMA、さらに深いバッファが要るなら PL 側 DDR4（4 GB / 64 bit）。
PL DDR4 を使うかどうかは配置配線の難易度を大きく変えるので早めに。

### 当時の CASPER 資産をどう扱うか

以前 casperfpga / mlib_devel ベースだった資産があるなら、PYNQ に載せ替えるか CASPER
トールフローに戻すかの判断が必要。今回は PYNQ を選んでいるので、再利用するのは HDL コアや
設計思想だけと割り切るのが現実的。

---

## 参照した一次情報

- [RFSoC 4x2 Reference Manual Rev. A5 — RealDigital](https://www.realdigital.org/downloads/4b98c421901794107cd1e25e208fe002.pdf)（ピン割当・クロック・ブート）
- [RealDigitalOrg/RFSoC4x2-BSP](https://github.com/RealDigitalOrg/RFSoC4x2-BSP)（board files・XDC・PetaLinux BSP / Vivado 2024.1）
- [Xilinx/RFSoC-PYNQ](https://github.com/Xilinx/RFSoC-PYNQ) と [リリース一覧](https://github.com/Xilinx/RFSoC-PYNQ/releases)（PYNQ v3.1.1 Carlisle / Vivado 2024.1）
- [RFSoC 4x2 Overview — RFSoC-PYNQ](http://www.rfsoc-pynq.io/rfsoc_4x2_overview.html)
- [GPIO Tutorial — RealDigital RFSoC 4x2 Tutorials (UMD)](https://www.physics.umd.edu/hep/drew/rfsoc/gpio.html)（PYNQ オーバーレイでの GPIO 例）
- [Vivado License Type for RFSoC4x2 — PYNQ discuss](https://discuss.pynq.io/t/vivado-license-type-for-rfsoc4x2/8698)（Enterprise が必要）
- [RFSoC 4x2 Kit — AMD University Program](https://www.amd.com/en/corporate/university-program/aup-boards/rfsoc4x2.html)
- [AMD University Program — Donation Program](https://www.amd.com/en/corporate/university-program/donation-program.html)
- [UG973 — Rehost: Change Node-Locked or License Server Host ID](https://docs.amd.com/r/en-US/ug973-vivado-release-notes-install-license/Rehost-Change-Node-Locked-or-License-Server-Host-ID-for-a-License-File)
- [UG973 — Managing Licenses on the AMD Product Licensing Site](https://docs.amd.com/r/en-US/ug973-vivado-release-notes-install-license/Managing-Licenses-on-the-AMD-Product-Licensing-Site)

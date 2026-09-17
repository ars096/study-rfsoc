# clocks — LMK04828 / LMX2594 のレジスタ設定

**ここにあるのは「出荷時の控え」であって、ボードに書かれるものではない。**

`pynq/extref.py` は実行時に **ボード上の `xrfclk` パッケージのディレクトリから**
`LMK04828_245.76.txt` を読み、必要なレジスタだけ差し替えて書き込む。
ここのファイルを読むことはない。

理由は 2 つある。

1. SD カードを焼き直したときに中身が変われば、**こちらも自動的に追随する**。
   コピーを持つと、ズレたまま気づかない事故が起きる
2. 差分がコードに残るので、**何を変えたのかが後から分かる**

控えを置いてあるのは、**差分を議論するときに「元」が要る**ためと、
ボードが手元に無いときにレジスタの意味を追えるようにするためである。

## ファイル

| | 出所 |
|---|---|
| `LMK04828_245.76_stock.txt` | Xilinx/RFSoC-PYNQ `boards/RFSoC4x2/packages/tics/tics/register_txts/` |
| `LMX2594_491.52_stock.txt` | 同上 |

出所は <https://github.com/Xilinx/RFSoC-PYNQ>（**BSD 3-Clause**、Copyright (c) Xilinx, Inc.）。
このリポジトリと同じライセンス条件なので、控えとして取り込んでよい。**改変していない。**

**ファイル名に `_stock` を付けてある。** これは `xrfclk` のディレクトリに置くための
ものではない。`xrfclk._read_tics_output()` はファイル名を `_` で 2 分割して
`チップ名_周波数.txt` と解釈するので、`_` が 2 つ以上あるファイルを置くと
`set_ref_clks()` が `ValueError: too many values to unpack` で落ちる。
**ここに置いてある限り安全だが、ボードの xrfclk のディレクトリには絶対にコピーしないこと。**

## 読み方（LMK04828）

1 行 1 レジスタ。`0xAAAADD` の形で、上位 13 bit がアドレス、下位 8 bit がデータ。

```
R0 (INIT)  0x000090     ← リセット。アドレス 0x0000 は 2 回出てくる
R0         0x000010     ← 並び順に意味がある。アドレスで辞書にすると壊れる
...
```

proj004 が見ている範囲。

| アドレス | 出荷時 | 意味 |
|---|---|---|
| `0x0146` | `0x1B` | CLKin の有効化と入力タイプ。**ビット割り当て未確定。触らない** |
| `0x0147` | `0x1A` | **CLKin_SEL_MODE[6:4] / CLKin1_DEMUX[3:2] / CLKin0_DEMUX[1:0]** |
| `0x014B` | `0x26` | ホールドオーバ関係 |
| `0x0150` | `0x11` | ホールドオーバ関係（bit6 = CLKin_OVERRIDE） |
| `0x0153/54` | `0x00/0x7D` | CLKin0_R = 125 → 10 MHz 前提 |
| `0x0155/56` | `0x00/0x7D` | CLKin1_R = 125 → 10 MHz 前提 |
| `0x0157/58` | `0x03/0xC0` | CLKin2_R = 960 → 76.8 MHz 前提 |
| `0x0159/5A` | `0x07/0xD0` | PLL1_N = 2000 → 80 kHz × 2000 = 160 MHz（VCXO） |
| `0x015F` | `0x0B` | PLL1_LD_MUX = 1（PLL1 DLD）/ TYPE = 3（push-pull）→ **ロック LED** |
| `0x016E` | `0x13` | PLL2_LD。同じくロック LED |
| `0x0183` | 読出専用 | PLL のロック状態の読み返し。**本 proj では使わない**（下記） |

### `0x0147` の値

```
0x0A = CLKin0 manual、CLKin0/1 とも PLL1 へ
0x1A = CLKin1 manual、同上            ← 出荷時
0x2A = CLKin2 manual、同上
0x4A = auto モード                     （ZCU208 の 500 MHz 設定や RFSoC-MTS がこれ）
```

出典は TI のデータシートの表ではなく、**実機で動いている初期化列からの復元**である。
Ettus Research の UHD に、同じ LMK04828 を使うボードの初期化列がコメント付きで
入っている。

- `mpm/python/usrp_mpm/dboard_manager/lmk_mg.py`
  `(0x147, 0x1A),  # CLKin_SEL = CLKin1 manual; CLKin1 to PLL1`
- `mpm/python/usrp_mpm/periph_manager/x4xx_sample_pll.py`
  `(0x0147, 0x06), # CLKin_SEL_MANUAL= CLKin0, ClkIn0_Demux = PLL1, CLKIn1-Demux = Feedback mux`
- `mpm/python/usrp_mpm/dboard_manager/lmk_rh.py`
  `(0x147, 0x0A),  # CLKin_SEL = CLKin0 manual ...; CLKin0/1 to PLL1`

3 つを突き合わせると、`bit4` が CLKin0/CLKin1 の選択、`bit[3:2]` と `bit[1:0]` が
それぞれの demux であることが決まる。**`bit[6:4]` の上位側（auto モード）は本 proj では
使わない。**

R 分周のビット割り当ては UHD 側のコメント
（`(0x153, (clkin_r_divider & 0x3F00) >> 8)  # CLKin0_R divider [13:8]`）と、
TICS プロジェクト（`CLKin0_FREQ=10` / `PLL1_PD_FREQ=0.08` → R = 125、
`CLKin2_FREQ=76.8` → R = 960）の両方から裏が取れている。

### 読み返しをしない理由

LMK04828 のレジスタ読み返しは 4 線 SPI で、読み出しを `CLKin_SEL0` / `CLKin_SEL1` /
`RESET` のいずれかのピンに出す方式である。RFSoC 4x2 でそのピンがどこへ行っているかは
未確認で、有効にすると `Status_LD1`（PLL1 ロック LED）を潰す危険もある。

そこで proj004 は **書いた結果ではなく効果で検証する**。判定は

1. ボードの PLL1 ロック LED
2. `adc_capture.py` が出す **ppm**

の 2 つ。2 が本命である。必要になったら 4 線読み返しを別 proj で扱う。

# proj021 の判定（SAM45-Fine の受け入れ試験）

最終の bit（proj021 手順 2-5、BIT_KIND 2・BIT_REV 3）と、それに載せる PS（`pynq/`、B2b まで）を、リリースの前に実機で通す判定。
1 判定 1 ファイル。書き方は 6 項目（ID・前提・手順・合格・陽性対照・記録）。YATSUGATAKE の `test/acceptance/` に移植の M1 でそのまま移す。

## 共通の前提

- **bit**: proj021（2-5）。`s45core --list` で IF_ID 0x0202_0301（4 コア）・time_core 0x0202_0302・リング 0x0202_0303
- **クロック**: 外部 10 MHz と 1PPS（PPS Clk の入力）。道具は `--clkin 0 --ref 10`
- **宛先**: 環境変数 `B`（ボード）・`SG`（信号発生器）・`PM`（パワーメーター）・`ATT`（プログラムアッテネータ）に入れる。宛先はファイルに書かない
- **道具の置き場所**: ボードの proj021 の道具のディレクトリ（`pynq/*.py`・`proj021.bit`・`proj021.hwh`・`bits.json`）と、制御 PC の `pynq/`
- **2 つの動かし方**:
  - 「ボード直」: ボードで root、**specd を止めてから**（Overlay を自分で載せる道具）
  - 「specd」: ボードで `python3 specd.py --clkin 0 --ref 10 --bits bits.json`（root）、制御 PC から specctl・specrecv など
- **配線**（今の実験室。値は配線に依る）:

| 名前 | 中身 | ADC での強さ |
|---|---|---|
| 配線 N | ノイズソース → PATT **13 dB** → 分配器 A →（−20 dB → PM）・（分配器 2 段 → ADC_A〜D） | ≒ −12.5 dBFS（PATT ≦ 4 dB で振り切れる） |
| 配線 S | SG → PATT 3 dB → 分配器 A → 分配器 2 段 → ADC_A〜D（ノイズソースは外す） | SG −0.9 dBm で ≒ −21.5 dBFS |
| 配線 P | 1PPS を分配して PPS Clk と ADC_A〜D に | — |

## 一覧

| ID | 何を確かめるか | 動かし方 | 配線 | 最終の bit で |
|---|---|---|---|---|
| [ID-1](ID-1.md) | 自己記述 | ボード直 | どれでも | 通過 |
| [F-0](F-0.md) | 1PPS の取り込み | ボード直 | N | 通過 |
| [F-1](F-1.md) | 13 コアの RUN の頭・ダンプの区切り | ボード直 | N | 通過 |
| [T-4](T-4.md) | RUN の値（DUMP_CFG・RUN_SHIFT） | ボード直 | N | 通過 |
| [F-2](F-2.md) | ADC → コアの遅れ（timebase.CAL） | ボード直 | P | 通過 |
| [W-0](W-0.md) | 窓が流れる | ボード直 | N | 通過 |
| [W-G](W-G.md) | 窓のスペクトル = numpy FFT | ボード直 | N | 通過（W 256） |
| [W-1](W-1.md) | SG の CW の ch と周波数 | ボード直 | S | **未** |
| [P-5](P-5.md) | ch の応答 | specd | S | 通過 |
| [P-8](P-8.md) | 線形性・窓の和 / TP | specd | N（＋ PM・ATT） | 通過（L-2 の B0 に注記） |
| [V2-a](V2-a.md) | specd の束ね = PL の 40.96 ms | specd | N | 通過 |
| [V2-b](V2-b.md) | 10.24 ms で 30 分 | specd | N | 通過（陽性対照 未） |
| [V2-c](V2-c.md) | W-G をレコードの道で | ボード直 | N | 通過 |
| [V2-d](V2-d.md) | LOAD で bit を往復 | specd | N | **NG → specd を直して回し直し** |
| [V2-e](V2-e.md) | TP のレコード = AXI4-Lite の TP のリング | ボード直 | N | 通過 |
| [V2-f](V2-f.md) | 5.1 の見張り（DDC 8 本） | ボード直 | N | 通過 |
| [V2-g](V2-g.md) | リングの溢れ・キャッシュ（陽性対照） | ボード直 | N | 通過 |
| [S](S.md) | specd の SNAP（RAW の生サンプル） | specd | N | 通過 |
| [PS-1](PS-1.md) | float32 の丸め・utc_ns の補正 | specd | N | 通過 |
| [PS-2](PS-2.md) | specd の 10 分の運転 | specd | N | 通過 |
| [PS-3](PS-3.md) | TP の跳ねの見張り | specd | N（＋ ATT） | 通過 |

**SAM45-Fine では回さない判定**（FULL = 全帯域のスペクトルが無い）: W-6・W-1b・全帯域の golden・F-5・`spectrometer --tp`。全帯域のある bit（SAM45-Wide など）の判定として扱う。

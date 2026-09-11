# proj001 — 開発環境の再構築と生存確認（PL only の LED 点滅）

日付: 2026-09-11
状態: **成功**

## 目的

数年の中断を挟んだ RFSoC4x2 開発の再開初日。分光計の実装に入る前に、
**ツールチェーン・ライセンス・ケーブル経路・ボード・ピン定義の 5 つを一度に検証する**
最小の設計を通す。

そのために、あえて **Zynq MPSoC IP を一切使わない** 構成を選んだ。
RFSoC4x2 には Si5395 が生成する自走 100 MHz（SYS_CLK_100M, LVDS）が PL に直結して
いるため、PS なしで論理が動く。

## やったこと

- 自走 100 MHz を `IBUFDS` で受け、27bit カウンタの上位 4bit をユーザ LED に出す
  設計を書いた（`src/blink.v` / `src/blink.xdc`）
- 非プロジェクトモードの Tcl でビルドし（`build.tcl`）、JTAG で書き込んだ（`program.tcl`）
- 途中で 3 点つまずき、いずれも解消した。詳細と切り分け手順は
  [`docs/runbook.md`](docs/runbook.md)
  1. `vivado` が PATH に無い（GUI はランチャが絶対パスで起動するため気づかない）
  2. ライセンスの Host ID 不一致 → rehost
  3. JTAG target が 0 個 → microUSB を `USB DEVICE` に挿していた

## 結果

LED0 が約 1.34 秒周期、LED3 がその 8 倍速で点滅。書き込みログに
`End of startup status: HIGH` が出てコンフィグ完了。

```
Opening hw_target localhost:3121/xilinx_tcf/Xilinx/<cable-serial>
Device xczu48dr (JTAG device index = 0) is not programmed (DONE status = 0).
End of startup status: HIGH
```

最後に出る `no supported debug core(s) in it` は ILA を入れていないという通知で、
エラーではない。

## 結論・次にやること

- **PS に依存しない土台が確認できた。** 以降で何かが動かなくても、
  ツールチェーン・ライセンス・ケーブル・ボード・LED のピン定義は容疑者から外せる
- 次の proj: **Zynq MPSoC + AXI GPIO のオーバーレイを作り、PYNQ から LED を叩く。**
  制御系の疎通と `.hwh` の扱いを取り戻す
- その前の判断: Vivado 2024.1 を追加インストールするか（BSP と PYNQ v3.1.1 が
  前提とする版）。対応範囲は手元のライセンスの Version Limit で決まる

### 残っている確認事項

- **part の速度グレードが未確定。** BSP は `-2` を宣言、RefMan A5 は `-1` と読める。
  決着はチップ上面の刻印。LED では影響しないが、分光計のタイミング解析では効く
- PYNQ イメージ（v3.1.1）の SD カードが手元にあるか未確認

## 再現手順

```bash
make        # 合成〜ビットストリーム生成（build/proj001.bit）
make prog   # JTAG 書き込み
make id     # デバイス表示だけ（合成ライセンス不要）
```

`Makefile` 先頭の `XILINX_VIVADO` を自分の環境に合わせる。
環境の固定値は [`../VERSIONS.md`](../VERSIONS.md)。

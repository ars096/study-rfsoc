# rfsoc — RFSoC4x2 電波分光計の開発

野辺山 45m 鏡の SAM45 の代替となる電波分光計を、RFSoC4x2（XCZU48DR）上に実装するための
開発リポジトリ。制御系は PYNQ オーバーレイを前提とする。

## 構成の考え方

試行ごとに `projNNN/` を作り、番号を増やしていく。実験ノートと同じ構造。

- **`projNNN` は自己完結にする。** Makefile・Tcl・RTL・XDC をディレクトリ内に持ち、
  他の proj に依存しない。共通化して DRY にすると、共通側を直した瞬間に過去の proj が
  再現しなくなる。このリポジトリでは **再現性を DRY より優先する**
- 新しい proj は `template/` をコピーして作る — `cp -r template proj002`。
  作成時点では DRY、以後は独立
- **各 `projNNN` に `README.md` を置く。** 目的・やったこと・結果・結論の4点。
  これが無いと proj050 の頃に proj017 が何だったか分からなくなる
- **`INDEX.md` に1行追記する。** 番号が増えても全体を見渡せる唯一の手段

## 使い方

```bash
cp -r template proj002        # 新しい試行を始める
cd proj002
$EDITOR README.md             # まず目的を書く
make                          # 合成〜ビットストリーム生成
make prog                     # JTAG 書き込み
```

`make` は `XILINX_VIVADO` で Vivado の場所を指定する。各 proj の `Makefile` 先頭にある。
**`settings64.sh` を `.bashrc` で source しないこと**（理由は runbook 参照）。

## 開発環境

- 環境の再構築手順とハマりどころ: [`proj001/docs/runbook.md`](proj001/docs/runbook.md)
- 版とハードウェアの固定値: [`VERSIONS.md`](VERSIONS.md)

ライセンスの Host ID・AMD アカウント・rehost の経緯といった環境固有の情報は、
**このリポジトリには書かない**（git の履歴は消せないため）。リポジトリ外の作業記録で管理する。

## 運用

Mac で編集し、Vivado サーバでビルドする。remote を2つ持つ。

```bash
git remote add origin git@github.com:<user>/rfsoc.git                       # 正本
git remote add build  ssh://<user>@<server>/home/<user>/git/rfsoc           # ビルド機

git push origin main
git push build  main          # サーバ側で receive.denyCurrentBranch=updateInstead
```

## ライセンス

[BSD 3-Clause License](LICENSE)。

PYNQ 本体が BSD-3-Clause であり、土台と条件を揃えている。第 3 条（非推奨条項）により、
書面の許可なく著作権者名・貢献者名を派生物の推奨や販促に用いることはできない。

各ソースファイルには `SPDX-License-Identifier: BSD-3-Clause` を記載してある。
著作権者の表記は `LICENSE` の 1 箇所にのみ持つ。

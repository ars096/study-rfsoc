# proj029 — 2G の取得の熱い所を C に（ボードの PS。tint 10.24 ms = n_sum 1 を 1 プロセスで）

日付: 2026-10-23（起こし）
状態: 進行中
土台: タグ **proj025-m0** の `proj025/pynq/`（`git ls-files` で追跡されている 61 ファイルをそのまま写した。G22Backend・FakeG22Backend・`--loop-log-ms`・CAL[0x0025_0100] 入りの timebase.py）。
bit は proj025 のまま（`proj025/build/proj025.bit`、sha256 `de3ee453…cf30bf9`、ボードの `~/proj025/` にある）。**RTL・bit は変えない見込み**なので、PS の ID の期待値・BITFILE は proj025 のまま直さない。
写した直後に、この PC で `pynq/test_fake.sh`（PL なし 23 試験）が **全部通過**（2026-10-23）。引き継ぎは [`../docs/handoff_proj029.md`](../docs/handoff_proj029.md)。

着手の前に [`../LESSONS.md`](../LESSONS.md) を全部読む（知見の全部は [`../docs/lessons_all.md`](../docs/lessons_all.md)）。

## 目的

**2G（2G-1・2G-2）の取得（ボードの PS、`s45acq.py`）の熱い所を C にして、tint 10.24 ms（n_sum 1、BITS.md の 2G の dt）を 1 プロセスで余裕をもって回す。**
西村さんの判断（2026-10-23）: proj025 追補 5 の実測（Python 1 本で 1 BASE 13.06 ms = 127 %）を見て、「C にする（1）」と「プロセスを分ける（2）」のうち **1**。

- 範囲は熱い所だけ: **リングの読み（`plring.Ring.read`）〜 束ね（`Bundler.add`）〜 SPEC の記録（`Acq._spec_record_full`）〜 溜まりへの写し（`Acq._put` → `s45ring.put`）**。制御・時刻・TP・STATUS は Python に残す
- **出す記録は今と bit 単位で同じ**（s45proto v2、`SPEC2_H`・u64 と f32・CRC）。今の Python の道が正解。test_fake と、同じ入力で Python と C の出力を照らす試験で確かめる
- 合格の線（仮）: tint 10.24 ms・src C・D（TP 4 本）で **1 BASE の段の時間の和 ≦ 7 ms（≦ 70 %）**。7.24 ms（= 10.24 − 寝る 3 ms）を越えると 1 周が 2 BASE を抱える形に跳ぶ（proj025 4c）ので、その手前に置く。取りこぼし 0 は 30 分で
- 範囲の外（C にしても残る）: 送り出し。dt 10.24 ms の float32 は 2 窓で ≒ 51 MB/s、ボードの TCP は ≒ 27 MB/s で頭打ち（proj021 C3、INTERFACE 8. の 10）。取得が間に合っても全 ch を 10.24 ms ごとには送れない

## 測った数（proj025 追補 5、ボードの A53、Python 1 本・CPU 3・SCHED_FIFO・mallopt あり）

| 1 BASE（10.24 ms）あたり | src C・D（TP 4 本） | src A・B（TP 2 本） |
|---|---|---|
| リングの読み（invalidate・CRC・写し。レコード 1 個 ≒ 0.6〜0.8 ms） | 3.97 ms | 3.69 ms |
| 振り分け | 1.39 ms | 0.71 ms |
| 窓の記録（束ね ＋ SPEC の記録 2 本。1 本 3.7 ms） | 7.48 ms | 7.36 ms |
| TP | 0.20 ms | 0.15 ms |
| 計 | 13.06 ms（127 %） | 11.93 ms（116 %） |

今の道で 1 窓の 1 BASE（65,536 ch）が何回なめられているか（コードから。n_sum 1・fmt f32）:
1. `Ring.read`: invalidate → `zlib.crc32`（512 KiB）→ `a64[…].copy()`（512 KiB の写し）
2. `Bundler.add`: `np.array(spec, dtype=np.uint64)`（n_sum 1 でも 512 KiB の写し）
3. `_spec_record_full`: `[::-1]` ＋ `ascontiguousarray`（512 KiB の写し）→ `f32_round` の `u.max()`（512 KiB の読み）→ `astype(float64)`（512 KiB の書き）→ `astype(float32)`（256 KiB の書き）→ `P.crc32`（256 KiB）
4. `_put` → `s45ring.put`: memoryview から溜まり（共有メモリ）へ 256 KiB の写し

## 1. 最初の一手: SPEC の記録 1 本を C の関数 1 つで — 予言（測る前に書く、2026-10-23）

**やること**
- C の関数 1 つ（仮に `pynq/s45fast.c` → `libs45fast.so`、ctypes で呼ぶ。標準ライブラリだけで済む）:
  入力 u64 × 65,536（FFT の ch の順）・88 バイトの `SPEC2_H` → 出力 f32 × 65,536（**逆順**、u64 → double → float の丸め = `P.f32_round` と同じ）と CRC-32（頭 ＋ 中身、`zlib.crc32` と同じ IEEE の多項式、ARMv8 の `__crc32d`）。
  **1 回のなめ**で、2^53 以上の値があれば戻り値で知らせる（Python 側で今と同じ ValueError にする）
- 照合（ボードとこの PC の両方で）: 同じ入力で Python の `_spec_record_full` の道（`[::-1]`・`f32_round`・`SPEC2_H.pack`・`P.crc32`）と **出力の bytes と CRC が一致**。
  入力は乱数（< 2^53）に端の値を混ぜる: 0・1・2^24 ＋ 1（float32 の丸めの偶数への寄せ）・2^24 ＋ 3・2^53 − 1・連続する同じ値。u64 の版（fmt u64・both）の CRC も同じ関数の別の口で照らす
- 陽性対照（落ちるべきもの）: (p1) C 側の入力の 1 ch だけ値を変える → bytes が不一致・不一致の位置が 1 か所、(p2) 丸めを 0 への切り捨てにした C の変種 → 不一致（`f32_trunc` と同じ形）、(p3) 逆順をやめた変種 → 不一致、(p4) 2^53 の値 → 両方が拒否
- 測る: ボードで（CPU 3 に固定）、1 本あたりの時間を Python の道と C で 1,000 回ずつ。溜まりへの写し（`s45ring.put`）は別に測る
- 先に確かめること（西村さんがボードで）: `gcc --version`・`gcc -march=armv8-a+crc` が通るか・`python3 -c "import ctypes, numpy; print(numpy.__version__)"`

**予言**
- 照合: 一致（乱数 ＋ 端の値の全部）。陽性対照 p1〜p4 は全部落ちる。
  理由: u64 < 2^53 は double で厳密なので、double → float の 1 回の丸め（最近接・偶数）は Python と C で同じ。**自信が低い所**: gcc が `(float)(double)u` を `(float)u`（ucvtf の 1 回の丸め）に畳む最適化はしない見込みだが、しても < 2^53 では同じ値。CRC の初期値・最後の反転を取り違えると全部が不一致になる（そのときは CRC の口だけを `zlib.crc32` と照らして切り分ける）
- 時間（ボードの A53、65,536 ch・fmt f32）: **Python の道（記録 1 本、put を除く） ≒ 3.3 ms（2.8〜3.8）**、**C ≒ 0.4 ms（0.2〜0.7）**、比 ≒ 8 倍（5〜15）。
  理由: 記憶の量は 512 KiB の読み ＋ 256 KiB の書き = 768 KiB。A53 の 1 コアの流しの帯域を 2〜4 GB/s と見て 0.2〜0.4 ms。変換は 1 ch あたり数サイクル（≒ 0.2 ms、帯域と重なる）、`__crc32d` は 32,768 回で ≒ 0.03 ms。
  Python の道は 2〜3 MiB をなめ、numpy の一時配列の確保（mallopt で mmap は避けている）と zlib のソフトウェアの CRC（≒ 1 GB/s として 0.25 ms）が乗る
- 効き（1 BASE の和、src C・D）: 記録 2 本が 2 × 3.7 → 2 × ≒ 0.8 ms（C ≒ 0.4 ＋ put ≒ 0.3 ＋ 呼び出し）になり、**13.06 → ≒ 7.3 ms（≒ 70 %、6.5〜8.5）**。合格の線（≦ 7 ms）には届かないか際どい。
  **残りの大半はリングの読み ＋ 振り分け（5.4 ms = 53 %）**なので、手順 2（リングの読みの CRC・写しと束ねを C の 1 回のなめに寄せる）が要る、と予言する
- 外れたら: C が 1 ms を越えるなら、帯域でなく CMA・キャッシュの属性か ctypes の呼び出しの重さを疑う（呼び出しだけを空の関数で測る）。Python の道が 2.5 ms を切るなら、3.7 ms の残りは put か束ねにある（追補 5 の「1 本 3.7 ms」は窓の記録の時間を本数で割った値で、束ね・put を含む）

## 2. 次の手（1 の結果で決める）

- 2: リングの読み（invalidate の後の CRC と写し）と束ねの足し算を同じ C の関数に寄せる（1 回のなめ。CRC は `__crc32d`、PL の尾の CRC と同じ多項式かを先に照らす）。溜まりへ直接書く（`s45ring.put` の写しを省く）かもここで決める
- 3: 段の時間を specd の `--loop-log-ms 0.1` で今と同じ形で出す（proj025 追補 5 と並べる）。PL なしの 1 周の台本は `bench_g21.py` を 2G-2 に直す
- 4: tint 10.24 ms・src C・D で 30 分（取りこぼし 0・受けの照合。送り出しは上限を越えるので、受けの形は決めてから）

## やったこと

- 2026-10-23: 起こした（template から README、proj025-m0 の `pynq/` を写した。Vivado の Makefile・build.tcl・program.tcl・src は PS だけの試行なので持たない。proj018・019 と同じ形）。写した `pynq/` で test_fake 全部通過

## 結果

-

## 結論・次にやること

- [x] 0. 起こす・写す・test_fake（2026-10-23）
- [ ] 1. SPEC の記録 1 本を C で（照合 ＋ 陽性対照 ＋ ボードの時間）
- [ ] 2. リングの読み・束ねを寄せる
- [ ] 3. 段の時間（`--loop-log-ms`）
- [ ] 4. tint 10.24 ms で 30 分
- 知見: 次の proj でも踏みそうなものを `../docs/lessons_all.md` に足した（要点なら `../LESSONS.md` にも）

## 再現手順

```bash
cd pynq && bash test_fake.sh all      # PL なし（どこの Linux でも。numpy だけ）
```

環境は [`../VERSIONS.md`](../VERSIONS.md)、詰まったときは
[`../proj001/docs/runbook.md`](../proj001/docs/runbook.md)。

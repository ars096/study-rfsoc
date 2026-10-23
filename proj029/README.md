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

**1a の結果（2026-10-23、ボード、`test_s45fast.py --bench 1000 --cpu 3` を `chrt -f 50` で、specd は止めて。`runs/fast_1a.txt`）: 照合は予言どおり、時間は外れ（Python が予言より速く、比は 3.5 倍）**
- `build_fast.sh`: gcc 11.2.0・`-march=armv8-a+crc` が通り、**CRC は命令**
- 照合: この PC と同じ 22 項目が全部 OK（bytes と CRC まで一致・陽性対照 p1〜p4 は全部落ちた・p1 の位置は n − 1 − ch）

| 1 本あたり（65,536 ch、中央値 / p99 ms） | 実測 | 予言 |
|---|---|---|
| Python の記録（`_spec_record_full`、put を除く） | **1.94** / 2.11 | 3.3（2.8〜3.8）← 外れ（速い） |
| 　うち逆順の写し・`f32_round`・`P.crc32`（zlib） | 0.16・0.76・0.75 | （zlib ≒ 0.25 ← 外れ: 350 MB/s） |
| **C（`s45_spec_f32`、out を使い回す）** | **0.557** / 0.592 | 0.4（0.2〜0.7）← 範囲の中 |
| 　C の CRC だけ（256 KiB、命令） | 0.155 | ≒ 0.03 ← 外れ（1.7 GB/s） |
| ctypes の呼び出し（空の関数） | 0.003 | — |
| 溜まりへの写し（`s45ring.put`、256 KiB） | 0.116 / 0.660（平均 0.245） | ≒ 0.3 |
| 比（Python / C） | **3.5 倍** | 8 倍（5〜15）← 外れ |

- 読み:
  - C は 1 ch あたり ≒ 8.5 ns（A53 1.33 GHz で ≒ 11 サイクル）。CRC だけなら 0.155 ms なので、残りの ≒ 0.4 ms は 1 個ずつの変換（ucvtf・fcvt）と逆順の読み。順に実行するコアで CRC の鎖と変換が重ならない形。
    詰める余地は、NEON で 2 個ずつ変換（`vcvtq_f64_u64` → `vcvt_f32_f64`）してから CRC を別になめること（見積もりで 0.3 ms 前後）。今は詰めない（下の 1b で効きの大きさを先に見る）
  - **Python の記録 1.94 ms は追補 5 の「1 本 3.7 ms」の半分**。この台は同じ 512 KiB の配列を 1,000 回なめるので L2（1 MiB）に載ったまま。
    実機の周では、記録 1 本の中に束ねの写し（≒ 0.16）・put（≒ 0.25）・`poll_win` も入る。それでも ≒ 1.3 ms が説明できず、キャッシュに載っていないことと、PL の DMA・送り出しのプロセスとの記憶の取り合いを疑う。
    **この台の比をそのまま 1 BASE に当てると 13.06 − 2 × (1.94 − 0.56) ≒ 10.3 ms（100 %）で、手順 1 だけでは回らない**（予言の 7.3 ms から外れる見込み）
  - 最大 ≒ 50 ms が 3 行に 1 回ずつ（py_record 53.8・py_f32_round 48.6・c_spec_f32_out 52.3 ms）。台は SCHED_FIFO で CPU 3 を休みなく使う。
    **RT の throttling（既定では 1 s のうち 0.95 s まで。残りの 50 ms は FIFO を止める）を疑う**（未確認。`/proc/sys/kernel/sched_rt_runtime_us` を読む）。
    specd は 1 周ごとに 3 ms 寝るので普段は当たらないが、取得が 95 % を越えて詰まると同じ 50 ms の止まりが入り得る

**1b. 実機の周で C の記録を使う（specd `--fast`） — 予言（2026-10-23、測る前に書く）**

足したもの: `s45acq.Acq._spec_record_full` に C の道（`self.fast`、specd の `--fast` で有効。既定は今の Python の道）。頭（`SPEC2_H.pack`）は Python のまま、中身と CRC は `s45fast`。
`tools/loopsum.py`: specd のログから運転ごとに 1 BASE あたりの段の時間を出す（proj025 追補 5 の数え方。`proj025/runs/g22_5.specd.log` で 3.97・1.39・7.48・0.20 ms を再現した）。
PL なしの確かめ（この PC）: `FAST=--fast bash test_fake.sh all` が**全部通過**（23 試験。25 回の specd の起動がどれも「SPEC の記録（FULL）は C」）。
specd を通した陽性対照（`--g22 --fast`、fmt both・n 30）: そのままで f32 の組 60・不一致 0、`--posctl-f32-trunc` を足すと**不一致 60 / 60**

- 手順（追補 5 の 5a と同じ形: tint 0.01024・src C・D・shift 7・fmt f32・`START n=200`・`--loop-log-ms 0.1`）。**同じ配線で `--fast` → なし → `--fast` の順に specd を起こし直して 3 回**（旧と新を交互に）
- 予言:
  - 記録: 3 回とも受けの欠け 0・CRC 0・照合 通過（n に達した後の分の落ちは追補 5 と同じに出てよい）
  - **なし（Python）の回: 1 BASE ≒ 13.1 ms（12.6〜13.5）**、窓の記録 ≒ 7.5 ms（追補 5 の再現）
  - **`--fast` の回: 窓の記録 7.48 → ≒ 4.5 ms（3.5〜5.0）・1 BASE ≒ 10.0 ms（8.8〜10.8、86〜105 %）**。リングの読み（≒ 4.0）・振り分け（≒ 1.4）・TP（≒ 0.2）は ±0.3 ms で変わらない。
    合格の線（7 ms）には届かない。**次に効くのはリングの読み ＋ 振り分け（5.4 ms）**で、手順 2 に進む
  - 自信が低い所: 実機の周の「説明できない 1.3 ms / 本」が、なめる回数に比例するなら C で大半が消え（窓の記録 ≒ 3.5 ms・1 BASE ≒ 9 ms）、記録の量に依るなら残る（≒ 5 ms・≒ 10.8 ms）。どちらに寄るかでこの分の正体を読む
  - 運転の形: 1 BASE が 10.24 ms を越えれば、追補 5 と同じく 1 周が伸び続けて pl_drop が出る。下回れば 1 周が多くの BASE を抱えて落ち着く（pl_drop 0）。どちらかは予言しない（線の上）
- ついでに（ボード）: `cat /proc/sys/kernel/sched_rt_runtime_us /proc/sys/kernel/sched_rt_period_us` → 予言 950000・1000000（throttling の疑いの確かめ）

## 2. 次の手（1 の結果で決める）

- 2: リングの読み（invalidate の後の CRC と写し）と束ねの足し算を同じ C の関数に寄せる（1 回のなめ。CRC は `__crc32d`、PL の尾の CRC と同じ多項式かを先に照らす）。溜まりへ直接書く（`s45ring.put` の写しを省く）かもここで決める
- 3: 段の時間を specd の `--loop-log-ms 0.1` で今と同じ形で出す（proj025 追補 5 と並べる）。PL なしの 1 周の台本は `bench_g21.py` を 2G-2 に直す
- 4: tint 10.24 ms・src C・D で 30 分（取りこぼし 0・受けの照合。送り出しは上限を越えるので、受けの形は決めてから）

## やったこと

- 2026-10-23: 起こした（template から README、proj025-m0 の `pynq/` を写した。Vivado の Makefile・build.tcl・program.tcl・src は PS だけの試行なので持たない。proj018・019 と同じ形）。写した `pynq/` で test_fake 全部通過
- 2026-10-23: ボードの道具の確かめ（西村さん）: gcc 11.2.0（Ubuntu 11.2.0-19ubuntu1）・numpy 1.21.5・ctypes あり。`-march=armv8-a+crc` は `build_fast.sh` の中で確かめる
- 2026-10-23: 手順 1 の道具を書いた。`pynq/s45fast.c`（`s45_spec_f32`・`s45_spec_u64`・`s45_crc32`。aarch64 で `__ARM_FEATURE_CRC32` があれば CRC32 命令、無ければ表）・
  `pynq/build_fast.sh`（→ `libs45fast.so`、.gitignore）・`pynq/s45fast.py`（ctypes の包み）・`pynq/test_s45fast.py`（照合 ＋ 陽性対照 ＋ `--bench`）。
  照合の正解は**本物の `Acq._spec_record_full`**（最小の Acq を作り、`_put` で頭・中身・CRC を捕まえる）。頭（`SPEC2_H.pack`）は Python のまま
- 2026-10-23: この PC（x86_64、CRC は表）で `test_s45fast.py`: **照合 22 項目が全部 OK**。n 65536・131072 とも f32・u64・fmt f32・out の使い回しが bytes と CRC まで一致。
  陽性対照: p1（1 ch を変える）は不一致 1 か所で位置 = n − 1 − ch、p2（切り捨て）は 32,754 / 65,536 か所が不一致・**p2 の C は Python の `f32_trunc` と bytes まで同じ**、p3（逆順なし）は全部不一致、p4（2^53）は両方が同じ ValueError。
  CRC の口だけ（位置 0〜8・長さ 0〜4096・初期値の続き）も zlib と一致。
  時間（参考、この PC）: Python の記録 0.26 ms・C 0.50 ms（表の CRC が 1 バイトずつで遅い。C の CRC 256 KiB だけで 0.49 ms）。**ボードは CRC32 命令なので、この比は持ち込まない**

## 結果

-

## 結論・次にやること

- [x] 0. 起こす・写す・test_fake（2026-10-23）
- [x] 1a. SPEC の記録 1 本を C で（2026-10-23。照合 ＋ 陽性対照は全部通過、ボードで Python 1.94 → C 0.557 ms = 3.5 倍、予言 8 倍は外れ）
- [ ] 1b. 実機の周で `--fast`（1 BASE の段の時間）
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

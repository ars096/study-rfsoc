#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-7 — 載っている .bit が別の作業に載せ替えられていないかを見る（ボードの上で）

  python3 pl_guard.py save <file>     # 今の載り（PYNQ の global_pl_state の bitfile_name・timestamp）を <file> に書く
  python3 pl_guard.py check <file>    # <file> と違えば ERROR を出して exit 1

Y-7 の 1 回目は、走っている途中に別の作業が .bit を載せ、こちらの道具は SG を回し続けた。各手順の前にこれを見る。
"""
import json
import os
import sys


def now():
    import pynq
    p = os.path.join(os.path.dirname(pynq.__file__), "pl_server", "global_pl_state_.json")
    d = json.load(open(p))
    return dict(bitfile_name=d.get("bitfile_name"), timestamp=d.get("timestamp"))


def check(path):
    """違えば (False, 今の載り)"""
    want, got = json.load(open(path)), now()
    return want == got, got


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("save", "check"):
        raise SystemExit(__doc__)
    if sys.argv[1] == "save":
        json.dump(now(), open(sys.argv[2], "w"))
        print(f"pl_guard: {now()}")
        return
    ok, got = check(sys.argv[2])
    if not ok:
        print(f"ERROR: 載っている .bit が変わった（{got}）。別の作業がボードを使っている")
        sys.exit(1)


if __name__ == "__main__":
    main()

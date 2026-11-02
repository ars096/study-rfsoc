#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj029 1: s45fast.c → libs45fast.so（s45fast.py が ctypes で読む）。ボード（aarch64）では CRC32 命令を使う（-march=armv8-a+crc）
#   bash build_fast.sh        # 最後の行の「CRC: 命令」/「CRC: 表」で、どちらでビルドされたかを読む
set -e
cd "$(dirname "$0")"
case "$(uname -m)" in
  aarch64) ARCH="-march=armv8-a+crc" ;;
  *)       ARCH="" ;;
esac
gcc -O2 $ARCH -Wall -Wextra -shared -fPIC -o libs45fast.so s45fast.c -lm
gcc --version | head -n 1
python3 -c "import ctypes; L = ctypes.CDLL('./libs45fast.so'); print('libs45fast.so: CRC:', '命令' if L.s45_hw_crc() else '表')"

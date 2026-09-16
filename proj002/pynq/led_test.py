# SPDX-License-Identifier: BSD-3-Clause
"""proj002 — PYNQ から AXI GPIO 経由で LED を叩く。

ボード（PYNQ v3.1.1）上で実行する。同じディレクトリに proj002.bit と
proj002.hwh の両方を置くこと。**PYNQ は .bit と同名の .hwh を探す。**

    python3 led_test.py
"""

import time

from pynq import Overlay

BIT = "proj002.bit"


def get_leds(ol):
    """AxiGPIO ドライバが束ねられていればそれを使い、駄目なら MMIO に落とす。"""
    try:
        from pynq.lib import AxiGPIO

        ch = AxiGPIO(ol.ip_dict["gpio_led"]).channel1
        ch.setdirection("out")
        ch.setlength(4)
        return lambda v: ch.write(v, 0xF)
    except Exception as e:  # noqa: BLE001
        print(f"AxiGPIO が使えないので MMIO に切り替える: {e}")
        mmio = ol.ip_dict["gpio_led"]["driver"](ol.ip_dict["gpio_led"]).mmio
        mmio.write(0x04, 0x0)  # GPIO_TRI: 0 = 出力
        return lambda v: mmio.write(0x00, v)


def main():
    ol = Overlay(BIT)
    print("ip_dict:", list(ol.ip_dict))

    write = get_leds(ol)

    # 0b0001 → 0b0010 → 0b0100 → 0b1000 を往復。目視で並びと順序を確認する
    pattern = [1, 2, 4, 8, 4, 2]
    for _ in range(10):
        for v in pattern:
            write(v)
            time.sleep(0.15)

    write(0xF)
    print("全点灯にして終了。消すには write(0x0)")


if __name__ == "__main__":
    main()

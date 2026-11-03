/* SPDX-License-Identifier: BSD-3-Clause
 * proj032 P-13: SpW のリングの SPEC のレコード（頭 64 バイト ＋ f32 × n）を写さずに、1 回のなめで
 *   PL の CRC（zlib.crc32(頭 ＋ 中身)、plring.Ring.read と同じ範囲）を取り、中身を double の器 acc に足す。
 *   YATSUGATAKE sw/pynq/s45fast.c の s45_ring_acc（Fine の u64）の f32 版。spw_b5.py --fast が ctypes で呼ぶ
 * ビルド（ボード）: gcc -O3 -march=armv8-a+crc -shared -fPIC -o libspwfast.so spwfast.c（-O2 はベクトル化されず 1 本 86 µs、-O3 で 45 µs。ボードの A53 1.2 GHz）
 * 戻り値: 中身の負か有限でない値の数（0 = よし）
 */
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#if defined(__aarch64__) && defined(__ARM_FEATURE_CRC32)
#include <arm_acle.h>
#define HW_CRC 1
#else
#define HW_CRC 0
#endif

#if !HW_CRC
static uint32_t crc_tab[256];
static int crc_tab_ok;
static void crc_init(void)
{
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++)
            c = c & 1 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
        crc_tab[i] = c;
    }
    crc_tab_ok = 1;
}
#endif

static inline uint32_t crc_u64(uint32_t c, uint64_t v)    /* v の 8 バイトをリトルエンディアンの順に */
{
#if HW_CRC
    return __crc32d(c, v);
#else
    for (int k = 0; k < 8; k++)
        c = crc_tab[(c ^ (uint8_t)(v >> (8 * k))) & 0xFF] ^ (c >> 8);
    return c;
#endif
}

int spw_hw_crc(void)
{
    return HW_CRC;
}

/* rec: 頭の位置（8 バイト揃え）、n: f32 の数（偶数）。acc: double × n（first なら acc = 中身）。*crc_pl: PL の CRC（照合は呼び手） */
int spw_rec_acc(const uint8_t *rec, size_t n, double *acc, int first, uint32_t *crc_pl)
{
#if !HW_CRC
    if (!crc_tab_ok)
        crc_init();
#endif
    uint32_t c = ~0u;
    const uint64_t *h = (const uint64_t *)rec;
    for (int i = 0; i < 8; i++)
        c = crc_u64(c, h[i]);
    const uint64_t *in = (const uint64_t *)(rec + 64);
    /* なめ 1: CRC（命令の鎖。ほかと混ぜると遅れが重なるので分ける）。なめ 2: 足し込みと悪い値（符号 bit か指数が全部 1）の数え（ベクトル化される形） */
    for (size_t i = 0; i < n / 2; i++)
        c = crc_u64(c, in[i]);
    const uint32_t *u = (const uint32_t *)(rec + 64);
    const float *f = (const float *)(rec + 64);
    int bad = 0;
    if (first)
        for (size_t i = 0; i < n; i++)
            acc[i] = f[i];
    else
        for (size_t i = 0; i < n; i++)
            acc[i] += f[i];
    for (size_t i = 0; i < n; i++)
        bad += (u[i] >> 31) | ((u[i] & 0x7F800000u) == 0x7F800000u);
    *crc_pl = ~c;
    return bad;
}

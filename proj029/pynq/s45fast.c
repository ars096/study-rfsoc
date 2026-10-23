/* SPDX-License-Identifier: BSD-3-Clause
 * proj029 1: 2G の SPEC の記録（s45acq.Acq._spec_record_full）の中身と CRC を 1 回のなめで作る。
 * 正解は Python の道: raw = spec[::-1]（u64）、f32 = P.f32_round(raw)（u64 → double → float の最近接）、crc = P.crc32(hd, data)（zlib.crc32、IEEE）。
 * 呼ぶのは s45fast.py（ctypes）。aarch64 では ARMv8 の CRC32 命令（__crc32d。CRC32C 系ではない）、それ以外（この PC の試験）は表で。
 * 戻り値: 0 = よし、1 = 2^53 以上の値がある（Python 側で f32_round と同じ ValueError にする。そのときの out・crc は使わない）
 */
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#if defined(__aarch64__) && defined(__ARM_FEATURE_CRC32)
#include <arm_acle.h>
#define HW_CRC 1
#else
#define HW_CRC 0
#endif

/* 陽性対照（s45fast.py の posctl）。正の道はどれも 0 */
#define PC_TRUNC 1   /* 0 への切り捨て（s45acq の f32_trunc と同じ形） */
#define PC_NOREV 2   /* 逆順にしない */

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

static inline uint32_t crc_u8(uint32_t c, uint8_t b)
{
#if HW_CRC
    return __crc32b(c, b);
#else
    return crc_tab[(c ^ b) & 0xFF] ^ (c >> 8);
#endif
}

static inline uint32_t crc_u64(uint32_t c, uint64_t v)    /* v の 8 バイトをリトルエンディアンの順に */
{
#if HW_CRC
    return __crc32d(c, v);
#else
    for (int k = 0; k < 8; k++)
        c = crc_u8(c, (uint8_t)(v >> (8 * k)));
    return c;
#endif
}

/* 反転済み（zlib の内側の形）の c に buf を足す */
static uint32_t crc_buf(uint32_t c, const uint8_t *p, size_t n)
{
    while (n && ((uintptr_t)p & 7)) {
        c = crc_u8(c, *p++);
        n--;
    }
    for (; n >= 8; n -= 8, p += 8) {
        uint64_t v;
        memcpy(&v, p, 8);
        c = crc_u64(c, v);
    }
    while (n--)
        c = crc_u8(c, *p++);
    return c;
}

/* zlib.crc32(buf, init) と同じ */
uint32_t s45_crc32(uint32_t init, const uint8_t *buf, size_t n)
{
#if !HW_CRC
    if (!crc_tab_ok)
        crc_init();
#endif
    return ~crc_buf(~init, buf, n);
}

int s45_hw_crc(void)
{
    return HW_CRC;
}

void s45_nop(void)
{
}

static inline float f32_of(uint64_t u, int trunc)
{
    double d = (double)u;          /* u < 2^53 なら厳密 */
    float f = (float)d;            /* 最近接・偶数（丸めはここ 1 回） */
    if (trunc && (double)f > d)
        f = nextafterf(f, 0.0f);
    return f;
}

/* in: FFT の ch の順の u64 × n。out: f32 × n（IF の昇順 = in の逆順）。*crc = zlib.crc32(hd ＋ out) */
int s45_spec_f32(const uint64_t *in, size_t n, const uint8_t *hd, size_t hlen, float *out, uint32_t *crc, int posctl)
{
#if !HW_CRC
    if (!crc_tab_ok)
        crc_init();
#endif
    int trunc = posctl & PC_TRUNC, norev = posctl & PC_NOREV;
    uint32_t c = crc_buf(~0u, hd, hlen);
    uint64_t hi = 0;
    size_t i = 0;
    if (!trunc && !norev && !(hlen & 7)) {
        /* 正の道: 2 個ずつ（8 バイト）で CRC。hlen が 8 の倍数なので CRC の並びは out の先頭から 8 バイトずつ */
        const uint64_t *src = in + n;
        for (; i + 2 <= n; i += 2) {
            uint64_t a = src[-1 - (ptrdiff_t)i], b = src[-2 - (ptrdiff_t)i];
            hi |= a | b;
            float fa = (float)(double)a, fb = (float)(double)b;
            uint32_t wa, wb;
            memcpy(&wa, &fa, 4);
            memcpy(&wb, &fb, 4);
            out[i] = fa;
            out[i + 1] = fb;
            c = crc_u64(c, (uint64_t)wa | (uint64_t)wb << 32);
        }
    }
    for (; i < n; i++) {
        uint64_t a = norev ? in[i] : in[n - 1 - i];
        hi |= a;
        float f = f32_of(a, trunc);
        out[i] = f;
        uint32_t w;
        memcpy(&w, &f, 4);
        for (int k = 0; k < 4; k++)
            c = crc_u8(c, (uint8_t)(w >> (8 * k)));
    }
    *crc = ~c;
    return (hi >> 53) ? 1 : 0;
}

/* fmt u64（both の u64 の側）: out = in の逆順、*crc = zlib.crc32(hd ＋ out)。2^53 の検査はしない（Python の u64 の道もしない） */
int s45_spec_u64(const uint64_t *in, size_t n, const uint8_t *hd, size_t hlen, uint64_t *out, uint32_t *crc, int posctl)
{
#if !HW_CRC
    if (!crc_tab_ok)
        crc_init();
#endif
    int norev = posctl & PC_NOREV;
    uint32_t c = crc_buf(~0u, hd, hlen);
    for (size_t i = 0; i < n; i++) {
        uint64_t a = norev ? in[i] : in[n - 1 - i];
        out[i] = a;
        if (hlen & 7) {
            for (int k = 0; k < 8; k++)
                c = crc_u8(c, (uint8_t)(a >> (8 * k)));
        } else {
            c = crc_u64(c, a);
        }
    }
    *crc = ~c;
    return 0;
}

/* proj029 2: PL のリングの上の SPEC のレコード（頭 64 バイト ＋ 中身 pb バイト = u64 × n、FFT の ch の順）から、写さずに記録を作る。
 * なめ 1: 前から 1 回。PL の CRC（zlib.crc32(頭 ＋ 中身)、plring.Ring.read と同じ範囲）を取りながら、out の逆順の位置に書く（fmt 1 = f32、0 = u64）。
 * なめ 2: out（書いたばかり）に頭 hd を付けた CRC（= P.crc32(hd, data)）。
 * 戻り値: 0 = よし、1 = 2^53 以上の値がある（f32 のときだけ見る）。*crc_pl と尾の CRC の照合は呼び手が行う */
int s45_ring_spec(const uint8_t *rec, size_t n, const uint8_t *hd, size_t hlen, void *out, int fmt, uint32_t *crc, uint32_t *crc_pl, int posctl)
{
#if !HW_CRC
    if (!crc_tab_ok)
        crc_init();
#endif
    int trunc = posctl & PC_TRUNC;
    uint32_t cp = crc_buf(~0u, rec, 64);
    const uint64_t *in = (const uint64_t *)(rec + 64);
    uint64_t hi = 0;
    if (fmt == 1) {
        float *o = (float *)out;
        if (!trunc) {
            for (size_t i = 0; i < n; i++) {
                uint64_t a = in[i];
                cp = crc_u64(cp, a);
                hi |= a;
                o[n - 1 - i] = (float)(double)a;
            }
        } else {
            for (size_t i = 0; i < n; i++) {
                uint64_t a = in[i];
                cp = crc_u64(cp, a);
                hi |= a;
                o[n - 1 - i] = f32_of(a, 1);
            }
        }
        *crc = ~crc_buf(crc_buf(~0u, hd, hlen), (const uint8_t *)out, n * 4);
    } else {
        uint64_t *o = (uint64_t *)out;
        for (size_t i = 0; i < n; i++) {
            uint64_t a = in[i];
            cp = crc_u64(cp, a);
            o[n - 1 - i] = a;
        }
        *crc = ~crc_buf(crc_buf(~0u, hd, hlen), (const uint8_t *)out, n * 8);
    }
    *crc_pl = ~cp;
    return (fmt == 1 && (hi >> 53)) ? 1 : 0;
}

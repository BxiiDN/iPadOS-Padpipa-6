/* SPDX-License-Identifier: MIT
 * Host test for Ktz8866Board.h. cc -std=c11 -Wall -Wextra -Werror Ktz8866Tests.c && ./a.out */
#include "Ktz8866Board.h"
#include <stdio.h>
#include <stdlib.h>

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); exit(1); } } while (0)

int main(void) {
    uint8_t m, l;
    /* The vendor table's power-on default, LSB 0x01 / MSB 0x7E, is level 1009 ("limit I2C code 1009"). */
    CHECK(ktz_decode(0x7e, 0x01) == 1009);
    ktz_encode(1009, &m, &l); CHECK(m == 0x7e && l == 0x01);
    ktz_encode(2047, &m, &l); CHECK(m == 0xff && l == 0x07);
    ktz_encode(5000, &m, &l); CHECK(ktz_decode(m, l) == 2047);   /* clamped, never HBM */
    for (uint32_t v = 0; v <= 2047; v++) { ktz_encode(v, &m, &l); CHECK(ktz_decode(m, l) == v); }

    KtzWrite w[3]; int wait, n;
    n = ktz_plan(0, 500, w, &wait);   /* turning on: enable first */
    CHECK(n == 3 && w[0].reg == KTZ_REG_BL_ENABLE && w[0].value == KTZ_BL_ENABLE_ON && w[1].reg == KTZ_REG_BRT_LSB && wait == 0);
    n = ktz_plan(500, 0, w, &wait);   /* turning off: disable, then the 10 ms wait */
    CHECK(n == 3 && w[0].value == KTZ_BL_ENABLE_OFF && wait == KTZ_OFF_WAIT_US);
    n = ktz_plan(500, 700, w, &wait); /* level change only */
    CHECK(n == 2 && w[0].reg == KTZ_REG_BRT_LSB && w[1].reg == KTZ_REG_BRT_MSB);
    for (int i = 0; i < 256; i++) {   /* every planned write is to an allowed register */
        n = ktz_plan((uint32_t)i * 8, (uint32_t)(255 - i) * 8, w, &wait);
        for (int k = 0; k < n; k++) CHECK(ktz_write_allowed(w[k].reg));
    }
    CHECK(!ktz_write_allowed(KTZ_REG_FULL_CURRENT) && !ktz_write_allowed(KTZ_REG_BC1) && !ktz_write_allowed(KTZ_REG_BIAS_CONF1));
    CHECK(ktz_check_config(KTZ_CURRENT_CSOT, 0x9f) == 0 && ktz_check_config(KTZ_CURRENT_BOE, 0x9f) == 0);
    CHECK(ktz_check_config(0xff, 0x9f) < 0 && ktz_check_config(KTZ_CURRENT_CSOT, 0x00) < 0);
    puts("PASS: pipa KTZ8866 backlight plan (encoding, on/off order, write allow-list, firmware config check)");
    return 0;
}

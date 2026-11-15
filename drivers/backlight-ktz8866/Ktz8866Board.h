/* SPDX-License-Identifier: MIT
 * KTZ8866 backlight of the Xiaomi Pad 6 (pipa): board facts and the register plan, header-only so the same code runs in
 * the host test (Ktz8866Tests.c) and in a future XNU driver on the QUP I2C master.
 *
 * Sources (values only; no code copied):
 *   MiCode Xiaomi_Kernel_OpenSource pipa-t-oss 77dc8e22: drivers/video/backlight/ktz8866.c, include/linux/platform_data/ktz8866.h
 *   uefi-pipa Resources/DTBs/pipa.dtb: /soc/i2c@a8c000/ktz8866@11 (hwen GPIO 139, enp 130, enn 131, panelid GPIO 30,
 *   "ktz8866,backlight-conf-disable": the bootloader has already configured the chip, so Linux skips its register table)
 *
 * SAFETY: the full-scale LED current (0x15) and the OVP/mapping (0x02) depend on the panel (CSOT 0xb1 = 22.8 mA,
 * BOE 0xc1 = 24.4 mA). A wrong value overdrives the LEDs. This plan never writes them: it reads them back and refuses to
 * run if they are not one of the two values the vendor driver programs. Only brightness (0x04/0x05) and enable (0x08) are
 * written.
 */
#ifndef PIPA_KTZ8866_BOARD_H
#define PIPA_KTZ8866_BOARD_H

#include <stdint.h>

enum {
    KTZ_I2C_ADDR = 0x11,          /* 7-bit, on the I2C controller at 0x00a8c000 */
    KTZ_I2C_BASE = 0x00a8c000,
    KTZ_GPIO_HWEN = 139, KTZ_GPIO_ENP = 130, KTZ_GPIO_ENN = 131, KTZ_GPIO_PANEL_ID = 30,

    KTZ_REG_ID = 0x01, KTZ_REG_BC1 = 0x02, KTZ_REG_BC2 = 0x03, KTZ_REG_BRT_LSB = 0x04, KTZ_REG_BRT_MSB = 0x05,
    KTZ_REG_BL_ENABLE = 0x08, KTZ_REG_BIAS_CONF1 = 0x09, KTZ_REG_FLAGS = 0x0f, KTZ_REG_FULL_CURRENT = 0x15,

    KTZ_BL_ENABLE_ON = 0x5f,      /* ktz8866.c: written when brightness goes from 0 to > 0 */
    KTZ_BL_ENABLE_OFF = 0x1f,     /* ... and when it goes to 0 (then 10 ms wait) */
    KTZ_BRIGHTNESS_MAX = 2047,    /* 11 bits; 4095 only with the vendor HBM mode, not used here */
    KTZ_CURRENT_CSOT = 0xb1, KTZ_CURRENT_BOE = 0xc1,
    KTZ_OFF_WAIT_US = 10000,
};

typedef struct { uint8_t reg, value; } KtzWrite;

/* 11-bit brightness to the two registers: MSB = bits 10..3, LSB = bits 2..0 (ktz8866.c update_status). */
static inline void ktz_encode(uint32_t level, uint8_t *msb, uint8_t *lsb) {
    if (level > KTZ_BRIGHTNESS_MAX) level = KTZ_BRIGHTNESS_MAX;
    *msb = (uint8_t)(level >> 3);
    *lsb = (uint8_t)(level & 0x7);
}

static inline uint32_t ktz_decode(uint8_t msb, uint8_t lsb) { return ((uint32_t)msb << 3) | (lsb & 0x7u); }

/* The chip state the firmware must have left; returns 0 if writing brightness is safe. */
static inline int ktz_check_config(uint8_t full_current, uint8_t bias_conf1) {
    if (full_current != KTZ_CURRENT_CSOT && full_current != KTZ_CURRENT_BOE) return -1;  /* unknown panel current */
    if (bias_conf1 != 0x9f) return -2;   /* OUTP/OUTN not under ENP/ENN: the panel rails are not as the vendor sets */
    return 0;
}

/* Writes for a change from `old_level` to `level`, in the vendor order: enable first when turning on, LSB then MSB,
 * disable (then KTZ_OFF_WAIT_US) when turning off. Returns the number of writes (at most 3). */
static inline int ktz_plan(uint32_t old_level, uint32_t level, KtzWrite out[3], int *wait_us) {
    int n = 0;
    uint8_t msb, lsb;
    if (level > KTZ_BRIGHTNESS_MAX) level = KTZ_BRIGHTNESS_MAX;
    *wait_us = 0;
    if (old_level == 0 && level > 0) out[n++] = (KtzWrite){KTZ_REG_BL_ENABLE, KTZ_BL_ENABLE_ON};
    else if (level == 0 && old_level != 0) { out[n++] = (KtzWrite){KTZ_REG_BL_ENABLE, KTZ_BL_ENABLE_OFF}; *wait_us = KTZ_OFF_WAIT_US; }
    ktz_encode(level, &msb, &lsb);
    out[n++] = (KtzWrite){KTZ_REG_BRT_LSB, lsb};
    out[n++] = (KtzWrite){KTZ_REG_BRT_MSB, msb};
    return n;
}

/* Registers this driver may ever write. */
static inline int ktz_write_allowed(uint8_t reg) {
    return reg == KTZ_REG_BRT_LSB || reg == KTZ_REG_BRT_MSB || reg == KTZ_REG_BL_ENABLE;
}

#endif

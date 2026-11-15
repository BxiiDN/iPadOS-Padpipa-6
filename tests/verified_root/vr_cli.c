/* SPDX-License-Identifier: MIT
 * Host harness for the VerifiedRoot kit: vr_open on an envelope with a trusted anchor, then vr_verify_block on every 4 KiB
 * block of an image. Linked with the kit's own src/verified_root.c and tests/openssl_provider.c (real RSA-3072 and
 * SHA-256 through OpenSSL), so the C parser that runs in the kernel is the code under test.
 *   vr_cli <manifest.bin> <anchor> <image> <minimum_generation>
 * Exit: the vr_status of the first failure (1 VR_FORMAT, 2 VR_KEY, 3 VR_SIGNATURE, 4 VR_HASH_TABLE, 5 VR_BLOCK), 0 if all
 * blocks verify, 10 on I/O errors. */
#include "verified_root.h"
#include <stdio.h>
#include <stdlib.h>

int vr_host_open(const uint8_t *p, size_t n, const uint8_t *key, uint64_t generation, struct vr_view *view);
int vr_host_block(const struct vr_view *view, uint64_t index, const void *data, size_t n);

static uint8_t *slurp(const char *path, size_t *n) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = malloc(size > 0 ? (size_t)size : 1);
    if (!data || fread(data, 1, (size_t)size, f) != (size_t)size) { fclose(f); free(data); return NULL; }
    fclose(f);
    *n = (size_t)size;
    return data;
}

int main(int argc, char **argv) {
    if (argc != 5) { fprintf(stderr, "usage: vr_cli manifest anchor image generation\n"); return 10; }
    size_t mn, kn, in;
    uint8_t *m = slurp(argv[1], &mn), *k = slurp(argv[2], &kn), *img = slurp(argv[3], &in);
    if (!m || !k || !img) return 10;
    if (kn != VR_KEY_BYTES) { fprintf(stderr, "anchor is %zu bytes\n", kn); return 2; }
    struct vr_view view;
    int rc = vr_host_open(m, mn, k, strtoull(argv[4], NULL, 0), &view);
    if (rc != VR_OK) { printf("open %d\n", rc); return rc; }
    if (view.image_bytes != in) { printf("size %llu != %zu\n", (unsigned long long)view.image_bytes, in); return VR_BLOCK; }
    for (uint64_t i = 0; i < view.block_count; i++) {
        size_t off = (size_t)(i * VR_BLOCK_BYTES), len = in - off < VR_BLOCK_BYTES ? in - off : VR_BLOCK_BYTES;
        rc = vr_host_block(&view, i, img + off, len);
        if (rc != VR_OK) { printf("block %llu: %d\n", (unsigned long long)i, rc); return rc; }
    }
    printf("ok %llu blocks\n", (unsigned long long)view.block_count);
    return 0;
}

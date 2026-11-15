#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Android sparse image reader: walk EVERY chunk header, so a truncated or inconsistent image is refused and the
expanded size is the one fastboot will actually write (format: AOSP system/core/libsparse/sparse_format.h).

    python3 tools/sparse.py image.img        prints the expanded size, or the reason the image is invalid
"""
from __future__ import annotations

import os
import struct
import sys

MAGIC = 0xED26FF3A
RAW, FILL, DONT_CARE, CRC32 = 0xCAC1, 0xCAC2, 0xCAC3, 0xCAC4


class SparseError(ValueError):
    pass


def info(path: str) -> dict:
    """{'sparse': bool, 'expanded': bytes, 'blk_sz', 'chunks', 'written'} or raise SparseError."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(28)
        if len(head) < 4 or struct.unpack_from("<I", head)[0] != MAGIC:
            return {"sparse": False, "expanded": size, "blk_sz": None, "chunks": 0, "written": size}
        if len(head) < 28:
            raise SparseError("truncated sparse header")
        _m, major, minor, hdr_sz, chunk_hdr_sz, blk_sz, total_blks, total_chunks, _crc = struct.unpack("<IHHHHIIII", head)
        if major != 1:
            raise SparseError(f"sparse major version {major} != 1")
        if hdr_sz < 28 or chunk_hdr_sz < 12:
            raise SparseError(f"bad header sizes {hdr_sz}/{chunk_hdr_sz}")
        if blk_sz == 0 or blk_sz % 4:
            raise SparseError(f"block size {blk_sz} is not a positive multiple of 4")
        f.seek(hdr_sz)
        blocks = written = 0
        for i in range(total_chunks):
            ch = f.read(chunk_hdr_sz)
            if len(ch) < 12:
                raise SparseError(f"truncated at chunk {i} of {total_chunks}")
            ctype, _res, chunk_sz, total_sz = struct.unpack_from("<HHII", ch)
            data = total_sz - chunk_hdr_sz
            if ctype == RAW:
                if data != chunk_sz * blk_sz:
                    raise SparseError(f"chunk {i}: raw data {data} != {chunk_sz} blocks")
                written += data
            elif ctype == FILL:
                if data != 4:
                    raise SparseError(f"chunk {i}: fill chunk with {data} data bytes")
                written += chunk_sz * blk_sz
            elif ctype == DONT_CARE:
                if data != 0:
                    raise SparseError(f"chunk {i}: don't-care chunk with data")
            elif ctype == CRC32:
                if data != 4 or chunk_sz != 0:
                    raise SparseError(f"chunk {i}: bad CRC chunk")
            else:
                raise SparseError(f"chunk {i}: unknown type {ctype:#x}")
            f.seek(data, os.SEEK_CUR)
            if f.tell() > size:
                raise SparseError(f"chunk {i} runs past the end of the file")
            blocks += chunk_sz
        if blocks != total_blks:
            raise SparseError(f"chunks cover {blocks} blocks, header says {total_blks}")
        if f.tell() != size:
            raise SparseError(f"{size - f.tell()} trailing bytes after the last chunk")
    return {"sparse": True, "expanded": total_blks * blk_sz, "blk_sz": blk_sz, "chunks": total_chunks, "written": written}


def build(chunks: list[tuple[int, int, bytes]], blk_sz: int = 4096) -> bytes:
    """Test helper: chunks of (type, blocks, payload)."""
    body = b"".join(struct.pack("<HHII", t, 0, n, 12 + len(p)) + p for t, n, p in chunks)
    total = sum(n for _t, n, _p in chunks)
    return struct.pack("<IHHHHIIII", MAGIC, 1, 0, 28, 12, blk_sz, total, len(chunks), 0) + body


if __name__ == "__main__":
    try:
        print(info(sys.argv[1]))
    except SparseError as e:
        print(f"invalid sparse image: {e}")
        sys.exit(1)

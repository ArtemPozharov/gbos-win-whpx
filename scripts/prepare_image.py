#!/usr/bin/env python3
"""Assembles the Googlebook OS base image from recovery assets with relative paths."""
import gzip
import hashlib
import json
import os
import pathlib
import shutil
import stat
import struct
import subprocess
import sys
import uuid
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXTRACTED = ROOT / 'extracted'
BUILD = ROOT / 'build'
PREPARED = ROOT / 'prepared'
DOWNLOADS = ROOT / 'downloads'

QEMU = ROOT / 'qemu' / 'qemu-system-x86_64.exe'
QEMU_IMG = ROOT / 'qemu' / 'qemu-img.exe'


def cpio_entry(name: str, body: bytes, ino: int, mode: int = 0o100644) -> bytes:
    n = name.encode() + b'\0'
    fields = [ino, mode, 0, 0, 1, 0, len(body), 0, 0, 0, 0, len(n), 0]
    block = b'070701' + b''.join(f'{v:08x}'.encode() for v in fields) + n
    block += b'\0' * (-len(block) % 4) + body + b'\0' * (-len(body) % 4)
    return block


def strip_cpio_trailers(raw: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(raw):
        if raw[i:i+6] != b'070701':
            if raw[i] == 0:
                i += 1
                continue
            raise ValueError(f'Unexpected cpio magic at {i}: {raw[i:i+6]!r}')
        filesize = int(raw[i+54:i+62], 16)
        namesize = int(raw[i+94:i+102], 16)
        name = raw[i+110:i+110+namesize-1].decode()
        hdr_end = i + 110 + namesize
        hdr_end += (-hdr_end) % 4
        next_i = hdr_end + filesize
        next_i += (-next_i) % 4
        if name != 'TRAILER!!!':
            out.extend(raw[i:next_i])
        i = next_i
    return bytes(out)


def main():
    PREPARED.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)

    print("Checking recovery assets...")
    # Locates downloaded raw recovery or extracted partitions
    ruby_raw = next(DOWNLOADS.glob('*ruby*.raw'), None) or next(DOWNLOADS.glob('*recovery*.raw'), None)
    if not ruby_raw or not ruby_raw.exists():
        print(f"Error: No recovery .raw file found in {DOWNLOADS}.")
        print("Please place the unpacked Googlebook OS recovery image (chromeos_...ruby...bin) into downloads/")
        sys.exit(1)

    print(f"Found recovery image: {ruby_raw.name}")
    print("Error: disk assembly is not implemented in this repository.")
    print("prepared/base.qcow2, kernel, initrd and vm.json must be created separately.")
    sys.exit(1)

if __name__ == '__main__':
    main()

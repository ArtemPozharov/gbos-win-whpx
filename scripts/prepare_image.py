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

    # 1. Ensure manifest and cmdline are present in prepared/
    launcher_manifest = ROOT / 'launcher' / 'vm.json'
    target_manifest = PREPARED / 'vm.json'
    if launcher_manifest.is_file() and not target_manifest.is_file():
        shutil.copyfile(launcher_manifest, target_manifest)
        print("Initialized prepared/vm.json from launcher template.")

    launcher_cmdline = ROOT / 'launcher' / 'cmdline.txt'
    target_cmdline = PREPARED / 'cmdline.txt'
    if launcher_cmdline.is_file() and not target_cmdline.is_file():
        shutil.copyfile(launcher_cmdline, target_cmdline)
        print("Initialized prepared/cmdline.txt from launcher template.")

    # 2. Check for kernel and initrd
    sibling_prepared = ROOT.parent / 'gbos-win-vm' / 'prepared'
    if sibling_prepared.is_dir():
        for asset_name in ('kernel', 'initrd.gz', 'base.qcow2'):
            src = sibling_prepared / asset_name
            dst = PREPARED / asset_name
            if src.is_file() and not dst.is_file():
                print(f"Importing {asset_name} from local dev environment...")
                shutil.copyfile(src, dst)

    # 3. Check base disk
    base_disk = PREPARED / 'base.qcow2'
    if base_disk.is_file():
        print(f"Base disk image found: {base_disk} ({base_disk.stat().st_size / (1024**3):.2f} GiB)")
        return 0

    print("Checking recovery assets in downloads/...")
    ruby_raw = next(DOWNLOADS.glob('*ruby*.raw'), None) or next(DOWNLOADS.glob('*recovery*.raw'), None) or next(DOWNLOADS.glob('*.bin'), None)
    if ruby_raw and ruby_raw.exists():
        print(f"Found recovery image: {ruby_raw.name} ({ruby_raw.stat().st_size / (1024**3):.2f} GiB)")
        print("Note: To assemble base.qcow2 from recovery raw, disk assembly tools are required.")
    else:
        print("No base.qcow2 or recovery raw found in downloads/.")
        print("Please place prepared/base.qcow2 or download the recovery image via install.ps1.")

    return 0

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Assembles the Googlebook OS VM assets (kernel, initrd.gz, cmdline.txt, base.qcow2, vm.json) from recovery raw.

With --virgl, only (re)creates prepared/base-virgl.qcow2 from build/vendor-virgl.erofs (optional GPU variant)."""
import gzip
import hashlib
import json
import os
import pathlib
import re
import shutil
import struct
import sys
import uuid
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'assets'
BUILD = ROOT / 'build'
PREPARED = ROOT / 'prepared'
DOWNLOADS = ROOT / 'downloads'


def lz4_decompress_legacy(data: bytes) -> bytes:
    """Pure-Python decompressor for LZ4 legacy frames (magic 0x184c2102) used in Android init_boot."""
    if data[:4] != b'\x02\x21\x4c\x18':
        raise ValueError(f"Unsupported LZ4 frame magic: {data[:4].hex()}")
    pos = 4
    out = bytearray()
    n = len(data)
    while pos + 4 <= n:
        bsz = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        if bsz == 0 or bsz == 0x184C2102:
            break
        end = pos + bsz
        while pos < end:
            token = data[pos]
            pos += 1
            lit_len = token >> 4
            if lit_len == 15:
                while True:
                    b = data[pos]
                    pos += 1
                    lit_len += b
                    if b != 255:
                        break
            if lit_len:
                out.extend(data[pos:pos + lit_len])
                pos += lit_len
            if pos >= end:
                break
            offset = data[pos] | (data[pos + 1] << 8)
            pos += 2
            match_len = (token & 0x0F) + 4
            if match_len == 19:
                while True:
                    b = data[pos]
                    pos += 1
                    match_len += b
                    if b != 255:
                        break
            start = len(out) - offset
            if offset >= match_len:
                out.extend(out[start:start + match_len])
            else:
                for i in range(match_len):
                    out.append(out[start + i])
    return bytes(out)


def cpio_entry(name: str, body: bytes, ino: int, mode: int = 0o100644) -> bytes:
    n = name.encode() + b'\0'
    fields = [ino, mode, 0, 0, 1, 0, len(body), 0, 0, 0, 0, len(n), 0]
    block = b'070701' + b''.join(f'{v:08x}'.encode() for v in fields) + n
    block += b'\0' * (-len(block) % 4) + body + b'\0' * (-len(body) % 4)
    return block


def find_gpt_partition(recovery_raw: pathlib.Path, target_name: str) -> tuple[int, int]:
    """Return (byte_offset, byte_size) of a named GPT partition inside recovery_raw."""
    with recovery_raw.open('rb') as f:
        f.seek(512)
        hdr = f.read(512)
        if hdr[:8] != b'EFI PART':
            raise ValueError(f"Invalid GPT header in {recovery_raw}")
        tlba, count, esz = struct.unpack_from('<QII', hdr, 72)
        f.seek(tlba * 512)
        table = f.read(count * esz)
        for i in range(count):
            entry = table[i * esz:(i + 1) * esz]
            if not any(entry[:16]):
                continue
            name = entry[56:128].decode('utf-16le', errors='ignore').rstrip('\0')
            if name == target_name:
                start_lba, end_lba = struct.unpack_from('<QQ', entry, 32)
                return start_lba * 512, (end_lba - start_lba + 1) * 512
    raise ValueError(f"GPT partition '{target_name}' not found in {recovery_raw}")


def find_super_subpartition_offset(recovery_raw: pathlib.Path, sub_name: str = 'vendor_a') -> int:
    """Locate a logical partition (e.g. vendor_a) inside the Android super partition via liblp metadata."""
    super_off, _ = find_gpt_partition(recovery_raw, 'super')
    with recovery_raw.open('rb') as f:
        f.seek(super_off + 12288)
        meta = f.read(65536)
        magic, major, minor, hdr_size = struct.unpack_from('<IHHI', meta, 0)
        if magic != 0x414C5030:
            return 6289358848
        p_off, p_num, p_esz = struct.unpack_from('<III', meta, 80)
        e_off, e_num, e_esz = struct.unpack_from('<III', meta, 80 + 12)
        for i in range(p_num):
            pe = meta[hdr_size + p_off + i * p_esz:hdr_size + p_off + (i + 1) * p_esz]
            name = pe[:36].decode('ascii', errors='ignore').rstrip('\x00')
            attrs, first_ext, num_exts, _ = struct.unpack_from('<IIII', pe, 36)
            if name == sub_name and num_exts > 0:
                ee = meta[hdr_size + e_off + first_ext * e_esz:hdr_size + e_off + (first_ext + 1) * e_esz]
                num_sectors, target_type, target_data, _ = struct.unpack_from('<QIQI', ee, 0)
                return super_off + target_data * 512
    return 6289358848


def extract_vbmeta_info(recovery_raw: pathlib.Path) -> tuple[int, str]:
    """Extract vbmeta_a AVB total size and SHA-256 digest from recovery_raw."""
    vb_off, vb_size = find_gpt_partition(recovery_raw, 'vbmeta_a')
    with recovery_raw.open('rb') as f:
        f.seek(vb_off)
        vb = f.read(min(vb_size, 65536))
    if vb[:4] != b'AVB0':
        raise ValueError("Invalid AVB0 magic in vbmeta_a partition")
    vs = 256 + int.from_bytes(vb[12:20], 'big') + int.from_bytes(vb[20:28], 'big')
    digest = hashlib.sha256(vb[:vs]).hexdigest()
    return vs, digest


def extract_init_boot_cpio(recovery_raw: pathlib.Path) -> bytes:
    """Extract and decompress the Android init_boot_a ramdisk CPIO (without trailing TRAILER!!!)."""
    ib_off, _ = find_gpt_partition(recovery_raw, 'init_boot_a')
    with recovery_raw.open('rb') as f:
        f.seek(ib_off)
        hdr = f.read(4096)
        if hdr[:8] != b'ANDROID!':
            raise ValueError("Invalid ANDROID! boot header in init_boot_a")
        ramdisk_size = struct.unpack_from('<I', hdr, 12)[0]
        lz4_data = f.read(ramdisk_size)
    c2 = lz4_decompress_legacy(lz4_data)
    trailer_pos = c2.rfind(b'070701', 0, c2.rfind(b'TRAILER!!!'))
    if trailer_pos == -1:
        raise ValueError("Could not locate CPIO TRAILER!!! in init_boot_a ramdisk")
    return c2[:trailer_pos]


def make_fat32_header(total_bytes: int, label: bytes = b'GBRUNCH_LOG') -> bytes:
    bps = 512
    spc = 8
    reserved_sectors = 32
    fats = 2
    total_sectors = total_bytes // bps
    clusters = (total_sectors - reserved_sectors) // spc
    spf32 = ((clusters + 2) * 4 + bps - 1) // bps
    data_start_sector = reserved_sectors + fats * spf32
    total_clusters = (total_sectors - data_start_sector) // spc

    buf = bytearray((data_start_sector + spc) * bps)
    bs = bytearray(512)
    bs[0:3] = b'\xeb\x58\x90'
    bs[3:11] = b'mkfs.fat'
    struct.pack_into('<H', bs, 11, bps)
    bs[13] = spc
    struct.pack_into('<H', bs, 14, reserved_sectors)
    bs[16] = fats
    bs[21] = 0xF8
    struct.pack_into('<H', bs, 24, 32)
    struct.pack_into('<H', bs, 26, 64)
    struct.pack_into('<I', bs, 32, total_sectors)
    struct.pack_into('<I', bs, 36, spf32)
    struct.pack_into('<I', bs, 44, 2)
    struct.pack_into('<H', bs, 48, 1)
    struct.pack_into('<H', bs, 50, 6)
    bs[64] = 0x80
    bs[66] = 0x29
    struct.pack_into('<I', bs, 67, 0x47424C47)
    bs[71:82] = label.ljust(11, b' ')[:11]
    bs[82:90] = b'FAT32   '
    bs[510:512] = b'\x55\xaa'

    fsinfo = bytearray(512)
    fsinfo[0:4] = b'RRaA'
    fsinfo[484:488] = b'rrAa'
    struct.pack_into('<I', fsinfo, 488, total_clusters - 1)
    struct.pack_into('<I', fsinfo, 492, 3)
    fsinfo[510:512] = b'\x55\xaa'

    buf[0:512] = bs
    buf[512:1024] = fsinfo
    buf[6 * 512:7 * 512] = bs
    buf[7 * 512:8 * 512] = fsinfo

    fat_init = struct.pack('<III', 0x0FFFFFF8, 0x0FFFFFFF, 0x0FFFFFF8)
    fat1_off = reserved_sectors * bps
    fat2_off = (reserved_sectors + spf32) * bps
    buf[fat1_off:fat1_off + 12] = fat_init
    buf[fat2_off:fat2_off + 12] = fat_init

    root_off = data_start_sector * bps
    buf[root_off:root_off + 11] = label.ljust(11, b' ')[:11]
    buf[root_off + 11] = 0x08
    return bytes(buf)


def reconstruct_vendor_erofs_bytes(recovery_raw: pathlib.Path) -> bytes:
    """Reconstruct vendor-software.erofs in memory from recovery_raw's vendor_a partition and assets/vendor-patch.zlib."""
    vendor_off = find_super_subpartition_offset(recovery_raw, 'vendor_a')
    raw_patch = zlib.decompress((ASSETS / 'vendor-patch.zlib').read_bytes())
    orig_size, num_blocks = struct.unpack_from('<II', raw_patch, 0)

    with recovery_raw.open('rb') as f:
        f.seek(vendor_off)
        vendor_buf = bytearray(f.read(orig_size))

    if len(vendor_buf) != orig_size:
        raise ValueError(f"Short read from vendor_a at offset {vendor_off}: got {len(vendor_buf)}, expected {orig_size}")

    pos = 8
    for _ in range(num_blocks):
        blk_off = struct.unpack_from('<I', raw_patch, pos)[0]
        pos += 4
        vendor_buf[blk_off:blk_off + 4096] = raw_patch[pos:pos + 4096]
        pos += 4096

    vendor_buf.extend(raw_patch[pos:])
    return bytes(vendor_buf)


def write_qcow2_backed(
    out_path: pathlib.Path,
    backing_file: str,
    virtual_size: int,
    writes: list[tuple[int, bytes]],
    raw_backing_path: pathlib.Path,
    backing_format: str = 'raw',
) -> None:
    """Write a QCOW2 v3 overlay image backed by raw_backing_path with exact byte writes at arbitrary guest offsets."""
    CS = 65536
    L2_ENTRIES = CS // 8
    clusters: dict[int, bytearray] = {}
    raw_size = raw_backing_path.stat().st_size

    with raw_backing_path.open('rb') as rf:
        for offset, data in writes:
            pos = 0
            n = len(data)
            mv = memoryview(data)
            while pos < n:
                g_off = offset + pos
                c_idx = g_off // CS
                c_off = g_off % CS
                chunk_len = min(CS - c_off, n - pos)
                if c_idx not in clusters:
                    buf = bytearray(CS)
                    if c_idx * CS < raw_size and chunk_len < CS:
                        rf.seek(c_idx * CS)
                        b = rf.read(min(CS, raw_size - c_idx * CS))
                        buf[:len(b)] = b
                    clusters[c_idx] = buf
                clusters[c_idx][c_off:c_off + chunk_len] = mv[pos:pos + chunk_len]
                pos += chunk_len

    sorted_c_indices = sorted(clusters.keys())
    l1_indices = sorted({c_idx // L2_ENTRIES for c_idx in sorted_c_indices})
    num_l2 = len(l1_indices)
    num_data = len(sorted_c_indices)
    num_refblock = 1
    meta_clusters = 3 + num_refblock + num_l2
    total_host_clusters = meta_clusters + num_data
    if total_host_clusters > 32768:
        raise ValueError(f"Host cluster count {total_host_clusters} exceeds single refcount block capacity")

    l2_host_cluster = {l1_idx: 3 + num_refblock + i for i, l1_idx in enumerate(l1_indices)}
    data_host_cluster = {c_idx: meta_clusters + i for i, c_idx in enumerate(sorted_c_indices)}
    OFLAG_COPIED = 1 << 63

    hdr = bytearray(CS)
    bf_bytes = backing_file.encode('utf-8')
    # Header extension at offset 104: Backing file format (magic 0xE2792ACA)
    ext_offset = 104
    fmt = backing_format.encode('ascii')
    struct.pack_into('>II8sII', hdr, ext_offset, 0xE2792ACA, len(fmt), fmt.ljust(8, b'\x00'), 0, 0)
    bf_offset = ext_offset + 24
    l1_entries = (virtual_size + (L2_ENTRIES * CS) - 1) // (L2_ENTRIES * CS)
    struct.pack_into(
        '>4sIQIIQIIQQIIQQQQII',
        hdr,
        0,
        b'QFI\xfb',
        3,
        bf_offset,
        len(bf_bytes),
        16,
        virtual_size,
        0,
        l1_entries,
        1 * CS,
        2 * CS,
        1,
        0,
        0,
        0,
        0,
        0,
        4,
        104,
    )
    hdr[bf_offset:bf_offset + len(bf_bytes)] = bf_bytes

    l1_tbl = bytearray(CS)
    for l1_idx, h_c in l2_host_cluster.items():
        struct.pack_into('>Q', l1_tbl, l1_idx * 8, (h_c * CS) | OFLAG_COPIED)

    reftbl = bytearray(CS)
    struct.pack_into('>Q', reftbl, 0, 3 * CS)

    refblk = bytearray(CS)
    for hc in range(total_host_clusters):
        struct.pack_into('>H', refblk, hc * 2, 1)

    with out_path.open('wb') as f:
        f.write(hdr)
        f.write(l1_tbl)
        f.write(reftbl)
        f.write(refblk)
        for l1_idx in l1_indices:
            l2_tbl = bytearray(CS)
            for l2_slot in range(L2_ENTRIES):
                c_idx = l1_idx * L2_ENTRIES + l2_slot
                if c_idx in data_host_cluster:
                    h_c = data_host_cluster[c_idx]
                    struct.pack_into('>Q', l2_tbl, l2_slot * 8, (h_c * CS) | OFLAG_COPIED)
            f.write(l2_tbl)
        for c_idx in sorted_c_indices:
            f.write(clusters[c_idx])


def write_virgl_overlay(recovery_raw: pathlib.Path, erofs: pathlib.Path, base: pathlib.Path, overlay: pathlib.Path) -> None:
    """Write a qcow2 overlay of base that replaces the GBVENDOR partition with a Mesa VirGL vendor EROFS."""
    mib = 1048576
    # GBVENDOR sits right after GBRUNCH, which starts at the 1 MiB-aligned end of the recovery raw.
    compat_size = len(zlib.decompress((ASSETS / 'compat-vm.ext4.zlib').read_bytes()))
    vendor_off = (recovery_raw.stat().st_size + mib - 1) // mib * mib + (compat_size + mib - 1) // mib * mib
    part_size = (len(reconstruct_vendor_erofs_bytes(recovery_raw)) + mib - 1) // mib * mib
    new_size = erofs.stat().st_size
    if new_size > part_size:
        raise ValueError(f"{erofs.name} ({new_size} B) does not fit the GBVENDOR partition ({part_size} B)")
    assert vendor_off % 65536 == 0 and part_size % 65536 == 0  # whole qcow2 clusters, no backing merge needed

    with base.open('rb') as f:
        hdr = f.read(32)
    if hdr[:4] != b'QFI\xfb':
        raise ValueError(f"{base} is not a qcow2 image")
    virtual_size = struct.unpack_from('>Q', hdr, 24)[0]
    padded = erofs.read_bytes().ljust(part_size, b'\0')
    write_qcow2_backed(overlay, base.name, virtual_size, [(vendor_off, padded)], base, backing_format='qcow2')


def prepare_virgl() -> int:
    """Optional step: prepared/base-virgl.qcow2 from build/vendor-virgl.erofs (see scripts/build_vendor_virgl.py)."""
    erofs = BUILD / 'vendor-virgl.erofs'
    base = PREPARED / 'base.qcow2'
    raw = find_recovery_raw()
    if not raw or not base.is_file():
        print("Error: recovery raw or prepared/base.qcow2 missing; run install.ps1 first.", file=sys.stderr)
        return 1
    if not erofs.is_file():
        print(f"Error: {erofs} missing; build it first with: python scripts/build_vendor_virgl.py", file=sys.stderr)
        return 1
    overlay = PREPARED / 'base-virgl.qcow2'
    write_virgl_overlay(raw, erofs, base, overlay)
    print(f"prepared/base-virgl.qcow2 ready ({overlay.stat().st_size / (1024**2):.1f} MiB overlay on base.qcow2)")
    return 0


def find_recovery_raw() -> pathlib.Path | None:
    for pattern in ('*ruby*.raw', '*recovery*.raw', '*.bin'):
        hit = next(DOWNLOADS.glob(pattern), None)
        if hit and hit.is_file():
            return hit
    sibling_raw = ROOT.parent / 'gbos-win-vm' / 'downloads' / 'ruby-recovery.raw'
    if sibling_raw.is_file():
        return sibling_raw
    return None


def get_isa_patch_artifacts() -> tuple[bytes, bytes, str]:
    ko_path = ROOT / 'patches' / 'avx_vnni' / 'avx_vnni_emu.ko'
    preinit_path = ROOT / 'patches' / 'avx_vnni' / 'preinit'
    if not ko_path.is_file():
        raise FileNotFoundError(f"Missing ISA compatibility kernel module: {ko_path}")
    if not preinit_path.is_file():
        raise FileNotFoundError(f"Missing early preinit wrapper: {preinit_path}")
    ko_bytes = ko_path.read_bytes()
    preinit_bytes = preinit_path.read_bytes()
    isa_sha = hashlib.sha256(ko_bytes + preinit_bytes).hexdigest()
    return ko_bytes, preinit_bytes, isa_sha


def update_existing_initrd_isa(initrd_path: pathlib.Path, ko_bytes: bytes, preinit_bytes: bytes) -> None:
    raw = gzip.decompress(initrd_path.read_bytes())
    t_idx = raw.rfind(b'TRAILER!!!')
    t_pos = raw.rfind(b'070701', 0, t_idx) if t_idx != -1 else len(raw)
    base_cpio = raw[:t_pos] if t_pos != -1 else raw
    updated = (
        base_cpio
        + cpio_entry('lib/modules/avx_vnni_emu.ko', ko_bytes, 900001)
        + cpio_entry('preinit', preinit_bytes, 900002, mode=0o100755)
        + cpio_entry('TRAILER!!!', b'', 0, mode=0)
    )
    initrd_path.write_bytes(gzip.compress(updated, compresslevel=6, mtime=0))


def main() -> int:
    if '--virgl' in sys.argv[1:]:
        return prepare_virgl()

    PREPARED.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)

    launcher_manifest = ROOT / 'launcher' / 'vm.json'
    target_manifest = PREPARED / 'vm.json'
    if launcher_manifest.is_file() and not target_manifest.is_file():
        shutil.copyfile(launcher_manifest, target_manifest)

    launcher_cmdline = ROOT / 'launcher' / 'cmdline.txt'
    target_cmdline = PREPARED / 'cmdline.txt'
    if launcher_cmdline.is_file() and not target_cmdline.is_file():
        shutil.copyfile(launcher_cmdline, target_cmdline)

    ko_bytes, preinit_bytes, isa_sha = get_isa_patch_artifacts()
    existing_spec = json.loads(target_manifest.read_text(encoding='utf-8')) if target_manifest.is_file() else {}
    isa_outdated = existing_spec.get('isa_patch_sha256') != isa_sha

    ruby_raw = find_recovery_raw()
    if not ruby_raw:
        if all((PREPARED / f).is_file() for f in ('kernel', 'initrd.gz', 'cmdline.txt', 'base.qcow2', 'vm.json')):
            if isa_outdated:
                print("Updating existing prepared/initrd.gz and cmdline.txt with latest CPU ISA patch...")
                update_existing_initrd_isa(PREPARED / 'initrd.gz', ko_bytes, preinit_bytes)
            cmdline = target_cmdline.read_text(encoding='utf-8')
            cmdline = re.sub(r'\brdinit=/init\b', 'rdinit=/preinit', cmdline)
            target_cmdline.write_text(cmdline, encoding='utf-8')
            existing_spec['isa_patch_sha256'] = isa_sha
            existing_spec['assets']['kernel']['sha256'] = hashlib.sha256((PREPARED / 'kernel').read_bytes()).hexdigest()
            existing_spec['assets']['initrd']['sha256'] = hashlib.sha256((PREPARED / 'initrd.gz').read_bytes()).hexdigest()
            existing_spec['assets']['cmdline']['sha256'] = hashlib.sha256(target_cmdline.read_bytes()).hexdigest()
            target_manifest.write_text(json.dumps(existing_spec, indent=2) + '\n', encoding='utf-8')
            print("All prepared VM assets are present and up to date.")
            return 0
        print("Error: Official recovery raw image not found in downloads/.", file=sys.stderr)
        print("Please run .\\install.ps1 (without -SkipDownload) to download and extract the recovery image.", file=sys.stderr)
        return 1

    print(f"Found recovery image: {ruby_raw} ({ruby_raw.stat().st_size / (1024**3):.2f} GiB)")

    # 1. Prepare kernel
    kernel_out = PREPARED / 'kernel'
    if not kernel_out.is_file():
        print("[1/5] Extracting compatibility Linux kernel...")
        kernel_bytes = zlib.decompress((ASSETS / 'kernel.zlib').read_bytes())
        kernel_out.write_bytes(kernel_bytes)
        print(f"      prepared/kernel ready ({len(kernel_bytes) / (1024**2):.2f} MiB)")
    else:
        print("[1/5] prepared/kernel already present.")

    # 2. Assemble initrd.gz from Cuttlefish base + recovery init_boot_a + CPU ISA & VirtIO overlay
    initrd_out = PREPARED / 'initrd.gz'
    if not initrd_out.is_file() or isa_outdated:
        print("[2/5] Assembling prepared/initrd.gz from recovery init_boot_a and compatibility ramdisk...")
        c1 = zlib.decompress((ASSETS / 'initrd-base.cpio.zlib').read_bytes())
        c2 = extract_init_boot_cpio(ruby_raw)
        ko_entry = cpio_entry('lib/modules/avx_vnni_emu.ko', ko_bytes, 900001)
        preinit_entry = cpio_entry('preinit', preinit_bytes, 900002, mode=0o100755)
        c3_rest = zlib.decompress((ASSETS / 'initrd-overlay.cpio.zlib').read_bytes())
        initrd_raw = c1 + c2 + ko_entry + preinit_entry + c3_rest
        initrd_gz = gzip.compress(initrd_raw, compresslevel=6, mtime=0)
        initrd_out.write_bytes(initrd_gz)
        print(f"      prepared/initrd.gz ready ({len(initrd_gz) / (1024**2):.2f} MiB)")
    else:
        print("[2/5] prepared/initrd.gz already present.")

    # 3. Update cmdline.txt with rdinit=/preinit and vbmeta_a AVB digest
    print("[3/5] Configuring kernel cmdline.txt for AVB verification...")
    vs, digest = extract_vbmeta_info(ruby_raw)
    cmdline = target_cmdline.read_text(encoding='utf-8')
    cmdline = re.sub(r'\brdinit=/init\b', 'rdinit=/preinit', cmdline)
    cmdline = re.sub(r'androidboot\.vbmeta\.size=\d+', f'androidboot.vbmeta.size={vs}', cmdline)
    cmdline = re.sub(r'androidboot\.vbmeta\.digest=[a-f0-9]+', f'androidboot.vbmeta.digest={digest}', cmdline)
    target_cmdline.write_text(cmdline, encoding='utf-8')
    print(f"      AVB vbmeta_a configured (size={vs}, digest={digest[:16]}...)")

    # 4. Assemble prepared/base.qcow2
    base_disk = PREPARED / 'base.qcow2'
    if not base_disk.is_file():
        print("[4/5] Reconstructing GBRUNCH and GBVENDOR partitions...")
        compat_bytes = zlib.decompress((ASSETS / 'compat-vm.ext4.zlib').read_bytes())
        vendor_bytes = reconstruct_vendor_erofs_bytes(ruby_raw)

        print("[5/5] Building GPT partition table and writing prepared/base.qcow2...")
        with ruby_raw.open('rb') as f:
            mbr = bytearray(f.read(512))
            header = bytearray(f.read(512))
            if header[:8] != b'EFI PART':
                raise ValueError("Invalid GPT header in recovery raw image")
            tlba, count, esz = struct.unpack_from('<QII', header, 72)
            f.seek(tlba * 512)
            table = bytearray(f.read(count * esz))

        cursor = (ruby_raw.stat().st_size + 1048575) // 1048576 * 1048576
        gblog_size = 256 * 1024 * 1024
        gblog_hdr = make_fat32_header(gblog_size)

        appended = []
        for n, psize, guid_prefix in [
            ('GBRUNCH', (len(compat_bytes) + 1048575) // 1048576 * 1048576, '4ab7c001'),
            ('GBVENDOR', (len(vendor_bytes) + 1048575) // 1048576 * 1048576, '4ab7c002'),
            ('GBLOG', gblog_size, '4ab7c003'),
        ]:
            start_lba = cursor // 512
            end_lba = (cursor + psize) // 512 - 1
            slot = next(i for i in range(count) if not any(table[i * esz:i * esz + 16]))
            e = bytearray(esz)
            e[:16] = uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4').bytes_le
            e[16:32] = uuid.UUID(f'{guid_prefix}-7400-4bab-b412-43cbd52b9fb1').bytes_le
            struct.pack_into('<QQQ', e, 32, start_lba, end_lba, 0)
            encoded = n.encode('utf-16le')
            e[56:56 + len(encoded)] = encoded
            table[slot * esz:(slot + 1) * esz] = e
            appended.append({'name': n, 'offset': cursor, 'bytes': psize})
            cursor += psize

        userdata_slots = [
            i for i in range(count)
            if table[i * esz + 56:(i + 1) * esz].decode('utf-16le', errors='ignore').rstrip('\0') == 'userdata'
        ]
        if len(userdata_slots) != 1:
            raise ValueError(f"Expected 1 userdata partition in GPT, found {len(userdata_slots)}")
        u_slot = userdata_slots[0]
        userdata_size = 16 * 1024 * 1024 * 1024
        u_start = cursor // 512
        u_end = (cursor + userdata_size) // 512 - 1
        struct.pack_into('<QQ', table, u_slot * esz + 32, u_start, u_end)
        cursor += userdata_size

        ts = (len(table) + 511) // 512
        last_lba = cursor // 512 + ts
        struct.pack_into('<Q', header, 32, last_lba)
        struct.pack_into('<Q', header, 48, cursor // 512 - 1)
        struct.pack_into('<I', header, 88, zlib.crc32(table))
        struct.pack_into('<I', header, 16, 0)
        struct.pack_into('<I', header, 16, zlib.crc32(header[:92]))

        backup = bytearray(header)
        struct.pack_into('<QQ', backup, 24, last_lba, 1)
        struct.pack_into('<Q', backup, 72, last_lba - ts)
        struct.pack_into('<I', backup, 16, 0)
        struct.pack_into('<I', backup, 16, zlib.crc32(backup[:92]))
        struct.pack_into('<I', mbr, 458, min(last_lba, 0xFFFFFFFF))

        try:
            backing_rel = os.path.relpath(ruby_raw, PREPARED)
        except ValueError:
            backing_rel = str(ruby_raw)

        total_disk_bytes = (last_lba + 1) * 512
        writes = [
            (0, bytes(mbr) + bytes(header)),
            (tlba * 512, bytes(table)),
            (appended[0]['offset'], compat_bytes),
            (appended[1]['offset'], vendor_bytes),
            (appended[2]['offset'], gblog_hdr),
            ((last_lba - ts) * 512, bytes(table) + bytes(backup)),
        ]
        write_qcow2_backed(base_disk, backing_rel, total_disk_bytes, writes, ruby_raw)
        print(f"      prepared/base.qcow2 assembled ({base_disk.stat().st_size / (1024**2):.1f} MiB overlay)")
    else:
        print("[4/5] prepared/base.qcow2 already present.")

    # Update vm.json hashes
    spec = json.loads(target_manifest.read_text(encoding='utf-8'))
    spec['isa_patch_sha256'] = isa_sha
    spec['assets']['kernel']['sha256'] = hashlib.sha256(kernel_out.read_bytes()).hexdigest()
    spec['assets']['initrd']['sha256'] = hashlib.sha256(initrd_out.read_bytes()).hexdigest()
    spec['assets']['cmdline']['sha256'] = hashlib.sha256(target_cmdline.read_bytes()).hexdigest()
    target_manifest.write_text(json.dumps(spec, indent=2) + '\n', encoding='utf-8')
    print("Updated prepared/vm.json with verified SHA-256 asset digests.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Patch virtio-gpu.ko format translation table inside initrd.gz to fix RGB/BGR inverted colors."""
import gzip
import hashlib
import json
import pathlib
import sys

def patch_initrd_colors(initrd_path: pathlib.Path, vm_json_path: pathlib.Path | None = None) -> str:
    data = initrd_path.read_bytes()
    if vm_json_path and vm_json_path.exists():
        expected = json.loads(vm_json_path.read_text(encoding='utf-8'))['assets']['initrd'].get('sha256')
        if expected and hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("initrd.gz does not match the SHA-256 in vm.json; refusing to patch")
    raw = bytearray(gzip.decompress(data))
    pos = raw.find(bytes.fromhex('81ff415832347f3681ff415232347454'))
    if pos == -1:
        raise ValueError("Signature for virtio_gpu_translate_format not found in initrd.gz")

    p1 = raw.find(bytes.fromhex('81ff415232347454b8'), pos)
    p2 = raw.find(bytes.fromhex('b8030000002ee900000000b8'), pos)
    if p1 == -1 or p2 == -1:
        raise ValueError("Patch signatures not found in initrd.gz; refusing to patch")
    p1 += 9
    p2 += 12

    # Map XR24 and AR24 to 0x43 (VIRTIO_GPU_FORMAT_R8G8B8A8_UNORM -> PIXMAN_a8b8g8r8)
    # Byte 0=Red, Byte 1=Green, Byte 2=Blue, Byte 3=Alpha. Pure black (0,0,0,255) stays black.
    raw[p1] = 0x43
    raw[p2] = 0x43

    compressed = gzip.compress(bytes(raw), compresslevel=6, mtime=0)
    initrd_path.write_bytes(compressed)
    new_sha = hashlib.sha256(compressed).hexdigest()

    if vm_json_path and vm_json_path.exists():
        spec = json.loads(vm_json_path.read_text(encoding='utf-8'))
        spec['assets']['initrd']['sha256'] = new_sha
        vm_json_path.write_text(json.dumps(spec, indent=2) + '\n', encoding='utf-8')

    return new_sha

if __name__ == '__main__':
    target = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else 'prepared/initrd.gz')
    v_json = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else target.parent / 'vm.json'
    sha = patch_initrd_colors(target, v_json)
    print(f"initrd.gz color patch applied successfully! New SHA-256: {sha}")

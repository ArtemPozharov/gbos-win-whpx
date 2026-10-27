#!/usr/bin/env python3
"""Builds a GBVENDOR variant with Mesa VirGL (GLES) and a qcow2 overlay of prepared/base.qcow2 that uses it.

Requires WSL (distro 'Ubuntu' by default) with an extracted vendor tree and an Android Mesa VirGL build.
Outputs: build/vendor-virgl.erofs and prepared/base-virgl.qcow2 (backed by prepared/base.qcow2).
"""
import argparse
import pathlib
import shlex
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import prepare_image as pi  # noqa: E402

DEFAULT_WSL_DISTRO = 'Ubuntu'
DEFAULT_MESA_OUT = '/root/build/out'
DEFAULT_VEND = '/root/vend'
DEFAULT_STAGE = '/root/vend-virgl'
DEFAULT_NDK_STRIP = '/root/build/android-ndk-r27c/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip'

# (Mesa build artifact, path inside the vendor tree)
MESA_LIBS = [
    ('src/gallium/targets/dri/libgallium_dri.so', 'lib64/libgallium_dri.so'),
    ('src/egl/libEGL.so', 'lib64/egl/libEGL_mesa.so'),
    ('src/mesa/glapi/es1api/libGLESv1_CM.so', 'lib64/egl/libGLESv1_CM_mesa.so'),
    ('src/mesa/glapi/es2api/libGLESv2.so', 'lib64/egl/libGLESv2_mesa.so'),
]


def wsl(distro: str, script: str) -> str:
    r = subprocess.run(
        ['wsl', '-d', distro, '-u', 'root', '-e', 'bash', '-ec', script],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )
    if r.returncode != 0:
        raise RuntimeError(f"WSL step failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r.stdout


def win_to_wsl(p: pathlib.Path) -> str:
    resolved = p.resolve()
    return f"/mnt/{resolved.drive.rstrip(':').lower()}/" + '/'.join(resolved.parts[1:])


def build_erofs(
    out: pathlib.Path,
    raw: pathlib.Path,
    distro: str,
    mesa_out: str,
    vend: str,
    stage: str,
    ndk_strip: str,
) -> None:
    vendor_stock = pi.BUILD / 'vendor-stock.erofs'
    if not vendor_stock.is_file():
        print('      Reconstructing patched vendor EROFS from recovery raw...')
        vendor_stock.write_bytes(pi.reconstruct_vendor_erofs_bytes(raw))
    q_stock = shlex.quote(win_to_wsl(vendor_stock))

    system_off = pi.find_super_subpartition_offset(raw, 'system_a')
    q_mesa = shlex.quote(mesa_out)
    q_vend = shlex.quote(vend)
    q_stage = shlex.quote(stage)
    q_strip = shlex.quote(ndk_strip)
    q_raw = shlex.quote(win_to_wsl(raw))
    q_out = shlex.quote(win_to_wsl(out))

    copies = '\n'.join(
        f'install -D -m 0644 {q_mesa}/{shlex.quote(src)} {q_stage}/{shlex.quote(dst)}\n'
        f'if [ -x {q_strip} ]; then {q_strip} {q_stage}/{shlex.quote(dst)}; '
        f'elif command -v llvm-strip >/dev/null 2>&1; then llvm-strip {q_stage}/{shlex.quote(dst)}; fi'
        for src, dst in MESA_LIBS
    )
    script = f'''
if [ ! -d {q_mesa} ]; then
  echo "Missing WSL prerequisites: expected Mesa Android build at {mesa_out}" >&2
  exit 2
fi
if [ ! -d {q_vend} ] || [ ! -f {q_vend}/build.prop ]; then
  echo "Unpacking vendor tree from {q_stock} to {vend} in WSL..."
  rm -rf {q_vend}
  mkdir -p {q_vend}
  fsck.erofs --extract={q_vend} {q_stock} >/dev/null
fi
# vendor_file_contexts alone leaves most files unlabeled; the vendor_file default rule lives in plat_file_contexts.
rm -rf /root/plat_fc
fsck.erofs --offset={system_off} --extract=/root/plat_fc --path=/system/etc/selinux/plat_file_contexts {q_raw} >/dev/null
cat /root/plat_fc {q_vend}/etc/selinux/vendor_file_contexts > /root/file_contexts.all
rm -rf {q_stage}
cp -a {q_vend} {q_stage}
{copies}
sed -i 's/^ro\\.hardware\\.egl=.*/ro.hardware.egl=mesa/' {q_stage}/build.prop
grep -q '^ro.hardware.egl=mesa' {q_stage}/build.prop
rm -f /root/vendor-virgl.erofs
mkfs.erofs -zlz4hc,12 -C65536 -T1230768000 --mount-point=/vendor \\
  --file-contexts=/root/file_contexts.all /root/vendor-virgl.erofs {q_stage} >/root/mkfs.log 2>&1 || (tail -20 /root/mkfs.log; exit 1)
cp /root/vendor-virgl.erofs {q_out}
'''
    wsl(distro, script)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--skip-erofs', action='store_true', help='Reuse an existing build/vendor-virgl.erofs')
    ap.add_argument('--wsl-distro', default=DEFAULT_WSL_DISTRO, help=f'WSL distro name (default: {DEFAULT_WSL_DISTRO})')
    ap.add_argument('--mesa-out', default=DEFAULT_MESA_OUT, help=f'WSL path to Mesa build output (default: {DEFAULT_MESA_OUT})')
    ap.add_argument('--vendor-tree', default=DEFAULT_VEND, help=f'WSL path to unpacked vendor tree (default: {DEFAULT_VEND})')
    ap.add_argument('--stage-dir', default=DEFAULT_STAGE, help=f'WSL staging directory (default: {DEFAULT_STAGE})')
    ap.add_argument('--ndk-strip', default=DEFAULT_NDK_STRIP, help='WSL path to Android NDK llvm-strip')
    args = ap.parse_args()

    erofs = pi.BUILD / 'vendor-virgl.erofs'
    base = pi.PREPARED / 'base.qcow2'
    overlay = pi.PREPARED / 'base-virgl.qcow2'
    raw = pi.find_recovery_raw()
    if not raw or not base.is_file():
        print('Error: recovery raw or prepared/base.qcow2 missing; run install.ps1 first.', file=sys.stderr)
        return 1

    pi.BUILD.mkdir(parents=True, exist_ok=True)
    if not args.skip_erofs:
        print(f'[1/2] Building vendor EROFS with Mesa VirGL in WSL ({args.wsl_distro})...')
        build_erofs(erofs, raw, args.wsl_distro, args.mesa_out, args.vendor_tree, args.stage_dir, args.ndk_strip)
    elif not erofs.is_file():
        print(f'Error: {erofs} not found; omit --skip-erofs to build it in WSL first.', file=sys.stderr)
        return 1

    new_size = erofs.stat().st_size
    print(f'      {erofs.name}: {new_size / 1048576:.1f} MiB')

    print(f'[2/2] Writing {overlay.name} (overlay on {base.name})...')
    pi.write_virgl_overlay(raw, erofs, base, overlay)
    print(f'Done: {overlay}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

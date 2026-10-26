#!/usr/bin/env python3
"""Builds a GBVENDOR variant with Mesa VirGL (GLES) and a qcow2 overlay of prepared/base.qcow2 that uses it.

Requires WSL (distro 'Ubuntu') with the vendor tree at /root/vend and the Mesa build at /root/build/out.
Outputs: build/vendor-virgl.erofs and prepared/base-virgl.qcow2 (backed by prepared/base.qcow2).
"""
import argparse
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import prepare_image as pi  # noqa: E402

WSL_DISTRO = 'Ubuntu'
MESA_OUT = '/root/build/out'
VEND = '/root/vend'
STAGE = '/root/vend-virgl'
NDK_STRIP = '/root/build/android-ndk-r27c/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip'

# (Mesa build artifact, path inside the vendor tree)
MESA_LIBS = [
    ('src/gallium/targets/dri/libgallium_dri.so', 'lib64/libgallium_dri.so'),
    ('src/egl/libEGL.so', 'lib64/egl/libEGL_mesa.so'),
    ('src/mesa/glapi/es1api/libGLESv1_CM.so', 'lib64/egl/libGLESv1_CM_mesa.so'),
    ('src/mesa/glapi/es2api/libGLESv2.so', 'lib64/egl/libGLESv2_mesa.so'),
]


def wsl(script: str) -> str:
    r = subprocess.run(['wsl', '-d', WSL_DISTRO, '-u', 'root', '-e', 'bash', '-ec', script],
                       capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        raise RuntimeError(f"WSL step failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r.stdout


def win_to_wsl(p: pathlib.Path) -> str:
    return f"/mnt/{p.drive.rstrip(':').lower()}/" + '/'.join(p.parts[1:])


def build_erofs(out: pathlib.Path, raw: pathlib.Path) -> None:
    system_off = pi.find_super_subpartition_offset(raw, 'system_a')
    copies = '\n'.join(
        f'install -D -m 0644 {MESA_OUT}/{src} {STAGE}/{dst}\n{NDK_STRIP} {STAGE}/{dst}' for src, dst in MESA_LIBS)
    script = f'''
# vendor_file_contexts alone leaves most files unlabeled; the vendor_file default rule lives in plat_file_contexts.
rm -rf /root/plat_fc
fsck.erofs --offset={system_off} --extract=/root/plat_fc --path=/system/etc/selinux/plat_file_contexts {win_to_wsl(raw)} >/dev/null
cat /root/plat_fc {VEND}/etc/selinux/vendor_file_contexts > /root/file_contexts.all
rm -rf {STAGE}
cp -a {VEND} {STAGE}
{copies}
sed -i 's/^ro\\.hardware\\.egl=.*/ro.hardware.egl=mesa/' {STAGE}/build.prop
grep -q '^ro.hardware.egl=mesa' {STAGE}/build.prop
rm -f /root/vendor-virgl.erofs
mkfs.erofs -zlz4hc,12 -C65536 -T1230768000 --mount-point=/vendor \\
  --file-contexts=/root/file_contexts.all /root/vendor-virgl.erofs {STAGE} >/root/mkfs.log 2>&1 || (tail -20 /root/mkfs.log; exit 1)
cp /root/vendor-virgl.erofs {win_to_wsl(out)}
'''
    wsl(script)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--skip-erofs', action='store_true', help='Reuse an existing build/vendor-virgl.erofs')
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
        print('[1/2] Building vendor EROFS with Mesa VirGL in WSL...')
        build_erofs(erofs, raw)
    new_size = erofs.stat().st_size
    print(f'      {erofs.name}: {new_size / 1048576:.1f} MiB')

    print(f'[2/2] Writing {overlay.name} (overlay on {base.name})...')
    pi.write_virgl_overlay(raw, erofs, base, overlay)
    print(f'Done: {overlay}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

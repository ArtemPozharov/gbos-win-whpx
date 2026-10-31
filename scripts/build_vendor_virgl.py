#!/usr/bin/env python3
"""Builds a GBVENDOR variant with Mesa VirGL (GLES) and a qcow2 overlay of prepared/base.qcow2 that uses it.

Requires WSL with any Ubuntu/Debian-style distro (auto-detected: Ubuntu, Ubuntu-24.04, Ubuntu-26.04, Debian, ...).
Outputs: build/vendor-virgl.erofs and prepared/base-virgl.qcow2 (backed by prepared/base.qcow2).
"""
import argparse
import os
import pathlib
import shlex
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import prepare_image as pi  # noqa: E402

DEFAULT_MESA_TAR = pi.ASSETS / 'mesa-virgl.tar.gz'
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


# Bump when the vendor-virgl recipe changes so install.ps1 rebuilds stale overlays.
# 2: no CPU Vulkan/ANGLE (fixes blank Chrome/YouTube/Gmail), Bluetooth disabled.
# 3: bundled plat_file_contexts.zlib (fixes Ubuntu 24.04 fsck.erofs --offset), SetupWizard partner provider kept.
# 4: unblock ADB over TCP (ro.vendor.adbd.unsafe=1) & enable fast DNS.
# 5: fix Settings Bluetooth NPE crash by keeping BluetoothAdapter non-null.
VIRGL_RECIPE = 5

# Utility distros that cannot run apt-get / mkfs.erofs.
_SKIP_DISTROS = ('docker-desktop', 'rancher-desktop', 'podman')

NO_BLUETOOTH_XML = '''<?xml version="1.0" encoding="utf-8"?>
<permissions>
    <unavailable-feature name="android.hardware.bluetooth" />
    <unavailable-feature name="android.hardware.bluetooth_le" />
</permissions>
'''


def list_wsl_distros() -> list[tuple[str, bool]]:
    """Return [(name, is_default)] of installed WSL distros (handles both UTF-8 and UTF-16LE wsl.exe output)."""
    try:
        r = subprocess.run(['wsl', '-l', '-q'], capture_output=True, env={**os.environ, 'WSL_UTF8': '1'})
        rv = subprocess.run(['wsl', '-l', '-v'], capture_output=True, env={**os.environ, 'WSL_UTF8': '1'})
    except FileNotFoundError:
        return []

    def decode(b: bytes) -> str:
        if b.count(b'\x00') > len(b) // 4:
            return b.decode('utf-16le', errors='ignore')
        return b.decode('utf-8', errors='ignore')

    names = [n.strip().strip('\x00') for n in decode(r.stdout).splitlines()]
    names = [n for n in names if n]
    default = None
    for line in decode(rv.stdout).splitlines():
        line = line.strip()
        if line.startswith('*'):
            parts = line[1:].split()
            if parts:
                default = parts[0]
    return [(n, n == default) for n in names]


def detect_wsl_distro() -> str | None:
    """Pick a usable WSL distro: prefer Ubuntu*, then Debian*, then the default, then anything else."""
    distros = [(n, d) for n, d in list_wsl_distros() if not n.lower().startswith(_SKIP_DISTROS)]
    if not distros:
        return None
    for prefix in ('ubuntu', 'debian'):
        hits = [n for n, d in distros if n.lower().startswith(prefix)]
        if hits:
            # Prefer the default distro among matches, otherwise the newest-looking name.
            default_hits = [n for n, d in distros if d and n in hits]
            return default_hits[0] if default_hits else sorted(hits)[-1]
    default = [n for n, d in distros if d]
    return default[0] if default else distros[0][0]


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
    mesa_tar: pathlib.Path | None,
    mesa_out: str | None,
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
    plat_fc_zlib = pi.ASSETS / 'plat_file_contexts.zlib'
    q_plat_fc_zlib = shlex.quote(win_to_wsl(plat_fc_zlib)) if plat_fc_zlib.is_file() else "''"
    q_vend = shlex.quote(vend)
    q_stage = shlex.quote(stage)
    q_raw = shlex.quote(win_to_wsl(raw))
    q_out = shlex.quote(win_to_wsl(out))

    if mesa_tar and mesa_tar.is_file():
        q_tar = shlex.quote(win_to_wsl(mesa_tar))
        install_mesa_cmd = f'tar -xzf {q_tar} -C {q_stage}/lib64'
    elif mesa_out:
        q_mesa = shlex.quote(mesa_out)
        q_strip = shlex.quote(ndk_strip)
        copies = '\n'.join(
            f'install -D -m 0644 {q_mesa}/{shlex.quote(src)} {q_stage}/{shlex.quote(dst)}\n'
            f'if [ -x {q_strip} ]; then {q_strip} {q_stage}/{shlex.quote(dst)}; '
            f'elif command -v llvm-strip >/dev/null 2>&1; then llvm-strip {q_stage}/{shlex.quote(dst)}; fi'
            for src, dst in MESA_LIBS
        )
        install_mesa_cmd = f'''
if [ ! -d {q_mesa} ]; then
  echo "Missing WSL prerequisites: expected Mesa Android build at {mesa_out}" >&2
  exit 2
fi
{copies}'''
    else:
        raise ValueError("Neither mesa_tar nor mesa_out provided")

    script = f'''
# Ensure erofs-utils is available
if ! command -v mkfs.erofs >/dev/null 2>&1 || ! command -v fsck.erofs >/dev/null 2>&1; then
  echo "Installing erofs-utils in WSL..."
  apt-get update -qq && apt-get install -y -qq erofs-utils
fi
if [ ! -d {q_vend} ] || [ ! -f {q_vend}/build.prop ]; then
  echo "Unpacking vendor tree from {q_stock} to {vend} in WSL..."
  rm -rf {q_vend}
  mkdir -p {q_vend}
  fsck.erofs --extract={q_vend} {q_stock} >/dev/null
fi
# vendor_file_contexts alone leaves most files unlabeled; the vendor_file default rule lives in plat_file_contexts.
rm -rf /root/plat_fc
if [ -n {q_plat_fc_zlib} ] && [ -f {q_plat_fc_zlib} ]; then
  python3 -c "import zlib; open('/root/plat_fc', 'wb').write(zlib.decompress(open('{q_plat_fc_zlib}', 'rb').read()))"
elif fsck.erofs --help 2>&1 | grep -q -- '--offset'; then
  fsck.erofs --offset={system_off} --extract=/root/plat_fc --path=/system/etc/selinux/plat_file_contexts {q_raw} >/dev/null
else
  LOOPDEV=$(losetup -f -r -o {system_off} {q_raw} --show)
  fsck.erofs --extract=/root/plat_fc --path=/system/etc/selinux/plat_file_contexts "$LOOPDEV" >/dev/null
  losetup -d "$LOOPDEV"
fi
cat /root/plat_fc {q_vend}/etc/selinux/vendor_file_contexts > /root/file_contexts.all
rm -rf {q_stage}
cp -a {q_vend} {q_stage}
{install_mesa_cmd}
# GLES via Mesa VirGL on the host GPU.
sed -i 's/^ro\\.hardware\\.egl=.*/ro.hardware.egl=mesa/' {q_stage}/build.prop
grep -q '^ro.hardware.egl=mesa' {q_stage}/build.prop
# Drop the CPU Vulkan ICDs (SwiftShader 'pastel' + Intel ANV). Otherwise Chrome's GPU process (and every
# Chrome/TWA app: YouTube, Gmail) picks ANGLE-on-SwiftShader-Vulkan, renders into buffers that never reach the
# host VirGL resources and the windows flicker black/white with no content.
rm -f {q_stage}/lib64/hw/vulkan.pastel.so {q_stage}/lib64/hw/vulkan.intel.so
rm -f {q_stage}/etc/permissions/android.hardware.vulkan.compute.xml \\
      {q_stage}/etc/permissions/android.hardware.vulkan.level.xml \\
      {q_stage}/etc/permissions/android.hardware.vulkan.version.xml \\
      {q_stage}/etc/permissions/android.software.vulkan.deqp.level.xml
sed -i -e '/^ro\\.hardware\\.vulkan=/d' \\
       -e 's/^ro\\.hwui\\.use_vulkan=.*/ro.hwui.use_vulkan=false/' \\
       -e 's/^ro\\.gfx\\.angle\\.supported=.*/ro.gfx.angle.supported=false/' \\
       -e 's/^debug\\.renderengine\\.graphite_desktop_optin=.*/debug.renderengine.graphite_desktop_optin=false/' \\
       -e 's/^ro\\.surface_flinger\\.has_wide_color_display=.*/ro.surface_flinger.has_wide_color_display=false/' \\
       -e 's/^ro\\.surface_flinger\\.has_HDR_display=.*/ro.surface_flinger.has_HDR_display=false/' \\
       {q_stage}/build.prop
! grep -q '^ro.hardware.vulkan=' {q_stage}/build.prop
# QEMU has no Bluetooth HCI: disable the HAL and the feature, so com.google.android.bluetooth doesn't crash-loop.
# (Files are overwritten rather than deleted: /oem/init.gbrunch-vm.rc bind-mounts over the same paths.)
rm -f {q_stage}/etc/init/bluetooth-service-desktop.rc
printf '<manifest version="9.0" type="device"/>\\n' > {q_stage}/etc/vintf/manifest/bluetooth-service-desktop.xml
cat > {q_stage}/etc/permissions/android.hardware.bluetooth.xml <<'GBXML'
{NO_BLUETOOTH_XML}GBXML
cp {q_stage}/etc/permissions/android.hardware.bluetooth.xml {q_stage}/etc/permissions/android.hardware.bluetooth_le.xml
rm -f /root/vendor-virgl.erofs
mkfs.erofs -zlz4hc,12 -C65536 -T1230768000 --mount-point=/vendor \\
  --file-contexts=/root/file_contexts.all /root/vendor-virgl.erofs {q_stage} >/root/mkfs.log 2>&1 || (tail -20 /root/mkfs.log; exit 1)
cp /root/vendor-virgl.erofs {q_out}
'''
    wsl(distro, script)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--skip-erofs', action='store_true', help='Reuse an existing build/vendor-virgl.erofs')
    ap.add_argument('--wsl-distro', default=None, help='WSL distro name (default: auto-detect Ubuntu*/Debian*)')
    ap.add_argument('--mesa-tar', type=pathlib.Path, default=DEFAULT_MESA_TAR if DEFAULT_MESA_TAR.is_file() else None,
                    help=f'Path to prebuilt mesa-virgl.tar.gz archive (default: {DEFAULT_MESA_TAR})')
    ap.add_argument('--mesa-out', default=None, help='WSL path to custom Mesa build output directory')
    ap.add_argument('--vendor-tree', default=DEFAULT_VEND, help=f'WSL path to unpacked vendor tree (default: {DEFAULT_VEND})')
    ap.add_argument('--stage-dir', default=DEFAULT_STAGE, help=f'WSL staging directory (default: {DEFAULT_STAGE})')
    ap.add_argument('--ndk-strip', default=DEFAULT_NDK_STRIP, help='WSL path to Android NDK llvm-strip')
    ap.add_argument('--if-outdated', action='store_true',
                    help='Do nothing if prepared/base-virgl.qcow2 was already built with the current recipe')
    args = ap.parse_args()

    erofs = pi.BUILD / 'vendor-virgl.erofs'
    base = pi.PREPARED / 'base.qcow2'
    overlay = pi.PREPARED / 'base-virgl.qcow2'
    stamp = pi.BUILD / 'vendor-virgl.recipe'
    raw = pi.find_recovery_raw()
    if not raw or not base.is_file():
        print('Error: recovery raw or prepared/base.qcow2 missing; run install.ps1 first.', file=sys.stderr)
        return 1
    if args.if_outdated and overlay.is_file() and stamp.is_file() and stamp.read_text().strip() == str(VIRGL_RECIPE):
        print(f'{overlay.name} is up to date (recipe {VIRGL_RECIPE}).')
        return 0

    pi.BUILD.mkdir(parents=True, exist_ok=True)
    if not args.skip_erofs:
        distro = args.wsl_distro or detect_wsl_distro()
        if not distro:
            print('Error: no WSL Linux distro found. Install one with: wsl --install -d Ubuntu', file=sys.stderr)
            return 1
        print(f'[1/2] Building vendor EROFS with Mesa VirGL in WSL ({distro})...')
        build_erofs(erofs, raw, distro, args.mesa_tar, args.mesa_out, args.vendor_tree, args.stage_dir, args.ndk_strip)
        stamp.write_text(f'{VIRGL_RECIPE}\n')
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

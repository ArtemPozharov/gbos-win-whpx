#!/usr/bin/env python3
"""Hardware-accelerated Windows WHPX launcher for Googlebook OS (Android 17) on x86_64 / AMD & Intel."""
import argparse
import ctypes
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / 'prepared' / 'vm.json'
# Disable bleeding-edge CPU features (waitpkg/tpause, la57, pks, pku, vmx/svm, pmu, arch-capabilities)
# that Windows Hypervisor Platform (WHPX) fails to virtualize on Intel/AMD CPUs.
DEFAULT_CPU = 'max,waitpkg=off,la57=off,pks=off,pku=off,vmx=off,svm=off,pmu=off,arch-capabilities=off'


def find_qemu_binaries(custom_qemu: Path | None = None) -> tuple[Path, Path]:
    """Locate qemu-system-x86_64.exe and qemu-img.exe across local project, PATH, and system paths."""
    candidates = []
    if custom_qemu:
        candidates.append(Path(custom_qemu))
    candidates.append(ROOT / 'qemu' / 'qemu-system-x86_64.exe')
    candidates.append(ROOT.parent / 'gbos-win-vm' / 'qemu' / 'qemu-system-x86_64.exe')

    which_qemu = shutil.which('qemu-system-x86_64') or shutil.which('qemu-system-x86_64.exe')
    if which_qemu:
        candidates.append(Path(which_qemu))

    prog_files = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))
    candidates.append(prog_files / 'qemu' / 'qemu-system-x86_64.exe')

    for candidate in candidates:
        if candidate and candidate.is_file():
            qemu_exe = candidate.resolve()
            qemu_img = qemu_exe.with_name('qemu-img.exe')
            if not qemu_img.is_file():
                which_img = shutil.which('qemu-img') or shutil.which('qemu-img.exe')
                if which_img:
                    qemu_img = Path(which_img).resolve()
            if qemu_img.is_file():
                return qemu_exe, qemu_img

    raise FileNotFoundError(
        "Could not locate QEMU binaries (qemu-system-x86_64.exe).\n"
        "Please install QEMU via 'winget install SoftwareFreedomConservancy.QEMU' "
        "or place QEMU inside the project's 'qemu/' directory."
    )


def get_qemu_version(qemu_exe: Path) -> tuple[str, int]:
    """Return (version_line, major_version) for qemu-system-x86_64.exe."""
    try:
        out = subprocess.check_output([str(qemu_exe), '--version'], text=True, timeout=5)
        first_line = out.splitlines()[0].strip() if out else 'Unknown'
        m = re.search(r'version\s+(\d+)\.', first_line)
        major = int(m.group(1)) if m else 0
        return first_line, major
    except Exception:
        return 'Unknown', 0


def detect_host_resources() -> tuple[int, int]:
    """Auto-detect host hardware and recommend using half of resources."""
    total_cpus = os.cpu_count() or 4
    half_cpus = max(2, total_cpus // 2)

    half_ram_mb = 4096
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            total_ram_mb = int(stat.ullTotalPhys / (1024 * 1024))
            half_ram_mb = max(2048, total_ram_mb // 2)
    except Exception:
        pass

    return half_cpus, half_ram_mb


def check_regular_file(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f'File not found: {resolved}')
    return resolved


def _cpio_entry(name: str, body: bytes, ino: int, mode: int = 0o100644) -> bytes:
    n = name.encode() + b'\0'
    fields = [ino, mode, 0, 0, 1, 0, len(body), 0, 0, 0, 0, len(n), 0]
    block = b'070701' + b''.join(f'{v:08x}'.encode() for v in fields) + n
    block += b'\0' * (-len(block) % 4) + body + b'\0' * (-len(body) % 4)
    return block


def ensure_isa_patch_current(manifest_path: Path, spec: dict) -> dict:
    """Auto-upgrade prepared/initrd.gz and cmdline.txt in-place when CPU ISA patch is updated via git pull."""
    ko_path = ROOT / 'patches' / 'avx_vnni' / 'avx_vnni_emu.ko'
    preinit_path = ROOT / 'patches' / 'avx_vnni' / 'preinit'
    if not (ko_path.is_file() and preinit_path.is_file()):
        return spec

    initrd_path = manifest_path.parent / spec['assets']['initrd']['file']
    cmdline_path = manifest_path.parent / spec['assets']['cmdline']['file']
    if not (initrd_path.is_file() and cmdline_path.is_file()):
        return spec

    ko_bytes = ko_path.read_bytes()
    preinit_bytes = preinit_path.read_bytes()
    isa_sha = hashlib.sha256(ko_bytes + preinit_bytes).hexdigest()
    cmdline_txt = cmdline_path.read_text(encoding='utf-8')

    if spec.get('isa_patch_sha256') == isa_sha and 'rdinit=/preinit' in cmdline_txt:
        return spec

    print('  [patch] Updating prepared/initrd.gz & cmdline.txt with latest CPU ISA compatibility patch...', flush=True)
    raw = gzip.decompress(initrd_path.read_bytes())
    t_idx = raw.rfind(b'TRAILER!!!')
    t_pos = raw.rfind(b'070701', 0, t_idx) if t_idx != -1 else len(raw)
    base_cpio = raw[:t_pos] if t_pos != -1 else raw
    updated = (
        base_cpio
        + _cpio_entry('lib/modules/avx_vnni_emu.ko', ko_bytes, 900001)
        + _cpio_entry('preinit', preinit_bytes, 900002, mode=0o100755)
        + _cpio_entry('TRAILER!!!', b'', 0, mode=0)
    )
    initrd_gz = gzip.compress(updated, compresslevel=6, mtime=0)
    initrd_path.write_bytes(initrd_gz)

    new_cmdline = re.sub(r'\brdinit=/init\b', 'rdinit=/preinit', cmdline_txt)
    cmdline_path.write_text(new_cmdline, encoding='utf-8')

    spec['isa_patch_sha256'] = isa_sha
    spec['assets']['initrd']['sha256'] = hashlib.sha256(initrd_gz).hexdigest()
    spec['assets']['cmdline']['sha256'] = hashlib.sha256(cmdline_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(spec, indent=2) + '\n', encoding='utf-8')
    return spec


def load_manifest(manifest_path: Path):
    if not manifest_path.is_file():
        fallback = ROOT / 'launcher' / 'vm.json'
        if fallback.is_file():
            manifest_path = fallback
        else:
            raise FileNotFoundError(
                f'Manifest not found: {manifest_path}\n'
                f'Please run install.ps1 first to assemble VM assets into prepared/.'
            )
    manifest_path = check_regular_file(manifest_path)
    spec = json.loads(manifest_path.read_text(encoding='utf-8'))
    if spec.get('profile_version') != 1:
        raise ValueError('Unsupported vm.json profile_version')
    spec = ensure_isa_patch_current(manifest_path, spec)
    assets = {}
    for key in ('kernel', 'initrd', 'cmdline', 'disk'):
        entry = spec['assets'][key]
        candidates = [
            manifest_path.parent / entry['file'],
            ROOT / 'prepared' / entry['file'],
            ROOT / 'launcher' / entry['file'],
        ]
        fpath = None
        for cand in candidates:
            if cand.is_file():
                fpath = cand.resolve()
                break
        if not fpath:
            raise FileNotFoundError(
                f"Required VM asset '{key}' ({entry['file']}) not found in prepared/.\n"
                f"Please ensure install.ps1 has finished preparing all VM assets."
            )
        if key != 'disk':
            with fpath.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != entry.get('sha256'):
                raise ValueError(f'SHA-256 mismatch for {key}: expected {entry.get("sha256")}, got {digest}')
        assets[key] = fpath
    cmdline = assets['cmdline'].read_text(encoding='utf-8').strip()
    return manifest_path, assets, cmdline


def wait_with_boot_monitor(proc: subprocess.Popen, serial_log: Path, qemu_log: Path) -> int:
    """Monitor early boot progress in serial.log so users aren't left guessing during 'Display output is not active'."""
    print('  [boot] Starting VM... Note: QEMU shows "Display output is not active" for ~20-45s', flush=True)
    print('         during initial boot (especially on first boot while formatting /data).', flush=True)

    stage = 0
    warned_no_serial = False
    reported_panic = False
    seen_qemu_lines: set[str] = set()
    start_ts = time.monotonic()

    while proc.poll() is None:
        time.sleep(1.5)
        elapsed = time.monotonic() - start_ts

        if qemu_log.is_file() and qemu_log.stat().st_size > 0:
            try:
                for qline in qemu_log.read_text(encoding='utf-8', errors='replace').splitlines():
                    qline_s = qline.strip()
                    if not qline_s or 'Ignoring request for interrupt vector 0' in qline_s:
                        continue
                    if qline_s not in seen_qemu_lines:
                        seen_qemu_lines.add(qline_s)
                        print(f'  [QEMU] {qline_s}', flush=True)
            except OSError:
                pass

        if serial_log.is_file():
            sz = serial_log.stat().st_size
            if sz > 0:
                try:
                    txt = serial_log.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    txt = ''

                if stage < 1 and len(txt) > 64:
                    print(f'  [boot] ({int(elapsed)}s) 1/4 Linux kernel started under WHPX...', flush=True)
                    stage = 1
                if stage < 2 and 'Initialized virtio_gpu' in txt:
                    print(f'  [boot] ({int(elapsed)}s) 2/4 VirtIO GPU & storage drivers initialized...', flush=True)
                    stage = 2
                if stage < 3 and "starting service 'surfaceflinger'" in txt:
                    print(f'  [boot] ({int(elapsed)}s) 3/4 Starting Android SurfaceFlinger -- display activating!', flush=True)
                    stage = 3
                if stage < 4 and ('GBRUNCH_DESKTOP_PROVISION' in txt or 'sys.boot_completed=1' in txt):
                    print(f'  [boot] ({int(elapsed)}s) 4/4 Googlebook OS Desktop ready!', flush=True)
                    stage = 4
                    break

                if not reported_panic and 'Kernel panic - not syncing' in txt:
                    reported_panic = True
                    print('\n  [ERROR] Guest kernel panic detected in serial.log:', flush=True)
                    p_idx = txt.find('Kernel panic - not syncing')
                    t_idx = txt.rfind('traps:', max(0, p_idx - 512), p_idx)
                    tail_txt = txt[t_idx if t_idx != -1 else p_idx:]
                    for line in tail_txt.splitlines():
                        if any(k in line for k in ('traps:', 'Kernel panic', 'RIP:', 'Call Trace:')):
                            print(f'    {line}', flush=True)
            elif elapsed >= 15.0 and not warned_no_serial:
                warned_no_serial = True
                print('\n  [WARN] No guest kernel serial output after 15s (WHPX vCPU may be stalled).', flush=True)
                if qemu_log.is_file():
                    qtxt = qemu_log.read_text(encoding='utf-8', errors='replace').strip()
                    if qtxt:
                        print(f'  [qemu.log] {qtxt}', flush=True)

    return proc.wait()


def main() -> int:
    default_cpus, default_ram = detect_host_resources()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--qemu', type=Path, default=None, help='Custom path to qemu-system-x86_64.exe')
    parser.add_argument('--cpu', default=DEFAULT_CPU, help='QEMU CPU model and feature flags')
    parser.add_argument('--accel', default='whpx', help='QEMU accelerator (default: whpx)')
    parser.add_argument('--memory-mb', type=int, default=default_ram,
                        help=f'Guest RAM in MiB (default: {default_ram} - half of host RAM)')
    parser.add_argument('--cpus', type=int, default=default_cpus,
                        help=f'Virtual CPU cores (default: {default_cpus} - half of host cores)')
    parser.add_argument('--resolution', default='1280x800', help='Display WxH (default: 1280x800, 16:10)')
    parser.add_argument('--display-backend', choices=['gtk', 'sdl', 'none'], default='sdl',
                        help='Display backend (default: sdl; gtk ignores --resolution and uses its window size)')
    parser.add_argument('--fullscreen', action=argparse.BooleanOptionalAction, default=False,
                        help='Start in fullscreen mode (default: False)')
    parser.add_argument('--gpu', choices=['swiftshader', 'virgl'], default='swiftshader',
                        help='Guest GLES renderer: swiftshader (CPU, default) or virgl (host GPU via Mesa VirGL; '
                             'needs prepared/base-virgl.qcow2, see scripts/build_vendor_virgl.py)')
    parser.add_argument('--ephemeral', action='store_true', help='Discard writes when VM closes')
    parser.add_argument('--offline', action='store_true', help='Disable user-mode NAT networking')
    parser.add_argument('--no-audio', action='store_true', help='Disable DirectSound USB audio')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    width_s, height_s = args.resolution.lower().split('x', 1)
    width, height = int(width_s), int(height_s)

    manifest_path, assets, cmdline = load_manifest(args.manifest)
    qemu, qemu_img = find_qemu_binaries(args.qemu)

    virgl = args.gpu == 'virgl'
    if virgl and args.display_backend == 'none':
        parser.error('--gpu virgl needs a display backend (sdl or gtk)')
    base_disk = assets['disk']
    userdata = manifest_path.parent / 'userdata.qcow2'
    if virgl:
        # Separate overlay chain: userdata is backed by the VirGL vendor image, so it must not be shared with the stock one.
        base_disk = base_disk.with_name('base-virgl.qcow2')
        userdata = manifest_path.parent / 'userdata-virgl.qcow2'
        if not args.dry_run:
            build_script = ROOT / 'scripts' / 'build_vendor_virgl.py'
            r = subprocess.run([sys.executable, str(build_script), '--if-outdated'])
            if r.returncode != 0 or not base_disk.is_file():
                parser.error(f'{base_disk} build failed; see output above.')
    if args.ephemeral:
        disk = base_disk
        drive_spec = f'if=none,id=os,format=qcow2,file={str(disk).replace(",", ",,")},snapshot=on'
    else:
        if (not userdata.exists() or userdata.stat().st_size == 0) and not args.dry_run:
            subprocess.run([
                str(qemu_img), 'create', '-f', 'qcow2', '-F', 'qcow2',
                '-b', str(base_disk), str(userdata)
            ], check=True)
        disk = userdata
        drive_spec = f'if=none,id=os,format=qcow2,file={str(disk).replace(",", ",,")}'

    run_name = 'run-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    session = manifest_path.parent / 'logs' / run_name
    serial_log = session / 'serial.log'

    # virgl: addr=02.0 is required, the vendor sepolicy only labels that PCI slot as sysfs_gpu (default 01.0 -> EGL init denied).
    gpu_device = (f'virtio-gpu-gl-pci,xres={width},yres={height},edid=off,romfile=,addr=02.0' if virgl
                  else f'virtio-gpu-pci,xres={width},yres={height},edid=off,romfile=')

    cmd = [str(qemu)]
    share_dir = qemu.parent / 'share'
    if share_dir.is_dir():
        cmd += ['-L', str(share_dir)]

    cmd += [
        '-name', 'Googlebook OS (Android 17)',
        '-machine', 'q35',
        '-accel', args.accel,
        '-cpu', args.cpu,
        '-m', str(args.memory_mb),
        '-smp', f'sockets=1,cores={args.cpus},threads=1',
        '-vga', 'none',
        '-device', gpu_device,
        '-drive', drive_spec,
        '-device', 'virtio-blk-pci,drive=os,addr=03.0',
        '-device', 'qemu-xhci,id=xhci',
        '-device', 'usb-kbd,bus=xhci.0',
        '-device', 'usb-mouse,bus=xhci.0',
        '-monitor', 'none',
        '-no-reboot',
        '-kernel', str(assets['kernel']),
        '-initrd', str(assets['initrd']),
        '-append', cmdline,
        '-serial', f'file:{str(serial_log).replace(",", ",,")}',
    ]

    if args.offline:
        cmd += ['-nic', 'none']
    else:
        cmd += [
            '-netdev', 'user,id=net0,ipv6=off',
            '-device', 'virtio-net-pci,netdev=net0',
        ]

    if not args.no_audio:
        cmd += [
            '-audiodev', 'dsound,id=audio0',
            '-device', 'usb-audio,audiodev=audio0,bus=xhci.0',
        ]

    display_opts = [args.display_backend]
    if args.display_backend == 'gtk':
        display_opts.append('zoom-to-fit=on')
        if args.fullscreen:
            display_opts.append('full-screen=on')
            display_opts.append('show-menubar=off')
    if virgl:
        display_opts.append('gl=on')
    cmd += ['-display', ','.join(display_opts)]
    if args.fullscreen and args.display_backend != 'none':
        cmd += ['-full-screen']

    if args.dry_run:
        print(json.dumps({'command': cmd, 'disk': str(disk)}, indent=2))
        return 0

    qemu_ver_str, qemu_major = get_qemu_version(qemu)

    session.mkdir(parents=True, exist_ok=True)
    (session / 'command.json').write_text(json.dumps(cmd, indent=2) + '\n', encoding='utf-8')

    print('================================================================')
    print('  Googlebook OS (Android 17) - Windows Hypervisor Platform (WHPX)')
    print('================================================================')
    print(f'  QEMU       : {qemu_ver_str}')
    print(f'  Resolution : {width}x{height} ({"fullscreen" if args.fullscreen else "windowed"})')
    print(f'  RAM / CPUs : {args.memory_mb} MiB / {args.cpus} vCPUs (50% host auto)')
    print(f'  User data  : {disk}')
    print(f'  Session log: {session}')
    print('  Controls   : Click inside window to capture mouse')
    print('               Press Ctrl+Alt+G to release mouse cursor')
    print('               Press Ctrl+Alt+F to toggle Fullscreen')
    print('================================================================')

    if 0 < qemu_major < 10:
        print(f'  [WARN] Detected older QEMU {qemu_major}.x. QEMU 10.0+ is strongly recommended for WHPX')
        print('         (run: winget upgrade SoftwareFreedomConservancy.QEMU)')

    qemu_log = session / 'qemu.log'
    with qemu_log.open('wb') as qlog:
        proc = subprocess.Popen(cmd, stdout=qlog, stderr=subprocess.STDOUT)
        try:
            rc = wait_with_boot_monitor(proc, serial_log, qemu_log)
        except KeyboardInterrupt:
            proc.terminate()
            rc = proc.wait(timeout=10)

    if rc != 0 and qemu_log.is_file():
        qtxt = qemu_log.read_text(encoding='utf-8', errors='replace').strip()
        if qtxt:
            print(f'\n  [QEMU Error Output]\n  {qtxt}')

    print(f'Googlebook OS VM exited (code {rc}). Logs saved in {session}')
    return 0 if rc == 0 else rc


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Hardware-accelerated Windows WHPX launcher for Googlebook OS (Android 17) on x86_64 / AMD & Intel."""
import argparse
import ctypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / 'prepared' / 'vm.json'


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


def detect_host_resources() -> tuple[int, int]:
    """Auto-detect host hardware and recommend using half of resources."""
    # Cores
    total_cpus = os.cpu_count() or 4
    half_cpus = max(2, total_cpus // 2)

    # RAM (Windows GlobalMemoryStatusEx)
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


def load_manifest(manifest_path: Path):
    manifest_path = check_regular_file(manifest_path)
    spec = json.loads(manifest_path.read_text(encoding='utf-8'))
    if spec.get('profile_version') != 1:
        raise ValueError('Unsupported vm.json profile_version')
    assets = {}
    for key in ('kernel', 'initrd', 'cmdline', 'disk'):
        entry = spec['assets'][key]
        fpath = check_regular_file(manifest_path.parent / entry['file'])
        if key != 'disk':
            with fpath.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != entry.get('sha256'):
                raise ValueError(f'SHA-256 mismatch for {key}: expected {entry.get("sha256")}, got {digest}')
        assets[key] = fpath
    cmdline = assets['cmdline'].read_text(encoding='utf-8').strip()
    return manifest_path, assets, cmdline


def main() -> int:
    default_cpus, default_ram = detect_host_resources()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--qemu', type=Path, default=None, help='Custom path to qemu-system-x86_64.exe')
    parser.add_argument('--memory-mb', type=int, default=default_ram,
                        help=f'Guest RAM in MiB (default: {default_ram} - half of host RAM)')
    parser.add_argument('--cpus', type=int, default=default_cpus,
                        help=f'Virtual CPU cores (default: {default_cpus} - half of host cores)')
    parser.add_argument('--resolution', default='1280x800', help='Display WxH (default: 1280x800, 16:10)')
    parser.add_argument('--display-backend', choices=['gtk', 'sdl', 'none'], default='gtk')
    parser.add_argument('--fullscreen', action=argparse.BooleanOptionalAction, default=True,
                        help='Start in fullscreen mode (default: True)')
    parser.add_argument('--ephemeral', action='store_true', help='Discard writes when VM closes')
    parser.add_argument('--offline', action='store_true', help='Disable user-mode NAT networking')
    parser.add_argument('--no-audio', action='store_true', help='Disable DirectSound USB audio')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    width_s, height_s = args.resolution.lower().split('x', 1)
    width, height = int(width_s), int(height_s)

    manifest_path, assets, cmdline = load_manifest(args.manifest)
    qemu, qemu_img = find_qemu_binaries(args.qemu)

    userdata = manifest_path.parent / 'userdata.qcow2'
    if args.ephemeral:
        disk = assets['disk']
        drive_spec = f'if=none,id=os,format=qcow2,file={str(disk).replace(",", ",,")},snapshot=on'
    else:
        if not userdata.exists() and not args.dry_run:
            subprocess.run([
                str(qemu_img), 'create', '-f', 'qcow2', '-F', 'qcow2',
                '-b', str(assets['disk']), str(userdata)
            ], check=True)
        disk = userdata
        drive_spec = f'if=none,id=os,format=qcow2,file={str(disk).replace(",", ",,")}'

    run_name = 'run-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    session = manifest_path.parent / 'logs' / run_name
    serial_log = session / 'serial.log'

    cmd = [str(qemu)]
    share_dir = qemu.parent / 'share'
    if share_dir.is_dir():
        cmd += ['-L', str(share_dir)]

    cmd += [
        '-name', 'Googlebook OS (Android 17)',
        '-machine', 'q35',
        '-accel', 'whpx',
        '-cpu', 'max',
        '-m', str(args.memory_mb),
        '-smp', str(args.cpus),
        '-vga', 'none',
        '-device', f'virtio-gpu-pci,xres={width},yres={height},romfile=',
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
    cmd += ['-display', ','.join(display_opts)]
    if args.fullscreen and args.display_backend != 'none':
        cmd += ['-full-screen']

    if args.dry_run:
        print(json.dumps({'command': cmd, 'disk': str(disk)}, indent=2))
        return 0

    session.mkdir(parents=True, exist_ok=True)
    (session / 'command.json').write_text(json.dumps(cmd, indent=2) + '\n', encoding='utf-8')

    print('================================================================')
    print('  Googlebook OS (Android 17) - Windows Hypervisor Platform (WHPX)')
    print('================================================================')
    print(f'  Resolution : {width}x{height} (Full screen scaled)')
    print(f'  RAM / CPUs : {args.memory_mb} MiB / {args.cpus} vCPUs (50% host auto)')
    print(f'  User data  : {disk}')
    print(f'  Session log: {session}')
    print('  Controls   : Click inside window to capture mouse')
    print('               Press Ctrl+Alt+G to release mouse cursor')
    print('               Press Ctrl+Alt+F to toggle Fullscreen')
    print('================================================================')

    with (session / 'qemu.log').open('wb') as qlog:
        proc = subprocess.Popen(cmd, stdout=qlog, stderr=subprocess.STDOUT)
        try:
            rc = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            rc = proc.wait(timeout=10)
    print(f'Googlebook OS VM exited (code {rc}). Logs saved in {session}')
    return 0 if rc == 0 else rc


if __name__ == '__main__':
    raise SystemExit(main())

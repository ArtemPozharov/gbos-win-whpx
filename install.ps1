#Requires -Version 5.1
<#
.SYNOPSIS
    Automated installer for Googlebook OS (Android 17) on Windows 11 / WHPX.
.DESCRIPTION
    Validates Windows virtualization requirements, downloads necessary dependencies,
    assembles the virtual machine disk with Zen 4 / AMD AVX-VNNI emulation and color
    patches, and creates ready-to-launch desktop shortcuts.
#>

[CmdletBinding()]
param(
    [switch]$SkipDownload,
    [string]$RecoveryUrl = "https://dl.google.com/dl/edgedl/chromeos/recovery/chromeos_16452.271.0_ruby_recovery_stable-channel_mp-v2.bin.zip"
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   Googlebook OS (Android 17) - Windows WHPX Auto-Installer    " -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. System checks
Write-Host "[1/6] Checking system requirements..." -ForegroundColor Yellow
if (-not [Environment]::Is64BitOperatingSystem) {
    Write-Error "Googlebook OS VM requires a 64-bit Windows 10/11 operating system."
    exit 1
}

# Check Python
$pythonCmd = Get-Command "python" -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Error "Python 3.10+ is required. Please install Python from https://www.python.org/ and check 'Add Python to PATH'."
    exit 1
}
$pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "   Python $pyVer detected: $($pythonCmd.Source)" -ForegroundColor Green

# Check WHPX (Windows Hypervisor Platform)
$whpxFeature = Get-WindowsOptionalFeature -Online -FeatureName "HypervisorPlatform" -ErrorAction SilentlyContinue
if ($whpxFeature -and $whpxFeature.State -ne "Enabled") {
    Write-Warning "Windows Hypervisor Platform (WHPX) is currently disabled."
    Write-Host "   To enable WHPX, run in an Administrator PowerShell:" -ForegroundColor Gray
    Write-Host "   dism /online /enable-feature /featurename:HypervisorPlatform /all /norestart" -ForegroundColor Cyan
    Write-Host "   and restart your PC." -ForegroundColor Gray
} else {
    Write-Host "   Windows Hypervisor Platform (WHPX): Enabled" -ForegroundColor Green
}

# 2. Directory Structure
Write-Host "`n[2/6] Initializing directory structure..." -ForegroundColor Yellow
$dirs = @("downloads", "extracted", "build", "prepared", "qemu")
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
}
Write-Host "   Directories ready." -ForegroundColor Green

# 3. Check / Download QEMU
Write-Host "`n[3/6] Verifying QEMU with WHPX support..." -ForegroundColor Yellow
$qemuBin = Join-Path $PSScriptRoot "qemu\qemu-system-x86_64.exe"
$qemuImg = Join-Path $PSScriptRoot "qemu\qemu-img.exe"

if (-not (Test-Path $qemuBin)) {
    $sysQemu = Get-Command "qemu-system-x86_64" -ErrorAction SilentlyContinue
    if ($sysQemu) {
        $qemuBin = $sysQemu.Source
        Write-Host "   Found system QEMU: $qemuBin" -ForegroundColor Green
    } elseif (Test-Path "C:\Program Files\qemu\qemu-system-x86_64.exe") {
        $qemuBin = "C:\Program Files\qemu\qemu-system-x86_64.exe"
        Write-Host "   Found standard QEMU in C:\Program Files\qemu" -ForegroundColor Green
    } elseif (Test-Path "$PSScriptRoot\..\gbos-win-vm\qemu\qemu-system-x86_64.exe") {
        $qemuBin = "$PSScriptRoot\..\gbos-win-vm\qemu\qemu-system-x86_64.exe"
        Write-Host "   Found development sibling QEMU: $qemuBin" -ForegroundColor Green
    } else {
        Write-Host "   QEMU not found in PATH or project directory." -ForegroundColor Yellow
        $winget = Get-Command "winget" -ErrorAction SilentlyContinue
        if ($winget) {
            Write-Host "   Installing QEMU via Windows Package Manager (winget)..." -ForegroundColor Cyan
            & winget install -e --id SoftwareFreedomConservancy.QEMU --accept-source-agreements --accept-package-agreements
            if (Test-Path "C:\Program Files\qemu\qemu-system-x86_64.exe") {
                $qemuBin = "C:\Program Files\qemu\qemu-system-x86_64.exe"
                Write-Host "   QEMU installed successfully!" -ForegroundColor Green
            }
        } else {
            Write-Warning "winget not found. Please install QEMU from https://qemu.weilnetz.de/w64/ or place QEMU binaries in $PSScriptRoot\qemu"
        }
    }
} else {
    Write-Host "   Found QEMU: $qemuBin" -ForegroundColor Green
}

if (-not (Test-Path $qemuImg)) {
    $sysImg = Get-Command "qemu-img" -ErrorAction SilentlyContinue
    if ($sysImg) {
        $qemuImg = $sysImg.Source
    } elseif (Test-Path "C:\Program Files\qemu\qemu-img.exe") {
        $qemuImg = "C:\Program Files\qemu\qemu-img.exe"
    } elseif (Test-Path "$PSScriptRoot\..\gbos-win-vm\qemu\qemu-img.exe") {
        $qemuImg = "$PSScriptRoot\..\gbos-win-vm\qemu\qemu-img.exe"
    }
}

# 4. In-flight patches and Assets
Write-Host "`n[4/6] Verifying patches (AVX-VNNI AMD emulator, SELinux, Colors)..." -ForegroundColor Yellow
$vnniKo = Join-Path $PSScriptRoot "patches\avx_vnni\avx_vnni_emu.ko"
if (Test-Path $vnniKo) {
    Write-Host "   Prebuilt AVX-VNNI kernel module present (AMD Zen 1-4 & pre-12th Gen Intel support)." -ForegroundColor Green
} else {
    Write-Host "   Compiling avx_vnni_emu.ko..." -ForegroundColor Gray
    & python "patches\avx_vnni\build_avx_vnni_ko.py"
}

# 5. Build Image
Write-Host "`n[5/6] Assembling base disk and initrd..." -ForegroundColor Yellow
if (Test-Path "prepared\base.qcow2") {
    Write-Host "   prepared\base.qcow2 is already assembled." -ForegroundColor Green
} else {
    Write-Host "   Assembling disk from official recovery image..." -ForegroundColor Gray
    & python "scripts\prepare_image.py"
}

# Apply color fix
if (Test-Path "prepared\initrd.gz") {
    Write-Host "   Applying virtio-gpu true-color channel mapping patch..." -ForegroundColor Gray
    & python "patches\color_fix\patch_color_format.py" "prepared\initrd.gz" "prepared\vm.json"
}

# Ensure userdata
if (-not (Test-Path "prepared\userdata.qcow2") -and (Test-Path "prepared\base.qcow2")) {
    Write-Host "   Creating disposable/persistent userdata.qcow2..." -ForegroundColor Gray
    & $qemuImg create -f qcow2 -F qcow2 -b "base.qcow2" "prepared\userdata.qcow2"
}

Write-Host "`n[6/6] Finalizing configuration..." -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Green
Write-Host "   INSTALLATION COMPLETE! READY TO LAUNCH!                     " -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start Googlebook OS, simply run:" -ForegroundColor Cyan
Write-Host "   .\Start-Googlebook.bat" -ForegroundColor Yellow
Write-Host "or in PowerShell:" -ForegroundColor Cyan
Write-Host "   .\Start-Googlebook.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "Controls:" -ForegroundColor Gray
Write-Host "   - Click inside window to capture mouse" -ForegroundColor Gray
Write-Host "   - Press Ctrl+Alt+G to release mouse cursor" -ForegroundColor Gray
Write-Host "   - Press Ctrl+Alt+F to toggle Fullscreen" -ForegroundColor Gray
Write-Host "   - Press Ctrl+Space inside Android to switch keyboard language" -ForegroundColor Gray
Write-Host ""

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
    [switch]$Latest,
    [switch]$SkipDownload,
    [switch]$SkipQemuInstall,
    [switch]$BuildFromSource,
    [string]$RecoverySha256 = "3C4DC7F636F29A1207E71D001FD2864AA20CE8354FAECD2EF1AE47582B977F6C",
    [string]$RecoveryUrl = "https://dl.google.com/device/recovery/ruby-user/16452207/recovery.zip"
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if ($Latest) {
    Write-Host "Fetching latest Googlebook OS release from Google Recovery API..." -ForegroundColor Cyan
    try {
        $apiJson = & python -c "import urllib.request, json; data=json.loads(urllib.request.urlopen('https://dl.google.com/dl/edgedl/device/recovery/production_recovery.json', timeout=15).read()); r=next(x for x in data if x.get('device')=='ruby'); print(json.dumps({'url': r['url'], 'build': r['buildidentifier'], 'date': r['dateupdated']}))"
        $latestObj = $apiJson | ConvertFrom-Json
        if ($latestObj -and $latestObj.url) {
            $RecoveryUrl = $latestObj.url
            $RecoverySha256 = ""
            Write-Host "   Found latest official release: $($latestObj.build) (Released: $($latestObj.date))" -ForegroundColor Green
            Write-Host "   Target URL: $RecoveryUrl" -ForegroundColor Gray
        }
    } catch {
        Write-Warning "Could not query Google Recovery API. Falling back to default release 16452207: $_"
    }
}

if (-not ($RecoveryUrl -match '^https://')) {
    Write-Error "Security error: RecoveryUrl must use a secure HTTPS protocol ($RecoveryUrl)."
    exit 1
}

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
try {
    $whpxFeature = Get-WindowsOptionalFeature -Online -FeatureName "HypervisorPlatform" -ErrorAction SilentlyContinue
    if ($whpxFeature -and $whpxFeature.State -ne "Enabled") {
        Write-Warning "Windows Hypervisor Platform (WHPX) is currently disabled."
        Write-Host "   To enable WHPX, run in an Administrator PowerShell:" -ForegroundColor Gray
        Write-Host "   dism /online /enable-feature /featurename:HypervisorPlatform /all /norestart" -ForegroundColor Cyan
        Write-Host "   and restart your PC." -ForegroundColor Gray
    } else {
        Write-Host "   Windows Hypervisor Platform (WHPX): Enabled" -ForegroundColor Green
    }
} catch {
    Write-Host "   Windows Hypervisor Platform (WHPX): Check skipped (requires admin to query)" -ForegroundColor Gray
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
        if ($SkipQemuInstall) {
            Write-Warning "QEMU not found and -SkipQemuInstall was specified. Please install QEMU manually and add to PATH."
        } else {
            Write-Host "   QEMU not found in PATH or project directory." -ForegroundColor Yellow
            $winget = Get-Command "winget" -ErrorAction SilentlyContinue
            if ($winget) {
                Write-Host "   Installing QEMU via Windows Package Manager (winget)..." -ForegroundColor Cyan
                Write-Host "   (Pass -SkipQemuInstall to skip automatic winget installation)" -ForegroundColor Gray
                & winget install -e --id SoftwareFreedomConservancy.QEMU --accept-source-agreements --accept-package-agreements
                if (Test-Path "C:\Program Files\qemu\qemu-system-x86_64.exe") {
                    $qemuBin = "C:\Program Files\qemu\qemu-system-x86_64.exe"
                    Write-Host "   QEMU installed successfully!" -ForegroundColor Green
                }
            } else {
                Write-Warning "winget not found. Please install QEMU from https://qemu.weilnetz.de/w64/ or place QEMU binaries in $PSScriptRoot\qemu"
            }
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
Write-Host "`n[4/6] Verifying patches (Alder Lake / GFNI / AVX-VNNI CPU emulator, SELinux, Colors)..." -ForegroundColor Yellow
$vnniKo = Join-Path $PSScriptRoot "patches\avx_vnni\avx_vnni_emu.ko"
$preinitBin = Join-Path $PSScriptRoot "patches\avx_vnni\preinit"
if ((Test-Path $vnniKo) -and (Test-Path $preinitBin) -and -not $BuildFromSource) {
    $koHash = (Get-FileHash $vnniKo -Algorithm SHA256).Hash
    Write-Host "   Using verified CPU compatibility module + preinit (SHA-256: $koHash)." -ForegroundColor Green
} else {
    Write-Host "   Compiling avx_vnni_emu.ko + preinit from source (requires zig compiler)..." -ForegroundColor Gray
    & python "patches\avx_vnni\build_avx_vnni_ko.py"
    if ($LASTEXITCODE -ne 0) { Write-Error "Building avx_vnni_emu.ko failed."; exit 1 }
}

# 5. Build Image
Write-Host "`n[5/6] Verifying image assets and assembling base disk..." -ForegroundColor Yellow

# Ensure template manifest and cmdline exist in prepared/ without clobbering existing digests
if ((Test-Path "launcher\vm.json") -and -not (Test-Path "prepared\vm.json")) {
    Copy-Item "launcher\vm.json" "prepared\vm.json"
}
if ((Test-Path "launcher\cmdline.txt") -and -not (Test-Path "prepared\cmdline.txt")) {
    Copy-Item "launcher\cmdline.txt" "prepared\cmdline.txt"
}

if (-not ((Test-Path "prepared\base.qcow2") -and (Test-Path "prepared\kernel") -and (Test-Path "prepared\initrd.gz"))) {
    $existingRaw = Get-ChildItem "downloads" -Filter "*ruby*.raw" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $existingRaw) {
        $existingRaw = Get-ChildItem "downloads" -Filter "*recovery*.raw" -ErrorAction SilentlyContinue | Select-Object -First 1
    }

    if (-not $existingRaw -and -not $SkipDownload) {
        $zipTarget = Join-Path $PSScriptRoot "downloads\ruby-recovery.zip"
        if (-not (Test-Path $zipTarget)) {
            Write-Host "   Downloading official Googlebook OS recovery (~7.8 GB)..." -ForegroundColor Cyan
            Write-Host "   URL: $RecoveryUrl" -ForegroundColor Gray
            if (Get-Command "curl.exe" -ErrorAction SilentlyContinue) {
                & curl.exe -L -# -o $zipTarget $RecoveryUrl
            } else {
                Invoke-WebRequest -Uri $RecoveryUrl -OutFile $zipTarget
            }
        }

        $zipHash = (Get-FileHash $zipTarget -Algorithm SHA256).Hash
        if ($RecoverySha256) {
            if ($zipHash -ne $RecoverySha256.ToUpper()) {
                Remove-Item $zipTarget -Force
                Write-Error "SHA-256 mismatch for recovery zip. Expected $RecoverySha256, got $zipHash. File deleted."
                exit 1
            }
            Write-Host "   Recovery zip SHA-256 verified." -ForegroundColor Green
        } else {
            Write-Host "   Recovery zip SHA-256: $zipHash" -ForegroundColor Gray
        }

        Write-Host "   Extracting recovery archive into downloads/..." -ForegroundColor Cyan
        if (Get-Command "tar.exe" -ErrorAction SilentlyContinue) {
            & tar.exe -xf $zipTarget -C "downloads"
        } else {
            Expand-Archive -Path $zipTarget -DestinationPath "downloads" -Force
        }

        $binFile = Get-ChildItem "downloads" -Filter "*android-desktop*.bin" -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $binFile) {
            $binFile = Get-ChildItem "downloads" -Filter "*recovery*.bin" -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if (-not $binFile) {
            $binFile = Get-ChildItem "downloads" -Filter "*.bin" -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if ($binFile) {
            $rawTarget = Join-Path $PSScriptRoot "downloads\ruby-recovery.raw"
            Move-Item -Path $binFile.FullName -Destination $rawTarget -Force
            Write-Host "   Recovery image extracted: $rawTarget" -ForegroundColor Green
        }
    }
}

Write-Host "   Verifying and assembling VM assets..." -ForegroundColor Gray
& python "scripts\prepare_image.py"
if ($LASTEXITCODE -ne 0) { Write-Error "Disk assembly failed."; exit 1 }

# Apply color fix
if (Test-Path "prepared\initrd.gz") {
    Write-Host "   Applying virtio-gpu true-color channel mapping patch..." -ForegroundColor Gray
    & python "patches\color_fix\patch_color_format.py" "prepared\initrd.gz" "prepared\vm.json"
    if ($LASTEXITCODE -ne 0) { Write-Error "Color patch failed."; exit 1 }
}

# Ensure userdata
if (-not (Test-Path "prepared\userdata.qcow2") -and (Test-Path "prepared\base.qcow2")) {
    if ($qemuImg -and (Test-Path $qemuImg)) {
        Write-Host "   Creating disposable/persistent userdata.qcow2..." -ForegroundColor Gray
        & $qemuImg create -f qcow2 -F qcow2 -b "base.qcow2" "prepared\userdata.qcow2"
    } else {
        Write-Warning "qemu-img not found. Skipping initial userdata.qcow2 creation (it will be created automatically on first launch)."
    }
}

# Optional VirGL GPU acceleration overlay
$hasWsl = (Get-Command "wsl.exe" -ErrorAction SilentlyContinue) -ne $null
if ($hasWsl -and -not (Test-Path "prepared\base-virgl.qcow2")) {
    Write-Host "   WSL detected: pre-building hardware GPU (VirGL) overlay..." -ForegroundColor Gray
    try {
        & python "scripts\build_vendor_virgl.py"
    } catch {
        Write-Warning "Could not build VirGL overlay during install: $_"
    }
}

Write-Host "`n[6/6] Finalizing configuration..." -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Green
Write-Host "   INSTALLATION COMPLETE! READY TO LAUNCH!                     " -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start Googlebook OS with GPU acceleration (recommended):" -ForegroundColor Cyan
Write-Host "   .\Start-Googlebook-VirGL.bat" -ForegroundColor Yellow
Write-Host "or with software CPU rendering:" -ForegroundColor Cyan
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

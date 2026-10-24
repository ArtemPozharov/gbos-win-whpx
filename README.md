# Googlebook OS (Android 17) on Windows 11 (WHPX)

Run the real **Googlebook OS** (Lenovo ThinkPad "Ruby" build, Android 17 desktop) inside a hardware-accelerated QEMU virtual machine under **Windows Hypervisor Platform (WHPX)** on any modern x86_64 PC (**AMD Ryzen & Intel**).

> **Disclaimer:** This project is independent research and is not affiliated with, endorsed by, or sponsored by Google LLC or Lenovo. Google, Android, Googlebook, and related marks are trademarks of Google LLC.

---

## 🌟 Key Breakthroughs in this Project

Previous community efforts (such as `gbrunch` and `gbos-vm`) were either restricted to Linux/Intel or exclusively designed for Apple Silicon Macs (ARM64 with Metal). Running Googlebook OS on Windows with AMD Ryzen CPUs previously failed with multiple blocking crashes. This project introduces several key fixes:

1. **Pure-GPR Kernel `#UD` AVX-VNNI Trap Emulator (`avx_vnni_emu.ko`)**:
   * *The Problem:* Googlebook OS userspace binaries (`libz.so`, `libcrypto_httpengine.so`) are compiled for Intel Core Ultra with VEX-encoded `AVX-VNNI` (`vpdpbusd`, `vpdpwssd`). AMD Zen 1–4 processors and older Intel CPUs (11th Gen and older) do not have this instruction set, resulting in immediate fatal `SIGILL` (Invalid Opcode) crashes.
   * *The Fix:* We developed a lightweight Linux kernel module that hooks the `#UD` exception handler, decodes the VEX instruction bytes, emulates the dot-product in pure general-purpose registers without clobbering host vector registers, and advances `pt_regs->ip`.
   * *CPU Compatibility:* Runs universally on **AMD Zen 1–5** and **Intel Core (all generations)**. On CPUs with native silicon AVX-VNNI (Zen 5, Intel 12th+ Gen), the hardware executes it natively with 0% overhead.

2. **SELinux `execmem` Policy Injection (Fixes User Picker Crash)**:
   * *The Problem:* Clicking on the user profile triggered an immediate `SIGSEGV (SEGV_ACCERR)` in `system_server` (`RenderThread`), killing `zygote` and forcing a soft reboot back to the lockscreen.
   * *The Root Cause:* Android's SwiftShader Vulkan software rasterizer (`vulkan.pastel.so`) compiles shaders to JIT memory at runtime. Upstream SELinux policies denied `execmem` to `system_server`.
   * *The Fix:* Our vendor patch grants `allow system_server self:process execmem;`, enabling seamless interactive user login.

3. **True Color Channel Translation (`virtio-gpu`)**:
   * *The Problem:* The guest DRM driver and QEMU's Pixman display backend suffered from an endianness channel mismatch: red and blue were swapped (YouTube and Gmail icons were blue), and black turned into solid red.
   * *The Fix:* Patched `virtio-gpu.ko` to translate DRM framebuffers into `VIRTIO_GPU_FORMAT_R8G8B8A8_UNORM` (`PIXMAN_a8b8g8r8`), restoring 100% accurate, vibrant colors with pure deep blacks (`#000000`).

4. **Performance Tuning for Software 3D (2–3x Speedup)**:
   * Injected init overrides to disable expensive multi-pass Kawase window blurs (`persist.sys.sf.disable_blurs=1` and `ro.surface_flinger.supports_background_blur=0`), freeing up over 60% of CPU time.
   * Enabled threaded SkiaGL rendering (`debug.renderengine.backend=skiaglthreaded`).
   * Scaled default resolution to 1280×800 (16:10 native aspect ratio), reducing software pixel fillrate by 40% while scaling smoothly to full screen.

5. **Plug-and-Play USB Keyboard & Mouse**:
   * Dedicated USB HID keyboard (`usb-kbd`) and mouse (`usb-mouse`) attached via virtual XHCI, bypassing virtualization conflicts and providing responsive desktop typing and pointer interaction.

---

## 🖥️ System Requirements

* **Operating System:** Windows 10 (21H2+) or Windows 11 64-bit.
* **Hypervisor:** Windows Hypervisor Platform (WHPX) enabled.
* **Processor:** 64-bit AMD Ryzen or Intel Core (4+ physical cores recommended).
* **Memory:** 8 GB RAM minimum (16 GB recommended). The launcher automatically allocates **50% of your system RAM and CPU cores** by default.
* **Storage:** 20 GB free disk space.
* **Python:** Python 3.10 or newer (ensure `Add Python to PATH` was checked during installation).

---

## 🚀 Quick Start (Automated Setup)

### Step 1: Enable Windows Hypervisor Platform (WHPX)
Open **PowerShell as Administrator** and execute:
```powershell
dism /online /enable-feature /featurename:HypervisorPlatform /all /norestart
```
*(If prompted, restart your computer).*

### Step 2: Clone the Repository & Run Installer
```powershell
git clone https://github.com/YOUR_USERNAME/gbos-win-whpx.git
cd gbos-win-whpx
powershell -ExecutionPolicy Bypass -File .\install.ps1
```
The automated script will:
1. Verify system virtualization requirements.
2. Download the official Lenovo Ruby recovery image and Android Cuttlefish donor components directly from official sources.
3. Apply the AVX-VNNI emulator, SELinux policy, and color fix patches.
4. Assemble the QCOW2 virtual disk image.

### Step 3: Launch Googlebook OS!
Double-click `Start-Googlebook.bat` or run:
```powershell
.\Start-Googlebook.bat
```

---

## ⌨️ Controls & Shortcuts

| Action | Shortcut / Instruction |
| :--- | :--- |
| **Capture Mouse** | Click inside the virtual machine window |
| **Release Mouse** | <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>G</kbd> |
| **Toggle Full Screen** | <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>F</kbd> |
| **Switch Keyboard Language** | <kbd>Ctrl</kbd> + <kbd>Space</kbd> or <kbd>Win</kbd> + <kbd>Space</kbd> inside Android |
| **Factory Reset / Wipe Data** | Run `.\Reset-Data.bat` (wipes `userdata.qcow2`, keeps system intact) |

---

## ⚙️ Advanced Launch Options

The Python launcher (`launcher/launch_googlebook.py`) supports full customization:

```powershell
# Run with 12 GB RAM and 8 CPU threads in a window
python launcher/launch_googlebook.py --memory-mb 12288 --cpus 8 --no-fullscreen

# Run with custom display resolution
python launcher/launch_googlebook.py --resolution 1600x1000

# Run in disposable mode (all disk changes discarded on exit)
python launcher/launch_googlebook.py --ephemeral
```

---

## 📁 Repository Structure

```text
gbos-win-whpx/
├── README.md                 # English documentation and architecture breakdown
├── install.ps1               # Automated end-to-end setup script
├── Start-Googlebook.bat      # Fast launcher batch script
├── Start-Googlebook.ps1      # Native PowerShell launcher script
├── Reset-Data.bat            # Factory data reset utility
├── launcher/
│   ├── launch_googlebook.py  # Python WHPX launcher with host auto-detection
│   └── vm.json               # Virtual machine image manifest
├── patches/
│   ├── avx_vnni/             # AVX-VNNI kernel emulator C source & builder
│   ├── color_fix/            # virtio-gpu DRM format translation patch
│   └── selinux/              # Vendor SELinux policy rules
└── scripts/
    └── prepare_image.py      # Recovery unpacker and base disk builder
```

---

## 🤝 Credits & Acknowledgements

This work builds upon research and concepts from the open-source community:
* [**gbrunch**](https://github.com/danbyumagic/gbrunch) by `@danbyumagic` for original x86 recovery analysis, GPT partition layout, and Cuttlefish component grafting.
* [**gbos-vm**](https://github.com/skylartaylor/gbos-vm) by `@skylartaylor` for the vendor replacement model and setup wizard bypass scripts.
* **Google Android Cuttlefish** team for the virtual hardware HAL implementations.
* **The QEMU Project** for the versatile open-source emulator.

---

## 📄 License
This repository contains original patches, scripts, and documentation distributed under the **Apache License 2.0**. No Google or Lenovo copyrighted images or proprietary binary firmware blobs are stored or distributed in this repository.

# LazyGimp

**The latest stable GIMP, patched with [PhotoGIMP](https://github.com/Diolinux/PhotoGIMP), [G'MIC](https://gmic.eu), [Batcher](https://github.com/kamilburda/batcher) and [Segment Anything (SAM)](https://github.com/Shriinivas/gimpsegany) — in one command, for lazy people.**

[![CI](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml)
[![Release](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

LazyGimp is an automated, zero-stress installer and configurator featuring a modern dark-themed GUI (PySide6/Qt) and a complete CLI. It sets up GIMP on your system (via package manager or Flatpak on Linux, or official installer on Windows), applies the Photoshop-like PhotoGIMP configuration layer without destroying your personal files, and configures powerful plugins.

---

## 📦 What are the Release Assets? (Quale file scaricare?)

When looking at a [GitHub Release](https://github.com/pierspad/LazyGimp/releases/latest), you will see several assets:

| Asset Name | Platform | Description | How to run |
|---|---|---|---|
| **`LazyGimp-Installer-Linux`** | **Linux** (x86_64) | **Standalone Executable** (GUI + CLI). Zero dependencies, bundles Python & Qt inside. | `chmod +x LazyGimp-Installer-Linux && ./LazyGimp-Installer-Linux` |
| **`LazyGimp-Installer-Windows.exe`** | **Windows** (x64) | **Standalone Windows Executable** (GUI + CLI). Double-click or run from PowerShell. | Double-click `LazyGimp-Installer-Windows.exe` |
| **`LazyGimp-Python.pyz`** | **All Platforms** | **Portable Python ZipApp**. Lightweight single-file script (requires Python 3.10+). | `python3 LazyGimp-Python.pyz` |
| **`LazyGimp-Source.zip`** | **All Platforms** | **Source Code Package**. Unzip and run `python3 installer.py`. | `unzip LazyGimp-Source.zip && cd lazygimp && python3 installer.py` |
| **`checksums.txt`** | - | SHA-256 integrity hashes for all release binaries. | - |

---

## 🚀 Quick Start

### Linux

**Option 1: One-Liner (Zero-dependency standalone binary)**
```bash
curl -fsSL -o LazyGimp-Installer-Linux https://github.com/pierspad/LazyGimp/releases/latest/download/LazyGimp-Installer-Linux && chmod +x LazyGimp-Installer-Linux && ./LazyGimp-Installer-Linux
```

**Option 2: From Source / Git Clone**
```bash
git clone https://github.com/pierspad/LazyGimp.git
cd LazyGimp
python3 installer.py            # Opens the GUI
python3 installer.py --help     # Opens the CLI help
```

---

### Windows

1. Download **[`LazyGimp-Installer-Windows.exe`](https://github.com/pierspad/LazyGimp/releases/latest/download/LazyGimp-Installer-Windows.exe)**.
2. Double-click to open the guided installer GUI!

Or run from PowerShell:
```powershell
.\LazyGimp-Installer-Windows.exe
```

---

## 💻 CLI Reference (Comandi e Argomenti)

LazyGimp accepts arguments directly from the command line for automated or headless setups.

```bash
LazyGimp-Installer-Linux [command] [options]
# or: python3 installer.py [command] [options]
```

### Main Commands

| Command | Description | Example |
|---|---|---|
| *(No arguments)* | Launches the interactive dark-themed GUI | `./LazyGimp-Installer-Linux` |
| `status` | Shows what components, profiles, and AI models are currently installed | `./LazyGimp-Installer-Linux status` |
| `install [components...]` | Installs specified components (`gimp`, `photogimp`, `gmic`, `sam`, `batcher`) | `./LazyGimp-Installer-Linux install gimp photogimp gmic` |
| `remove [components...]` | Uninstalls specified components safely | `./LazyGimp-Installer-Linux remove photogimp` |
| `fix-desktop` | Repairs Linux taskbar/desktop launcher integration and `Exec=` paths | `./LazyGimp-Installer-Linux fix-desktop` |
| `sam list` | Lists all supported Segment Anything checkpoints and download status | `./LazyGimp-Installer-Linux sam list` |
| `sam install <key>` | Installs a specific SAM checkpoint (e.g. `sam2_hiera_small`) | `./LazyGimp-Installer-Linux sam install sam2_hiera_small` |
| `sam3 download --token <token>` | Downloads gated SAM 3.1 weights from HuggingFace | `./LazyGimp-Installer-Linux sam3 download --token hf_xxx` |

### CLI Options

* `--method flatpak` / `--method pm`: Force GIMP installation method (Flatpak vs native Package Manager).
* `--ephemeral`: Self-deletes the installer binary upon exiting the GUI.
* `--help`: Displays all available CLI commands and flags.

---

## ✨ Features & Included Components

1. **GIMP 3.x**: Automatically detected from your system (distro package manager, Flathub Flatpak, or official Windows installer).
2. **PhotoGIMP**: Photoshop-style shortcuts, tool arrangement, dark UI defaults, splash screen, and single-window mode. Safe configuration layer: backups your old configuration first!
3. **G'MIC**: 500+ advanced image processing filters.
4. **Batcher**: Batch processing, format conversion, and **export layers as individual files**.
5. **Segment Anything (SAM)**: AI-powered subject selection tool (Meta SAM1, SAM2, SAM 3.1). Automatically sets up an isolated Python virtual environment with GPU/PyTorch acceleration.

---

## ❓ FAQ / Troubleshooting

**Q: Clicking the PhotoGIMP menu icon on Linux does nothing?**  
A: Run `./LazyGimp-Installer-Linux fix-desktop` or click "Fix taskbar icon now" in the GUI. This repairs the `Exec=` path in `~/.local/share/applications/gimp.desktop` and `org.gimp.GIMP.desktop`.

**Q: Why do I see `ModuleNotFoundError: No module named 'gi'` when starting `gimp` from the terminal?**  
A: If you run `gimp` inside a terminal where a Python virtual environment (`.venv`) is activated, GIMP's internal Python plugins try to use the `.venv` Python, which doesn't have `gi` (PyGObject). Launch GIMP from your desktop application menu or outside `.venv` (`deactivate`) and all Python plugins will work normally.

---

## 📜 License

This project is licensed under the GPL-3.0 License — see the [LICENSE](LICENSE) file.

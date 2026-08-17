# LazyGimp

The latest stable GIMP, patched with [PhotoGIMP](https://github.com/Diolinux/PhotoGIMP), [G'MIC](https://gmic.eu), [Batcher](https://github.com/kamilburda/batcher) and [Segment Anything](https://github.com/pierspad/GIMPSAM) — in one command.

[![CI](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml)
[![Release](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

LazyGimp installs GIMP (package manager or Flatpak on Linux, official installer on Windows), applies the Photoshop-style PhotoGIMP layer on top without touching your own settings, and wires up G'MIC, Batcher and SAM-based selection. One binary, a GUI wizard and a full CLI, no manual configuration.

## Install

| Asset | Platform | What it is |
|---|---|---|
| `LazyGimp-Installer-Linux` | Linux x86_64 | Standalone executable, GUI + CLI, no dependencies |
| `LazyGimp-Installer-Windows.exe` | Windows x64 | Standalone executable, GUI + CLI |
| `LazyGimp-Python.pyz` | Any OS | Portable zipapp, needs Python 3.10+ |
| `LazyGimp-Source.zip` | Any OS | Source checkout |
| `checksums.txt` | — | SHA-256 of every binary above |

All from [the latest release](https://github.com/pierspad/LazyGimp/releases/latest).

**Linux, one-liner:**

```bash
curl -fsSL -o LazyGimp-Installer-Linux https://github.com/pierspad/LazyGimp/releases/latest/download/LazyGimp-Installer-Linux
chmod +x LazyGimp-Installer-Linux
./LazyGimp-Installer-Linux
```

**Linux/macOS, from source:**

```bash
git clone https://github.com/pierspad/LazyGimp.git
cd LazyGimp
python3 installer.py            # GUI
python3 installer.py --help     # CLI
```

**Windows:** download `LazyGimp-Installer-Windows.exe` and double-click it, or run it from PowerShell.

Running with no arguments always opens the GUI; any subcommand runs headless.

## CLI

```
LazyGimp-Installer-Linux [command] [options]
# or: python3 installer.py [command] [options]
```

| Command | Description |
|---|---|
| *(none)* | Opens the GUI wizard |
| `status` | What's installed: GIMP, PhotoGIMP, G'MIC, SAM plug-in/backend/models, Batcher |
| `install <components...>` | `gimp`, `photogimp`, `gmic`, `sam`, `batcher` |
| `remove <components...>` | Uninstalls the given components |
| `fix-desktop` | Repairs the Linux taskbar/launcher icon after a PhotoGIMP install |
| `sam list` | Lists every SAM checkpoint and whether it's installed |
| `sam install <key>` | Downloads a specific checkpoint, e.g. `sam2_hiera_small` |
| `sam remove <key>` | Deletes a checkpoint |
| `sam3 download --token <hf_token>` | Downloads the gated SAM 3 weights from Hugging Face |
| `sam3 remove` | Deletes the SAM 3 checkpoint |

`--method package-manager` / `--method flatpak` forces how `gimp` gets installed (default: auto-detected). `--ephemeral` self-deletes the binary once the GUI closes.

## What it sets up

- **GIMP 3.x** — from your distro's package manager, Flathub, or the official Windows installer.
- **PhotoGIMP** — Photoshop-like shortcuts, tool layout, dark theme, single-window mode. Your existing GIMP config is backed up first and can be restored by removing the component.
- **G'MIC** — 500+ image-processing filters.
- **Batcher** — batch conversion and exporting layers as individual files.
- **SAM (Segment Anything)** — AI-assisted subject selection (SAM1, SAM2, SAM 3), with an isolated Python virtualenv and GPU-accelerated PyTorch set up automatically. The plug-in, model registry and backend all come from [GIMPSAM](https://github.com/pierspad/GIMPSAM), which LazyGimp pulls in as its single source of truth for everything SAM.

## Troubleshooting

**Clicking the PhotoGIMP icon on Linux does nothing.**
Run `./LazyGimp-Installer-Linux fix-desktop` (or "Fix taskbar icon now" in the GUI). It repairs the `Exec=` path in `~/.local/share/applications/gimp.desktop` and `org.gimp.GIMP.desktop`.

**`ModuleNotFoundError: No module named 'gi'` when launching `gimp` from a terminal.**
GIMP's Python plug-ins need PyGObject (`gi`), which isn't in a Python virtualenv. If you start `gimp` from a terminal with a `.venv` active, `deactivate` first, or launch GIMP from your application menu instead.

## License

GPL-3.0 — see [LICENSE](LICENSE).

# LazyGimp

The latest stable GIMP, patched with [PhotoGIMP](https://github.com/Diolinux/PhotoGIMP), [G'MIC](https://gmic.eu), [Batcher](https://github.com/kamilburda/batcher) and [Segment Anything](https://github.com/pierspad/GIMPSAM) — in one command.

[![CI](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml)
[![Release](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

Lazy in LazyGimp stands as the [first virtue of the great programmer](https://thethreevirtues.com/).

You are not forced to install everything i recommended, you can selectively disable every component that you don't like/need and can always reuse the installer to add them later on.  

In a nutshell, I aim to mantain this as an aggregator of all the best and most useful GIMP plugins,add-ons and config files.

## Install

You can find the downloadable files in [the latest release](https://github.com/pierspad/LazyGimp/releases/latest).

---

**Linux one-liner:**

```bash
curl -fsSL -o LazyGimp-Installer-Linux https://github.com/pierspad/LazyGimp/releases/latest/download/LazyGimp-Installer-Linux && chmod +x LazyGimp-Installer-Linux && ./LazyGimp-Installer-Linux
```

**From source:**

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

## Troubleshooting

**Clicking the PhotoGIMP icon on Linux does nothing.**
Run `./LazyGimp-Installer-Linux fix-desktop` (or "Fix taskbar icon now" in the GUI). It repairs the `Exec=` path in `~/.local/share/applications/gimp.desktop` and `org.gimp.GIMP.desktop`.

**`ModuleNotFoundError: No module named 'gi'` when launching `gimp` from a terminal.**
GIMP's Python plug-ins need PyGObject (`gi`), which isn't in a Python virtualenv. If you start `gimp` from a terminal with a `.venv` active, `deactivate` first, or launch GIMP from your application menu instead.


## Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss your ideas.

---

## AI Disclosure

This project was developed with the assistance of Large Language Models, used to support code writing and documentation.

---
## License

This project is licensed under the GPL v3 License — see the [LICENSE](LICENSE) file for details.

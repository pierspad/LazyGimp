# LazyGimp

**The latest stable GIMP, patched with [PhotoGIMP](https://github.com/Diolinux/PhotoGIMP) and [G'MIC](https://gmic.eu), in one command — for lazy people.**

[![CI](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml)
[![Release](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](../LICENSE)

LazyGimp is a single installer app — a dark-themed GUI plus a full CLI — that installs GIMP (package manager or AppImage), applies PhotoGIMP, and sets up G'MIC, Batcher and Segment Anything (SAM). No arguments opens the GUI; every action is also a plain CLI command for headless boxes.

## Quick start (Linux)

Pick **one** of the three release artifacts — they are the same program, packaged three ways:

| Artifact | Requirements | How to run |
|---|---|---|
| [`lazygimp-linux-x86_64`](https://github.com/pierspad/LazyGimp/releases/latest/download/lazygimp-linux-x86_64) | none (self-contained: Python, Tk, GUI toolkit all inside) | `chmod +x lazygimp-linux-x86_64 && ./lazygimp-linux-x86_64` |
| [`lazygimp.pyz`](https://github.com/pierspad/LazyGimp/releases/latest/download/lazygimp.pyz) | `python3` + Tk; GUI also needs `pip install customtkinter` (CLI doesn't) | `python3 lazygimp.pyz` |
| [`lazygimp-src.zip`](https://github.com/pierspad/LazyGimp/releases/latest/download/lazygimp-src.zip) | same as the `.pyz` | see below |

The binary is the recommended download: it's disposable by design — tick *"Delete this installer when it closes"* on its start screen (or launch with `--ephemeral`) and it removes itself once you're done, leaving the folder clean.

One-liner (binary, zero dependencies):

```bash
curl -fsSL -o lazygimp https://github.com/pierspad/LazyGimp/releases/latest/download/lazygimp-linux-x86_64 && chmod +x lazygimp && ./lazygimp
```

### Running from the zip

```bash
unzip lazygimp-src.zip
cd lazygimp
python3 lazygimp.py            # GUI
python3 lazygimp.py --help     # CLI
```

### Running from a clone (uncompiled source)

```bash
git clone https://github.com/pierspad/LazyGimp.git
cd LazyGimp
python3 lazygimp.py            # GUI  (equivalent: python3 -m lazygimp)
python3 lazygimp.py status     # CLI
```

Requirements when running from source or the `.pyz`: Python 3.10+ with Tkinter (`sudo apt install python3-tk` on Debian/Ubuntu; usually preinstalled elsewhere) and, for the GUI only, [CustomTkinter](https://customtkinter.tomschimansky.com) (`pip install customtkinter`). The CLI needs neither. [Pillow](https://python-pillow.org) is optional — nicer anti-aliased icons if present. The prebuilt binary bundles everything.

### CLI in 20 seconds

```bash
python3 lazygimp.py status                          # what's installed
python3 lazygimp.py install gimp photogimp gmic sam batcher
python3 lazygimp.py install gimp --method appimage  # force a method
python3 lazygimp.py remove batcher
python3 lazygimp.py sam list                        # SAM models & install state
python3 lazygimp.py sam install sam2_hiera_small
python3 lazygimp.py sam3 download --token hf_xxx    # SAM 3.1 (gated on HF)
python3 lazygimp.py fix-desktop                     # repair the menu entry
python3 lazygimp.py --ephemeral                     # GUI, self-deletes on exit
```

**Package manager or AppImage?** On rolling or fast-moving distros (Arch, Fedora, openSUSE Tumbleweed) the package manager is the best choice: native, integrated, current. On Debian stable or Ubuntu LTS the repos ship an old GIMP — there the AppImage is the honest recommendation, and LazyGimp tells you exactly that if it detects GIMP 2.x. Supported out of the box: **Arch**, **Fedora**, **Debian**, **Ubuntu**, **openSUSE** — and their derivatives (Manjaro, EndeavourOS, Linux Mint, Pop!\_OS, Nobara, ...) via `ID_LIKE` matching.

## Quick start (Windows)

[![windows-install.ps1](https://img.shields.io/badge/⬇-windows--install.ps1-0078d4)](https://github.com/pierspad/LazyGimp/releases/latest/download/windows-install.ps1) — download, then:

```powershell
powershell -ExecutionPolicy Bypass -File windows-install.ps1
```

It downloads the official GIMP installer (checksum-verified against gimp.org's own metadata), installs it silently, and applies the PhotoGIMP layer.

### What are the GitHub releases for, then?

A release is the immutable, checksummed artifact set behind the links above: the binary, the `.pyz`, the source zip, the Windows script and the changelog — `main` may move; a release never does. Pushes to `dev` publish **pre-releases** (versions tagged `-dev.N`) if you want to try what's coming.

## What you get

* **GIMP** — always the newest stable, from official channels only (your distro or gimp.org). Never rebuilt or repackaged by us.
* **PhotoGIMP** — Photoshop-style layout, shortcuts and defaults, applied as a *configuration layer*: your existing settings are backed up first, every installed file is tracked in a manifest, and your brushes/scripts/plug-ins are never touched.
* **G'MIC** — 500+ filters, from your package manager.

Works with any GIMP 3.x — including future releases. Nothing in LazyGimp hardcodes a GIMP version: the right config directory (`3.0`, `3.2`, `3.4`, ...) is detected at runtime.

## Plug-ins

| Plug-in | What it adds | Notes |
|---|---|---|
| [Batcher](https://github.com/kamilburda/batcher) | Batch processing, convert images, **export layers as separate files** | Just works after a GIMP restart |
| [Segment Anything](https://github.com/Shriinivas/gimpsegany) | AI subject selection via Meta SAM (SAM1 **and** SAM2, plus gated SAM 3.1) | **Fully automated backend**: LazyGimp creates a dedicated Python venv (PyTorch wheels matched to your GPU), installs both the SAM1 and SAM2 backends, downloads your chosen checkpoint and runs upstream's self-test. Model management: `python3 lazygimp.py sam list/install/remove`. On first use, paste the two paths the installer prints (also in `~/.local/share/lazygimp/segany/INFO.txt`) — GIMP remembers them. |

Plug-ins land in the plug-ins folder of the GIMP you installed (auto-detected) and are tracked for clean removal.

## Undo / uninstall

```bash
python3 lazygimp.py remove gimp photogimp gmic sam batcher   # everything
python3 lazygimp.py remove photogimp                          # or selectively
```

The GUI's Manage screen does the same per-component. Your personal GIMP files are never deleted; full pre-install backups live in `~/.local/state/lazygimp/backups/`.

## FAQ / Troubleshooting

**The "PhotoGIMP" menu entry does nothing.** Fixed in current LazyGimp: upstream PhotoGIMP hardcodes a launch command in its menu entry that silently fails if it doesn't match the GIMP you installed. LazyGimp retargets the entry to the GIMP it actually installed — run `python3 lazygimp.py fix-desktop` if you hit this.

**I see two GIMP entries in the menu.** LazyGimp hides the stock duplicate where it can; after `fix-desktop` you should see a single "PhotoGIMP" entry. Log out/in (or run `update-desktop-database`) if your menu caches entries.

**G'MIC appears in Filters but is greyed out.** That's GIMP, not a bug: G'MIC operates on an image, so it stays disabled until you open one. Same for most filters.

**Where is Segment Anything, and what goes in its dialog?** Open an image first, then `Image → Segment Anything Layers`. On the very first run fill in (GIMP remembers them afterwards):

| Field | Value |
|---|---|
| Python3 Path | `~/.local/share/lazygimp/segany/venv/bin/python3` |
| Model Checkpoint | `~/.local/share/lazygimp/segany/models/<your-checkpoint>` |
| Model Type | `Auto` (inferred from the checkpoint filename) |

The exact values are saved in `~/.local/share/lazygimp/segany/INFO.txt`. Checkpoints live under `~/.local/share/lazygimp/segany/models/`; `python3 lazygimp.py sam list` shows every model key and its state. SAM1 checkpoints (`sam_vit_*`) are the reliable choice with this plug-in; SAM2 checkpoints are offered but experimental.

## Re-running & updating

Every action is **idempotent** — re-running is the supported way to update or repair. Whatever is already present and valid is kept (native packages, an intact AppImage of the same version, the SAM virtualenv and any checkpoint already downloaded are never re-fetched); whatever is missing is added; whatever LazyGimp manages (PhotoGIMP layer, plug-in folders) is **brutally overwritten** with the current version — after the usual timestamped backup of your GIMP configuration. Your personal files (brushes, scripts, your own plug-ins) are never touched.


## Credits & licenses

LazyGimp is a thin installer/configurator: it **does not bundle or redistribute** any of these projects — it downloads them from their official channels at install time. All credit goes to their authors:

| Project | Author(s) | What LazyGimp uses it for | License |
|---|---|---|---|
| [GIMP](https://www.gimp.org) | The GIMP team | The image editor itself | [GPL-3.0-or-later](https://gitlab.gnome.org/GNOME/gimp/-/blob/master/COPYING) |
| [PhotoGIMP](https://github.com/Diolinux/PhotoGIMP) | Diolinux | Photoshop-style configuration layer | [GPL-3.0](https://github.com/Diolinux/PhotoGIMP/blob/master/LICENSE) |
| [G'MIC](https://gmic.eu) | GREYC / D. Tschumperlé et al. | 500+ image filters | [CeCILL 2.1 / CeCILL-C](https://gmic.eu/download.html) |
| [Batcher](https://github.com/kamilburda/batcher) | Kamil Burda | Batch processing & layer export | [BSD-3-Clause](https://github.com/kamilburda/batcher/blob/main/LICENSE) |
| [gimpsegany](https://github.com/Shriinivas/gimpsegany) | Shriinivas | Segment Anything integration | [AGPL-3.0](https://github.com/Shriinivas/gimpsegany/blob/main/LICENSE) |
| [GIMPSAM](https://github.com/pierspad/GIMPSAM) | //TODO | //TODO | //TODO |


---

## Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss your ideas.

---

## AI Disclosure

This project was developed with the assistance of Large Language Models, used to support code writing and documentation.

---

## License

This project is licensed under the GPL v3 License — see the [LICENSE](../LICENSE) file for details.

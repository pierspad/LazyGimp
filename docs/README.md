# LazyGimp

**The latest stable GIMP, patched with [PhotoGIMP](https://github.com/Diolinux/PhotoGIMP) and [G'MIC](https://gmic.eu), in one command — for lazy people.**

[![CI](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml)
[![Release](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

## Quick start (Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/pierspad/LazyGimp/main/install.sh | bash
```

`install.sh` is a pure orchestrator: it shows an interactive menu of the available methods and **downloads nothing before you choose**. Each method is also a standalone script you can run directly:

```bash
./install_with_package_manager.sh   # native distro packages, updated by your system [default]
./install_with_flatpak.sh           # Flathub GIMP + G'MIC extension, auto-updated
./install_with_appimage.sh          # official gimp.org AppImage, single portable file
```

Non-interactive? `./install.sh --method package-manager` (or `flatpak` / `appimage` / `auto`).

**Which method should I pick?** On rolling or fast-moving distros (Arch, Fedora, openSUSE Tumbleweed) the package manager is the best choice: native, integrated, current. On Debian stable or Ubuntu LTS the repos ship an old GIMP — there the flatpak is the honest recommendation, and the installer will tell you exactly that if it detects GIMP 2.x.

Supported out of the box: **Arch**, **Fedora**, **Debian**, **Ubuntu**, **openSUSE** — and their derivatives (Manjaro, EndeavourOS, Linux Mint, Pop!\_OS, Nobara, ...) via `ID_LIKE` matching. Adding a distro is one small file in [`shell_scripts/`](../shell_scripts/).

## Quick start (Windows)

Download [`install-lazygimp.ps1`](https://github.com/pierspad/LazyGimp/releases/latest/download/install-lazygimp.ps1) from the latest release, then:

```powershell
powershell -ExecutionPolicy Bypass -File install-lazygimp.ps1
```

It downloads the official GIMP installer (checksum-verified against gimp.org's own metadata), installs it silently, and applies the PhotoGIMP layer.

## What you get

* **GIMP** — always the newest stable, from official channels only (Flathub, your distro, gimp.org). Never rebuilt or repackaged by us.
* **PhotoGIMP** — Photoshop-style layout, shortcuts and defaults, applied as a *configuration layer*: your existing settings are backed up first, every installed file is tracked in a manifest, and your brushes/scripts/plug-ins are never touched.
* **G'MIC** — 500+ filters, from your package manager or as the Flathub extension where available.

Works with any GIMP 3.x — including future releases. Nothing in LazyGimp hardcodes a GIMP version: the right config directory (`3.0`, `3.2`, `3.4`, ...) is detected at runtime. See [ARCHITECTURE.md](ARCHITECTURE.md) for how and why.

## Plug-ins (installed by default)

A default install sets up **everything**: GIMP + PhotoGIMP + G'MIC + the plug-ins below, ready to use. Opt out with `--skip-plugins` or `--no-sam`.

| Plug-in | What it adds | Notes |
|---|---|---|
| [Batcher](https://github.com/kamilburda/batcher) | Batch processing, convert images, **export layers as separate files** | Just works after a GIMP restart |
| [Segment Anything](https://github.com/Shriinivas/gimpsegany) | AI subject selection via Meta SAM | **Fully automated backend**: LazyGimp creates a dedicated Python venv (PyTorch CPU wheels), installs SAM, downloads the checkpoint (~1 GB total) and runs upstream's self-test. On first use, paste the two paths shown by the installer (also in `~/.local/share/lazygimp/segany/INFO.txt`) — GIMP remembers them. GPU: `LAZYGIMP_TORCH_INDEX_URL=<cuda wheel index> ./install_plugins.sh --segment-anything` |
| [Resynthesizer](https://github.com/bootchk/resynthesizer) | Heal Selection — content-aware fill, GIMP's most loved plug-in | Flatpak method only (installed as Flathub extension); native builds are per-platform C binaries |

Plug-ins land in the plug-ins folder of whichever GIMP you have (native or flatpak, auto-detected) and are tracked for clean removal. Standalone: `./install_plugins.sh`.

## Fonts and the flatpak sandbox

Recent flatpak already exposes your system **and** user fonts to GIMP. To make sure nothing is ever missing (custom fontconfig setups included), the flatpak installer additionally grants the sandbox **read-only** access to `~/.local/share/fonts` and `~/.config/fontconfig` — it tells you it did, records the exact override, and `./uninstall.sh` reverts it. Opt out with `--no-font-access`.

## Undo / uninstall

```bash
./uninstall.sh
```

Detects what LazyGimp installed (native packages, flatpak, AppImage, PhotoGIMP layer, plug-ins), lists it, and removes what you confirm — so you can reinstall clean with a different method. Selective removal: `--method photogimp`, `--method flatpak`, etc. Your personal GIMP files are never deleted; full pre-install backups live in `~/.local/state/lazygimp/backups/` (removed only with `--purge`).

## Contributing

Commits follow [Conventional Commits](https://www.conventionalcommits.org): `feat:` (minor), `fix:`/`perf:`/`refactor:` (patch), `docs:`/`chore:` (no release), `BREAKING CHANGE:` (major). Every push to `main` is released automatically — version bump, changelog, tag, GitHub release and backmerge to `dev` are handled by [semantic-release](../.releaserc). CI gates every PR with ShellCheck, bats tests, actionlint and PSScriptAnalyzer.

To support a new distribution, add `shell_scripts/<id>.sh` defining `lazygimp::install_packages` and `lazygimp::remove_packages` — see any existing file for the contract.

## Credits & licenses

LazyGimp is a thin installer/configurator: it **does not bundle or redistribute** any of these projects — it downloads them from their official channels at install time. All credit goes to their authors:

| Project | Author(s) | What LazyGimp uses it for | License |
|---|---|---|---|
| [GIMP](https://www.gimp.org) | The GIMP team | The image editor itself | [GPL-3.0-or-later](https://gitlab.gnome.org/GNOME/gimp/-/blob/master/COPYING) |
| [PhotoGIMP](https://github.com/Diolinux/PhotoGIMP) | Diolinux | Photoshop-style configuration layer | [GPL-3.0](https://github.com/Diolinux/PhotoGIMP/blob/master/LICENSE) |
| [G'MIC](https://gmic.eu) | GREYC / D. Tschumperlé et al. | 500+ image filters | [CeCILL 2.1 / CeCILL-C](https://gmic.eu/download.html) |
| [Batcher](https://github.com/kamilburda/batcher) | Kamil Burda | Batch processing & layer export | [BSD-3-Clause](https://github.com/kamilburda/batcher/blob/main/LICENSE) |
| [Resynthesizer](https://github.com/bootchk/resynthesizer) | Lloyd Konneker (bootchk) et al. | Heal Selection / texture synthesis | [GPL-3.0](https://github.com/bootchk/resynthesizer/blob/master/COPYING) |
| [gimpsegany](https://github.com/Shriinivas/gimpsegany) | Shriinivas | Segment Anything integration | [AGPL-3.0](https://github.com/Shriinivas/gimpsegany/blob/main/LICENSE) |
| [Segment Anything](https://github.com/facebookresearch/segment-anything) | Meta AI | AI models behind gimpsegany | [Apache-2.0](https://github.com/facebookresearch/segment-anything/blob/main/LICENSE) |

License compatibility: LazyGimp itself is GPL-3.0. Since we only *invoke and download* the projects above (mere aggregation, no derived work), no license conflict can arise. Even in the strictest reading, every license in the table is GPL-3.0-compatible: GPL-3.0 (same), BSD-3-Clause and Apache-2.0 (permissive, one-way compatible), CeCILL 2.1 (explicitly GPL-compatible, art. 5.3.4), AGPL-3.0 (linkable with GPL-3.0 per GPLv3 §13).

## License

[GPL-3.0](LICENSE)

# LazyGimp

**The latest stable GIMP, patched with [PhotoGIMP](https://github.com/Diolinux/PhotoGIMP) and [G'MIC](https://gmic.eu), in one command — for lazy people.**

[![CI](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/ci.yml)
[![Release](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml/badge.svg)](https://github.com/pierspad/LazyGimp/actions/workflows/release.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

## Quick start (Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/pierspad/LazyGimp/main/install.sh | bash
```

That's it. The installer picks the best method for your system (Flatpak when available, otherwise your distro's package manager, otherwise the official AppImage), installs GIMP and G'MIC, and applies the PhotoGIMP layout — with a full backup of any existing configuration first.

Prefer a specific method?

```bash
./install.sh --method flatpak            # Flathub GIMP + G'MIC extension (recommended)
./install.sh --method package-manager    # native packages, updated by your distro
./install.sh --method appimage           # official gimp.org AppImage, portable
```

### Native packages only

```bash
./install_with_package_manager.sh
```

Supported out of the box: **Arch**, **Fedora**, **Debian**, **Ubuntu**, **openSUSE** — and their derivatives (Manjaro, EndeavourOS, Linux Mint, Pop!\_OS, Nobara, ...) via `ID_LIKE` matching. Adding a distro is one small file in [`shell_scripts/`](shell_scripts/).

## Quick start (Windows)

Download [`install-lazygimp.ps1`](https://github.com/pierspad/LazyGimp/releases/latest/download/install-lazygimp.ps1) from the latest release, then:

```powershell
powershell -ExecutionPolicy Bypass -File install-lazygimp.ps1
```

It downloads the official GIMP installer (checksum-verified against gimp.org's own metadata), installs it silently, and applies the PhotoGIMP layer.

## What you get

* **GIMP** — always the newest stable, from official channels only (Flathub, your distro, gimp.org). Never rebuilt or repackaged by us.
* **PhotoGIMP** — Photoshop-style layout, shortcuts and defaults, applied as a *configuration layer*: your existing settings are backed up first, every installed file is tracked in a manifest, and your brushes/scripts/plug-ins are never touched.
* **G'MIC** — 500+ filters, installed from your package manager or as the Flathub extension where available.

Works with any GIMP 3.x — including future releases. Nothing in LazyGimp hardcodes a GIMP version: the right config directory (`3.0`, `3.2`, `3.4`, ...) is detected at runtime. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how and why.

## Undo / uninstall

```bash
./install.sh --uninstall-photogimp            # native GIMP
./install.sh --uninstall-photogimp flatpak    # flatpak GIMP
```

Removes only the files the layer installed (tracked in its manifest) and leaves your personal files alone. Full pre-install backups live in `~/.local/state/lazygimp/backups/`.

## Contributing

Commits follow [Conventional Commits](https://www.conventionalcommits.org): `feat:` (minor), `fix:`/`perf:`/`refactor:` (patch), `docs:`/`chore:` (no release), `BREAKING CHANGE:` (major). Every push to `main` is released automatically — version bump, changelog, tag, GitHub release and backmerge to `dev` are all handled by [semantic-release](.releaserc). CI gates every PR with ShellCheck, bats tests, actionlint and PSScriptAnalyzer.

To support a new distribution, add `shell_scripts/<id>.sh` defining `lazygimp::install_packages` — see any existing file for the contract.

## Credits

* [GIMP](https://www.gimp.org) — the GNU Image Manipulation Program
* [Diolinux/PhotoGIMP](https://github.com/Diolinux/PhotoGIMP) — the patch this project exists to deliver
* [G'MIC](https://gmic.eu) — GREYC's Magic for Image Computing

## License

[GPL-3.0](LICENSE)

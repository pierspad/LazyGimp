# LazyGimp — Architecture

LazyGimp turns three moving upstream parts — GIMP, [PhotoGIMP](https://github.com/Diolinux/PhotoGIMP) and [G'MIC](https://gmic.eu) — into a single download or a single command. This document explains the structure and, more importantly, the decisions behind it.

## The core decision: LazyGimp is a distribution layer, not a build

We do **not** compile or repackage GIMP. Upstream already publishes excellent, signed, up-to-date builds for every platform (Flathub flatpak, official AppImage since 3.0, Windows installer). Rebuilding any of them would duplicate work the GIMP team already does, produce binaries nobody has audited, and break every time upstream changes its build system.

Instead, LazyGimp does two things:

1. **acquire** the newest stable GIMP through the channel best suited to the user's system, plus G'MIC where packaged;
2. **apply** the PhotoGIMP *configuration layer* to whatever config directory that GIMP actually uses.

This keeps the whole project a few hundred lines of shell and PowerShell — small enough to audit, cheap to maintain.

## Repository layout

```
install.sh                       ORCHESTRATOR ONLY: interactive menu → dispatch;
                                 downloads nothing before the user chooses
install_with_package_manager.sh  method: native distro packages (default)
install_with_flatpak.sh          method: Flathub GIMP + G'MIC extension
install_with_appimage.sh         method: official gimp.org AppImage
install_plugins.sh               optional plug-ins (Batcher, Segment Anything)
uninstall.sh                     detect-and-confirm removal of everything we installed
shell_scripts/<distro>.sh        per-distro package logic ONLY (one file per family)
lib/
  common.sh                      logging, root escalation, downloads, distro detection
  gimp.sh                        GIMP version + config-dir resolution (version-agnostic)
  photogimp.sh                   the PhotoGIMP configuration layer (backup + manifest)
  plugins.sh                     the optional plug-ins layer (state-tracked folders)
config/versions.conf             every pinned version/URL, in one place (Renovate-managed)
windows/install-lazygimp.ps1     Windows path (same design, in PowerShell)
scripts/build_release_assets.sh  builds dist/ for a release
tests/*.bats                     unit tests for the resolution and layer logic
.github/workflows/{ci,release}.yml
.releaserc, package.json         semantic-release configuration
```

One script per method, plus a thin orchestrator. Users who know what they want run the method script directly and get its focused `--help`; `install.sh` exists for the `curl | bash` one-liner and for people who want to be guided. The menu runs on `/dev/tty`, so it works even when the script itself arrives through a pipe; with no terminal attached, an explicit `--method` is required — LazyGimp never auto-picks a download channel silently.

Extending to a new distribution means adding one `shell_scripts/<id>.sh` file that defines `lazygimp::install_packages` and `lazygimp::remove_packages` (and optionally `lazygimp::post_install_notes`). The dispatcher matches `/etc/os-release` `ID` first, then every entry of `ID_LIKE`, so derivatives (Manjaro→arch, Mint→ubuntu, Nobara→fedora) work without their own file.

## The PhotoGIMP problem: hardcoded `3.0`

PhotoGIMP ships its payload under `.config/GIMP/3.0/`, but GIMP 3.2 reads `~/.config/GIMP/3.2/`, and 3.4 will read `3.4` (upstream issue [Diolinux/PhotoGIMP#194](https://github.com/Diolinux/PhotoGIMP/issues/194)). LazyGimp never trusts either number. `gimp::config_dir` resolves the real target at runtime:

1. an explicit hint from an installer that already knows what it installed (`LAZYGIMP_GIMP_VERSION_HINT`, used by the AppImage method);
2. the version reported by the installed GIMP itself (`gimp --version`, `flatpak info`);
3. the newest `X.Y` directory already on disk (`sort -V`, so `3.10` > `3.2`);
4. a clear error telling the user to launch GIMP once.

Symmetrically, `photogimp::locate_payload` finds the newest `.config/GIMP/X.Y` *inside* the archive rather than assuming `3.0`. A future GIMP 3.6 with a future PhotoGIMP 3.4 payload needs zero code changes.

### Configuration layer, not a folder copy

Blindly replacing the config directory would destroy user brushes, scripts and preferences. The layer instead:

* takes a **full timestamped backup** (`~/.local/state/lazygimp/backups/…`) before writing anything;
* copies the payload **file by file**, recording each path in `.lazygimp-photogimp.manifest` inside the target;
* on uninstall, removes **only** manifest-listed files and prunes empty dirs — personal files are untouched by construction;
* refuses to target a GIMP 2.x profile (PhotoGIMP is a GIMP 3+ patch).

The manifest also makes upgrades idempotent: re-running the installer rewrites the layer without accumulating stale files.

### The same pattern, reused: optional plug-ins

`lib/plugins.sh` applies the identical design to the plug-ins (Batcher, Segment Anything — installed by default, opt out with `--skip-plugins`/`--no-sam`): resolve the real `plug-ins/` directory at runtime, install each plug-in into its own folder, record every folder in a state manifest, remove exactly those folders on uninstall. Because a plug-in folder is entirely ours, removal is a safe `rm -rf` of tracked paths — user plug-ins are untouched.

Segment Anything's backend — the part upstream leaves to the user — is automated by `lib/segany_backend.sh`: a dedicated venv under `~/.local/share/lazygimp/segany/` with CPU PyTorch wheels (universal, ~10x smaller than CUDA; override via `LAZYGIMP_TORCH_INDEX_URL`), the official SAM package, the `vit_b` checkpoint, and upstream's own bridge self-test as the acceptance gate. The one thing that cannot be automated is GIMP's own per-plugin dialog persistence: on first run the user pastes the two paths the installer prints (and saves to `INFO.txt`); GIMP remembers them afterwards. Resynthesizer (Heal Selection) is included on the flatpak method via its Flathub extension; its engine is a per-platform C binary, so on native/AppImage installs we do not attempt fragile binary drops.

### Uninstall as a first-class citizen

`uninstall.sh` closes the loop: it *detects* what is actually present (native packages, flatpak, AppImage files, PhotoGIMP manifests, plug-in manifests), lists it, and removes what the user confirms — enabling a clean switch between methods. Ordering matters: configuration layers are removed before the GIMP that anchors their config-dir detection. Package removal is delegated to `lazygimp::remove_packages` in the same per-distro files that install them, so the knowledge never spreads.

### Flatpak fonts: applied by default, never silent

A common complaint is that the GIMP flatpak "can't see user fonts". On current flatpak this is mostly outdated — system and user fonts are exposed to the sandbox by default; what may genuinely be missing is a *custom fontconfig configuration*. LazyGimp's goal is "nothing missing out of the box", so the flatpak installer applies a **read-only** override (`flatpak override --user --filesystem=~/.local/share/fonts:ro --filesystem=xdg-config/fontconfig:ro`) by default — but never silently: it logs what it did, records the exact overrides in the state dir, `uninstall.sh` reverts precisely those, and `--no-font-access` opts out. Read-only scope keeps the sandbox widening minimal and harmless.

## Install methods and their trade-offs

| Method | GIMP updates | G'MIC | Why / why not |
|---|---|---|---|
| **Flatpak** (default) | automatic via Flathub | `org.gimp.GIMP.Plugin.GMic` extension | Current GIMP on every distro; the plugin branch is resolved by flatpak itself. |
| **Package manager** | automatic via the distro | distro package where available | What the user asked for when they want system integration. Package names differ (`gimp-plugin-gmic` on Arch, `gmic-gimp` on Fedora/openSUSE, `gimp-gmic` on Debian 13+/Ubuntu 25.04+) — each difference is confined to its `shell_scripts` file. |
| **AppImage** | re-run installer (or self-managed) | manual (warned) | We download the **official** gimp.org AppImage, checksum-verified via `gimp_versions.json`. |
| **Windows** | GIMP's own updater notice | manual (warned) | PowerShell script drives the official installer silently, then applies the layer to `%APPDATA%\GIMP\<X.Y>`. |

### Why we don't build our own Flatpak

Flathub already distributes GIMP and the G'MIC extension. A LazyGimp flatpak would be the same bits under a different ID, invisible to Flathub's update infrastructure, and we would own every security update. Driving `flatpak install` + the config layer achieves the user-visible goal ("one command, ready to use") with none of that liability.

### Why we don't repackage the AppImage

Unpacking the official AppImage, injecting G'MIC and PhotoGIMP, and re-squashing it *works once* and then breaks: the G'MIC binary must match GIMP's ABI, the repack invalidates upstream checksums, and every GIMP release forces a rebuild-and-pray cycle. The official AppImage plus a runtime config layer is strictly more maintainable; G'MIC users on AppImage get a pointed warning with the upstream download page, and the flatpak method as the recommended alternative.

### Why no MSI/EXE for Windows

An unsigned installer triggers SmartScreen warnings scarier than a script; a code-signing certificate costs money and yearly renewal; and an MSI wrapping the upstream EXE adds no capability over `install-lazygimp.ps1`. If a native artifact becomes worthwhile, the maintainable route is a **WinGet manifest** or a **Chocolatey package**, not a homemade MSI. The script is lint-gated in CI (PSScriptAnalyzer) like everything else.

## Release pipeline

Modelled on [MorpheApp/morphe-patches](https://github.com/MorpheApp/morphe-patches): `semantic-release` runs on every push to `main` (and produces `beta` pre-releases from `dev`).

* **Conventional commits** drive everything: `feat` → minor, `fix`/`perf`/`refactor` → patch, `BREAKING CHANGE` → major, `docs`/`chore` → no release (but `docs` shows in the notes of the next release).
* The pipeline bumps the version, regenerates `CHANGELOG.md`, tags, creates the GitHub release, and **backmerges `main` into `dev`**.
* Release assets, built by `scripts/build_release_assets.sh`: `lazygimp.tar.gz` (stable-URL bundle consumed by the `curl | bash` bootstrap), a versioned copy, `install-lazygimp.ps1`, and `checksums.txt`.

The bundle at a stable URL is what makes the one-liner work forever:
`.../releases/latest/download/lazygimp.tar.gz`.

## CI and dependency automation

Every PR runs: `bash -n` + ShellCheck (`--severity=style`, sources followed) on all scripts, bats unit tests on the resolution/layer logic, actionlint on the workflows, and PSScriptAnalyzer on the Windows script.

Renovate keeps three things current with zero manual work: GitHub Actions versions, the semantic-release toolchain in `package.json`, and — via a regex custom manager — every upstream tag pinned in `config/versions.conf` (PhotoGIMP, Batcher, gimpsegany) and in `windows/install-lazygimp.ps1`. A PhotoGIMP bump lands as a `fix:` PR, so merging it automatically publishes a release that ships the new payload. GIMP itself is intentionally *not* pinned anywhere: every method resolves the newest stable at install time.

## Testing philosophy

The risky logic is pure and unit-tested (bats): version parsing, `sort -V` directory resolution, payload discovery, manifest apply/remove, user-file preservation. The distro scripts are thin wrappers around one package-manager call each — CI lints them, and their correctness is trivially reviewable. End-to-end installs in containers for each distro would be nice-to-have; the modular layout makes adding a matrix job straightforward later.

# LazyGimp — Architecture

LazyGimp turns three moving upstream parts — GIMP, [PhotoGIMP](https://github.com/Diolinux/PhotoGIMP) and [G'MIC](https://gmic.eu) — into a single download or a single command. This document explains the structure and, more importantly, the decisions behind it.

## The core decision: LazyGimp is a distribution layer, not a build

We do **not** compile or repackage GIMP. Upstream already publishes excellent, signed, up-to-date builds for every platform (distro packages, the official AppImage since 3.0, the Windows installer). Rebuilding any of them would duplicate work the GIMP team already does, produce binaries nobody has audited, and break every time upstream changes its build system.

Instead, LazyGimp does two things:

1. **acquire** the newest stable GIMP through the channel best suited to the user's system, plus G'MIC where packaged;
2. **apply** the PhotoGIMP *configuration layer* to whatever config directory that GIMP actually uses.

This keeps the whole project a few hundred lines of shell and PowerShell — small enough to audit, cheap to maintain.

## Repository layout

```
install.sh                       ORCHESTRATOR ONLY: interactive menu → dispatch;
                                 downloads nothing before the user chooses
package-manager-install.sh  method: native distro packages (default)
appimage-install.sh         method: official gimp.org AppImage
plugins-install.sh               optional plug-ins (Batcher, Segment Anything)
uninstall.sh                     detect-and-confirm removal of everything we installed
shell_scripts/<distro>.sh        per-distro package logic ONLY (one file per family)
lib/
  common.sh                      logging, root escalation, downloads, distro detection
  gimp.sh                        GIMP version + config-dir resolution (version-agnostic)
  photogimp.sh                   the PhotoGIMP configuration layer (backup + manifest)
  plugins.sh                     the optional plug-ins layer (state-tracked folders)
config/versions.conf             every pinned version/URL, in one place (Renovate-managed)
windows/windows-install.ps1     Windows path (same design, in PowerShell)
scripts/build_release_assets.sh  builds dist/ for a release
tests/*.bats                     unit tests for the resolution and layer logic
.github/workflows/{ci,release}.yml
.releaserc, package.json         semantic-release configuration
```

One script per method, plus a thin orchestrator. Method scripts are **fully unattended** (zero questions — the lazy contract: run, wait, open GIMP); `install.sh` is the only interactive piece, a menu for people who have not chosen a channel yet. The menu runs on `/dev/tty`, so it works even when the script arrives through a pipe; with no terminal attached, an explicit `--method` is required — LazyGimp never auto-picks a download channel silently.

Every entry script carries two small guards: a re-exec shim that tolerates `sh script.sh` (dash, or bash in POSIX mode, which rejects `::` in function names), and a bootstrap block that, when `lib/` is not sitting next to the script, downloads the latest release bundle and re-execs itself from there. That makes each script independently `curl`-able and independently downloadable from a release — the file names (`package-manager-install.sh`, `appimage-install.sh`, `plugins-install.sh`, `uninstall.sh`) are deliberately prefix-distinct for shell autocompletion.

A subtle but critical ordering detail: **GIMP must run once before anything is layered on it**, otherwise its per-user config tree does not exist and there is nothing to target. `gimp::warm_up` launches the freshly installed GIMP headless right after installation (`gimp -i -d -f -s -b '(gimp-quit 0)'` — no UI, no data, *no font-cache build* which can take minutes on a first run, stdin from `/dev/null`, wrapped in `timeout`), so the PhotoGIMP layer and the plug-ins always find a real directory. On Arch, packages are installed with a full `-Syu` because installing against a stale database is both unsupported and a source of mirror 404s.

Extending to a new distribution means adding one `shell_scripts/<id>.sh` file that defines `lazygimp::install_packages` and `lazygimp::remove_packages` (and optionally `lazygimp::post_install_notes`). The dispatcher matches `/etc/os-release` `ID` first, then every entry of `ID_LIKE`, so derivatives (Manjaro→arch, Mint→ubuntu, Nobara→fedora) work without their own file.

## The PhotoGIMP problem: hardcoded `3.0`

PhotoGIMP ships its payload under `.config/GIMP/3.0/`, but a given GIMP reads its own per-user profile dir — and that dir's version namespace is **not** guaranteed to equal the application's `MAJOR.MINOR` (a GIMP reporting `3.2` may still keep its profile under `GIMP/3.0`; see upstream issue [Diolinux/PhotoGIMP#194](https://github.com/Diolinux/PhotoGIMP/issues/194)). Trusting `gimp --version` therefore risks writing the layer into a directory GIMP never opens — the classic "PhotoGIMP installed but nothing changed". LazyGimp never trusts a number when it can observe the truth. `gimp::config_dir` resolves the real target at runtime:

1. an explicit hint from an installer that already knows what it installed (`LAZYGIMP_GIMP_VERSION_HINT`, used by the AppImage method);
2. **the directory GIMP actually reads**, proven by a live `pluginrc` — a file GIMP regenerates on every startup and that the PhotoGIMP layer never ships (`gimp::live_config_dir`). Since `warm_up` guarantees GIMP has run once, this is authoritative;
3. the version reported by the installed GIMP itself (`gimp --version`), for the brief window before that file exists;
4. the newest `X.Y` directory already on disk (`sort -V`, so `3.10` > `3.2`);
5. a clear error telling the user to launch GIMP once.

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

Segment Anything's backend — the part upstream leaves to the user — is automated by `lib/segany_backend.sh`: a dedicated venv under `~/.local/share/lazygimp/segany/` with CPU PyTorch wheels (universal, ~10x smaller than CUDA; override via `LAZYGIMP_TORCH_INDEX_URL`), **both** the SAM1 and SAM2 Python packages, a checkpoint chosen from the `SAM_MODELS` registry (`LAZYGIMP_SAM_MODEL`, default `sam_vit_l`), and upstream's own bridge self-test as the acceptance gate. Installing both backends is not optional: the plug-in's bridge (`seganybridge.py`) imports `sam2` **and** `segment_anything` unconditionally at module load, so a missing package raises `ImportError` and the plug-in silently produces an empty layer group — historically the single most common failure. SAM1 checkpoints are the reliable default because their load path has no Hydra config-file dependency; SAM2 checkpoints are offered but flagged experimental, as this pinned bridge targets an older SAM2 config layout. The one thing that cannot be automated is GIMP's own per-plugin dialog persistence: on first run the user pastes the two paths the installer prints (and saves to `INFO.txt`); GIMP remembers them afterwards.

### Uninstall as a first-class citizen

`uninstall.sh` closes the loop: it *detects* what is actually present (native packages, AppImage files, PhotoGIMP manifests, plug-in manifests), lists it, and removes what the user confirms — enabling a clean switch between methods. Ordering matters: configuration layers are removed before the GIMP that anchors their config-dir detection. Package removal is delegated to `lazygimp::remove_packages` in the same per-distro files that install them, so the knowledge never spreads. `--purge` additionally wipes all GIMP per-user metadata for every version (config/cache/data, plus any leftover flatpak tree under `~/.var/app`) behind a single explicit confirmation.

## Install methods and their trade-offs

| Method | GIMP updates | G'MIC | Why / why not |
|---|---|---|---|
| **Package manager** (default) | automatic via the distro | distro package where available | System integration, the newest GIMP on rolling distros. Package names differ (`gimp-plugin-gmic` on Arch, `gmic-gimp` on Fedora/openSUSE, `gimp-gmic` on Debian 13+/Ubuntu 25.04+) — each difference is confined to its `shell_scripts` file. |
| **AppImage** | re-run installer (or self-managed) | manual (warned) | We download the **official** gimp.org AppImage, checksum-verified via `gimp_versions.json` — the newest GIMP even where the distro repos lag. |
| **Windows** | GIMP's own updater notice | manual (warned) | PowerShell script drives the official installer silently, then applies the layer to `%APPDATA%\GIMP\<X.Y>`. |

### Why Flatpak was dropped

An earlier version offered a Flatpak method. It was removed: the sandbox blocks the very features that make LazyGimp worthwhile. Segment Anything's backend runs an external host Python that the sandbox cannot execute; the headless `warm_up` is unreliable inside the sandbox; and the PhotoGIMP layer landed in a profile the sandboxed GIMP did not reliably read. The two native methods (package manager, AppImage) deliver the full experience without any of that, so keeping Flatpak meant maintaining the one variant where the core value broke.

### Why we don't repackage the AppImage

Unpacking the official AppImage, injecting G'MIC and PhotoGIMP, and re-squashing it *works once* and then breaks: the G'MIC binary must match GIMP's ABI, the repack invalidates upstream checksums, and every GIMP release forces a rebuild-and-pray cycle. The official AppImage plus a runtime config layer is strictly more maintainable; G'MIC users on AppImage get a pointed warning with the upstream download page, and the package-manager method as the alternative where G'MIC is packaged.

### Why no MSI/EXE for Windows

An unsigned installer triggers SmartScreen warnings scarier than a script; a code-signing certificate costs money and yearly renewal; and an MSI wrapping the upstream EXE adds no capability over `windows-install.ps1`. If a native artifact becomes worthwhile, the maintainable route is a **WinGet manifest** or a **Chocolatey package**, not a homemade MSI. The script is lint-gated in CI (PSScriptAnalyzer) like everything else.

## Release pipeline

Modelled on [MorpheApp/morphe-patches](https://github.com/MorpheApp/morphe-patches): `semantic-release` runs on every push to `main` (and produces `beta` pre-releases from `dev`).

* **Conventional commits** drive everything: `feat` → minor, `fix`/`perf`/`refactor` → patch, `BREAKING CHANGE` → major, `docs`/`chore` → no release (but `docs` shows in the notes of the next release).
* The pipeline bumps the version, regenerates `CHANGELOG.md`, tags, creates the GitHub release, and **backmerges `main` into `dev`**.
* Release assets, built by `scripts/build_release_assets.sh`: `lazygimp.tar.gz` (stable-URL bundle consumed by the `curl | bash` bootstrap), a versioned copy, `windows-install.ps1`, and `checksums.txt`.

The bundle at a stable URL is what makes the one-liner work forever:
`.../releases/latest/download/lazygimp.tar.gz`.

## CI and dependency automation

Every PR runs: `bash -n` + ShellCheck (`--severity=style`, sources followed) on all scripts, bats unit tests on the resolution/layer logic, actionlint on the workflows, and PSScriptAnalyzer on the Windows script.

Renovate keeps three things current with zero manual work: GitHub Actions versions, the semantic-release toolchain in `package.json`, and — via a regex custom manager — every upstream tag pinned in `config/versions.conf` (PhotoGIMP, Batcher, gimpsegany) and in `windows/windows-install.ps1`. A PhotoGIMP bump lands as a `fix:` PR, so merging it automatically publishes a release that ships the new payload. GIMP itself is intentionally *not* pinned anywhere: every method resolves the newest stable at install time.

## Testing philosophy

The risky logic is pure and unit-tested (bats): version parsing, `sort -V` directory resolution, payload discovery, manifest apply/remove, user-file preservation. The distro scripts are thin wrappers around one package-manager call each — CI lints them, and their correctness is trivially reviewable. End-to-end installs in containers for each distro would be nice-to-have; the modular layout makes adding a matrix job straightforward later.

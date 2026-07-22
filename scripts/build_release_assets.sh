#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/build_release_assets.sh <version> — assemble everything a GitHub
# release ships, under dist/:
#
#   lazygimp.pyz                single-file zipapp — runs anywhere with
#                               python3 + Tk:  python3 lazygimp.pyz
#                               (the default CustomTkinter GUI only — see
#                               the "PACKAGING DECISION" note below for why
#                               PySide6/--qt does NOT ride inside this one)
#   lazygimp-linux-x86_64       PyInstaller binary — zero dependencies,
#                               Linux x86_64 only, bundles BOTH GUIs
#                               (CustomTkinter default + PySide6 --qt).
#                               Grows measurably once PySide6 is in the
#                               mix (see the PyInstaller step's own
#                               comment below for the actual numbers and
#                               why it's scoped per-submodule, not a
#                               blanket `--collect-all PySide6`).
#   lazygimp-src.zip            the source folder (lazygimp/ package +
#                               installer.py launcher) — unzip and run
#   lazygimp-<version>-src.zip  the same zip, versioned
#   windows-install.ps1         Windows installer script
#   checksums.txt               SHA-256 of every asset
#
# Invoked by semantic-release (@semantic-release/exec, see .releaserc) and
# by the CI dry run. Requires: python3 (+python3-tk for a useful binary),
# pyinstaller, zip, and — new as of the PySide6 rewrite's Phase 3 — the
# packages in requirements-qt.txt (installed just before the PyInstaller
# step below).
#
# STAGE_ONLY=1 skips the PyInstaller step (the slow one): everything else —
# staging, version stamping, zipapp, source zips — still runs, which is
# exactly the part that can break on file moves. The pre-push git hook uses
# this to catch "cannot stat" style failures before CI does.
#
# --- PACKAGING DECISION: PySide6 and the zipapp -----------------------------
# PySide6 is a ~100-150MB compiled wheel (Qt itself, not stdlib) — nothing
# like customtkinter, which is pure Python + font/JSON assets and rides
# inside lazygimp.pyz for free. Two ways to give the zipapp a `--qt` option
# were on the table:
#
#   (a) [CHOSEN] Leave lazygimp.pyz as the zero-dependency fallback it
#       already is — Tk/CustomTkinter only, exactly as before. `--qt` is
#       still importable from the zipapp (lazygimp/gui_qt/ is plain-Python
#       source, harmless dead weight when unused, and it's all inside
#       lazygimp/ already so it rides along with everything else `cp -a`
#       stages), but if PySide6 isn't already on the interpreter running
#       the .pyz, `--qt` fails fast with a one-line "pip install -r
#       requirements-qt.txt" message (see lazygimp/gui_qt/__init__.py's
#       launch_gui_qt()) instead of silently doing something surprising.
#       Users who want Qt from a zipapp-style single file should grab the
#       PyInstaller binary instead, which bundles it.
#   (b) [REJECTED] Have the zipapp `pip install PySide6` itself on first
#       `--qt` use, falling back to Tk if that fails/is declined. Rejected:
#       a ~100MB unattended network install the first time someone
#       double-clicks a *.pyz is exactly the kind of surprise a
#       zero-dependency zipapp exists to avoid — it can fail behind a
#       firewall, silently pick the wrong `pip` (which Python owns the
#       target site-packages when the .pyz was invoked with a random
#       `python3` off $PATH?), or take minutes with no progress indication
#       before the GUI even opens. Explicit and fast-failing (a) is more
#       predictable for someone who just wants the installer to open.
#
# Flag this packaging call out to whoever reviews this branch — it's a
# real product trade-off, not a mechanical porting detail.
# ---------------------------------------------------------------------------
set -euo pipefail

STAGE_ONLY="${STAGE_ONLY:-0}"

VERSION="${1:?usage: build_release_assets.sh <version>}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
DIST="${ROOT}/dist"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

rm -rf "$DIST"
mkdir -p "$DIST"

# --- stage the source tree, stamped with the release version ---------------
BUNDLE="${STAGE}/lazygimp"
mkdir -p "$BUNDLE"
cp -a "${ROOT}/lazygimp" "${ROOT}/installer.py" "$BUNDLE/"

# Docs may live in docs/ or at the repo root — take each from wherever it is.
copy_first() { # <dest-name> <candidate>...
  local dest="$1" candidate
  shift
  for candidate in "$@"; do
    if [[ -e "${ROOT}/${candidate}" ]]; then
      cp -a "${ROOT}/${candidate}" "${BUNDLE}/${dest}"
      return 0
    fi
  done
  echo "error: none of the candidates for '${dest}' exist: $*" >&2
  exit 1
}
copy_first README.md docs/README.md README.md
copy_first LICENSE docs/LICENSE LICENSE

# --- vendor the gimpsam package into the bundle ----------------------------
# LazyGimp is an aggregator: everything SAM comes from pierspad/GIMPSAM.
# A sibling checkout wins (dev builds install what's on disk); otherwise
# the LATEST official GitHub release's gimpsam-src.zip asset — built
# specifically to be consumed here — is fetched, with the main zipball as
# the bootstrap fallback for before that first release exists. Either
# way, a LazyGimp release bundle ships its own gimpsam copy and needs no
# network to resolve it at runtime.
SIBLING="${ROOT}/../GIMPSAM"
vendor_from() { # <dir containing gimpsam/ + plug-in files>
  cp -a "$1/gimpsam" "$1/seganyplugin.py" "$1/seganybridge.py" "$BUNDLE/"
}
if [[ -f "${SIBLING}/gimpsam/__init__.py" ]]; then
  echo "vendoring gimpsam from sibling checkout ${SIBLING}"
  vendor_from "$SIBLING"
else
  GS_TMP="${STAGE}/gimpsam-src"
  mkdir -p "$GS_TMP"

  # Build the Authorization header if a token is available (CI sets
  # GITHUB_TOKEN; local dev falls back to unauthenticated, which has a
  # lower rate-limit but works fine for infrequent local builds).
  GH_AUTH_HEADER=()
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    GH_AUTH_HEADER=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
  fi

  GS_URL="$(curl -fsSL -H 'User-Agent: LazyGimp-build' \
      "${GH_AUTH_HEADER[@]+${GH_AUTH_HEADER[@]}}" \
      "https://api.github.com/repos/pierspad/GIMPSAM/releases/latest" 2>/dev/null \
    | python3 -c "
import json, sys
try:
    release = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for asset in release.get('assets', []):
    if asset.get('name') == 'gimpsam-src.zip':
        print(asset['browser_download_url'])
        break" || true)"
  if [[ -n "$GS_URL" ]]; then
    echo "vendoring gimpsam from the latest GIMPSAM release: ${GS_URL}"
    curl -fsSL "${GH_AUTH_HEADER[@]+${GH_AUTH_HEADER[@]}}" \
      "$GS_URL" -o "${GS_TMP}/gimpsam.zip"
  else
    echo "vendoring gimpsam from pierspad/GIMPSAM@main (no release asset or rate-limited)"
    curl -fsSL "https://github.com/pierspad/GIMPSAM/archive/main.zip" -o "${GS_TMP}/gimpsam.zip"
  fi
  (cd "$GS_TMP" && unzip -q gimpsam.zip)
  GS_ROOT="$(dirname "$(dirname "$(find "$GS_TMP" -path '*/gimpsam/__init__.py' | head -1)")")"
  vendor_from "$GS_ROOT"
fi

find "$BUNDLE" -name '__pycache__' -type d -exec rm -rf {} +

sed -i "s/^__version__ = .*/__version__ = \"${VERSION}\"/" \
  "${BUNDLE}/lazygimp/__init__.py"

# --- 1. zipapp: one .pyz file, runs on any python3 with Tk -----------------
# Tk/CustomTkinter (the default GUI) only — see the "PACKAGING DECISION"
# note up top for why PySide6 (--qt) is deliberately NOT bundled/installed
# here. lazygimp/gui_qt/ still gets staged along with the rest of the
# lazygimp package below (it's plain-Python source, no extra weight to
# speak of) so `--qt` at least fails with a clear, fast message rather than
# an ImportError stack trace if someone tries it without PySide6 installed.
PYZ_STAGE="${STAGE}/pyz"
mkdir -p "$PYZ_STAGE"
cp -a "${BUNDLE}/lazygimp" "${BUNDLE}/gimpsam" "$PYZ_STAGE/"
python3 -m zipapp "$PYZ_STAGE" \
  --main "lazygimp.cli:main" \
  --python "/usr/bin/env python3" \
  --output "${DIST}/lazygimp.pyz" \
  --compress
chmod +x "${DIST}/lazygimp.pyz"

# --- 2. PyInstaller: self-contained Linux binary ---------------------------
# customtkinter (pure python + json/font assets), Pillow AND PySide6/Qt now
# all ship inside the binary, so the downloaded file needs nothing at all on
# the host system for either GUI (--qt or default).
#
# PySide6 is collected per-submodule (QtCore/QtGui/QtWidgets — the only
# three lazygimp/gui_qt/ actually imports; verified with
# `grep -rhoE "from PySide6\.[A-Za-z0-9_]+" lazygimp/gui_qt`) rather than a
# blanket `--collect-all PySide6`. That blanket form pulls in EVERYTHING in
# the wheel — QtWebEngine, Qt Quick/QML, Multimedia, Bluetooth, PDF, SQL,
# ... — none of which this app uses; measured locally it bloats the binary
# to ~750MB+ for zero benefit. The scoped form below still pulls in
# everything QtCore/QtGui/QtWidgets need at runtime (platform plugins,
# styles, etc. — PyInstaller's own PySide6 hooks handle that), just not the
# unrelated modules. Measured locally (--onedir, uncompressed): ~220MB,
# roughly 650MB less than the blanket approach; the final --onefile binary
# here compresses further. Re-verify this if lazygimp/gui_qt/ ever starts
# importing from another PySide6 submodule (QtSvg, QtNetwork, ...) — add it
# to the three --collect-all lines below, don't switch back to the blanket
# form.
#
# PySide6 itself is NOT pip-installed by this script (same convention as
# pyinstaller/customtkinter/pillow, none of which this script installs
# either) — the caller is responsible for having requirements-qt.txt
# installed first. See .github/workflows/ci.yml's `build` job and
# .github/workflows/release.yml's "Install asset build prerequisites"
# step for where that happens in practice.
[[ "$STAGE_ONLY" == "1" ]] || pyinstaller --onefile --clean --noconfirm \
  --name "lazygimp-linux-x86_64" \
  --distpath "$DIST" \
  --workpath "${STAGE}/pyi-build" \
  --specpath "${STAGE}/pyi-spec" \
  --paths "$BUNDLE" \
  --hidden-import tkinter \
  --hidden-import gimpsam \
  --hidden-import gimpsam.constants \
  --hidden-import gimpsam.models \
  --hidden-import gimpsam.hardware \
  --hidden-import gimpsam.backend \
  --hidden-import gimpsam.sam3 \
  --hidden-import gimpsam.plugin \
  --hidden-import gimpsam.gimp_dirs \
  --hidden-import gimpsam.compat \
  --hidden-import gimpsam.job \
  --hidden-import gimpsam.plan \
  --hidden-import gimpsam.util \
  --collect-submodules gimpsam \
  --collect-all customtkinter \
  --collect-submodules PIL \
  --collect-submodules lazygimp.gui_qt \
  --collect-all PySide6.QtCore \
  --collect-all PySide6.QtGui \
  --collect-all PySide6.QtWidgets \
  "${BUNDLE}/installer.py"

# --- 3. source zip: the folder with everything needed to run ---------------
(cd "$STAGE" && zip -qr "${DIST}/lazygimp-src.zip" lazygimp \
  -x 'lazygimp/lazygimp/__pycache__/*')
cp "${DIST}/lazygimp-src.zip" "${DIST}/lazygimp-${VERSION}-src.zip"

# --- 4. Windows installer script -------------------------------------------
cp "${ROOT}/windows/windows-install.ps1" "${DIST}/"

(cd "$DIST" && sha256sum -- * >checksums.txt)

echo "release assets for v${VERSION}:"
ls -l "$DIST"

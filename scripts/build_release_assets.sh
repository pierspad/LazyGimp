#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/build_release_assets.sh <version> — assemble everything a GitHub
# release ships, under dist/:
#
#   lazygimp.pyz                single-file zipapp — runs anywhere with
#                               python3 + Tk:  python3 lazygimp.pyz
#   lazygimp-linux-x86_64       PyInstaller binary — zero dependencies,
#                               Linux x86_64 only
#   lazygimp-src.zip            the source folder (lazygimp/ package +
#                               installer.py launcher) — unzip and run
#   lazygimp-<version>-src.zip  the same zip, versioned
#   windows-install.ps1         Windows installer script
#   checksums.txt               SHA-256 of every asset
#
# Invoked by semantic-release (@semantic-release/exec, see .releaserc) and
# by the CI dry run. Requires: python3 (+python3-tk for a useful binary),
# pyinstaller, zip.
#
# STAGE_ONLY=1 skips the PyInstaller step (the slow one): everything else —
# staging, version stamping, zipapp, source zips — still runs, which is
# exactly the part that can break on file moves. The pre-push git hook uses
# this to catch "cannot stat" style failures before CI does.
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
  GS_URL="$(curl -fsSL -H 'User-Agent: LazyGimp-build' \
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
        break")"
  if [[ -n "$GS_URL" ]]; then
    echo "vendoring gimpsam from the latest GIMPSAM release: ${GS_URL}"
    curl -fsSL "$GS_URL" -o "${GS_TMP}/gimpsam.zip"
  else
    echo "vendoring gimpsam from pierspad/GIMPSAM@main (no release asset yet)"
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
# customtkinter (pure python + json/font assets) and Pillow ship inside the
# binary, so the downloaded file needs nothing at all on the host system.
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

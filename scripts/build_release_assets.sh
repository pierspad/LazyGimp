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
#                               lazygimp.py launcher) — unzip and run
#   lazygimp-<version>-src.zip  the same zip, versioned
#   windows-install.ps1         Windows installer script
#   checksums.txt               SHA-256 of every asset
#
# Invoked by semantic-release (@semantic-release/exec, see .releaserc) and
# by the CI dry run. Requires: python3 (+python3-tk for a useful binary),
# pyinstaller, zip.
# ---------------------------------------------------------------------------
set -euo pipefail

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
cp -a "${ROOT}/lazygimp" "${ROOT}/lazygimp.py" "$BUNDLE/"
cp -a "${ROOT}/docs/README.md" "${ROOT}/docs/LICENSE" "$BUNDLE/" 2>/dev/null ||
  cp -a "${ROOT}/README.md" "${ROOT}/LICENSE" "$BUNDLE/"
find "$BUNDLE" -name '__pycache__' -type d -exec rm -rf {} +

sed -i "s/^__version__ = .*/__version__ = \"${VERSION}\"/" \
  "${BUNDLE}/lazygimp/__init__.py"

# --- 1. zipapp: one .pyz file, runs on any python3 with Tk -----------------
PYZ_STAGE="${STAGE}/pyz"
mkdir -p "$PYZ_STAGE"
cp -a "${BUNDLE}/lazygimp" "$PYZ_STAGE/"
python3 -m zipapp "$PYZ_STAGE" \
  --main "lazygimp.cli:main" \
  --python "/usr/bin/env python3" \
  --output "${DIST}/lazygimp.pyz" \
  --compress
chmod +x "${DIST}/lazygimp.pyz"

# --- 2. PyInstaller: self-contained Linux binary ---------------------------
pyinstaller --onefile --clean --noconfirm \
  --name "lazygimp-linux-x86_64" \
  --distpath "$DIST" \
  --workpath "${STAGE}/pyi-build" \
  --specpath "${STAGE}/pyi-spec" \
  --paths "$BUNDLE" \
  --hidden-import tkinter \
  "${BUNDLE}/lazygimp.py"

# --- 3. source zip: the folder with everything needed to run ---------------
(cd "$STAGE" && zip -qr "${DIST}/lazygimp-src.zip" lazygimp \
  -x 'lazygimp/lazygimp/__pycache__/*')
cp "${DIST}/lazygimp-src.zip" "${DIST}/lazygimp-${VERSION}-src.zip"

# --- 4. Windows installer script -------------------------------------------
cp "${ROOT}/windows/windows-install.ps1" "${DIST}/"

(cd "$DIST" && sha256sum -- * >checksums.txt)

echo "release assets for v${VERSION}:"
ls -l "$DIST"

#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/build_release_assets.sh <version> — assemble everything a GitHub
# release ships, under dist/:
#
#   lazygimp.tar.gz             installer bundle, stable URL used by the
#                               `curl | bash` bootstrap ("latest" alias)
#   lazygimp-<version>.tar.gz   the same bundle, versioned
#   install-lazygimp.ps1        Windows installer script
#   checksums.txt               SHA-256 of every asset
#
# Invoked by semantic-release (@semantic-release/exec, see .releaserc).
# ---------------------------------------------------------------------------
set -euo pipefail

VERSION="${1:?usage: build_release_assets.sh <version>}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
DIST="${ROOT}/dist"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

rm -rf "$DIST"
mkdir -p "$DIST" "${STAGE}/lazygimp"

cp -a \
  "${ROOT}/install.sh" \
  "${ROOT}/install_with_package_manager.sh" \
  "${ROOT}/lib" \
  "${ROOT}/shell_scripts" \
  "${ROOT}/config" \
  "${ROOT}/LICENSE" \
  "${ROOT}/README.md" \
  "${STAGE}/lazygimp/"

# Stamp the release version into the bundled installer.
sed -i "s/^LAZYGIMP_VERSION=.*/LAZYGIMP_VERSION=\"${VERSION}\"/" \
  "${STAGE}/lazygimp/install.sh"

tar -czf "${DIST}/lazygimp.tar.gz" -C "$STAGE" lazygimp
cp "${DIST}/lazygimp.tar.gz" "${DIST}/lazygimp-${VERSION}.tar.gz"
cp "${ROOT}/windows/install-lazygimp.ps1" "${DIST}/"

(cd "$DIST" && sha256sum -- * >checksums.txt)

echo "release assets for v${VERSION}:"
ls -l "$DIST"

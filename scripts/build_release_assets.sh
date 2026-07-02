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

BUNDLE="${STAGE}/lazygimp"
rm -rf "$DIST"
mkdir -p "$DIST" "$BUNDLE"

# Copy the first existing candidate; fail loudly listing what was tried.
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

# Everything the installer needs at runtime.
cp -a \
  "${ROOT}/install.sh" \
  "${ROOT}/install_with_package_manager.sh" \
  "${ROOT}/install_with_flatpak.sh" \
  "${ROOT}/install_with_appimage.sh" \
  "${ROOT}/install_plugins.sh" \
  "${ROOT}/uninstall.sh" \
  "${ROOT}/lib" \
  "${ROOT}/shell_scripts" \
  "${ROOT}/config" \
  "$BUNDLE/"

# Docs live under docs/ in this repository, but tolerate a root layout too.
copy_first LICENSE docs/LICENSE LICENSE
copy_first README.md docs/README.md README.md

# Stamp the release version into the bundled installer.
sed -i "s/^LAZYGIMP_VERSION=.*/LAZYGIMP_VERSION=\"${VERSION}\"/" \
  "${BUNDLE}/install.sh"

tar -czf "${DIST}/lazygimp.tar.gz" -C "$STAGE" lazygimp
cp "${DIST}/lazygimp.tar.gz" "${DIST}/lazygimp-${VERSION}.tar.gz"
cp "${ROOT}/windows/install-lazygimp.ps1" "${DIST}/"

(cd "$DIST" && sha256sum -- * >checksums.txt)

echo "release assets for v${VERSION}:"
ls -l "$DIST"

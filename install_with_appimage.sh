#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install_with_appimage.sh — download the *official* GIMP AppImage published
# by gimp.org, verify its checksum, and apply the PhotoGIMP layer.
#
# We deliberately do NOT repackage our own AppImage: gimp.org has shipped
# official AppImages since GIMP 3.0, and injecting binaries (G'MIC) into a
# repacked image is ABI-fragile and a maintenance trap. Rationale in
# docs/ARCHITECTURE.md.
#
# Usage:
#   ./install_with_appimage.sh [--skip-photogimp] [--uninstall-photogimp]
#
# The AppImage lands in ~/Applications (override: LAZYGIMP_APPIMAGE_DIR).
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
# shellcheck source=lib/photogimp.sh
source "${SCRIPT_DIR}/lib/photogimp.sh"

usage() {
  cat <<EOF
LazyGimp — official gimp.org AppImage installer

Usage: ${0##*/} [options]

Options:
  --skip-photogimp        do not apply the PhotoGIMP configuration layer
  --skip-plugins          do not install the optional plug-ins (Batcher, SAM)
  --no-sam                install Batcher but skip Segment Anything (~1 GB)
  --uninstall-photogimp   remove the PhotoGIMP layer (personal files are kept)
  -h, --help              show this help

Environment:
  LAZYGIMP_APPIMAGE_DIR   destination directory (default: ~/Applications)

By default EVERYTHING is set up: GIMP + PhotoGIMP + Batcher + Segment
Anything with its automated Python backend (G'MIC needs a manual step on
AppImage — see the note printed at the end).
EOF
}

SKIP_PHOTOGIMP="${LAZYGIMP_SKIP_PHOTOGIMP:-0}"
SKIP_PLUGINS="${LAZYGIMP_SKIP_PLUGINS:-0}"
NO_SAM="${LAZYGIMP_NO_SAM:-0}"
while (($#)); do
  case "$1" in
    --skip-photogimp) SKIP_PHOTOGIMP=1 ;;
    --skip-plugins) SKIP_PLUGINS=1 ;;
    --no-sam) NO_SAM=1 ;;
    --uninstall-photogimp)
      photogimp::uninstall native
      exit 0
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
  shift
done

# Query gimp.org's version metadata; echo "version filename sha256" for the
# newest stable AppImage matching this machine's architecture.
latest_appimage_info() {
  require python3
  local arch
  arch="$(uname -m)"
  fetch "${GIMP_VERSIONS_JSON_URL}" | python3 -c '
import json, sys

arch = sys.argv[1]
data = json.load(sys.stdin)
for release in data.get("STABLE", []):
    for image in release.get("appimage", []):
        if arch in image.get("filename", ""):
            print(release["version"], image["filename"], image["sha256"])
            sys.exit(0)
sys.exit(1)
' "$arch"
}

main() {
  local info version filename sha256 series url dest_dir dest
  if ! info="$(latest_appimage_info)"; then
    die "no official GIMP AppImage published for architecture $(uname -m)"
  fi
  read -r version filename sha256 <<<"$info"

  series="${version%.*}" # 3.2.4 → 3.2
  url="${GIMP_DOWNLOAD_MIRROR}/v${series}/linux/${filename}"
  dest_dir="${LAZYGIMP_APPIMAGE_DIR:-${HOME}/Applications}"
  dest="${dest_dir}/${filename}"

  mkdir -p "$dest_dir"
  download "$url" "$dest"
  sha256_verify "$dest" "$sha256"
  chmod +x "$dest"
  ln -sf "$filename" "${dest_dir}/GIMP.AppImage"
  log::ok "GIMP ${version} AppImage installed at ${dest} (symlink: GIMP.AppImage)"

  if [[ "$SKIP_PHOTOGIMP" != 1 ]]; then
    # The AppImage is not on PATH, but we know exactly which version we
    # just downloaded — pass it as a hint to the config-dir resolver.
    if ! (LAZYGIMP_GIMP_VERSION_HINT="$version" photogimp::install native); then
      log::warn "PhotoGIMP layer not applied (see message above); GIMP itself is installed"
    fi
  fi

  if [[ "$SKIP_PLUGINS" != 1 ]]; then
    local plugin_args=(--kind native --batcher)
    if [[ "$NO_SAM" != 1 ]]; then
      plugin_args+=(--segment-anything)
    fi
    if ! LAZYGIMP_GIMP_VERSION_HINT="$version" \
      "${SCRIPT_DIR}/install_plugins.sh" "${plugin_args[@]}"; then
      log::warn "plug-ins step failed — re-run it later with: ./install_plugins.sh"
    fi
  fi

  log::warn "G'MIC cannot be bundled into the official AppImage safely;"
  log::warn "grab the GIMP plugin build from ${GMIC_DOWNLOAD_PAGE} if you need it,"
  log::warn "or prefer ./install_with_flatpak.sh which includes G'MIC."
}

main

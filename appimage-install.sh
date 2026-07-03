#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# appimage-install.sh — download the *official* GIMP AppImage published by
# gimp.org, verify its checksum, then everything else: headless first
# launch, PhotoGIMP layer, Batcher, Segment Anything. Fully unattended.
#
# We deliberately do NOT repackage our own AppImage: gimp.org has shipped
# official AppImages since GIMP 3.0, and injecting binaries (G'MIC) into a
# repacked image is ABI-fragile and a maintenance trap. Rationale in
# docs/ARCHITECTURE.md.
#
# Usage:
#   ./appimage-install.sh [--skip-photogimp] [--skip-plugins] [--no-sam]
#
# Piped usage (no checkout needed):
#   curl -fsSL https://raw.githubusercontent.com/pierspad/LazyGimp/main/appimage-install.sh | bash
#
# The AppImage lands in ~/Applications (override: LAZYGIMP_APPIMAGE_DIR).
# ---------------------------------------------------------------------------

# Tolerate being launched with `sh script.sh` (dash, or bash in POSIX mode,
# which rejects function names containing '::'): re-exec under real bash.
if [ -f "${0:-}" ]; then
  if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
  if shopt -qo posix 2>/dev/null; then exec bash "$0" "$@"; fi
fi

set -euo pipefail

LAZYGIMP_REPO_SLUG="${LAZYGIMP_REPO_SLUG:-pierspad/LazyGimp}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"

# Standalone download or `curl | bash`: fetch the release bundle and re-exec.
if [[ ! -d "${SCRIPT_DIR}/lib" ]]; then
  bootstrap_dir="$(mktemp -d "${TMPDIR:-/tmp}/lazygimp-bootstrap.XXXXXX")"
  trap 'rm -rf "$bootstrap_dir"' EXIT
  echo "[info] fetching the latest LazyGimp bundle..." >&2
  curl -fsSL "https://github.com/${LAZYGIMP_REPO_SLUG}/releases/latest/download/lazygimp.tar.gz" |
    tar -xz -C "$bootstrap_dir"
  exec bash "${bootstrap_dir}/lazygimp/appimage-install.sh" "$@"
fi

# shellcheck source=lib/photogimp.sh
source "${SCRIPT_DIR}/lib/photogimp.sh"

usage() {
  cat <<EOF
LazyGimp — official gimp.org AppImage installer (fully unattended)

Usage: ${0##*/} [options]

Options:
  --skip-photogimp        do not apply the PhotoGIMP configuration layer
  --skip-plugins          do not install the plug-ins (Batcher, SAM)
  --no-sam                install Batcher but skip Segment Anything (~1 GB)
  --uninstall-photogimp   remove the PhotoGIMP layer (personal files are kept)
  -h, --help              show this help

Environment:
  LAZYGIMP_APPIMAGE_DIR   destination directory (default: ~/Applications)

By default EVERYTHING is set up, no questions asked: GIMP + PhotoGIMP +
Batcher + Segment Anything (G'MIC needs a manual step on AppImage — see
the note printed at the end).
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
  # Idempotent: if this exact AppImage is already present and intact, reuse it.
  if [[ -f "$dest" ]] && [[ "$(sha256sum "$dest" | awk '{print $1}')" == "$sha256" ]]; then
    log::info "GIMP ${version} AppImage already present and verified — skipping download"
  else
    download "$url" "$dest"
    sha256_verify "$dest" "$sha256"
  fi
  chmod +x "$dest"
  ln -sf "$filename" "${dest_dir}/GIMP.AppImage"
  log::ok "GIMP ${version} AppImage installed at ${dest} (symlink: GIMP.AppImage)"

  # GIMP must run once to generate its config tree before we layer on it.
  gimp::warm_up native "$dest"

  if [[ "$SKIP_PHOTOGIMP" != 1 ]]; then
    # The AppImage is not on PATH: hint the exact version to the config-dir
    # resolver and make the desktop entry launch the AppImage itself.
    if ! (LAZYGIMP_GIMP_VERSION_HINT="$version" \
      LAZYGIMP_GIMP_COMMAND="${dest_dir}/GIMP.AppImage" photogimp::install native); then
      log::warn "PhotoGIMP layer not applied (see message above); GIMP itself is installed"
    fi
  fi

  if [[ "$SKIP_PLUGINS" != 1 ]]; then
    local plugin_args=(--kind native --batcher)
    if [[ "$NO_SAM" != 1 ]]; then
      plugin_args+=(--segment-anything)
    fi
    if ! LAZYGIMP_GIMP_VERSION_HINT="$version" \
      "${SCRIPT_DIR}/plugins-install.sh" "${plugin_args[@]}"; then
      log::warn "plug-ins step failed — re-run it later with: ./plugins-install.sh"
    fi
  fi

  log::warn "G'MIC cannot be bundled into the official AppImage safely;"
  log::warn "grab the GIMP plugin build from ${GMIC_DOWNLOAD_PAGE} if you need it,"
  log::warn "or use ./package-manager-install.sh where G'MIC comes from your distro."
}

main

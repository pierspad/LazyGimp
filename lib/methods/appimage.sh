#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# lib/methods/appimage.sh — download the *official* GIMP AppImage published
# by gimp.org, verify its checksum, and apply the PhotoGIMP layer.
#
# We deliberately do NOT repackage our own AppImage: gimp.org has shipped
# official AppImages since GIMP 3.0, and injecting binaries (G'MIC) into a
# repacked image is ABI-fragile and a maintenance trap. Rationale in
# docs/ARCHITECTURE.md.
# ---------------------------------------------------------------------------

if [[ -n "${_LAZYGIMP_METHOD_APPIMAGE_LOADED:-}" ]]; then return 0; fi
readonly _LAZYGIMP_METHOD_APPIMAGE_LOADED=1

# shellcheck source=lib/photogimp.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/../photogimp.sh"

# Query gimp.org's version metadata; echo "version filename sha256" for the
# newest stable AppImage matching this machine's architecture.
method_appimage::latest_info() {
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

method_appimage::install() {
  local info version filename sha256 series url dest_dir dest
  if ! info="$(method_appimage::latest_info)"; then
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

  if [[ "${LAZYGIMP_SKIP_PHOTOGIMP:-0}" != 1 ]]; then
    # The AppImage is not on PATH, but we know exactly which version we
    # just downloaded — pass it as a hint to the config-dir resolver.
    LAZYGIMP_GIMP_VERSION_HINT="$version" photogimp::install native
  fi

  log::warn "G'MIC cannot be bundled into the official AppImage safely;"
  log::warn "grab the GIMP plugin build from ${GMIC_DOWNLOAD_PAGE} if you need it,"
  log::warn "or prefer './install.sh --method flatpak' which includes G'MIC."
}

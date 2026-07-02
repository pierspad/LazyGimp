#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install_with_flatpak.sh — install GIMP + G'MIC from Flathub, then apply
# the PhotoGIMP layer to the flatpak's sandboxed config directory.
#
# Best choice on distributions whose repositories lag behind upstream
# (Debian stable, Ubuntu LTS): Flathub ships current GIMP everywhere and
# updates flow through the system's flatpak updater.
#
# Usage:
#   ./install_with_flatpak.sh [--skip-photogimp] [--uninstall-photogimp]
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
# shellcheck source=lib/photogimp.sh
source "${SCRIPT_DIR}/lib/photogimp.sh"

usage() {
  cat <<EOF
LazyGimp — Flatpak installer (Flathub)

Usage: ${0##*/} [options]

Options:
  --skip-photogimp        install GIMP and G'MIC only
  --font-access           grant the sandbox read access to ~/.local/share/fonts
                          and your fontconfig configuration (opt-in; see note)
  --uninstall-photogimp   remove the PhotoGIMP layer (personal files are kept)
  -h, --help              show this help

Note on --font-access:
  Recent flatpak already exposes system AND user fonts to GIMP, so most
  people need nothing. Pass --font-access only if a custom fontconfig setup
  of yours is not picked up. The override is recorded and can be reverted
  with ./uninstall.sh (or: flatpak override --user --reset org.gimp.GIMP).
EOF
}

# Grant the GIMP flatpak read access to user fonts + fontconfig, recording
# exactly what was applied so uninstall.sh can revert it precisely.
apply_font_overrides() {
  local state="${LAZYGIMP_STATE_DIR}/flatpak-font-overrides" fs
  mkdir -p "${LAZYGIMP_STATE_DIR}"
  : >"$state"
  # shellcheck disable=SC2088  # the literal ~ is intentional: flatpak expands it
  for fs in '~/.local/share/fonts:ro' 'xdg-config/fontconfig:ro'; do
    flatpak override --user --filesystem="$fs" "${GIMP_FLATPAK_ID}"
    printf '%s\n' "$fs" >>"$state"
  done
  log::ok "sandbox override applied: GIMP can read ~/.local/share/fonts and your fontconfig"
  log::info "recorded in ${state} — revert with ./uninstall.sh"
}

SKIP_PHOTOGIMP="${LAZYGIMP_SKIP_PHOTOGIMP:-0}"
FONT_ACCESS=0
while (($#)); do
  case "$1" in
    --skip-photogimp) SKIP_PHOTOGIMP=1 ;;
    --font-access) FONT_ACCESS=1 ;;
    --uninstall-photogimp)
      photogimp::uninstall flatpak
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

main() {
  have flatpak ||
    die "flatpak is not installed — install it from your package manager first \
(e.g. 'sudo apt install flatpak'), or use ./install_with_package_manager.sh"

  if ! flatpak remotes --columns=name 2>/dev/null | grep -qx flathub; then
    log::info "adding the flathub remote (user scope)"
    flatpak remote-add --user --if-not-exists flathub \
      https://dl.flathub.org/repo/flathub.flatpakrepo
  fi

  log::info "installing ${GIMP_FLATPAK_ID} from flathub"
  flatpak install -y flathub "${GIMP_FLATPAK_ID}"

  # The G'MIC plugin ships as a flatpak *extension*; flatpak resolves the
  # branch matching the installed GIMP automatically.
  if ! flatpak install -y flathub "${GMIC_FLATPAK_ID}"; then
    log::warn "G'MIC flatpak extension not available for this GIMP branch yet"
    log::warn "you can install it manually later: flatpak install flathub ${GMIC_FLATPAK_ID}"
  fi

  if [[ "$SKIP_PHOTOGIMP" != 1 ]]; then
    if ! (photogimp::install flatpak); then
      log::warn "PhotoGIMP layer not applied (see message above); GIMP itself is installed"
    fi
  fi

  if ((FONT_ACCESS)); then
    apply_font_overrides
  else
    log::info "fonts: system and user fonts are normally visible to the flatpak already;"
    log::info "if a custom fontconfig setup is missing, re-run with --font-access"
  fi

  log::ok "flatpak setup complete — launch GIMP from your app menu"
  log::info "optional plug-ins (Batcher, Segment Anything): ./install_plugins.sh"
}

main

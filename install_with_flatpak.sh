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
  --skip-photogimp        do not apply the PhotoGIMP configuration layer
  --skip-plugins          do not install the optional plug-ins (Batcher, SAM)
  --no-sam                install Batcher but skip Segment Anything (~1 GB)
  --no-font-access        do not apply the font sandbox override (see note)
  --uninstall-photogimp   remove the PhotoGIMP layer (personal files are kept)
  -h, --help              show this help

By default EVERYTHING is set up: GIMP + G'MIC + PhotoGIMP + Batcher +
Segment Anything with its automated Python backend.

Note on fonts:
  Recent flatpak already exposes system AND user fonts to GIMP. To make
  sure nothing is ever missing (e.g. custom fontconfig setups), LazyGimp
  additionally grants the sandbox READ-ONLY access to ~/.local/share/fonts
  and ~/.config/fontconfig. This is logged, recorded, and reverted by
  ./uninstall.sh. Pass --no-font-access to skip it.
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
SKIP_PLUGINS="${LAZYGIMP_SKIP_PLUGINS:-0}"
NO_SAM="${LAZYGIMP_NO_SAM:-0}"
FONT_ACCESS=1
while (($#)); do
  case "$1" in
    --skip-photogimp) SKIP_PHOTOGIMP=1 ;;
    --skip-plugins) SKIP_PLUGINS=1 ;;
    --no-sam) NO_SAM=1 ;;
    --font-access) FONT_ACCESS=1 ;; # kept for compatibility (now the default)
    --no-font-access) FONT_ACCESS=0 ;;
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

  # Plug-ins ship as flatpak *extensions*; flatpak resolves the branch
  # matching the installed GIMP automatically.
  local ext
  for ext in "${GMIC_FLATPAK_ID}" "${RESYNTH_FLATPAK_ID}"; do
    if ! flatpak install -y flathub "$ext"; then
      log::warn "${ext##*.} flatpak extension not available for this GIMP branch yet"
      log::warn "install it manually later: flatpak install flathub ${ext}"
    fi
  done

  if [[ "$SKIP_PHOTOGIMP" != 1 ]]; then
    if ! (photogimp::install flatpak); then
      log::warn "PhotoGIMP layer not applied (see message above); GIMP itself is installed"
    fi
  fi

  if ((FONT_ACCESS)); then
    apply_font_overrides
  else
    log::info "font sandbox override skipped (--no-font-access)"
  fi

  if [[ "$SKIP_PLUGINS" != 1 ]]; then
    local plugin_args=(--kind flatpak --batcher)
    if [[ "$NO_SAM" != 1 ]]; then
      plugin_args+=(--segment-anything)
    fi
    if ! "${SCRIPT_DIR}/install_plugins.sh" "${plugin_args[@]}"; then
      log::warn "plug-ins step failed — re-run it later with: ./install_plugins.sh"
    fi
  fi

  log::ok "flatpak setup complete — launch GIMP from your app menu"
}

main

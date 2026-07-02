#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# lib/methods/flatpak.sh — install GIMP + G'MIC from Flathub, then apply
# the PhotoGIMP layer to the flatpak's sandboxed config directory.
#
# This is the recommended method: Flathub ships current GIMP for every
# distro and updates flow automatically through the user's flatpak updater.
# ---------------------------------------------------------------------------

if [[ -n "${_LAZYGIMP_METHOD_FLATPAK_LOADED:-}" ]]; then return 0; fi
readonly _LAZYGIMP_METHOD_FLATPAK_LOADED=1

# shellcheck source=lib/photogimp.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/../photogimp.sh"

method_flatpak::install() {
  require flatpak

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

  if [[ "${LAZYGIMP_SKIP_PHOTOGIMP:-0}" != 1 ]]; then
    photogimp::install flatpak
  fi

  log::ok "flatpak setup complete — launch GIMP from your app menu"
}

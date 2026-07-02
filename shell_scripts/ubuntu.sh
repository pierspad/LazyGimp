#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# shell_scripts/ubuntu.sh — Ubuntu and derivatives (matched through
# ID=ubuntu or ID_LIKE containing "ubuntu", e.g. Linux Mint, Pop!_OS).
#
# GIMP 3.x entered the Ubuntu archive with 25.04 ("plucky"); on older
# releases the archive still ships GIMP 2.10, for which PhotoGIMP does not
# apply — the script detects that and points users to the flatpak method.
#
# Sourced by install_with_package_manager.sh. Contract: define
# lazygimp::install_packages (required) and lazygimp::post_install_notes
# (optional). Distro-specific knowledge stays confined to this file.
# ---------------------------------------------------------------------------

lazygimp::install_packages() {
  as_root apt-get update
  as_root apt-get install -y gimp

  # gimp-gmic exists in the archive from Ubuntu 25.04 onwards.
  if apt-cache show gimp-gmic >/dev/null 2>&1; then
    as_root apt-get install -y gimp-gmic
  else
    log::warn "package 'gimp-gmic' is not available on this release — skipping G'MIC"
    log::warn "alternatives: upgrade to Ubuntu 25.04+, or run './install.sh --method flatpak'"
  fi
}

lazygimp::remove_packages() {
  local pkgs=() p
  for p in gimp-gmic gimp; do
    dpkg -s "$p" >/dev/null 2>&1 && pkgs+=("$p")
  done
  if ((${#pkgs[@]})); then
    as_root apt-get remove -y "${pkgs[@]}"
    as_root apt-get autoremove -y
  else
    log::info "no LazyGimp packages installed via apt"
  fi
}

lazygimp::post_install_notes() {
  local candidate
  candidate="$(apt-cache policy gimp 2>/dev/null | sed -n 's/^ *Candidate: *//p')"
  if [[ "$candidate" == 2.* ]]; then
    log::warn "this release ships GIMP ${candidate}, but PhotoGIMP requires GIMP 3+"
    log::warn "use './install_with_flatpak.sh' to get current GIMP with automatic updates"
  fi
}

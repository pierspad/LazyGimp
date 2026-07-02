#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# shell_scripts/debian.sh — Debian (13 "trixie" and later recommended).
#
# Sourced by install_with_package_manager.sh. Contract: define
# lazygimp::install_packages (required) and lazygimp::post_install_notes
# (optional). Distro-specific knowledge stays confined to this file.
# ---------------------------------------------------------------------------

lazygimp::install_packages() {
  as_root apt-get update
  as_root apt-get install -y gimp

  # The G'MIC plugin for GIMP 3 is packaged only from Debian 13 onwards.
  if apt-cache show gimp-gmic >/dev/null 2>&1; then
    as_root apt-get install -y gimp-gmic
  else
    log::warn "package 'gimp-gmic' is not available on this release — skipping G'MIC"
    log::warn "alternatives: upgrade to Debian 13+, or run './install.sh --method flatpak'"
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

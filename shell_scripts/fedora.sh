#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# shell_scripts/fedora.sh — Fedora and derivatives (matched through
# ID=fedora or ID_LIKE=fedora, e.g. Nobara).
#
# Sourced by install_with_package_manager.sh. Contract: define
# lazygimp::install_packages (required) and lazygimp::post_install_notes
# (optional). Distro-specific knowledge stays confined to this file.
# ---------------------------------------------------------------------------

lazygimp::install_packages() {
  as_root dnf install -y gimp gmic-gimp
}

lazygimp::remove_packages() {
  local pkgs=() p
  for p in gmic-gimp gimp; do
    rpm -q "$p" >/dev/null 2>&1 && pkgs+=("$p")
  done
  if ((${#pkgs[@]})); then
    as_root dnf remove -y "${pkgs[@]}"
  else
    log::info "no LazyGimp packages installed via dnf"
  fi
}

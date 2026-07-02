#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# shell_scripts/arch.sh — Arch Linux and derivatives (Manjaro, EndeavourOS,
# ... matched through ID_LIKE=arch).
#
# Sourced by install_with_package_manager.sh. Contract: define
# lazygimp::install_packages (required) and lazygimp::post_install_notes
# (optional). Distro-specific knowledge stays confined to this file.
# ---------------------------------------------------------------------------

lazygimp::install_packages() {
  as_root pacman -S --needed --noconfirm gimp gimp-plugin-gmic
}

lazygimp::remove_packages() {
  local pkgs=() p
  for p in gimp-plugin-gmic gimp; do
    pacman -Qi "$p" >/dev/null 2>&1 && pkgs+=("$p")
  done
  if ((${#pkgs[@]})); then
    as_root pacman -Rns --noconfirm "${pkgs[@]}"
  else
    log::info "no LazyGimp packages installed via pacman"
  fi
}

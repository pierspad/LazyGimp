#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# shell_scripts/arch.sh — Arch Linux and derivatives (Manjaro, EndeavourOS,
# ... matched through ID_LIKE=arch).
#
# Sourced by package-manager-install.sh. Contract: define
# lazygimp::install_packages (required) and lazygimp::post_install_notes
# (optional). Distro-specific knowledge stays confined to this file.
# ---------------------------------------------------------------------------

lazygimp::install_packages() {
  local pkgs=(gimp)
  [[ "${LAZYGIMP_SKIP_GMIC:-0}" == 1 ]] || pkgs+=(gimp-plugin-gmic)
  # Full -Syu: never install against a stale database (partial upgrades are
  # unsupported on Arch and stale DBs cause 404s from rotated mirrors).
  as_root pacman -Syu --needed --noconfirm --color never --noprogressbar "${pkgs[@]}"
}

lazygimp::remove_packages() {
  local pkgs=() p
  for p in gimp-plugin-gmic gimp; do
    pacman -Qi "$p" >/dev/null 2>&1 && pkgs+=("$p")
  done
  if ((${#pkgs[@]})); then
    as_root pacman -Rns --noconfirm --color never "${pkgs[@]}"
  else
    log::info "no LazyGimp packages installed via pacman"
  fi
}

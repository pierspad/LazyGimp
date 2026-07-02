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

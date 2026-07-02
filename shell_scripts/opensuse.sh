#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# shell_scripts/opensuse.sh — openSUSE Tumbleweed and Leap (matched through
# ID_LIKE, which contains "opensuse" on both).
#
# Sourced by install_with_package_manager.sh. Contract: define
# lazygimp::install_packages (required) and lazygimp::post_install_notes
# (optional). Distro-specific knowledge stays confined to this file.
# ---------------------------------------------------------------------------

lazygimp::install_packages() {
  as_root zypper --non-interactive install gimp gmic-gimp
}

lazygimp::post_install_notes() {
  log::info "on Leap, current GIMP 3.x may require the graphics repository;"
  log::info "Tumbleweed always ships the latest stable"
}

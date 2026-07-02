#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# lib/gimp.sh — GIMP detection: install kind, version, per-user config dir.
#
# Nothing here hardcodes a GIMP version. The config directory (3.0, 3.2,
# 3.4, ...) is resolved at runtime, so future GIMP releases keep working
# without any code change (see docs/ARCHITECTURE.md).
# ---------------------------------------------------------------------------

if [[ -n "${_LAZYGIMP_GIMP_LOADED:-}" ]]; then return 0; fi
readonly _LAZYGIMP_GIMP_LOADED=1

# shellcheck source=lib/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

# Echo the per-user config *base* directory for an install kind.
gimp::config_base() { # <native|flatpak|snap>
  case "$1" in
    native)  printf '%s/GIMP\n' "${XDG_CONFIG_HOME:-${HOME}/.config}" ;;
    flatpak) printf '%s/.var/app/%s/config/GIMP\n' "${HOME}" "${GIMP_FLATPAK_ID}" ;;
    snap)    printf '%s/snap/gimp/current/.config/GIMP\n' "${HOME}" ;;
    *)       die "unknown install kind: $1" ;;
  esac
}

# Echo MAJOR.MINOR of the installed GIMP; fails if undetectable.
gimp::detect_version() { # <native|flatpak|snap>
  local kind="$1" raw=""
  case "$kind" in
    native)
      if have gimp; then
        raw="$(gimp --version 2>/dev/null || true)"
      fi
      ;;
    flatpak)
      if have flatpak; then
        raw="$(flatpak info "${GIMP_FLATPAK_ID}" 2>/dev/null | sed -n 's/^ *Version: *//p' || true)"
      fi
      ;;
    snap)
      if have snap; then
        raw="$(snap list gimp 2>/dev/null | awk 'NR==2 {print $2}' || true)"
      fi
      ;;
  esac
  # "GNU Image Manipulation Program version 3.2.4" → "3.2"
  [[ "$raw" =~ ([0-9]+)\.([0-9]+)(\.[0-9]+)? ]] || return 1
  printf '%s.%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
}

# Echo the newest existing MAJOR.MINOR directory under a config base.
# Uses `sort -V` so 3.10 correctly beats 3.2.
gimp::newest_config_dir() { # <base-dir>
  local base="$1" best
  [[ -d "$base" ]] || return 1
  best="$(find "$base" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null |
    grep -E '^[0-9]+\.[0-9]+$' | sort -V | tail -n1)"
  [[ -n "$best" ]] || return 1
  printf '%s/%s\n' "$base" "$best"
}

# Resolve THE config directory a configuration layer must target.
#
# Strategy, in order:
#   0. explicit hint (LAZYGIMP_GIMP_VERSION_HINT) — used by installers that
#      already know which GIMP they just installed (e.g. the AppImage method);
#   1. version reported by the installed GIMP itself;
#   2. newest MAJOR.MINOR directory that already exists on disk;
#   3. give up with an actionable error.
gimp::config_dir() { # <native|flatpak|snap>
  local kind="$1" base ver
  base="$(gimp::config_base "$kind")"

  if [[ "${LAZYGIMP_GIMP_VERSION_HINT:-}" =~ ([0-9]+)\.([0-9]+) ]]; then
    printf '%s/%s.%s\n' "$base" "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    return 0
  fi

  if ver="$(gimp::detect_version "$kind")"; then
    printf '%s/%s\n' "$base" "$ver"
    return 0
  fi

  if gimp::newest_config_dir "$base"; then
    return 0
  fi

  die "cannot locate a GIMP config directory under ${base} — launch GIMP once, then re-run"
}

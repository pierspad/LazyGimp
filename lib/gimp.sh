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
        # `flatpak list --columns` is locale-independent, unlike the
        # human-oriented (and translated!) `flatpak info` output.
        raw="$(flatpak list --app --columns=application,version 2>/dev/null |
          awk -v id="${GIMP_FLATPAK_ID}" '$1 == id {print $2}' || true)"
        if [[ -z "$raw" ]]; then
          raw="$(LC_ALL=C flatpak info "${GIMP_FLATPAK_ID}" 2>/dev/null |
            sed -n 's/^ *Version: *//p' || true)"
        fi
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

# Launch GIMP once, headless, so it generates its per-user configuration
# files (config dir, plug-in folders, rc files). On a fresh system this MUST
# happen before the PhotoGIMP layer and plug-ins are applied, otherwise
# there is no directory to target.
#
# Runs the child in the background with an inline progress line, a hard
# timeout (LAZYGIMP_WARMUP_TIMEOUT, default 120 s) and an INT trap, so the
# user always sees activity and Ctrl+C always kills it. Skipped entirely if
# a config dir already exists.
gimp::warm_up() { # <kind> [explicit-gimp-binary]
  local kind="$1" bin="${2:-}" base cmd=()

  base="$(gimp::config_base "$kind")"
  if gimp::newest_config_dir "$base" >/dev/null 2>&1; then
    return 0 # GIMP has run before — nothing to generate
  fi

  case "$kind" in
    native)
      if [[ -n "$bin" ]]; then
        cmd=("$bin")
      elif have gimp; then
        cmd=(gimp)
      else
        return 0
      fi
      ;;
    flatpak)
      have flatpak || return 0
      cmd=(flatpak run "${GIMP_FLATPAK_ID}")
      ;;
    *) return 0 ;;
  esac

  # -i no UI, -d skip data (brushes...), -f skip fonts (the font-cache build
  # can take minutes on a first run), -s no splash; stdin from /dev/null so
  # batch mode can never sit waiting for input. stderr goes to a log we can
  # point the user at if something goes wrong.
  local warmup_log="${XDG_STATE_HOME:-${HOME}/.local/state}/lazygimp/warmup.log"
  mkdir -p "$(dirname "$warmup_log")"
  "${cmd[@]}" -i -d -f -s -b '(gimp-quit 0)' </dev/null >"$warmup_log" 2>&1 &
  local pid=$! elapsed=0 limit="${LAZYGIMP_WARMUP_TIMEOUT:-120}"

  trap 'kill -TERM "$pid" 2>/dev/null; sleep 1; kill -KILL "$pid" 2>/dev/null; \
printf "\n" >&2; log::error "interrupted"; exit 130' INT

  while kill -0 "$pid" 2>/dev/null; do
    if ((elapsed >= limit)); then
      kill -TERM "$pid" 2>/dev/null || true
      sleep 2
      kill -KILL "$pid" 2>/dev/null || true
      break
    fi
    printf '\r[info] first GIMP start, generating configuration... %3ds (one-time step)' \
      "$elapsed" >&2
    sleep 1
    ((elapsed += 1))
  done
  printf '\r%*s\r' 78 '' >&2
  trap - INT

  if wait "$pid" 2>/dev/null; then
    log::ok "GIMP configuration initialized"
  else
    log::warn "GIMP warm-up did not finish cleanly (details: ${warmup_log}); continuing"
  fi

  # Belt and braces: if GIMP still did not create its tree but we know the
  # version, create the directory ourselves — GIMP happily adopts it, and
  # the layers/plug-ins need a real path to target.
  local ver
  if ! gimp::newest_config_dir "$base" >/dev/null 2>&1; then
    if ver="$(gimp::detect_version "$kind")"; then
      mkdir -p "${base}/${ver}"
      log::info "created ${base}/${ver} (GIMP will adopt it on first launch)"
    fi
  fi
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

#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# flatpak-install.sh — GIMP + G'MIC + Resynthesizer from Flathub, then
# everything else: headless first launch, PhotoGIMP layer, Batcher,
# Segment Anything. Fully unattended: no questions asked.
#
# Best choice on distributions whose repositories lag behind upstream
# (Debian stable, Ubuntu LTS): Flathub ships current GIMP everywhere and
# updates flow through the system's flatpak updater.
#
# Usage:
#   ./flatpak-install.sh [--skip-photogimp] [--skip-plugins] [--no-sam] [--no-font-access]
#
# Piped usage (no checkout needed):
#   curl -fsSL https://raw.githubusercontent.com/pierspad/LazyGimp/main/flatpak-install.sh | bash
# ---------------------------------------------------------------------------

# Tolerate being launched with `sh script.sh` (dash, or bash in POSIX mode,
# which rejects function names containing '::'): re-exec under real bash.
if [ -f "${0:-}" ]; then
  if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
  if shopt -qo posix 2>/dev/null; then exec bash "$0" "$@"; fi
fi

set -euo pipefail

LAZYGIMP_REPO_SLUG="${LAZYGIMP_REPO_SLUG:-pierspad/LazyGimp}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"

# Standalone download or `curl | bash`: fetch the release bundle and re-exec.
if [[ ! -d "${SCRIPT_DIR}/lib" ]]; then
  bootstrap_dir="$(mktemp -d "${TMPDIR:-/tmp}/lazygimp-bootstrap.XXXXXX")"
  trap 'rm -rf "$bootstrap_dir"' EXIT
  echo "[info] fetching the latest LazyGimp bundle..." >&2
  curl -fsSL "https://github.com/${LAZYGIMP_REPO_SLUG}/releases/latest/download/lazygimp.tar.gz" |
    tar -xz -C "$bootstrap_dir"
  exec bash "${bootstrap_dir}/lazygimp/flatpak-install.sh" "$@"
fi

# shellcheck source=lib/photogimp.sh
source "${SCRIPT_DIR}/lib/photogimp.sh"

usage() {
  cat <<EOF
LazyGimp — Flatpak installer (Flathub, fully unattended)

Usage: ${0##*/} [options]

Options:
  --skip-photogimp        do not apply the PhotoGIMP configuration layer
  --skip-plugins          do not install the plug-ins (Batcher, SAM)
  --no-sam                install Batcher but skip Segment Anything (~1 GB)
  --no-font-access        do not apply the font sandbox override (see note)
  --uninstall-photogimp   remove the PhotoGIMP layer (personal files are kept)
  -h, --help              show this help

By default EVERYTHING is set up, no questions asked: GIMP + G'MIC +
Resynthesizer + PhotoGIMP + Batcher + Segment Anything (automated backend).

Note on fonts:
  Recent flatpak already exposes system AND user fonts to GIMP. To make
  sure nothing is ever missing (e.g. custom fontconfig setups), LazyGimp
  additionally grants the sandbox READ-ONLY access to ~/.local/share/fonts
  and ~/.config/fontconfig. This is logged, recorded, and reverted by
  ./uninstall.sh. Pass --no-font-access to skip it.
EOF
}

# Grant the GIMP flatpak read access to user fonts + fontconfig, recording
# exactly what was applied so uninstall.sh can revert it precisely.
apply_font_overrides() {
  local state="${LAZYGIMP_STATE_DIR}/flatpak-font-overrides" fs
  mkdir -p "${LAZYGIMP_STATE_DIR}"
  : >"$state"
  # shellcheck disable=SC2088  # the literal ~ is intentional: flatpak expands it
  for fs in '~/.local/share/fonts:ro' 'xdg-config/fontconfig:ro'; do
    flatpak override --user --filesystem="$fs" "${GIMP_FLATPAK_ID}"
    printf '%s\n' "$fs" >>"$state"
  done
  log::ok "sandbox override applied: GIMP can read ~/.local/share/fonts and your fontconfig"
  log::info "recorded in ${state} — revert with ./uninstall.sh"
}

SKIP_PHOTOGIMP="${LAZYGIMP_SKIP_PHOTOGIMP:-0}"
SKIP_PLUGINS="${LAZYGIMP_SKIP_PLUGINS:-0}"
NO_SAM="${LAZYGIMP_NO_SAM:-0}"
FONT_ACCESS=1
while (($#)); do
  case "$1" in
    --skip-photogimp) SKIP_PHOTOGIMP=1 ;;
    --skip-plugins) SKIP_PLUGINS=1 ;;
    --no-sam) NO_SAM=1 ;;
    --font-access) FONT_ACCESS=1 ;; # kept for compatibility (now the default)
    --no-font-access) FONT_ACCESS=0 ;;
    --uninstall-photogimp)
      photogimp::uninstall flatpak
      exit 0
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
  shift
done

main() {
  have flatpak ||
    die "flatpak is not installed — install it from your package manager first \
(e.g. 'sudo apt install flatpak'), or use ./package-manager-install.sh"

  if ! flatpak remotes --columns=name 2>/dev/null | grep -qx flathub; then
    log::info "adding the flathub remote (user scope)"
    flatpak remote-add --user --if-not-exists flathub \
      https://dl.flathub.org/repo/flathub.flatpakrepo
  fi

  log::info "installing ${GIMP_FLATPAK_ID} from flathub"
  flatpak install -y --noninteractive flathub "${GIMP_FLATPAK_ID}"

  # Plug-ins ship as flatpak *extensions* with one branch per GIMP major
  # (2-40, 2-3.36, 3, ...). A bare ref is ambiguous and makes flatpak ask —
  # a lazy installer never asks: pin the branch of the GIMP just installed,
  # and pass --noninteractive so flatpak fails instead of ever prompting.
  local ext branch
  branch="$(gimp::detect_version flatpak || true)"
  branch="${branch%%.*}" # extension branch = GIMP major ("3")
  if [[ -z "$branch" ]]; then
    log::warn "cannot determine the installed GIMP version — skipping the plug-in"
    log::warn "extensions; install them later with, e.g.:"
    log::warn "  flatpak install flathub ${GMIC_FLATPAK_ID}//3"
  else
    for ext in "${GMIC_FLATPAK_ID}" "${RESYNTH_FLATPAK_ID}"; do
      if ! flatpak install -y --noninteractive flathub "${ext}//${branch}"; then
        log::warn "${ext##*.} flatpak extension not available for GIMP ${branch} yet"
        log::warn "install it manually later: flatpak install flathub ${ext}//${branch}"
      fi
    done
  fi

  # GIMP must run once to generate its config tree before we layer on it.
  gimp::warm_up flatpak

  if [[ "$SKIP_PHOTOGIMP" != 1 ]]; then
    if ! (photogimp::install flatpak); then
      log::warn "PhotoGIMP layer not applied (see message above); GIMP itself is installed"
    fi
  fi

  if ((FONT_ACCESS)); then
    apply_font_overrides
  else
    log::info "font sandbox override skipped (--no-font-access)"
  fi

  if [[ "$SKIP_PLUGINS" != 1 ]]; then
    local plugin_args=(--kind flatpak --batcher)
    if [[ "$NO_SAM" != 1 ]]; then
      plugin_args+=(--segment-anything)
    fi
    if ! "${SCRIPT_DIR}/plugins-install.sh" "${plugin_args[@]}"; then
      log::warn "plug-ins step failed — re-run it later with: ./plugins-install.sh"
    fi
  fi

  log::ok "flatpak setup complete — launch GIMP from your app menu"
}

main

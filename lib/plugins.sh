#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# lib/plugins.sh — optional GIMP plug-ins layer (Batcher, Segment Anything).
#
# Same philosophy as the PhotoGIMP layer: the target plug-ins directory is
# resolved at runtime (never hardcoded), every folder we install is recorded
# in a state manifest for clean removal, and user files are never touched —
# each plug-in lives in its own folder that is entirely ours.
# ---------------------------------------------------------------------------

if [[ -n "${_LAZYGIMP_PLUGINS_LOADED:-}" ]]; then return 0; fi
readonly _LAZYGIMP_PLUGINS_LOADED=1

# shellcheck source=lib/gimp.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/gimp.sh"

LAZYGIMP_STATE_DIR="${LAZYGIMP_STATE_DIR:-${XDG_STATE_HOME:-${HOME}/.local/state}/lazygimp}"

plugins::dir() { # <native|snap>
  local config_dir
  config_dir="$(gimp::config_dir "$1")" || return 1
  [[ -n "$config_dir" ]] || return 1
  printf '%s/plug-ins\n' "$config_dir"
}

plugins::state_file() {
  printf '%s/plugins.manifest\n' "${LAZYGIMP_STATE_DIR}"
}

plugins::record() { # <installed-dir>
  mkdir -p "${LAZYGIMP_STATE_DIR}"
  # de-duplicate: an upgrade re-records the same path
  if [[ -f "$(plugins::state_file)" ]] && grep -qxF "$1" "$(plugins::state_file)"; then
    return 0
  fi
  printf '%s\n' "$1" >>"$(plugins::state_file)"
}

# Download a release zip and install the single plug-in folder it contains.
plugins::install_zip() { # <plugin-folder-name> <url> <kind>
  local name="$1" url="$2" kind="$3"
  require unzip
  local tmp zip src dest
  tmp="$(make_tmpdir)"
  zip="${tmp}/${name}.zip"
  download "$url" "$zip"
  unzip -qo "$zip" -d "${tmp}/extracted"

  src="$(find "${tmp}/extracted" -maxdepth 3 -type d -name "$name" 2>/dev/null | head -n1)"
  [[ -n "$src" ]] || die "folder '${name}' not found inside the downloaded archive"

  dest="$(plugins::dir "$kind")" || {
    log::error "cannot resolve the plug-ins directory for kind '${kind}'"
    return 1
  }
  mkdir -p "$dest"
  rm -rf "${dest:?}/${name}" # idempotent upgrade: this folder is entirely ours
  cp -a "$src" "${dest}/"
  # GIMP requires the plug-in entry point to be executable on native installs.
  find "${dest}/${name}" -maxdepth 1 -name '*.py' -exec chmod +x {} +

  plugins::record "${dest}/${name}"
  log::ok "plug-in '${name}' installed into ${dest}"
}

# Batcher — batch image processing / export layers for GIMP 3 (BSD-3-Clause).
plugins::install_batcher() { # <kind>
  local url="https://github.com/${BATCHER_REPO}/releases/download/${BATCHER_RELEASE_TAG}/batcher-${BATCHER_RELEASE_TAG}.zip"
  plugins::install_zip batcher "$url" "$1"
  log::info "restart GIMP, then look for 'Export Layers…' and 'Batch Convert…' under File"
}

# Segment Anything — AI subject selection (AGPL-3.0). The GIMP plug-in is
# tiny; the inference backend is handled by lib/segany_backend.sh.
plugins::install_segany() { # <kind>
  local url="https://github.com/${SEGANY_REPO}/releases/download/${SEGANY_RELEASE_TAG}/gimp-segany-gimp3.zip"
  plugins::install_zip seganyplugin "$url" "$1"
  log::info "find it under Image → Segment Anything Layers after a GIMP restart"
}

# Remove every plug-in folder LazyGimp installed (recorded in the manifest).
plugins::uninstall_all() {
  local state dir removed=0
  state="$(plugins::state_file)"
  if [[ ! -f "$state" ]]; then
    log::info "no LazyGimp-managed plug-ins recorded"
    return 0
  fi
  while IFS= read -r dir; do
    if [[ -n "$dir" && -d "$dir" ]]; then
      rm -rf -- "$dir"
      log::info "removed ${dir}"
      removed=1
    fi
  done <"$state"
  rm -f -- "$state"
  if ((removed)); then
    log::ok "LazyGimp-managed plug-ins removed"
  else
    log::info "recorded plug-ins were already gone; manifest cleaned"
  fi
}

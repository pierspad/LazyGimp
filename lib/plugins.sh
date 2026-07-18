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

# GIMP only re-queries a plug-in's procedures when it believes something
# changed, a decision driven by a cache file (pluginrc) next to the
# plug-ins dir. That cache is usually kept in sync correctly, but a plug-in
# installed/updated while GIMP itself was left running in the background,
# or a previous install that failed partway through, can leave a menu
# entry missing (or stuck on the old version) even after a restart.
# Clearing pluginrc after every plug-in (re)install is always safe — GIMP
# just regenerates it, at the cost of one slightly slower next startup —
# so do it unconditionally rather than trying to guess whether this
# particular run actually needs it.
plugins::_invalidate_cache() { # <kind>
  local kind="$1" config_dir pluginrc
  config_dir="$(gimp::config_dir "$kind" 2>/dev/null)" || return 0
  pluginrc="${config_dir}/pluginrc"
  if [[ -f "$pluginrc" ]]; then
    rm -f -- "$pluginrc"
    log::info "cleared GIMP's plug-in cache (${pluginrc}) so it rescans on next launch"
  fi
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
  plugins::_invalidate_cache "$kind"
  log::ok "plug-in '${name}' installed into ${dest}"
}

# Batcher — batch image processing / export layers for GIMP 3 (BSD-3-Clause).
plugins::install_batcher() { # <kind>
  local tag="" url
  if have python3; then
    tag="$(fetch "https://api.github.com/repos/${BATCHER_REPO}/releases/latest" 2>/dev/null |
      python3 -c 'import sys, json; print(json.load(sys.stdin).get("tag_name", ""))' 2>/dev/null)"
  fi
  if [[ -z "$tag" ]]; then
    tag="${BATCHER_RELEASE_TAG}"
  fi
  log::info "using Batcher release: ${tag}"
  url="https://github.com/${BATCHER_REPO}/releases/download/${tag}/batcher-${tag}.zip"
  plugins::install_zip batcher "$url" "$1"
  log::info "restart GIMP, then look for 'Export Layers…' and 'Batch Convert…' under File"
}

# Segment Anything — AI subject selection (AGPL-3.0). The GIMP plug-in is
# tiny; the inference backend is handled by lib/segany_backend.sh.
#
# Local-checkout-first: while actively developing the plug-in (this is a
# fork, pierspad/gimpsegany), we never want to fetch a stale upstream zip
# over the network when a working copy already sits right next to LazyGimp
# on disk — that would silently overwrite local fixes with an old release.
# `plugins::segany_source_dir` resolves that local checkout; the GitHub zip
# is only a fallback for people who installed LazyGimp standalone, without
# the sibling gimpsegany checkout.
plugins::segany_source_dir() {
  local override="${LAZYGIMP_SEGANY_SRC_DIR:-}"
  if [[ -n "$override" ]]; then
    [[ -f "${override}/seganyplugin.py" ]] || return 1
    (cd "$override" >/dev/null 2>&1 && pwd)
    return 0
  fi
  local sibling="${LAZYGIMP_ROOT}/../gimpsegany"
  if [[ -f "${sibling}/seganyplugin.py" ]]; then
    (cd "$sibling" >/dev/null 2>&1 && pwd)
    return 0
  fi
  return 1
}

# Install/refresh the plug-in folder from a local source checkout (copy,
# not symlink — GIMP plug-in dirs are otherwise-owned folders we manage).
plugins::install_segany_local() { # <src-dir> <kind>
  local src="$1" kind="$2" dest name="seganyplugin"
  dest="$(plugins::dir "$kind")" || {
    log::error "cannot resolve the plug-ins directory for kind '${kind}'"
    return 1
  }
  mkdir -p "$dest"
  rm -rf -- "${dest:?}/${name}"
  mkdir -p "${dest}/${name}"
  cp -a "${src}/seganyplugin.py" "${src}/seganybridge.py" "${dest}/${name}/"
  chmod +x "${dest}/${name}"/*.py
  plugins::record "${dest}/${name}"
  plugins::_invalidate_cache "$kind"
  log::ok "plug-in '${name}' installed into ${dest} (from local checkout: ${src})"
}

plugins::install_segany() { # <kind>
  local kind="$1" src
  if src="$(plugins::segany_source_dir)"; then
    plugins::install_segany_local "$src" "$kind"
  else
    local url="https://github.com/${SEGANY_REPO}/releases/download/${SEGANY_RELEASE_TAG}/gimp-segany-gimp3.zip"
    plugins::install_zip seganyplugin "$url" "$kind"
  fi
  log::info "SAM (Segmentation Models plug-in) installed — find it under Image → Segment Anything Layers after a GIMP restart"
}

# Remove exactly ONE tracked plug-in folder (by its base name, e.g.
# "batcher" or "seganyplugin"), rewriting the manifest without that line.
# Every other tracked plug-in is left completely alone — this is what makes
# uninstall selective instead of "remove everything LazyGimp ever touched",
# which matters because the plug-ins directory is shared with whatever else
# the user has installed there themselves.
plugins::uninstall_one() { # <name>
  local name="$1" state dir removed=0 tmp
  state="$(plugins::state_file)"
  if [[ ! -f "$state" ]]; then
    log::info "no LazyGimp-managed plug-ins recorded"
    return 0
  fi
  tmp="$(mktemp "${state}.XXXXXX")"
  while IFS= read -r dir; do
    if [[ -n "$dir" && "$(basename "$dir")" == "$name" ]]; then
      if [[ -d "$dir" ]]; then
        rm -rf -- "$dir"
        log::ok "removed ${dir}"
        removed=1
      fi
    elif [[ -n "$dir" ]]; then
      printf '%s\n' "$dir" >>"$tmp"
    fi
  done <"$state"
  mv -f -- "$tmp" "$state"
  ((removed)) || log::info "'${name}' was not installed (or already removed)"
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

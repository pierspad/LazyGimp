#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# lib/photogimp.sh — the PhotoGIMP *configuration layer*.
#
# Design goals (rationale in docs/ARCHITECTURE.md):
#   * version-agnostic: the payload inside the PhotoGIMP archive (currently
#     shipped under .config/GIMP/3.0) is re-targeted onto whatever config
#     directory the *installed* GIMP actually uses (3.2, 3.4, ...);
#   * non-destructive: a full backup is taken before anything is written and
#     every file we install is recorded in a manifest, so the layer can be
#     upgraded or removed cleanly while personal files are never deleted.
# ---------------------------------------------------------------------------

if [[ -n "${_LAZYGIMP_PHOTOGIMP_LOADED:-}" ]]; then return 0; fi
readonly _LAZYGIMP_PHOTOGIMP_LOADED=1

# shellcheck source=lib/gimp.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/gimp.sh"

readonly PHOTOGIMP_MANIFEST=".lazygimp-photogimp.manifest"
LAZYGIMP_STATE_DIR="${LAZYGIMP_STATE_DIR:-${XDG_STATE_HOME:-${HOME}/.local/state}/lazygimp}"

# Download and extract the pinned PhotoGIMP release; echo the extraction dir.
photogimp::download() {
  require unzip
  local tmp zip base_url
  tmp="$(make_tmpdir)"
  zip="${tmp}/photogimp.zip"
  base_url="https://github.com/${PHOTOGIMP_REPO}/releases/download/${PHOTOGIMP_RELEASE_TAG}"
  download "${base_url}/PhotoGIMP-linux.zip" "$zip" ||
    download "${base_url}/PhotoGIMP.zip" "$zip"
  unzip -qo "$zip" -d "${tmp}/extracted"
  printf '%s/extracted\n' "$tmp"
}

# Locate the GIMP config payload inside an extracted PhotoGIMP tree.
# The archive currently ships `.config/GIMP/3.0/…`; we take the newest
# version directory found, so a future PhotoGIMP that ships `3.4` keeps
# working without changes here.
photogimp::locate_payload() { # <extracted-dir>
  local root="$1" payload
  payload="$(find "$root" -type d -path '*/.config/GIMP/*' 2>/dev/null |
    grep -E '/[0-9]+\.[0-9]+$' | sort -V | tail -n1)"
  [[ -n "$payload" ]] || die "no GIMP payload (.config/GIMP/X.Y) found in the PhotoGIMP archive"
  printf '%s\n' "$payload"
}

# Back up an existing config directory; echo the backup path ("" if there
# was nothing to back up).
photogimp::backup() { # <target-dir>
  local target="$1" stamp backup
  if [[ ! -d "$target" ]]; then
    printf '\n'
    return 0
  fi
  stamp="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "${LAZYGIMP_STATE_DIR}/backups"
  backup="${LAZYGIMP_STATE_DIR}/backups/gimp-config-$(basename "$target")-${stamp}.tar.gz"
  tar -czf "$backup" -C "$(dirname "$target")" "$(basename "$target")"
  printf '%s\n' "$backup"
}

# Files from the PhotoGIMP payload that must NEVER be copied: pluginrc is
# GIMP's *plug-in registry cache*, specific to the packager's machine — it
# makes ghost menu entries appear (e.g. a greyed-out G'MIC that is not
# actually installed). GIMP regenerates it on startup.
readonly -a PHOTOGIMP_EXCLUDE=(pluginrc)

# Copy the payload file-by-file, recording every path we own in a manifest.
# Files that belong to the user but are NOT part of PhotoGIMP (brushes,
# scripts, plug-ins, palettes, ...) are never touched; files we do overwrite
# are recoverable from the backup produced by photogimp::backup.
photogimp::apply() { # <payload-dir> <target-dir>
  local payload="$1" target="$2" file rel excluded
  # Defence in depth: a broken resolver upstream must never make us write
  # into '' or '/'.
  if [[ -z "$payload" || -z "$target" || "$target" != /?*/* ]]; then
    log::error "refusing to apply PhotoGIMP: invalid target '${target}'"
    return 1
  fi
  mkdir -p "$target"
  : >"${target}/${PHOTOGIMP_MANIFEST}"
  while IFS= read -r -d '' file; do
    rel="${file#"${payload}"/}"
    for excluded in "${PHOTOGIMP_EXCLUDE[@]}"; do
      if [[ "$rel" == "$excluded" ]]; then
        continue 2
      fi
    done
    install -D -m 0644 "$file" "${target}/${rel}"
    printf '%s\n' "$rel" >>"${target}/${PHOTOGIMP_MANIFEST}"
  done < <(find "$payload" -type f -print0)
}

# Remove every file listed in a target's manifest (and the manifest itself),
# then prune directories left empty. User files are untouched by design.
photogimp::remove() { # <target-dir>
  local target="$1" rel
  local manifest="${target}/${PHOTOGIMP_MANIFEST}"
  [[ -f "$manifest" ]] || die "no PhotoGIMP manifest in ${target}; nothing to uninstall"
  while IFS= read -r rel; do
    [[ -n "$rel" ]] && rm -f -- "${target:?}/${rel}"
  done <"$manifest"
  rm -f -- "$manifest"
  find "$target" -type d -empty -delete 2>/dev/null || true
}

# Desktop entry and icons shipped by PhotoGIMP. Every installed file is
# recorded in a manifest under the state dir, so
# photogimp::remove_desktop_files can undo this cleanly.
#
# Upstream hardcodes an `Exec=` line in its .desktop file (historically a
# flatpak invocation), which silently does nothing unless it matches the GIMP
# actually installed. We retarget Exec to the GIMP that was installed (override
# the command via LAZYGIMP_GIMP_COMMAND, e.g. an AppImage path).
photogimp::install_desktop_files() { # <extracted-dir> <kind>
  local root="$1" kind="${2:-native}" share manifest file rel
  share="$(find "$root" -type d -path '*/.local/share' 2>/dev/null | head -n1)"
  [[ -n "$share" ]] || return 0

  manifest="${LAZYGIMP_STATE_DIR}/desktop-files.manifest"
  mkdir -p "${LAZYGIMP_STATE_DIR}"
  : >"$manifest"

  while IFS= read -r -d '' file; do
    rel="${file#"${share}"/}"
    install -D -m 0644 "$file" "${HOME}/.local/share/${rel}"
    printf '%s\n' "${HOME}/.local/share/${rel}" >>"$manifest"
  done < <(find "$share" -type f -print0)

  # Retarget the launcher. Upstream PhotoGIMP hardcodes an Exec line for one
  # specific GIMP (often a flatpak invocation with a pinned `--command=`, or a
  # bare `gimp`); on a mismatch the menu entry launches nothing or the wrong
  # binary. Rewrite Exec to point unambiguously at the GIMP LazyGimp set up
  # (override via LAZYGIMP_GIMP_COMMAND, e.g. an AppImage path), and drop
  # TryExec/DBusActivatable which reference the same stale binary/service.
  local desktop exec_line="${LAZYGIMP_GIMP_COMMAND:-gimp} %U"
  while IFS= read -r desktop; do
    [[ "$desktop" == *.desktop ]] || continue
    sed -i -e "s|^Exec=.*|Exec=${exec_line}|" -e '/^TryExec=/d' -e '/^DBusActivatable=/d' "$desktop"
  done <"$manifest"

  # Our entry shadows org.gimp.GIMP.desktop, but some distros name the stock
  # entry differently (e.g. Arch ships gimp.desktop) — hide that duplicate with
  # a NoDisplay override, tracked for clean removal.
  local stock="/usr/share/applications/gimp.desktop" hidden
  hidden="${HOME}/.local/share/applications/gimp.desktop"
  if [[ -f "$stock" && ! -f "$hidden" ]]; then
    printf '[Desktop Entry]\nType=Application\nName=GIMP\nNoDisplay=true\n' >"$hidden"
    printf '%s\n' "$hidden" >>"$manifest"
  fi

  if have update-desktop-database; then
    update-desktop-database "${HOME}/.local/share/applications" 2>/dev/null || true
  fi

  # The icon FILES were just installed above (they live under the same
  # .local/share tree as the .desktop file, so the loop already copied
  # them), but icon THEMES are indexed/cached — GTK/Qt/Plasma consult that
  # cache instead of re-scanning the icon directory on every lookup.
  # Without refreshing it, PhotoGIMP's icon can stay invisible (a generic
  # fallback shown instead, e.g. in the taskbar/app switcher/Wayland
  # window-list) until something else happens to rebuild the cache on its
  # own. Never fatal: some distros don't ship gtk-update-icon-cache, and a
  # missing index.theme in ~/.local/share/icons/hicolor is common/harmless.
  local icon_theme_dir="${HOME}/.local/share/icons/hicolor"
  if have gtk-update-icon-cache && [[ -d "$icon_theme_dir" ]]; then
    gtk-update-icon-cache -q -t -f "$icon_theme_dir" 2>/dev/null || true
    log::info "refreshed the icon cache (${icon_theme_dir})"
  fi
  log::info "PhotoGIMP desktop entry installed (launches the GIMP set up by LazyGimp)"
}

# Undo photogimp::install_desktop_files using its manifest.
photogimp::remove_desktop_files() {
  local manifest="${LAZYGIMP_STATE_DIR}/desktop-files.manifest" file
  [[ -f "$manifest" ]] || return 0
  while IFS= read -r file; do
    [[ -n "$file" ]] && rm -f -- "$file"
  done <"$manifest"
  rm -f -- "$manifest"
  if have update-desktop-database; then
    update-desktop-database "${HOME}/.local/share/applications" 2>/dev/null || true
  fi
}

photogimp::install() { # <native|snap>
  local kind="$1" target extracted payload backup files
  # NOTE: `die` inside $() only kills the subshell, and set -e is suspended
  # when the caller tests our exit status — every step needs its own guard.
  target="$(gimp::config_dir "$kind")" || return 1
  [[ -n "$target" ]] || return 1

  # PhotoGIMP is a GIMP 3+ patch: refuse to target a 2.x profile.
  if [[ "$(basename "$target")" =~ ^([0-9]+)\. ]] && ((BASH_REMATCH[1] < 3)); then
    log::error "PhotoGIMP requires GIMP 3+, but the detected profile is $(basename "$target")"
    return 1
  fi

  log::info "GIMP config directory: ${target}"
  extracted="$(photogimp::download)" || return 1
  payload="$(photogimp::locate_payload "$extracted")" || return 1

  backup="$(photogimp::backup "$target")" || return 1
  if [[ -n "$backup" ]]; then
    log::info "existing configuration backed up to ${backup}"
  fi

  photogimp::apply "$payload" "$target" || return 1
  photogimp::install_desktop_files "$extracted" "$kind"

  files="$(wc -l <"${target}/${PHOTOGIMP_MANIFEST}")"
  log::ok "PhotoGIMP layer installed (${files} files) into $(basename "$target")"
}

photogimp::uninstall() { # <native|snap>
  local kind="$1" target
  target="$(gimp::config_dir "$kind")" || return 1
  [[ -n "$target" ]] || return 1
  photogimp::remove "$target"
  photogimp::remove_desktop_files
  log::ok "PhotoGIMP layer removed; personal files were left untouched"
  log::info "backups (if any) are in ${LAZYGIMP_STATE_DIR}/backups"
}

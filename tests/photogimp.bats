#!/usr/bin/env bats
# Tests for lib/photogimp.sh — payload discovery, manifest apply/remove,
# preservation of user files.

setup() {
  export HOME="${BATS_TEST_TMPDIR}/home"
  export LAZYGIMP_STATE_DIR="${BATS_TEST_TMPDIR}/state"
  mkdir -p "$HOME"
  unset XDG_CONFIG_HOME LAZYGIMP_GIMP_VERSION_HINT
  # shellcheck source=lib/photogimp.sh
  source "${BATS_TEST_DIRNAME}/../lib/photogimp.sh"
}

make_fake_payload() { # <version> → echoes payload dir
  local root="${BATS_TEST_TMPDIR}/extracted"
  local payload="${root}/PhotoGIMP/.config/GIMP/$1"
  mkdir -p "${payload}/tool-options"
  echo "photogimp gimprc" >"${payload}/gimprc"
  echo "photogimp shortcuts" >"${payload}/shortcutsrc"
  echo "opt" >"${payload}/tool-options/gimp-move-tool"
  printf '%s\n' "$payload"
}

@test "locate_payload finds the versioned dir inside the archive tree" {
  payload="$(make_fake_payload 3.0)"
  run photogimp::locate_payload "${BATS_TEST_TMPDIR}/extracted"
  [ "$status" -eq 0 ]
  [ "$output" = "$payload" ]
}

@test "locate_payload picks the newest payload if several ship" {
  make_fake_payload 3.0 >/dev/null
  newest="$(make_fake_payload 3.4)"
  run photogimp::locate_payload "${BATS_TEST_TMPDIR}/extracted"
  [ "$status" -eq 0 ]
  [ "$output" = "$newest" ]
}

@test "apply copies files, writes a manifest, and preserves user files" {
  payload="$(make_fake_payload 3.0)"
  target="${HOME}/.config/GIMP/3.2"
  mkdir -p "$target"
  echo "user data" >"${target}/my-brush-notes"

  photogimp::apply "$payload" "$target"

  [ -f "${target}/gimprc" ]
  [ -f "${target}/tool-options/gimp-move-tool" ]
  [ "$(cat "${target}/my-brush-notes")" = "user data" ]
  grep -qx "gimprc" "${target}/.lazygimp-photogimp.manifest"
  grep -qx "tool-options/gimp-move-tool" "${target}/.lazygimp-photogimp.manifest"
  ! grep -q "my-brush-notes" "${target}/.lazygimp-photogimp.manifest"
}

@test "backup produces a tarball of the existing config" {
  target="${HOME}/.config/GIMP/3.2"
  mkdir -p "$target"
  echo "precious" >"${target}/gimprc"
  run photogimp::backup "$target"
  [ "$status" -eq 0 ]
  [ -f "$output" ]
  tar -tzf "$output" | grep -q "3.2/gimprc"
}

@test "backup is a no-op when the target does not exist yet" {
  run photogimp::backup "${HOME}/.config/GIMP/9.9"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "remove deletes only manifest-listed files and keeps user files" {
  payload="$(make_fake_payload 3.0)"
  target="${HOME}/.config/GIMP/3.2"
  mkdir -p "$target"
  echo "user data" >"${target}/my-brush-notes"
  photogimp::apply "$payload" "$target"

  photogimp::remove "$target"

  [ ! -f "${target}/gimprc" ]
  [ ! -f "${target}/.lazygimp-photogimp.manifest" ]
  [ ! -d "${target}/tool-options" ]
  [ "$(cat "${target}/my-brush-notes")" = "user data" ]
}

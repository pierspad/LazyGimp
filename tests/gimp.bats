#!/usr/bin/env bats
# Tests for lib/gimp.sh — version detection and config-dir resolution.

setup() {
  export HOME="${BATS_TEST_TMPDIR}/home"
  mkdir -p "$HOME"
  unset XDG_CONFIG_HOME LAZYGIMP_GIMP_VERSION_HINT
  # shellcheck source=lib/gimp.sh
  source "${BATS_TEST_DIRNAME}/../lib/gimp.sh"
}

@test "config_base(native) honours XDG_CONFIG_HOME" {
  export XDG_CONFIG_HOME="${BATS_TEST_TMPDIR}/xdg"
  run gimp::config_base native
  [ "$status" -eq 0 ]
  [ "$output" = "${BATS_TEST_TMPDIR}/xdg/GIMP" ]
}

@test "config_base(flatpak) targets the sandboxed app dir" {
  run gimp::config_base flatpak
  [ "$status" -eq 0 ]
  [ "$output" = "${HOME}/.var/app/org.gimp.GIMP/config/GIMP" ]
}

@test "newest_config_dir picks the highest version (sort -V: 3.10 > 3.2)" {
  mkdir -p "${HOME}/.config/GIMP/3.0" "${HOME}/.config/GIMP/3.2" "${HOME}/.config/GIMP/3.10"
  run gimp::newest_config_dir "${HOME}/.config/GIMP"
  [ "$status" -eq 0 ]
  [ "$output" = "${HOME}/.config/GIMP/3.10" ]
}

@test "newest_config_dir ignores non-version directories" {
  mkdir -p "${HOME}/.config/GIMP/backups" "${HOME}/.config/GIMP/3.2"
  run gimp::newest_config_dir "${HOME}/.config/GIMP"
  [ "$status" -eq 0 ]
  [ "$output" = "${HOME}/.config/GIMP/3.2" ]
}

@test "detect_version(native) parses the gimp binary output" {
  local bin="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$bin"
  printf '#!/bin/sh\necho "GNU Image Manipulation Program version 3.2.4"\n' >"${bin}/gimp"
  chmod +x "${bin}/gimp"
  PATH="${bin}:${PATH}" run gimp::detect_version native
  [ "$status" -eq 0 ]
  [ "$output" = "3.2" ]
}

@test "config_dir prefers the version reported by the binary" {
  local bin="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$bin" "${HOME}/.config/GIMP/3.0"
  printf '#!/bin/sh\necho "GNU Image Manipulation Program version 3.4.1"\n' >"${bin}/gimp"
  chmod +x "${bin}/gimp"
  PATH="${bin}:${PATH}" run gimp::config_dir native
  [ "$status" -eq 0 ]
  [ "$output" = "${HOME}/.config/GIMP/3.4" ]
}

@test "config_dir uses LAZYGIMP_GIMP_VERSION_HINT when set (full version normalised to X.Y)" {
  export LAZYGIMP_GIMP_VERSION_HINT="3.6.2"
  run gimp::config_dir native
  [ "$status" -eq 0 ]
  [ "$output" = "${HOME}/.config/GIMP/3.6" ]
}

@test "config_dir falls back to the newest existing dir without a gimp binary" {
  mkdir -p "${HOME}/.config/GIMP/3.0" "${HOME}/.config/GIMP/3.2"
  PATH="/usr/bin:/bin" run gimp::config_dir native
  [ "$status" -eq 0 ]
  [ "$output" = "${HOME}/.config/GIMP/3.2" ]
}

@test "config_dir fails with a clear message when nothing can be resolved" {
  PATH="/usr/bin:/bin" run gimp::config_dir native
  [ "$status" -ne 0 ]
  [[ "$output" == *"launch GIMP once"* ]]
}

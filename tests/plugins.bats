#!/usr/bin/env bats
# Tests for lib/plugins.sh — plug-ins dir resolution and state tracking.

setup() {
  export HOME="${BATS_TEST_TMPDIR}/home"
  export LAZYGIMP_STATE_DIR="${BATS_TEST_TMPDIR}/state"
  mkdir -p "$HOME"
  unset XDG_CONFIG_HOME LAZYGIMP_GIMP_VERSION_HINT
  # shellcheck source=lib/plugins.sh
  source "${BATS_TEST_DIRNAME}/../lib/plugins.sh"
}

@test "plugins::dir targets plug-ins inside the resolved config dir" {
  mkdir -p "${HOME}/.config/GIMP/3.2"
  PATH="/usr/bin:/bin" run plugins::dir native
  [ "$status" -eq 0 ]
  [ "$output" = "${HOME}/.config/GIMP/3.2/plug-ins" ]
}

@test "plugins::record de-duplicates entries" {
  plugins::record "/some/plug-ins/batcher"
  plugins::record "/some/plug-ins/batcher"
  plugins::record "/some/plug-ins/seganyplugin"
  run wc -l <"$(plugins::state_file)"
  [ "$output" -eq 2 ]
}

@test "uninstall_all removes recorded folders only, then cleans the manifest" {
  local base="${HOME}/.config/GIMP/3.2/plug-ins"
  mkdir -p "${base}/batcher" "${base}/user-own-plugin"
  echo "x" >"${base}/batcher/batcher.py"
  echo "y" >"${base}/user-own-plugin/mine.py"
  plugins::record "${base}/batcher"

  plugins::uninstall_all

  [ ! -d "${base}/batcher" ]
  [ -f "${base}/user-own-plugin/mine.py" ]
  [ ! -f "$(plugins::state_file)" ]
}

@test "uninstall_all is a safe no-op without a manifest" {
  run plugins::uninstall_all
  [ "$status" -eq 0 ]
}

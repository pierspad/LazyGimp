#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# lib/segany_backend.sh — fully automated Segment Anything backend.
#
# The gimpsegany plug-in delegates inference to an external Python via its
# bridge script; upstream leaves that setup to the user. LazyGimp automates
# it end-to-end so the default install "just works":
#
#   ~/.local/share/lazygimp/segany/
#     venv/          dedicated virtualenv: torch (CPU wheels), SAM, deps
#     models/        SAM checkpoint (vit_b by default, ~375 MB)
#     INFO.txt       the two paths the plug-in dialog asks for on first run
#
# After installing everything we run upstream's own bridge test
# (seganybridge.py) and only report success if it prints "Success".
# GPU users: set LAZYGIMP_TORCH_INDEX_URL to a CUDA/ROCm wheel index.
# ---------------------------------------------------------------------------

if [[ -n "${_LAZYGIMP_SEGANY_BACKEND_LOADED:-}" ]]; then return 0; fi
readonly _LAZYGIMP_SEGANY_BACKEND_LOADED=1

# shellcheck source=lib/plugins.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/plugins.sh"

segany::backend_dir() {
  printf '%s/lazygimp/segany\n' "${XDG_DATA_HOME:-${HOME}/.local/share}"
}

segany::python() {
  printf '%s/venv/bin/python3\n' "$(segany::backend_dir)"
}

segany::checkpoint() {
  printf '%s/models/%s\n' "$(segany::backend_dir)" "${SAM_CHECKPOINT_URL##*/}"
}

segany::_create_venv() {
  local dir="$1"
  if [[ -x "${dir}/venv/bin/python3" ]]; then
    log::info "reusing existing virtualenv at ${dir}/venv"
    return 0
  fi
  if ! python3 -m venv "${dir}/venv" 2>/dev/null; then
    rm -rf "${dir}/venv"
    die "cannot create a Python virtualenv — on Debian/Ubuntu install it first: \
sudo apt install python3-venv"
  fi
}

segany::_pip_install() {
  local pip="$1" torch_index="${LAZYGIMP_TORCH_INDEX_URL:-${TORCH_INDEX_URL_DEFAULT}}"
  log::info "installing PyTorch from ${torch_index} (CPU wheels by default)"
  "$pip" install --quiet --upgrade pip
  "$pip" install --quiet torch torchvision --index-url "$torch_index"
  log::info "installing Segment Anything and image dependencies"
  "$pip" install --quiet "${SAM_PIP_SPEC}" numpy pillow opencv-python-headless
}

segany::_download_checkpoint() {
  local ckpt
  ckpt="$(segany::checkpoint)"
  if [[ -f "$ckpt" ]]; then
    log::info "SAM checkpoint already present: ${ckpt}"
    return 0
  fi
  mkdir -p "$(dirname "$ckpt")"
  log::info "downloading SAM checkpoint '${SAM_MODEL_TYPE}' (~375 MB, one-time)"
  download "${SAM_CHECKPOINT_URL}" "$ckpt"
}

# Run upstream's own bridge test from the installed plug-in directory.
segany::_bridge_test() { # <kind>
  local kind="$1" plugin_dir bridge
  plugin_dir="$(plugins::dir "$kind")/seganyplugin"
  bridge="$(find "$plugin_dir" -maxdepth 1 -name 'seganybridge*.py' 2>/dev/null | head -n1)"
  if [[ -z "$bridge" ]]; then
    log::warn "bridge script not found in ${plugin_dir}; skipping self-test"
    return 0
  fi
  log::info "running the upstream bridge self-test (first run compiles kernels, be patient)"
  if (cd "$plugin_dir" &&
    "$(segany::python)" "$bridge" "${SAM_MODEL_TYPE}" "$(segany::checkpoint)" 2>&1 |
    grep -qi 'success'); then
    log::ok "bridge self-test passed — the SAM backend is fully functional"
  else
    log::warn "bridge self-test did not report success; the plug-in may still work,"
    log::warn "see https://github.com/${SEGANY_REPO}#readme for troubleshooting"
  fi
}

segany::_write_info() {
  local dir info
  dir="$(segany::backend_dir)"
  info="${dir}/INFO.txt"
  cat >"$info" <<EOF
LazyGimp — Segment Anything backend
===================================

On the FIRST run of the plug-in (GIMP → Image → Segment Anything Layers),
fill in these two fields — GIMP remembers them afterwards:

  Python3 Path:    $(segany::python)
  Checkpoint Path: $(segany::checkpoint)

Model type: ${SAM_MODEL_TYPE} (leave "Auto" in the dialog: it is inferred
from the checkpoint filename).

GPU acceleration: reinstall the backend with a CUDA/ROCm wheel index, e.g.
  LAZYGIMP_TORCH_INDEX_URL=https://download.pytorch.org/whl/cu126 \\
  ./install_plugins.sh --segment-anything
EOF
  printf '%s\n' "$info"
}

# Install the whole backend. Safe to re-run (idempotent).
segany::install_backend() { # <kind>
  local kind="$1" dir info
  require python3
  have git || die "git is required to install Segment Anything (pip installs it \
from the official repository) — install git and re-run"
  dir="$(segany::backend_dir)"
  mkdir -p "$dir"

  segany::_create_venv "$dir"
  segany::_pip_install "${dir}/venv/bin/pip"
  segany::_download_checkpoint
  segany::_bridge_test "$kind"
  info="$(segany::_write_info)"

  log::ok "SAM backend ready under ${dir}"
  log::info "first-run values (also saved to ${info}):"
  log::info "  Python3 Path:    $(segany::python)"
  log::info "  Checkpoint Path: $(segany::checkpoint)"
}

segany::remove_backend() {
  local dir
  dir="$(segany::backend_dir)"
  if [[ -d "$dir" ]]; then
    rm -rf -- "$dir"
    log::ok "SAM backend removed (${dir})"
  else
    log::info "no SAM backend found"
  fi
}

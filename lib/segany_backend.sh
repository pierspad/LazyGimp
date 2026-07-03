#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# lib/segany_backend.sh — fully automated Segment Anything backend.
#
# The gimpsegany plug-in delegates inference to an external Python via its
# bridge script; upstream leaves that setup to the user. LazyGimp automates
# it end-to-end so the default install "just works":
#
#   ~/.local/share/lazygimp/segany/
#     venv/          dedicated virtualenv: torch (CPU wheels), SAM1 + SAM2, deps
#     models/        the chosen SAM checkpoint(s)
#     INFO.txt       the two paths the plug-in dialog asks for on first run
#
# Why BOTH SAM1 and SAM2 are installed: the upstream bridge (seganybridge.py)
# imports `sam2` AND `segment_anything` at module load, unconditionally. If
# either package is missing the bridge raises ImportError, the plug-in catches
# nothing useful, and you get an empty "Segment Anything" layer group. Missing
# SAM2 was the single most common cause of that symptom.
#
# The model is selected via LAZYGIMP_SAM_MODEL (a key of SAM_MODELS in
# config/versions.conf); the default is SAM_DEFAULT_MODEL. After installing we
# run upstream's own bridge test and only report success if it prints "Success".
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

# Echo the selected model key, validated against the registry.
segany::model() {
  local m="${LAZYGIMP_SAM_MODEL:-${SAM_DEFAULT_MODEL}}"
  if [[ -z "${SAM_MODELS[$m]:-}" ]]; then
    log::warn "unknown SAM model '${m}' — falling back to ${SAM_DEFAULT_MODEL}"
    m="${SAM_DEFAULT_MODEL}"
  fi
  printf '%s\n' "$m"
}

# Echo one field of a model spec ("family|url|size|note"): 1=family 2=url
# 3=size 4=note.
segany::_model_field() { # <model-key> <1-4>
  local spec="${SAM_MODELS[$1]:-}" fields
  [[ -n "$spec" ]] || return 1
  IFS='|' read -r -a fields <<<"$spec"
  printf '%s\n' "${fields[$(($2 - 1))]}"
}

# Absolute path of the checkpoint on disk (filename = basename of its URL, so
# the plug-in's Auto detection can read the family from it).
segany::checkpoint() {
  local url
  url="$(segany::_model_field "$(segany::model)" 2)" || return 1
  printf '%s/models/%s\n' "$(segany::backend_dir)" "${url##*/}"
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
  "$pip" install --quiet --upgrade pip
  log::info "installing PyTorch from ${torch_index} (CPU wheels by default)"
  "$pip" install --quiet torch torchvision --index-url "$torch_index"
  log::info "installing image dependencies (numpy, pillow, opencv)"
  "$pip" install --quiet numpy pillow opencv-python-headless
  # Both backends: the bridge imports both no matter which model runs.
  log::info "installing Segment Anything 1 (SAM) backend"
  "$pip" install --quiet "${SAM1_PIP_SPEC}"
  log::info "installing Segment Anything 2 (SAM2) backend — the bridge imports both"
  if ! "$pip" install --quiet "${SAM2_PIP_SPEC}"; then
    log::warn "SAM2 backend failed to build/install; SAM1 models will still work,"
    log::warn "but the bridge needs SAM2 importable — re-run after installing a"
    log::warn "C/C++ toolchain, or see https://github.com/${SEGANY_REPO}#readme"
  fi
}

segany::_download_checkpoint() {
  local model ckpt url size
  model="$(segany::model)"
  ckpt="$(segany::checkpoint)"
  url="$(segany::_model_field "$model" 2)"
  size="$(segany::_model_field "$model" 3)"
  if [[ -f "$ckpt" ]]; then
    log::info "SAM checkpoint already present: ${ckpt}"
    return 0
  fi
  mkdir -p "$(dirname "$ckpt")"
  log::info "downloading SAM checkpoint '${model}' (~${size}, one-time)"
  download "$url" "$ckpt"
}

# Run upstream's own bridge test from the installed plug-in directory. Passing
# "auto" makes the bridge infer the model type from the checkpoint filename.
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
    "$(segany::python)" "$bridge" auto "$(segany::checkpoint)" 2>&1 |
    grep -qi 'success'); then
    log::ok "bridge self-test passed — the SAM backend is fully functional"
  else
    log::warn "bridge self-test did not report success; the plug-in may still work,"
    log::warn "see https://github.com/${SEGANY_REPO}#readme for troubleshooting"
  fi
}

segany::_write_info() {
  local dir info model
  dir="$(segany::backend_dir)"
  info="${dir}/INFO.txt"
  model="$(segany::model)"
  cat >"$info" <<EOF
LazyGimp — Segment Anything backend
===================================

On the FIRST run of the plug-in (GIMP → Image → Segment Anything Layers),
fill in these two fields — GIMP remembers them afterwards:

  Python3 Path:    $(segany::python)
  Checkpoint Path: $(segany::checkpoint)

Model Type: leave "Auto" in the dialog — it is inferred from the checkpoint
filename ($(basename "$(segany::checkpoint)")).

Selected model: ${model} — $(segany::_model_field "$model" 4)
Checkpoints live in: ${dir}/models/

Change model later:
  LAZYGIMP_SAM_MODEL=<key> ./plugins-install.sh --segment-anything
  (list keys with: ./plugins-install.sh --list-sam-models)

GPU acceleration: reinstall the backend with a CUDA/ROCm wheel index, e.g.
  LAZYGIMP_TORCH_INDEX_URL=https://download.pytorch.org/whl/cu126 \\
  ./plugins-install.sh --segment-anything
EOF
  printf '%s\n' "$info"
}

# Install the whole backend. Safe to re-run (idempotent).
segany::install_backend() { # <kind>
  local kind="$1" dir info model
  require python3
  have git || die "git is required to install Segment Anything (pip installs it \
from the official repositories) — install git and re-run"
  dir="$(segany::backend_dir)"
  model="$(segany::model)"
  mkdir -p "$dir"

  log::info "SAM model: ${model} — $(segany::_model_field "$model" 4)"
  segany::_create_venv "$dir"
  segany::_pip_install "${dir}/venv/bin/pip"
  segany::_download_checkpoint
  segany::_bridge_test "$kind"
  info="$(segany::_write_info)"

  log::ok "SAM backend ready under ${dir}"
  log::info "checkpoints are stored in ${dir}/models/"
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

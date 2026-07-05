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

# Echo the selected model key, validated against the registry. Kept as the
# single-model entry point for backward compatibility (plugins-install.sh
# --sam-model, LAZYGIMP_SAM_MODEL) — segany::models() below is the
# multi-model-aware superset everything new should call instead.
segany::model() {
  local m="${LAZYGIMP_SAM_MODEL:-${SAM_DEFAULT_MODEL}}"
  if [[ -z "${SAM_MODELS[$m]:-}" ]]; then
    log::warn "unknown SAM model '${m}' — falling back to ${SAM_DEFAULT_MODEL}"
    m="${SAM_DEFAULT_MODEL}"
  fi
  printf '%s\n' "$m"
}

# Echo every requested model key, one per line, validated against the
# registry — the multi-model counterpart of segany::model(). Reads
# LAZYGIMP_SAM_MODELS (comma/space-separated); when that is unset it falls
# back to the single-model selection above, so any existing
# LAZYGIMP_SAM_MODEL-only setup keeps behaving exactly as before.
segany::models() {
  local raw="${LAZYGIMP_SAM_MODELS:-}"
  if [[ -z "$raw" ]]; then
    segany::model
    return 0
  fi
  local -a keys valid=()
  IFS=', ' read -r -a keys <<<"$raw"
  local m
  for m in "${keys[@]}"; do
    [[ -n "$m" ]] || continue
    if [[ -n "${SAM_MODELS[$m]:-}" ]]; then
      valid+=("$m")
    else
      log::warn "unknown SAM model '${m}' in LAZYGIMP_SAM_MODELS — skipping"
    fi
  done
  if ((${#valid[@]} == 0)); then
    log::warn "LAZYGIMP_SAM_MODELS had no valid entries — falling back to $(segany::model)"
    segany::model
    return 0
  fi
  printf '%s\n' "${valid[@]}"
}

# The "primary" model — used for the plug-in's first-run settings.json and
# for segany::checkpoint()'s single-path callers — is always the first
# entry of segany::models(), i.e. the first one listed in LAZYGIMP_SAM_MODELS
# or the sole value from LAZYGIMP_SAM_MODEL/SAM_DEFAULT_MODEL.
segany::primary_model() {
  segany::models | head -n1
}

# Echo one field of a model spec ("family|url|size|note"): 1=family 2=url
# 3=size 4=note.
segany::_model_field() { # <model-key> <1-4>
  local spec="${SAM_MODELS[$1]:-}" fields
  [[ -n "$spec" ]] || return 1
  IFS='|' read -r -a fields <<<"$spec"
  printf '%s\n' "${fields[$(($2 - 1))]}"
}

# Absolute path a given model's checkpoint lives (or will live) at on disk
# (filename = basename of its URL, so the plug-in's Auto detection can read
# the family from it).
segany::_checkpoint_for() { # <model-key>
  local url
  url="$(segany::_model_field "$1" 2)" || return 1
  printf '%s/models/%s\n' "$(segany::backend_dir)" "${url##*/}"
}

# Absolute path of the PRIMARY checkpoint on disk — what the plug-in's
# first-run settings point at. Kept as its own function (rather than every
# caller writing segany::_checkpoint_for "$(segany::primary_model)") since
# it existed before multi-model support and several callers already use it.
segany::checkpoint() {
  segany::_checkpoint_for "$(segany::primary_model)"
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
  # On an interactive terminal, let pip print its own progress (download bars,
  # "Building wheel for ..."); the git+https installs below build from source
  # and can otherwise look like a multi-minute hang with --quiet. Piped/CI
  # runs keep --quiet to avoid noisy logs.
  local -a q=(--quiet)
  [[ -t 2 ]] && q=()

  "$pip" install "${q[@]}" --upgrade pip
  log::info "installing PyTorch from ${torch_index} (CPU wheels by default)"
  "$pip" install "${q[@]}" torch torchvision --index-url "$torch_index"
  log::info "installing image dependencies (numpy, pillow, opencv)"
  "$pip" install "${q[@]}" numpy pillow opencv-python-headless
  # Both backends: the bridge imports both no matter which model runs.
  log::info "installing Segment Anything 1 (SAM) backend"
  "$pip" install "${q[@]}" "${SAM1_PIP_SPEC}"
  log::info "installing Segment Anything 2 (SAM2) backend — the bridge imports both; builds from source, can take a few minutes"
  if ! "$pip" install "${q[@]}" "${SAM2_PIP_SPEC}"; then
    log::warn "SAM2 backend failed to build/install; SAM1 models will still work,"
    log::warn "but the bridge needs SAM2 importable — re-run after installing a"
    log::warn "C/C++ toolchain, or see https://github.com/${SEGANY_REPO}#readme"
  fi
}

segany::_download_checkpoint() {
  local model ckpt url size
  while IFS= read -r model; do
    ckpt="$(segany::_checkpoint_for "$model")"
    url="$(segany::_model_field "$model" 2)"
    size="$(segany::_model_field "$model" 3)"
    if [[ -f "$ckpt" ]]; then
      log::info "SAM checkpoint already present: ${ckpt}"
      continue
    fi
    mkdir -p "$(dirname "$ckpt")"
    log::info "downloading SAM checkpoint '${model}' (~${size}, one-time)"
    download "$url" "$ckpt"
  done < <(segany::models)
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

# Pre-fill the plug-in's own settings file (seganyplugin/segany_settings.json)
# with the Python/checkpoint paths we just set up, so the OptionsDialog's
# first run opens already populated instead of asking the user to browse to
# two files by hand. We deliberately write ONLY the keys we know (pythonPath,
# checkPtPath, modelType) rather than the whole schema DialogValue.persist()
# writes — any field we omit falls back to seganyplugin.py's own default, so
# this stays forward-compatible if upstream adds fields later. Silently a
# no-op if the plug-in hasn't been installed into this "kind" yet.
segany::_write_plugin_settings() { # <kind>
  local kind="$1" plugin_dir settings_file
  plugin_dir="$(plugins::dir "$kind")/seganyplugin"
  [[ -d "$plugin_dir" ]] || return 0
  settings_file="${plugin_dir}/segany_settings.json"
  cat >"$settings_file" <<EOF
{
  "pythonPath": "$(segany::python)",
  "checkPtPath": "$(segany::checkpoint)",
  "modelType": "Auto"
}
EOF
  log::ok "pre-filled the plug-in's dialog (Python/checkpoint paths) — first run just needs OK"
}

segany::_write_info() {
  local dir info primary all_models
  dir="$(segany::backend_dir)"
  info="${dir}/INFO.txt"
  primary="$(segany::primary_model)"
  all_models="$(segany::models | paste -sd, -)"
  cat >"$info" <<EOF
LazyGimp — Segment Anything backend
===================================

On the FIRST run of the plug-in (GIMP → Image → Segment Anything Layers),
fill in these two fields — GIMP remembers them afterwards:

  Python3 Path:    $(segany::python)
  Checkpoint Path: $(segany::checkpoint)

Model Type: leave "Auto" in the dialog — it is inferred from the checkpoint
filename ($(basename "$(segany::checkpoint)")).

Installed model(s): ${all_models}
Primary (pre-filled above): ${primary} — $(segany::_model_field "$primary" 4)
Checkpoints live in: ${dir}/models/
To use a different installed model, browse to its checkpoint under
${dir}/models/ in the plug-in's Expert Mode.

Change/add models later:
  LAZYGIMP_SAM_MODEL=<key> ./plugins-install.sh --segment-anything
  LAZYGIMP_SAM_MODELS=<key1,key2,...> ./plugins-install.sh --segment-anything
  (list keys with: ./plugins-install.sh --list-sam-models)

GPU acceleration: reinstall the backend with a CUDA/ROCm wheel index, e.g.
  LAZYGIMP_TORCH_INDEX_URL=https://download.pytorch.org/whl/cu126 \\
  ./plugins-install.sh --segment-anything
EOF
  printf '%s\n' "$info"
}

# Install the whole backend. Safe to re-run (idempotent) — including with a
# different/expanded LAZYGIMP_SAM_MODELS: already-downloaded checkpoints are
# left alone (see segany::_download_checkpoint) and only the missing ones
# are fetched, so re-running this to add a model never re-downloads what's
# already there, and never fails just because a previous run left the venv
# already built.
segany::install_backend() { # <kind>
  local kind="$1" dir info models_list
  require python3
  have git || die "git is required to install Segment Anything (pip installs it \
from the official repositories) — install git and re-run"
  dir="$(segany::backend_dir)"
  mkdir -p "$dir"
  mapfile -t models_list < <(segany::models)

  log::info "SAM model(s): ${models_list[*]}"
  segany::_create_venv "$dir"
  segany::_pip_install "${dir}/venv/bin/pip"
  segany::_download_checkpoint
  segany::_bridge_test "$kind"
  segany::_write_plugin_settings "$kind"
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

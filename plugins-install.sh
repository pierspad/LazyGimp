#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# plugins-install.sh — GIMP 3 plug-ins, on top of any LazyGimp installation
# (native packages or AppImage):
#
#   batcher            batch processing / export layers  (BSD-3-Clause)
#   segment-anything   AI subject selection via Meta SAM (AGPL-3.0),
#                      including a fully automated Python backend
#
# Usage:
#   ./plugins-install.sh                     both, ready to use (default)
#   ./plugins-install.sh --batcher           install Batcher only
#   ./plugins-install.sh --segment-anything  install Segment Anything only
#   ./plugins-install.sh --uninstall-all     remove everything we installed
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
  exec bash "${bootstrap_dir}/lazygimp/plugins-install.sh" "$@"
fi

# shellcheck source=lib/segany_backend.sh
source "${SCRIPT_DIR}/lib/segany_backend.sh"

usage() {
  cat <<EOF
LazyGimp — plug-ins installer

Usage: ${0##*/} [options]

Options:
  --batcher            install Batcher (batch processing / export layers)
  --segment-anything   install Segment Anything, INCLUDING its Python backend
                       (PyTorch CPU + SAM checkpoint, ~1 GB download) — the
                       result is fully working out of the box
  --no-sam-backend     with --segment-anything: install the plug-in only,
                       e.g. if you already manage your own PyTorch/SAM setup
  --sam-model <key>    which SAM checkpoint to set up (default: ${SAM_DEFAULT_MODEL});
                       also settable via LAZYGIMP_SAM_MODEL
  --sam-models <k1,k2,...>  install SEVERAL SAM checkpoints in one run;
                       also settable via LAZYGIMP_SAM_MODELS. Takes priority
                       over --sam-model/LAZYGIMP_SAM_MODEL when both are set.
  --list-sam-models    list the available SAM models and exit
  --kind <k>           target GIMP install kind: native
                       (default: auto-detected)
  --sam-info           print the two values the Segment Anything dialog asks
                       for on its first run, then exit
  --uninstall <name>   remove exactly ONE plug-in (batcher|segment-anything),
                       leaving every other installed plug-in untouched;
                       segment-anything also removes the SAM backend
  --uninstall-all      remove every plug-in installed by LazyGimp
                       (and the SAM backend, if present)
  -h, --help           show this help

Without options BOTH plug-ins are installed, ready to use.
GPU acceleration: LAZYGIMP_TORCH_INDEX_URL=<torch wheel index> (default: CPU wheels).
EOF
}

# Print the SAM model registry, one row per model, marking the default.
list_sam_models() {
  local key
  printf 'Available SAM models:\n'
  printf '  one:     --sam-model <key>        (or LAZYGIMP_SAM_MODEL)\n'
  printf '  several: --sam-models <k1,k2,...>  (or LAZYGIMP_SAM_MODELS)\n\n'
  for key in "${SAM_MODEL_ORDER[@]}"; do
    local mark=' '
    [[ "$key" == "${SAM_DEFAULT_MODEL}" ]] && mark='*'
    printf ' %s %-22s %s (%s)\n' "$mark" "$key" \
      "$(segany::_model_field "$key" 4)" "$(segany::_model_field "$key" 3)"
  done
  printf '\n * = default. Checkpoints are stored under %s/models/\n' "$(segany::backend_dir)"
}

# Which GIMP should receive the plug-ins? Detect a native install, whether by
# querying `gimp --version` or by finding an existing config dir on disk.
detect_kinds() {
  local kinds=()
  gimp::detect_version native >/dev/null 2>&1 && kinds+=(native)
  if ((${#kinds[@]} == 0)); then
    gimp::newest_config_dir "$(gimp::config_base native)" >/dev/null 2>&1 && kinds+=(native)
  fi
  ((${#kinds[@]} > 0)) || return 1
  printf '%s\n' "${kinds[@]}"
}

KIND=""
WANT_BATCHER=0
WANT_SEGANY=0
SAM_BACKEND=1
while (($#)); do
  case "$1" in
    --batcher) WANT_BATCHER=1 ;;
    --segment-anything | --segany) WANT_SEGANY=1 ;;
    --no-sam-backend) SAM_BACKEND=0 ;;
    --sam-model)
      export LAZYGIMP_SAM_MODEL="${2:?--sam-model requires a value}"
      shift
      ;;
    --sam-model=*) export LAZYGIMP_SAM_MODEL="${1#*=}" ;;
    --sam-models)
      export LAZYGIMP_SAM_MODELS="${2:?--sam-models requires a comma-separated value}"
      shift
      ;;
    --sam-models=*) export LAZYGIMP_SAM_MODELS="${1#*=}" ;;
    --list-sam-models)
      list_sam_models
      exit 0
      ;;
    --kind)
      KIND="${2:?--kind requires a value}"
      shift
      ;;
    --kind=*) KIND="${1#*=}" ;;
    --sam-info)
      cat <<EOF
SAM (Segmentation Models plug-in) — first-run dialog values (GIMP remembers them afterwards):

  Python3 Path:      $(segany::python)
  Model Checkpoint:  $(segany::checkpoint)   (primary — first of: $(segany::models | paste -sd, -))
  Model Type:        Auto (inferred from the checkpoint filename)
EOF
      exit 0
      ;;
    --uninstall)
      target="${2:?--uninstall requires a value (batcher|segment-anything)}"
      shift
      case "$target" in
        batcher) plugins::uninstall_one batcher ;;
        segment-anything | segany)
          plugins::uninstall_one seganyplugin
          segany::remove_backend
          ;;
        *) die "unknown --uninstall target: ${target} (batcher|segment-anything)" ;;
      esac
      exit 0
      ;;
    --uninstall-all)
      plugins::uninstall_all
      segany::remove_backend
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
  # No selection → everything, ready to use. Lazy by default.
  if ((!WANT_BATCHER && !WANT_SEGANY)); then
    WANT_BATCHER=1
    WANT_SEGANY=1
  fi

  local kinds=()
  if [[ -n "$KIND" ]]; then
    kinds=("$KIND")
  else
    mapfile -t kinds < <(detect_kinds || true)
    ((${#kinds[@]} > 0)) ||
      die "no GIMP installation detected — install GIMP first (./install.sh), or pass --kind"
  fi
  log::info "target GIMP install kind(s): ${kinds[*]}"

  local kind
  for kind in "${kinds[@]}"; do
    if ((WANT_BATCHER)); then
      plugins::install_batcher "$kind"
    fi
    if ((WANT_SEGANY)); then
      plugins::install_segany "$kind"
    fi
  done

  if ((WANT_SEGANY)); then
    if ((SAM_BACKEND)); then
      segany::install_backend "${kinds[0]}"
    else
      log::warn "SAM backend skipped (--no-sam-backend) — the plug-in needs one to run:"
      log::warn "see https://github.com/${SEGANY_REPO}#readme"
    fi
  fi

  log::ok "done — restart GIMP to load the new plug-ins"
}

main

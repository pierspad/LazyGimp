#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Shared by update-components.sh and check-component-releases.sh: find the
# upstream component clones, wherever this particular machine keeps them.
#
# Two layouts are supported on purpose.
#
#   sibling   — the clones sit next to the LazyGimp checkout, e.g.
#               GIMP_STUFF/{LazyGimp,GIMPSAM,batcher,gmic,PhotoGIMP}.
#               This is what a maintainer's machine looks like, because
#               those clones are also the ones you push from, branch in and
#               open PRs from. It is also the layout gimpsam_dep.py already
#               assumes: it loads ../GIMPSAM relative to this checkout.
#
#   in-repo   — the clones sit inside GITHUB_FOLDERS_OF_LAZYGIMP_COMPONENTS/.
#               Self-contained, and what someone who just cloned LazyGimp
#               gets by following that folder's README.
#
# Sibling wins when both exist, because when the two disagree the sibling
# copy is the one that actually runs — an in-repo GIMPSAM can sit thirteen
# commits behind the one LazyGimp imports, and reading the wrong one is
# worse than not having it.
# ---------------------------------------------------------------------------

# Directory names we expect to find; also the order things get reported in.
COMPONENT_DIRS=(GIMPSAM batcher PhotoGIMP gmic)

_holds_components() {
  local dir=$1 name
  [[ -d "$dir" ]] || return 1
  for name in "${COMPONENT_DIRS[@]}"; do
    [[ -d "${dir}/${name}/.git" ]] && return 0
  done
  return 1
}

resolve_components_dir() {
  local root=$1

  if [[ -n "${LAZYGIMP_COMPONENTS_DIR:-}" ]]; then
    if _holds_components "$LAZYGIMP_COMPONENTS_DIR"; then
      echo "$LAZYGIMP_COMPONENTS_DIR"
      return 0
    fi
    echo "[FAIL] LAZYGIMP_COMPONENTS_DIR=${LAZYGIMP_COMPONENTS_DIR} holds no component clones" >&2
    return 1
  fi

  local sibling in_repo
  sibling="$(dirname "$root")"
  in_repo="${root}/GITHUB_FOLDERS_OF_LAZYGIMP_COMPONENTS"

  if _holds_components "$sibling"; then
    echo "$sibling"
    return 0
  fi
  if _holds_components "$in_repo"; then
    echo "$in_repo"
    return 0
  fi

  echo "[FAIL] no component clones found." >&2
  echo "       Looked next to this checkout (${sibling}) and inside it" >&2
  echo "       (${in_repo}); set LAZYGIMP_COMPONENTS_DIR to point elsewhere." >&2
  echo "       To populate the in-repo layout, see that folder's README." >&2
  return 1
}

# The LazyGimp checkout itself lives inside the components dir under the
# sibling layout. It is the repo being worked in — never sync it from a
# script that is running out of it.
is_self() {
  local candidate=$1 root=$2
  [[ "$(cd "$candidate" && pwd -P)" == "$(cd "$root" && pwd -P)" ]]
}

#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/check-component-releases.sh — what has upstream *released*, versus
# what we have locally.
#
# Different question from update-components.sh: that one syncs source, this
# one asks GitHub for the newest published release of each component.
# LazyGimp installs from releases, not from main, so a component can be
# months ahead in source and unchanged from the installer's point of view —
# and the reverse (a release we don't handle yet) is the case worth
# catching early.
#
# Usage:
#   ./scripts/check-component-releases.sh
#
# Uses `gh` when authenticated (higher rate limit), otherwise plain curl
# against the public API.
# ---------------------------------------------------------------------------
set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT="$(dirname "$HERE")"
COMPONENTS_DIR="${ROOT}/GITHUB_FOLDERS_OF_LAZYGIMP_COMPONENTS"

# repo|local clone dir|how LazyGimp consumes it
COMPONENTS=(
  "pierspad/GIMPSAM|GIMPSAM|gimpsam-src.zip asset — LazyGimp's SAM source of truth"
  "kamilburda/batcher|batcher|release asset installed into GIMP's plug-ins"
  "Diolinux/PhotoGIMP|PhotoGIMP|release zip unpacked into GIMP's config"
  "GreycLab/gmic|gmic|installed as a Flatpak extension, not from this repo"
)

api() {
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    gh api "$1" 2>/dev/null
  else
    curl -fsSL -H "Accept: application/vnd.github+json" \
      "https://api.github.com/$1" 2>/dev/null
  fi
}

printf "%-22s %-16s %-12s %s\n" "COMPONENT" "LATEST RELEASE" "PUBLISHED" "LOCAL CLONE"
printf "%-22s %-16s %-12s %s\n" "---------" "--------------" "---------" "-----------"

stale=0
for entry in "${COMPONENTS[@]}"; do
  IFS='|' read -r repo dir note <<<"$entry"

  json="$(api "repos/${repo}/releases/latest")"
  tag="$(jq -r '.tag_name // empty' <<<"$json" 2>/dev/null)"
  date="$(jq -r '.published_at // empty' <<<"$json" 2>/dev/null | cut -dT -f1)"
  [[ -z "$tag" ]] && { tag="(none/unreachable)"; date="-"; }

  clone="${COMPONENTS_DIR}/${dir}"
  if [[ -d "${clone}/.git" ]]; then
    head_date="$(git -C "$clone" log -1 --format=%cs 2>/dev/null)"
    # Is the released tag actually present in the clone? If not, the clone
    # predates the release and wants an update-components.sh run.
    if [[ "$tag" != "(none/unreachable)" ]] \
       && ! git -C "$clone" rev-parse --verify --quiet "refs/tags/${tag}" >/dev/null; then
      local_state="HEAD ${head_date} — TAG ${tag} MANCANTE, aggiorna"
      ((stale++))
    else
      local_state="HEAD ${head_date}"
    fi
  else
    local_state="non clonato"
    ((stale++))
  fi

  printf "%-22s %-16s %-12s %s\n" "$repo" "$tag" "$date" "$local_state"
  printf "%-22s %s\n" "" "  ↳ ${note}"
done

echo
if ((stale)); then
  echo "${stale} componente/i non allineato/i — esegui ./scripts/update-components.sh"
else
  echo "Ogni clone contiene il tag dell'ultima release pubblicata."
fi

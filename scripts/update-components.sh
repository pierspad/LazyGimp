#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/update-components.sh — bring every upstream clone under
# GITHUB_FOLDERS_OF_LAZYGIMP_COMPONENTS/ up to date, and say what changed.
#
# Run this at the start of a working session. LazyGimp itself never reads
# these clones (it resolves versions from the GitHub API at runtime); they
# exist so that the code we integrate against can actually be read — which
# is the difference between "the API probably works like this" and knowing.
#
# Safety: fast-forward only, and any clone with local modifications or
# unpushed commits is reported and left completely alone. Nothing here can
# lose work.
#
# Usage:
#   ./scripts/update-components.sh
# ---------------------------------------------------------------------------
set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT="$(dirname "$HERE")"
COMPONENTS_DIR="${ROOT}/GITHUB_FOLDERS_OF_LAZYGIMP_COMPONENTS"

if [[ ! -d "$COMPONENTS_DIR" ]]; then
  echo "[FAIL] no component clones at ${COMPONENTS_DIR}" >&2
  echo "       clone them first, e.g.:" >&2
  echo "       git clone https://github.com/kamilburda/batcher.git \\" >&2
  echo "                 \"${COMPONENTS_DIR}/batcher\"" >&2
  exit 1
fi

changed=0
current=0
skipped=0
failed=0

for repo in "$COMPONENTS_DIR"/*/; do
  name="$(basename "$repo")"
  if [[ ! -d "${repo}.git" ]]; then
    echo "[skip] ${name}: not a git clone"
    ((skipped++))
    continue
  fi

  # Never touch a clone someone is working in.
  if [[ -n "$(git -C "$repo" status --porcelain 2>/dev/null)" ]]; then
    echo "[skip] ${name}: has local changes — left untouched"
    ((skipped++))
    continue
  fi

  branch="$(git -C "$repo" symbolic-ref --short HEAD 2>/dev/null || true)"
  if [[ -z "$branch" ]]; then
    echo "[skip] ${name}: detached HEAD — left untouched"
    ((skipped++))
    continue
  fi

  before="$(git -C "$repo" rev-parse HEAD)"
  if ! git -C "$repo" fetch --quiet --tags --prune origin 2>/dev/null; then
    echo "[FAIL] ${name}: fetch failed (network? credentials?)"
    ((failed++))
    continue
  fi

  # --ff-only: if upstream force-pushed or the local branch diverged, stop
  # and say so rather than merging or rewriting anything.
  if ! git -C "$repo" merge --quiet --ff-only "origin/${branch}" 2>/dev/null; then
    echo "[FAIL] ${name}: cannot fast-forward ${branch} — diverged from origin"
    ((failed++))
    continue
  fi

  after="$(git -C "$repo" rev-parse HEAD)"
  if [[ "$before" == "$after" ]]; then
    echo "[ ok ] ${name}: already current ($(git -C "$repo" log -1 --format=%cs))"
    ((current++))
  else
    count="$(git -C "$repo" rev-list --count "${before}..${after}")"
    echo "[NEW ] ${name}: ${count} new commit(s) on ${branch}"
    git -C "$repo" log --oneline --no-decorate "${before}..${after}" | head -n 10 | sed 's/^/         /'
    ((changed++))
  fi
done

echo
echo "aggiornati: ${changed}   già aggiornati: ${current}   saltati: ${skipped}   errori: ${failed}"
echo "Per confrontare con le release pubblicate: ./scripts/check-component-releases.sh"
exit $(( failed > 0 ? 1 : 0 ))

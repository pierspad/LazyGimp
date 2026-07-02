#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# lib/common.sh — shared helpers for every LazyGimp script.
# Meant to be sourced, never executed directly.
# ---------------------------------------------------------------------------

if [[ -n "${_LAZYGIMP_COMMON_LOADED:-}" ]]; then return 0; fi
readonly _LAZYGIMP_COMMON_LOADED=1

LAZYGIMP_ROOT="${LAZYGIMP_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)}"
readonly LAZYGIMP_ROOT

# shellcheck source=config/versions.conf
source "${LAZYGIMP_ROOT}/config/versions.conf"

# --------------------------------- logging --------------------------------
if [[ -t 2 ]]; then
  _C_RESET=$'\033[0m' _C_INFO=$'\033[1;34m' _C_WARN=$'\033[1;33m' _C_ERR=$'\033[1;31m' _C_OK=$'\033[1;32m'
else
  _C_RESET='' _C_INFO='' _C_WARN='' _C_ERR='' _C_OK=''
fi

log::info()  { printf '%s[info]%s %s\n' "${_C_INFO}" "${_C_RESET}" "$*" >&2; }
log::ok()    { printf '%s[ ok ]%s %s\n' "${_C_OK}"   "${_C_RESET}" "$*" >&2; }
log::warn()  { printf '%s[warn]%s %s\n' "${_C_WARN}" "${_C_RESET}" "$*" >&2; }
log::error() { printf '%s[fail]%s %s\n' "${_C_ERR}"  "${_C_RESET}" "$*" >&2; }
die()        { log::error "$*"; exit 1; }

# --------------------------------- checks ---------------------------------
have()    { command -v "$1" >/dev/null 2>&1; }
require() {
  local cmd
  for cmd in "$@"; do
    have "$cmd" || die "required command not found: ${cmd}"
  done
}

# ------------------------- privilege escalation ---------------------------
# Run a command as root, using whatever the system provides.
as_root() {
  if [[ ${EUID} -eq 0 ]]; then
    "$@"
  elif have sudo; then
    sudo "$@"
  elif have doas; then
    doas "$@"
  else
    die "root privileges required for: $* (install sudo/doas or run as root)"
  fi
}

# --------------------- temp dirs with automatic cleanup --------------------
_LAZYGIMP_TMPDIRS=()

make_tmpdir() {
  local tmp
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/lazygimp.XXXXXX")"
  _LAZYGIMP_TMPDIRS+=("$tmp")
  printf '%s\n' "$tmp"
}

_lazygimp_cleanup() {
  local dir
  for dir in "${_LAZYGIMP_TMPDIRS[@]}"; do
    rm -rf -- "$dir"
  done
}
trap _lazygimp_cleanup EXIT

# -------------------------------- downloads --------------------------------
download() { # download <url> <dest-file>
  local url="$1" dest="$2"
  log::info "downloading ${url}"
  if have curl; then
    curl -fsSL --retry 3 -o "$dest" "$url"
  elif have wget; then
    wget -qO "$dest" "$url"
  else
    die "neither curl nor wget is available"
  fi
}

fetch() { # fetch <url> → stdout
  if have curl; then
    curl -fsSL --retry 3 "$1"
  elif have wget; then
    wget -qO- "$1"
  else
    die "neither curl nor wget is available"
  fi
}

sha256_verify() { # sha256_verify <file> <expected-hash>
  local file="$1" expected="$2" actual
  actual="$(sha256sum "$file" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    die "checksum mismatch for ${file} (expected ${expected}, got ${actual})"
  fi
  log::info "checksum verified for $(basename "$file")"
}

# ---------------------------- distro detection -----------------------------
# Echo the distro family that has a matching shell_scripts/<family>.sh,
# trying ID first and then every entry of ID_LIKE. Fails if unsupported.
lazygimp::detect_distro() {
  [[ -r /etc/os-release ]] || return 1
  local id id_like candidate
  id="$(. /etc/os-release && printf '%s' "${ID:-}")"
  id_like="$(. /etc/os-release && printf '%s' "${ID_LIKE:-}")"
  for candidate in $id $id_like; do
    if [[ -f "${LAZYGIMP_ROOT}/shell_scripts/${candidate}.sh" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

#!/usr/bin/env bash
# Prepare the worktree this script lives in: sync local main from origin/main,
# rebase the current branch onto it, and link the main repo's config.local.yaml.
#
# Works from any worktree and any working directory: the target worktree is the
# one that contains this script, and the main worktree is discovered through
# `git rev-parse --git-common-dir` (no hardcoded repository path).
set -euo pipefail

PROG="[init_worktree]"

log() { printf '%s %s\n' "${PROG}" "$*"; }
warn() { printf '%s WARNING: %s\n' "${PROG}" "$*" >&2; }
err() { printf '%s ERROR: %s\n' "${PROG}" "$*" >&2; }
die() { err "$*"; exit 1; }

usage() {
  cat <<'EOF'
usage: scripts/init_worktree.sh [--force] [--help]

Initialise the worktree that contains this script (run it from anywhere inside
that worktree):

  1. locate the main worktree and the current branch;
  2. fetch origin/main and fast-forward the local main branch inside the main
     worktree (main is normally checked out there, so it is advanced with
     `git -C <main> merge --ff-only`, never `git fetch origin main:main`);
  3. rebase the current branch onto origin/main -- on conflict the rebase is
     aborted, the branch is left untouched and the script exits non-zero;
  4. link config.local.yaml to the main repo's copy.

options:
  -f, --force   replace an existing config.local.yaml after backing it up to
                config.local.yaml.bak.<timestamp>
  -h, --help    show this help and exit

config.local.yaml symlink policy:
  * missing target           -> symlink is created
  * symlink to main config   -> no-op (the script is idempotent)
  * symlink somewhere else   -> refreshed to point at the main config
  * regular file             -> refused; nothing is destroyed. Pass --force to
                                back it up (config.local.yaml.bak.<timestamp>)
                                and replace it with the symlink.

exit codes:
  0  done (or nothing to do; a non-fast-forwardable main is reported and the
     branch is still rebased onto origin/main)
  1  stopped: rebase conflict, uncommitted changes in this worktree, or a
     config.local.yaml that would have to be overwritten without --force
EOF
}

FORCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -f|--force)
      FORCE=1
      shift
      ;;
    --)
      shift
      break
      ;;
    *)
      usage >&2
      die "unknown argument: $1"
      ;;
  esac
done

command -v git >/dev/null 2>&1 || die "git is required but was not found in PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKTREE_DIR="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null)" ||
  die "not inside a git worktree: ${SCRIPT_DIR}"
CURRENT_BRANCH="$(git -C "${WORKTREE_DIR}" symbolic-ref --quiet --short HEAD)" ||
  die "detached HEAD in ${WORKTREE_DIR}; check out a branch before initialising"

# -- main worktree -------------------------------------------------------
# From a linked worktree --git-common-dir is the absolute path of the main
# repo's .git; in the main worktree it is the relative ".git".
GIT_COMMON_DIR="$(git -C "${WORKTREE_DIR}" rev-parse --git-common-dir)"
case "${GIT_COMMON_DIR}" in
  /*) ;;
  *) GIT_COMMON_DIR="${WORKTREE_DIR}/${GIT_COMMON_DIR}" ;;
esac
MAIN_WORKTREE="$(cd "${GIT_COMMON_DIR}/.." && pwd)"

log "worktree:  ${WORKTREE_DIR}"
log "branch:    ${CURRENT_BRANCH}"
log "main repo: ${MAIN_WORKTREE}"

# Where (if anywhere) is local main checked out?
MAIN_CHECKOUT=""
WORKTREE_PATH=""
while IFS= read -r line; do
  case "${line}" in
    worktree\ *)
      WORKTREE_PATH="${line#worktree }"
      ;;
    branch\ refs/heads/main)
      MAIN_CHECKOUT="${WORKTREE_PATH}"
      break
      ;;
    "")
      WORKTREE_PATH=""
      ;;
  esac
done < <(git -C "${WORKTREE_DIR}" worktree list --porcelain)

# -- fetch origin/main ---------------------------------------------------
if ! FETCH_OUT="$(git -C "${WORKTREE_DIR}" fetch origin main 2>&1)"; then
  err "could not fetch origin/main from this worktree:"
  printf '%s\n' "${FETCH_OUT}" >&2
  exit 1
fi
log "fetched origin/main"

if ORIGIN_REF="$(git -C "${WORKTREE_DIR}" rev-parse --verify --quiet refs/remotes/origin/main)"; then
  ORIGIN_SHA="$(git -C "${WORKTREE_DIR}" rev-parse "${ORIGIN_REF}")"
else
  # Older git versions do not update the remote-tracking ref for a fetch by name.
  ORIGIN_REF="FETCH_HEAD"
  ORIGIN_SHA="$(git -C "${WORKTREE_DIR}" rev-parse --verify --quiet FETCH_HEAD)" ||
    die "origin/main not found after fetching"
fi

# -- fast-forward local main --------------------------------------------
LOCAL_MAIN_SHA="$(git -C "${WORKTREE_DIR}" rev-parse --verify --quiet refs/heads/main || true)"
if [[ -z "${LOCAL_MAIN_SHA}" ]]; then
  git -C "${WORKTREE_DIR}" branch main "${ORIGIN_SHA}"
  log "created local main at $(git -C "${WORKTREE_DIR}" rev-parse --short "${ORIGIN_SHA}")"
fi

if [[ "${LOCAL_MAIN_SHA}" == "${ORIGIN_SHA}" ]]; then
  log "main is already up to date with origin/main ($(git -C "${WORKTREE_DIR}" rev-parse --short "${ORIGIN_SHA}"))"
else
  if ! git -C "${WORKTREE_DIR}" merge-base --is-ancestor "${LOCAL_MAIN_SHA}" "${ORIGIN_SHA}"; then
    warn "local main has diverged from origin/main; leaving main at $(git -C "${WORKTREE_DIR}" rev-parse --short "${LOCAL_MAIN_SHA}")"
    warn "resolve it in ${MAIN_WORKTREE} (commit, reset or pull --rebase) before syncing again"
  elif [[ -z "${MAIN_CHECKOUT}" ]]; then
    if git -C "${WORKTREE_DIR}" branch -f main "${ORIGIN_SHA}"; then
      log "fast-forwarded local main to $(git -C "${WORKTREE_DIR}" rev-parse --short "${ORIGIN_SHA}") (not checked out)"
    else
      warn "could not fast-forward local main"
    fi
  elif [[ "${MAIN_CHECKOUT}" != "${MAIN_WORKTREE}" ]]; then
    warn "local main is checked out in another worktree (${MAIN_CHECKOUT}); update it there"
  elif ! FF_OUT="$(git -C "${MAIN_WORKTREE}" merge --ff-only "${ORIGIN_REF}" 2>&1)"; then
    warn "could not fast-forward main in ${MAIN_WORKTREE}:"
    printf '%s\n' "${FF_OUT}" >&2
    warn "commit or stash the changes there and re-run this script"
  else
    log "fast-forwarded local main to $(git -C "${MAIN_WORKTREE}" rev-parse --short main) in ${MAIN_WORKTREE}"
  fi
fi

# -- rebase the current branch onto origin/main --------------------------
if [[ "${CURRENT_BRANCH}" == "main" ]]; then
  log "already on main; no rebase needed"
elif [[ -n "$(git -C "${WORKTREE_DIR}" status --porcelain --untracked-files=no)" ]]; then
  die "this worktree has uncommitted tracked changes; commit or stash them before rebasing onto origin/main"
else
  BEFORE_SHA="$(git -C "${WORKTREE_DIR}" rev-parse HEAD)"
  if REBASE_OUT="$(git -C "${WORKTREE_DIR}" rebase "${ORIGIN_REF}" 2>&1)"; then
    if [[ -n "${REBASE_OUT}" ]]; then
      printf '%s\n' "${REBASE_OUT}"
    fi
    AFTER_SHA="$(git -C "${WORKTREE_DIR}" rev-parse HEAD)"
    if [[ "${BEFORE_SHA}" == "${AFTER_SHA}" ]]; then
      log "${CURRENT_BRANCH} is already up to date with origin/main"
    else
      log "rebased ${CURRENT_BRANCH} onto origin/main ($(git -C "${WORKTREE_DIR}" rev-parse --short "${BEFORE_SHA}") -> $(git -C "${WORKTREE_DIR}" rev-parse --short "${AFTER_SHA}"))"
    fi
  else
    printf '%s\n' "${REBASE_OUT}" >&2
    if [[ -d "$(git -C "${WORKTREE_DIR}" rev-parse --git-path rebase-merge)" ]] ||
      [[ -d "$(git -C "${WORKTREE_DIR}" rev-parse --git-path rebase-apply)" ]]; then
      err "=============================================================="
      err "rebase CONFLICT: rebasing ${CURRENT_BRANCH} onto origin/main hit conflicts"
      CONFLICTS="$(git -C "${WORKTREE_DIR}" diff --name-only --diff-filter=U)"
      if [[ -n "${CONFLICTS}" ]]; then
        err "conflicting files:"
        printf '  %s\n' "${CONFLICTS}" >&2
      fi
      err "resolving them manually would lose the script's safe-stop guarantee,"
      err "so the rebase is being aborted and ${CURRENT_BRANCH} is left at $(git -C "${WORKTREE_DIR}" rev-parse --short "${BEFORE_SHA}")"
      if ! git -C "${WORKTREE_DIR}" rebase --abort; then
        err "could not abort the rebase automatically; finish it with: git rebase --abort"
      fi
      err "rebase aborted; fix the conflict on ${CURRENT_BRANCH} and re-run this script"
      err "=============================================================="
    else
      err "rebase of ${CURRENT_BRANCH} onto origin/main failed; the branch was not changed"
    fi
    exit 1
  fi
fi

# -- link config.local.yaml ---------------------------------------------
if [[ "${WORKTREE_DIR}" == "${MAIN_WORKTREE}" ]]; then
  log "this is the main worktree; config.local.yaml is used in place"
  exit 0
fi

MAIN_CONFIG="${MAIN_WORKTREE}/config.local.yaml"
TARGET_CONFIG="${WORKTREE_DIR}/config.local.yaml"

if [[ ! -e "${MAIN_CONFIG}" ]]; then
  log "no ${MAIN_CONFIG} to link"
  log "hint: create it in ${MAIN_WORKTREE} with only the fields that differ from config.yaml, then re-run this script"
  exit 0
fi

if [[ -L "${TARGET_CONFIG}" ]]; then
  CURRENT_TARGET="$(readlink "${TARGET_CONFIG}")"
  case "${CURRENT_TARGET}" in
    /*) CURRENT_TARGET_ABS="${CURRENT_TARGET}" ;;
    *) CURRENT_TARGET_ABS="${WORKTREE_DIR}/${CURRENT_TARGET}" ;;
  esac
  if [[ "${CURRENT_TARGET_ABS}" == "${MAIN_CONFIG}" ]]; then
    log "config.local.yaml already links to ${MAIN_CONFIG}"
    exit 0
  fi
  ln -sfn "${MAIN_CONFIG}" "${TARGET_CONFIG}"
  log "refreshed config.local.yaml: ${CURRENT_TARGET} -> ${MAIN_CONFIG}"
  exit 0
fi

if [[ -e "${TARGET_CONFIG}" ]]; then
  if [[ "${FORCE}" -ne 1 ]]; then
    err "${TARGET_CONFIG} is a regular file, not a symlink; refusing to overwrite it"
    err "back it up and re-run with --force to back it up and replace it with a symlink to ${MAIN_CONFIG}"
    exit 1
  fi
  BACKUP="${TARGET_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"
  mv "${TARGET_CONFIG}" "${BACKUP}"
  log "backed up ${TARGET_CONFIG} to ${BACKUP}"
fi

ln -s "${MAIN_CONFIG}" "${TARGET_CONFIG}"
log "linked config.local.yaml -> ${MAIN_CONFIG}"
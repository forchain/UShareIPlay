#!/usr/bin/env bash
# Prepare the worktree this script lives in: sync local main from origin/main,
# rebase the current branch onto it, link the main repo's config.local.yaml and .codegraph,
# and sync the codegraph index.
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
  4. link config.local.yaml and .codegraph to the main repo's copies;
  5. sync .codegraph if present and codegraph is available.

options:
  -f, --force   replace an existing config.local.yaml or .codegraph after backing
                it up to <path>.bak.<timestamp>
  -h, --help    show this help and exit

symlink policy (config.local.yaml and .codegraph):
  * missing target           -> symlink is created
  * symlink to main copy     -> no-op (the script is idempotent)
  * symlink somewhere else   -> refreshed to point at the main copy
  * regular file/dir         -> refused; nothing is destroyed. Pass --force to
                                back it up (<path>.bak.<timestamp>)
                                and replace it with the symlink.
  * main repo has none       -> skipped with a friendly note

exit codes:
  0  done (or nothing to do; a non-fast-forwardable main is reported and the
     branch is still rebased onto origin/main)
  1  stopped: rebase conflict, uncommitted changes in this worktree, or a
     file/dir that would have to be overwritten without --force
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
        # One indented line per path: git emits them newline-separated, and
        # paths may contain spaces, so read them individually.
        while IFS= read -r conflicted_path; do
          printf '  %s\n' "${conflicted_path}" >&2
        done <<< "${CONFLICTS}"
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

# -- link config.local.yaml and .codegraph -------------------------------
if [[ "${WORKTREE_DIR}" == "${MAIN_WORKTREE}" ]]; then
  log "this is the main worktree; config.local.yaml and .codegraph are used in place"
else
  link_item() {
    local name="$1"
    local main_path="$2"
    local target_path="$3"

    if [[ -L "${target_path}" ]]; then
      local current_target
      current_target="$(readlink "${target_path}")"
      local current_target_abs
      case "${current_target}" in
        /*) current_target_abs="${current_target}" ;;
        *) current_target_abs="${WORKTREE_DIR}/${current_target}" ;;
      esac
      if [[ "${current_target_abs}" == "${main_path}" ]]; then
        log "${name} already links to ${main_path}"
        return 0
      fi
      ln -sfn "${main_path}" "${target_path}"
      log "refreshed ${name}: ${current_target} -> ${main_path}"
      return 0
    fi

    if [[ -e "${target_path}" ]]; then
      if [[ "${FORCE}" -ne 1 ]]; then
        local kind="a regular file"
        if [[ -d "${target_path}" && ! -L "${target_path}" ]]; then
          kind="a directory"
        fi
        err "${target_path} is ${kind}, not a symlink; refusing to overwrite it"
        err "back it up and re-run with --force to back it up and replace it with a symlink to ${main_path}"
        return 1
      fi
      local backup="${target_path}.bak.$(date +%Y%m%d%H%M%S)"
      mv "${target_path}" "${backup}"
      log "backed up ${target_path} to ${backup}"
    fi

    ln -s "${main_path}" "${target_path}"
    log "linked ${name} -> ${main_path}"
  }

  MAIN_CONFIG="${MAIN_WORKTREE}/config.local.yaml"
  TARGET_CONFIG="${WORKTREE_DIR}/config.local.yaml"

  if [[ ! -e "${MAIN_CONFIG}" ]]; then
    log "no ${MAIN_CONFIG} to link"
    log "hint: create it in ${MAIN_WORKTREE} with only the fields that differ from config.yaml, then re-run this script"
  else
    link_item "config.local.yaml" "${MAIN_CONFIG}" "${TARGET_CONFIG}" || exit 1
  fi

  MAIN_CODEGRAPH="${MAIN_WORKTREE}/.codegraph"
  TARGET_CODEGRAPH="${WORKTREE_DIR}/.codegraph"

  if [[ ! -e "${MAIN_CODEGRAPH}" ]]; then
    log "no ${MAIN_CODEGRAPH} to link; skipping"
  else
    link_item ".codegraph" "${MAIN_CODEGRAPH}" "${TARGET_CODEGRAPH}" || exit 1
  fi
fi

# -- sync codegraph -----------------------------------------------------
if [[ -e "${WORKTREE_DIR}/.codegraph" ]]; then
  if command -v codegraph >/dev/null 2>&1; then
    if SYNC_OUT="$(cd "${WORKTREE_DIR}" && codegraph sync -q "${WORKTREE_DIR}" 2>&1)"; then
      if [[ -n "${SYNC_OUT}" ]]; then
        printf '%s\n' "${SYNC_OUT}"
      fi
      log "synced codegraph"
    else
      warn "codegraph sync failed:"
      printf '%s\n' "${SYNC_OUT}" >&2
    fi
  else
    warn "codegraph not found in PATH; skipping sync"
  fi
fi

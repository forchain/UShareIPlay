---
covers: [scripts/init_worktree.sh, git worktree, config.local.yaml, .codegraph]
last-synced: 2026-11-07
---

## Overview

`scripts/init_worktree.sh` prepares a freshly created git worktree so it is immediately
usable: it syncs the local `main` branch from `origin/main`, rebases the worktree branch
onto it, links the main repository's `config.local.yaml` and `.codegraph`, and syncs
the codegraph index.

```bash
scripts/init_worktree.sh            # sync main, rebase, link config and .codegraph, sync index
scripts/init_worktree.sh --force    # also replace pre-existing config.local.yaml or .codegraph
scripts/init_worktree.sh --help     # usage + symlink conflict policy
```

## What It Does

| Step | Behaviour |
|---|---|
| Locate | Target worktree = the one containing the script; main worktree = parent of `git rev-parse --git-common-dir` (no hardcoded repository path) |
| Fetch | `git fetch origin main` — **not** `git fetch origin main:main`, which fails while `main` is checked out |
| Fast-forward | `git -C <main worktree> merge --ff-only origin/main`; a diverged or dirty main is reported, never force-overwritten |
| Rebase | `git rebase origin/main` in the current worktree; on conflict the rebase is aborted, the branch keeps its original commit and the script exits non-zero |
| Link | `config.local.yaml` → `<main worktree>/config.local.yaml` and `.codegraph` → `<main worktree>/.codegraph` |
| Sync | `codegraph sync` in the worktree if `.codegraph` exists and `codegraph` CLI is available |

The script is idempotent: a second run rebases nothing and leaves an already-correct
symlink untouched.

## Symlink Policy (config.local.yaml and .codegraph)

| Existing state at `<worktree>/<item>` | Result |
|---|---|
| Missing | Symlink created |
| Symlink to the main copy | No-op, exit 0 |
| Symlink to some other path | Refreshed to the main copy |
| Regular file or directory | Refused with a clear message; `--force` backs it up to `<item>.bak.<timestamp>` before replacing it |
| Main repo has no such item | Friendly hint/skip, exit 0 |

Running the script inside the main worktree itself skips the symlink step (the config and
`.codegraph` are already in place there).

## Notes

- `run.sh` performs the same `config.local.yaml` link on startup, locating the main worktree
  with the identical `git rev-parse --git-common-dir` technique — so running the bot from a
  fresh worktree wires the config even if this script was never run. This script remains the
  one-stop option because it also syncs `main` and rebases the branch.
- Behavioural coverage lives in `tests/test_init_worktree_script.py`, which runs the real
  script against throwaway git environments built in `tmp_path`, and in
  `tests/test_run_sh_config_link.py` for the `run.sh` linking path.
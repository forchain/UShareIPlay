# AGENTS.md

## Cursor Cloud specific instructions

### Overview

UShareIPlay is a Python Android automation bot for **Soul App** + **QQ Music** via Appium. See `CLAUDE.md` and `README.md` for full architecture and command reference.

### Virtual environment

The `.venv` virtual environment is pre-created. Always activate before running anything:

```bash
source .venv/bin/activate
```

### Running tests

Use pytest via `uv run`:

```bash
uv run pytest -q
```

To run focused subsets while iterating:

```bash
uv run pytest -q tests/test_db_manager.py tests/test_timer_add.py
```

### Running `main.py`

`main.py` loads `config.yaml`, initializes SQLite DB at `data/soul_bot.db`, then attempts to connect to an Appium server. **It will always fail in the cloud VM** because it requires:
1. A running Appium server with a connected Android device
2. Soul App and QQ Music installed on the device

To validate code changes without a device, use pytest suites and focused unit tests with in-memory SQLite.

### Linting

No linter configuration (flake8/pylint/ruff) is committed. Use `python -m py_compile <file>` to syntax-check individual files.

### Key gotchas

- `config.yaml` is 26k+ lines. Local overrides go in `config.local.yaml` (gitignored). See `config.local.yaml.example`.
- Singleton creation is limited to the composition root: call `.initialize(...)` exactly once there, then use `.instance()` for lookup only. Never construct singleton classes directly.
- The project is configured via `pyproject.toml` and can be run with `uv run ushareiplay`.

### GitHub / PR account switching

When creating or editing pull requests with `gh`, the correct GitHub account depends on the repository remote URL.

- **Rule**: Read `remote.origin.url` and extract the username before `@github.com` (e.g. `https://forchain@github.com/forchain/UShareIPlay` → `forchain`). Temporarily switch `gh` to that account for PR operations, then switch back.

### PR branch naming rule (rename random branches)

If the current branch name is randomly generated and unrelated to the change (e.g. worktree default names like `lava-flint`), then **before creating a PR**:

1. **Rename the current branch** to a meaningful kebab-case name that matches the change intent (e.g. `fix/async-command-parser-recovery`).
2. **Then** create the PR from the renamed branch.

Example:

```bash
git config --get remote.origin.url
gh auth status -h github.com
gh auth switch -h github.com -u <remote-username>

# PR operations (create/edit/view)
gh pr create ...

# Switch back (pick whatever was active before)
gh auth switch -h github.com -u <previous-active-username>
```

### PR reuse rule in same worktree (NEVER create a new PR if one exists)

**全局铁律**：如果当前 worktree 不变，且已有打开的 PR，**必须直接复用已有的 PR**（向该 PR 分支追加 commit 并 push），**严禁在已有 PR 的情况下创建新的 PR**。
- 如果觉得当前 PR 的描述或分支名不合适，允许修正（如通过 `gh pr edit` 更新标题和描述），但绝不允许在已有 PR 的情况下创建新 PR，必须复用已有 PR。

### 日志输出铁律（禁止输出无行为触发的监控轮询日志）

**全局铁律**：严禁在循环监控、轮询、周期性检测（如麦位观测、UI 锁获取/释放、心跳巡检等）中输出无行为触发的监控日志。
- **只有触发了具体行为才输出日志**：例如检测到麦位/用户变更、解析并执行命令、进入/离开房间、发起弹窗交互或出现异常/错误时，才允许输出日志。
- **禁止在日常轮询中刷屏**：常规空转巡检、定时扫描、锁的常规获取与释放等内部机制，严禁使用 INFO/CRITICAL 等级别打印无动作的监控日志（仅可在排查问题时置于 DEBUG 级别），保持控制台与运行时日志整洁。



## Agent skills

### Issue tracker

GitHub Issues on `forchain/UShareIPlay`; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles use default label names (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: `CONTEXT.md` at repo root and `docs/adr/` for ADRs. See `docs/agents/domain.md`.

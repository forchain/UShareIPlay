# AGENTS.md

## Project Overview

UShareIPlay is a Python-based Android automation framework that controls **Soul App** (Chinese social platform) and **QQ Music** via Appium. It provides music playback management, room administration, and interactive features through a command-driven architecture. See `README.md` for the full command reference.

## Environment Setup

```bash
# Activate virtual environment (pre-created in cloud VM)
source .venv/bin/activate

# Install / sync dependencies
uv sync

# Configure per-machine settings (optional override; gitignored)
# config.local.yaml holds ONLY the fields that differ from config.yaml:
# nested dicts merge per-key, lists are replaced wholesale.
# An existing config.local.yaml is never truncated: edit it by hand instead.
if [ -e config.local.yaml ]; then
  echo "config.local.yaml already exists — edit it in place" >&2
else
  cat > config.local.yaml <<'EOF'
device:
  name: "192.168.1.100:5555"
appium:
  host: "127.0.0.1"
EOF
fi

# Start Appium server (separate terminal)
./appium.sh
# or: appium --allow-insecure=adb_shell,chromedriver_autodownload

# Run the bot
./run.sh
# or: uv run ushareiplay
```

### Working in a git worktree

After `git worktree add`, run `./scripts/init_worktree.sh` from inside the new worktree. It
locates the main worktree, fast-forwards local `main` from `origin/main` (main is checked out
there, so it is advanced in place rather than by fetching into it), rebases the worktree branch
onto the new main (aborting safely on conflict), and links the main repo's
`config.local.yaml`. See `docs/worktree-init.md`.

### Running tests

Use pytest via `uv run`:

```bash
uv run pytest -q
```

To run focused subsets while iterating:

```bash
uv run pytest -q tests/test_db_manager.py tests/test_timer_add.py
```

### Running `main.py` / `uv run ushareiplay`

`main.py` loads `config.yaml`, initializes SQLite DB at `data/soul_bot.db`, then attempts to connect to an Appium server. **It will fail without a live Android device** because it requires:
1. A running Appium server with a connected Android device
2. Soul App and QQ Music installed on the device

To validate code changes without a device, use pytest suites and focused unit tests with in-memory SQLite.

### Linting

No linter configuration (flake8/pylint/ruff) is committed. Use `python -m py_compile <file>` to syntax-check individual files.

## Architecture

### Initialization Flow

```
uv run ushareiplay  (or python main.py)
  → ConfigLoader.load_config('config.yaml')
  → DatabaseManager.init()            # Tortoise ORM schema initialization
  → AppController.initialize(config)  # Creates DriverLifecycle, starts apps
  → CommandManager.load_all_commands() # Auto-discovers ushareiplay/commands/*.py
  → controller.start_monitoring()     # Starts EventManager and Chat Intaker tasks
```

### Key Design Patterns

- **Singleton** — The composition root creates managers and handlers once with `.initialize(...)`; all other code uses `.instance()` as a lookup-only API. Never call singleton constructors directly.
- **Manager Pattern** — Business logic split into 20+ specialized managers under `src/ushareiplay/managers/`
- **Command Pattern** — 37+ commands under `src/ushareiplay/commands/`, all inheriting from `BaseCommand`; commands are auto-discovered by `CommandManager` — no registration needed
- **DAO Pattern** — Database access via DAOs in `src/ushareiplay/dal/`; models in `src/ushareiplay/models/` using Tortoise ORM

### Component Relationships

```
AppController
├── SoulHandler       — Soul App UI automation (chat reading, room control)
├── QQMusicHandler    — QQ Music app automation (music operations, lyrics OCR)
├── CommandManager    — Parses and dispatches chat commands
├── EventManager      — Handles UI events (page classifier, drawer, focus/entry events)
├── TimerManager      — Scheduled tasks persisted in DB
├── PartyManager      — Party/room lifecycle management
├── SeatManager       — Seat reservation, focus, validation sub-managers
├── MusicManager      — Playback control
├── PlaybackMuting    — Mic mute/restore around song switching; arms on XXX 已上麦
├── MessageManager    — Async message queue and dispatch
├── RecoveryManager   — Tracks Appium/UI failures; triggers driver reinit or app restart
├── RoomProfileManager — 房间档案唯一所有者（抽屉会话 + 话题/公告/房名草稿）
└── [KeywordManager, InfoManager, UserManager, AdminManager, MemoryManager,
    MicManager, SleepManager, PlaylistAdoption, PendingWrite]
```

### Adding a New Command

1. Create `src/ushareiplay/commands/<name>.py` with exactly one `BaseCommand` subclass
2. Implement `do_process(self, message_info, parameters)` — the concrete `BaseCommand.process()` wrapper owns the shell (handler alias via `handler_attr`, exception → `{'error': ...}` mapping via `error_message`). Declare `playback_muting = True` on commands that switch songs so `CommandManager` runs them inside the `PlaybackMuting` mic lifecycle
3. Do **not** add a `create_command()` factory or a module-level `command = None`
4. Add command config entry in `config.yaml` under the commands section
5. `CommandManager` auto-discovers commands via dynamic loading — no registration needed

### Configuration

`config.yaml` is the master configuration template containing:
- Android device and Appium server settings
- 100+ Soul App UI element XPath selectors
- 80+ QQ Music UI element XPath selectors
- Command templates with response/error message templates

Local overrides go in `config.local.yaml` (gitignored, optional) and MUST contain only the fields that differ from `config.yaml` — nested dicts are merged per-key, lists are replaced wholesale. `config.yaml` is the committed baseline and doubles as the worked example; there is no separate example file.

### Data Layer

- **Database**: SQLite at `data/soul_bot.db` via Tortoise ORM with async/await
- **Models**: `User`, `UserMemory`, `SeatReservation`, `Keyword`, `EnterEvent`, `ExitEvent`, `ReturnEvent`, `ReceiveEvent`, `FocusEvent`, `Timer`, `MessageInfo`
- **DAOs**: `UserDAO`, `EnterDao`, `ExitDao`, `ReturnDao`, `ReceiveDao`, `FocusEventDao`, `KeywordDAO`

### Crash Recovery

`AppHandler` (base class for `SoulHandler`/`QQMusicHandler`) implements automatic crash detection and app restart. `RecoveryManager` tracks consecutive Appium/UI failures and triggers driver reinitialisation or app restart. `main.py` wraps the controller in a retry loop.

## Key Gotchas

- **用户名参数铁律**：同一个人在 Soul UI 上是**可见昵称（分身名）**、在 DB 里是 **canonical 名（主账号名）**，两者字符串不同。任何以用户名作参数的命令（`:seat 3`、`:admin`、`:gift`、`:level`、事件钩子等），DB 侧用 canonical，**面向 UI 的查找必须先 `InfoManager.resolve_visible_username(...)`**；跨命名域比对只能用 `UserDAO.is_same_identity(...)`，严禁拿 canonical 名与 UI 文本做 `==`。详见 `docs/users.md` 的「两个命名域」。

## Logging Policy (铁律)

**全局铁律**：严禁在循环监控、轮询、周期性检测（如麦位观测、UI 锁获取/释放、心跳巡检等）中输出无行为触发的监控日志。
- **只有触发了具体行为才输出日志**：例如检测到麦位/用户变更、解析并执行命令、进入/离开房间、发起弹窗交互或出现异常/错误时，才允许输出日志。
- **禁止在日常轮询中刷屏**：常规空转巡检、定时扫描、锁的常规获取与释放等内部机制，严禁使用 INFO/CRITICAL 等级别打印无动作的监控日志（仅可在排查问题时置于 DEBUG 级别），保持控制台与运行时日志整洁。

## OpenSpec Workflow

This repo uses OpenSpec for structured change management:

```bash
# Propose a new change
/openspec-propose

# Explore/investigate before implementing
/openspec-explore

# Implement tasks from a change
/openspec-apply-change

# Archive after completion
/openspec-archive-change
```

Change specs live in `docs/superpowers/specs/`. Active changes are tracked there with tasks, design docs, and implementation notes.

## GitHub / PR Rules & Account Switching

### Account Switching
When creating or editing pull requests with `gh`, the correct GitHub account depends on the repository remote URL.
- **Rule**: Read `remote.origin.url` and extract the username before `@github.com` (e.g. `https://forchain@github.com/forchain/UShareIPlay` → `forchain`). Temporarily switch `gh` to that account for PR operations, then switch back.

### PR Branch Naming Rule
If the current branch name is randomly generated or non-descriptive (e.g. worktree default names like `lava-flint` or temporary names like `forchain/i-will-read-the-2`), then **before creating a PR**:
1. **Rename the current branch** to a meaningful kebab-case name matching the change intent (e.g. `forchain/<feature-name>` or `feat/<feature-name>`).
2. Push to remote and then create the PR.

Example:
```bash
git config --get remote.origin.url
gh auth status -h github.com
gh auth switch -h github.com -u <remote-username>

# PR operations (create/edit/view)
gh pr create ...

# Switch back
gh auth switch -h github.com -u <previous-active-username>
```

### PR Reuse in Same Worktree (铁律)
**全局铁律**：如果当前 worktree 不变，且已有打开的 PR，**必须直接复用已有的 PR**（向该 PR 分支追加 commit 并 push），**严禁在已有 PR 的情况下创建新的 PR**。
- 若有新增改动且与当前 PR 需求出入较大，直接通过 `gh pr edit` 修改已有 PR 的标题和描述，保持单一 PR 递进；若确实需要拆分新 PR，必须事先与用户明确确认是在当前 worktree 下新开还是另建独立 worktree。

### PR Issue Auto-Close (铁律)
**全局铁律**：创建 Pull Request 时，如果该 PR 与 Issue 关联，必须在 PR 描述（Body）中使用规范的 GitHub 关闭关键字（如 `Closes #123`、`Fixes #123` 或 `Resolves #123`）。
- 若关联多个 Issue，必须对每个 Issue 分别显式声明关键字（如 `Closes #123, Closes #124` 或多行独立声明，严禁写成 `Closes #123, #124`）。

## Agent Skills

### Issue tracker
GitHub Issues on `forchain/UShareIPlay`; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels
Five canonical roles use default label names (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs
Single-context layout: `GLOSSARY.md` at repo root and `docs/adr/` for ADRs. See `docs/agents/domain.md`.

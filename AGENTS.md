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

No path is ever hardcoded: the main worktree is found via `git rev-parse --git-common-dir`.
`run.sh` links the same `config.local.yaml` on startup, so the bot still gets its per-machine
overrides in a fresh worktree even without running the script.

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
├── SeatManager       — Seat commands facade → SeatSubsystem (see seat sub-tree below)
├── MusicManager      — Playback control
├── PlaybackMuting    — Mic mute/restore around song switching; arms on XXX 已上麦
├── MessageManager    — Async message queue and dispatch
├── RecoveryManager   — Tracks Appium/UI failures; triggers driver reinit or app restart
├── RoomProfileManager — 房间档案唯一所有者（抽屉会话 + 话题/公告/房名草稿）
└── [KeywordManager, InfoManager, UserManager, AdminManager, MemoryManager,
    MicManager, SleepManager, PlaylistAdoption, PendingWrite]
```

#### 座位观测 vs 面板驱动（铁律，`src/ushareiplay/managers/seat_manager/`）

```
SeatManager (facade) → SeatSubsystem (sole implementation)
├── SeatObservationManager — 被动观测：视口快照、12 座位状态、专注人数对账
└── SeatPanelDriver        — 主动驱动：展开/收起/滚动/头像弹窗（命令路径）
```

- **被动观测 `SeatObservationManager`**（`seat_observation.py`，Singleton）：周期性观测**当前视口**里可见的桌位，维护 12 座位状态、3 排快照日志与专注人数对账；命令路径借它做**读数校验**（`sync_current_viewport`），但不继承它的跳过策略与冷却。
- **主动驱动 `SeatPanelDriver`**（`seat_panel_driver.py`，普通可注入对象、非单例）：执行面板动作与用户显式命令 —— `expand` / `collapse` / `expand_and_find_desks` / `scroll_to_row` / `reveal_seat`；并持有 UI 独占与头像弹窗生命周期：`ui_session` / `avatar_card` / `read_occupant` / `card_still_present`。
- **视口裁剪约束只属于被动观测路径**：`SeatObservationManager._is_desk_interactable` 拒绝三类桌位 —— 读不出渲染尺寸（既无 `bounds` 属性，也无 `location`/`size`）、渲染高度 < `MIN_INTERACTABLE_DESK_HEIGHT`(100)、或 h/w < 0.4；残片头像已被视口裁切，按座位几何算出的四分之一/四分之三落点点击只会命中空白 → **绝不盲目点击**，观测的**逐桌读数**里**跳过**这类桌位；主动驱动用另一种方式满足同一条物理约束 —— **先把面板滚到目标座位所在的那一排**（`scroll_to_row`，排级滚动；顶/底排会被内容边缘夹住，不保证整桌完全渲染），再用 `sync_current_viewport` 的读数校验空位，并以座位元素自身的 `bounds` 为落点（读不到时才退回桌位的四分之一/四分之三落点）。`reveal_seat` 支持按座位展开并滚动，但目前只有测试在调用，生产命令未接入。
- **严禁**把观测者的「跳过裁剪桌位」守卫抄进驱动例程（会让 `:seat N` 对视口外的座位静默失效），**严禁**把观测者的后台重扫冷却（`RESCAN_COOLDOWN` 等）搬进命令路径 —— 显式用户命令必须立即执行。
- 头像弹窗的**按返回的铁律**在驱动侧实现：`avatar_card` / `read_occupant` 只在 `card_still_present` 证据成立时按 back —— 房间里一次盲按 back 就是退出派对房间。

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

- **座位与麦位术语铁律（Party Seat vs Mic）**：派对房间内的 1~12 号位置是**座位（Seat / 在座）**，与「上麦」没有任何关系；Soul 在线用户列表不包含在座用户。只有开麦说话的才叫**麦位（Mic）/ 上麦（On-Mic）**（例如公屏「XXX 已上麦」通知、切歌防啸叫的 `PlaybackMuting`）。日志、报错提示、提示文案与代码注释严禁把 1~12 号座位叫作「麦位」，严禁把在座用户说成「在麦上/上麦」（如「在 11 号麦上」是错误术语，必须表述为「在 11 号座位上」）。
- **用户名参数铁律**：同一个人在 Soul UI 上是**可见昵称（分身名）**、在 DB 里是 **canonical 名（主账号名）**，两者字符串不同。任何以用户名作参数的命令（`:seat 3`、`:admin`、`:gift`、`:level`、事件钩子等），DB 侧用 canonical，**面向 UI 的查找必须先 `InfoManager.resolve_visible_username(...)`**；跨命名域比对只能用 `UserDAO.is_same_identity(...)`，严禁拿 canonical 名与 UI 文本做 `==`。详见 `docs/users.md` 的「两个命名域」。
- **元素选择器单一事实源铁律（Single Source of Truth for Elements）**：`config.yaml` 是 UI 元素选择器（`elements`）的唯一权威定义，集中维护多版本兼容与联合 XPath（如 `user_count` 兼容 `tvUserCount` 与 `tvOnlineCount`）。`config.local.yaml` 仅用于机器级硬件与秘钥差异（`device.name`、`appium.host`、LLM Key 等），严禁在 `config.local.yaml` 中覆盖 `soul.elements` 或 `qq_music.elements`。私自覆盖会导致 UI 定位器降级为过时或单一 resource-id，引发事件无法触发、在线列表无法刷新（`/info` 显示「列表暂未更新」）、进退房事件失灵及座位判定异常等隐蔽故障。
- **UI 驱动开发与防过度设计铁律（UI Driver Anti-Overengineering Iron Rules）**：开发 UI 驱动（Driver / Adaptor）时，必须保持逻辑精简，严禁过度设计引入虚假的「健壮性」代码：
  1. **严禁防御性判空（No Defensive Null-Checking for Injected Dependencies）**：对 `handler`、`element_finder` 等注入依赖直接访问，严禁写冗余的 `if handler is None` 或 `getattr(handler, 'element_finder', None)`。依赖缺失应直接抛出异常（Fail-Fast）暴露问题，严禁掩盖错误；显式引用便于 IDE 精准维护对象关系与静态代码跳转。
  2. **窗口状态用标准等待判定，禁止遍历 Marker 列表推测（State Assertion via Standard Waits）**：检测弹窗/面板是否存在或关闭，直接调用 SDK / Finder 标准等待方法（如 `wait_for_element`、`wait_for_element_disappear`）等待唯一权威标志（如专属标题），或直接等待预期目标出现。严禁遍历多个 marker key 列表做多重循环轮询，低效且掩盖状态异常。
  3. **元素交互默认使用原生点击（Default to element.click()）**：查找并点击元素一律优先使用 `finder.wait_for_element_clickable(key)` 配合 `element.click()`。严禁无特殊要求私自引入 `click_element_at` 坐标手势或兜底阶梯（UiAutomator2 的 `clickGesture` 坐标点击极易仅消费手势而不触发 Android 原生 View 点击监听，导致二级弹窗或跳转失效）；仅在明确特殊说明（如座位面板 1/4 / 3/4 盲点几何落点）时方可使用坐标点击。同时直接调用 finder 标准接口，严禁到处滥用 `hasattr` 检查。
  4. **滑动与翻页通用能力必须下沉底层模块（Gesture Primitives in GestureHandler）**：滚动查找元素、屏幕翻页等属于通用底层能力，必须统一下沉到 `GestureHandler`，严禁在业务 Driver 中重复编写屏幕宽高计算、滑动坐标百分比与循环滑动重试。必须清晰区分两类手势场景：
     - **容器局部滑动（`scroll_container_until_element`）**：明确已知滚动容器（如歌单横滑卡片、特定列表视图）；
     - **全屏中心滑动（`swipe_until_element`）**：无需指定容器（如设置面板、全局长页面），由底层基于屏幕中心区域执行滑动并检测目标元素出现。
  5. **禁止无意义的浅层包装（No Superfluous Wrapper Methods）**：严禁在 Driver 内封装毫无价值的私有包装方法（如 `_click_key`、`_click_element` 等），直接在业务步骤中调用 finder 标准等待并点击，保持代码扁平、精简与可读性。

## Logging Policy (铁律)

**全局铁律**：严禁在循环监控、轮询、周期性检测（如座位观测、UI 锁获取/释放、心跳巡检等）中输出无行为触发的监控日志。
- **只有触发了具体行为才输出日志**：例如检测到座位/用户变更、解析并执行命令、进入/离开房间、发起弹窗交互或出现异常/错误时，才允许输出日志。
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

## GitHub Account Switching

### Account Switching
When creating or editing pull requests with `gh`, the correct GitHub account depends on the repository remote URL.
- **Rule**: Read `remote.origin.url` and extract the username before `@github.com` (e.g. `https://forchain@github.com/forchain/UShareIPlay` → `forchain`). Temporarily switch `gh` to that account for PR operations, then switch back.

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

### Branch Naming (铁律)

分支一律用 `<type>/<slug>` 格式：类型前缀与 slug 之间**必须用斜杠分隔**。严禁使用
`forchain/fix-<slug>` 这类「属主前缀 + 连字符」的形式。

```bash
# ✅ 正确
fix/seat-panel-collapse-race
feat/invite-empty-seat
chore/ci-pytest-gate

# ❌ 错误
forchain/fix-seat-panel-collapse-race
forchain/feat-invite-empty-seat
```

- 类型前缀：`fix/`、`feat/`、`chore/`、`refactor/`、`docs/`、`test/`
- slug 用短横线小写，**不重复类型前缀**（`fix/seat-panel-collapse-race`，而不是
  `fix/fix-seat-panel-collapse-race`）
- 仓库里已存在的 `forchain/*` 历史分支不用回改，新建分支一律按本规则命名

## Agent Skills

### Issue tracker
GitHub Issues on `forchain/UShareIPlay`; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels
Five canonical roles use default label names (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs
Single-context layout: `GLOSSARY.md` at repo root and `docs/adr/` for ADRs. See `docs/agents/domain.md`.

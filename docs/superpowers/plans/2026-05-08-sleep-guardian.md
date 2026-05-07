# Sleep Guardian（睡眠守护模式）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在配置的夜间时段内，当睡眠守护开启时，禁止用户触发“开始播放/点歌类”命令；允许 `:skip` / `:pause` 等控制类命令；系统用户（含 `Timer`）始终放行；支持 `:sleep on/off/status` 临时切换。

**Architecture:** 在 `CommandManager.process_command()` 统一拦截被禁用的点歌类命令；新增 `SleepGuardianManager` 负责读取配置、时间窗判断、临时开关覆盖与提示文案；新增 `:sleep` 命令管理临时覆盖。

**Tech Stack:** Python 3.x、pytest、现有 `Singleton` 单例模式、`ConfigLoader`（`config.yaml` + `config.local.yaml` 深度合并）。

---

## File Structure (Create/Modify Map)

**Create**
- `src/ushareiplay/managers/sleep_guardian_manager.py`：守护规则/时间窗/临时覆盖的唯一入口
- `src/ushareiplay/commands/sleep.py`：`:sleep on/off/status` 命令实现
- `tests/test_sleep_guardian_manager.py`：时间窗与开关优先级的单测
- `tests/test_command_manager_sleep_guardian_block.py`：验证拦截发生在 `CommandManager.process_command()` 且对 system_users 放行

**Modify**
- `src/ushareiplay/managers/command_manager.py`：在 dispatch 前增加拦截
- `config.yaml`：新增 `sleep_guardian:` 配置段；新增 `commands:` 中的 `sleep` 命令项
- `README.md`（可选）：在 Command Reference / Music 部分补充 `:sleep`

---

### Task 1: Add `SleepGuardianManager` (core policy + time window)

**Files:**
- Create: `src/ushareiplay/managers/sleep_guardian_manager.py`
- Test: `tests/test_sleep_guardian_manager.py`

- [ ] **Step 1: Write failing tests for time-window logic**

```python
from datetime import datetime

import pytest

from ushareiplay.managers.sleep_guardian_manager import SleepGuardianManager


def _dt(hhmm: str) -> datetime:
    # Fixed date; only time matters.
    return datetime.fromisoformat(f"2026-05-08 {hhmm}:00")


def test_is_in_window_non_cross_day():
    cfg = {"sleep_guardian": {"enabled": True, "start": "09:00", "end": "18:00"}}
    g = SleepGuardianManager.instance(cfg)
    assert g.is_in_guard_window(_dt("09:00")) is True
    assert g.is_in_guard_window(_dt("12:00")) is True
    assert g.is_in_guard_window(_dt("18:00")) is False  # end is exclusive


def test_is_in_window_cross_day():
    cfg = {"sleep_guardian": {"enabled": True, "start": "23:00", "end": "06:00"}}
    g = SleepGuardianManager.instance(cfg)
    assert g.is_in_guard_window(_dt("22:59")) is False
    assert g.is_in_guard_window(_dt("23:00")) is True
    assert g.is_in_guard_window(_dt("00:00")) is True
    assert g.is_in_guard_window(_dt("05:59")) is True
    assert g.is_in_guard_window(_dt("06:00")) is False


def test_is_in_window_all_day_when_start_equals_end():
    cfg = {"sleep_guardian": {"enabled": True, "start": "00:00", "end": "00:00"}}
    g = SleepGuardianManager.instance(cfg)
    assert g.is_in_guard_window(_dt("00:00")) is True
    assert g.is_in_guard_window(_dt("12:00")) is True
    assert g.is_in_guard_window(_dt("23:59")) is True
```

- [ ] **Step 2: Run tests to verify FAIL**

Run:
- `uv run pytest -q tests/test_sleep_guardian_manager.py -q`

Expected:
- FAIL with `ModuleNotFoundError: No module named ...sleep_guardian_manager`

- [ ] **Step 3: Implement minimal manager to pass tests**

```python
# src/ushareiplay/managers/sleep_guardian_manager.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Iterable, Optional

from ushareiplay.core.singleton import Singleton


def _parse_hhmm(value: str) -> Optional[time]:
    if not value or not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hh = int(parts[0])
        mm = int(parts[1])
    except Exception:
        return None
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return time(hour=hh, minute=mm)


@dataclass(frozen=True)
class SleepGuardianConfig:
    enabled: bool
    start: time
    end: time
    blocked_commands: tuple[str, ...]


class SleepGuardianManager(Singleton):
    def __init__(self, config: dict | None = None):
        self._config_dict = config or {}
        self._override_enabled: Optional[bool] = None  # None = no override, else on/off

        sg = (self._config_dict.get("sleep_guardian") or {}) if isinstance(self._config_dict, dict) else {}
        enabled = bool(sg.get("enabled", True))
        start = _parse_hhmm(str(sg.get("start", "23:00")))
        end = _parse_hhmm(str(sg.get("end", "06:00")))
        blocked = sg.get(
            "blocked_commands",
            ["play", "next", "fav", "singer", "album", "playlist", "radio"],
        )
        if not isinstance(blocked, list):
            blocked = ["play", "next", "fav", "singer", "album", "playlist", "radio"]

        # Fallback parsing: if invalid, use safe defaults (do not block due to misconfig)
        # Window parsing failures will be handled in is_in_guard_window.
        self._cfg = SleepGuardianConfig(
            enabled=enabled,
            start=start or time(0, 0),
            end=end or time(0, 0),
            blocked_commands=tuple(str(x) for x in blocked),
        )

        self._start_valid = start is not None
        self._end_valid = end is not None

    @classmethod
    def instance(cls, config: dict | None = None) -> "SleepGuardianManager":
        # singleton supports passing config on first call; later calls ignore
        return super().instance(config)

    def set_override(self, enabled: Optional[bool]) -> None:
        self._override_enabled = enabled

    def get_effective_enabled(self) -> bool:
        if self._override_enabled is None:
            return self._cfg.enabled
        return bool(self._override_enabled)

    def is_in_guard_window(self, now: datetime) -> bool:
        # If time parsing failed, be safe: do not block.
        if not self._start_valid or not self._end_valid:
            return False
        start = self._cfg.start
        end = self._cfg.end
        t = now.time().replace(second=0, microsecond=0)

        # start == end => all day
        if start == end:
            return True

        if start < end:
            return start <= t < end

        # Cross-day: [start, 24h) U [00:00, end)
        return t >= start or t < end

    def is_blocked_command(self, prefix: str) -> bool:
        return (prefix or "") in set(self._cfg.blocked_commands)
```

- [ ] **Step 4: Run tests to verify PASS**

Run:
- `uv run pytest -q tests/test_sleep_guardian_manager.py -q`

Expected:
- PASS

- [ ] **Step 5: Add tests for override priority (write failing, then pass)**

```python
def test_override_enabled_takes_precedence():
    cfg = {"sleep_guardian": {"enabled": True, "start": "23:00", "end": "06:00"}}
    g = SleepGuardianManager.instance(cfg)
    g.set_override(False)
    assert g.get_effective_enabled() is False
    g.set_override(True)
    assert g.get_effective_enabled() is True
    g.set_override(None)
    assert g.get_effective_enabled() is True
```

Run:
- `uv run pytest -q tests/test_sleep_guardian_manager.py -q`

Expected:
- PASS

- [ ] **Step 6 (Optional): Commit**

Only if you want a commit now:
- `git add src/ushareiplay/managers/sleep_guardian_manager.py tests/test_sleep_guardian_manager.py`
- `git commit -m "feat: add sleep guardian policy manager"`

---

### Task 2: Add `:sleep` command (on/off/status)

**Files:**
- Create: `src/ushareiplay/commands/sleep.py`
- Modify: `config.yaml` (commands entry)
- Test: `tests/test_command_manager_sleep_guardian_block.py` (status path can be unit-tested via manager; command itself verified via CommandManager integration-ish test)

- [ ] **Step 1: Create `SleepCommand` skeleton**

```python
# src/ushareiplay/commands/sleep.py
from ushareiplay.core.base_command import BaseCommand


class SleepCommand(BaseCommand):
    async def process(self, message_info, parameters):
        if not parameters:
            return {"error": "Missing parameter: on/off/status"}
        sub = str(parameters[0]).lower()

        from ushareiplay.managers.sleep_guardian_manager import SleepGuardianManager
        guardian = SleepGuardianManager.instance(self.soul_handler.config)

        if sub == "on":
            guardian.set_override(True)
            return {"message": "睡眠守护已开启（临时）"}
        if sub == "off":
            guardian.set_override(False)
            return {"message": "睡眠守护已关闭（临时）"}
        if sub == "status":
            # best-effort status text; kept simple for templates
            enabled = guardian.get_effective_enabled()
            return {"message": f"睡眠守护状态: {'ON' if enabled else 'OFF'}"}

        return {"error": "Invalid parameter: on/off/status"}
```

- [ ] **Step 2: Add `sleep` command entry to `config.yaml`**

Add under top-level `commands:` list:

```yaml
  - prefix: "sleep"
    level: 4
    response_template: "{message}"
    error_template: "{error}"
```

Notes:
- `level` can be raised later (e.g. 9) without code change.

- [ ] **Step 3: Run existing command loading tests**

Run:
- `uv run pytest -q tests/test_command_manager_class_loading.py -q`

Expected:
- PASS (ensures one BaseCommand subclass per module and loadability)

- [ ] **Step 4 (Optional): Update README command table**

Add a row:
- `:sleep` | (level per config) | `on/off/status` | Sleep guardian toggle

- [ ] **Step 5 (Optional): Commit**

Only if you want a commit now:
- `git add src/ushareiplay/commands/sleep.py config.yaml README.md`
- `git commit -m "feat: add :sleep command to toggle sleep guardian"`

---

### Task 3: Enforce sleep guardian in `CommandManager.process_command()`

**Files:**
- Modify: `src/ushareiplay/managers/command_manager.py`
- Create/Modify: `tests/test_command_manager_sleep_guardian_block.py`

- [ ] **Step 1: Write failing test that blocks `play` but allows system user `Timer`**

```python
import types
import pytest

from ushareiplay.managers.command_manager import CommandManager


class _DummyCommand:
    def __init__(self):
        self.called = False

    async def process(self, message_info, parameters):
        self.called = True
        return {"song": "x", "singer": "y", "album": "z"}


class _Msg:
    def __init__(self, nickname: str, content: str = ":play x"):
        self.nickname = nickname
        self.content = content


@pytest.mark.asyncio
async def test_sleep_guardian_blocks_play_for_normal_user(monkeypatch):
    cm = CommandManager.instance()
    # Minimal runtime stub for process_command
    cm.configure_runtime(
        types.SimpleNamespace(
            emit=lambda *a, **k: None,
            ui_session=lambda *a, **k: _NullAsyncContext(),
            controller=None,
        )
    )
    # minimal handler config including system_users + sleep_guardian
    cm._handler = types.SimpleNamespace(config={"system_users": ["Timer"], "sleep_guardian": {"enabled": True, "start": "00:00", "end": "00:00", "blocked_commands": ["play"]}})
    cm._logger = types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None, warning=lambda *a, **k: None)

    cmd = _DummyCommand()
    res = await cm.process_command(cmd, _Msg("Alice"), {"prefix": "play", "parameters": [], "error_template": "{error}", "response_template": "{song}"})
    assert "睡眠守护" in res
    assert cmd.called is False


@pytest.mark.asyncio
async def test_sleep_guardian_allows_timer_system_user(monkeypatch):
    cm = CommandManager.instance()
    cmd = _DummyCommand()
    res = await cm.process_command(cmd, _Msg("Timer"), {"prefix": "play", "parameters": [], "error_template": "{error}", "response_template": "{song}"})
    # should call through (template may differ, but command must run)
    assert cmd.called is True


class _NullAsyncContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False
```

Run:
- `uv run pytest -q tests/test_command_manager_sleep_guardian_block.py -q`

Expected:
- FAIL (no blocking yet / singleton reuse issues will require test isolation fixes in implementation)

- [ ] **Step 2: Implement guard check in `CommandManager.process_command()`**

Pseudo-code to insert near the top of `process_command` (after `cmd` is known and before `await command.process(...)`):

```python
prefix = command_info.get("prefix")
system_users = self.handler.config.get("system_users", [])
is_system_user = message_info.nickname in system_users

if not is_system_user:
    from ushareiplay.managers.sleep_guardian_manager import SleepGuardianManager
    guardian = SleepGuardianManager.instance(self.handler.config)
    if guardian.get_effective_enabled() and guardian.is_blocked_command(prefix) and guardian.is_in_guard_window(datetime.now()):
        return f"睡眠守护已开启（{start}-{end}），当前时段禁止点歌。如需临时关闭：:sleep off"
```

Implementation notes:
- Use `datetime.now()` (local time) to match operator expectations.
- Message should be returned as a **string response** (consistent with other early returns in `process_command`).

- [ ] **Step 3: Run guard tests; fix singleton test isolation**

Run:
- `uv run pytest -q tests/test_command_manager_sleep_guardian_block.py -q`

Expected:
- PASS

If singleton reuse across tests causes leakage:
- add a `SleepGuardianManager.reset_for_tests()` method OR construct `SleepGuardianManager` without singleton (less aligned with codebase).
- prefer adding a tiny test-only reset hook guarded by name (e.g. method exists but not used in prod).

- [ ] **Step 4: Add `sleep_guardian:` section to `config.yaml`**

Append near top-level (location doesn’t matter; keep near other feature configs):

```yaml
sleep_guardian:
  enabled: true
  start: "23:00"
  end: "06:00"
  blocked_commands:
    - play
    - next
    - fav
    - singer
    - album
    - playlist
    - radio
```

- [ ] **Step 5: Run focused regression tests**

Run:
- `uv run pytest -q tests/test_command_manager_class_loading.py tests/test_help_command_is_current.py -q`

Expected:
- PASS

- [ ] **Step 6 (Optional): Commit**

Only if you want a commit now:
- `git add src/ushareiplay/managers/command_manager.py config.yaml tests/test_command_manager_sleep_guardian_block.py`
- `git commit -m "feat: enforce sleep guardian during command dispatch"`

---

## Plan Self-Review (against spec)

- Spec requirement “默认开启 + 时间可配 + 跨天窗口”：Task 1 tests + config section cover
- “除非主动关闭否则一直生效”：配置默认启用；临时覆盖只在进程内，重启回默认
- “命令临时关闭”：Task 2 `:sleep off/on/status`
- “B：所有开始播放命令禁用；切歌允许；pause 允许”：blocked list + explicit allow list
- “定时器允许触发”：system_users（含 Timer）在 Task 3 放行
- “radio 子命令一起禁用”：blocked prefix=radio covers all `:radio <keyword>`

No placeholders; every task includes runnable code/commands.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-08-sleep-guardian.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?


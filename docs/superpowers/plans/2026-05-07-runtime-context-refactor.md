# Runtime Context Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current `AppController.instance()` runtime back-references in command, event, and driver recovery paths with narrow runtime contexts.

**Architecture:** Add small context objects under `ushareiplay.core.runtime_context` that expose only the capabilities downstream modules need: command UI sessions, observability, event UI-busy checks, and driver recovery. `AppController` remains the lifecycle orchestrator, but managers and decorators stop importing it at runtime for shared services.

**Tech Stack:** Python 3.13, asyncio, Appium Python Client, Selenium exceptions, pytest, pytest-asyncio, uv.

---

## Scope

This plan implements方案 A for the known circular-dependency pressure points. It removes direct `AppController.instance()` calls from:

- `src/ushareiplay/managers/command_manager.py`
- `src/ushareiplay/managers/event_manager.py`
- `src/ushareiplay/core/driver_decorator.py`
- `src/ushareiplay/events/chat_room_title.py`

This plan does not migrate every command class away from `BaseCommand(controller)`. Command modules currently store themselves on the controller and several commands read `controller.config`, `controller.soul_handler`, or `controller.music_handler`. That broader command API migration should be a follow-up once the runtime back-reference cycle is gone.

## File Structure

- Create `src/ushareiplay/core/runtime_context.py`: defines `CommandRuntimeContext`, `EventRuntimeContext`, and `DriverRecoveryContext`.
- Modify `src/ushareiplay/core/app_controller.py`: creates the runtime context objects and injects them into `CommandManager` and `EventManager`.
- Modify `src/ushareiplay/managers/command_manager.py`: stores an injected command runtime context and uses it for `obs`, `ui_session`, and command factory controller access.
- Modify `src/ushareiplay/managers/event_manager.py`: stores an injected event runtime context and uses it to check whether UI is busy.
- Modify `src/ushareiplay/core/driver_decorator.py`: resolves driver recovery through an owner-provided context instead of importing `AppController`.
- Modify `src/ushareiplay/core/app_handler.py`: exposes `driver_recovery_context` so UI helper decorators can recover driver sessions through their owner chain.
- Modify `src/ushareiplay/managers/music_manager.py`: exposes `driver_recovery_context` so its decorated methods keep the same behavior.
- Modify `src/ushareiplay/core/base_event.py`: accepts an optional event runtime context and provides `is_ui_busy()`.
- Modify `src/ushareiplay/events/chat_room_title.py`: uses `self.is_ui_busy()` instead of importing `AppController`.
- Modify `tests/test_imports.py`: adds `ushareiplay.core.runtime_context` import coverage.
- Create `tests/test_runtime_context.py`: unit-tests context behavior without Appium.
- Create `tests/test_command_manager_runtime_context.py`: unit-tests command loading and processing without importing `AppController`.
- Create `tests/test_event_manager_runtime_context.py`: unit-tests unknown-page behavior and event context injection.
- Create `tests/test_driver_decorator_runtime_context.py`: unit-tests driver recovery context lookup.
- Create `tests/test_chat_room_title_runtime_context.py`: unit-tests that the event respects UI-busy state through `BaseEvent`.

## Task 1: Add Runtime Context Objects

**Files:**
- Create: `src/ushareiplay/core/runtime_context.py`
- Modify: `tests/test_imports.py`
- Create: `tests/test_runtime_context.py`

- [ ] **Step 1: Add import coverage for the new module**

Add this entry to `MODULES` in `tests/test_imports.py` immediately after `"ushareiplay.core.runtime_services"`:

```python
    "ushareiplay.core.runtime_context",
```

- [ ] **Step 2: Write tests for runtime context behavior**

Create `tests/test_runtime_context.py`:

```python
import asyncio
from contextlib import asynccontextmanager

from ushareiplay.core.runtime_context import (
    CommandRuntimeContext,
    DriverRecoveryContext,
    EventRuntimeContext,
)


class FakeObserver:
    def __init__(self):
        self.events = []

    def emit(self, name, **kwargs):
        self.events.append((name, kwargs))


class FakeController:
    def __init__(self):
        self.obs = FakeObserver()
        self.reinitialized = 0
        self.session_reasons = []
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def ui_session(self, reason):
        self.session_reasons.append(reason)
        async with self.lock:
            yield

    def reinitialize_driver(self):
        self.reinitialized += 1
        return True


def test_command_runtime_context_delegates_observer_and_controller():
    controller = FakeController()
    runtime = CommandRuntimeContext(controller=controller)

    runtime.emit("command.received", ctx={"prefix": ":play"})

    assert runtime.controller is controller
    assert controller.obs.events == [
        ("command.received", {"ctx": {"prefix": ":play"}})
    ]


def test_event_runtime_context_reports_ui_busy_from_lock():
    lock = asyncio.Lock()
    runtime = EventRuntimeContext(ui_lock=lock)

    assert runtime.is_ui_busy() is False

    async def lock_once():
        await lock.acquire()
        try:
            assert runtime.is_ui_busy() is True
        finally:
            lock.release()

    asyncio.run(lock_once())


def test_driver_recovery_context_delegates_reinitialize_and_observer():
    controller = FakeController()
    runtime = DriverRecoveryContext(
        reinitialize_driver=controller.reinitialize_driver,
        obs=controller.obs,
    )

    assert runtime.reinitialize_driver() is True
    runtime.emit("recovery.reinitialized", ctx={"method": "page_source"})

    assert controller.reinitialized == 1
    assert controller.obs.events == [
        ("recovery.reinitialized", {"ctx": {"method": "page_source"}})
    ]
```

- [ ] **Step 3: Run the new tests and verify they fail**

Run:

```bash
uv run pytest -q tests/test_runtime_context.py tests/test_imports.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ushareiplay.core.runtime_context'`.

- [ ] **Step 4: Create the runtime context module**

Create `src/ushareiplay/core/runtime_context.py`:

```python
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class DriverRecoveryContext:
    reinitialize_driver: Callable[[], bool]
    obs: Any = None

    def emit(self, event: str, **kwargs) -> None:
        if self.obs is not None:
            self.obs.emit(event, **kwargs)


@dataclass(frozen=True)
class EventRuntimeContext:
    ui_lock: Any = None

    def is_ui_busy(self) -> bool:
        if self.ui_lock is None:
            return False
        return bool(self.ui_lock.locked())


@dataclass(frozen=True)
class CommandRuntimeContext:
    controller: Any

    @property
    def obs(self):
        return getattr(self.controller, "obs", None)

    @asynccontextmanager
    async def ui_session(self, reason: str):
        async with self.controller.ui_session(reason):
            yield

    def emit(self, event: str, **kwargs) -> None:
        if self.obs is not None:
            self.obs.emit(event, **kwargs)
```

- [ ] **Step 5: Run tests for the new context module**

Run:

```bash
uv run pytest -q tests/test_runtime_context.py tests/test_imports.py
```

Expected: PASS.

- [ ] **Step 6: Commit the context module**

```bash
git add src/ushareiplay/core/runtime_context.py tests/test_runtime_context.py tests/test_imports.py
git commit -m "refactor: add runtime context objects"
```

## Task 2: Inject Command Runtime Into CommandManager

**Files:**
- Modify: `src/ushareiplay/managers/command_manager.py`
- Modify: `src/ushareiplay/core/app_controller.py`
- Create: `tests/test_command_manager_runtime_context.py`

- [ ] **Step 1: Write tests proving CommandManager does not need AppController lookup**

Create `tests/test_command_manager_runtime_context.py`:

```python
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from ushareiplay.managers.command_manager import CommandManager


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def error(self, message):
        self.messages.append(("error", message))


class FakeObserver:
    def __init__(self):
        self.events = []

    def emit(self, name, **kwargs):
        self.events.append((name, kwargs))


class FakeRuntime:
    def __init__(self, controller):
        self.controller = controller
        self.obs = controller.obs
        self.session_reasons = []

    def emit(self, event, **kwargs):
        self.obs.emit(event, **kwargs)

    @asynccontextmanager
    async def ui_session(self, reason):
        self.session_reasons.append(reason)
        yield


class FakeCommand:
    async def process(self, message_info, parameters):
        return {"song": parameters[0]}


def make_manager(tmp_path):
    controller = SimpleNamespace(obs=FakeObserver())
    runtime = FakeRuntime(controller)
    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager.configure_runtime(runtime)
    manager._logger = FakeLogger()
    manager._handler = SimpleNamespace(config={"system_users": ["Console"]})
    manager.commands_path = tmp_path
    return manager, runtime, controller


def test_load_command_module_uses_injected_runtime_controller(tmp_path):
    command_file = tmp_path / "demo.py"
    command_file.write_text(
        "\n".join(
            [
                "command = None",
                "def create_command(controller):",
                "    controller.loaded_by_command_manager = True",
                "    return object()",
            ]
        ),
        encoding="utf-8",
    )
    manager, runtime, controller = make_manager(tmp_path)

    module = manager.load_command_module("demo")

    assert module is not None
    assert module.command is not None
    assert controller.loaded_by_command_manager is True


def test_process_command_uses_runtime_for_observability_and_ui_session():
    manager, runtime, controller = make_manager(Path("."))
    message_info = SimpleNamespace(content=":demo abc", nickname="Console")
    command_info = {
        "parameters": ["abc"],
        "prefix": ":demo",
        "response_template": "ok {song}",
        "error_template": "error {error}",
    }

    result = asyncio.run(
        manager.process_command(FakeCommand(), message_info, command_info)
    )

    assert result == "ok abc @Console"
    assert runtime.session_reasons == ["command::demo"]
    assert [event[0] for event in controller.obs.events] == [
        "command.received",
        "command.dispatch",
        "command.result",
    ]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest -q tests/test_command_manager_runtime_context.py
```

Expected: FAIL because `CommandManager` has no `configure_runtime` method.

- [ ] **Step 3: Add runtime storage to CommandManager**

In `src/ushareiplay/managers/command_manager.py`, add `self._runtime = None` in `__init__`, then add:

```python
    def configure_runtime(self, runtime):
        self._runtime = runtime

    @property
    def runtime(self):
        if self._runtime is None:
            raise RuntimeError("CommandManager runtime has not been configured")
        return self._runtime
```

- [ ] **Step 4: Replace AppController lookup in `load_command_module`**

Replace:

```python
            # 获取 AppController 单例实例
            from ushareiplay.core.app_controller import AppController
            controller = AppController.instance()

            module.command = module.create_command(controller)
```

with:

```python
            module.command = module.create_command(self.runtime.controller)
```

- [ ] **Step 5: Replace AppController lookup in `process_command`**

Replace the first observability block with:

```python
            try:
                self.runtime.emit(
                    "command.received",
                    ctx={
                        "prefix": command_info.get("prefix"),
                        "raw": message_info.content,
                        "nickname": message_info.nickname,
                    },
                )
            except Exception:
                pass
```

Replace the UI session block with:

```python
            result = {'error': 'unknown'}
            async with self.runtime.ui_session(f"command:{command_info.get('prefix', 'unknown')}"):
                try:
                    self.runtime.emit(
                        "command.dispatch",
                        ctx={
                            "prefix": command_info.get("prefix"),
                            "parameters": parameters,
                            "nickname": message_info.nickname,
                        },
                    )
                except Exception:
                    pass
                result = await command.process(message_info, parameters)
```

Replace the result observability block with:

```python
            try:
                self.runtime.emit(
                    "command.result",
                    ctx={
                        "prefix": command_info.get("prefix"),
                        "success": "error" not in result,
                        "error": result.get("error") if isinstance(result, dict) else None,
                        "response": res,
                        "response_len": len(res or ""),
                    },
                )
            except Exception:
                pass
```

- [ ] **Step 6: Configure CommandManager runtime from AppController**

In `src/ushareiplay/core/app_controller.py`, import:

```python
from ushareiplay.core.runtime_context import (
    CommandRuntimeContext,
    DriverRecoveryContext,
    EventRuntimeContext,
)
```

In `AppController.__init__`, after `self.ui_lock` exists, add:

```python
        self.driver_recovery_context = DriverRecoveryContext(
            reinitialize_driver=self.reinitialize_driver,
            obs=self.obs,
        )
        self.command_runtime_context = CommandRuntimeContext(controller=self)
        self.event_runtime_context = EventRuntimeContext(ui_lock=self.ui_lock)
```

In `_init_handlers`, after:

```python
            self.command_manager = CommandManager.instance()
```

add:

```python
            self.command_manager.configure_runtime(self.command_runtime_context)
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run pytest -q tests/test_command_manager_runtime_context.py tests/test_runtime_context.py
```

Expected: PASS.

- [ ] **Step 8: Confirm CommandManager no longer imports AppController**

Run:

```bash
rg -n "AppController|app_controller" src/ushareiplay/managers/command_manager.py
```

Expected: no output.

- [ ] **Step 9: Commit CommandManager runtime injection**

```bash
git add src/ushareiplay/managers/command_manager.py src/ushareiplay/core/app_controller.py tests/test_command_manager_runtime_context.py
git commit -m "refactor: inject command runtime context"
```

## Task 3: Inject Event Runtime Into EventManager And BaseEvent

**Files:**
- Modify: `src/ushareiplay/managers/event_manager.py`
- Modify: `src/ushareiplay/core/base_event.py`
- Modify: `src/ushareiplay/core/app_controller.py`
- Create: `tests/test_event_manager_runtime_context.py`

- [ ] **Step 1: Write tests for event runtime usage**

Create `tests/test_event_manager_runtime_context.py`:

```python
import asyncio
from types import SimpleNamespace

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.managers.event_manager import EventManager


class FakeLogger:
    def __init__(self):
        self.messages = []

    def debug(self, message):
        self.messages.append(("debug", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))


class FakeHandler:
    def __init__(self):
        self.logger = FakeLogger()
        self.controller = SimpleNamespace(party_manager="party")
        self.switched = 0
        self.back_pressed = 0

    def switch_to_app(self):
        self.switched += 1

    def press_back(self):
        self.back_pressed += 1


class FakeRuntime:
    def __init__(self, busy):
        self.busy = busy

    def is_ui_busy(self):
        return self.busy


def make_manager(runtime):
    manager = EventManager.__new__(EventManager)
    manager.__init__()
    manager._handler = FakeHandler()
    manager._logger = manager._handler.logger
    manager._config = {"elements": {}}
    manager.configure_runtime(runtime)
    manager._initialized = True
    return manager


def test_event_manager_skips_auto_back_when_runtime_reports_ui_busy():
    manager = make_manager(FakeRuntime(busy=True))

    triggered = asyncio.run(manager.process_events("<hierarchy />"))

    assert triggered == 0
    assert manager.handler.switched == 0
    assert manager.handler.back_pressed == 0


def test_event_manager_auto_backs_when_runtime_reports_ui_available(monkeypatch):
    manager = make_manager(FakeRuntime(busy=False))

    async def ready_source(*args, **kwargs):
        return "<hierarchy />"

    monkeypatch.setattr(manager, "_wait_page_source_ready_async", ready_source)

    triggered = asyncio.run(manager.process_events("<hierarchy />"))

    assert triggered == 0
    assert manager.handler.switched == 1
    assert manager.handler.back_pressed == 1


def test_base_event_accepts_runtime_and_exposes_ui_busy():
    handler = FakeHandler()
    event = BaseEvent(handler, runtime=FakeRuntime(busy=True))

    assert event.controller.party_manager == "party"
    assert event.is_ui_busy() is True
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest -q tests/test_event_manager_runtime_context.py
```

Expected: FAIL because `EventManager` has no `configure_runtime` and `BaseEvent.__init__` does not accept `runtime`.

- [ ] **Step 3: Add runtime support to EventManager**

In `src/ushareiplay/managers/event_manager.py`, add `self._runtime = None` in `__init__`, then add:

```python
    def configure_runtime(self, runtime):
        self._runtime = runtime

    @property
    def runtime(self):
        if self._runtime is None:
            raise RuntimeError("EventManager runtime has not been configured")
        return self._runtime
```

- [ ] **Step 4: Pass runtime into event instances**

In `load_event_module`, replace:

```python
            module.event = event_class(self.handler)
```

with:

```python
            module.event = event_class(self.handler, runtime=self.runtime)
```

- [ ] **Step 5: Replace AppController lookup in unknown-page handling**

In `process_events`, replace the `AppController.instance()` block with:

```python
                if self.runtime.is_ui_busy():
                    self.logger.debug(
                        "No events triggered, but UI is busy (ui_lock locked). Skip auto press_back.")
                else:
                    self.handler.switch_to_app()
                    ready_source = await self._wait_page_source_ready_async(max_wait_s=2.5, interval_s=0.2)
                    if not ready_source:
                        self.logger.debug(
                            "PageSource not ready after switch_to_app; skip auto press_back this round.")
                    else:
                        second_triggered = await self._process_events_once(ready_source)
                        if second_triggered == 0:
                            self.handler.press_back()
                            self.logger.warning("No events triggered, pressed back to exit unknown page")
                            self._consecutive_unknown_pages += 1
                            if self._consecutive_unknown_pages > 10:
                                backoff_s = min(10.0, 0.5 * (self._consecutive_unknown_pages - 10))
                                self.logger.warning(
                                    f"连续未知页面已达 {self._consecutive_unknown_pages} 次，"
                                    f"非阻塞退避 {backoff_s:.1f}s 后继续"
                                )
                                await asyncio.sleep(backoff_s)
                        else:
                            self._consecutive_unknown_pages = 0
```

- [ ] **Step 6: Add runtime support to BaseEvent**

In `src/ushareiplay/core/base_event.py`, change:

```python
    def __init__(self, handler):
```

to:

```python
    def __init__(self, handler, runtime=None):
```

and add:

```python
        self.runtime = runtime
```

Then add:

```python
    def is_ui_busy(self) -> bool:
        if self.runtime is None:
            return False
        return self.runtime.is_ui_busy()
```

- [ ] **Step 7: Configure EventManager runtime from AppController**

In `_init_handlers`, replace:

```python
            self.event_manager = EventManager.instance()
            self.event_manager.initialize()
```

with:

```python
            self.event_manager = EventManager.instance()
            self.event_manager.configure_runtime(self.event_runtime_context)
            self.event_manager.initialize()
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
uv run pytest -q tests/test_event_manager_runtime_context.py tests/test_runtime_context.py
```

Expected: PASS.

- [ ] **Step 9: Confirm EventManager no longer imports AppController**

Run:

```bash
rg -n "AppController|app_controller" src/ushareiplay/managers/event_manager.py
```

Expected: no output.

- [ ] **Step 10: Commit EventManager runtime injection**

```bash
git add src/ushareiplay/managers/event_manager.py src/ushareiplay/core/base_event.py src/ushareiplay/core/app_controller.py tests/test_event_manager_runtime_context.py
git commit -m "refactor: inject event runtime context"
```

## Task 4: Use BaseEvent Runtime In ChatRoomTitleEvent

**Files:**
- Modify: `src/ushareiplay/events/chat_room_title.py`
- Create: `tests/test_chat_room_title_runtime_context.py`

- [ ] **Step 1: Write test for UI-busy skip without AppController import**

Create `tests/test_chat_room_title_runtime_context.py`:

```python
import asyncio
from types import SimpleNamespace

from ushareiplay.events.chat_room_title import ChatRoomTitleEvent


class FakeLogger:
    def __init__(self):
        self.messages = []

    def debug(self, message):
        self.messages.append(message)


class FakeRuntime:
    def __init__(self, busy):
        self.busy = busy

    def is_ui_busy(self):
        return self.busy


def test_chat_room_title_event_skips_when_ui_busy(monkeypatch):
    handler = SimpleNamespace(logger=FakeLogger(), controller=SimpleNamespace())
    event = ChatRoomTitleEvent(handler, runtime=FakeRuntime(busy=True))
    event._last_check_ts = 0.0

    def fail_if_called():
        raise AssertionError("TitleManager should not be used while UI is busy")

    monkeypatch.setattr(
        "ushareiplay.managers.title_manager.TitleManager.instance",
        classmethod(lambda cls: fail_if_called()),
    )

    assert asyncio.run(event.handle("chat_room_title", None)) is False
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run pytest -q tests/test_chat_room_title_runtime_context.py
```

Expected: FAIL because `ChatRoomTitleEvent.__init__` does not accept `runtime`, or because it still checks `AppController.instance()`.

- [ ] **Step 3: Update ChatRoomTitleEvent constructor**

In `src/ushareiplay/events/chat_room_title.py`, replace:

```python
    def __init__(self, handler):
        super().__init__(handler)
```

with:

```python
    def __init__(self, handler, runtime=None):
        super().__init__(handler, runtime=runtime)
```

- [ ] **Step 4: Replace AppController lookup**

Replace:

```python
            from ushareiplay.core.app_controller import AppController

            controller = AppController.instance()
            if controller and controller.ui_lock and controller.ui_lock.locked():
                return False
```

with:

```python
            if self.is_ui_busy():
                return False
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest -q tests/test_chat_room_title_runtime_context.py tests/test_event_manager_runtime_context.py
```

Expected: PASS.

- [ ] **Step 6: Confirm ChatRoomTitleEvent no longer imports AppController**

Run:

```bash
rg -n "AppController|app_controller" src/ushareiplay/events/chat_room_title.py
```

Expected: no output.

- [ ] **Step 7: Commit ChatRoomTitleEvent runtime usage**

```bash
git add src/ushareiplay/events/chat_room_title.py tests/test_chat_room_title_runtime_context.py
git commit -m "refactor: use event runtime for chat title checks"
```

## Task 5: Route Driver Recovery Through Owner Context

**Files:**
- Modify: `src/ushareiplay/core/driver_decorator.py`
- Modify: `src/ushareiplay/core/app_handler.py`
- Modify: `src/ushareiplay/managers/music_manager.py`
- Create: `tests/test_driver_decorator_runtime_context.py`

- [ ] **Step 1: Write tests for decorator-owned recovery context**

Create `tests/test_driver_decorator_runtime_context.py`:

```python
from selenium.common.exceptions import WebDriverException

from ushareiplay.core.driver_decorator import with_driver_recovery


class FakeObserver:
    def __init__(self):
        self.events = []

    def emit(self, name, **kwargs):
        self.events.append((name, kwargs))


class FakeRecoveryContext:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0
        self.obs = FakeObserver()

    def reinitialize_driver(self):
        self.calls += 1
        return self.ok

    def emit(self, event, **kwargs):
        self.obs.emit(event, **kwargs)


class Owner:
    def __init__(self, context):
        self.driver_recovery_context = context
        self.calls = 0

    @with_driver_recovery(op="read")
    def flaky_read(self):
        self.calls += 1
        if self.calls == 1:
            raise WebDriverException("session gone")
        return "ok"


class NestedOwner:
    def __init__(self, context):
        self.owner = Owner(context)
        self.calls = 0

    @property
    def driver_recovery_context(self):
        return self.owner.driver_recovery_context

    @with_driver_recovery(retry=False, op="write")
    def flaky_write(self):
        self.calls += 1
        raise WebDriverException("session gone")


def test_driver_decorator_retries_read_after_context_recovery():
    context = FakeRecoveryContext(ok=True)
    owner = Owner(context)

    assert owner.flaky_read() == "ok"

    assert context.calls == 1
    assert [event[0] for event in context.obs.events] == [
        "recovery.reinitialized",
        "recovery.retry",
    ]


def test_driver_decorator_does_not_retry_write_when_retry_false():
    context = FakeRecoveryContext(ok=True)
    owner = NestedOwner(context)

    assert owner.flaky_write() is None

    assert owner.calls == 1
    assert context.calls == 1
    assert [event[0] for event in context.obs.events] == [
        "recovery.reinitialized",
        "recovery.no_retry",
    ]


def test_driver_decorator_returns_none_without_recovery_context():
    class NoContextOwner:
        @with_driver_recovery
        def read(self):
            raise WebDriverException("session gone")

    assert NoContextOwner().read() is None
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run pytest -q tests/test_driver_decorator_runtime_context.py
```

Expected: FAIL because `driver_decorator.py` still imports `AppController`.

- [ ] **Step 3: Add recovery context resolver to driver_decorator**

In `src/ushareiplay/core/driver_decorator.py`, add:

```python
def _get_driver_recovery_context(owner):
    context = getattr(owner, "driver_recovery_context", None)
    if context is not None:
        return context
    nested_owner = getattr(owner, "owner", None)
    if nested_owner is not None:
        return getattr(nested_owner, "driver_recovery_context", None)
    return None
```

- [ ] **Step 4: Replace AppController lookup in driver_decorator**

Replace:

```python
                # 延迟导入避免循环依赖
                from ushareiplay.core.app_controller import AppController

                controller = AppController.instance()
                if not controller:
                    return None
```

with:

```python
                context = _get_driver_recovery_context(self)
                if context is None:
                    return None
```

Replace `controller.reinitialize_driver()` with:

```python
context.reinitialize_driver()
```

Replace every `getattr(controller, "obs", None)` emit block with explicit calls to `context.emit`. The four event branches should look like this:

```python
                try:
                    if ok:
                        context.emit(
                            "recovery.reinitialized",
                            ctx={"method": f.__name__, "op": op, "retry": retry},
                        )
                except Exception:
                    pass

                if not ok:
                    try:
                        context.emit(
                            "recovery.failed",
                            level="ERROR",
                            ctx={"method": f.__name__, "op": op, "error": str(e)},
                        )
                    except Exception:
                        pass
                    return None

                if not retry:
                    try:
                        context.emit(
                            "recovery.no_retry",
                            ctx={"method": f.__name__, "op": op},
                        )
                    except Exception:
                        pass
                    return None

                try:
                    context.emit(
                        "recovery.retry",
                        ctx={"method": f.__name__, "op": op},
                    )
                except Exception:
                    pass
```

- [ ] **Step 5: Expose driver_recovery_context from AppHandler**

In `src/ushareiplay/core/app_handler.py`, add:

```python
    @property
    def driver_recovery_context(self):
        return getattr(self.controller, "driver_recovery_context", None)
```

Place it near other simple controller/config accessors.

- [ ] **Step 6: Expose driver_recovery_context from MusicManager**

In `src/ushareiplay/managers/music_manager.py`, add:

```python
    @property
    def driver_recovery_context(self):
        return getattr(self.music_handler, "driver_recovery_context", None)
```

This keeps the existing `@with_driver_recovery` methods in `MusicManager` working because the manager already owns `self.music_handler`.

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run pytest -q tests/test_driver_decorator_runtime_context.py tests/test_app_controller_driver_subscribers.py
```

Expected: PASS.

- [ ] **Step 8: Confirm driver_decorator no longer imports AppController**

Run:

```bash
rg -n "AppController|app_controller" src/ushareiplay/core/driver_decorator.py
```

Expected: no output.

- [ ] **Step 9: Commit driver recovery context routing**

```bash
git add src/ushareiplay/core/driver_decorator.py src/ushareiplay/core/app_handler.py src/ushareiplay/managers/music_manager.py tests/test_driver_decorator_runtime_context.py
git commit -m "refactor: route driver recovery through runtime context"
```

## Task 6: Verify Circular Back-References Are Removed

**Files:**
- Test only, no source changes expected.

- [ ] **Step 1: Run the exact AppController back-reference scan**

Run:

```bash
rg -n "from ushareiplay\\.core\\.app_controller import AppController|AppController\\.instance\\(" src/ushareiplay
```

Expected output should only include application entrypoint usage in `src/ushareiplay/__main__.py`.

If the scan still reports `command_manager.py`, `event_manager.py`, `driver_decorator.py`, or `chat_room_title.py`, remove those references before proceeding.

- [ ] **Step 2: Run focused architecture tests**

Run:

```bash
uv run pytest -q \
  tests/test_runtime_context.py \
  tests/test_command_manager_runtime_context.py \
  tests/test_event_manager_runtime_context.py \
  tests/test_chat_room_title_runtime_context.py \
  tests/test_driver_decorator_runtime_context.py
```

Expected: PASS.

- [ ] **Step 3: Run existing related tests**

Run:

```bash
uv run pytest -q \
  tests/test_imports.py \
  tests/test_paths.py \
  tests/test_app_controller_driver_subscribers.py \
  tests/test_runtime_queue_pipeline.py
```

Expected: PASS.

- [ ] **Step 4: Run the full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS. If tests fail because of missing Appium/device integration, do not run `main.py`; isolate the failing test and keep verification within pytest/unit coverage.

- [ ] **Step 5: Syntax-check modified source files**

Run:

```bash
python -m py_compile \
  src/ushareiplay/core/runtime_context.py \
  src/ushareiplay/core/app_controller.py \
  src/ushareiplay/core/base_event.py \
  src/ushareiplay/core/driver_decorator.py \
  src/ushareiplay/core/app_handler.py \
  src/ushareiplay/managers/command_manager.py \
  src/ushareiplay/managers/event_manager.py \
  src/ushareiplay/managers/music_manager.py \
  src/ushareiplay/events/chat_room_title.py
```

Expected: no output and exit code 0.

- [ ] **Step 6: Commit verification cleanup if needed**

If any source or test adjustments were needed during verification:

```bash
git add src tests
git commit -m "test: verify runtime context refactor"
```

If no adjustments were needed, do not create an empty commit.

## Self-Review

- Spec coverage: The plan covers方案 A by adding narrow runtime contexts for command processing, event UI-busy checks, and driver recovery. It intentionally leaves the broader command constructor API for a later plan because existing command modules still use full controller capabilities.
- Placeholder scan: No placeholder tasks remain. Each code-changing step includes the target file, concrete code, and the command needed to verify it.
- Type consistency: `CommandRuntimeContext`, `EventRuntimeContext`, and `DriverRecoveryContext` are introduced in Task 1 and used consistently by later tasks. Manager methods are named `configure_runtime` in both `CommandManager` and `EventManager`.
- Risk note: `Singleton.instance()` can retain previous manager instances across tests. Tests in this plan construct managers with `__new__()` and `__init__()` to avoid singleton state bleed.

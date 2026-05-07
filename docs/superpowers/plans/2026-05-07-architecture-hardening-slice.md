# Architecture Hardening Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the highest-risk architecture pressure from `architecture_review.md` with a small, testable slice: split `AppHandler` UI helper responsibilities, centralize driver refresh notifications, and move root-level tests into pytest.

**Architecture:** Keep `AppHandler` as the public compatibility facade for `SoulHandler` and `QQMusicHandler`, but move low-level UI operations into focused helper classes under `src/ushareiplay/core/ui/`. Add a lightweight driver subscriber registry to `AppController` so driver reinitialization updates every registered component through one path. Convert the four standalone root tests into normal pytest tests under `tests/` so the suite covers the cleanup without Appium.

**Tech Stack:** Python 3.13, Appium Python Client, Selenium WebDriverWait/action APIs, Tortoise ORM, pytest, pytest-asyncio, uv.

---

## Scope

This plan intentionally implements one independent architecture-hardening slice from the review. It does not introduce a ServiceRegistry, split `QQMusicHandler`, split `config.yaml`, or replace every `time.sleep()`/`print()`/broad `except Exception` in the project. Those are follow-up plans because each touches a different subsystem and should remain independently testable.

## File Structure

- Create `src/ushareiplay/core/ui/__init__.py`: exports the helper classes for import tests and future reuse.
- Create `src/ushareiplay/core/ui/element_finder.py`: owns locator resolution, wait/find helpers, child element helpers, safe text/attribute helpers, and any-element helpers.
- Create `src/ushareiplay/core/ui/key_actions.py`: owns Android key presses, clipboard, paste, app switching, and activity switching.
- Create `src/ushareiplay/core/ui/gesture_handler.py`: owns coordinate taps, W3C swipes, and `scroll_container_until_element`.
- Create `src/ushareiplay/core/ui/navigation.py`: owns `navigate_to_element`.
- Modify `src/ushareiplay/core/app_handler.py`: keep logger/driver/config/controller setup and expose existing public methods as thin delegates to helper instances.
- Modify `src/ushareiplay/core/app_controller.py`: add driver subscriber registration and replace hard-coded driver assignment in `reinitialize_driver()`.
- Modify `tests/test_imports.py`: include the new `ushareiplay.core.ui.*` modules.
- Create `tests/test_app_controller_driver_subscribers.py`: unit-test driver subscriber registration and notification without calling `AppController.__init__`.
- Create `tests/test_command_parser_no_config_mutation.py`: pytest version of root `test_command_parser_no_config_mutation.py`.
- Create `tests/test_keyword_acl.py`: pytest version of root `test_keyword_acl.py`.
- Create `tests/test_user_canonical_mapping.py`: pytest version of root `test_user_canonical_mapping.py`.
- Create `tests/test_avatar_exit.py`: pytest version of root `test_avatar_exit.py`.
- Delete root `test_command_parser_no_config_mutation.py`, `test_keyword_acl.py`, `test_user_canonical_mapping.py`, and `test_avatar_exit.py` after the moved tests pass.

## Task 1: Add Focused UI Helper Modules

**Files:**
- Create: `src/ushareiplay/core/ui/__init__.py`
- Create: `src/ushareiplay/core/ui/element_finder.py`
- Create: `src/ushareiplay/core/ui/key_actions.py`
- Create: `src/ushareiplay/core/ui/gesture_handler.py`
- Create: `src/ushareiplay/core/ui/navigation.py`
- Modify: `tests/test_imports.py`

- [ ] **Step 1: Write import coverage for new modules**

Add these entries to `MODULES` in `tests/test_imports.py` immediately after `"ushareiplay.core.driver_decorator"`:

```python
    "ushareiplay.core.ui",
    "ushareiplay.core.ui.element_finder",
    "ushareiplay.core.ui.gesture_handler",
    "ushareiplay.core.ui.key_actions",
    "ushareiplay.core.ui.navigation",
```

- [ ] **Step 2: Run import test to verify it fails**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_imports.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ushareiplay.core.ui'`.

- [ ] **Step 3: Create `src/ushareiplay/core/ui/__init__.py`**

```python
from ushareiplay.core.ui.element_finder import ElementFinder
from ushareiplay.core.ui.gesture_handler import GestureHandler
from ushareiplay.core.ui.key_actions import KeyActions
from ushareiplay.core.ui.navigation import Navigator

__all__ = [
    "ElementFinder",
    "GestureHandler",
    "KeyActions",
    "Navigator",
]
```

- [ ] **Step 4: Create `src/ushareiplay/core/ui/element_finder.py`**

Copy these methods from `AppHandler` into an `ElementFinder` class:

```python
from __future__ import annotations

from typing import Optional, Tuple

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ushareiplay.core.driver_decorator import with_driver_recovery


class ElementFinder:
    def __init__(self, owner):
        self.owner = owner

    @property
    def driver(self):
        return self.owner.driver

    @property
    def config(self):
        return self.owner.config

    @property
    def logger(self):
        return self.owner.logger
```

Then move the full current bodies of these methods from `AppHandler` into `ElementFinder`, replacing `self.log_debug(...)` with `self.owner.log_debug(...)` only where the original method used `log_debug`:

```python
    @with_driver_recovery(op="read")
    def wait_for_element(self, locator_type, locator_value, timeout=10):
        ...

    @with_driver_recovery(op="read")
    def wait_for_element_plus(self, element_key: str, timeout: int = 10) -> WebElement:
        ...

    def is_element_clickable(self, element):
        ...

    @with_driver_recovery(op="read")
    def wait_for_element_clickable_plus(self, element_key: str, timeout: int = 10) -> WebElement:
        ...

    @with_driver_recovery(op="read")
    def wait_for_element_clickable(self, locator_type, locator_value, timeout=10):
        ...

    @with_driver_recovery(op="read")
    def try_find_element_plus(self, element_key: str, log=False, clickable=False) -> WebElement:
        ...

    @with_driver_recovery(op="read")
    def try_find_element(self, locator_type, locator_value, log=True, clickable=False):
        ...

    @with_driver_recovery(op="read")
    def wait_for_element_polling(self, locator_type, locator_value, timeout=10, poll_frequency=0.5):
        ...

    @with_driver_recovery(op="read")
    def wait_for_element_clickable_polling(self, locator_type, locator_value, timeout=10, poll_frequency=0.5):
        ...

    def find_child_element(self, parent, locator_type, locator_value):
        ...

    def find_child_elements(self, parent, locator_type, locator_value):
        ...

    def get_element_text(self, element):
        ...

    def try_get_attribute(self, element, attribute):
        ...

    def _get_locator(self, element_key: str) -> tuple:
        ...

    @with_driver_recovery(op="read")
    def find_elements_plus(self, element_key: str) -> list:
        ...

    def find_child_element_plus(self, parent, element_key):
        ...

    def find_child_elements_plus(self, parent, element_key: str) -> list:
        ...

    @with_driver_recovery(op="read")
    def wait_for_any_element_plus(self, element_keys: list, timeout: int = 10) -> Tuple[Optional[str], Optional[WebElement]]:
        ...

    def try_find_any_element_plus(self, element_keys: list) -> Tuple[Optional[str], Optional[WebElement]]:
        ...
```

Keep the existing behavior exactly. Do not improve exception handling or sleeps in this task.

- [ ] **Step 5: Create `src/ushareiplay/core/ui/key_actions.py`**

```python
from __future__ import annotations

import time

from ushareiplay.core.driver_decorator import with_driver_recovery


class KeyActions:
    def __init__(self, owner):
        self.owner = owner

    @property
    def driver(self):
        return self.owner.driver

    @property
    def config(self):
        return self.owner.config

    @property
    def logger(self):
        return self.owner.logger
```

Then move the full current bodies of these methods from `AppHandler` into `KeyActions`:

```python
    @with_driver_recovery(retry=False, op="write")
    def switch_to_app(self):
        ...

    @with_driver_recovery(retry=False, op="write")
    def close_app(self):
        ...

    @with_driver_recovery(retry=False, op="write")
    def switch_to_activity(self, activity):
        ...

    @with_driver_recovery(retry=False, op="write")
    def press_enter(self, element):
        ...

    @with_driver_recovery(retry=False, op="write")
    def press_back(self):
        ...

    @with_driver_recovery(retry=False, op="write")
    def press_dpad_down(self):
        ...

    @with_driver_recovery(retry=False, op="write")
    def press_volume_up(self):
        ...

    @with_driver_recovery(retry=False, op="write")
    def press_volume_down(self):
        ...

    @with_driver_recovery(retry=False, op="write")
    def press_right_key(self, times=1):
        ...

    @with_driver_recovery(retry=False, op="write")
    def set_clipboard_text(self, text):
        ...

    @with_driver_recovery(retry=False, op="write")
    def paste_text(self):
        ...
```

When moving `press_back`, preserve `self.owner.error_count = 0` because `error_count` lives on `AppHandler`.

- [ ] **Step 6: Create `src/ushareiplay/core/ui/gesture_handler.py`**

```python
from __future__ import annotations

import traceback
from typing import Optional, Tuple

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.remote.webelement import WebElement

from ushareiplay.core.driver_decorator import with_driver_recovery


class GestureHandler:
    def __init__(self, owner):
        self.owner = owner

    @property
    def driver(self):
        return self.owner.driver

    @property
    def logger(self):
        return self.owner.logger
```

Then move the full current bodies of these methods from `AppHandler` into `GestureHandler`:

```python
    @with_driver_recovery(retry=False, op="write")
    def click_element_at(self, element, x_ratio=0.5, y_ratio=0.5, x_offset=0, y_offset=0):
        ...

    @with_driver_recovery(retry=False, op="write")
    def _perform_swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300) -> bool:
        ...

    @with_driver_recovery(op="read")
    def scroll_container_until_element(
        self,
        element_key: str,
        container_key: str,
        direction: str = "up",
        attribute_name: str = None,
        attribute_value: str = None,
        max_swipes: int = 10,
    ) -> Tuple[Optional[str], Optional[WebElement], list[str]]:
        ...
```

Inside `scroll_container_until_element`, replace helper calls with owner calls so the facade remains the dependency point:

```python
container = self.owner.wait_for_element_clickable_plus(container_key)
container = self.owner.wait_for_element_plus(container_key)
found = self.owner.find_child_element_plus(container, element_key)
elements = self.owner.find_child_elements_plus(container, element_key)
value = self.owner.try_get_attribute(element, attr)
ok = self._perform_swipe(sx, sy, ex, ey, duration_ms=100)
```

- [ ] **Step 7: Create `src/ushareiplay/core/ui/navigation.py`**

```python
from __future__ import annotations

from typing import Optional, Tuple

from selenium.webdriver.remote.webelement import WebElement


class Navigator:
    def __init__(self, owner):
        self.owner = owner

    @property
    def logger(self):
        return self.owner.logger

    def navigate_to_element(
        self,
        target_key: str,
        interference_keys: list = None,
        home_key: str = "home_nav",
        back_keys=None,
        max_attempts: int = 10,
    ) -> Tuple[Optional[str], Optional[WebElement]]:
        ...
```

Move the full current body of `AppHandler.navigate_to_element` into `Navigator.navigate_to_element`, replacing `self.press_back()`, `self.wait_for_any_element_plus(...)`, `self.try_find_any_element_plus(...)`, and `self.click_element_at(...)` with `self.owner.press_back()`, `self.owner.wait_for_any_element_plus(...)`, `self.owner.try_find_any_element_plus(...)`, and `self.owner.click_element_at(...)`.

- [ ] **Step 8: Run import test to verify helper modules import**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_imports.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/ushareiplay/core/ui tests/test_imports.py
git commit -m "refactor: add ui helper modules"
```

## Task 2: Turn `AppHandler` Into a Compatibility Facade

**Files:**
- Modify: `src/ushareiplay/core/app_handler.py`

- [ ] **Step 1: Add helper construction to `AppHandler.__init__`**

Add imports near the existing imports:

```python
from ushareiplay.core.ui import ElementFinder, GestureHandler, KeyActions, Navigator
```

After `self.controller = controller`, add:

```python
        self.element_finder = ElementFinder(self)
        self.key_actions = KeyActions(self)
        self.gestures = GestureHandler(self)
        self.navigator = Navigator(self)
```

- [ ] **Step 2: Replace moved methods with delegates**

For every method moved in Task 1, replace the old body in `AppHandler` with a one-line delegate. Use exactly these wrappers so existing `SoulHandler`, `QQMusicHandler`, managers, commands, and events keep calling the same public methods:

```python
    def wait_for_element(self, *args, **kwargs):
        return self.element_finder.wait_for_element(*args, **kwargs)

    def wait_for_element_plus(self, *args, **kwargs):
        return self.element_finder.wait_for_element_plus(*args, **kwargs)

    def is_element_clickable(self, *args, **kwargs):
        return self.element_finder.is_element_clickable(*args, **kwargs)

    def wait_for_element_clickable_plus(self, *args, **kwargs):
        return self.element_finder.wait_for_element_clickable_plus(*args, **kwargs)

    def wait_for_element_clickable(self, *args, **kwargs):
        return self.element_finder.wait_for_element_clickable(*args, **kwargs)

    def switch_to_app(self, *args, **kwargs):
        return self.key_actions.switch_to_app(*args, **kwargs)

    def close_app(self, *args, **kwargs):
        return self.key_actions.close_app(*args, **kwargs)

    def switch_to_activity(self, *args, **kwargs):
        return self.key_actions.switch_to_activity(*args, **kwargs)

    def press_enter(self, *args, **kwargs):
        return self.key_actions.press_enter(*args, **kwargs)

    def press_back(self, *args, **kwargs):
        return self.key_actions.press_back(*args, **kwargs)

    def press_dpad_down(self, *args, **kwargs):
        return self.key_actions.press_dpad_down(*args, **kwargs)

    def press_volume_up(self, *args, **kwargs):
        return self.key_actions.press_volume_up(*args, **kwargs)

    def press_volume_down(self, *args, **kwargs):
        return self.key_actions.press_volume_down(*args, **kwargs)

    def press_right_key(self, *args, **kwargs):
        return self.key_actions.press_right_key(*args, **kwargs)

    def try_find_element_plus(self, *args, **kwargs):
        return self.element_finder.try_find_element_plus(*args, **kwargs)

    def try_find_element(self, *args, **kwargs):
        return self.element_finder.try_find_element(*args, **kwargs)

    def wait_for_element_polling(self, *args, **kwargs):
        return self.element_finder.wait_for_element_polling(*args, **kwargs)

    def wait_for_element_clickable_polling(self, *args, **kwargs):
        return self.element_finder.wait_for_element_clickable_polling(*args, **kwargs)

    def set_clipboard_text(self, *args, **kwargs):
        return self.key_actions.set_clipboard_text(*args, **kwargs)

    def paste_text(self, *args, **kwargs):
        return self.key_actions.paste_text(*args, **kwargs)

    def find_child_element(self, *args, **kwargs):
        return self.element_finder.find_child_element(*args, **kwargs)

    def find_child_elements(self, *args, **kwargs):
        return self.element_finder.find_child_elements(*args, **kwargs)

    def get_element_text(self, *args, **kwargs):
        return self.element_finder.get_element_text(*args, **kwargs)

    def try_get_attribute(self, *args, **kwargs):
        return self.element_finder.try_get_attribute(*args, **kwargs)

    def _get_locator(self, *args, **kwargs):
        return self.element_finder._get_locator(*args, **kwargs)

    def find_elements_plus(self, *args, **kwargs):
        return self.element_finder.find_elements_plus(*args, **kwargs)

    def click_element_at(self, *args, **kwargs):
        return self.gestures.click_element_at(*args, **kwargs)

    def find_child_element_plus(self, *args, **kwargs):
        return self.element_finder.find_child_element_plus(*args, **kwargs)

    def find_child_elements_plus(self, *args, **kwargs):
        return self.element_finder.find_child_elements_plus(*args, **kwargs)

    def _perform_swipe(self, *args, **kwargs):
        return self.gestures._perform_swipe(*args, **kwargs)

    def scroll_container_until_element(self, *args, **kwargs):
        return self.gestures.scroll_container_until_element(*args, **kwargs)

    def wait_for_any_element_plus(self, *args, **kwargs):
        return self.element_finder.wait_for_any_element_plus(*args, **kwargs)

    def try_find_any_element_plus(self, *args, **kwargs):
        return self.element_finder.try_find_any_element_plus(*args, **kwargs)

    def navigate_to_element(self, *args, **kwargs):
        return self.navigator.navigate_to_element(*args, **kwargs)
```

- [ ] **Step 3: Remove unused imports from `app_handler.py`**

After the delegation rewrite, remove imports that are only needed by helper modules:

```python
import time
import traceback
from typing import Optional, Tuple

from appium.webdriver.common.appiumby import AppiumBy
from ushareiplay.core.driver_decorator import with_driver_recovery
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
```

Keep only imports still used by `AppHandler` itself:

```python
import logging
from datetime import datetime

from ushareiplay.core.log_formatter import ColoredFormatter
from ushareiplay.core.ui import ElementFinder, GestureHandler, KeyActions, Navigator
```

- [ ] **Step 4: Run syntax and import checks**

Run:

```bash
source .venv/bin/activate
python -m py_compile src/ushareiplay/core/app_handler.py src/ushareiplay/core/ui/element_finder.py src/ushareiplay/core/ui/key_actions.py src/ushareiplay/core/ui/gesture_handler.py src/ushareiplay/core/ui/navigation.py
uv run pytest -q tests/test_imports.py
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ushareiplay/core/app_handler.py src/ushareiplay/core/ui
git commit -m "refactor: delegate app handler ui operations"
```

## Task 3: Add Driver Subscriber Registry

**Files:**
- Modify: `src/ushareiplay/core/app_controller.py`
- Create: `tests/test_app_controller_driver_subscribers.py`

- [ ] **Step 1: Write tests for registration, duplicate prevention, and notification**

Create `tests/test_app_controller_driver_subscribers.py`:

```python
from types import SimpleNamespace

from ushareiplay.core.app_controller import AppController


class DriverAware:
    def __init__(self):
        self.driver = None


def controller_without_init():
    controller = AppController.__new__(AppController)
    controller._driver_subscribers = []
    controller.logger = None
    return controller


def test_register_driver_subscriber_adds_unique_objects():
    controller = controller_without_init()
    subscriber = DriverAware()

    controller.register_driver_subscriber(subscriber)
    controller.register_driver_subscriber(subscriber)

    assert controller._driver_subscribers == [subscriber]


def test_notify_driver_subscribers_sets_driver_on_each_registered_object():
    controller = controller_without_init()
    first = DriverAware()
    second = DriverAware()
    new_driver = SimpleNamespace(name="new-driver")

    controller.register_driver_subscriber(first)
    controller.register_driver_subscriber(second)
    controller._notify_driver_subscribers(new_driver)

    assert first.driver is new_driver
    assert second.driver is new_driver
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_app_controller_driver_subscribers.py
```

Expected: FAIL with `AttributeError: 'AppController' object has no attribute 'register_driver_subscriber'`.

- [ ] **Step 3: Initialize subscriber storage in `AppController.__init__`**

In `src/ushareiplay/core/app_controller.py`, after `self.driver = self._init_driver()`, add:

```python
        self._driver_subscribers = []
```

- [ ] **Step 4: Add subscriber methods to `AppController`**

Add these methods before `reinitialize_driver()`:

```python
    def register_driver_subscriber(self, component) -> None:
        """Register a component whose .driver reference must track controller.driver."""
        if component is None:
            return
        if component in self._driver_subscribers:
            return
        self._driver_subscribers.append(component)
        if hasattr(component, "driver"):
            component.driver = self.driver

    def _notify_driver_subscribers(self, driver) -> None:
        for component in list(self._driver_subscribers):
            if not hasattr(component, "driver"):
                continue
            component.driver = driver
            if self.logger:
                self.logger.debug(
                    "更新 %s.driver",
                    component.__class__.__name__,
                )
```

- [ ] **Step 5: Register driver-aware components in `_init_handlers()`**

After each driver-aware component is created in `_init_handlers()`, register it:

```python
            self.soul_handler = SoulHandler.instance(
                self.driver, self.config["soul"], self
            )
            self.register_driver_subscriber(self.soul_handler)
            self.music_handler = QQMusicHandler.instance(
                self.driver, self.config["qq_music"], self
            )
            self.register_driver_subscriber(self.music_handler)
```

After `self.music_manager = MusicManager.instance()`, add:

```python
            self.register_driver_subscriber(self.music_manager)
```

- [ ] **Step 6: Replace hard-coded driver updates in `reinitialize_driver()`**

Replace this block:

```python
            # 4. 更新所有组件的driver引用
            if self.soul_handler:
                self.soul_handler.driver = self.driver
                if self.logger:
                    self.logger.debug("更新 soul_handler.driver")

            if self.music_handler:
                self.music_handler.driver = self.driver
                if self.logger:
                    self.logger.debug("更新 music_handler.driver")

            # 5. 更新music_manager（关键修复！）
            if hasattr(self, "music_manager") and self.music_manager:
                self.music_manager.driver = self.driver
                if self.logger:
                    self.logger.debug("更新 music_manager.driver")

            # 6. 切换回应用
```

With:

```python
            # 4. 更新所有订阅组件的driver引用
            self._notify_driver_subscribers(self.driver)

            # 5. 切换回应用
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_app_controller_driver_subscribers.py tests/test_imports.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/ushareiplay/core/app_controller.py tests/test_app_controller_driver_subscribers.py
git commit -m "refactor: centralize driver subscriber updates"
```

## Task 4: Move Root Tests Into `tests/`

**Files:**
- Create: `tests/test_command_parser_no_config_mutation.py`
- Create: `tests/test_keyword_acl.py`
- Create: `tests/test_user_canonical_mapping.py`
- Create: `tests/test_avatar_exit.py`
- Delete: `test_command_parser_no_config_mutation.py`
- Delete: `test_keyword_acl.py`
- Delete: `test_user_canonical_mapping.py`
- Delete: `test_avatar_exit.py`

- [ ] **Step 1: Create pytest version of command parser mutation test**

Create `tests/test_command_parser_no_config_mutation.py`:

```python
from ushareiplay.core.command_parser import CommandParser


def test_command_parser_does_not_mutate_shared_config():
    commands = [
        {"prefix": "help", "response_template": "ok"},
        {"prefix": "play", "response_template": "ok"},
    ]
    parser = CommandParser(commands)

    help_result = parser.parse_command("help")
    assert help_result is not None
    assert help_result["prefix"] == "help"
    assert help_result.get("parameters") == []

    play_result = parser.parse_command("play foo")
    assert play_result is not None
    assert play_result["prefix"] == "play"
    assert play_result.get("parameters") == ["foo"]

    assert "parameters" not in commands[0]
    assert "parameters" not in commands[1]
```

- [ ] **Step 2: Create pytest version of keyword ACL test**

Create `tests/test_keyword_acl.py`:

```python
import pytest

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.keyword_dao import KeywordDAO
from ushareiplay.dal.user_dao import UserDAO


@pytest.mark.asyncio
async def test_private_keyword_acl_and_canonical_alias_access():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        user_a = await UserDAO.get_or_create("A")
        user_b = await UserDAO.get_or_create("B")
        user_c = await UserDAO.get_or_create("C")

        await KeywordDAO.create(
            keyword="k1",
            command=":help",
            creator_id=user_a.id,
            is_public=False,
        )

        assert await KeywordDAO.find_accessible_keyword("k1", "A") is not None
        assert await KeywordDAO.find_accessible_keyword("k1", "B") is None

        await KeywordDAO.grant_users("k1", [user_b.id, user_c.id])
        assert await KeywordDAO.find_accessible_keyword("k1", "B") is not None
        assert await KeywordDAO.find_accessible_keyword("k1", "C") is not None

        await KeywordDAO.revoke_users("k1", [user_b.id])
        assert await KeywordDAO.find_accessible_keyword("k1", "B") is None
        assert await KeywordDAO.find_accessible_keyword("k1", "C") is not None

        alias_user = await UserDAO.get_or_create_raw("A2")
        alias_user.canonical_user_id = user_a.id
        await alias_user.save(update_fields=["canonical_user_id"])
        assert await KeywordDAO.find_accessible_keyword("k1", "A2") is not None
    finally:
        await db.close()
```

- [ ] **Step 3: Create pytest version of canonical user mapping test**

Create `tests/test_user_canonical_mapping.py`:

```python
import pytest

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.user_dao import UserDAO


@pytest.mark.asyncio
async def test_alias_username_resolves_to_canonical_user():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        canonical = await UserDAO.get_or_create("小明")
        canonical.level = 3
        await canonical.save(update_fields=["level"])

        alias_raw = await UserDAO.get_or_create_raw("明明")
        alias_raw.canonical_user_id = canonical.id
        await alias_raw.save(update_fields=["canonical_user_id"])

        resolved = await UserDAO.get_or_create("明明")
        assert resolved.id == canonical.id
        assert resolved.username == "小明"
        assert resolved.level == 3

        resolved2 = await UserDAO.get_or_create("小明")
        assert resolved2.id == canonical.id
    finally:
        await db.close()
```

- [ ] **Step 4: Create pytest version of avatar exit tests**

Create `tests/test_avatar_exit.py`:

```python
import pytest
from tortoise import Tortoise

from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.models.user import User


@pytest.fixture
async def user_db():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["ushareiplay.models.user"]},
    )
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_all_avatar_usernames(user_db):
    canonical = await User.create(username="小明", level=0)
    await User.create(username="明明", level=0, canonical_user_id=canonical.id)
    await User.create(username="小M", level=0, canonical_user_id=canonical.id)

    result = await UserDAO.get_all_avatar_usernames("小明")

    assert result == {"小明", "明明", "小M"}


@pytest.mark.asyncio
async def test_no_leave_if_alias_still_online(user_db):
    canonical = await User.create(username="小明", level=0)
    await User.create(username="明明", level=0, canonical_user_id=canonical.id)

    online_users = {"小明", "张三"}
    all_avatars = await UserDAO.get_all_avatar_usernames("明明")
    still_online = all_avatars & online_users

    assert len(still_online) != 0


@pytest.mark.asyncio
async def test_leave_when_all_avatars_offline(user_db):
    canonical = await User.create(username="小明", level=0)
    await User.create(username="明明", level=0, canonical_user_id=canonical.id)

    online_users = {"张三", "李四"}
    all_avatars = await UserDAO.get_all_avatar_usernames("明明")
    still_online = all_avatars & online_users

    assert len(still_online) == 0


@pytest.mark.asyncio
async def test_no_aliases_user_triggers_immediately(user_db):
    await User.create(username="张三", level=0)

    online_users = {"李四"}
    all_avatars = await UserDAO.get_all_avatar_usernames("张三")
    still_online = all_avatars & online_users

    assert len(still_online) == 0


@pytest.mark.asyncio
async def test_alias_queried_resolves_to_canonical_group(user_db):
    canonical = await User.create(username="小明", level=0)
    await User.create(username="明明", level=0, canonical_user_id=canonical.id)
    await User.create(username="小M", level=0, canonical_user_id=canonical.id)

    result = await UserDAO.get_all_avatar_usernames("明明")

    assert "小明" in result
    assert "明明" in result
    assert "小M" in result
    assert len(result) == 3
```

- [ ] **Step 5: Run moved tests while root files still exist**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_command_parser_no_config_mutation.py tests/test_keyword_acl.py tests/test_user_canonical_mapping.py tests/test_avatar_exit.py
```

Expected: PASS.

- [ ] **Step 6: Delete root standalone tests**

Delete these files:

```bash
rm test_command_parser_no_config_mutation.py test_keyword_acl.py test_user_canonical_mapping.py test_avatar_exit.py
```

- [ ] **Step 7: Verify there are no root test files left**

Run:

```bash
find . -maxdepth 1 -name 'test_*.py' -print
```

Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add tests/test_command_parser_no_config_mutation.py tests/test_keyword_acl.py tests/test_user_canonical_mapping.py tests/test_avatar_exit.py
git rm test_command_parser_no_config_mutation.py test_keyword_acl.py test_user_canonical_mapping.py test_avatar_exit.py
git commit -m "test: move standalone tests into pytest suite"
```

## Task 5: Final Verification and Review Notes

**Files:**
- Modify only if earlier verification exposes issues.

- [ ] **Step 1: Run syntax checks for touched source**

Run:

```bash
source .venv/bin/activate
python -m py_compile src/ushareiplay/core/app_handler.py src/ushareiplay/core/app_controller.py src/ushareiplay/core/ui/__init__.py src/ushareiplay/core/ui/element_finder.py src/ushareiplay/core/ui/key_actions.py src/ushareiplay/core/ui/gesture_handler.py src/ushareiplay/core/ui/navigation.py
```

Expected: PASS with no output.

- [ ] **Step 2: Run focused architecture-slice tests**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_imports.py tests/test_app_controller_driver_subscribers.py tests/test_command_parser_no_config_mutation.py tests/test_keyword_acl.py tests/test_user_canonical_mapping.py tests/test_avatar_exit.py
```

Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run:

```bash
source .venv/bin/activate
uv run pytest -q
```

Expected: PASS. If a test requires external Appium/device state, document the exact failing test and reason; do not run `main.py` because AGENTS.md says it always fails in this environment without Appium and Android apps.

- [ ] **Step 4: Inspect diff for accidental behavior changes**

Run:

```bash
git diff -- src/ushareiplay/core/app_handler.py src/ushareiplay/core/ui src/ushareiplay/core/app_controller.py tests
```

Expected:
- `AppHandler` keeps all previous public method names.
- New helper modules contain the moved method bodies.
- `reinitialize_driver()` calls `_notify_driver_subscribers(self.driver)`.
- Root tests are represented under `tests/`.

- [ ] **Step 5: Commit any verification fixes**

If verification required fixes, commit them:

```bash
git add src/ushareiplay/core/app_handler.py src/ushareiplay/core/ui src/ushareiplay/core/app_controller.py tests
git commit -m "fix: stabilize architecture hardening slice"
```

If no fixes were needed, skip this step.

## Follow-Up Plans

- ServiceRegistry/DI plan: remove direct `AppController.instance()` calls from `driver_decorator.py`, `command_manager.py`, `event_manager.py`, and `events/chat_room_title.py`.
- Async blocking plan: replace or isolate `time.sleep()` calls beginning with event-loop paths in `AppController.start_monitoring()`, command execution, and handlers.
- Logging plan: replace production `print()` calls with logger calls where a logger is available.
- QQMusicHandler plan: split search, playlist, lyrics, quality filtering, and playback control into a `handlers/qq_music/` package.
- Config plan: introduce layered config files while preserving `config.yaml` and `config.local.yaml` compatibility.

## Self-Review

- Spec coverage: This plan covers P0 `AppHandler` splitting, P2 driver reference observer pattern, and P2 root test cleanup. It scopes out DI, broad exception cleanup, full async sleep replacement, print/logger cleanup, QQMusic split, config split, and DB migration tooling as separate follow-up plans.
- Placeholder scan: No `TBD`, `TODO`, "implement later", or unspecified test steps remain. The only ellipses appear in code move instructions where the exact source is the existing method body in `AppHandler`; the target method list and required substitutions are explicit.
- Type consistency: Helper class names are `ElementFinder`, `KeyActions`, `GestureHandler`, and `Navigator` throughout. `AppController` uses `_driver_subscribers`, `register_driver_subscriber()`, and `_notify_driver_subscribers()` consistently.

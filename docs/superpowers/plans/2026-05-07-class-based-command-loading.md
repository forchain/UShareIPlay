# Class-Based Command Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove per-command factory boilerplate so each command module only defines a `BaseCommand` subclass, while `CommandManager` discovers and instantiates commands directly from the controller it already owns.

**Architecture:** Keep `CommandManager` as the single loader and cache owner. It should resolve each module from `self.commands_path`, find the concrete `BaseCommand` subclass, instantiate it with the controller reference stored on the manager, and continue attaching the runtime instance to the imported module for backward-compatible caching. Migrate command modules in two batches so the codebase stays testable while the old factory protocol is still in place. Once all modules are class-only, remove the legacy factory fallback and update the developer docs to describe the new contract.

**Tech Stack:** Python 3.13, pytest, uv.

---

## Scope

This plan only changes command discovery, command module structure, and the small docs surface that tells contributors how to add a command. It does not redesign `BaseCommand`, change command parsing, or alter command behavior beyond removing the old `create_command()` / `command = None` module boilerplate.

## File Structure

- Modify `src/ushareiplay/managers/command_manager.py`: load modules from `self.commands_path`, resolve a concrete `BaseCommand` subclass, instantiate it with the manager's controller, and later remove the legacy factory branch.
- Modify `src/ushareiplay/core/app_controller.py`: assign `self` to `self.command_manager.controller` during initialization so the manager can inject the controller into new command instances without importing `AppController`.
- Modify `src/ushareiplay/commands/acc.py`
- Modify `src/ushareiplay/commands/admin.py`
- Modify `src/ushareiplay/commands/alias.py`
- Modify `src/ushareiplay/commands/enter.py`
- Modify `src/ushareiplay/commands/exit.py`
- Modify `src/ushareiplay/commands/gift.py`
- Modify `src/ushareiplay/commands/help.py`
- Modify `src/ushareiplay/commands/info.py`
- Modify `src/ushareiplay/commands/keyword.py`
- Modify `src/ushareiplay/commands/mode.py`
- Modify `src/ushareiplay/commands/next.py`
- Modify `src/ushareiplay/commands/notice.py`
- Modify `src/ushareiplay/commands/pack.py`
- Modify `src/ushareiplay/commands/pause.py`
- Modify `src/ushareiplay/commands/playlist.py`
- Modify `src/ushareiplay/commands/room.py`
- Modify `src/ushareiplay/commands/say.py`
- Modify `src/ushareiplay/commands/seat.py`
- Modify `src/ushareiplay/commands/skip.py`
- Modify `src/ushareiplay/commands/vol.py`
- Modify `src/ushareiplay/commands/album.py`
- Modify `src/ushareiplay/commands/end.py`
- Modify `src/ushareiplay/commands/fav.py`
- Modify `src/ushareiplay/commands/lyrics.py`
- Modify `src/ushareiplay/commands/mic.py`
- Modify `src/ushareiplay/commands/play.py`
- Modify `src/ushareiplay/commands/radio.py`
- Modify `src/ushareiplay/commands/return.py`
- Modify `src/ushareiplay/commands/singer.py`
- Modify `src/ushareiplay/commands/theme.py`
- Modify `src/ushareiplay/commands/timer.py`
- Modify `src/ushareiplay/commands/title.py`
- Modify `src/ushareiplay/commands/topic.py`
- Modify `tests/test_command_manager_class_loading.py`
- Modify `tests/test_simple_command_modules_class_only.py`
- Modify `tests/test_stateful_command_modules_class_only.py`
- Modify `tests/test_command_manager_no_legacy_factory.py`
- Modify `CLAUDE.md`
- Modify `docs/music.md`

## Task 1: Teach `CommandManager` to Instantiate Command Classes

**Files:**
- Modify: `src/ushareiplay/managers/command_manager.py`
- Modify: `src/ushareiplay/core/app_controller.py`
- Create: `tests/test_command_manager_class_loading.py`

- [ ] **Step 1: Write the failing test for class-based loading**

Create `tests/test_command_manager_class_loading.py` with a temp module that defines only a `BaseCommand` subclass and no `create_command()` function:

```python
import asyncio
from pathlib import Path


class DummyController:
    def __init__(self):
        self.soul_handler = object()
        self.music_handler = object()
        self.marker = "ok"


def test_load_command_module_instantiates_class_without_factory(tmp_path):
    (tmp_path / "demo.py").write_text(
        "from ushareiplay.core.base_command import BaseCommand\n"
        "class DemoCommand(BaseCommand):\n"
        "    async def process(self, message_info, parameters):\n"
        "        return {'message': self.controller.marker}\n"
    )

    from ushareiplay.managers.command_manager import CommandManager

    manager = CommandManager.__new__(CommandManager)
    manager.__init__()
    manager.commands_path = tmp_path
    manager.controller = DummyController()

    module = manager.load_command_module("demo")
    assert module is not None
    assert hasattr(module, "command")
    assert module.command.controller is manager.controller
    result = asyncio.run(module.command.process(None, []))
    assert result == {"message": "ok"}
```

- [ ] **Step 2: Run the test to confirm the current loader cannot do this yet**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_command_manager_class_loading.py
```

Expected: fail because `CommandManager` still requires the old factory contract.

- [ ] **Step 3: Implement class-based discovery with controller injection**

Update `src/ushareiplay/managers/command_manager.py` so it stores a controller reference and resolves command classes directly from the imported module. The essential shape should be:

```python
class CommandManager(Singleton):
    def __init__(self):
        self.controller = None
        self._handler = None
        self._logger = None
        self.commands_path = Path(__file__).parent.parent / "commands"
        self.command_modules = {}
        self.command_parser = None

    def _find_command_class(self, module):
        from ushareiplay.core.base_command import BaseCommand

        candidates = [
            value
            for value in module.__dict__.values()
            if isinstance(value, type)
            and issubclass(value, BaseCommand)
            and value is not BaseCommand
            and value.__module__ == module.__name__
        ]
        return candidates[0] if len(candidates) == 1 else None

    def load_command_module(self, command):
        module_path = (self.commands_path / f"{command}.py").resolve()
        ...
        command_cls = self._find_command_class(module)
        if command_cls is None:
            self.logger.error("Command module does not define a concrete BaseCommand subclass")
            return None
        module.command = command_cls(self.controller)
        self.command_modules[command] = module
        return module
```

Also update `src/ushareiplay/core/app_controller.py` so that after `self.command_manager = CommandManager.instance()` it assigns:

```python
self.command_manager.controller = self
```

That keeps the controller injection explicit and removes the need for `CommandManager` to import `AppController`.

- [ ] **Step 4: Run the class-loading test again**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_command_manager_class_loading.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ushareiplay/managers/command_manager.py src/ushareiplay/core/app_controller.py tests/test_command_manager_class_loading.py
git commit -m "refactor: support class-based command loading"
```

## Task 2: Convert the Simple Command Modules

**Files:**
- Modify: `src/ushareiplay/commands/acc.py`
- Modify: `src/ushareiplay/commands/admin.py`
- Modify: `src/ushareiplay/commands/alias.py`
- Modify: `src/ushareiplay/commands/enter.py`
- Modify: `src/ushareiplay/commands/exit.py`
- Modify: `src/ushareiplay/commands/gift.py`
- Modify: `src/ushareiplay/commands/help.py`
- Modify: `src/ushareiplay/commands/info.py`
- Modify: `src/ushareiplay/commands/keyword.py`
- Modify: `src/ushareiplay/commands/mode.py`
- Modify: `src/ushareiplay/commands/next.py`
- Modify: `src/ushareiplay/commands/notice.py`
- Modify: `src/ushareiplay/commands/pack.py`
- Modify: `src/ushareiplay/commands/pause.py`
- Modify: `src/ushareiplay/commands/playlist.py`
- Modify: `src/ushareiplay/commands/say.py`
- Modify: `src/ushareiplay/commands/seat.py`
- Modify: `src/ushareiplay/commands/skip.py`
- Modify: `src/ushareiplay/commands/vol.py`
- Create: `tests/test_simple_command_modules_class_only.py`

- [ ] **Step 1: Write the failing source-level regression test**

Create `tests/test_simple_command_modules_class_only.py` to verify that the simple command modules no longer contain the legacy factory boilerplate:

```python
from pathlib import Path


SIMPLE_COMMANDS = {
    "acc",
    "admin",
    "alias",
    "enter",
    "exit",
    "gift",
    "help",
    "info",
    "keyword",
    "mode",
    "next",
    "notice",
    "pack",
    "pause",
    "playlist",
    "say",
    "seat",
    "skip",
    "vol",
}


def test_simple_command_modules_are_class_only():
    commands_path = Path(__file__).resolve().parents[1] / "src" / "ushareiplay" / "commands"
    offenders = {}

    for name in SIMPLE_COMMANDS:
        source = (commands_path / f"{name}.py").read_text(encoding="utf-8")
        hits = []
        if "def create_command(" in source:
            hits.append("create_command")
        if "command = None" in source:
            hits.append("command = None")
        if hits:
            offenders[name] = hits

    assert not offenders, f"Simple command modules still use the old factory protocol: {offenders}"
```

- [ ] **Step 2: Run the test to confirm it fails on the current code**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_simple_command_modules_class_only.py
```

Expected: fail because those modules still define `create_command()` and `command = None`.

- [ ] **Step 3: Rewrite the simple command modules as pure classes**

For each file listed in this task, delete the module-level factory boilerplate and keep only the class definition plus existing behavior. The resulting module shape should look like:

```python
from ushareiplay.core.base_command import BaseCommand


class FooCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler
```

Apply that pattern to:

`acc.py`, `admin.py`, `alias.py`, `enter.py`, `exit.py`, `gift.py`, `help.py`, `info.py`, `keyword.py`, `mode.py`, `next.py`, `notice.py`, `pack.py`, `pause.py`, `playlist.py`, `say.py`, `seat.py`, `skip.py`, `vol.py`.

Keep each module's existing `process`, `update`, and helper methods unchanged apart from removing any `controller.<name>_command = ...` assignment and deleting the `create_command()` function plus `command = None`.

- [ ] **Step 4: Run the simple-module regression test again**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_simple_command_modules_class_only.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ushareiplay/commands/acc.py src/ushareiplay/commands/admin.py src/ushareiplay/commands/alias.py src/ushareiplay/commands/enter.py src/ushareiplay/commands/exit.py src/ushareiplay/commands/gift.py src/ushareiplay/commands/help.py src/ushareiplay/commands/info.py src/ushareiplay/commands/keyword.py src/ushareiplay/commands/mode.py src/ushareiplay/commands/next.py src/ushareiplay/commands/notice.py src/ushareiplay/commands/pack.py src/ushareiplay/commands/pause.py src/ushareiplay/commands/playlist.py src/ushareiplay/commands/say.py src/ushareiplay/commands/seat.py src/ushareiplay/commands/skip.py src/ushareiplay/commands/vol.py tests/test_simple_command_modules_class_only.py
git commit -m "refactor: convert simple commands to class-only modules"
```

## Task 3: Convert the Stateful Command Modules

**Files:**
- Modify: `src/ushareiplay/commands/album.py`
- Modify: `src/ushareiplay/commands/end.py`
- Modify: `src/ushareiplay/commands/fav.py`
- Modify: `src/ushareiplay/commands/lyrics.py`
- Modify: `src/ushareiplay/commands/mic.py`
- Modify: `src/ushareiplay/commands/play.py`
- Modify: `src/ushareiplay/commands/radio.py`
- Modify: `src/ushareiplay/commands/return.py`
- Modify: `src/ushareiplay/commands/room.py`
- Modify: `src/ushareiplay/commands/singer.py`
- Modify: `src/ushareiplay/commands/theme.py`
- Modify: `src/ushareiplay/commands/timer.py`
- Modify: `src/ushareiplay/commands/title.py`
- Modify: `src/ushareiplay/commands/topic.py`
- Create: `tests/test_stateful_command_modules_class_only.py`

- [ ] **Step 1: Write the failing source-level regression test**

Create `tests/test_stateful_command_modules_class_only.py` with the same boilerplate check, but only for the stateful modules:

```python
from pathlib import Path


STATEFUL_COMMANDS = {
    "album",
    "end",
    "fav",
    "lyrics",
    "mic",
    "play",
    "radio",
    "return",
    "room",
    "singer",
    "theme",
    "timer",
    "title",
    "topic",
}


def test_stateful_command_modules_are_class_only():
    commands_path = Path(__file__).resolve().parents[1] / "src" / "ushareiplay" / "commands"
    offenders = {}

    for name in STATEFUL_COMMANDS:
        source = (commands_path / f"{name}.py").read_text(encoding="utf-8")
        hits = []
        if "def create_command(" in source:
            hits.append("create_command")
        if "command = None" in source:
            hits.append("command = None")
        if hits:
            offenders[name] = hits

    assert not offenders, f"Stateful command modules still use the old factory protocol: {offenders}"
```

- [ ] **Step 2: Run the test to confirm it fails on the current code**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_stateful_command_modules_class_only.py
```

Expected: fail because these modules still expose the factory protocol.

- [ ] **Step 3: Rewrite the stateful command modules as pure classes**

Apply the same class-only cleanup to:

`album.py`, `end.py`, `fav.py`, `lyrics.py`, `mic.py`, `play.py`, `radio.py`, `return.py`, `room.py`, `singer.py`, `theme.py`, `timer.py`, `title.py`, `topic.py`.

Keep existing behavior intact:

```python
class ReturnCommand(BaseCommand):
    async def user_return(self, username: str):
        ...

class TimerCommand(BaseCommand):
    def update(self):
        ...

class EndCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler
        self.party_manager = PartyManager.instance()
```

Only remove `create_command()`, `command = None`, and any `controller.<name>_command = ...` assignment from the module body. Keep the controller injection in the class constructor so the command still has access to handlers, config, and managers.

- [ ] **Step 4: Run the stateful-module regression test again**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_stateful_command_modules_class_only.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ushareiplay/commands/album.py src/ushareiplay/commands/end.py src/ushareiplay/commands/fav.py src/ushareiplay/commands/lyrics.py src/ushareiplay/commands/mic.py src/ushareiplay/commands/play.py src/ushareiplay/commands/radio.py src/ushareiplay/commands/return.py src/ushareiplay/commands/room.py src/ushareiplay/commands/singer.py src/ushareiplay/commands/theme.py src/ushareiplay/commands/timer.py src/ushareiplay/commands/title.py src/ushareiplay/commands/topic.py tests/test_stateful_command_modules_class_only.py
git commit -m "refactor: convert stateful commands to class-only modules"
```

## Task 4: Remove the Legacy Factory Path and Update Docs

**Files:**
- Modify: `src/ushareiplay/managers/command_manager.py`
- Create: `tests/test_command_manager_no_legacy_factory.py`
- Modify: `CLAUDE.md`
- Modify: `docs/music.md`

- [ ] **Step 1: Write the failing test that guards against reintroducing the old protocol**

Create `tests/test_command_manager_no_legacy_factory.py` to assert that `CommandManager` no longer contains the legacy factory branch:

```python
from pathlib import Path


def test_command_manager_has_no_legacy_create_command_branch():
    source = (Path(__file__).resolve().parents[1] / "src" / "ushareiplay" / "managers" / "command_manager.py").read_text(encoding="utf-8")
    assert "create_command" not in source
    assert "does not have create_command" not in source
```

- [ ] **Step 2: Run the test to confirm the fallback still exists**

Run:

```bash
source .venv/bin/activate
uv run pytest -q tests/test_command_manager_no_legacy_factory.py
```

Expected: fail because `CommandManager` still includes the legacy compatibility branch.

- [ ] **Step 3: Delete the legacy factory branch and update the docs**

Remove the `create_command()` fallback from `src/ushareiplay/managers/command_manager.py` so the loader only accepts a concrete `BaseCommand` subclass. Keep the module attachment behavior (`module.command = ...`) and the `self.commands_path / f"{command}.py"` lookup.

Update `CLAUDE.md` and `docs/music.md` so the contributor guidance reads like this:

```markdown
### Adding a New Command

1. Create `src/ushareiplay/commands/<name>.py`
2. Define exactly one `BaseCommand` subclass in that module
3. Implement `process(self, message_info, parameters)` and any optional hooks such as `update()` or `user_return()`
4. Do not add a `create_command()` factory or a module-level `command = None`
5. `CommandManager` auto-discovers the class via dynamic loading, so no registration is needed
```

Also update the command extension note in `docs/music.md` to say the new command module should export a single `BaseCommand` subclass with `process()`, not `execute()`.

- [ ] **Step 4: Run the targeted verification suite**

Run:

```bash
source .venv/bin/activate
uv run pytest -q \
  tests/test_command_manager_class_loading.py \
  tests/test_simple_command_modules_class_only.py \
  tests/test_stateful_command_modules_class_only.py \
  tests/test_command_manager_no_legacy_factory.py \
  tests/test_dynamic_loading.py \
  tests/test_paths.py \
  tests/test_help_command_is_current.py
python -m py_compile src/ushareiplay/managers/command_manager.py src/ushareiplay/commands/*.py
```

Expected: all targeted tests pass and every modified Python file compiles.

- [ ] **Step 5: Commit**

```bash
git add src/ushareiplay/managers/command_manager.py tests/test_command_manager_no_legacy_factory.py CLAUDE.md docs/music.md
git commit -m "refactor: remove legacy command factory protocol"
```

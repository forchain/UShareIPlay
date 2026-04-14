## 1. Initialize Root Package

- [ ] 1.1 Create the new directory `src/ushareiplay/` and place an empty `__init__.py` inside.
- [ ] 1.2 Move all existing functional directories (`commands`, `core`, `dal`, `events`, `handlers`, `helpers`, `managers`, `models`) from `src/` into the `src/ushareiplay/` namespace.

## 2. Setup uv and pyproject.toml

- [ ] 2.1 Run `uv init` at the project root to generate `pyproject.toml` (or manually scaffold).
- [ ] 2.2 Parse `requirements.txt` and use `uv add` to migrate all dependencies into `pyproject.toml`.
- [ ] 2.3 Remove the legacy `requirements.txt`.

## 3. Refactor Import Paths

- [ ] 3.1 Execute a bulk regex/AST replacement to convert all relative imports (e.g., `from ..core` and `from .handlers`) to absolute `ushareiplay` package imports (`from ushareiplay.core` and `from ushareiplay.handlers`).
- [ ] 3.2 Update dynamic command module loading in `src/ushareiplay/managers/command_manager.py` to correctly resolve `f"ushareiplay.commands.{command}"`.
- [ ] 3.3 Update dynamic event module loading in `src/ushareiplay/managers/event_manager.py` to correctly resolve `f"ushareiplay.events.{module_name}"`.
- [ ] 3.4 Fix `timer_manager.py` `Path(__file__).parent.parent.parent` to add one extra `.parent` for the new nesting level.
- [ ] 3.5 Update Tortoise ORM model registration in `db_manager.py` from `src.models` to `ushareiplay.models`.
- [ ] 3.6 Ensure all other path resolutions using `__file__` remain correct when nested.

## 4. Fix Entry Points

- [ ] 4.1 Update the imports in `main.py` at the root to point to `ushareiplay.xxx`.
- [ ] 4.2 Update all python test files (`test_singleton.py`, `test_chat_logger.py`, `test_timer_restart.py`) to import from `ushareiplay` and remove `sys.path` hacks.
- [ ] 4.3 Update `run.sh` to use `uv run python main.py`.

## 5. Verification

- [ ] 5.1 Run all standard tests to verify that no `ModuleNotFoundError` or layout regressions exist.
- [ ] 5.2 Do a dry-run startup (`uv run main.py` or equivalent) to verify successful app initialization and database connections.

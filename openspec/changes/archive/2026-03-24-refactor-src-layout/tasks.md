## 1. Initialize Root Package

- [x] 1.1 Create the new directory `src/ushareiplay/` and place an empty `__init__.py` inside.
- [x] 1.2 Move all existing functional directories (`commands`, `core`, `dal`, `events`, `handlers`, `helpers`, `managers`, `models`) from `src/` into the `src/ushareiplay/` namespace.

## 2. Setup uv and pyproject.toml

- [x] 2.1 Run `uv init` at the project root to generate `pyproject.toml` (or manually scaffold).
- [x] 2.2 Parse `requirements.txt` and use `uv add` to migrate all dependencies into `pyproject.toml`.
- [x] 2.3 Remove the legacy `requirements.txt`.

## 3. Refactor Import Paths

- [x] 3.1 Execute a bulk regex/AST replacement to convert all relative imports (e.g., `from ..core` and `from .handlers`) to absolute `ushareiplay` package imports (`from ushareiplay.core` and `from ushareiplay.handlers`).
- [x] 3.2 Update dynamic command module loading in `src/ushareiplay/managers/command_manager.py` to correctly resolve `f"ushareiplay.commands.{command}"`.
- [x] 3.3 Update dynamic event module loading in `src/ushareiplay/managers/event_manager.py` to correctly resolve `f"ushareiplay.events.{module_name}"`.
- [x] 3.4 Fix `timer_manager.py` `Path(__file__).parent.parent.parent` to add one extra `.parent` for the new nesting level.
- [x] 3.5 Update Tortoise ORM model registration in `db_manager.py` from `src.models` to `ushareiplay.models`.
- [x] 3.6 Ensure all other path resolutions using `__file__` remain correct when nested.

## 4. Fix Entry Points

- [x] 4.1 Update the imports in `main.py` at the root to point to `ushareiplay.xxx`.
- [x] 4.2 Update all python test files (`test_singleton.py`, `test_chat_logger.py`, `test_timer_restart.py`) to import from `ushareiplay` and remove `sys.path` hacks.
- [x] 4.3 Update `run.sh` to use `uv run python main.py`.

## 5. Verification

- [x] 5.1 Run all standard tests to verify that no `ModuleNotFoundError` or layout regressions exist.
- [x] 5.2 Do a dry-run startup (`uv run main.py` or equivalent) to verify successful app initialization and database connections.

## 6. Proper Entry Point (src layout best practice)

- [x] 6.1 Create `src/ushareiplay/__main__.py` with the application entry logic moved from root `main.py`.
- [x] 6.2 Add `[project.scripts]` entry point in `pyproject.toml` pointing to `ushareiplay.__main__:main`.
- [x] 6.3 Update `run.sh` to use `uv run ushareiplay` (via script entry point).
- [x] 6.4 Simplify root `main.py` to a minimal shim (or remove it) since logic lives in the package.

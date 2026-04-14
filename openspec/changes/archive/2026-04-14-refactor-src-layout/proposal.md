## Why

The current structure of the project organizes code into flat directories under `src/` (e.g., `src/managers`, `src/commands`). This causes these directories to be treated as top-level Python packages, resulting in extensive use of fragile relative imports (`from ..core.singleton` etc.) and potential namespace collisions. Furthermore, the project currently uses `requirements.txt` which is less standard for modern package management than `pyproject.toml`.

Refactoring to a standard Python `src layout` and utilizing `pyproject.toml` will establish a clear root package namespace (`ushareiplay`), allowing for clean and robust absolute imports (`from ushareiplay.core...`), and simplifying dependency management and installation.

## What Changes

- Create a new root package directory `src/ushareiplay/`.
- Move all existing code directories (`commands`, `core`, `dal`, `events`, `handlers`, `helpers`, `managers`, `models`) into `src/ushareiplay/`.
- Add an empty `__init__.py` to `src/ushareiplay/`.
- Replace all relative module imports across the codebase with absolute imports (`from ushareiplay.X`).
- Refactor dynamic module loading in `CommandManager` to resolve paths inside the new package namespace.
- Update all entry point scripts (`main.py`, `test_*.py`) to import from the new `ushareiplay` package.
- Introduce `pyproject.toml` to replace `requirements.txt` for standardized dependency and package management.

## Capabilities

### New Capabilities
None. This is a purely structural refactoring.

### Modified Capabilities
None.

## Impact

- **Codebase:** Extensive modifications to import statements in ~50+ files.
- **Dependencies:** Transition from `requirements.txt` to `pyproject.toml`.
- **System:** `CommandManager`'s dynamic command loading strings will change.
- **Entry Points:** Top-level scripts will need updated import paths.

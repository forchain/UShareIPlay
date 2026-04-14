## Context

The current Python codebase places modules directly under `src/`, causing polluting imports and preventing standard tooling. The user requested migrating to a standard `src` layout and replacing `requirements.txt` with a modern `pyproject.toml`.

## Goals / Non-Goals

**Goals:**
- Move all source code into the `src/ushareiplay/` namespace.
- Update all internal imports from relative to absolute (`ushareiplay.xxx`).
- Introduce `pyproject.toml` using a standard build backend (like `setuptools` or `hatchling`), migrating all dependencies from `requirements.txt`.
- Ensure the app starts cleanly and tests pass.

**Non-Goals:**
- No business logic changes or feature additions.
- No changes to user-facing functionality.

## Decisions

- **Namespace Name:** `ushareiplay`, derived from the repository name. All code will live in `src/ushareiplay/`.
- **Dependency Management:** Use `uv` to initialize the project (`uv init`) and manage dependencies. We will port existing dependencies (`Appium-Python-Client`, `PyYAML`, `tortoise-orm`, `aiosqlite`, etc.) from `requirements.txt` into `pyproject.toml` using `uv add`.
- **CommandManager:** Dynamically loading command modules uses `importlib`. The module string path will be updated to `ushareiplay.commands.{command}`.

## Risks / Trade-offs

- **Risk:** Missed relative imports could break specific commands not covered by tests.
**Mitigation:** We will rigorously search and replace `from ..` and `from .` matching the codebase structure and leverage Python's module resolution during test runs.
- **Risk:** `main.py` entrypoint and file paths.
**Mitigation:** `main.py` remains at the project root. Imports change from `from src.core...` to `from ushareiplay.core...`. We will also ensure `PYTHONPATH` or editable installs (`pip install -e .`) are used to execute the code.

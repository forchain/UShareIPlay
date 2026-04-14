# AGENTS.md

## Cursor Cloud specific instructions

### Overview

UShareIPlay is a Python Android automation bot for **Soul App** + **QQ Music** via Appium. See `CLAUDE.md` and `README.md` for full architecture and command reference.

### Virtual environment

The `.venv` virtual environment is pre-created. Always activate before running anything:

```bash
source .venv/bin/activate
```

### Running tests

Tests are standalone scripts (no pytest runner configured). The most reliable test is:

```bash
python test_timer_restart.py   # DB + timer logic, uses in-memory SQLite — always passes
```

The other two tests have known issues unrelated to code quality:
- `test_singleton.py` — fails due to `ThemeManager.instance()` signature mismatch with the mock (test was written against an older API)
- `test_chat_logger.py` — fails due to `PermissionError` when log directory is `../logs` (relative path escapes workspace)

### Running `main.py`

`main.py` loads `config.yaml`, initializes SQLite DB at `data/soul_bot.db`, then attempts to connect to an Appium server. **It will always fail in the cloud VM** because it requires:
1. A running Appium server with a connected Android device
2. Soul App and QQ Music installed on the device

To validate code changes without a device, use the test scripts or write focused unit tests with in-memory SQLite (see `test_timer_restart.py` for a good pattern).

### Linting

No linter configuration (flake8/pylint/ruff) is committed. Use `python -m py_compile <file>` to syntax-check individual files, or import-test modules in a Python shell.

### Key gotchas

- `config.yaml` is 26k+ lines. Local overrides go in `config.local.yaml` (gitignored). See `config.local.yaml.example`.
- All managers use the Singleton pattern via `Singleton` metaclass — always call `.instance()`, never construct directly.
- The project has no `pyproject.toml` or `setup.py` — it's not an installable package. Imports use `src.` prefix from the workspace root.

### GitHub / PR account switching

When creating or editing pull requests with `gh`, the correct GitHub account depends on the repository remote URL.

- **Rule**: Read `remote.origin.url` and extract the username before `@github.com` (e.g. `https://forchain@github.com/forchain/UShareIPlay` → `forchain`). Temporarily switch `gh` to that account for PR operations, then switch back.

Example:

```bash
git config --get remote.origin.url
gh auth status -h github.com
gh auth switch -h github.com -u <remote-username>

# PR operations (create/edit/view)
gh pr create ...

# Switch back (pick whatever was active before)
gh auth switch -h github.com -u <previous-active-username>
```

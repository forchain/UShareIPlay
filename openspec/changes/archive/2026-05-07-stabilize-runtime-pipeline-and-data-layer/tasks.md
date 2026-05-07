## 1. Runtime Queue Pipeline

- [x] 1.1 Extract the existing queued-message splitting/routing behavior into a testable runtime queue drain helper.
- [x] 1.2 Preserve semicolon splitting, `{user_name}` substitution, command routing, and normal message sending behavior in the helper.
- [x] 1.3 Wire the helper into `AppController.start_monitoring()` so the monitor loop drains `MessageQueue` independently of `MessageContentEvent`.
- [x] 1.4 Remove the queue-drain call from `MessageContentEvent` update logic to keep queue drain single-owner.
- [x] 1.5 Preserve `queue.drain.start` and `queue.drain.end` observability events with message and command counts.

## 2. Runtime Helper Extraction

- [x] 2.1 Extract `.agent/commands/*.cmd` reading and enqueue behavior into an `AgentCommandSpool` helper while preserving `agent.inject.*` events.
- [x] 2.2 Extract status snapshot generation from `AppController._update_status_from_page_source()` into a `StatusReporter` helper.
- [x] 2.3 Keep status JSON fields and `state.snapshot` / `state.ready` event behavior compatible with the current runtime output.
- [x] 2.4 Keep driver lifecycle, handler initialization, and `ui_lock` ownership in `AppController`.

## 3. Data Layer Cleanup

- [x] 3.1 Search for live `DBHelper`, `db_helper`, and `pending_hellos` usage and document the result in the implementation notes or commit message.
- [x] 3.2 If no live callers exist, remove eager `DBHelper` initialization and delete the unused direct sqlite helper module.
- [x] 3.3 If live callers exist, add a Tortoise model/DAO for pending hellos and migrate those callers before removing direct sqlite access. (N/A: no live callers found)
- [x] 3.4 Verify the Tortoise DB initialization tests still pass after the cleanup.

## 4. Config and Logging Cleanup

- [x] 4.1 Update handler and chat logger setup to prefer the already-loaded runtime config instead of re-reading `config.yaml`.
- [x] 4.2 Keep safe fallback defaults for tests or partial construction paths that lack full runtime config.
- [x] 4.3 Add or update focused tests for log directory resolution behavior.

## 5. Verification and Documentation

- [x] 5.1 Add tests proving queued commands are drained without requiring a `message_content` event.
- [x] 5.2 Add tests proving queue drain is not duplicated when `MessageContentEvent` processes visible chat messages.
- [x] 5.3 Run `uv run pytest -q`.
- [x] 5.4 Run `python -m py_compile` across `src/ushareiplay`.
- [x] 5.5 Update project documentation that still describes stale test runner or missing `pyproject.toml` assumptions.

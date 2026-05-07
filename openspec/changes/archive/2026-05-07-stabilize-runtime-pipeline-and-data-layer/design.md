## Context

The runtime monitor loop currently reads agent command files, polls console input, reads `page_source`, updates status, and dispatches events from a single `AppController` class. Chat messages are handled through `MessageContentEvent`, and that event also drains `MessageQueue` for runtime-produced inputs such as timer messages, post-party automation, keyword expansion, and agent-injected commands.

That coupling makes queued command execution depend on a UI chat anchor being visible and processed. It also keeps several non-UI responsibilities inside `AppController`, making the main loop harder to reason about and harder to test without a device.

The project already has useful constraints and infrastructure:
- `MessageQueue` is the shared async input channel.
- `CommandManager.handle_message_commands()` is the existing command dispatch path.
- `Observability` already emits queue and command lifecycle events.
- `ui_lock` protects UI mutation paths and must remain the guard for command/event UI operations.
- Existing tests can exercise queue, parser, DB, and import behavior without a real Appium device.

## Goals / Non-Goals

**Goals:**
- Drain runtime-produced messages from the monitor loop independently of `message_content` events.
- Keep queue and command observability stable after moving the drain location.
- Extract non-UI helper responsibilities from `AppController` without changing Appium driver ownership.
- Resolve the legacy direct sqlite helper path by either removing it if unused or migrating it behind the ORM if still needed.
- Reduce duplicate config loading in logger setup paths.
- Update documentation to match the current pytest/`pyproject.toml` baseline.

**Non-Goals:**
- No full rewrite of the command manager, event manager, singleton pattern, or dynamic loader.
- No broad conversion of synchronous Appium calls to async/threaded execution.
- No new UI worker queue in this change.
- No database migration framework or new dependency.
- No behavioral changes to command syntax, timer semantics, or chat message parsing beyond queue drain timing.

## Decisions

1. **Move queue drain to the runtime loop**

   `AppController.start_monitoring()` should drain `MessageQueue` once per loop iteration before or near the existing agent/console input handling and before event processing. The drain implementation should reuse the existing splitting and dispatch semantics from `MessageContentEvent._process_queue_messages()`:
   - semicolon-separated parts remain supported
   - `{user_name}` substitution remains supported
   - colon-prefixed parts become command messages
   - non-command parts are sent as normal Soul messages

   Alternative considered: leave drain in `MessageContentEvent` and add another fallback event. This keeps the hidden dependency on chat UI state and does not address timer/agent starvation when chat anchors are unavailable.

2. **Extract a small message drain helper rather than moving logic into another manager with UI ownership**

   Introduce a small helper/module that depends on `MessageQueue`, `CommandManager`, `SoulHandler`, and `Observability` through arguments or a runtime context. This keeps the queue drain testable and avoids deepening `MessageManager` or `MessageContentEvent`.

   Alternative considered: put drain into `MessageManager`. This is workable, but `MessageManager` already owns chat deduplication and missed-message recovery; runtime queue drain is broader than chat processing.

3. **Extract only low-risk AppController responsibilities**

   First extraction targets are:
   - `AgentCommandSpool`: read `.agent/commands/*.cmd`, delete successfully read files, enqueue command text, emit injection events.
   - `StatusReporter`: compute/write status from `page_source`, preserving current status fields and readiness events.
   - `ArtifactDumper` if implementation remains small; otherwise leave artifact dump inside controller for this change.

   Driver lifecycle, handler initialization, and UI lock ownership stay in `AppController`.

4. **Data layer cleanup starts with usage verification**

   Before changing schema, search for `DBHelper`, `pending_hellos`, and `db_helper` call sites. If only initialization remains, remove `DBHelper` and the unused module. If live callers exist, add a Tortoise model/DAO for pending hellos and migrate the caller before removing direct sqlite access.

   Alternative considered: always create a Tortoise model for `pending_hellos`. That adds schema and code for a feature that may already be dead.

5. **Config remains loaded once at runtime**

   Logger setup should prefer injected config or a resolved runtime paths helper instead of calling `ConfigLoader.load_config()` internally. Backward-compatible defaults may remain for tests that instantiate components without a full controller, but runtime paths should not depend on the current working directory re-reading `config.yaml`.

## Risks / Trade-offs

- **[Risk] Queue drain moves earlier and may dispatch commands while UI state is not chat-ready** → **Mitigation**: keep command execution under existing `ui_session`/`ui_lock` and reuse command manager behavior; do not dispatch direct UI writes outside the established command path.
- **[Risk] Duplicate drain if old `MessageContentEvent` drain remains active** → **Mitigation**: centralize drain in one helper and remove the queue-drain call from the message-content update path after tests cover the new location.
- **[Risk] Non-command queued messages call `send_message()` from the runtime loop and may fail if Soul input is unavailable** → **Mitigation**: preserve current behavior and logging; do not silently drop messages. Future UI operation boundary work can add retry/defer semantics.
- **[Risk] Removing `DBHelper` could delete dormant-but-expected behavior** → **Mitigation**: require static usage verification and, if uncertain, keep the module but stop initializing it eagerly until a caller is identified.
- **[Risk] Config injection may break tests that construct handlers with partial config** → **Mitigation**: keep fallback defaults in path resolution helpers and add focused tests for logger directory behavior.

## Migration Plan

1. Add the runtime queue drain helper and tests around queue splitting/dispatch using fake handler and command manager collaborators.
2. Wire the helper into `AppController.start_monitoring()` and remove the old drain trigger from `MessageContentEvent`.
3. Extract `AgentCommandSpool` and `StatusReporter` while preserving emitted event names and status schema.
4. Verify and remove/migrate `DBHelper`.
5. Update documentation and run the no-device verification suite.

Rollback is straightforward: restore queue drain to `MessageContentEvent` and keep helper extraction changes only if they are behavior-preserving. No external data format changes are planned unless `pending_hellos` is proven live and migrated.

## Why

Runtime inputs from timers, agent command files, keyword execution, and console injection currently depend on the chat message event path to drain `MessageQueue`. When the chat message anchor is absent, delayed, or the app is on an unknown page, queued commands can stall even though the main monitor loop is still running.

The project also has a few low-risk architecture cleanup opportunities surfaced by review: `AppController` owns too many runtime responsibilities, logger/config loading is duplicated, and a legacy sqlite helper opens the same database outside the Tortoise ORM lifecycle.

## What Changes

- Move message queue draining into the runtime monitor loop so non-chat inputs are processed independently from `message_content` events.
- Preserve existing queue observability events (`queue.drain.start`, `queue.drain.end`) while making drain behavior deterministic across input sources.
- Extract small, non-UI runtime helpers from `AppController` for agent command spool reading, status snapshot generation, and optional artifact dumping.
- Remove or migrate the legacy `DBHelper`/`pending_hellos` path after confirming whether it has any live callers.
- Stop reloading `config.yaml` inside logger setup paths when an already-loaded runtime config is available.
- Update project run/test documentation to match the current `pyproject.toml` and pytest-based verification baseline.

## Capabilities

### New Capabilities
- `runtime-message-pipeline`: Defines how runtime-produced messages and commands are enqueued, drained, and dispatched independently of UI chat events.

### Modified Capabilities
- `agent-observability-events`: Queue lifecycle events must still be emitted when queue drain moves from the chat event handler into the runtime loop.

## Impact

- Affected code: `src/ushareiplay/core/app_controller.py`, `src/ushareiplay/core/message_queue.py`, `src/ushareiplay/events/message_content.py`, `src/ushareiplay/managers/message_manager.py`, `src/ushareiplay/core/db_service.py`, logger setup in handler/manager modules, and documentation.
- Runtime behavior: queued timer/agent/keyword/console commands should be consumed even when no new chat message event is processed.
- Data layer: the legacy direct sqlite helper will be removed if unused, or migrated behind a Tortoise model/DAO if a live business use is found.
- No new third-party dependencies are introduced.

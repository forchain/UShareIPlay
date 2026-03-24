---
covers: [AppController, AppHandler, CommandManager, EventManager, MessageManager, MessageQueue, DatabaseManager, Singleton, BaseCommand, RecoveryManager, InfoManager, main.py]
last-synced: 2026-03-24
---

## Overview

`AppController` is the top-level orchestrator. It owns the Appium driver, initialises all handlers and managers, and runs the main async event loop. `AppHandler` is the base class for both app-specific handlers, providing element interaction primitives and crash recovery. All managers and handlers are singletons.

## Components

| Component | Responsibility |
|---|---|
| `AppController` | Driver init, handler/manager wiring, main loop, UI lock |
| `AppHandler` | Base UI automation: element wait/find/click, app switching, crash recovery |
| `SoulHandler` | Extends `AppHandler` for Soul App; reads chat, dispatches to `CommandManager` |
| `QQMusicHandler` | Extends `AppHandler` for QQ Music operations |
| `CommandManager` | Dynamic command loading; parses prefix → dispatches to command class |
| `EventManager` | Monitors background UI events (drawers, dialogs, planet tab, user count) |
| `MessageQueue` | Thread-safe async queue for outbound Soul App messages |
| `MessageManager` | Dequeues from `MessageQueue`, sends via `SoulHandler` |
| `DatabaseManager` | Tortoise ORM init; registers all models |
| `Singleton` | Thread-safe base class for all singletons |
| `BaseCommand` | Abstract base for all commands; provides level check, response formatting |
| `RecoveryManager` | Tracks consecutive errors; triggers app restart if threshold exceeded |
| `InfoManager` | Aggregates status for `:info` command |

## How It Works

**Startup sequence** (entry point: `uv run ushareiplay` → `ushareiplay.__main__:run`):
```
ConfigLoader.load_config()
  → DatabaseManager.init()         # Tortoise ORM, creates tables
  → AppController.instance(config) # creates driver, starts apps
  → controller.start_monitoring()  # enters main async loop
```

**Main loop**: `SoulHandler` polls the chat message list. New messages are parsed by `CommandManager.parse()` → matched to a command by prefix → `command.execute()` is called → result posted to `MessageQueue` → `MessageManager` sends it.

**UI lock** (`AppController.ui_lock`): An `asyncio.Lock` ensuring only one task touches the UI at a time. All commands and background event handlers acquire this lock via `async with controller.ui_session(reason)`.

**Crash recovery** (`AppHandler` + `RecoveryManager`):
- `@with_driver_recovery` decorator wraps UI methods — on `WebDriverException`, reinitialises the Appium driver and retries.
- `RecoveryManager` counts consecutive failures; if threshold exceeded, triggers full app restart.
- `main.py` wraps the controller in a retry loop (up to 10 restarts).

**Singleton pattern**: All managers use `Singleton` base class. Call `ClassName.instance()`, never the constructor directly. Constructors use lazy initialisation to avoid circular imports.

**Command discovery**: `CommandManager` scans `src/ushareiplay/commands/*.py` at startup, dynamically imports each module as `ushareiplay.commands.<name>`, and registers any module that exposes a `command` object. No manual registration needed.

**Async model**: Single asyncio event loop. Long-running operations (timer loop, event polling) run as `asyncio.Task`. UI operations are serialised via `ui_lock`. Outbound messages go through `MessageQueue` (thread-safe) → consumed by `MessageManager` task.

## Data Model

SQLite at `data/soul_bot.db` via Tortoise ORM.

Models registered at startup in `DatabaseManager`:
- `User`, `SeatReservation`, `Keyword`, `Timer`
- `EnterEvent`, `ExitEvent`, `ReturnEvent`
- `MessageInfo`

## Extension Points

- **New manager**: Create `src/ushareiplay/managers/<name>_manager.py` extending `Singleton`. Initialise lazily via `instance()`.
- **New event handler**: Create `src/ushareiplay/events/<name>.py` extending `BaseEvent`, register in `EventManager`.
- **New DB model**: Add to `src/ushareiplay/models/`, create DAO in `src/ushareiplay/dal/`, register in `DatabaseManager.init()` model list.
- **New command**: See `docs/music.md` Extension Points — same pattern applies everywhere.

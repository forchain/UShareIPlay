---
covers: [AppController, DriverLifecycle, AppHandler, SoulHandler, QQMusicHandler, CommandManager, ChatIntake, EventManager, MessageManager, MessageQueue, PlaybackMuting, DatabaseManager, Singleton, BaseCommand, RecoveryManager, InfoManager, RoomState, PresenceTracker, PlaylistState, PlaybackBroadcaster, OnlineListScraper, RolePolicy, main.py]
last-synced: 2026-09-23
---

## Overview

`AppController` orchestrates the application runtime, coordinating the Appium driver via `DriverLifecycle`, initialising all handlers, state managers, and background event loops. `AppHandler` supplies core UI primitives, element waits, and crash recovery. Domain state is separated into focused modules under `ushareiplay.state` with `InfoManager` as an explicit facade. All managers and handlers follow thread-safe singleton lifecycle patterns.

## Components

| Component | Responsibility |
|---|---|
| `AppController` | Runtime orchestrator; driver lifecycle coordination, UI lock (`ui_session`), main loop |
| `DriverLifecycle` | Appium driver initialization, socket/bridge health, and graceful teardown |
| `AppHandler` | Base UI automation: wait/find/click, app switching, crash recovery decorator |
| `SoulHandler` | Soul App UI automation: message list ingestion, drawer interactions, seat/mic control |
| `QQMusicHandler` | QQ Music UI automation: search, play, playlist navigation, lyrics OCR, accompaniment |
| `ChatIntake` | Pure classification boundary: regex parsing, Quoted Message isolation (`「...」`), prefix normalization, queue grammar |
| `CommandManager` | Discovers commands dynamically, checks permissions via `RolePolicy`, dispatches execution |
| `RolePolicy` | Evaluates caller tiers: Human Operators (Host, Console, Admin), System Users, Privileged, Normal |
| `PlaybackMuting` | Mutes bot microphone during track transitions, polls MediaSession for playback readiness |
| `EventManager` | Background UI monitor (page classification, drawer auto-dismissal, focus/entry events) |
| `MessageQueue` | Thread-safe async queue for outbound Soul App messages |
| `MessageManager` | Dequeues messages, formats tags (`[智能]`, `[人工]`), and sends them via `SoulHandler` |
| `InfoManager` | Explicit facade over `RoomState`, `PresenceTracker`, `PlaylistState`, `PlaybackBroadcaster`, and `OnlineListScraper` |
| `DatabaseManager` | Tortoise ORM initialization and schema management |
| `Singleton` | Thread-safe base class ensuring explicit composition root initialisation |
| `BaseCommand` | Base class for all commands; handles permissions, error wrapping, response templates |
| `RecoveryManager` | Tracks consecutive Appium/UI failures; triggers driver reinitialisation or app restart |

## How It Works

### Startup Sequence
Entry point: `uv run ushareiplay` (or `python main.py`):
```
ConfigLoader.load_config('config.yaml')
  → DatabaseManager.init()             # Tortoise ORM schema initialization
  → AppController.instance(config)     # Creates DriverLifecycle, starts apps
  → CommandManager.load_all_commands() # Auto-discovers ushareiplay/commands/*.py
  → controller.start_monitoring()      # Starts EventManager and Chat Intaker tasks
```

### Chat Intake & Command Dispatching
1. `ChatIntake.classify_chat_line()` parses raw Soul App chat messages with zero side effects:
   - Detects Quoted Messages wrapped in `「...」` and isolates them so quoted text cannot accidentally trigger commands or mention handlers.
   - Recognizes command prefixes:
     - Public commands: `:` or `：`
     - Silent commands: `/` or `／` (executes quietly without broadcasting response)
     - Private reply commands: `$` or `＄` (routes command output to the sender's private chat)
   - Recognizes `@我` or `@room_owner` mentions anywhere in the chat text.
2. `CommandManager` resolves the command:
   - Validates caller permissions against `RolePolicy`.
   - Checks `SleepManager` (blocks non-exempt commands between 23:00 and 06:00).
   - Enforces guest room restrictions if not in the default party room.
   - Acquires `controller.ui_session()` lock to prevent race conditions.
   - Executes the command under `PlaybackMuting` guard if the command touches music playback.

### Message Tagging
Outbound messages dispatched by `MessageManager` are tagged automatically to maintain transparency:
- LLM natural language replies: prefixed with `[智能]`
- Manual backend console replies: prefixed with `[人工]`

### State Architecture (`ushareiplay.state`)
Following ADR-0004, state concerns are separated into dedicated modules:
- `RoomState`: Tracks party ID, host/guest mode, and room capabilities.
- `PresenceTracker`: Maintains online user counts, follower presence, and entrant timestamps.
- `PlaylistState`: Tracks current playlist, queue items, and on-demand exemptions.
- `PlaybackBroadcaster`: Observes track changes and triggers song announcements.
- `OnlineListScraper`: Extracts usernames and levels from the Soul App online user drawer.
`InfoManager` serves as a clean, unified facade delegating to these state modules.

### Crash Recovery & macOS Network Bridge
- `@with_driver_recovery` wraps Appium UI operations, automatically recovering from transient connection drops.
- On macOS, an automated socket bridge circumvents Local Network access restrictions (`[Errno 65] No route to host`).
- `RecoveryManager` restarts the driver or app after repeated unrecoverable failures.

## Data Model

SQLite database at `data/soul_bot.db` managed via Tortoise ORM:
- **User Management**: `User` (with `canonical_user_id` alias mapping), `UserMemory` (dual-layer conversational memory).
- **Party & Seats**: `SeatReservation`.
- **Chat Automation**: `Keyword` (auto-replies), `EnterEvent`, `ExitEvent`, `ReturnEvent`, `ReceiveEvent`, `FocusEvent`.
- **Scheduling**: `Timer` (persisted scheduled commands).
- **Messaging**: `MessageInfo`.

## Extension Points

- **New Manager**: Create `src/ushareiplay/managers/<name>_manager.py` subclassing `Singleton`. Initialize lazily via `instance()`.
- **New State Component**: Add module under `src/ushareiplay/state/`, expose relevant accessors through `InfoManager`.
- **New Command**: Implement `BaseCommand` in `src/ushareiplay/commands/<name>.py`.
- **New Background Event**: Implement `BaseEvent` in `src/ushareiplay/events/`, register in `EventManager`.

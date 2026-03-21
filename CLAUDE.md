# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UShareIPlay is a Python-based Android automation framework that controls the **Soul App** (Chinese social platform) and **QQ Music** via Appium. It provides music playback management, room administration, and interactive features through a command-driven architecture.

## Environment Setup

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start Appium server (separate terminal)
./appium.sh
# or: appium --allow-insecure=adb_shell,chromedriver_autodownload

# Run the application
./run.sh
# or: python main.py
```

## Testing

```bash
python test_singleton.py
python test_chat_logger.py
```

No test framework (pytest/unittest runner) is configured — tests are run directly as scripts.

## Architecture

### Initialization Flow

```
main.py
  → ConfigLoader.load_config()        # Loads config.yaml
  → DatabaseManager.init()            # SQLite via Tortoise ORM
  → AppController.instance(config)    # Main singleton orchestrator
  → controller.start_monitoring()     # Main event loop
```

### Key Design Patterns

- **Singleton** — All managers and handlers use thread-safe singletons; never call constructors directly, always use `.instance()`
- **Manager Pattern** — Business logic split into 14+ specialized managers under `src/managers/`
- **Command Pattern** — 30+ commands under `src/commands/`, all inheriting from `BaseCommand`; commands are dynamically loaded by `CommandManager`
- **DAO Pattern** — Database access via DAOs in `src/dal/`; models in `src/models/` using Tortoise ORM

### Component Relationships

```
AppController
├── SoulHandler       — Soul App UI automation (chat reading, room control)
├── QQMusicHandler    — QQ Music app automation (641 lines, music operations)
├── CommandManager    — Parses and dispatches chat commands
├── EventManager      — Handles UI events (message tips, drawer, planet tab, etc.)
├── TimerManager      — Scheduled tasks persisted in DB
├── PartyManager      — Party/room lifecycle management
├── SeatManager       — Seat reservation, focus, validation sub-managers
├── MusicManager      — Playback control
├── MessageManager    — Async message queue and dispatch
└── [KeywordManager, TitleManager, ThemeManager, TopicManager, NoticeManager, InfoManager, UserManager, AdminManager]
```

### Adding a New Command

1. Create `src/commands/<name>_command.py` inheriting from `BaseCommand`
2. Implement `execute(self, params, context)` method
3. Add command config entry in `config.yaml` under the commands section
4. `CommandManager` auto-discovers commands via dynamic loading — no registration needed

### Configuration

`config.yaml` (26,000+ lines) is the master config containing:
- Android device and Appium server settings
- 100+ Soul App UI element XPath selectors
- 80+ QQ Music UI element XPath selectors
- 24+ scheduled timer definitions
- Command templates with response/error message templates

Element selectors and UI automation logic are tightly coupled to `config.yaml` — changes to the target apps require updating selectors here.

### Data Layer

- **Database**: SQLite at `data/` via Tortoise ORM with async/await
- **Models**: `User`, `SeatReservation`, `Keyword`, `MessageInfo`
- **DAOs**: `UserDAO`, `SeatReservationDAO`, `KeywordDAO`, `EnterDAO`, `ExitDAO`, `ReturnDAO`

### Crash Recovery

`AppHandler` (base class for `SoulHandler`/`QQMusicHandler`) implements automatic crash detection and app restart. `main.py` wraps the controller in a retry loop (up to 10 restarts).

## OpenSpec Workflow

This repo uses OpenSpec for structured change management:

```bash
# Propose a new change
/openspec-propose

# Explore/investigate before implementing
/openspec-explore

# Implement tasks from a change
/openspec-apply-change

# Archive after completion
/openspec-archive-change
```

Change specs live in `/openspec/`. Active changes are tracked there with tasks, design docs, and implementation notes.

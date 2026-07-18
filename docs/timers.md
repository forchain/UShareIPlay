---
covers: [TimerManager, TimerCommand, Timer, TimerDAO]
last-synced: 2026-03-23
---

## Overview

`TimerManager` runs an async loop that fires scheduled commands at specified times. Timers are persisted in SQLite so they survive restarts. Each timer injects a message into `MessageQueue` as if a user sent it, so any valid command can be scheduled.

## Components

| Component | Responsibility |
|---|---|
| `TimerManager` | Async timer loop; timer grammar/key allocation; loads/saves timers from DB; fires commands via `MessageQueue` |
| `TimerCommand` | Handles `:timer` user commands (add, remove, list, start, stop, reset, reload) |
| `Timer` (model) | ORM model mapping to `timer_events` table |
| `TimerDAO` | DB CRUD for `Timer` model |

## How It Works

**Startup**: `TimerManager.start()` loads all timers from DB. If DB is empty (first run after migration), it reads `timers.json` and migrates. Timer loop runs as an `asyncio.Task`.

**Firing**: Every tick, the loop checks each enabled timer's `next_trigger`. When `now >= next_trigger`, it pushes `timer.message` into `MessageQueue` with sender=`"Timer"` (a system user, bypasses level checks). For `repeat=True` timers, `next_trigger` advances to the next occurrence of `target_time`.

**Time format**:
- `HH:MM` / `HH:MM:SS` schedules for the next occurrence of that time (today or tomorrow).
- A pure number `N` schedules a one-shot timer delayed by `N` seconds (computed as `now + N seconds`).
`next_trigger` is a full datetime computed at add/load time and after each fire.

## Commands

| Prefix | Level | Params | Description |
|---|---|---|---|
| `timer` | 9 | `add <key?> <time> <command...> [repeat]` | Add a new timer (key optional) |
| `timer` | 9 | `remove <key>` | Delete a timer |
| `timer` | 9 | `list` | List all timers with next trigger time |
| `timer` | 9 | `start` | Start the timer loop |
| `timer` | 9 | `stop` | Stop the timer loop |
| `timer` | 9 | `reset` | Remove all timers |
| `timer` | 9 | `reload` | Reload timers from DB |

Examples:
- `:timer add morning 08:00 play 早安音乐`
- `:timer add 10 :play test` (fires once after 10 seconds)
- `:timer add 1 \":play test\" @Console` (quotes are used for whitespace grouping and will be stripped in the stored/output message)

## Data Model

| Field | Type | Description |
|---|---|---|
| `key` | CharField (unique) | Timer identifier |
| `message` | TextField | Command string to inject (e.g., `play 早安音乐`) |
| `target_time` | CharField | `HH:MM` schedule time |
| `repeat` | BooleanField | If true, reschedules after firing |
| `enabled` | BooleanField | Whether the timer is active |
| `next_trigger` | DatetimeField | Pre-computed next fire datetime (nullable) |

Table: `timer_events`

## Extension Points

- **One-shot timers**: Set `repeat=False` — timer fires once then is deleted from DB.
- **New timer commands**: Extend `TimerCommand.execute()` with new sub-commands.
- **Migration from JSON**: `TimerManager._migrate_from_json()` handles legacy `timers.json` automatically on first start.

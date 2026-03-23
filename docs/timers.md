---
covers: [TimerManager, TimerCommand, Timer, TimerDAO]
last-synced: 2026-03-23
---

## Overview

`TimerManager` runs an async loop that fires scheduled commands at specified times. Timers are persisted in SQLite so they survive restarts. Each timer injects a message into `MessageQueue` as if a user sent it, so any valid command can be scheduled.

## Components

| Component | Responsibility |
|---|---|
| `TimerManager` | Async timer loop; loads/saves timers from DB; fires commands via `MessageQueue` |
| `TimerCommand` | Handles `:timer` user commands (add, remove, list, enable/disable) |
| `Timer` (model) | ORM model mapping to `timer_events` table |
| `TimerDAO` | DB CRUD for `Timer` model |

## How It Works

**Startup**: `TimerManager.start()` loads all timers from DB. If DB is empty (first run after migration), it reads `timers.json` and migrates. Timer loop runs as an `asyncio.Task`.

**Firing**: Every tick, the loop checks each enabled timer's `next_trigger`. When `now >= next_trigger`, it pushes `timer.message` into `MessageQueue` with sender=`"Timer"` (a system user, bypasses level checks). For `repeat=True` timers, `next_trigger` advances to the next occurrence of `target_time`.

**Time format**: `target_time` is stored as `HH:MM` (24-hour). `next_trigger` is a full datetime computed at load time and after each fire.

## Commands

| Prefix | Level | Params | Description |
|---|---|---|---|
| `timer` | 9 | `add <key> <HH:MM> <command>` | Add a new timer |
| `timer` | 9 | `remove <key>` | Delete a timer |
| `timer` | 9 | `list` | List all timers with next trigger time |
| `timer` | 9 | `enable/disable <key>` | Toggle a timer without deleting it |

Example: `:timer add morning 08:00 play 早安音乐`

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

- **One-shot timers**: Set `repeat=False` — timer fires once then stays in DB with `enabled=False`.
- **New timer commands**: Extend `TimerCommand.execute()` with new sub-commands.
- **Migration from JSON**: `TimerManager._migrate_from_json()` handles legacy `timers.json` automatically on first start.

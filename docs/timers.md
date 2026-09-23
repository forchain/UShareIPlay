---
covers: [TimerManager, TimerCommand, Timer, TimerDAO]
last-synced: 2026-09-23
---

## Overview

`TimerManager` runs an asynchronous scheduling loop that executes scheduled commands at designated times. Timers are persisted in SQLite (`timer_events` table) so they survive process restarts. Each fired timer injects its command into `MessageQueue` with sender `"Timer"` (a system user that bypasses standard user level checks).

## Components

| Component | Responsibility |
|---|---|
| `TimerManager` | Async timer loop; key allocation; DB persistence; queue injection |
| `TimerCommand` | Handles `:timer` commands (add, remove, list, enable, disable, start, stop, reset, reload) |
| `Timer` (model) | Tortoise ORM model mapping to `timer_events` table |
| `TimerDAO` | Database CRUD operations for `Timer` |

## How It Works

### Startup & Persistence
`TimerManager.start()` loads all stored timers from SQLite. The timer loop runs as a persistent background `asyncio.Task`.

### Firing Logic
Every tick, the loop checks enabled timers whose `next_trigger` has arrived (`now >= next_trigger`):
1. Expands queue grammar:
   - Semicolon `;` chained commands (executed sequentially).
   - `{user_name}` template expansion.
   - Preserves silent prefixes (`/`, `／`) and private-reply prefixes (`$`, `＄`).
2. Injects the message into `MessageQueue` with sender=`"Timer"`.
3. If `repeat=True`, calculates the next trigger time; otherwise, removes or disables the one-shot timer.

### Schedule Formats
- **Clock Time**: `HH:MM` or `HH:MM:SS` (schedules for the next calendar occurrence, today or tomorrow).
- **Delay Seconds**: A pure number `N` (fires once after `N` seconds from now, computed as `now + N seconds`).

## Commands

| Prefix | Level | Params | Description |
|---|---|---|---|
| `timer` | 9 | `add <key?> <time> <command...> [repeat]` | Add a scheduled timer (key optional; time in seconds or HH:MM) |
| `timer` | 9 | `remove <key>` | Delete a timer by key |
| `timer` | 9 | `list` | List all active timers with next trigger times |
| `timer` | 9 | `enable <key>` | Enable a previously disabled timer |
| `timer` | 9 | `disable <key>` | Disable a timer without deleting it |
| `timer` | 9 | `start` | Start the timer loop if paused |
| `timer` | 9 | `stop` | Pause the timer loop |
| `timer` | 9 | `reset` | Remove all timers from database |
| `timer` | 9 | `reload` | Reload timers from database into memory |

### Examples
- `:timer add morning 08:00 :play 早安音乐` (Daily repeating morning music at 08:00)
- `:timer add 10 :say 10秒提醒` (One-shot command delay after 10 seconds)
- `:timer add 30 ":play 稻香; :say 欢迎收听" false` (Multi-command chain after 30 seconds)
- Quotes group arguments containing spaces and are stripped during storage.

## Data Model

| Field | Type | Description |
|---|---|---|
| `key` | CharField (unique) | Unique timer identifier |
| `message` | TextField | Command string to execute (e.g. `:play 晴天`) |
| `target_time` | CharField | `HH:MM` or numeric delay string |
| `repeat` | BooleanField | Whether to repeat on schedule |
| `enabled` | BooleanField | Active status flag |
| `next_trigger` | DatetimeField | Computed next fire timestamp |

Table: `timer_events`

## Extension Points

- **One-shot Timers**: Created with `repeat=False`; automatically cleaned up after firing.
- **Queue Grammar Extensions**: Modify `expand_queue_text()` in `src/ushareiplay/core/chat_intake.py` to support new template parameters or token replacement rules.

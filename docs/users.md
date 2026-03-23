---
covers: [UserManager, AdminManager, MessageManager, KeywordManager, UserDAO, EnterDAO, ExitDAO, ReturnDAO, AdminCommand, HelloCommand, SayCommand, KeywordCommand, EnterCommand, ExitCommand, ReturnCommand, GiftCommand]
last-synced: 2026-03-23
---

## Overview

User management handles identity, permission levels, automated greetings, keyword-triggered responses, and enter/exit/return event tracking. `UserManager` is the central authority for user levels. `MessageManager` dispatches outbound messages and processes inbound events.

## Components

| Component | Responsibility |
|---|---|
| `UserManager` | User lookup, level assignment, persistence via `UserDAO` |
| `AdminManager` | Toggles admin role for users in the Soul App room UI |
| `MessageManager` | Async outbound message queue; processes follower notifications and greetings |
| `KeywordManager` | Maps trigger keywords → response messages (stored in DB) |
| `UserDAO` | CRUD for `User` model |
| `EnterDAO` / `ExitDAO` / `ReturnDAO` | Record enter/exit/return events for tracking |

## How It Works

**User levels** control command access. Level is stored in the `User` DB table. System users (`Timer`, `Console`) bypass level checks. Default level for unknown users is 0.

```
Level  Role
  0    Guest (play-only commands)
  1    Regular user
  2    Trusted user
  3    VIP
  4    Moderator
  5    Sub-admin
  9    Owner / system
```

**Greeting flow**: When a follower enters the room, `MessageManager` detects the follower notification event → checks if a `:hello` rule exists for that user → sends greeting message and optionally plays a song.

**Keyword responses**: `:keyword add <trigger> <response>` stores a mapping in `Keyword` table. When any chat message contains the trigger, the system auto-replies.

**Enter/exit/return tracking**: `EnterDAO`, `ExitDAO`, `ReturnDAO` record timestamped events. Used by `:info` to report activity.

## Commands

| Prefix | Level | Params | Description |
|---|---|---|---|
| `admin` | 9 | `1/0 <user>` | Grant (1) or revoke (0) admin role in room UI |
| `hello` | 1 | `<user> "<msg>" "<song>"` | Set greeting rule for a user |
| `say` | 1 | `<message>` | Post a message to room chat |
| `keyword` | 1 | `add/del/list <trigger> [response]` | Manage keyword auto-reply rules |
| `enter` | 1 | `<user> <message>` | Set custom enter message for a user |
| `exit` | 1 | `<user> <message>` | Set custom exit message for a user |
| `return` | 1 | `<user> <message>` | Set custom return message for a user |
| `gift` | 5 | `<user>` | Send a gift to a user; falls back to yellow duck if backpack empty |

## Data Model

| Model | Table | Key Fields |
|---|---|---|
| `User` | `users` | `username`, `level`, `created_at` |
| `Keyword` | `keywords` | `trigger`, `response` |
| `EnterEvent` | `enter_events` | `username`, `timestamp` |
| `ExitEvent` | `exit_events` | `username`, `timestamp` |
| `ReturnEvent` | `return_events` | `username`, `timestamp` |

## Extension Points

- **New user level**: Update level constants in `UserManager` and `BaseCommand.check_level()`.
- **New event type**: Add model + DAO under `src/models/` and `src/dal/`, register in `db_manager.py` Tortoise config.
- **New keyword action**: Extend `KeywordManager.handle()` with additional action types beyond plain text reply.

---
covers: [PartyManager, SoulHandler, ThemeManager, TitleManager, TopicManager, NoticeManager, SeatManager, MicManager, ThemeCommand, TitleCommand, TopicCommand, NoticeCommand, SeatCommand, EndCommand, RoomCommand, PackCommand, MicCommand]
last-synced: 2026-03-23
---

## Overview

Room management covers the Soul App party room lifecycle: creation, restart, UI customisation (theme, title, topic, notice), seat management, and microphone control. `SoulHandler` owns all Soul App UI automation; the various managers hold state and cooldowns.

## Components

| Component | Responsibility |
|---|---|
| `PartyManager` | Party lifecycle: creation, auto-restart after `party_restart_minutes`, state tracking |
| `SoulHandler` | All Soul App UI automation (chat reading, room navigation, UI actions) |
| `ThemeManager` | Room theme — persists value, combines with title for full room name |
| `TitleManager` | Room title — persists value, enforces cooldown to avoid rate-limiting |
| `TopicManager` | Study-room topic display |
| `NoticeManager` | Room announcement text |
| `SeatManager` | Seat reservation + seating sub-managers (see users.md) |
| `MicManager` | Microphone on/off automation |

## How It Works

**Room name** = `{theme} {title}` — `ThemeManager` and `TitleManager` each own one half and write the combined value to the UI when either changes.

**Auto-restart**: `PartyManager` tracks `init_time`. When elapsed time exceeds `soul.party_restart_minutes` (default 720 min / 12 h) AND only the owner is in the room, it closes and recreates the party to avoid Soul App's 24-hour forced closure.

**Seat flow**: A user requests a seat → `SeatManager` validates level + reservation → `SeatManager.seating` performs UI actions to put the user on the specified seat number.

**Pack opening**: `:pack` is auto-triggered when the online user count reaches ≥ 5; can also be called manually. It opens the backpack UI and uses the first available luck pack.

## Commands

| Prefix | Level | Params | Description |
|---|---|---|---|
| `theme` | 3 | `<text>` | Set room theme (max 2 chars); combined with title |
| `title` | 3 | `<text>` | Set room title |
| `topic` | 1 | `<text>` | Set study-room topic |
| `notice` | 1 | `<message>` | Set room announcement |
| `seat` | 1 | `1 <n> / 2 <n>` | Reserve (1) or immediately take (2) seat number n |
| `mic` | 2 | `0/1` | Turn microphone off (0) or on (1) |
| `pack` | 1 | — | Open luck pack from backpack |
| `end` | 4 | — | Close the party (requires owner's friend present) |
| `room` | 4 | `<party_id>` | Switch to a different party room |

## Data Model

| Model | Table | Key Fields |
|---|---|---|
| `SeatReservation` | `seat_reservations` | `user_id`, `seat_number`, `reserved_at` |

## Extension Points

- **New room UI action**: Add method to `SoulHandler`, call from appropriate manager or command.
- **Change restart threshold**: Update `soul.party_restart_minutes` in `config.yaml` (or `config.local.yaml`).
- **New seat rule**: Extend `SeatManager.seat_check` submodule.

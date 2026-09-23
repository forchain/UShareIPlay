---
covers: [PartyManager, SoulHandler, RoomNameManager, TopicManager, NoticeManager, SeatManager, MicManager, RecommendationManager, SleepManager, RoomInfoAuditor, ThemeCommand, TitleCommand, TopicCommand, NoticeCommand, SeatCommand, EndCommand, RoomCommand, PackCommand, MicCommand, RecommendCommand, SleepCommand]
last-synced: 2026-09-23
---

## Overview

Room management covers the Soul App party room lifecycle: room creation, auto-restart, UI customisation (theme, title, topic, notice), seat management, recommendation distribution, Sleep Guardian, and microphone control. `SoulHandler` owns low-level Soul App UI automation; managers hold domain state and cooldowns.

## Components

| Component | Responsibility |
|---|---|
| `PartyManager` | Party lifecycle: creation, auto-restart after `party_restart_minutes`, state tracking |
| `SoulHandler` | All Soul App UI automation (chat reading, room navigation, UI actions) |
| `RoomNameManager` | Room name invariant: `{theme}｜{title}`, shared cooldown, single UI write, notice restore |
| `TopicManager` | Study-room topic display |
| `NoticeManager` | Room announcement text |
| `SeatManager` | Seat reservation + seating sub-managers |
| `MicManager` | Microphone on/off automation and off-seat preparation |
| `RecommendationManager` | Room recommendation state tracking, drawer automation, and toggle (:recommend) |
| `SleepManager` | Sleep Guardian: blocks unprivileged automated commands during night hours (23:00 - 06:00) |
| `RoomInfoAuditor` | Periodic background auditor validating room information and title state |

## How It Works

### Room Name & Cooldowns
**Room name** = `{theme}｜{title}` — `RoomNameManager` owns the combined value, the shared cooldown, pending state, and the single UI write. legacy `ThemeManager` and `TitleManager` adapters have been consolidated into `RoomNameManager`.

### Auto-Restart
`PartyManager` tracks `init_time`. When elapsed time exceeds `soul.party_restart_minutes` (default 720 min / 12 h) AND only the owner is in the room, it closes and recreates the party to avoid Soul App's 24-hour forced closure.

### Seat & Mic Flow
- **Seat**: `:seat 1 <n>` reserves seat `n`; `:seat 2 <n>` seats user immediately; `:seat 4 [n]` vacates the occupant.
- **Mic**: `:mic 1` (or `:mic` when off-seat) automatically calls `SoulHandler.ensure_on_seat()` to claim a seat before unmuting. `:mic 0` mutes without leaving the seat.

### Recommendation Distribution
Soul App periodically surfaces party recommendation popups or toggles in room settings. `RecommendationManager` controls the recommendation state, handles the drawer UI safely, and allows operators to toggle distribution via `:recommend on` / `:recommend off`.

### Sleep Guardian
`SleepManager` prevents automated command floods during rest hours (default 23:00 to 06:00).
- Unprivileged users and background timers are blocked.
- Human operators (Owner, Console, Admin) and explicit `@我` conversational interactions bypass sleep restrictions.
- Can be controlled via `:sleep on`, `:sleep off`, or `:sleep status`.

### Guest Mode & Host Adoption
- When the current party ID differs from `soul.default_party_id`, the bot enters guest room mode (`RoomState.is_guest_room`), restricting commands strictly to music playback and disabling all administrative/seat/title commands.
- If room ownership is transferred to the bot, `RoomState.adopt_host_room()` safely switches to host mode without closing or leaving the party.

## Commands

| Prefix | Level | Params | Description |
|---|---|---|---|
| `theme` | 3 | `<text>` | Set room theme (max 2 chars); combined with title |
| `title` | 3 | `<text>` | Set room title |
| `topic` | 1 | `<text>` | Set study-room topic |
| `notice` | 1 | `<message>` | Set room announcement |
| `seat` | 1 | `1 <n> / 2 <n> / 4 [n]` | Reserve (1), immediately take (2), or remove seat occupant (4) |
| `mic` | 2 | `0/1` | Turn microphone off (0) or on (1); seats bot first if off-seat |
| `pack` | 1 | — | Open luck pack from backpack (auto-triggered at ≥ 5 online users) |
| `recommend`| 1 | `[on/off]` | Turn room recommendation distribution on or off |
| `sleep` | 4 | `on/off/status` | Manage Sleep Guardian night rest mode (overrides 23:00 - 06:00 window) |
| `end` | 4 | — | Close party (requires owner's friend present) |
| `room` | 4 | `<party_id>` | Switch to a different party room (verifies target room is open before switching) |

## Data Model

| Model | Table | Key Fields |
|---|---|---|
| `SeatReservation` | `seat_reservations` | `user_id`, `seat_number`, `reserved_at` |

## Extension Points

- **New room UI action**: Add method to `SoulHandler`, expose through the appropriate domain manager.
- **Sleep schedule customization**: Adjust sleep window or exempted commands in `config.yaml` under `sleep`.
- **Auditor rules**: Register new room sanity checks in `RoomInfoAuditor`.

---
covers: [PartyManager, SoulHandler, RoomProfileManager, SeatManager, MicManager, SleepManager, ThemeCommand, TitleCommand, TopicCommand, NoticeCommand, SeatCommand, EndCommand, RoomCommand, PackCommand, MicCommand, RecommendCommand, SleepCommand]
last-synced: 2026-09-23
---

## Overview

Room management covers the Soul App party room lifecycle: room creation, auto-restart, UI customisation (theme, title, topic, notice), seat management, recommendation distribution, Sleep Guardian, and microphone control. `SoulHandler` owns low-level Soul App UI automation; managers hold domain state and cooldowns.

## Components

| Component | Responsibility |
|---|---|
| `PartyManager` | Party lifecycle: creation, auto-restart after `party_restart_minutes`, state tracking |
| `SoulHandler` | All Soul App UI automation (chat reading, room navigation, UI actions) |
| `RoomProfileManager` | Sole owner of the room drawer session and its field groups (room name / topic / notice / party type) plus recommendation state; owns the `{theme}｜{title}` invariant, the 5-minute topic, 15-minute notice and shared 10-minute room-name cooldowns, every drawer write, the batched audit, and the notice restore after a title change. Recommendation reads/writes go through a separate party-settings driver (#456) |
| `SeatManager` | Seat reservation + seating sub-managers |
| `MicManager` | Microphone on/off automation and off-seat preparation |
| `SleepManager` | Sleep Guardian: blocks unprivileged automated commands during night hours (23:00 - 06:00) |

## How It Works

### Room Name & Cooldowns
**Room name** = `{theme}｜{title}` — `RoomProfileManager` owns the combined value, the shared 10-minute cooldown, pending state, and the single UI write. The legacy `ThemeManager`, `TitleManager`, `TopicManager`, `NoticeManager` and `RoomNameManager` adapters have all been consolidated into it; `:title` and `:theme` are thin adapters at the seam. `RoomInfoWindow` was a transient facade over the same drawer session and has since been deleted (#394) — `RoomProfileManager` is the only owner.

### Auto-Restart
`PartyManager` tracks `init_time`. When elapsed time exceeds `soul.party_restart_minutes` (default 720 min / 12 h) AND only the owner is in the room, it closes and recreates the party to avoid Soul App's 24-hour forced closure.

### Seat & Mic Flow
- **Seat**: `:seat 1 <n>` reserves seat `n`; `:seat 2 <n>` seats user immediately; `:seat 4 [n]` vacates the occupant.
- **Mic**: `:mic 1` (or `:mic` when off-seat) automatically calls `SoulHandler.ensure_on_seat()` to claim a seat before unmuting. `:mic 0` mutes without leaving the seat.

### Recommendation Distribution
Soul moved the recommendation toggle out of the room-info drawer and into the **party settings panel** (`partySettingBtn`). `RoomProfileManager` still owns the state (`RoomState.recommendation_enabled`), but reads and writes it through `SoulPartySettingsDriver`: open the panel, scroll (with a bounded swipe limit) to the recommendation row, read its text (`所有人` / `关闭推荐分发`), and only when the state differs click the row and then the target option. The manager closes only panels it opened; a panel already open is left for the caller. `:recommend` with no argument toggles, and accepts `on`/`off` plus the UI's own wording (`开启`/`关闭`, `所有人`/`关闭推荐分发`). The legacy `RecommendationManager` was folded into `RoomProfileManager` in #393; #456 moved its UI to the settings panel.

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
| `recommend`| 1 | `[on/off]` | Toggle room recommendation distribution (no argument toggles; also accepts `开启`/`关闭`, `所有人`/`关闭推荐分发`) |
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
- **Auditor rules**: Register new room sanity checks in `RoomProfileManager.audit_and_repair()`.

# Spec: Room Info Window Audit & Sync Pipeline (`RoomInfoWindowAuditor`)

## Problem Statement

When UShareIPlay automates Soul App party rooms, multiple managers and commands (`PartyManager` during creation/recovery, `RoomNameManager` during theme/title updates, `NoticeManager` during notice updates, `RecommendationManager` during recommendation checks, and the `:info` command) interact with the Room Info Window (opened by clicking the room header bar `tvStudyRoomTitle`).

Previously, attribute checks were performed in isolation or skipped, resulting in:
1. Uncorrected room type drift (e.g. room defaulting to "闲聊唠嗑" instead of "唱歌听歌").
2. Potential UI interaction conflicts when multiple room attributes required updates in a single window opening.
3. Inconsistent memory state synchronization when the Room Info Window was opened passively by another operation.
4. The risk of lingering overlay dialogs blocking subsequent chat message polling and automation if an error occurred during dialog interaction.

## Solution

Introduce a unified **Room Info Window Auditor (`RoomInfoWindowAuditor`)** and **Safe Exit Guard**.

Whenever the Room Info Window is opened—whether actively (e.g. during room creation, `:info` command, or periodic check) or passively (e.g. while updating room title/theme or notice)—the auditor executes a single-pass, non-conflicting audit and synchronization across all four Room Info Window attributes:

1. **`type` (房间类型)**: Inspect `party_room_type_option` (`tv_type`). If "闲聊唠嗑", click to switch to "唱歌听歌" (returns to Room Info Window automatically).
2. **`recommendation` (派对推荐分发)**: Inspect `party_recommendation_status` (`tv_private_title`). If `RoomState.recommendation_enabled` is uninitialized (`None`), sync state from UI; if target recommendation config is specified and UI differs, update UI option.
3. **`theme & title` (主题与标题)**: Inspect UI text `{theme}｜{title}` against `RoomNameManager`. If a pending update exists and cooldown allows (`can_update_now()`), update UI; if in the 10-minute cooldown period, sync memory state (`current_theme`, `current_title`) from the actual UI text.
4. **`notice` (派对公告)**: Inspect notice text via `edit_notice_entry`. If UI notice matches system reset defaults (e.g. "Souler们在随便聊聊ing"), re-write the default custom notice; otherwise sync `current_notice` in memory.
5. **Safe Exit Guard**: At the end of any audit or upon error, `ensure_room_info_window_closed()` checks for open dialog indicators (`party_room_type_option`, `party_recommendation_status`, `edit_topic_entry`, `edit_notice_entry`) and presses back until the Room Info Window is completely closed and the main room screen is restored.

## User Stories

1. As a party room host bot, I want the room type to automatically be set to "唱歌听歌" during party creation, so that the room is correctly categorized in Soul App.
2. As a party room host bot, I want to automatically correct the room type from "闲聊唠嗑" to "唱歌听歌" whenever the Room Info Window is opened, so that room type drift is fixed without extra manual steps.
3. As a bot administrator executing the `:info` command, I want uninitialized recommendation status to be inspected from the UI and synced to memory while automatically correcting any room type drift in the same window opening, so that status reports are accurate and room settings stay compliant.
4. As a bot administrator updating the room theme or title, I want the system to passively inspect and correct room type, recommendation, and notice while the Room Info Window is open, so that all attributes are audited without opening extra dialogs.
5. As a bot administrator updating the room notice, I want any system-reset default notice text to be detected and restored to custom notice text, so that room announcements remain consistent.
6. As a party room bot owner, I want the theme and title displayed on UI (`{theme}｜{title}`) to be synced back to memory when in cooldown, so that the bot's internal state accurately reflects the room's current appearance.
7. As a party room bot owner, I want the Room Info Window to always be safely closed after all attribute audits and fixes finish (even if an error occurs), so that overlay dialogs never block chat message polling or subsequent automation.

## Implementation Decisions

### Domain Glossary & Vocabulary Alignment
- **`theme` (主题)**: Room theme prefix e.g. "听歌".
- **`title` (标题)**: Room main title e.g. "玫瑰暮色".
- **`topic` (话题)**: Blackboard topic UI element (independent green blackboard panel, managed by `TopicManager`, separate from Room Info Window).
- **`notice` (派对公告)**: Party announcement managed by `NoticeManager`.
- **`type` (房间类型)**: Room category managed by `PartyManager` (`party_room_type_option` / `tv_type`).
- **`recommendation` (派对推荐分发)**: Recommendation distribution status managed by `RecommendationManager` (`party_recommendation_status` / `tv_private_title`).

### Module Interfaces & Control Flow
- **`PartyManager`**:
  - `check_and_correct_room_type(auto_close: bool = True) -> dict`: Active room type check and correction.
  - `sync_and_correct_room_type_if_dialog_open() -> dict`: Passive room type check when Room Info Window is already open.
  - `ensure_room_info_window_closed() -> None`: Safe Exit Guard. Inspects `party_room_type_option`, `party_recommendation_status`, `edit_topic_entry`, `edit_notice_entry` and presses back until window is closed.
- **`RoomInfoWindowAuditor`**:
  - `audit_and_sync_all(auto_close: bool = True) -> dict`: Single-pass pipeline running type correction, recommendation sync/update, theme/title sync/update (handling 10-minute cooldown), and notice sync/update.
  - `open_room_info_window()`: Context manager wrapping window open, audit execution, and safe exit guard closure.
- **Hooks**:
  - Hook passive audit into `RoomNameManager._update_title_ui`, `NoticeManager._set_notice_ui`, `RecommendationManager.sync_ui_status_if_dialog_open`, and `:info` command active sync.

## Testing Decisions

### Good Test Principles
- Test external behavior (correct UI clicks, memory state updates, safe window closure), not internal implementation details.

### Test Coverage & Seams
- **Seam**: Unit test `PartyManager` and `RoomInfoWindowAuditor` with mocked `element_finder`, `key_actions`, and `config`.
- **Test Cases**:
  1. Room creation flow switches room type from "闲聊唠嗑" to "唱歌听歌".
  2. In-room active type correction switches "闲聊唠嗑" to "唱歌听歌" and closes window cleanly.
  3. Passive type correction runs when window is open for another operation without auto-closing prematurely.
  4. Theme and title sync handles 10-minute cooldown (syncs memory when in cooldown, updates UI when allowed).
  5. Notice sync detects system reset defaults and restores custom notice.
  6. Safe Exit Guard closes window when any dialog element (`party_room_type_option`, `party_recommendation_status`, `edit_topic_entry`, `edit_notice_entry`) is visible.

## Out of Scope

- Modifying the blackboard `topic` UI panel (managed independently by `TopicManager`).
- Automating screens outside of Soul App party rooms.

## Further Notes

All 418 unit tests in the test suite continue to pass cleanly.

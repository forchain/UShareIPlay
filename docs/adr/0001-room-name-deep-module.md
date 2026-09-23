# Room name is owned by one deep module

The Soul App party room name is the single invariant `{theme}｜{title}`, shared cooldown, pending UI state, and notice restoration. Previously these responsibilities were split across `ThemeManager`, `TitleManager`, `NoticeManager`, and the theme/title commands, which duplicated the cooldown/pending orchestration and leaked retry state. We decided to concentrate all room-name behavior in `RoomNameManager`, with the commands as adapters at the seam.

This gives us one place to reason about the room-name transition, one interface-level test surface, and lets commands stay thin.

## Status (2026-07)

The `ThemeManager` and `TitleManager` legacy adapters were deleted; all callers now use `RoomNameManager.instance()` directly. Future architecture reviews should not re-suggest reintroducing the adapters.

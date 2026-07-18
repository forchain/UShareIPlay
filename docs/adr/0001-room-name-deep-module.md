# Room name is owned by one deep module

The Soul App party room name is the single invariant `{theme}｜{title}`, shared cooldown, pending UI state, and notice restoration. Previously these responsibilities were split across `ThemeManager`, `TitleManager`, `NoticeManager`, and the theme/title commands, which duplicated the cooldown/pending orchestration and leaked retry state. We decided to concentrate all room-name behavior in `RoomNameManager`, with `ThemeManager` and `TitleManager` kept as thin legacy adapters and the commands as adapters at the seam.

This gives us one place to reason about the room-name transition, one interface-level test surface, and lets commands stay thin. The trade-off is that `ThemeManager`/`TitleManager` remain as adapters for existing callers (music commands, events, tests) rather than being removed outright; they delegate to `RoomNameManager` and carry no behavior of their own.

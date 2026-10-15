# Room name is owned by one deep module

The Soul App party room name is the single invariant `{theme}｜{title}`, shared cooldown, pending UI state, and notice restoration. Previously these responsibilities were split across `ThemeManager`, `TitleManager`, `NoticeManager`, and the theme/title commands, which duplicated the cooldown/pending orchestration and leaked retry state. We decided to concentrate all room-name behavior in `RoomNameManager`, with the commands as adapters at the seam.

This gives us one place to reason about the room-name transition, one interface-level test surface, and lets commands stay thin.

## Status (2026-07)

The `ThemeManager` and `TitleManager` legacy adapters were deleted; all callers now use `RoomNameManager.instance()` directly. Future architecture reviews should not re-suggest reintroducing the adapters.

## Status (2026-10, #387/#392)

The decision above still holds unchanged — one deep module owns the `{theme}｜{title}` invariant, the shared cooldown, the pending UI state and notice restoration, with the commands as thin adapters. What changed is the module's name: `RoomNameManager` was absorbed into `RoomProfileManager` as part of the room-profile vertical (#392), which also took over topic, notice, party type and recommendation. The same review guidance applies one level up — do not re-suggest splitting the invariant back out across per-field adapters.

## Status (2026-10, #413 后续修复)

本 ADR 的核心不变量成立至今：一个深模块拥有 `{theme}｜{title}`、共享冷却、待写入状态
与公告恢复，命令只是薄适配器。需要补一笔的是「共享冷却」这个词被读成了「字段之间毫无
关系」：#413 停用抽屉推荐读写时，把档案接地（`ensure_synced_on_return` ->
`initialize_from_ui`）的生产接线一起清掉了，并且三个字段各记各的预算，忽略了这个抽屉
在服务端是**一块限速表面**。两者的处理见 ADR-0011：接地是生产契约；`can_apply_now`
（字段预算）与 `can_start_write`（字段预算 + 抽屉表面 60 秒安静）是两个问题，分开答。

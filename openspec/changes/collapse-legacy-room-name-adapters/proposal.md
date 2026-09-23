## Context

UShareIPlay's room-name behavior — the combined `{theme}｜{title}` Soul App party room name, shared cooldown, pending theme/title state, single UI write, and notice restoration — was previously scattered across `ThemeManager`, `TitleManager`, `NoticeManager`, and the theme/title commands. Recent architecture work (`docs/adr/0001-room-name-deep-module.md`) concentrated all behavior in `RoomNameManager`, leaving `ThemeManager` and `TitleManager` as thin legacy adapters for existing callers.

The adapters now exist only to forward calls. Their docstrings explicitly state: *"All behavior now lives in `RoomNameManager`. New code should use `RoomNameManager.instance()` directly."* They add no behavior, no invariants, and no test coverage that `RoomNameManager` lacks.

This is a shallow-module problem that the deletion test exposes directly: deleting the adapters concentrates complexity in the deep module rather than scattering it. Understanding the room-name transition currently requires tracing three files; it should require one.

## Goals / Non-Goals

**Goals:**
- Migrate every external caller of `ThemeManager` and `TitleManager` to use `RoomNameManager.instance()` directly
- Delete `ThemeManager` and `TitleManager` modules
- Remove their initialization calls from `AppController._init_handlers`
- Confirm all existing tests pass against `RoomNameManager` (the deep module) without modification
- Reopen ADR-0001 to drop the legacy-adapter rationale

**Non-Goals:**
- Do not redesign the `RoomNameManager` interface — it already exposes everything callers need
- Do not change room-name behavior or test coverage
- Do not touch `NoticeManager` — it sits outside the adapter layer
- Do not introduce new abstractions or seams — the deep module is already the right shape

## Decisions

### 决策 1: Migrate callers in-place, then delete the adapter modules

**选择**: Update each external caller to import and use `RoomNameManager` directly, then delete `theme_manager.py` and `title_manager.py` in the same change.

**理由**:
- The adapters carry no behavior, so the migration is mechanical and reversible per file
- Splitting "migrate" and "delete" into two changes leaves a window where the adapters still exist but are unused, inviting accidental reintroduction
- One change preserves the seam (or absence thereof) at exactly one moment in history

**Call sites to migrate**:
- `AppController._init_handlers` — remove `ThemeManager.initialize()` and `TitleManager.initialize()` (already duplicated by `RoomNameManager.initialize()`)
- `BaseCommand` — replace lazy `theme_manager` / `title_manager` properties with a `room_name_manager` property
- `events/chat_room_title.py` — replace `TitleManager.instance().get_next_title()` with `RoomNameManager.instance().get_next_title()`
- `events/party_name_violation_later.py` — replace `TitleManager.instance().set_next_title(...)` with `RoomNameManager.instance().set_next_title(...)`

### 决策 2: Update tests to import `RoomNameManager` directly

**选择**: Update test files that reference `ThemeManager` / `TitleManager` to use `RoomNameManager.instance()` and reset its singleton state between tests.

**理由**:
- Tests should exercise the deep module — the public surface — not the adapter
- Existing `test_room_name_manager.py` already covers the deep module's behavior
- Test fixtures that reset `RoomNameManager` state work for all migrated call sites without per-adapter reset logic

### 决策 3: Reopen ADR-0001

**选择**: Update `docs/adr/0001-room-name-deep-module.md` to remove the paragraph that preserves `ThemeManager` / `TitleManager` as legacy adapters, and add a note recording when and why they were removed.

**理由**:
- The ADR's current rationale ("migration convenience") is now stale
- A future architecture review should not re-suggest the same deletion
- The ADR is the right place to record "we deliberately removed these, do not reintroduce"

## Risks & Mitigations

**Risk**: A caller uses an attribute on the adapter that `RoomNameManager` does not expose.
**Mitigation**: Grep all call sites before deletion. The adapters are pure passthroughs, so attribute exposure is mechanical. Run the full test suite after migration.

**Risk**: Singleton state isolation breaks in tests if multiple adapters previously reset state independently.
**Mitigation**: `RoomNameManager` already owns all the relevant state. Tests that previously reset `ThemeManager` / `TitleManager` should reset `RoomNameManager`.

**Risk**: Initialization order changes break module import side effects.
**Mitigation**: `RoomNameManager.initialize()` already happens during `AppController._init_handlers`; removing the adapter `initialize()` calls simply removes a redundant no-op.

## Testing Decisions

**What makes a good test for this change:**
- Test external behavior of migrated call sites, not the migration itself
- Verify `RoomNameManager` is the single point of state for theme/title
- Verify no test relies on adapter-specific attribute exposure

**Modules to test:**
- `RoomNameManager` (existing coverage in `tests/test_room_name_manager.py`)
- `AppController` initialization (existing coverage in `tests/test_app_controller*.py`)
- `BaseCommand` lazy manager loading (existing coverage)
- Events (`chat_room_title`, `party_name_violation_later`) — existing coverage in their respective test files

**Prior art:**
- `tests/test_room_name_manager.py` exercises the deep module's public surface directly
- `tests/test_chat_room_title_runtime_context.py` and `tests/test_party_name_violation_later.py` exercise the event handlers that will be migrated

## Out of Scope

- Refactoring `RoomNameManager`'s internal structure
- Removing `NoticeManager` (different concern)
- Renaming `RoomNameManager` (its name already encodes the domain concept of "the room-name")
- Adding new tests for behavior that doesn't exist today
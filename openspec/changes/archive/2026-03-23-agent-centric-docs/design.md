## Context

The project has one developer and an AI agent as primary doc consumer. Current `docs/` contains 9 ad-hoc files: mix of design decisions, fix summaries, and how-to notes — all in Chinese, inconsistent structure, no metadata. `README.md` is 769 lines of English prose with outdated config examples (e.g., `initial_timers` in YAML, which was migrated to DB). `openspec/specs/` is empty because no archive has ever run the sync step.

The agent reads docs when: (a) exploring the project before a change, (b) implementing a task that touches a known capability, (c) archive-time to check what needs updating. All three cases benefit from flat, structured, metadata-indexed files over prose.

## Goals / Non-Goals

**Goals:**
- 6 flat capability docs in `docs/` with consistent section structure and `covers:` frontmatter
- README rebuilt as a concise index: overview + quick start + command table + links to docs
- `openspec/specs/` populated from 3 archived changes
- Archive skill extended to check README + relevant docs after spec-sync

**Non-Goals:**
- Generating docs from code automatically (fragile, out of scope)
- Human-facing tutorial or onboarding docs (the user won't maintain these)
- Translating historical dev notes (just delete them)

## Decisions

### Flat docs/ structure (no subdirectories)

**Choice**: `docs/*.md` — 6 files directly in `docs/`
**Why**: Agent needs one glob (`docs/*.md`) to load all reference docs. Subdirectory structure adds navigation overhead with no benefit at this scale. 6 files is small enough to be scanned entirely.

### Capability grouping (coarse)

| File | Covers |
|---|---|
| `music.md` | QQMusicHandler, MusicManager, play/fav/skip/next/pause/vol/mode/acc/ktv/lyrics/singer/album/playlist/radio commands |
| `room.md` | PartyManager, SoulHandler (room ops), theme/title/topic/notice/end/room/seat/pack commands |
| `users.md` | UserManager, AdminManager, SeatManager + sub-managers, admin/enter/exit/return/say/hello/keyword commands |
| `timers.md` | TimerManager, TimerCommand, Timer model, TimerDAO |
| `config.md` | ConfigLoader, config.yaml structure, config.local.yaml override system |
| `system.md` | AppController, AppHandler, CommandManager, EventManager, MessageManager, crash recovery, DB layer, singleton pattern |

**Why coarse**: Agent identifies relevant file by topic, then reads the whole file. Fine-grained files would require more round-trips. 6 files maps to how the agent naturally thinks about "what area am I working in?"

### `covers:` frontmatter as the archive-trigger index

Each doc declares what components/commands it covers:
```yaml
---
covers: [TimerManager, TimerCommand, timer, TimerDAO]
last-synced: 2026-03-23
---
```

Archive step: intersect `covers` lists with the change's proposal Impact section (component names). Any doc with a match gets flagged for review.

**Why not full-text scan**: Too noisy. `covers:` is a deliberate, maintained contract — the same as how specs declare their scope.

### Standard section template for all docs

```
## Overview          ← 2-3 sentences: what this capability does
## Components        ← table: component → responsibility
## How It Works      ← mechanism, data flow, key decisions
## Commands          ← if user-facing: prefix, params, example
## Data Model        ← if DB-backed: models, key fields
## Extension Points  ← how to add/modify this capability
```

Consistent headers mean the agent can request "the Commands section of room.md" without reading the whole file.

### opsx:archive extension: README + docs check step

After spec-sync and before moving to archive:
1. Read change's `proposal.md` Impact + What Changes
2. Always check README for drift (README always relevant)
3. Parse `covers:` from all `docs/*.md`, intersect with impact
4. For each matched doc: show diff summary, ask user to confirm update or skip
5. Proceed to archive regardless (no blocking)

This is additive — existing archive flow unchanged, new step inserted before `mv`.

## Risks / Trade-offs

- **`covers:` gets stale** → Mitigation: archive step surfaces this naturally — if a change touches TimerManager and `timers.md` doesn't list it in `covers:`, the review will catch the drift. Agent can also update `covers:` when updating a doc.
- **Doc content drifts anyway** → Mitigation: archive-time review is the correction mechanism. Docs are written by the agent, updated by the agent — no human maintenance required.
- **6 files may merge too much** → If a capability becomes very complex, split then. Starting coarse is reversible; starting fine-grained creates unnecessary maintenance surface.

## Migration Plan

1. Sync `openspec/specs/` from the 3 archived changes (manual, one-time)
2. Delete all existing `docs/*.md` files
3. Write 6 new capability docs
4. Rewrite `README.md`
5. Update `opsx:archive` skill with the doc-check step

No rollback needed — old docs are prose notes with no dependents. Git history preserves them.

## Open Questions

- None — design is fully determined by the explore session.

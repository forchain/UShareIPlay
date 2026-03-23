## Why

README and `docs/` have drifted from the codebase and are not designed for agent consumption — they are either outdated narrative prose or ad-hoc development notes that no one maintains. The primary consumer of project docs is the AI agent, and the current structure makes it slow and unreliable for the agent to find accurate information. Additionally, `openspec/specs/` is empty because the spec-sync step was never run on any previous archive.

## What Changes

- **BREAKING** `docs/` fully rebuilt: all existing files deleted, replaced with 6 flat capability docs in English, structured for agent lookup
- **BREAKING** `README.md` fully rebuilt: overview + quick start + command reference + index to `docs/`
- `openspec/specs/` populated: delta specs from all 3 archived changes synced to the global specs directory
- `opsx:archive` skill extended: after spec-sync, check README and any `docs/*.md` whose `covers:` frontmatter intersects the change's impact, prompt user to confirm updates before completing archive

## Capabilities

### New Capabilities

- `agent-docs-system`: the `docs/` directory as a maintained, agent-readable reference — 6 capability files with consistent structure and `covers:` frontmatter enabling targeted lookup and archive-time sync

### Modified Capabilities

<!-- No existing openspec specs to modify -->

## Impact

- `README.md`: full rewrite
- `docs/`: full rewrite (6 files: `music.md`, `room.md`, `users.md`, `timers.md`, `config.md`, `system.md`)
- `openspec/specs/`: create directory, sync 3 sets of delta specs from archived changes
- `.claude/` or `openspec/` skill definitions: extend `opsx:archive` with README + docs check step
- Old `docs/` files: deleted (historical notes moved conceptually to commit history / change archives)

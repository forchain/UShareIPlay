## ADDED Requirements

### Requirement: docs/ contains flat capability reference files
The `docs/` directory SHALL contain exactly 6 Markdown files at the root level (`music.md`, `room.md`, `users.md`, `timers.md`, `config.md`, `system.md`). Each file MUST have YAML frontmatter with a `covers` list and a `last-synced` date.

#### Scenario: Agent locates capability doc
- **WHEN** the agent needs reference for a known capability (e.g., timer system)
- **THEN** a single glob `docs/*.md` returns all files and the relevant file is identifiable by name without reading content

#### Scenario: Frontmatter covers list is present
- **WHEN** any `docs/*.md` file is parsed
- **THEN** it SHALL contain a `covers:` YAML array listing the component/class names it describes

### Requirement: docs/ capability files use consistent section structure
Each capability doc SHALL contain sections in this order: Overview, Components, How It Works, Commands (if applicable), Data Model (if applicable), Extension Points.

#### Scenario: Agent extracts commands reference
- **WHEN** the agent reads the Commands section of any capability doc
- **THEN** it SHALL find command prefix, parameters, and at least one usage example

#### Scenario: Agent finds extension guidance
- **WHEN** the agent needs to add a new command or modify a capability
- **THEN** the Extension Points section SHALL provide the steps required

### Requirement: README serves as system overview and docs index
`README.md` SHALL contain: one-paragraph system description, quick start (setup + run), full command reference table, and a capability index linking to each `docs/*.md` file.

#### Scenario: Agent identifies all available commands
- **WHEN** the agent reads README.md
- **THEN** it SHALL find a table or list of all commands with prefix and brief description

#### Scenario: Agent navigates to capability detail
- **WHEN** the agent reads the capability index in README
- **THEN** it SHALL find a link or path to the relevant `docs/*.md` for each capability

### Requirement: Archive step checks README and affected docs before completing
The `opsx:archive` skill SHALL, after spec-sync and before moving the change directory, check README.md for drift and check any `docs/*.md` whose `covers:` frontmatter intersects the change's stated impact. The agent SHALL present a diff summary and prompt the user to confirm updates or skip. Archive MUST NOT be blocked by skipping doc updates.

#### Scenario: Archive detects README drift
- **WHEN** a change's proposal Impact mentions components documented in README
- **THEN** the archive step SHALL surface the relevant README sections and prompt for update

#### Scenario: Archive detects affected capability doc
- **WHEN** a change's proposal Impact mentions a component listed in a doc's `covers:` frontmatter
- **THEN** that doc SHALL be flagged and reviewed before archive completes

#### Scenario: User skips doc update during archive
- **WHEN** the user chooses to skip a doc update during archive
- **THEN** archive SHALL complete normally with a warning note in the summary

### Requirement: openspec/specs/ is populated from archived changes
`openspec/specs/` SHALL exist and contain at minimum the synced specs from all previously archived changes (gift-fallback-yellow-duck, timer-config-to-db, local-config-override).

#### Scenario: Specs directory is non-empty after migration
- **WHEN** `openspec/specs/` is listed
- **THEN** it SHALL contain at least one capability subdirectory with a `spec.md`

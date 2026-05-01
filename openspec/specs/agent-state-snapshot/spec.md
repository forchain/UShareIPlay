## ADDED Requirements

### Requirement: The system SHALL write a versioned status snapshot
The system SHALL write a JSON status snapshot file (`status.json`) that represents the latest known runtime state. The snapshot MUST include a `schema_version` integer.

#### Scenario: Snapshot is machine-readable
- **WHEN** a tool reads `status.json`
- **THEN** it SHALL parse as valid JSON and include `schema_version`

### Requirement: The snapshot MUST include run identity and time
The snapshot MUST include:
- `run_id` (string)
- `ts` (RFC3339/ISO8601 timestamp string)

#### Scenario: Snapshot can be associated to events
- **WHEN** `events.jsonl` is present
- **THEN** `status.json.run_id` SHALL match the `run_id` used by emitted events for the same run

### Requirement: The snapshot MUST expose foreground application classification
The snapshot MUST include `foreground_app` with one of: `Soul`, `QQMusic`, `Launcher`, `Unknown`.

#### Scenario: Agent can decide which subsystem is active
- **WHEN** the snapshot indicates `foreground_app`
- **THEN** the agent SHALL be able to decide whether command testing is possible without UI mutation

### Requirement: The snapshot MUST include Soul/QQMusic coarse UI states
The snapshot MUST include:
- `soul_ui_state` (string)
- `qqmusic_ui_state` (string)

These state strings MUST be stable identifiers (no free-form messages).

#### Scenario: Readiness gating uses stable states
- **WHEN** `soul_ui_state` changes
- **THEN** it SHALL only change to one of the documented stable identifiers (e.g., `InChatReady`, `InHome`, `InUnknownPage`)

### Requirement: The snapshot MUST include anchors for readiness explanation
The snapshot MUST include `anchors` as a list of strings representing currently detected UI anchors (e.g., `message_content`, `input_box_entry`).

#### Scenario: Readiness is explainable
- **WHEN** the system claims it is ready for command testing
- **THEN** `anchors` SHALL include at least the anchor(s) used to justify readiness

### Requirement: The snapshot MUST include pipeline state for safe injection
The snapshot MUST include:
- `pipeline.ui_lock` (string: `locked` or `unlocked`)
- `pipeline.queue_size` (integer)

#### Scenario: Agent avoids racing UI operations
- **WHEN** `pipeline.ui_lock == locked`
- **THEN** the agent SHALL treat the system as not safe for injecting new test commands

### Requirement: The snapshot SHALL support optional business context
The snapshot SHALL support optional business context fields:
- `business.party_id_current` and `business.party_id_target` (strings, MAY be empty)
- `business.timers_running` (boolean)
- `business.playback_info_summary` (object or null)

#### Scenario: Agent can validate timer/music-related tests
- **WHEN** timer or music subsystems are involved
- **THEN** the snapshot SHOULD provide enough summary context to support assertions without UI mutation


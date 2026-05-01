## ADDED Requirements

### Requirement: The Agent E2E runner SHALL choose process lifecycle by scenario
The Agent E2E runner SHALL distinguish at least two scenarios:
- `dev`: code or configuration under test may have changed; the runner MUST stop a managed existing process and start a fresh process before injecting commands.
- `test`: the user is asking to test behavior of a currently available build; the runner SHOULD reuse a healthy running process and MUST only start a process when none is running or the running process is unhealthy.

#### Scenario: Development test restarts stale code
- **WHEN** the runner is invoked with scenario `dev`
- **THEN** it SHALL stop the previously managed process if present
- **AND** it SHALL start a fresh process before waiting for readiness

#### Scenario: Behavior test reuses a healthy app
- **WHEN** the runner is invoked with scenario `test`
- **AND** a managed process is alive and has fresh `status.json` / `events.jsonl`
- **THEN** it SHALL reuse that process instead of killing it

#### Scenario: Behavior test starts missing app
- **WHEN** the runner is invoked with scenario `test`
- **AND** no healthy managed process is running
- **THEN** it SHALL start the process and proceed with the same E2E flow

### Requirement: The runner SHALL detect managed process health before injection
The runner SHALL determine process health using machine-readable evidence, including:
- a live managed PID or equivalent process identity
- a fresh run-scoped `status.json`
- an appendable or recently updated `events.jsonl`
- readiness gates from `agent/preconditions.md`

#### Scenario: Stale artifacts are not treated as a running app
- **WHEN** `status.json` and `events.jsonl` exist but are stale or disconnected from a live process
- **THEN** the runner SHALL NOT treat the app as healthy

### Requirement: The system SHALL provide a reusable background command injection channel
The system SHALL support injecting an E2E command into a reused running process without relying on the runner owning the process stdin. The channel MAY be implemented as a file spool, local IPC, socket, or another repository-approved control mechanism, but it MUST route into the same console/queue path used by interactive console commands.

#### Scenario: Runner injects into reused process
- **WHEN** a healthy managed process was started outside the current runner invocation
- **THEN** the runner SHALL still be able to inject `:command` or `!dump` through the background control channel
- **AND** the system SHALL emit `queue.enqueue` with enough context to identify the source as an agent/background injection

### Requirement: The runner SHALL collect multi-source assertions
For every non-smoke E2E run, the runner SHALL support assertions from these sources:
- structured events (`events.jsonl`)
- runtime status (`status.json`)
- human-readable logs
- SQLite database queries when a DB path is configured
- read-only UI evidence (`page_source.xml`, `screenshot.png`)
- optional open source UI evidence tooling such as XML parsing, OCR, image comparison, or accessibility snapshot parsing when available

#### Scenario: Command result is validated through evidence chain
- **WHEN** a command is injected
- **THEN** the runner SHALL assert the event chain for that command
- **AND** it SHALL include configured log/DB/UI checks in the run report

### Requirement: UI validation SHALL be read-only and tool-driven
The runner SHALL NOT mutate the device UI or create a second Appium session for validation. UI validation SHALL use only evidence emitted by the running process, such as page source and screenshots, and MAY analyze those files with open source tools.

#### Scenario: UI feedback is validated without touching the device
- **WHEN** a test expects visible feedback in Soul or QQ Music
- **THEN** the runner SHALL request or reuse a read-only dump
- **AND** it SHALL validate the expected feedback from `page_source.xml`, `screenshot.png`, OCR, or image matching

### Requirement: The run report SHALL explain lifecycle and evidence decisions
The E2E report SHALL include:
- trigger type (`auto` or `manual`)
- selected scenario (`dev` or `test`)
- lifecycle action (`restarted`, `reused`, `started`, or `failed`)
- command injected and injection channel used
- readiness status and anchors
- assertion results for events/logs/DB/UI evidence
- artifact paths for postmortem inspection

#### Scenario: Failed readiness leaves actionable evidence
- **WHEN** readiness or assertion fails
- **THEN** the report SHALL include the last status snapshot, relevant recent events, log excerpts if available, and paths to any generated UI artifacts

### Requirement: The runner SHALL accept an explicit trigger type
The runner SHALL allow callers to identify whether a run was started automatically by the Agent or manually by the user. Trigger type SHALL be recorded in the report and SHOULD be emitted in structured events when available.

#### Scenario: Manual trigger is auditable
- **WHEN** the user explicitly asks to test a command
- **THEN** the E2E report SHALL identify the trigger as `manual`

#### Scenario: Automatic trigger is auditable
- **WHEN** the Agent runs E2E after implementation and unit tests
- **THEN** the E2E report SHALL identify the trigger as `auto`


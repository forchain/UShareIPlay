## ADDED Requirements

### Requirement: The system SHALL emit structured events as JSON Lines
The system SHALL write a structured event stream in JSON Lines format (`events.jsonl`) during runtime. Each line MUST be a single JSON object.

#### Scenario: Events are append-only and crash-tolerant
- **WHEN** the process is running and emits events
- **THEN** events SHALL be appended to `events.jsonl` line-by-line without requiring in-memory buffering of the full file

### Requirement: Each event MUST include stable core fields
Each event JSON object MUST contain:
- `schema_version` (integer)
- `ts` (RFC3339/ISO8601 timestamp string)
- `level` (string)
- `event` (string, dot-separated)
- `run_id` (string)
- `ctx` (object, MAY be empty)

#### Scenario: Minimal event is still parseable
- **WHEN** an event is emitted with no extra context
- **THEN** it SHALL still include all required core fields and `ctx` SHALL be an object

### Requirement: The system SHALL support trace correlation
Events related to one “test action / command execution / recovery sequence” SHALL be correlatable via `trace_id` (string). If a trace_id is not available, it SHALL be omitted rather than set to null.

#### Scenario: Command execution is correlated
- **WHEN** a command is enqueued and executed
- **THEN** `queue.enqueue`, `command.dispatch`, and `command.result` events SHALL share the same `trace_id`

### Requirement: The system SHALL emit readiness and state transition events
The system SHALL emit explicit state transition and readiness events, including:
- `state.snapshot`
- `state.ready`
- `foreground.app`

#### Scenario: Readiness is observable
- **WHEN** the app reaches the command-test-ready condition (e.g., `InChatReady`)
- **THEN** it SHALL emit a `state.ready` event with enough context to explain why it is ready (anchors, foreground app)

### Requirement: The system SHALL emit queue lifecycle events
The system SHALL emit queue-related events:
- `queue.enqueue`
- `queue.drain.start`
- `queue.drain.end`

#### Scenario: Queue drain is observable
- **WHEN** the queue is drained for processing
- **THEN** it SHALL emit `queue.drain.start` and `queue.drain.end` including message counts in `ctx`

### Requirement: The system SHALL emit command lifecycle events
The system SHALL emit command-related events:
- `command.received`
- `command.dispatch`
- `command.result`

#### Scenario: Command result is observable
- **WHEN** a command finishes execution
- **THEN** it SHALL emit `command.result` with `ctx.success=true` OR `ctx.error` populated


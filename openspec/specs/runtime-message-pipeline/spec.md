## Purpose
Define how runtime-produced messages and commands are enqueued, drained, and dispatched independently of UI chat events.

## Requirements

### Requirement: Runtime queue SHALL be drained independently of chat message events
The runtime SHALL drain queued messages from `MessageQueue` as part of the monitor loop and MUST NOT require a `message_content` event to occur before timer, agent, keyword, post-party automation, or console-injected messages can be processed.

#### Scenario: Timer message is processed without new chat content
- **WHEN** a timer enqueues a message while no new `message_content` event is processed in the same monitor iteration
- **THEN** the runtime SHALL still drain the queued timer message through the runtime queue pipeline

#### Scenario: Agent spool command is processed without chat anchor dependency
- **WHEN** an agent command file is read and converted into a queued command
- **THEN** the runtime SHALL process that queued command without waiting for a chat message element to trigger `MessageContentEvent`

### Requirement: Runtime queue drain SHALL preserve existing message semantics
The runtime queue drain SHALL preserve the existing queue message semantics: semicolon-delimited parts are processed in order, `{user_name}` placeholders are replaced with the queue message nickname, colon-prefixed parts are dispatched as commands, and non-command parts are sent as normal chat messages.

#### Scenario: Mixed queued message parts are routed correctly
- **WHEN** a queued message contains `hello {user_name};:timer list`
- **THEN** the runtime SHALL send `hello <nickname>` as a normal chat message
- **AND THEN** the runtime SHALL dispatch `:timer list` through the command handling path for the same nickname

### Requirement: Runtime queue drain SHALL be single-owner
The system SHALL have one authoritative runtime queue drain path to avoid duplicate processing of queued messages.

#### Scenario: MessageContentEvent does not duplicate runtime queue drain
- **WHEN** `MessageContentEvent` processes visible chat content
- **THEN** it SHALL NOT independently drain `MessageQueue` after the runtime loop has assumed queue drain ownership

### Requirement: Runtime helper extraction SHALL preserve runtime status behavior
Extracted runtime helpers SHALL preserve the existing externally observable status fields and readiness event behavior.

#### Scenario: Status snapshot remains compatible
- **WHEN** the runtime writes a status snapshot from `page_source`
- **THEN** the snapshot SHALL continue to include foreground app, Soul UI state, anchors, pipeline status, and business status fields equivalent to the pre-extraction behavior

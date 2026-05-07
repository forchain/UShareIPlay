## MODIFIED Requirements

### Requirement: The system SHALL emit queue lifecycle events
The system SHALL emit queue-related events:
- `queue.enqueue`
- `queue.drain.start`
- `queue.drain.end`

Queue drain lifecycle events MUST be emitted by the authoritative runtime queue drain path, regardless of whether the queued message originated from timer execution, agent command spool injection, keyword expansion, post-party automation, console injection, or chat-related recovery.

#### Scenario: Queue drain is observable
- **WHEN** the queue is drained for processing
- **THEN** it SHALL emit `queue.drain.start` and `queue.drain.end` including message counts in `ctx`

#### Scenario: Runtime-loop queue drain is observable without chat event dependency
- **WHEN** the runtime loop drains one or more queued messages without a `message_content` event being processed in the same iteration
- **THEN** it SHALL emit `queue.drain.start` and `queue.drain.end` from that runtime drain path

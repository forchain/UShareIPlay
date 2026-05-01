## ADDED Requirements

### Requirement: The system SHALL dump read-only UI artifacts using the existing Appium session
The system SHALL be able to dump read-only UI artifacts (page source and screenshot) using the existing Appium driver/session owned by the running process.

#### Scenario: No second Appium session is created
- **WHEN** an artifact dump is triggered
- **THEN** the system SHALL NOT create a new Appium session and SHALL use the existing driver

### Requirement: The system SHALL write page source to a file
The system SHALL write the current `page_source` to `page_source.xml` (or an equivalent `.xml` file) under a run-scoped artifacts directory.

#### Scenario: Page source is available for postmortem
- **WHEN** a guard fails or an assertion fails during E2E
- **THEN** the system SHALL write `page_source.xml` and emit an `artifact.page_source` event containing the path

### Requirement: The system SHALL write a screenshot to a file
The system SHALL write a screenshot image to `screenshot.png` (or an equivalent `.png` file) under a run-scoped artifacts directory.

#### Scenario: Screenshot is available for postmortem
- **WHEN** a guard fails or an assertion fails during E2E
- **THEN** the system SHALL write `screenshot.png` and emit an `artifact.screenshot` event containing the path

### Requirement: Artifact dumping SHALL be triggerable without UI mutation
Artifact dumping SHALL be triggerable in a way that does not require UI mutation by external tools. Triggering MAY be automatic on failures and/or via an internal admin command routed through console/queue.

#### Scenario: Agent requests a dump via console/queue
- **WHEN** the agent injects a supported admin command (e.g., `!dump_state` or equivalent) via console/queue
- **THEN** the system SHALL generate artifacts and update `status.json` and `events.jsonl` accordingly


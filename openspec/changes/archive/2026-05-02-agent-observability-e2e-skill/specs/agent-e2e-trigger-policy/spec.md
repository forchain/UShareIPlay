## ADDED Requirements

### Requirement: The Agent SHALL support automatic E2E triggering
After completing code changes and passing relevant unit or script tests, the Agent SHALL evaluate whether an E2E run is warranted. The Agent SHOULD automatically run E2E when the change affects any of:
- command dispatch or command output
- queue consumption or asynchronous event flow
- timers or scheduled behavior
- SQLite database side effects
- structured events, logs, reports, or status snapshots
- read-only UI evidence or user-visible feedback
- Appium startup, session, foreground app, or readiness behavior
- cross-component user workflows

#### Scenario: Agent runs E2E after risky feature work
- **WHEN** a feature change passes unit tests
- **AND** the change affects command execution and user-visible output
- **THEN** the Agent SHALL run the E2E skill before declaring the feature complete unless a documented blocker prevents it

#### Scenario: Agent skips E2E for low-risk static-only work
- **WHEN** a change only updates documentation or isolated static metadata
- **THEN** the Agent MAY skip E2E
- **AND** it SHALL state why E2E was not necessary if reporting completion

### Requirement: The Agent SHALL support manual E2E triggering
When the user explicitly asks the Agent to test a feature, command, or suspected behavior, the Agent SHALL treat that as a manual E2E trigger and execute the real runtime path.

#### Scenario: User asks to test Help command freshness
- **WHEN** the user asks whether the Help command output is stale
- **THEN** the Agent SHALL start or reuse the program according to lifecycle policy
- **AND** it SHALL inject the Help command through the approved background/console/queue path
- **AND** it SHALL validate the generated output through runtime evidence
- **AND** it SHALL NOT rely only on static configuration inspection

### Requirement: Manual E2E SHALL prefer real behavior over static inspection
For manual triggers, static source/config/database inspection SHALL only be used as supporting evidence. The primary result SHALL come from running the program, injecting the requested action, and validating produced events, logs, reports, database changes, or read-only UI evidence.

#### Scenario: Static config matches but runtime output fails
- **WHEN** static config appears current
- **BUT** the runtime command output is missing or stale
- **THEN** the Agent SHALL report the runtime behavior as failing and investigate the runtime path

### Requirement: E2E failures SHALL enter an iterative repair loop
When E2E fails and the failure appears fixable within the repository, the Agent SHALL use the collected evidence to modify the implementation, rerun relevant unit/script tests, and rerun the E2E scenario until it passes or a blocker is reached.

#### Scenario: E2E finds a command output bug
- **WHEN** an E2E command test fails because output is stale or malformed
- **THEN** the Agent SHALL fix the relevant command/config/rendering path
- **AND** it SHALL rerun the focused tests and the E2E command test

### Requirement: The Agent SHALL stop with a concrete blocker when E2E cannot proceed
If E2E cannot be completed because of missing device state, unavailable Appium server, unauthenticated account, missing selector, missing injection channel, unsafe environment, or unclear expected behavior, the Agent SHALL stop and provide:
- the blocker
- evidence already collected
- the next user action or missing input needed
- whether code changes were made before the blocker

#### Scenario: Device-dependent UI evidence is unavailable
- **WHEN** the test requires UI evidence
- **AND** the running process cannot produce page source or screenshot
- **THEN** the Agent SHALL report the missing evidence path as a blocker unless a non-UI assertion is sufficient for the requested test

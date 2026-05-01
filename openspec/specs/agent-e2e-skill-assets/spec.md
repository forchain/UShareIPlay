## ADDED Requirements

### Requirement: The repository SHALL include versioned Agent E2E skill assets
The repository SHALL include an `agent/` directory containing versioned assets that define the Agent’s E2E testing behavior, constraints, and self-evolution workflow.

#### Scenario: Agent finds its operational contract in-repo
- **WHEN** an agent needs to understand how to run E2E in this repository
- **THEN** it SHALL be able to read `agent/` assets without needing external context

### Requirement: Capabilities registry MUST encode hard rules and prerequisites
`agent/capabilities.json` MUST exist and MUST include hard rules, including:
- External tools MUST NOT create or connect a second Appium session for UI mutation.
- Input MUST be injected via console/queue.
- Read-only UI evidence MUST be produced by the running process using its existing session.

#### Scenario: Agent rejects forbidden actions
- **WHEN** a requested test plan includes UI mutation via a new Appium session
- **THEN** the agent SHALL refuse and propose the allowed alternative (console injection + read-only artifacts)

### Requirement: Preconditions MUST define readiness gates
`agent/preconditions.md` MUST define the readiness gate(s) used for command E2E, including `CommandReady` as a stable concept with anchor-based criteria.

#### Scenario: Agent performs readiness gating
- **WHEN** an E2E test is requested for a command
- **THEN** the agent SHALL check `CommandReady` before injecting commands

### Requirement: Event taxonomy MUST define the minimal assertion set
`agent/event_taxonomy.md` MUST define the set of events required to assert a basic E2E flow (enqueue → drain → dispatch → result), and how to correlate with `trace_id`.

#### Scenario: Agent asserts success using events
- **WHEN** a command E2E test completes
- **THEN** the agent SHALL be able to assert success by reading `events.jsonl` according to the taxonomy

### Requirement: Playbooks MUST exist for common scenarios
`agent/playbooks/` MUST contain playbooks for at least:
- `command_e2e`
- `timer_e2e`

Each playbook MUST define Scenario/Lifecycle/Guard/Advance/Inject/Assert/OnFail, including when to restart the app and when to reuse an existing healthy process.

#### Scenario: Agent follows a playbook
- **WHEN** a timer E2E test is requested
- **THEN** the agent SHALL follow the `timer_e2e` playbook and produce a minimal report/artifacts on failure

### Requirement: Playbooks MUST define scenario-specific lifecycle behavior
The E2E playbooks MUST define the default lifecycle behavior for:
- development validation after code changes: restart managed process before testing
- behavior-only testing of an already running app: reuse the app if healthy; start it only if missing or unhealthy

#### Scenario: Agent chooses reuse in test scenario
- **WHEN** the user asks only to test an existing feature or command
- **THEN** the playbook SHALL direct the agent to inspect current process health before deciding whether to start the app

### Requirement: Playbooks MUST define automatic and manual trigger behavior
The E2E playbooks MUST explain:
- when the Agent may automatically run E2E after unit/script tests pass
- how the Agent should respond to an explicit user request to test a feature or command
- how failures feed back into implementation and retesting

#### Scenario: Agent follows manual trigger playbook
- **WHEN** the user asks the Agent to test a specific command
- **THEN** the relevant playbook SHALL require runtime command injection and evidence-based validation

### Requirement: Self-evolution MUST be recorded as repo changes
When the agent discovers a repeated failure mode or missing prerequisite, it MUST record it in:
- `agent/known_issues.md` (if not fixable or deferred), OR
- `agent/questions.md` (if additional user input is required), OR
- propose a new change (if fixable by infrastructure updates)

#### Scenario: Agent improves future collaboration
- **WHEN** a test cannot be executed due to missing selectors or missing dump hooks
- **THEN** the agent SHALL record the missing inputs and the recommended next step in `agent/` assets


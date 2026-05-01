# agent-e2e-test Skill Design

## Problem

The current repository has useful observability artifacts and a runner script, but it still lacks a real callable skill for manual end-to-end testing.

The earlier design was wrong because it framed `scripts/agent_e2e.py --command ...` as the center of the E2E workflow. That only fits command-style tests. It does not fit tests such as entering a room, validating startup state, observing pre-room behavior, checking recovery, or verifying UI/DB/log side effects without a command.

The correct boundary is:

- **Skill / Agent**: understands the user's test intent, creates a test plan, chooses tools, reads evidence, decides pass/fail, fixes code when appropriate, and reruns.
- **Scripts / tools**: perform deterministic low-level actions such as starting the app, checking ADB state, reading logs, querying DB, capturing screenshots, dumping page source, and optionally injecting text or commands.

## Goal

Create an `agent-e2e-test` skill that turns a natural-language test request into a real E2E test session.

The skill must be able to support many kinds of requests, including but not limited to:

- testing a command such as Help
- testing app startup and room-entry behavior
- testing behavior before entering a room
- testing UI feedback
- testing DB side effects
- testing logs/recovery behavior
- testing Android foreground activity or page state

The skill must never treat unit tests, static checks, or runner smoke mode as user-facing E2E success.

## Architecture

```text
User natural-language request
        |
        v
agent-e2e-test skill
        |
        v
Agent creates request-specific test plan
        |
        v
Agent selects tool actions:
  process / adb / logs / db / artifacts / screenshot / page_source / input
        |
        v
Agent observes runtime evidence
        |
        v
Agent reasons over evidence:
  pass | fix and retest | blocker
```

## Toolbelt Principle

Tool scripts must be business-neutral. They expose capabilities, not test cases.

Allowed tool categories:

- **Process tools**: check managed PID, start `./run.sh`, stop/restart service, wait for artifacts.
- **ADB tools**: list devices, inspect current package/activity, collect logcat, optionally perform user-level input actions when explicitly required by the test plan.
- **Artifact tools**: read `status.json`, `events.jsonl`, screenshots, page source, and generated reports.
- **DB tools**: run read-only SQLite queries; optionally perform controlled test acceleration only when the plan calls for it.
- **Log tools**: tail logs, filter by time window, regex/search for errors or expected messages.
- **UI evidence tools**: capture or request screenshot/page source from the running process and analyze files.
- **Input tools**: inject text/commands through approved background/console/queue paths. This is one tool action, not the skill interface.

`scripts/agent_e2e.py` may remain as one runner tool, but it must be documented as a low-level helper. Its `--command` argument means “inject this text into the backend input path,” not “all E2E tests are command tests.”

## Skill Workflow

The skill should instruct Agent to:

1. Restate the user's test intent in concrete terms.
2. Classify the test surface: process, Android/ADB, UI, command/input, DB, logs, timers, recovery, or mixed.
3. Create a test plan with:
   - preconditions
   - startup/reuse policy
   - actions to perform
   - evidence to collect
   - success criteria
   - failure and blocker handling
4. Start or reuse the real service:
   - `dev`: restart managed process through `./run.sh`
   - `test`: reuse healthy process; otherwise start through `./run.sh`
5. Execute the plan using toolbelt actions.
6. Read runtime evidence and reason about pass/fail.
7. If the failure is fixable in the repo, fix code and rerun focused checks plus E2E.
8. If blocked by device/Appium/account/page state/missing evidence, report the blocker with collected evidence.

## Manual Test Examples

### Help Command Freshness

The Agent may choose background input as one action:

```text
Plan:
- Start/reuse service
- Inject ":help" through approved input tool
- Read events/logs/status and any runtime output evidence
- Compare observed runtime output against current command capability
- Fix help generation if runtime output is stale
```

The test is not “run `--command :help` and trust the script.” The script only performs the input and evidence collection; the Agent judges whether output is stale.

### Pre-Room Behavior

No command is required.

```text
Plan:
- Start service through run.sh
- Use ADB/artifacts to observe current package/activity
- Capture status/page source/screenshot before entering a room
- Inspect logs/events for expected startup and navigation behavior
- Decide whether pre-room UI/state matches the requested behavior
```

### DB Side Effect

Command input may or may not be involved.

```text
Plan:
- Snapshot relevant DB rows
- Perform requested runtime action
- Snapshot DB rows again
- Correlate DB changes with events/logs
- Decide whether side effect matches expected behavior
```

## Blocker Policy

The skill must report a blocker instead of claiming E2E success when:

- `./run.sh` was not executed and no healthy real process was reused
- Appium is unavailable
- Android device is not connected or not responding
- required app package/activity cannot be observed
- artifacts are missing or stale
- page source/screenshot cannot be produced when needed
- the expected behavior is ambiguous

## Verification

To verify this work:

- Confirm `.agents/skills/agent-e2e-test/SKILL.md` exists.
- Confirm the skill describes Agent-led planning and toolbelt usage.
- Confirm the skill forbids treating smoke/unit/static checks as E2E success.
- Confirm command injection is documented as a tool action, not the skill interface.
- Run syntax/readability checks for any new scripts or changed Python files.
- On a machine with Appium and device access, run a real manual E2E session and verify ADB/device activity.

## Out of Scope

- Encoding every possible E2E scenario as command-line flags.
- Creating a second Appium session from the Agent.
- Treating runner success as the final oracle when Agent has not inspected evidence.

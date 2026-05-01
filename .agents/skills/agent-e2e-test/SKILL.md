---
name: agent-e2e-test
description: Use when the user asks to manually or automatically run a real end-to-end test of UShareIPlay behavior through the running app, Android device, logs, DB, artifacts, screenshots, page source, or backend input. This skill is an Agent-led test orchestration workflow, not a fixed command runner.
license: MIT
---

# Agent E2E Test

Use this skill for real runtime validation. The Agent owns the test plan and pass/fail judgment. Scripts are only a toolbelt for deterministic low-level actions.

## Core Rule

Do not call unit tests, static inspection, or `scripts/agent_e2e.py --mode smoke` an end-to-end test. Smoke mode is only a runner self-check and does not start `run.sh` or exercise Android.

## Workflow

1. Restate the user's test intent in concrete terms.
2. Classify the surfaces involved: process, Android/ADB, UI, input/command, DB, logs, timers, recovery, artifacts, or mixed.
3. Create a short test plan:
   - preconditions
   - whether to restart or reuse the service
   - tool actions to perform
   - evidence to collect
   - success criteria
   - failure/blocker handling
4. Before executing the plan, run a tool/resource self-check for the actions the plan needs.
   - Check only required capabilities, plus shared basics.
   - Prepare directories/files when safe.
   - Stop with a blocker if required tools, config, permissions, or resources are missing.
5. Start or reuse the real service:
   - `dev`: restart managed process and start via `./run.sh`
   - `test`: reuse a healthy managed process; if missing or unhealthy, start via `./run.sh`
6. Execute the plan using toolbelt actions.
7. Read runtime evidence and decide pass/fail with reasoning.
8. If failing and fixable in repo, fix code and rerun focused checks plus E2E.
9. If blocked by device/Appium/account/page state/missing evidence, report a blocker with collected evidence.
10. After each difficult or repetitive test, decide whether the E2E toolbelt or the system's testability should evolve.

## Toolbelt

Use the bundled toolbelt for atomic operations:

```bash
source .venv/bin/activate
python .agents/skills/agent-e2e-test/scripts/e2e_toolbelt.py <subcommand> [args]
```

Common subcommands:

- `doctor --needs adb,db,logs,artifacts,input,process`: self-check required tools/resources before running the plan.
- `process-status`: show managed PID, whether alive, latest artifact run.
- `start --scenario test|dev`: start or restart the real service through `./run.sh`.
- `stop`: stop the managed process.
- `inject --text '...'`: write backend input into `.agent/commands/*.cmd`.
- `adb-devices`: list Android devices through `adb devices`.
- `adb-current`: show current focused package/activity through `adb shell dumpsys window`.
- `adb-screenshot --out <png>`: capture a device screenshot through ADB.
- `adb-logcat --seconds <n> --out <txt>`: capture recent logcat output.
- `artifacts-latest`: print latest `artifacts/<run_id>` paths.
- `read-status`: print latest `status.json`.
- `tail-events --limit <n>`: print recent structured events.
- `tail-logs --pattern <regex>`: inspect workspace logs.
- `db-query --sql 'select ...'`: run a SQLite query against `data/soul_bot.db`.
- `request-dump`: inject `!dump` so the running process exports page source/screenshot using its existing Appium session.
- `record-gap --kind missing-tool|repeatable-flow|temporary-helper|testability-gap|architecture-upgrade --title '...' --detail '...'`: record a toolbelt or system testability evolution opportunity.

`scripts/agent_e2e.py` is also available as a low-level runner. Its `--command` argument means “inject this text into the backend input path.” It is not the skill interface and not the whole E2E process.

## Evidence Rules

Prefer evidence from the real runtime:

- `artifacts/<run_id>/events.jsonl`
- `artifacts/<run_id>/status.json`
- `artifacts/<run_id>/page_source.xml`
- `artifacts/<run_id>/screenshot.png`
- workspace logs
- SQLite query results
- ADB current activity / screenshots / logcat

Static source/config reads can support analysis, but they cannot replace runtime evidence for a manual E2E request.

## Self-Check Rule

After drafting the test plan and before executing it, identify the required tool categories and run `doctor`.

Examples:

```bash
python .agents/skills/agent-e2e-test/scripts/e2e_toolbelt.py doctor --needs process,adb,artifacts,logs
python .agents/skills/agent-e2e-test/scripts/e2e_toolbelt.py doctor --needs process,input,db,logs
```

If `doctor` reports missing config, unavailable ADB, unreadable DB, missing `run.sh`, unwritable `.agent/commands`, unavailable logs/artifacts paths, or extra authorization/resource needs, resolve or report the blocker before starting the actual test.

## Toolbelt And Testability Evolution

The toolbelt and the system under test must evolve through real collaboration. After drafting or running a test plan, check whether the current tools or the application's architecture made the work slower, weaker, ambiguous, or impossible.

Use five levels:

1. **Fill tool gaps**: if a required observation/action cannot be performed with current tools, add or propose a reusable tool.
2. **Script repeatable flows**: if Agent repeatedly performs the same monitor/collect/compare sequence, promote it into a script while keeping Agent responsible for pass/fail reasoning.
3. **Temporary targeted helpers**: if one specific test would be inefficient through manual orchestration, create a temporary helper under `.agent/e2e-tools/`; promote it into the skill only if it becomes generally useful.
4. **Expose testability gaps**: if Agent can observe behavior only through fragile log scraping, screenshots, or timing guesses, record the missing structured state/report/event that would make the system testable.
5. **Propose architecture upgrades**: if repeated tool calls still cannot prove behavior reliably, propose concrete system changes such as structured intermediate reports, stronger event taxonomy, stable state anchors, explicit health/readiness endpoints, or better DB/log correlation IDs.

Record discoveries with:

```bash
python .agents/skills/agent-e2e-test/scripts/e2e_toolbelt.py record-gap \
  --kind testability-gap \
  --title "Need focused room-entry state report" \
  --detail "Current tools require fragile manual correlation of ADB activity, status, and logs."
```

When adding durable tools, prefer extending `.agents/skills/agent-e2e-test/scripts/e2e_toolbelt.py` or adding a small script under `.agents/skills/agent-e2e-test/scripts/`. Keep tools business-neutral when possible. If a helper is scenario-specific, mark it temporary first and only promote it after reuse.

When proposing architecture upgrades, be specific: name the missing signal, where it should be emitted, how Agent would use it, and what tests it would make possible. Do not keep adding scripts when the real issue is missing system observability or unstable architecture.

## Blockers

Stop and report a blocker instead of claiming success if:

- `./run.sh` was not executed and no healthy real process was reused
- no Android device is connected/responding
- Appium is unavailable
- required app package/activity cannot be observed
- artifacts are missing or stale
- `CommandReady` or the required UI state is not reached in time
- page source/screenshot cannot be produced when needed
- the expected behavior is ambiguous
- required tool/resource self-check fails

## Examples

### Command-Like Behavior

For “test Help command output freshness,” command injection is one action in the plan:

```text
Plan:
- start/reuse real service
- inject ":help"
- read events/logs/status and runtime output evidence
- compare observed output against current command capability
- fix and retest if stale
```

Do not stop at “the inject script returned ok.” The Agent must inspect evidence.

### Non-Command Behavior

For “test behavior before entering a room,” no command is required:

```text
Plan:
- start/reuse real service
- observe Android current activity
- read status/events/logs
- request or inspect screenshot/page_source
- decide whether pre-room behavior matches the requirement
```

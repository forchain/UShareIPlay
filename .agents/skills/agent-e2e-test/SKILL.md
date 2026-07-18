---
name: agent-e2e-test
description: Use when the user asks to validate UShareIPlay behavior through the real running service, Android device, Appium session, UI state, command input, timers, database, logs, or runtime artifacts; also use after a change whose risk requires runtime evidence.
license: MIT
---

# Agent E2E Test

Run a real UShareIPlay workflow and make the pass/fail decision from fresh runtime evidence. The Agent owns the oracle and reasoning; scripts only provide deterministic actions.

## Hard Rules

- Unit tests, static inspection, and `scripts/agent_e2e.py --mode smoke` are not E2E. Smoke only self-checks the runner.
- For command tests, satisfy `CommandReady` before injection. Read [agent/preconditions.md](../../../agent/preconditions.md).
- Inject through the console/queue path (`.agent/commands/*.cmd` is the background channel). Do not create a second Appium session or mutate the device UI from the test agent.
- Treat a live PID, successful file injection, old logs, or a stale screenshot as insufficient evidence.
- Use structured events first; use logs, DB, page source, and screenshots to answer the test-specific oracle. Read [agent/event_taxonomy.md](../../../agent/event_taxonomy.md).

## Workflow

### 1. Define the oracle

Restate the request as one observable behavior. Classify the required surfaces: process, Android/ADB, UI, command/input, DB, logs, timers, recovery, artifacts, or a combination.

Write a compact plan containing:

- `trigger`: `manual` for an explicit user request, `auto` for a risk-based validation after tests;
- `scenario`: `dev` when code/config changed, `test` when validating the current build;
- preconditions and readiness gate;
- lifecycle action, input channel, evidence sources, timeout, and pass/fail criteria.

Completion criterion: the plan names the expected result and the evidence that would prove or disprove it.

### 2. Establish a freshness boundary

Before execution, record the current time and latest artifact run. For a reused process, verify all of these are current and connected:

- managed PID is alive and is the intended process;
- `status.json` and `events.jsonl` are fresh after the boundary or carry the current `run_id`;
- readiness matches the requested surface, including `CommandReady` anchors and `pipeline.ui_lock == unlocked` for command tests;
- the background input spool is writable.

Never promote an old `CommandReady`, log line, screenshot, or artifact to current evidence merely because the process is alive.

### 3. Self-check required capabilities

Run the self-check after the plan and before the real action. Request only the needed capabilities plus shared basics:

```bash
source .venv/bin/activate
python .agents/skills/agent-e2e-test/scripts/e2e_toolbelt.py doctor --needs process,input,adb,db,logs,artifacts
```

Remove categories the plan does not need. A non-zero result, missing config/run script, unavailable ADB, unreadable DB, or unwritable input/log/artifact path is a blocker. Resolve it or report it before starting the test.

Completion criterion: every capability named in the plan is available, or the run is explicitly reported blocked with the doctor output.

### 4. Select the lifecycle

- `dev`: restart the managed process and start the latest code with `start --scenario dev` (or the equivalent composed runner command).
- `test`: reuse the managed process only after the freshness and readiness checks above. If it is missing, run `start --scenario test`; if it is alive but unhealthy, run `stop` first and then `start --scenario test` because the toolbelt reuses any live PID.

After starting or reusing, wait for the readiness gate. If it does not arrive, use `request-dump` for a read-only page source/screenshot and stop as blocked; do not inject early.

### 5. Execute and collect evidence

Use the narrowest tool action that exercises the requested behavior:

```bash
python .agents/skills/agent-e2e-test/scripts/e2e_toolbelt.py inject --text ':help'
```

For composed command scenarios, `scripts/agent_e2e.py` may be used with `--scenario dev|test`, `--trigger auto|manual`, and `--command`; do not use its `--mode smoke` as the test.

Collect evidence from the same run boundary:

- `artifacts/<run_id>/events.jsonl` and `status.json`;
- relevant workspace logs;
- SQLite queries when the plan includes DB behavior;
- `page_source.xml` and `screenshot.png`, requested through `!dump` or `request-dump` when UI evidence is required;
- ADB activity, screenshot, or logcat when the plan requires device evidence.

For command E2E, assert the event chain `queue.enqueue → queue.drain.start → command.received → command.dispatch → command.result → queue.drain.end`, correlated to the current run/trace where available. For timers, also assert the relevant timer event or queue entry and the expected DB mutation. Follow the scenario-specific details in [agent/playbooks/command_e2e.md](../../../agent/playbooks/command_e2e.md) or [agent/playbooks/timer_e2e.md](../../../agent/playbooks/timer_e2e.md).

Completion criterion: each planned assertion has a cited artifact, event, log excerpt, DB result, or UI file from this run.

### 6. Decide and report

Pass only when the expected behavior is observed and every required assertion is backed by fresh, causally connected evidence. Report:

- trigger, scenario, lifecycle action, and injection channel;
- readiness state and anchors;
- assertion results for events, status, logs, DB, and UI as applicable;
- artifact paths and relevant timestamps/run IDs;
- failures, uncertainty, and the next action.

Report a blocker instead of success when the device/Appium/account/app state, process health, readiness, injection path, artifact freshness, expected behavior, or required evidence is missing. A deadline does not lower the evidence bar.

### 7. Recover or evolve

If evidence identifies a repo defect, fix it, run focused unit/script checks, then repeat the E2E with a fresh boundary. If the failure is environmental or the expected behavior is underspecified, preserve the evidence and report the blocker.

After a difficult or repeated run, record a reusable gap with `record-gap`. Use `agent/known_issues.md` for deferred failures, `agent/questions.md` for missing user input, or propose an infrastructure change when the missing signal is architectural. Add a tool only when it removes a repeatable observation/action gap; do not script away the Agent's pass/fail judgment.

## Toolbelt Quick Reference

```text
doctor --needs <csv>                 capability preflight
process-status                       managed PID and latest artifact run
start --scenario dev|test            restart or start/reuse service
stop                                 stop managed service
inject --text '...'                  background console/queue input
request-dump                         current process page source + screenshot
adb-devices | adb-current            device and focused activity
adb-screenshot --out <png>           device screenshot
adb-logcat --seconds <n> --out <txt> recent device logs
artifacts-latest | read-status       latest run paths/status
tail-events --limit <n>              structured runtime events
tail-logs --pattern <regex>          workspace logs
db-query --sql '...'                 SQLite evidence
record-gap --kind ...                durable testability feedback
```

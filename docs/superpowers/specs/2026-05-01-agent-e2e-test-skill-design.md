# agent-e2e-test Skill Design

## Problem

The current observability runner can validate its own smoke path, but smoke mode does not start `run.sh`, does not connect to Appium, and does not exercise the Android device. Reporting smoke success as end-to-end success is misleading.

The repository also lacks a callable skill for manual E2E testing. Existing `agent/` files are playbooks and knowledge assets, not an invokable skill entrypoint.

## Goal

Create an `agent-e2e-test` skill that agents can use when the user asks to manually test a real feature or command, such as checking whether `:help` output is stale.

The skill must enforce real runtime behavior:

- start or reuse the actual service through `./run.sh`
- inject commands through the approved console/queue path
- validate using runtime evidence from artifacts, logs, DB, and read-only UI dumps
- report blockers when Appium/device/runtime evidence is unavailable
- never treat `--mode smoke` as user-facing E2E validation

## Approach

Add a new skill at:

```text
.agents/skills/agent-e2e-test/SKILL.md
```

The skill will wrap the existing repo-native runner, `scripts/agent_e2e.py`, but will constrain how it is used.

Manual E2E tests must use full mode. Smoke mode is allowed only for runner self-checks and must be explicitly described as not exercising the Android device.

## Runtime Flow

```text
User asks to test a real feature
        |
        v
agent-e2e-test skill
        |
        v
Decide scenario:
  dev  -> restart managed process with ./run.sh
  test -> reuse healthy process, otherwise ./run.sh
        |
        v
Wait for real artifacts:
  status.json + events.jsonl + CommandReady
        |
        v
Inject command:
  stdin if runner owns process
  .agent/commands/*.cmd if reusing process
        |
        v
Assert evidence:
  events, logs, DB, page_source, screenshot
        |
        v
Pass, fix-and-retest, or blocker
```

## Skill Rules

The skill must:

- run from the repository root
- activate `.venv` before commands
- prefer `--scenario test --trigger manual` for user-requested tests
- use `--scenario dev --trigger auto` after risky implementation work
- execute real `./run.sh` indirectly through `scripts/agent_e2e.py --mode full`
- refuse to call a smoke run “E2E”
- use `.agent/commands/*.cmd` for reused-process injection
- request `!dump` when UI evidence is needed
- include the generated report path in the response

The skill must stop and report a blocker if:

- Appium is unavailable
- no Android device or required apps respond
- `status.json` / `events.jsonl` are not produced by the real service
- `CommandReady` is not reached within timeout
- command injection cannot be confirmed by `queue.enqueue`
- requested UI evidence cannot be dumped

## Help Command Example

For “test whether Help command output is stale,” the skill should run a real manual E2E command similar to:

```bash
source .venv/bin/activate
python scripts/agent_e2e.py \
  --mode full \
  --scenario test \
  --trigger manual \
  --trigger-reason "test Help command freshness" \
  --command ':help' \
  --dump-after-command \
  --expect-log-regex 'help|Help|帮助'
```

Static config inspection may be used as supporting evidence only after the runtime command has been executed.

## Testing

The skill itself is documentation and workflow, so verification should include:

- syntax/readability check of `SKILL.md`
- runner smoke self-check clearly labeled as non-E2E
- full manual E2E on a machine with Appium and Android device available
- evidence that `./run.sh` was invoked or a healthy managed process was reused

## Out of Scope

- Creating a second Appium session from the agent
- Mutating UI directly through ADB/Appium outside the running app process
- Treating unit tests, static config checks, or runner smoke mode as E2E success

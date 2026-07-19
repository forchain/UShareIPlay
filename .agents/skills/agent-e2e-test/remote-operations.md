# Remote E2E Operations

Remote access needs only `agent_e2e.remote.host` and `deploy_path` in the ignored `config.local.yaml`. SSH authentication comes from the local SSH agent or `~/.ssh/config`.

## State and logs

Run `remote-status` when production behavior, a stale remote-silence proof, or remote logs make the remote state relevant. `remote-logs` saves a read-only, redacted tail of recent `logs/`, `artifacts/`, and `.agent/` evidence in a local artifact directory.

## Pause and recovery

Before a local run that could contend for the shared device, use `remote-pause`. It discovers UShareIPlay processes rooted at the deployment path and sends `SIGINT`; a successful pause records a local session receipt. When it cannot pause every discovered process, preserve the status and logs, report the PIDs, and ask the user before `remote-force-stop --confirm`.

Restore only a remote service paused by the current E2E session. If automatic discovery cannot prove a safe restart method, leave it paused and report the recovery blocker.

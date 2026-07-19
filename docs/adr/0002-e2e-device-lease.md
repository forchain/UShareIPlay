# Device leases coordinate E2E ownership

UShareIPlay shares an Android/Appium target across local worktrees and production, so E2E coordination uses a user-wide device lease plus process-family discovery instead of a worktree PID file alone. Remote access remains optional and uses only SSH host and deployment path, preserving local-only validation while requiring fresh remote evidence when production state matters.

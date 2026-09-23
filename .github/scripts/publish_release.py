#!/usr/bin/env python3
"""Execute Git and GitHub API actions based on the release plan.

Supports force-overwriting colliding tags and existing releases.
Supports both dry-run simulation and real execution.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

COLLISION_NOTE = (
    "\n\n> ⚠️ **Note**: This release tag overwrites a legacy tag under the "
    "sequential merged PR count rule.\n"
)


def run_cmd(cmd: List[str], dry_run: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a shell command or simulate in dry-run mode."""
    print(f"[{'DRY-RUN' if dry_run else 'EXEC'}] {' '.join(cmd)}")
    if dry_run:
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def tag_exists_locally(tag_name: str) -> bool:
    """Check if a git tag exists locally."""
    try:
        proc = subprocess.run(["git", "tag", "-l", tag_name], capture_output=True, text=True, check=True)
        return tag_name in proc.stdout.splitlines()
    except Exception:
        return False


def _upsert_release(
    tag_name: str,
    title: str,
    body: str,
    is_collision: bool,
    dry_run: bool = False,
) -> None:
    """Create or overwrite GitHub release, ensuring collision note is included."""
    release_notes = body
    if is_collision and COLLISION_NOTE.strip() not in release_notes:
        release_notes = f"{release_notes.rstrip()}{COLLISION_NOTE}"

    if is_collision:
        try:
            run_cmd(["gh", "release", "edit", tag_name, "--title", title, "--notes", release_notes], dry_run=dry_run)
            print(f"✓ Overwrote existing GitHub release {tag_name}")
            return
        except subprocess.CalledProcessError as exc:
            err_msg = exc.stderr.strip() if exc.stderr else ""
            print(f"Warning: Release edit failed ({err_msg}), attempting recreation...", file=sys.stderr)

    try:
        run_cmd(["gh", "release", "create", tag_name, "--title", title, "--notes", release_notes], dry_run=dry_run)
        print(f"✓ Created GitHub release {tag_name}")
    except subprocess.CalledProcessError as exc:
        err_msg = exc.stderr.strip() if exc.stderr else ""
        print(f"Release create failed ({err_msg}), attempting overwrite via edit...", file=sys.stderr)
        if COLLISION_NOTE.strip() not in release_notes:
            release_notes = f"{release_notes.rstrip()}{COLLISION_NOTE}"
        run_cmd(["gh", "release", "edit", tag_name, "--title", title, "--notes", release_notes], dry_run=dry_run)
        print(f"✓ Overwrote existing GitHub release {tag_name}")


def execute_release_plan(plan: Dict[str, Any], dry_run: bool = False) -> None:
    """Execute tag creation and GitHub release with force-overwrite support."""
    current = plan.get("current_pr", {})
    tag_name = current.get("tag_name")
    release_title = current.get("release_title")
    release_body = current.get("release_body")
    pr_id = current.get("pr_id")
    pr_count = current.get("pr_count", 0)
    is_collision = bool(plan.get("is_collision", False))

    if not tag_name:
        raise ValueError("Missing tag_name in release plan")

    print(f"=== Processing Release for PR #{pr_id} (Merged PR #{pr_count}, Tag: {tag_name}) ===")
    if is_collision:
        print(f"⚠️ Tag {tag_name} already exists. Executing force overwrite.")

    # 1. Create and push Git tag
    git_tag_cmd = ["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"]
    git_push_cmd = ["git", "push", "origin", tag_name]

    if is_collision or (not dry_run and tag_exists_locally(tag_name)):
        git_tag_cmd = ["git", "tag", "-f", "-a", tag_name, "-m", f"Release {tag_name}"]
        git_push_cmd.append("--force")

    try:
        run_cmd(git_tag_cmd, dry_run=dry_run)
        run_cmd(git_push_cmd, dry_run=dry_run)
        print(f"✓ Tag {tag_name} pushed to origin")
    except subprocess.CalledProcessError as exc:
        print(f"Warning: Git tag creation or push error: {exc.stderr}", file=sys.stderr)

    # 2. Upsert GitHub Release
    _upsert_release(
        tag_name=tag_name,
        title=release_title,
        body=release_body,
        is_collision=is_collision,
        dry_run=dry_run,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish release based on calculated plan.")
    parser.add_argument("--plan", help="Path to plan JSON file", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Simulate without executing API calls")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.exists():
        print(f"Plan file not found: {plan_path}", file=sys.stderr)
        return 1

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    execute_release_plan(plan, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())

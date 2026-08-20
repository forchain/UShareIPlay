#!/usr/bin/env python3
"""Execute Git and GitHub API actions based on the release plan.

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


def run_cmd(cmd: List[str], dry_run: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a shell command or simulate in dry-run mode."""
    print(f"[{'DRY-RUN' if dry_run else 'EXEC'}] {' '.join(cmd)}")
    if dry_run:
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def execute_release_plan(plan: Dict[str, Any], dry_run: bool = False) -> None:
    """Execute tag creation, GitHub release, and out-of-order backfills."""
    current = plan.get("current_pr", {})
    tag_name = current.get("tag_name")
    release_title = current.get("release_title")
    release_body = current.get("release_body")
    pr_id = current.get("pr_id")

    if not tag_name:
        raise ValueError("Missing tag_name in release plan")

    print(f"=== Processing Release for PR #{pr_id} (Tag: {tag_name}) ===")

    # 1. Create and push Git tag for current PR
    try:
        run_cmd(["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"], dry_run=dry_run)
        run_cmd(["git", "push", "origin", tag_name], dry_run=dry_run)
    except subprocess.CalledProcessError as exc:
        print(f"Warning: Git tag creation or push error: {exc.stderr}", file=sys.stderr)

    # 2. Create GitHub Release
    try:
        run_cmd(
            [
                "gh",
                "release",
                "create",
                tag_name,
                "--title",
                release_title,
                "--notes",
                release_body,
            ],
            dry_run=dry_run,
        )
        print(f"✓ Created GitHub release {tag_name}")
    except subprocess.CalledProcessError as exc:
        print(f"Error creating release: {exc.stderr}", file=sys.stderr)
        raise

    # 3. Handle out-of-order backfill if applicable
    if plan.get("out_of_order") and plan.get("higher_pr_update"):
        higher = plan["higher_pr_update"]
        higher_pr_id = higher["pr_id"]
        old_tag = higher["old_tag"]
        new_tag = higher["new_tag"]
        new_release_title = higher["new_release_title"]
        pr_body_append = higher["pr_body_append"]

        print(f"=== Backfilling Out-of-Order PR #{higher_pr_id} ({old_tag} -> {new_tag}) ===")

        # Create new tag pointing to old tag / release commit
        try:
            run_cmd(["git", "tag", "-a", new_tag, old_tag, "-m", f"Bump patch to {new_tag}"], dry_run=dry_run)
            run_cmd(["git", "push", "origin", new_tag], dry_run=dry_run)
        except subprocess.CalledProcessError as exc:
            print(f"Warning: Backfill tag creation/push error: {exc.stderr}", file=sys.stderr)

        # Update existing release tag & title
        try:
            run_cmd(
                [
                    "gh",
                    "release",
                    "edit",
                    old_tag,
                    "--tag",
                    new_tag,
                    "--title",
                    new_release_title,
                ],
                dry_run=dry_run,
            )
            print(f"✓ Updated GitHub release from {old_tag} to {new_tag}")
        except subprocess.CalledProcessError as exc:
            print(f"Warning: Updating release {old_tag} failed: {exc.stderr}", file=sys.stderr)

        # Update PR description (body)
        try:
            if not dry_run:
                # Fetch existing body
                view_proc = subprocess.run(
                    ["gh", "pr", "view", str(higher_pr_id), "--json", "body", "-q", ".body"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                existing_body = view_proc.stdout.rstrip()
                updated_body = f"{existing_body}{pr_body_append}"
                subprocess.run(
                    ["gh", "pr", "edit", str(higher_pr_id), "--body", updated_body],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            else:
                print(f"[DRY-RUN] gh pr edit {higher_pr_id} --body <existing_body + backfill_note>")
            print(f"✓ Updated PR #{higher_pr_id} description with backfill reference")
        except subprocess.CalledProcessError as exc:
            print(f"Warning: Updating PR #{higher_pr_id} description failed: {exc.stderr}", file=sys.stderr)


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

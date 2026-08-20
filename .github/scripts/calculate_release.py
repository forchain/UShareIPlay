#!/usr/bin/env python3
"""Calculate version tags, release metadata, and out-of-order PR backfills.

Versioning Rule:
  Format: v<Major>.<PR_ID>.<commits_count>
  Major: Read from `VERSION` file in repo root (defaults to 0).
  Minor: Merged PR ID.
  Patch: Total commit count in the PR.

Out-of-order Rule:
  When a lower PR ID merges after a higher PR ID was already released,
  1. The lower PR gets tagged and released with its own v<Major>.<lower_PR>.<commits>.
  2. The highest existing PR release has its patch increased by the lower PR's commit count.
  3. The highest PR's description on GitHub is updated referencing the lower PR.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

TAG_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_major_version(content: Optional[str]) -> int:
    """Parse major version integer from string content or file."""
    if not content:
        return 0
    text = content.strip()
    if not text:
        return 0
    # Match the first integer found in text
    match = re.search(r"(\d+)", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return 0
    return 0


def calculate_current_release(
    major: int,
    pr_id: int,
    commits: int,
    pr_title: str,
    pr_body: str,
    pr_author: str,
    repo_name: str,
) -> Dict[str, Any]:
    """Calculate tag name and release notes for the current PR."""
    tag_name = f"v{major}.{pr_id}.{commits}"
    release_title = f"{tag_name} - {pr_title}"

    sanitized_body = (pr_body or "").strip()
    if not sanitized_body:
        sanitized_body = "_No description provided in PR._"

    release_body = (
        f"## What's Changed\n\n"
        f"* **{pr_title}** by @{pr_author} in #{pr_id}\n\n"
        f"### PR Details\n"
        f"{sanitized_body}\n\n"
        f"---\n"
        f"**Merged Commit Count**: {commits} commit(s)\n"
    )
    if repo_name:
        release_body += f"**PR Link**: https://github.com/{repo_name}/pull/{pr_id}\n"

    return {
        "tag_name": tag_name,
        "release_title": release_title,
        "release_body": release_body,
    }


def detect_and_calculate_backfill(
    current_major: int,
    current_pr_id: int,
    current_commits: int,
    existing_releases: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Detect if higher PR IDs exist in releases, and calculate backfill for the highest one."""
    higher_candidates = []

    for item in existing_releases:
        tag = item.get("tagName") or item.get("tag_name") or ""
        match = TAG_PATTERN.match(tag.strip())
        if not match:
            continue
        rel_major = int(match.group(1))
        rel_pr_id = int(match.group(2))
        rel_patch = int(match.group(3))

        if rel_major == current_major and rel_pr_id > current_pr_id:
            higher_candidates.append(
                {
                    "pr_id": rel_pr_id,
                    "old_tag": tag.strip(),
                    "old_patch": rel_patch,
                    "release_name": item.get("name") or "",
                }
            )

    if not higher_candidates:
        return None

    # Pick the highest PR ID
    highest = max(higher_candidates, key=lambda x: x["pr_id"])
    new_patch = highest["old_patch"] + current_commits
    new_tag = f"v{current_major}.{highest['pr_id']}.{new_patch}"

    # Extract base title if possible
    old_name = highest["release_name"]
    clean_title = old_name
    if " - " in old_name:
        clean_title = old_name.split(" - ", 1)[1]
    new_release_title = f"{new_tag} - {clean_title}" if clean_title else new_tag

    pr_body_append = (
        f"\n\n---\n"
        f"> 📌 **关联合并追溯**: 后续已合并包含 {current_commits} 个 commit 的 PR #{current_pr_id}，"
        f"最新小版本升级为 `{new_tag}`。"
    )

    return {
        "pr_id": highest["pr_id"],
        "old_tag": highest["old_tag"],
        "new_tag": new_tag,
        "new_release_title": new_release_title,
        "commits_added": current_commits,
        "pr_body_append": pr_body_append,
    }


def plan_release(
    major_str: Optional[str],
    event_payload: Dict[str, Any],
    existing_releases: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the complete execution plan."""
    major = parse_major_version(major_str)
    pr = event_payload.get("pull_request", {})
    repo = event_payload.get("repository", {})

    pr_id = pr.get("number") or event_payload.get("number") or 0
    commits = pr.get("commits") or 1
    title = pr.get("title") or "Merge Pull Request"
    body = pr.get("body") or ""
    author = pr.get("user", {}).get("login") or "github-actions[bot]"
    repo_name = repo.get("full_name") or os.environ.get("GITHUB_REPOSITORY", "")

    current_rel = calculate_current_release(
        major=major,
        pr_id=pr_id,
        commits=commits,
        pr_title=title,
        pr_body=body,
        pr_author=author,
        repo_name=repo_name,
    )

    backfill = detect_and_calculate_backfill(
        current_major=major,
        current_pr_id=pr_id,
        current_commits=commits,
        existing_releases=existing_releases,
    )

    return {
        "major": major,
        "current_pr": {
            "pr_id": pr_id,
            "commits": commits,
            "title": title,
            "author": author,
            "tag_name": current_rel["tag_name"],
            "release_title": current_rel["release_title"],
            "release_body": current_rel["release_body"],
        },
        "out_of_order": backfill is not None,
        "higher_pr_update": backfill,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate PR tag and release metadata.")
    parser.add_argument("--version-file", help="Path to VERSION file", default="VERSION")
    parser.add_argument("--event-path", help="Path to GITHUB_EVENT_PATH json file")
    parser.add_argument("--releases-json", help="Path to existing releases JSON or raw JSON string")
    parser.add_argument("--output", help="Output plan JSON file path")
    args = parser.parse_args()

    # Read VERSION
    major_content = None
    if args.version_file and Path(args.version_file).exists():
        major_content = Path(args.version_file).read_text(encoding="utf-8")

    # Read Event Path
    event_path = args.event_path or os.environ.get("GITHUB_EVENT_PATH")
    event_payload: Dict[str, Any] = {}
    if event_path and Path(event_path).exists():
        event_payload = json.loads(Path(event_path).read_text(encoding="utf-8"))

    # Read Existing Releases
    existing_releases: List[Dict[str, Any]] = []
    if args.releases_json:
        if Path(args.releases_json).exists():
            existing_releases = json.loads(Path(args.releases_json).read_text(encoding="utf-8"))
        else:
            try:
                existing_releases = json.loads(args.releases_json)
            except Exception:
                existing_releases = []

    plan = plan_release(
        major_str=major_content,
        event_payload=event_payload,
        existing_releases=existing_releases,
    )

    formatted_json = json.dumps(plan, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(formatted_json, encoding="utf-8")
        print(f"Plan written to {args.output}")
    else:
        print(formatted_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())

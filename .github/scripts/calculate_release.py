#!/usr/bin/env python3
"""Calculate version tags and release metadata based on merged PR count.

Versioning Rule:
  Format: v<Major>.<Merged_PR_Count>.<commits_count>
  Major: Read from `VERSION` file in repo root (defaults to 0).
  Minor: Sequential merged PR count on target base branch.
  Patch: Total commit count in the PR.

Tag Overwrite:
  If a newly calculated tag collides with a legacy tag generated under previous
  rules, it is flagged for force-overwrite.
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
    match = re.search(r"(\d+)", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return 0
    return 0


def count_merged_prs(
    merged_prs: List[Dict[str, Any]],
    current_pr_id: int,
) -> int:
    """Calculate the sequential merged PR count including the current PR."""
    pr_numbers = set()
    for item in merged_prs:
        if isinstance(item, dict) and "number" in item:
            pr_numbers.add(item["number"])
        elif isinstance(item, int):
            pr_numbers.add(item)

    if current_pr_id > 0:
        pr_numbers.add(current_pr_id)

    return len(pr_numbers) if pr_numbers else 1


def check_tag_collision(
    tag_name: str,
    existing_releases: List[Dict[str, Any]],
    existing_git_tags: Optional[List[str]] = None,
) -> bool:
    """Check if the tag name already exists in releases or git tags."""
    target = tag_name.strip()
    for item in existing_releases:
        tag = item.get("tagName") or item.get("tag_name") or ""
        if tag.strip() == target:
            return True
    if existing_git_tags:
        for git_tag in existing_git_tags:
            if git_tag.strip() == target:
                return True
    return False


def calculate_current_release(
    major: int,
    pr_count: int,
    commits: int,
    pr_id: int,
    pr_title: str,
    pr_body: str,
    pr_author: str,
    repo_name: str,
    is_collision: bool = False,
) -> Dict[str, Any]:
    """Calculate tag name and release notes for the current PR."""
    tag_name = f"v{major}.{pr_count}.{commits}"
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

    if is_collision:
        release_body += (
            f"\n> ⚠️ **Note**: This release tag overwrites a legacy tag under the "
            f"sequential merged PR count rule.\n"
        )

    return {
        "tag_name": tag_name,
        "release_title": release_title,
        "release_body": release_body,
    }


def plan_release(
    major_str: Optional[str],
    event_payload: Dict[str, Any],
    existing_releases: List[Dict[str, Any]],
    merged_prs: Optional[List[Dict[str, Any]]] = None,
    existing_git_tags: Optional[List[str]] = None,
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

    pr_count = count_merged_prs(merged_prs or [], pr_id)

    preliminary_tag = f"v{major}.{pr_count}.{commits}"
    is_collision = check_tag_collision(preliminary_tag, existing_releases, existing_git_tags)

    current_rel = calculate_current_release(
        major=major,
        pr_count=pr_count,
        commits=commits,
        pr_id=pr_id,
        pr_title=title,
        pr_body=body,
        pr_author=author,
        repo_name=repo_name,
        is_collision=is_collision,
    )

    return {
        "major": major,
        "current_pr": {
            "pr_id": pr_id,
            "pr_count": pr_count,
            "commits": commits,
            "title": title,
            "author": author,
            "tag_name": current_rel["tag_name"],
            "release_title": current_rel["release_title"],
            "release_body": current_rel["release_body"],
        },
        "is_collision": is_collision,
    }


def _load_json_data(file_or_raw: Optional[str]) -> List[Any]:
    """Load JSON from a file path if exists, else parse as raw JSON string."""
    if not file_or_raw:
        return []
    path = Path(file_or_raw)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
    try:
        return json.loads(file_or_raw)
    except Exception:
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate PR tag and release metadata.")
    parser.add_argument("--version-file", help="Path to VERSION file", default="VERSION")
    parser.add_argument("--event-path", help="Path to GITHUB_EVENT_PATH json file")
    parser.add_argument("--releases-json", help="Path to existing releases JSON or raw JSON string")
    parser.add_argument("--merged-prs-json", help="Path to merged PRs list JSON or raw JSON string")
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

    existing_releases = _load_json_data(args.releases_json)
    merged_prs = _load_json_data(args.merged_prs_json)

    plan = plan_release(
        major_str=major_content,
        event_payload=event_payload,
        existing_releases=existing_releases,
        merged_prs=merged_prs,
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

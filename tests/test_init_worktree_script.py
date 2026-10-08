"""Behavioural tests for scripts/init_worktree.sh (#411).

Every test builds a throwaway git environment under ``tmp_path`` -- a bare
``origin``, a main clone that keeps ``main`` checked out (the real topology that
makes ``git fetch origin main:main`` fail), a second clone used to push new
commits upstream, and a linked feature worktree. The script under test is
copied into those worktrees and executed for real; assertions read git and
filesystem state instead of the script's text.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SOURCE = REPO_ROOT / "scripts" / "init_worktree.sh"

pytestmark = [
    pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-only shell script"),
    pytest.mark.skipif(shutil.which("git") is None, reason="git is required"),
]


def _make_env(root: Path) -> dict:
    """Isolate git from the developer's real configuration."""
    home = root / "home"
    home.mkdir(exist_ok=True)
    empty_gitconfig = root / "gitconfig"
    empty_gitconfig.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    env.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": str(empty_gitconfig),
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_EDITOR": "true",
        }
    )
    return env


class Sandbox:
    """origin (bare) + main clone (main checked out) + feature worktree."""

    def __init__(self, root: Path):
        self.root = root
        self.env = _make_env(root)
        self.origin = root / "origin.git"
        self.main = root / "main-clone"
        self.other = root / "other-clone"
        self.feature = root / "feature-worktree"
        self.feature_branch = "feat/411-worktree-init"
        self._build()

    # -- plumbing ---------------------------------------------------------
    def _configure(self, repo: Path) -> None:
        """Give a sandbox clone the identity and signing policy commits need."""
        for key, value in (
            ("user.email", "fixture@example.com"),
            ("user.name", "Worktree Fixture"),
            ("commit.gpgsign", "false"),
        ):
            self.git("config", key, value, cwd=repo)

    def git(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            env=self.env,
            capture_output=True,
            text=True,
            check=check,
        )

    def out(self, *args: str, cwd: Path) -> str:
        return self.git(*args, cwd=cwd).stdout.strip()

    def rev(self, repo: Path, ref: str) -> str:
        return self.out("rev-parse", "--verify", ref, cwd=repo)

    def commit(self, repo: Path, filename: str, content: str, message: str) -> str:
        (repo / filename).write_text(content, encoding="utf-8")
        self.git("add", filename, cwd=repo)
        self.git("commit", "-m", message, cwd=repo)
        return self.rev(repo, "HEAD")

    # -- construction -----------------------------------------------------
    def _build(self) -> None:
        self.git("init", "--bare", "-q", str(self.origin), cwd=self.root)
        self.git("-C", str(self.origin), "symbolic-ref", "HEAD", "refs/heads/main", cwd=self.root)
        self.git("clone", "-q", str(self.origin), str(self.main), cwd=self.root)
        self._configure(self.main)

        self.commit(self.main, "shared.txt", "base\n", "base")
        self.git("push", "-q", "-u", "origin", "main", cwd=self.main)

        self.git(
            "worktree",
            "add",
            "-q",
            "-b",
            self.feature_branch,
            str(self.feature),
            cwd=self.main,
        )

        # The real script ships in both worktrees; local user config is shared
        # across linked worktrees, so commits work inside the feature worktree.
        for repo in (self.main, self.feature):
            script = repo / "scripts" / "init_worktree.sh"
            script.parent.mkdir(exist_ok=True)
            shutil.copy2(SCRIPT_SOURCE, script)
            script.chmod(0o755)

    # -- upstream simulation ---------------------------------------------
    def advance_main(self, filename: str, content: str, message: str) -> str:
        """Push a new commit to origin/main from a second clone."""
        self.git("clone", "-q", str(self.origin), str(self.other), cwd=self.root)
        self._configure(self.other)
        sha = self.commit(self.other, filename, content, message)
        self.git("push", "-q", "origin", "main", cwd=self.other)
        return sha

    # -- driving the script ----------------------------------------------
    def script_path(self, repo: Path) -> Path:
        return repo / "scripts" / "init_worktree.sh"

    def run_script(self, *args: str, cwd: Path = None, script_repo: Path = None) -> subprocess.CompletedProcess:
        """Run the copy of the script owned by ``script_repo`` from ``cwd``."""
        script_repo = script_repo or self.feature
        return subprocess.run(
            [str(self.script_path(script_repo)), *args],
            cwd=str(cwd or script_repo),
            env=self.env,
            capture_output=True,
            text=True,
        )

    # -- assertions helpers ----------------------------------------------
    def rebase_in_progress(self, repo: Path) -> bool:
        for state in ("rebase-merge", "rebase-apply"):
            path = self.out("rev-parse", "--git-path", state, cwd=repo)
            if Path(path).exists():
                return True
        return False


@pytest.fixture
def sandbox(tmp_path) -> Sandbox:
    return Sandbox(tmp_path)


# (a) local main is checked out in the main worktree and gets fast-forwarded
def test_fast_forwards_local_main_branch_that_is_checked_out(sandbox: Sandbox):
    origin_sha = sandbox.advance_main("from_main.txt", "main change\n", "main: add file")

    result = sandbox.run_script()

    assert result.returncode == 0, result.stdout + result.stderr
    assert sandbox.rev(sandbox.main, "main") == origin_sha
    assert (sandbox.main / "from_main.txt").read_text(encoding="utf-8") == "main change\n"


# (b) the feature branch is rebased onto the new main
def test_rebases_feature_branch_onto_advanced_main(sandbox: Sandbox):
    sandbox.commit(sandbox.feature, "feature.txt", "feature work\n", "feat: add file")
    feature_sha = sandbox.rev(sandbox.feature, "HEAD")
    main_sha = sandbox.advance_main("from_main.txt", "main change\n", "main: add file")

    result = sandbox.run_script()

    assert result.returncode == 0, result.stdout + result.stderr
    rebased_sha = sandbox.rev(sandbox.feature, "HEAD")
    assert rebased_sha != feature_sha
    parents = sandbox.out("rev-list", "--parents", "-n", "1", "HEAD", cwd=sandbox.feature).split()
    assert parents[1] == main_sha
    assert (sandbox.feature / "feature.txt").exists()
    assert (sandbox.feature / "from_main.txt").exists()


# (c) rebase conflict: loud failure, rebase aborted, branch left untouched
def test_rebase_conflict_aborts_and_leaves_branch_intact(sandbox: Sandbox):
    feature_sha = sandbox.commit(sandbox.feature, "shared.txt", "feature side\n", "feat: edit")
    sandbox.advance_main("shared.txt", "main side\n", "main: conflicting edit")

    result = sandbox.run_script()

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "conflict" in output.lower()
    assert "abort" in output.lower()
    assert sandbox.rev(sandbox.feature, "HEAD") == feature_sha
    assert sandbox.out("rev-parse", "--abbrev-ref", "HEAD", cwd=sandbox.feature) == sandbox.feature_branch
    assert sandbox.rev(sandbox.feature, sandbox.feature_branch) == feature_sha
    assert not sandbox.rebase_in_progress(sandbox.feature)
    assert sandbox.out("diff", "--name-only", "--diff-filter=U", cwd=sandbox.feature) == ""
    assert "rebase" not in sandbox.out("status", "--porcelain", cwd=sandbox.feature).lower()
    assert (sandbox.feature / "shared.txt").read_text(encoding="utf-8") == "feature side\n"


# (c2) a conflicting path containing a space must print as one intact line
def test_conflict_output_keeps_paths_with_spaces_intact(sandbox: Sandbox):
    filename = "my notes.txt"
    sandbox.commit(sandbox.feature, filename, "feature side\n", "feat: edit spaced file")
    sandbox.advance_main(filename, "main side\n", "main: conflicting spaced edit")

    result = sandbox.run_script()

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    printed = [line.strip() for line in output.splitlines()]
    assert any(line.endswith("conflicting files:") for line in printed), output
    assert filename in printed, output
    # the unquoted expansion split the path into two entries
    assert "my" not in printed, output
    assert "notes.txt" not in printed, output


# (c3) every conflicting path gets its own indented line, not just the first
def test_conflict_output_indents_every_path(sandbox: Sandbox):
    # Both files must conflict inside a single feature commit: git halts the
    # rebase at the first conflicted commit, so a second commit would never be
    # reached and only one path would ever be unmerged.
    for path in ("alpha.txt", "beta.txt"):
        (sandbox.feature / path).write_text("feature side\n", encoding="utf-8")
    sandbox.git("add", "alpha.txt", "beta.txt", cwd=sandbox.feature)
    sandbox.git("commit", "-m", "feat: both files", cwd=sandbox.feature)

    # advance_main clones origin afresh, so only the first push may use it;
    # the second conflicting change rides on that same second clone.
    sandbox.advance_main("alpha.txt", "main side\n", "main: conflicting alpha")
    sandbox.commit(sandbox.other, "beta.txt", "main side\n", "main: conflicting beta")
    sandbox.git("push", "-q", "origin", "main", cwd=sandbox.other)

    result = sandbox.run_script()

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    indented = [line for line in output.splitlines() if line.startswith("  ")]
    assert indented == ["  alpha.txt", "  beta.txt"], output


# (d) symlink points at the main repo's config.local.yaml
def test_creates_config_symlink_to_main_repo(sandbox: Sandbox):
    main_cfg = sandbox.main / "config.local.yaml"
    main_cfg.write_text('device:\n  name: "127.0.0.1:5555"\n', encoding="utf-8")

    result = sandbox.run_script()

    assert result.returncode == 0, result.stdout + result.stderr
    link = sandbox.feature / "config.local.yaml"
    assert link.is_symlink()
    assert Path(os.readlink(link)) == main_cfg
    assert link.read_text(encoding="utf-8") == main_cfg.read_text(encoding="utf-8")


# (e) running twice changes nothing
def test_second_run_is_idempotent(sandbox: Sandbox):
    sandbox.main.joinpath("config.local.yaml").write_text("device: {}\n", encoding="utf-8")
    assert sandbox.run_script().returncode == 0

    link = sandbox.feature / "config.local.yaml"
    target_after_first = os.readlink(link)
    head_after_first = sandbox.rev(sandbox.feature, "HEAD")
    status_after_first = sandbox.out("status", "--porcelain", cwd=sandbox.feature)

    second = sandbox.run_script()

    assert second.returncode == 0, second.stdout + second.stderr
    assert "already" in second.stdout.lower()
    assert link.is_symlink()
    assert os.readlink(link) == target_after_first
    assert sandbox.rev(sandbox.feature, "HEAD") == head_after_first
    assert sandbox.out("status", "--porcelain", cwd=sandbox.feature) == status_after_first


# (f) no config in the main repo: friendly hint, still a success
def test_missing_main_config_is_a_friendly_hint(sandbox: Sandbox):
    result = sandbox.run_script()

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "config.local.yaml" in output
    assert not (sandbox.feature / "config.local.yaml").exists()
    assert not (sandbox.feature / "config.local.yaml").is_symlink()


# (g) --help documents the symlink conflict policy
def test_help_exits_zero_and_documents_policy(sandbox: Sandbox):
    result = sandbox.run_script("--help")

    output = (result.stdout + result.stderr).lower()
    assert result.returncode == 0
    assert "usage" in output
    assert "--force" in output
    assert "config.local.yaml" in output


# (h) a regular file is never destroyed silently; --force backs it up
def test_refuses_to_clobber_regular_file_unless_forced(sandbox: Sandbox):
    sandbox.main.joinpath("config.local.yaml").write_text("device: {name: main}\n", encoding="utf-8")
    existing = sandbox.feature / "config.local.yaml"
    existing.write_text("device: {name: mine}\n", encoding="utf-8")

    refused = sandbox.run_script()

    assert refused.returncode != 0
    assert "config.local.yaml" in (refused.stdout + refused.stderr)
    assert existing.is_file() and not existing.is_symlink()
    assert existing.read_text(encoding="utf-8") == "device: {name: mine}\n"

    forced = sandbox.run_script("--force")

    assert forced.returncode == 0, forced.stdout + forced.stderr
    assert existing.is_symlink()
    assert Path(os.readlink(existing)) == sandbox.main / "config.local.yaml"
    backups = sorted(sandbox.feature.glob("config.local.yaml.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "device: {name: mine}\n"


# (i) a symlink pointing somewhere else is refreshed
def test_refreshes_symlink_pointing_elsewhere(sandbox: Sandbox):
    sandbox.main.joinpath("config.local.yaml").write_text("device: {}\n", encoding="utf-8")
    elsewhere = sandbox.root / "elsewhere.yaml"
    elsewhere.write_text("device: {}\n", encoding="utf-8")
    link = sandbox.feature / "config.local.yaml"
    link.symlink_to(elsewhere)

    result = sandbox.run_script()

    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(os.readlink(link)) == sandbox.main / "config.local.yaml"


# (j) runnable from any directory; main repo lives at an arbitrary path
def test_runs_from_outside_the_worktree(sandbox: Sandbox):
    sandbox.main.joinpath("config.local.yaml").write_text("device: {}\n", encoding="utf-8")

    result = sandbox.run_script(cwd=sandbox.root)

    assert result.returncode == 0, result.stdout + result.stderr
    link = sandbox.feature / "config.local.yaml"
    assert Path(os.readlink(link)) == sandbox.main / "config.local.yaml"


# (k) running inside the main worktree never creates a self-referential link
def test_main_worktree_run_skips_symlink(sandbox: Sandbox):
    sandbox.main.joinpath("config.local.yaml").write_text("device: {}\n", encoding="utf-8")

    result = sandbox.run_script(cwd=sandbox.main, script_repo=sandbox.main)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (sandbox.main / "config.local.yaml").is_symlink()


# (l) a dirty main worktree is reported, not dumped as a raw git error
def test_dirty_main_worktree_reports_a_clear_message(sandbox: Sandbox):
    sandbox.main.joinpath("shared.txt").write_text("uncommitted local edit\n", encoding="utf-8")
    sandbox.advance_main("shared.txt", "upstream edit\n", "main: conflicting edit")

    result = sandbox.run_script()

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "main" in output.lower()
    assert sandbox.out("status", "--porcelain", cwd=sandbox.main) != ""


# (m) a diverged local main is left alone with a clear message
def test_diverged_local_main_is_left_alone(sandbox: Sandbox):
    local_sha = sandbox.commit(sandbox.main, "local_only.txt", "local\n", "local: divergence")
    sandbox.advance_main("from_main.txt", "main change\n", "main: add file")

    result = sandbox.run_script()

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert sandbox.rev(sandbox.main, "main") == local_sha
    assert (sandbox.feature / "from_main.txt").exists()
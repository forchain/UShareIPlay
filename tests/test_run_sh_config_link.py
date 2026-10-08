"""Behavioural tests for run.sh's ``ensure_config`` local-config wiring.

Each test builds a throwaway repository under ``tmp_path``: a main clone that
keeps ``main`` checked out, plus a linked feature worktree. ``run.sh`` is copied
into both worktrees and ``ensure_config`` is invoked for real by sourcing it, so
assertions read filesystem state instead of the script's text.

``HOME`` is redirected into the sandbox, so any absolute path baked into
``run.sh`` -- the hardcoded ``$HOME/github.com/forchain/UShareIPlay`` that
``ensure_config`` used to copy from -- cannot exist. That is what makes the
"links from any clone location" test a real regression test.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SH_SOURCE = REPO_ROOT / "run.sh"

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
        }
    )
    return env


class Sandbox:
    """A main clone (main checked out) plus a linked feature worktree."""

    def __init__(self, root: Path):
        self.root = root
        self.env = _make_env(root)
        self.main = root / "some-deeply-nested-clone-dir"
        self.feature = root / "feature-worktree"
        self._build()

    def git(self, *args: str, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )

    def _build(self) -> None:
        self.main.mkdir(parents=True)
        self.git("init", "-q", "-b", "main", cwd=self.main)
        for key, value in (
            ("user.email", "fixture@example.com"),
            ("user.name", "Worktree Fixture"),
            ("commit.gpgsign", "false"),
        ):
            self.git("config", key, value, cwd=self.main)

        (self.main / "config.yaml").write_text("appium:\n  host: 127.0.0.1\n", encoding="utf-8")
        self.git("add", "config.yaml", cwd=self.main)
        self.git("commit", "-m", "base", cwd=self.main)

        self.git("worktree", "add", "-q", "-b", "feat/411", str(self.feature), cwd=self.main)

        # run.sh derives ROOT_DIR from BASH_SOURCE, so each worktree needs its
        # own copy for the test to target it.
        for repo in (self.main, self.feature):
            shutil.copy2(RUN_SH_SOURCE, repo / "run.sh")

    # -- driving run.sh ---------------------------------------------------
    def ensure_config(self, repo: Path) -> subprocess.CompletedProcess:
        """Source run.sh in ``repo`` and run ``ensure_config`` there."""
        return subprocess.run(
            ["bash", "-c", "source ./run.sh && ensure_config"],
            cwd=str(repo),
            env=self.env,
            capture_output=True,
            text=True,
        )


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def _write_main_config(sandbox: Sandbox, body: str = 'device:\n  name: "10.0.0.2:5555"\n') -> Path:
    path = sandbox.main / "config.local.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# -- the regression this ticket exists for ------------------------------------
def test_links_main_config_from_any_clone_path(sandbox: Sandbox):
    """The main repo lives nowhere near $HOME/github.com/forchain/UShareIPlay."""
    main_cfg = _write_main_config(sandbox)

    result = sandbox.ensure_config(sandbox.feature)

    link = sandbox.feature / "config.local.yaml"
    assert result.returncode == 0, result.stdout + result.stderr
    assert link.is_symlink(), result.stdout + result.stderr
    assert Path(os.readlink(link)) == main_cfg
    assert link.read_text(encoding="utf-8") == main_cfg.read_text(encoding="utf-8")


def test_run_sh_contains_no_hardcoded_repository_path():
    """The old copy source was a literal absolute path baked into run.sh."""
    assert "github.com/forchain/UShareIPlay" not in RUN_SH_SOURCE.read_text(encoding="utf-8")


# -- policy -------------------------------------------------------------------
def test_second_run_is_idempotent(sandbox: Sandbox):
    _write_main_config(sandbox)

    first = sandbox.ensure_config(sandbox.feature)
    link = sandbox.feature / "config.local.yaml"
    target_after_first = os.readlink(link)

    second = sandbox.ensure_config(sandbox.feature)

    assert first.returncode == 0 and second.returncode == 0
    assert link.is_symlink()
    assert os.readlink(link) == target_after_first


def test_existing_regular_file_is_left_alone(sandbox: Sandbox):
    """A hand-written worktree config is never clobbered."""
    _write_main_config(sandbox)
    own = sandbox.feature / "config.local.yaml"
    own.write_text('device:\n  name: "worktree-only:5555"\n', encoding="utf-8")

    result = sandbox.ensure_config(sandbox.feature)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not own.is_symlink()
    assert own.read_text(encoding="utf-8") == 'device:\n  name: "worktree-only:5555"\n'


def test_main_worktree_does_not_link_to_itself(sandbox: Sandbox):
    """With no config of its own, the main worktree must not self-link."""
    result = sandbox.ensure_config(sandbox.main)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (sandbox.main / "config.local.yaml").exists()
    assert "config.yaml" in result.stdout


def test_missing_main_config_falls_back_to_config_yaml(sandbox: Sandbox):
    result = sandbox.ensure_config(sandbox.feature)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (sandbox.feature / "config.local.yaml").exists()
    assert "config.yaml" in result.stdout


def test_dangling_symlink_is_replaced(sandbox: Sandbox):
    """A link left over from an unmounted main repo must not block re-linking."""
    _write_main_config(sandbox)
    link = sandbox.feature / "config.local.yaml"
    link.symlink_to(sandbox.root / "gone" / "config.local.yaml")
    assert link.is_symlink() and not link.exists()

    result = sandbox.ensure_config(sandbox.feature)

    main_cfg = sandbox.main / "config.local.yaml"
    assert result.returncode == 0, result.stdout + result.stderr
    assert link.is_symlink()
    assert Path(os.readlink(link)) == main_cfg


def test_run_sh_runs_main_only_when_executed_directly(sandbox: Sandbox):
    """Sourcing must load helpers without launching the bot."""
    result = subprocess.run(
        ["bash", "-c", "source ./run.sh"],
        cwd=str(sandbox.feature),
        env=sandbox.env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == ""
    assert not (sandbox.feature / "logs").exists()
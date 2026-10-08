"""Behavioural and unit tests for install.sh cross-platform support (Linux and macOS).

Ensures install.sh correctly detects macOS (Darwin) alongside Linux,
bypasses Linux-only container and systemd operations on macOS, and provides
clear macOS runtime guidance.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH_SOURCE = REPO_ROOT / "install.sh"

pytestmark = [
    pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-only shell script"),
    pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required"),
]


def _run_bash_command(script_content: str, env: dict | None = None) -> subprocess.CompletedProcess:
    base_env = dict(os.environ)
    if env:
        base_env.update(env)
    return subprocess.run(
        ["bash", "-c", script_content],
        text=True,
        capture_output=True,
        env=base_env,
    )


def test_install_sh_syntax_check():
    """install.sh passes bash syntax validation."""
    proc = subprocess.run(["bash", "-n", str(INSTALL_SH_SOURCE)], capture_output=True, text=True)
    assert proc.returncode == 0, f"Syntax error in install.sh: {proc.stderr}"


def test_install_sh_sourcing_guard():
    """Sourcing install.sh defines functions without immediately running main()."""
    cmd = f"""
    source "{INSTALL_SH_SOURCE}"
    type check_prerequisites
    type print_summary
    """
    proc = _run_bash_command(cmd)
    assert proc.returncode == 0
    assert "check_prerequisites is a function" in proc.stdout
    assert "print_summary is a function" in proc.stdout


def test_check_prerequisites_darwin_allowed():
    """On Darwin (macOS), check_prerequisites does not reject the system."""
    cmd = f"""
    source "{INSTALL_SH_SOURCE}"
    # Stub uname to report Darwin and sudo to succeed
    uname() {{
      if [[ "$1" == "-s" ]]; then echo "Darwin"; elif [[ "$1" == "-m" ]]; then echo "arm64"; else command uname "$@"; fi
    }}
    sudo() {{ return 0; }}
    check_prerequisites
    """
    proc = _run_bash_command(cmd)
    assert proc.returncode == 0
    assert "仅支持 Linux" not in proc.stderr
    assert "系统与权限检查通过" in proc.stdout


def test_check_prerequisites_unsupported_os():
    """Unsupported OS (e.g., SunOS) is rejected with clear error."""
    cmd = f"""
    source "{INSTALL_SH_SOURCE}"
    uname() {{
      if [[ "$1" == "-s" ]]; then echo "SunOS"; else command uname "$@"; fi
    }}
    check_prerequisites
    """
    proc = _run_bash_command(cmd)
    assert proc.returncode != 0
    assert "仅支持 Linux" in proc.stderr and "macOS" in proc.stderr


def test_setup_waydroid_skipped_on_darwin():
    """Waydroid setup is skipped on macOS without error."""
    cmd = f"""
    source "{INSTALL_SH_SOURCE}"
    uname() {{
      if [[ "$1" == "-s" ]]; then echo "Darwin"; else command uname "$@"; fi
    }}
    setup_waydroid
    """
    proc = _run_bash_command(cmd)
    assert proc.returncode == 0
    assert "跳过 Waydroid" in proc.stdout or "跳过 Waydroid" in proc.stderr or "Waydroid" in proc.stdout


def test_setup_adb_forwarding_skipped_on_darwin():
    """ADB port forwarding is skipped on macOS without error."""
    cmd = f"""
    source "{INSTALL_SH_SOURCE}"
    uname() {{
      if [[ "$1" == "-s" ]]; then echo "Darwin"; else command uname "$@"; fi
    }}
    setup_adb_forwarding
    """
    proc = _run_bash_command(cmd)
    assert proc.returncode == 0
    assert "跳过" in proc.stdout or "直连" in proc.stdout


def test_setup_appium_service_skipped_on_darwin():
    """Appium background systemd service setup is skipped on macOS."""
    cmd = f"""
    source "{INSTALL_SH_SOURCE}"
    uname() {{
      if [[ "$1" == "-s" ]]; then echo "Darwin"; else command uname "$@"; fi
    }}
    setup_appium_service
    """
    proc = _run_bash_command(cmd)
    assert proc.returncode == 0
    assert "appium.sh" in proc.stdout


def test_print_summary_macos():
    """print_summary displays macOS-specific usage guide on Darwin."""
    cmd = f"""
    TARGET_DIR="/path/to/ushareiplay"
    source "{INSTALL_SH_SOURCE}"
    uname() {{
      if [[ "$1" == "-s" ]]; then echo "Darwin"; else command uname "$@"; fi
    }}
    print_summary
    """
    proc = _run_bash_command(cmd)
    assert proc.returncode == 0
    assert "macOS" in proc.stdout
    assert "appium.sh" in proc.stdout

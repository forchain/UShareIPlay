#!/usr/bin/env python3
"""Automate evidence-gated rooted Android Emulator audio experiments."""

from __future__ import annotations

import hashlib
import argparse
import json
import platform
import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

try:
    from scripts.virtual_audio_device import ROOT_FALLBACK_AVD, open_avd, provision_avd, sdk_tools
except ModuleNotFoundError:  # Direct execution adds scripts/ instead of the repo root.
    from virtual_audio_device import ROOT_FALLBACK_AVD, open_avd, provision_avd, sdk_tools


GATES = ("gate-0", "gate-1", "gate-2", "gate-3a", "gate-3b", "gate-4", "gate-5")
GATE_STATUSES = {"pending", "passed", "failed", "blocked-on-human-auth"}
TARGET_PACKAGES = ("com.tencent.qqmusic", "cn.soulapp.android")
FRIDA_TOOLS_VERSION = "14.10.4"
SOUL_PACKAGE = "cn.soulapp.android"
SOUL_MAIN_ACTIVITY = "cn.soulapp.android/.component.startup.main.MainActivity"
SOUL_EXPERIMENT_PERMISSIONS = ("android.permission.RECORD_AUDIO", "android.permission.CAMERA")


@dataclass(frozen=True)
class ExperimentRun:
    run_id: str
    evidence_dir: Path


def root_avd_spec():
    return ROOT_FALLBACK_AVD


def prepare_root_avd() -> None:
    provision_avd(sdk_tools(), root_avd_spec())


def open_root_avd(
    *,
    port: int,
    config_path: Path,
    camera_front: str = "webcam0",
    camera_back: str = "emulated",
) -> str:
    return open_avd(
        sdk_tools(),
        root_avd_spec(),
        port=port,
        config_path=config_path,
        writable_system=True,
        host_audio=False,
        camera_front=camera_front,
        camera_back=camera_back,
    )


def ensure_rooted_device(
    adb: Path,
    *,
    serial: str,
    runner=subprocess.run,
    wait_for_device=None,
) -> dict[str, int | bool]:
    prefix = [str(adb), "-s", serial]

    def run(suffix: list[str]):
        return runner(prefix + suffix, check=True, text=True, capture_output=True)

    if wait_for_device is None:
        wait_for_device = lambda: runner(prefix + ["wait-for-device"], check=True, timeout=180)

    run(["root"])
    wait_for_device()
    remount = run(["remount"])
    rebooted = "reboot your device" in f"{remount.stdout}\n{remount.stderr}".lower()
    if rebooted:
        run(["reboot"])
        wait_for_device()
        run(["root"])
        wait_for_device()
        run(["remount"])

    identity = run(["shell", "id"])
    match = re.search(r"\buid=(\d+)", identity.stdout)
    uid = int(match.group(1)) if match else -1
    if uid != 0:
        raise RuntimeError(f"rooted AVD did not retain uid 0: {identity.stdout.strip()}")
    return {"uid": uid, "rebooted_for_overlayfs": rebooted}


def frida_injection_command(*, host: str, pid: int, script: Path) -> list[str]:
    return [
        "uvx",
        "--from",
        f"frida-tools=={FRIDA_TOOLS_VERSION}",
        "frida",
        "-H",
        host,
        "-p",
        str(pid),
        "-l",
        str(script),
    ]


def frida_spawn_command(*, host: str, package: str, script: Path) -> list[str]:
    return [
        "uvx",
        "--from",
        f"frida-tools=={FRIDA_TOOLS_VERSION}",
        "frida",
        "-H",
        host,
        "-f",
        package,
        "-l",
        str(script),
    ]


def frida_server_manifest(*, version: str, abi: str, sha256: str) -> dict[str, str]:
    if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
        raise ValueError("Frida server SHA-256 must be lowercase hexadecimal")
    return {"version": version, "abi": abi, "sha256": sha256}


def probe_command_plan(
    adb: Path,
    *,
    serial: str,
    apk: Path,
    mode: str,
    source: Path | None = None,
    capture_uid: int | None = None,
) -> list[list[str]]:
    if mode not in {"probe", "synthetic", "playback_capture", "loopback"}:
        raise ValueError(f"unsupported verifier mode: {mode}")
    prefix = [str(adb), "-s", serial]
    commands = [
        prefix + ["install", "-r", str(apk)],
        prefix + ["shell", "pm", "grant", "io.ushareiplay.loopback", "android.permission.RECORD_AUDIO"],
    ]
    if source is not None:
        commands.append(prefix + ["push", str(source), "/data/local/tmp/ushareiplay-source.pcm"])
    commands.extend([
        prefix + ["shell", "rm", "-rf", "/sdcard/Android/data/io.ushareiplay.loopback/files/Music"],
        prefix + ["shell", "am", "force-stop", "io.ushareiplay.loopback"],
    ])
    start = prefix + ["shell", "am", "start", "-n", "io.ushareiplay.loopback/.MainActivity", "--es", "mode", mode]
    if capture_uid is not None:
        start.extend(["--ei", "capture_uid", str(capture_uid)])
    commands.append(start)
    return commands


def install_apk_plan(adb: Path, *, serial: str, apks: Iterable[Path]) -> list[list[str]]:
    return [[str(adb), "-s", serial, "install", "-r", str(apk)] for apk in apks]


def install_apks(adb: Path, *, serial: str, apks: Iterable[Path], runner=subprocess.run) -> None:
    for command in install_apk_plan(adb, serial=serial, apks=apks):
        runner(command, check=True, text=True, capture_output=True)


def run_probe(
    adb: Path,
    *,
    serial: str,
    apk: Path,
    mode: str,
    evidence_dir: Path,
    source: Path | None = None,
    capture_uid: int | None = None,
    frida_script: Path | None = None,
    frida_host: str = "127.0.0.1:27042",
    wait_seconds: int = 15,
    runner=subprocess.run,
    process_factory=subprocess.Popen,
    sleep=time.sleep,
) -> dict[str, str]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for command in probe_command_plan(
        adb, serial=serial, apk=apk, mode=mode, source=source, capture_uid=capture_uid
    ):
        runner(command, check=True, text=True, capture_output=True)

    prefix = [str(adb), "-s", serial]
    pid = ""
    for _ in range(30):
        result = runner(prefix + ["shell", "pidof", "io.ushareiplay.loopback"], check=True, text=True, capture_output=True)
        pid = result.stdout.strip()
        if pid:
            break
        sleep(1)
    if not pid:
        raise RuntimeError("verifier process did not start")

    frida_process = None
    if frida_script is not None:
        frida_process = process_factory(
            frida_injection_command(host=frida_host, pid=int(pid.split()[0]), script=frida_script),
            stdout=(evidence_dir / "frida.log").open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            text=True,
        )
    try:
        sleep(wait_seconds)
    finally:
        if frida_process is not None:
            frida_process.terminate()
            frida_process.wait(timeout=10)

    pulled: dict[str, str] = {}
    remote_root = "/sdcard/Android/data/io.ushareiplay.loopback/files/Music"
    for name in ("capture.pcm", "source.pcm", "metadata.json", "complete.json"):
        local = evidence_dir / name
        result = runner(prefix + ["pull", f"{remote_root}/{name}", str(local)], text=True, capture_output=True)
        if result.returncode == 0 and local.is_file():
            pulled[name] = str(local)
    return pulled


def soul_hook_command_plan(
    adb: Path,
    *,
    serial: str,
    source: Path | None = None,
    package: str = SOUL_PACKAGE,
    activity: str = SOUL_MAIN_ACTIVITY,
    launch: bool = True,
) -> list[list[str]]:
    """Build the deterministic Soul launch sequence used by the hook gate."""
    prefix = [str(adb), "-s", serial]
    commands = [
        prefix + ["shell", "pm", "grant", package, permission]
        for permission in SOUL_EXPERIMENT_PERMISSIONS
    ]
    if source is not None:
        commands.append(prefix + ["push", str(source), "/data/local/tmp/ushareiplay-source.pcm"])
    commands.append(prefix + ["shell", "am", "force-stop", package])
    if launch:
        commands.append(prefix + ["shell", "am", "start", "-W", "-n", activity])
    return commands


def _first_pid(
    adb: Path,
    *,
    serial: str,
    package: str,
    runner=subprocess.run,
    sleep=time.sleep,
    attempts: int = 30,
) -> str:
    prefix = [str(adb), "-s", serial]
    for _ in range(attempts):
        result = runner(
            prefix + ["shell", "pidof", package],
            check=False,
            text=True,
            capture_output=True,
        )
        pid = result.stdout.strip().split()
        if pid:
            return pid[0]
        sleep(1)
    raise RuntimeError(f"{package} process did not start")


def run_soul_hook(
    adb: Path,
    *,
    serial: str,
    evidence_dir: Path,
    source: Path | None = None,
    frida_script: Path,
    frida_host: str = "127.0.0.1:27042",
    package: str = SOUL_PACKAGE,
    activity: str = SOUL_MAIN_ACTIVITY,
    wait_seconds: int = 30,
    runner=subprocess.run,
    process_factory=subprocess.Popen,
    sleep=time.sleep,
) -> dict[str, object]:
    """Attach the AudioRecord hook to Soul and retain a human-check handoff.

    This intentionally reports ``blocked-on-human-auth`` until a human confirms
    the two-account listening result. A hook-install message alone is not a
    positive Soul compatibility result.
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    commands = soul_hook_command_plan(
        adb, serial=serial, source=source, package=package, activity=activity, launch=False
    )
    command_log = evidence_dir / "commands.log"
    with command_log.open("w", encoding="utf-8") as log:
        for command in commands:
            result = runner(command, check=True, text=True, capture_output=True)
            log.write(json.dumps({"command": command, "returncode": result.returncode}) + "\n")

    frida_log = evidence_dir / "frida.log"
    frida_process = process_factory(
        frida_spawn_command(host=frida_host, package=package, script=frida_script),
        stdout=frida_log.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        text=True,
    )
    process_restarted = False
    current_pid = ""
    try:
        # Spawn injection removes the race between Soul's startup activity and
        # its first process restart. The PID is retained as evidence after the
        # injected process has resumed.
        pid = _first_pid(adb, serial=serial, package=package, runner=runner, sleep=sleep)
        current_pid = pid
        sleep(wait_seconds)
    finally:
        frida_process.terminate()
        frida_process.wait(timeout=10)

    current = runner(
        [str(adb), "-s", serial, "shell", "pidof", package],
        check=False,
        text=True,
        capture_output=True,
    )
    current_pids = current.stdout.strip().split()
    if current_pids:
        current_pid = current_pids[0]
        process_restarted = current_pid != pid
    else:
        process_restarted = True

    prefix = [str(adb), "-s", serial]
    (evidence_dir / "activity.txt").write_text(
        runner(prefix + ["shell", "dumpsys", "activity", "activities"], check=True, text=True, capture_output=True).stdout,
        encoding="utf-8",
    )
    (evidence_dir / "logcat.txt").write_text(
        runner(prefix + ["logcat", "-d", "-t", "1000"], check=True, text=True, capture_output=True).stdout,
        encoding="utf-8",
    )
    frida_text = frida_log.read_text(encoding="utf-8") if frida_log.exists() else ""
    hook_installed = "hook-installed" in frida_text
    status = "blocked-on-human-auth" if hook_installed and not process_restarted else "failed"
    manifest_path = evidence_dir / "environment.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "candidate": "soul-frida-hook",
            "emulator_version": None,
            "gate_details": {},
            "gates": {gate: "pending" for gate in GATES},
            "host": platform.system(),
            "run_id": evidence_dir.name,
        }
    manifest["gates"]["gate-2"] = status
    manifest["gate_details"]["gate-2"] = {
        "audio_record_events": frida_text.count("AudioRecord::obtainBuffer"),
        "hook_installed": hook_installed,
        "human_confirmation_required": True,
        "package": package,
        "pid": pid,
        "current_pid": current_pid,
        "process_restarted": process_restarted,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "package": package,
        "pid": pid,
        "hook_installed": hook_installed,
        "audio_record_events": frida_text.count("AudioRecord::obtainBuffer"),
        "status": status,
        "evidence_dir": str(evidence_dir),
    }


def _write_manifest(run: ExperimentRun, manifest: dict) -> None:
    path = run.evidence_dir / "environment.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def new_run(
    evidence_root: Path,
    *,
    candidate: str,
    host: str | None = None,
    emulator_version: str | None = None,
) -> ExperimentRun:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{secrets.token_hex(4)}-{candidate}"
    evidence_dir = evidence_root.expanduser().resolve() / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    run = ExperimentRun(run_id=run_id, evidence_dir=evidence_dir)
    _write_manifest(
        run,
        {
            "candidate": candidate,
            "emulator_version": emulator_version,
            "gate_details": {},
            "gates": {gate: "pending" for gate in GATES},
            "host": host or platform.system(),
            "run_id": run_id,
        },
    )
    return run


def record_gate(run: ExperimentRun, gate: str, *, status: str, details: dict | None = None) -> None:
    if gate not in GATES:
        raise ValueError(f"unknown acceptance gate: {gate}")
    if status not in GATE_STATUSES:
        raise ValueError(f"unknown gate status: {status}")
    path = run.evidence_dir / "environment.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["gates"][gate] = status
    manifest["gate_details"][gate] = details or {}
    _write_manifest(run, manifest)


def classify_gate(*, positive_passed: bool, negative_passed: bool) -> tuple[str, str]:
    if not positive_passed:
        return "failed", "positive_control_failed"
    if negative_passed:
        return "failed", "negative_control_passed"
    return "passed", "controls_valid"


def parse_pm_paths(output: str) -> list[str]:
    paths: list[str] = []
    for line in output.splitlines():
        if not line.startswith("package:"):
            continue
        path = line.removeprefix("package:").strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def hash_files(paths: Iterable[Path]) -> dict[str, str]:
    hashes = {}
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        hashes[path.name] = digest.hexdigest()
    return hashes


def extract_package(
    adb: Path,
    *,
    serial: str,
    package: str,
    cache_root: Path,
    runner=subprocess.run,
) -> Path:
    """Pull only APK paths reported by package manager and write a hash manifest."""
    result = runner(
        [str(adb), "-s", serial, "shell", "pm", "path", package],
        check=True,
        text=True,
        capture_output=True,
    )
    remote_paths = parse_pm_paths(result.stdout)
    if not remote_paths:
        raise RuntimeError(f"package is not installed on {serial}: {package}")

    package_dir = cache_root.expanduser().resolve() / package
    package_dir.mkdir(parents=True, exist_ok=True)
    local_paths: list[Path] = []
    for remote_path in remote_paths:
        name = Path(remote_path).name
        if not name.endswith(".apk"):
            raise RuntimeError(f"package manager returned a non-APK path: {remote_path}")
        local_path = package_dir / name
        runner(
            [str(adb), "-s", serial, "pull", remote_path, str(local_path)],
            check=True,
            text=True,
            capture_output=True,
        )
        local_paths.append(local_path)

    hashes = hash_files(local_paths)
    manifest_path = package_dir / "apk-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "package": package,
                "source_serial": serial,
                "apks": [
                    {"name": path.name, "sha256": hashes[path.name]}
                    for path in local_paths
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_run_parser = subparsers.add_parser("new-run", help="create an evidence run")
    new_run_parser.add_argument("--candidate", required=True)
    new_run_parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path.home() / "ushareiplay-evidence" / "rooted-emulator",
    )
    new_run_parser.add_argument("--host", default=platform.system())
    new_run_parser.add_argument("--emulator-version")

    extract_parser = subparsers.add_parser("extract-apks", help="extract APKs from an authorized device")
    extract_parser.add_argument("--source-serial", required=True)
    extract_parser.add_argument("--adb", type=Path, default=Path(shutil.which("adb") or "adb"))
    extract_parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path.home() / "ushareiplay-evidence" / "apk-cache",
    )
    extract_parser.add_argument("packages", nargs="*", default=list(TARGET_PACKAGES))
    subparsers.add_parser("prepare-root", help="provision the owned rootable AVD")
    open_parser = subparsers.add_parser("open-root", help="start the owned writable root AVD")
    open_parser.add_argument("--port", type=int, default=5558)
    open_parser.add_argument("--config-path", type=Path, default=Path(__file__).resolve().parents[1] / "config.local.yaml")
    open_parser.add_argument("--camera-front", default="webcam0", help="Emulator front camera mode/device")
    open_parser.add_argument("--camera-back", default="emulated", help="Emulator back camera mode/device")
    health_parser = subparsers.add_parser("health-root", help="verify root and writable-system access")
    health_parser.add_argument("--serial", required=True)
    health_parser.add_argument("--adb", type=Path, default=Path(shutil.which("adb") or "adb"))
    probe_parser = subparsers.add_parser("probe", help="run an automated verifier mode")
    probe_parser.add_argument("--serial", required=True)
    probe_parser.add_argument("--apk", type=Path, required=True)
    probe_parser.add_argument("--mode", choices=("probe", "synthetic", "playback_capture", "loopback"), default="probe")
    probe_parser.add_argument("--source", type=Path)
    probe_parser.add_argument("--capture-uid", type=int)
    probe_parser.add_argument("--frida-script", type=Path)
    probe_parser.add_argument("--frida-host", default="127.0.0.1:27042")
    probe_parser.add_argument("--wait-seconds", type=int, default=15)
    probe_parser.add_argument("--evidence-dir", type=Path, required=True)
    probe_parser.add_argument("--adb", type=Path, default=Path(shutil.which("adb") or "adb"))
    install_parser = subparsers.add_parser("install-apks", help="install fixed APK artifacts on the experiment AVD")
    install_parser.add_argument("--serial", required=True)
    install_parser.add_argument("--adb", type=Path, default=Path(shutil.which("adb") or "adb"))
    install_parser.add_argument("apks", nargs="+", type=Path)
    soul_parser = subparsers.add_parser("soul-hook", help="attach the AudioRecord hook to Soul")
    soul_parser.add_argument("--serial", required=True)
    soul_parser.add_argument("--evidence-dir", type=Path, required=True)
    soul_parser.add_argument("--frida-script", type=Path, required=True)
    soul_parser.add_argument("--source", type=Path)
    soul_parser.add_argument("--frida-host", default="127.0.0.1:27042")
    soul_parser.add_argument("--wait-seconds", type=int, default=30)
    soul_parser.add_argument("--adb", type=Path, default=Path(shutil.which("adb") or "adb"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "new-run":
        run = new_run(
            args.evidence_root,
            candidate=args.candidate,
            host=args.host,
            emulator_version=args.emulator_version,
        )
        print(run.evidence_dir)
        return 0
    if args.command == "prepare-root":
        prepare_root_avd()
        print(root_avd_spec().name)
        return 0
    if args.command == "open-root":
        print(open_root_avd(port=args.port, config_path=args.config_path, camera_front=args.camera_front, camera_back=args.camera_back))
        return 0
    if args.command == "health-root":
        print(json.dumps(ensure_rooted_device(args.adb, serial=args.serial), sort_keys=True))
        return 0
    if args.command == "probe":
        print(json.dumps(run_probe(
            args.adb,
            serial=args.serial,
            apk=args.apk,
            mode=args.mode,
            evidence_dir=args.evidence_dir,
            source=args.source,
            capture_uid=args.capture_uid,
            frida_script=args.frida_script,
            frida_host=args.frida_host,
            wait_seconds=args.wait_seconds,
        ), sort_keys=True))
        return 0
    if args.command == "install-apks":
        install_apks(args.adb, serial=args.serial, apks=args.apks)
        print("installed", len(args.apks), "APK artifacts")
        return 0
    if args.command == "soul-hook":
        print(json.dumps(run_soul_hook(
            args.adb,
            serial=args.serial,
            evidence_dir=args.evidence_dir,
            source=args.source,
            frida_script=args.frida_script,
            frida_host=args.frida_host,
            wait_seconds=args.wait_seconds,
        ), sort_keys=True))
        return 0
    for package in args.packages:
        print(extract_package(args.adb, serial=args.source_serial, package=package, cache_root=args.cache_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

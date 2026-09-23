#!/usr/bin/env python3
"""Provision and operate the UShareIPlay virtual audio Android device."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

import yaml


class HostAudioBackend(StrEnum):
    BLACKHOLE = "blackhole"
    PIPEWIRE = "pipewire"


@dataclass(frozen=True)
class AvdSpec:
    name: str
    package: str
    play_store: bool


@dataclass(frozen=True)
class SdkTools:
    sdk_root: Path
    emulator: Path
    adb: Path
    sdkmanager: Path
    avdmanager: Path


DEFAULT_AVD = AvdSpec(
    name="ushareiplay-audio",
    package="system-images;android-36;google_apis_playstore;arm64-v8a",
    play_store=True,
)

ROOT_FALLBACK_AVD = AvdSpec(
    name="ushareiplay-audio-root",
    package="system-images;android-30;google_apis;arm64-v8a",
    play_store=False,
)


def avd_spec(*, root_fallback: bool) -> AvdSpec:
    return ROOT_FALLBACK_AVD if root_fallback else DEFAULT_AVD


def host_backend(system: str | None = None) -> HostAudioBackend:
    current_system = system or platform.system()
    if current_system == "Darwin":
        return HostAudioBackend.BLACKHOLE
    if current_system == "Linux":
        return HostAudioBackend.PIPEWIRE
    raise RuntimeError(f"unsupported host platform: {current_system}")


def appium_override(serial: str) -> dict[str, dict[str, str | int | bool]]:
    return {
        "device": {
            "name": serial,
            "platform_name": "Android",
            "automation_name": "UiAutomator2",
            "no_reset": True,
        },
        "appium": {"host": "127.0.0.1", "port": 4723},
    }


def sdk_tools(env: dict[str, str] | None = None) -> SdkTools:
    values = env or os.environ
    configured_root = values.get("ANDROID_SDK_ROOT") or values.get("ANDROID_HOME")
    candidates = [Path(configured_root).expanduser()] if configured_root else [
        Path.home() / "Library" / "Android" / "sdk",
        Path.home() / "Android" / "Sdk",
    ]
    root = next((candidate for candidate in candidates if candidate.is_dir()), None)
    if root is None:
        raise RuntimeError("Android SDK not found; set ANDROID_SDK_ROOT")
    command_tools = root / "cmdline-tools" / "latest" / "bin"
    return SdkTools(
        sdk_root=root,
        emulator=root / "emulator" / "emulator",
        adb=root / "platform-tools" / "adb",
        sdkmanager=command_tools / "sdkmanager",
        avdmanager=command_tools / "avdmanager",
    )


def emulator_launch_command(
    emulator: Path,
    spec: AvdSpec,
    *,
    port: int,
    host_audio: bool = False,
    writable_system: bool = False,
    camera_front: str | None = None,
    camera_back: str | None = None,
) -> list[str]:
    if port < 5554 or port > 5682 or port % 2:
        raise ValueError("emulator console port must be even and between 5554 and 5682")
    command = [
        str(emulator),
        "-avd",
        spec.name,
        "-port",
        str(port),
        "-no-snapshot-save",
    ]
    if host_audio:
        command.insert(-1, "-allow-host-audio")
    if writable_system:
        command.insert(-1, "-writable-system")
    if camera_front is not None:
        command.insert(-1, "-camera-front")
        command.insert(-1, camera_front)
    if camera_back is not None:
        command.insert(-1, "-camera-back")
        command.insert(-1, camera_back)
    return command


def avd_exists(spec: AvdSpec, avd_home: Path | None = None) -> bool:
    home = avd_home or Path(os.environ.get("ANDROID_AVD_HOME", Path.home() / ".android" / "avd"))
    return (home / f"{spec.name}.avd").is_dir()


def create_avd_command(avdmanager: Path, spec: AvdSpec) -> list[str]:
    return [
        str(avdmanager),
        "create",
        "avd",
        "--force",
        "--name",
        spec.name,
        "--package",
        spec.package,
        "--device",
        "pixel_7",
    ]


def parse_emulator_serials(adb_devices_output: str) -> list[str]:
    serials = []
    for line in adb_devices_output.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].startswith("emulator-") and fields[1] == "device":
            serials.append(fields[0])
    return serials


def _adb_state(adb_devices_output: str, serial: str) -> str | None:
    for line in adb_devices_output.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] == serial:
            return fields[1]
    return None


def wait_for_authorized_device(adb: Path, serial: str, *, timeout_seconds: int = 180, sleep: Callable[[float], None] = time.sleep) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_state = None
    while time.monotonic() <= deadline:
        result = subprocess.run([str(adb), "devices"], text=True, check=True, capture_output=True)
        last_state = _adb_state(result.stdout, serial)
        if last_state == "device":
            return
        sleep(1)
    raise RuntimeError(f"{serial} did not become authorized (last ADB state: {last_state or 'missing'})")


def _image_directory(tools: SdkTools, spec: AvdSpec) -> Path:
    return tools.sdk_root / spec.package.replace(";", "/")


def java_home(env: dict[str, str] | None = None, homebrew_default: Path | None = None) -> Path | None:
    values = os.environ if env is None else env
    configured = values.get("JAVA_HOME")
    if configured and Path(configured).is_dir():
        return Path(configured)
    default = homebrew_default or Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home")
    return default if default.is_dir() else None


def _run_checked(command: list[str], *, input_text: str | None = None) -> None:
    environment = os.environ.copy()
    if (detected_java_home := java_home(environment)) is not None:
        environment["JAVA_HOME"] = str(detected_java_home)
        environment["PATH"] = f"{detected_java_home / 'bin'}:{environment['PATH']}"
    subprocess.run(command, input=input_text, text=True, check=True, env=environment)


def provision_avd(
    tools: SdkTools,
    spec: AvdSpec,
    avd_home: Path | None = None,
    runner: Callable[..., None] = _run_checked,
) -> None:
    # SDK directories can outlive the package-manager metadata. sdkmanager's
    # idempotent install operation is the only authoritative availability check.
    runner([str(tools.sdkmanager), "--install", spec.package])
    if not avd_exists(spec, avd_home):
        runner(create_avd_command(tools.avdmanager, spec), input_text="no\n")


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def write_appium_override(config_path: Path, serial: str) -> None:
    existing = {}
    if config_path.exists():
        existing = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(existing, dict):
        raise RuntimeError(f"local configuration must be a mapping: {config_path}")
    merged = _deep_merge(existing, appium_override(serial))
    config_path.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")


def root_fallback_allowed(report_path: Path) -> bool:
    if not report_path.is_file():
        return False
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return report.get("status") == "failed" and report.get("mode") == "standard"


def open_avd(
    tools: SdkTools,
    spec: AvdSpec,
    *,
    port: int,
    config_path: Path,
    host_audio: bool = False,
    writable_system: bool = False,
    camera_front: str | None = None,
    camera_back: str | None = None,
) -> str:
    provision_avd(tools, spec)
    serial = f"emulator-{port}"
    subprocess.Popen(
        emulator_launch_command(
            tools.emulator,
            spec,
            port=port,
            host_audio=host_audio,
            writable_system=writable_system,
            camera_front=camera_front,
            camera_back=camera_back,
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    subprocess.run([str(tools.adb), "-s", serial, "wait-for-device"], check=True, timeout=180)
    wait_for_authorized_device(tools.adb, serial)
    if host_audio:
        subprocess.run([str(tools.adb), "-s", serial, "emu", "avd", "hostmicon"], check=True, timeout=30)
    write_appium_override(config_path, serial)
    return serial


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "prepare", "open"), help="operation to perform")
    parser.add_argument("--root-fallback", action="store_true", help="select the disposable rootable AVD")
    parser.add_argument("--port", type=int, default=5556, help="even emulator console port")
    parser.add_argument("--enable-host-audio", action="store_true", help="opt in to routing the current host input into Android")
    parser.add_argument("--camera-front", help="emulator camera mode/device, e.g. webcam0 or emulated")
    parser.add_argument("--camera-back", help="emulator camera mode/device, e.g. webcam0 or emulated")
    parser.add_argument("--config-path", type=Path, default=Path(__file__).resolve().parents[1] / "config.local.yaml")
    parser.add_argument("--failure-report", type=Path, help="required failed standard verification report for Root Fallback")
    args = parser.parse_args()

    spec = avd_spec(root_fallback=args.root_fallback)
    if args.root_fallback and not args.failure_report:
        parser.error("--root-fallback requires --failure-report")
    if args.root_fallback and not root_fallback_allowed(args.failure_report):
        parser.error("Root Fallback requires a failed standard verification report")

    if args.action == "status":
        print({"avd": asdict(spec), "audio_backend": host_backend().value})
        return 0

    tools = sdk_tools()
    if args.action == "prepare":
        provision_avd(tools, spec)
        print(f"prepared {spec.name}")
        return 0

    serial = open_avd(
        tools,
        spec,
        port=args.port,
        config_path=args.config_path,
        host_audio=args.enable_host_audio,
        camera_front=args.camera_front,
        camera_back=args.camera_back,
    )
    print(f"opened {spec.name} as {serial}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Provision and operate the UShareIPlay virtual audio Android device."""

from __future__ import annotations

import argparse
import json
import os
import platform
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

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


def emulator_launch_command(emulator: Path, spec: AvdSpec, *, port: int) -> list[str]:
    if port < 5554 or port > 5682 or port % 2:
        raise ValueError("emulator console port must be even and between 5554 and 5682")
    return [
        str(emulator),
        "-avd",
        spec.name,
        "-port",
        str(port),
        "-allow-host-audio",
        "-no-snapshot-save",
    ]


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-fallback", action="store_true", help="select the disposable rootable AVD")
    parser.add_argument("--status", action="store_true", help="print the selected virtual device contract")
    args = parser.parse_args()

    if args.status:
        print({"avd": asdict(avd_spec(root_fallback=args.root_fallback)), "audio_backend": host_backend().value})
        return 0

    parser.error("choose an action; use --status for the current device contract")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

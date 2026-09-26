import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_tool():
    path = Path(__file__).resolve().parents[1] / "scripts" / "rooted_emulator_harness.py"
    spec = importlib.util.spec_from_file_location("rooted_emulator_harness", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_new_run_creates_manifest_and_owned_evidence_directory(tmp_path):
    tool = _load_tool()

    run = tool.new_run(tmp_path, candidate="probe-file", host="Darwin", emulator_version="36.1.9.0")

    assert run.evidence_dir == tmp_path / run.run_id
    assert (run.evidence_dir / "environment.json").is_file()
    manifest = json.loads((run.evidence_dir / "environment.json").read_text(encoding="utf-8"))
    assert manifest["candidate"] == "probe-file"
    assert manifest["host"] == "Darwin"
    assert manifest["gates"]["gate-0"] == "pending"


def test_gate_result_requires_positive_and_negative_controls(tmp_path):
    tool = _load_tool()
    run = tool.new_run(tmp_path, candidate="probe-file")

    tool.record_gate(run, "gate-1", status="passed", details={"positive": True, "negative": False})

    report = json.loads((run.evidence_dir / "environment.json").read_text(encoding="utf-8"))
    assert report["gates"]["gate-1"] == "passed"
    assert report["gate_details"]["gate-1"]["negative"] is False


def test_classify_gate_stops_when_negative_control_passes():
    tool = _load_tool()

    result = tool.classify_gate(positive_passed=True, negative_passed=True)

    assert result == ("failed", "negative_control_passed")


def test_parse_pm_paths_returns_unique_apk_paths_in_order():
    tool = _load_tool()

    output = "package:/data/app/base.apk\npackage:/data/app/split_config.arm64_v8a.apk\npackage:/data/app/base.apk\n"

    assert tool.parse_pm_paths(output) == [
        "/data/app/base.apk",
        "/data/app/split_config.arm64_v8a.apk",
    ]


def test_hash_files_returns_sha256_manifest(tmp_path):
    tool = _load_tool()
    first = tmp_path / "base.apk"
    second = tmp_path / "split.apk"
    first.write_bytes(b"base")
    second.write_bytes(b"split")

    hashes = tool.hash_files([first, second])

    assert hashes == {
        "base.apk": "cae662172fd450bb0cd710a769079c05bfc5d8e35efa6576edc7d0377afdd4a2",
        "split.apk": "ad1a64057f9ab34fecfe3f4ee78660bb0316dbda9370581ffbeb1e8bddf3d598",
    }


def test_extract_package_caches_base_and_split_apks_with_manifest(tmp_path):
    tool = _load_tool()
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        if command[-4:-1] == ["shell", "pm", "path"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="package:/data/app/pkg/base.apk\npackage:/data/app/pkg/split_config.arm64_v8a.apk\n",
                stderr="",
            )
        if "pull" in command:
            Path(command[-1]).write_bytes(Path(command[-2]).name.encode())
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(command)

    manifest_path = tool.extract_package(
        Path("/sdk/adb"),
        serial="device-1",
        package="com.example.player",
        cache_root=tmp_path,
        runner=runner,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["package"] == "com.example.player"
    assert manifest["source_serial"] == "device-1"
    assert [item["name"] for item in manifest["apks"]] == ["base.apk", "split_config.arm64_v8a.apk"]
    assert all(len(item["sha256"]) == 64 for item in manifest["apks"])
    assert commands[0] == ["/sdk/adb", "-s", "device-1", "shell", "pm", "path", "com.example.player"]


def test_extract_package_rejects_device_without_requested_package(tmp_path):
    tool = _load_tool()

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    try:
        tool.extract_package(
            Path("adb"),
            serial="device-1",
            package="com.example.missing",
            cache_root=tmp_path,
            runner=runner,
        )
    except RuntimeError as error:
        assert "not installed" in str(error)
    else:
        raise AssertionError("missing package should fail")


def test_extract_cli_defaults_to_target_application_packages():
    tool = _load_tool()

    args = tool.build_parser().parse_args(["extract-apks", "--source-serial", "device-1"])

    assert args.packages == ["com.tencent.qqmusic", "cn.soulapp.android"]


def test_new_run_cli_requires_candidate_name():
    tool = _load_tool()

    try:
        tool.build_parser().parse_args(["new-run"])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("candidate should be required")


def test_root_avd_spec_is_google_apis_arm64_without_play_store():
    tool = _load_tool()

    spec = tool.root_avd_spec()

    assert spec.name == "ushareiplay-audio-root"
    assert spec.package == "system-images;android-30;google_apis;arm64-v8a"
    assert spec.play_store is False


def test_prepare_root_avd_provisions_only_root_fallback(monkeypatch):
    tool = _load_tool()
    calls = []

    monkeypatch.setattr(tool, "sdk_tools", lambda: "sdk-tools")
    monkeypatch.setattr(
        tool,
        "provision_avd",
        lambda tools, spec: calls.append((tools, spec)),
    )

    tool.prepare_root_avd()

    assert calls == [("sdk-tools", tool.root_avd_spec())]


def test_parser_exposes_prepare_root_command():
    tool = _load_tool()

    args = tool.build_parser().parse_args(["prepare-root"])

    assert args.command == "prepare-root"


def test_open_root_avd_uses_writable_system_and_does_not_enable_host_audio(monkeypatch, tmp_path):
    tool = _load_tool()
    calls = []
    monkeypatch.setattr(tool, "sdk_tools", lambda: "sdk-tools")
    monkeypatch.setattr(tool, "open_avd", lambda *args, **kwargs: calls.append((args, kwargs)) or "emulator-5558")

    serial = tool.open_root_avd(port=5558, config_path=tmp_path / "config.local.yaml")

    assert serial == "emulator-5558"
    assert calls[0][0] == ("sdk-tools", tool.root_avd_spec())
    assert calls[0][1] == {
        "port": 5558,
        "config_path": tmp_path / "config.local.yaml",
        "writable_system": True,
        "host_audio": False,
        "camera_front": "webcam0",
        "camera_back": "emulated",
    }


def test_ensure_rooted_device_reboots_when_remount_requires_it():
    tool = _load_tool()
    commands = []
    remount_count = 0

    def runner(command, **kwargs):
        nonlocal remount_count
        commands.append(command)
        if command[-1] == "remount":
            remount_count += 1
            message = "Now reboot your device for settings to take effect\n" if remount_count == 1 else "remount succeeded\n"
            return type("Result", (), {"stdout": message, "stderr": "", "returncode": 0})()
        if command[-2:] == ["shell", "id"]:
            return type("Result", (), {"stdout": "uid=0(root) gid=0(root)\n", "stderr": "", "returncode": 0})()
        return type("Result", (), {"stdout": "", "stderr": "", "returncode": 0})()

    report = tool.ensure_rooted_device(
        Path("adb"),
        serial="emulator-5558",
        runner=runner,
        wait_for_device=lambda: commands.append(["wait-for-device"]),
    )

    assert report["uid"] == 0
    assert remount_count == 2
    assert ["adb", "-s", "emulator-5558", "reboot"] in commands


def test_parser_exposes_health_root_with_explicit_serial():
    tool = _load_tool()

    args = tool.build_parser().parse_args(["health-root", "--serial", "emulator-5558"])

    assert args.command == "health-root"
    assert args.serial == "emulator-5558"


def test_frida_injection_command_targets_one_process_and_fixed_script(tmp_path):
    tool = _load_tool()

    command = tool.frida_injection_command(
        host="127.0.0.1:27042",
        pid=1234,
        script=tmp_path / "audio_record_inject.js",
    )

    assert command == [
        "uvx",
        "--from",
        "frida-tools==14.10.4",
        "frida",
        "-H",
        "127.0.0.1:27042",
        "-p",
        "1234",
        "-l",
        str(tmp_path / "audio_record_inject.js"),
    ]


def test_frida_server_manifest_records_release_hash(tmp_path):
    tool = _load_tool()

    manifest = tool.frida_server_manifest(
        version="17.17.0",
        abi="android-arm64",
        sha256="09d1fad867b27d69562a79289f4c412e85867f5d38ab72877036ed35e4223021",
    )

    assert manifest == {
        "version": "17.17.0",
        "abi": "android-arm64",
        "sha256": "09d1fad867b27d69562a79289f4c412e85867f5d38ab72877036ed35e4223021",
    }


def test_frida_spawn_command_targets_package_without_pid(tmp_path):
    tool = _load_tool()

    command = tool.frida_spawn_command(
        host="127.0.0.1:27042",
        package="cn.soulapp.android",
        script=tmp_path / "inject.js",
    )

    assert command == [
        "uvx",
        "--from",
        "frida-tools==14.10.4",
        "frida",
        "-H",
        "127.0.0.1:27042",
        "-f",
        "cn.soulapp.android",
        "-l",
        str(tmp_path / "inject.js"),
    ]


def test_probe_command_plan_installs_grants_and_starts_selected_mode(tmp_path):
    tool = _load_tool()

    plan = tool.probe_command_plan(
        Path("adb"),
        serial="emulator-5558",
        apk=Path("verifier.apk"),
        mode="probe",
        source=Path("source.pcm"),
    )

    assert plan == [
        ["adb", "-s", "emulator-5558", "install", "-r", "verifier.apk"],
        ["adb", "-s", "emulator-5558", "shell", "pm", "grant", "io.ushareiplay.loopback", "android.permission.RECORD_AUDIO"],
        ["adb", "-s", "emulator-5558", "push", "source.pcm", "/data/local/tmp/ushareiplay-source.pcm"],
        ["adb", "-s", "emulator-5558", "shell", "rm", "-rf", "/sdcard/Android/data/io.ushareiplay.loopback/files/Music"],
        ["adb", "-s", "emulator-5558", "shell", "am", "force-stop", "io.ushareiplay.loopback"],
        ["adb", "-s", "emulator-5558", "shell", "am", "start", "-n", "io.ushareiplay.loopback/.MainActivity", "--es", "mode", "probe"],
    ]


def test_probe_command_plan_accepts_playback_capture_mode():
    tool = _load_tool()

    plan = tool.probe_command_plan(
        Path("adb"),
        serial="emulator-5558",
        apk=Path("verifier.apk"),
        mode="playback_capture",
    )

    assert plan[-1][-2:] == ["mode", "playback_capture"]


def test_probe_command_plan_can_target_external_playback_uid():
    tool = _load_tool()

    plan = tool.probe_command_plan(
        Path("adb"),
        serial="emulator-5558",
        apk=Path("verifier.apk"),
        mode="playback_capture",
        capture_uid=10167,
    )

    assert plan[-1][-4:] == ["playback_capture", "--ei", "capture_uid", "10167"]


def test_install_apk_plan_targets_only_explicit_fixed_packages():
    tool = _load_tool()

    commands = tool.install_apk_plan(
        Path("adb"),
        serial="emulator-5558",
        apks=[Path("qqmusic.apk"), Path("soul.apk")],
    )

    assert commands == [
        ["adb", "-s", "emulator-5558", "install", "-r", "qqmusic.apk"],
        ["adb", "-s", "emulator-5558", "install", "-r", "soul.apk"],
    ]


def test_soul_hook_command_plan_grants_permissions_and_uses_explicit_activity(tmp_path):
    tool = _load_tool()

    plan = tool.soul_hook_command_plan(
        Path("adb"),
        serial="emulator-5558",
        source=tmp_path / "source.pcm",
    )

    assert plan == [
        ["adb", "-s", "emulator-5558", "shell", "pm", "grant", "cn.soulapp.android", "android.permission.RECORD_AUDIO"],
        ["adb", "-s", "emulator-5558", "shell", "pm", "grant", "cn.soulapp.android", "android.permission.CAMERA"],
        ["adb", "-s", "emulator-5558", "push", str(tmp_path / "source.pcm"), "/data/local/tmp/ushareiplay-source.pcm"],
        ["adb", "-s", "emulator-5558", "shell", "am", "force-stop", "cn.soulapp.android"],
        ["adb", "-s", "emulator-5558", "shell", "am", "start", "-W", "-n", "cn.soulapp.android/.component.startup.main.MainActivity"],
    ]


def test_parser_exposes_soul_hook_human_handoff_command(tmp_path):
    tool = _load_tool()

    args = tool.build_parser().parse_args([
        "soul-hook",
        "--serial", "emulator-5558",
        "--evidence-dir", str(tmp_path),
        "--frida-script", "inject.js",
    ])

    assert args.command == "soul-hook"
    assert args.wait_seconds == 30


def test_run_soul_hook_records_hook_and_blocks_for_human_confirmation(tmp_path):
    tool = _load_tool()
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        if command[-2:] == ["pidof", "cn.soulapp.android"]:
            return subprocess.CompletedProcess(command, 0, stdout="42\n", stderr="")
        if command[-3:] == ["dumpsys", "activity", "activities"]:
            return subprocess.CompletedProcess(command, 0, stdout="resumed Soul", stderr="")
        if command[-4:-2] == ["logcat", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="logcat", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    class FakeProcess:
        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    def process_factory(command, **kwargs):
        kwargs["stdout"].write("hook-installed\nAudioRecord::obtainBuffer\n")
        kwargs["stdout"].close()
        return FakeProcess()

    result = tool.run_soul_hook(
        Path("adb"),
        serial="emulator-5558",
        evidence_dir=tmp_path,
        source=None,
        frida_script=Path("inject.js"),
        wait_seconds=0,
        runner=runner,
        process_factory=process_factory,
        sleep=lambda _: None,
    )

    assert result["hook_installed"] is True
    assert result["audio_record_events"] == 1
    assert result["status"] == "blocked-on-human-auth"
    assert (tmp_path / "activity.txt").read_text() == "resumed Soul"


def test_run_soul_hook_fails_when_injected_process_is_replaced(tmp_path):
    tool = _load_tool()
    pid_calls = 0

    def runner(command, **kwargs):
        nonlocal pid_calls
        if command[-2:] == ["pidof", "cn.soulapp.android"]:
            pid_calls += 1
            pid = "42" if pid_calls == 1 else "99"
            return subprocess.CompletedProcess(command, 0, stdout=pid + "\n", stderr="")
        if command[-3:] == ["dumpsys", "activity", "activities"]:
            return subprocess.CompletedProcess(command, 0, stdout="resumed Soul", stderr="")
        if command[-4:-2] == ["logcat", "-d"]:
            return subprocess.CompletedProcess(command, 0, stdout="logcat", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    class FakeProcess:
        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    def process_factory(command, **kwargs):
        kwargs["stdout"].write("hook-installed\n")
        kwargs["stdout"].close()
        return FakeProcess()

    result = tool.run_soul_hook(
        Path("adb"),
        serial="emulator-5558",
        evidence_dir=tmp_path,
        frida_script=Path("inject.js"),
        runner=runner,
        process_factory=process_factory,
        sleep=lambda _: None,
    )

    assert result["status"] == "failed"

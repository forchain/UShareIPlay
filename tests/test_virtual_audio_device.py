import importlib.util
import sys
from pathlib import Path

import yaml


def _load_tool():
    path = Path(__file__).resolve().parents[1] / "scripts" / "virtual_audio_device.py"
    spec = importlib.util.spec_from_file_location("virtual_audio_device", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_avd_uses_play_store_arm64_image():
    tool = _load_tool()

    spec = tool.avd_spec(root_fallback=False)

    assert spec.name == "ushareiplay-audio"
    assert spec.package == "system-images;android-36;google_apis_playstore;arm64-v8a"
    assert spec.play_store is True


def test_root_fallback_uses_disposable_google_apis_image():
    tool = _load_tool()

    spec = tool.avd_spec(root_fallback=True)

    assert spec.name == "ushareiplay-audio-root"
    assert spec.package == "system-images;android-30;google_apis;arm64-v8a"
    assert spec.play_store is False


def test_appium_override_targets_running_avd_serial():
    tool = _load_tool()

    override = tool.appium_override("emulator-5556")

    assert override == {
        "device": {
            "name": "emulator-5556",
            "platform_name": "Android",
            "automation_name": "UiAutomator2",
            "no_reset": True,
        },
        "appium": {"host": "127.0.0.1", "port": 4723},
    }


def test_host_backend_selects_blackhole_on_macos_and_pipewire_on_linux():
    tool = _load_tool()

    assert tool.host_backend("Darwin") == tool.HostAudioBackend.BLACKHOLE
    assert tool.host_backend("Linux") == tool.HostAudioBackend.PIPEWIRE


def test_sdk_tools_use_explicit_sdk_root(tmp_path):
    tool = _load_tool()
    sdk_root = tmp_path / "sdk"
    (sdk_root / "emulator").mkdir(parents=True)
    (sdk_root / "platform-tools").mkdir()
    (sdk_root / "cmdline-tools" / "latest" / "bin").mkdir(parents=True)

    tools = tool.sdk_tools({"ANDROID_SDK_ROOT": str(sdk_root)})

    assert tools.sdk_root == sdk_root
    assert tools.emulator == sdk_root / "emulator" / "emulator"
    assert tools.adb == sdk_root / "platform-tools" / "adb"
    assert tools.sdkmanager == sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager"


def test_default_launch_command_enables_host_microphone(tmp_path):
    tool = _load_tool()
    emulator = tmp_path / "emulator"

    command = tool.emulator_launch_command(emulator, tool.avd_spec(root_fallback=False), port=5556)

    assert command == [
        str(emulator),
        "-avd",
        "ushareiplay-audio",
        "-port",
        "5556",
        "-allow-host-audio",
        "-no-snapshot-save",
    ]


def test_generated_override_preserves_unrelated_local_values(tmp_path):
    tool = _load_tool()
    config_path = tmp_path / "config.local.yaml"
    config_path.write_text(
        "soul:\n  default_party_id: FM00000000\nappium:\n  port: 9999\n",
        encoding="utf-8",
    )

    tool.write_appium_override(config_path, "emulator-5556")

    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == {
        "soul": {"default_party_id": "FM00000000"},
        "device": {
            "name": "emulator-5556",
            "platform_name": "Android",
            "automation_name": "UiAutomator2",
            "no_reset": True,
        },
        "appium": {"host": "127.0.0.1", "port": 4723},
    }


def test_root_fallback_requires_failed_standard_report(tmp_path):
    tool = _load_tool()
    report = tmp_path / "result.json"
    report.write_text('{"status": "passed"}', encoding="utf-8")

    assert tool.root_fallback_allowed(report) is False

    report.write_text('{"status": "failed", "mode": "standard"}', encoding="utf-8")
    assert tool.root_fallback_allowed(report) is True


def test_avd_exists_uses_only_the_named_avd_home_entry(tmp_path):
    tool = _load_tool()
    avd_home = tmp_path / "avd"
    avd_home.mkdir()
    (avd_home / "other.avd").mkdir()

    assert tool.avd_exists(tool.avd_spec(root_fallback=False), avd_home) is False

    (avd_home / "ushareiplay-audio.avd").mkdir()
    assert tool.avd_exists(tool.avd_spec(root_fallback=False), avd_home) is True


def test_create_avd_command_is_noninteractive_and_uses_selected_image(tmp_path):
    tool = _load_tool()
    avdmanager = tmp_path / "avdmanager"

    command = tool.create_avd_command(avdmanager, tool.avd_spec(root_fallback=False))

    assert command == [
        str(avdmanager),
        "create",
        "avd",
        "--force",
        "--name",
        "ushareiplay-audio",
        "--package",
        "system-images;android-36;google_apis_playstore;arm64-v8a",
        "--device",
        "pixel_7",
    ]


def test_parse_adb_devices_returns_only_emulator_serials():
    tool = _load_tool()

    serials = tool.parse_emulator_serials(
        "List of devices attached\n192.168.8.151:5555\tdevice\nemulator-5556\tdevice\nemulator-5558\toffline\n"
    )

    assert serials == ["emulator-5556"]


def test_provision_installs_missing_image_and_creates_only_named_avd(tmp_path):
    tool = _load_tool()
    sdk_root = tmp_path / "sdk"
    (sdk_root / "emulator").mkdir(parents=True)
    (sdk_root / "platform-tools").mkdir()
    (sdk_root / "cmdline-tools" / "latest" / "bin").mkdir(parents=True)
    commands = []

    def runner(command, *, input_text=None):
        commands.append((command, input_text))

    tool.provision_avd(tool.sdk_tools({"ANDROID_SDK_ROOT": str(sdk_root)}), tool.avd_spec(root_fallback=False), tmp_path / "avd", runner)

    assert commands == [
        ([str(sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager"), "--install", "system-images;android-36;google_apis_playstore;arm64-v8a"], None),
        ([str(sdk_root / "cmdline-tools" / "latest" / "bin" / "avdmanager"), "create", "avd", "--force", "--name", "ushareiplay-audio", "--package", "system-images;android-36;google_apis_playstore;arm64-v8a", "--device", "pixel_7"], "no\n"),
    ]

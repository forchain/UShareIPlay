from pathlib import Path


def test_waydroid_script_keeps_audio_routing_opt_in_and_reversible():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "waydroid_virtual_audio.sh").read_text(encoding="utf-8")

    assert 'open)\n    start_session\n    if [[ "${2:-}" == "--loopback" ]]' in script
    assert 'pactl set-default-sink "${VIRTUAL_SINK}"' in script
    assert 'pactl set-default-source "${VIRTUAL_SOURCE}"' in script
    assert 'pactl unload-module "${module_id}"' in script


def test_waydroid_script_provisions_official_runtime_and_waits_for_a_session():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "waydroid_virtual_audio.sh").read_text(encoding="utf-8")

    assert 'apt-get install -y adb pipewire-pulse wireplumber pulseaudio-utils waydroid' in script
    assert 'sudo waydroid init' in script
    assert "Session:[[:space:]]*RUNNING" in script

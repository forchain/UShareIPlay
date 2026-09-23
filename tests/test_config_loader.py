import os
import tempfile
import yaml
from ushareiplay.core.config_loader import ConfigLoader, _deep_merge


def test_deep_merge_preserves_other_commands_when_overriding_single_command():
    base = {
        "commands": [
            {
                "prefix": "play",
                "level": 1,
                "description": "Play music",
                "response_template": "{song}",
            },
            {
                "prefix": "seat",
                "level": 1,
                "description": "Old seat description",
                "response_template": "{success}",
                "error_template": "error: {error}",
            },
            {
                "prefix": "radio",
                "level": 1,
                "description": "Radio command",
            },
        ]
    }

    override = {
        "commands": [
            {
                "prefix": "seat",
                "description": "New seat description with parameters <1/2/3/0>",
            }
        ]
    }

    merged = _deep_merge(base, override)
    commands = merged["commands"]

    # All 3 commands should be present
    assert len(commands) == 3
    prefixes = [c["prefix"] for c in commands]
    assert prefixes == ["play", "seat", "radio"]

    # 'seat' should have updated description, but preserved other fields
    seat_cmd = commands[1]
    assert seat_cmd["prefix"] == "seat"
    assert seat_cmd["description"] == "New seat description with parameters <1/2/3/0>"
    assert seat_cmd["level"] == 1
    assert seat_cmd["response_template"] == "{success}"
    assert seat_cmd["error_template"] == "error: {error}"

    # 'play' and 'radio' should remain untouched
    assert commands[0]["description"] == "Play music"
    assert commands[2]["description"] == "Radio command"


def test_deep_merge_appends_new_command_from_override():
    base = {
        "commands": [
            {"prefix": "play", "level": 1},
        ]
    }
    override = {
        "commands": [
            {"prefix": "custom", "level": 2, "description": "Custom command"},
        ]
    }

    merged = _deep_merge(base, override)
    assert len(merged["commands"]) == 2
    assert merged["commands"][0]["prefix"] == "play"
    assert merged["commands"][1]["prefix"] == "custom"
    assert merged["commands"][1]["level"] == 2


def test_deep_merge_standard_dicts_and_non_command_lists():
    base = {
        "server": {"host": "127.0.0.1", "port": 8080},
        "tags": ["tag1", "tag2"],
        "post_party_create": {
            "enabled": True,
            "commands": [":skip"],
        },
    }
    override = {
        "server": {"port": 9090},
        "tags": ["tag3"],
        "post_party_create": {
            "commands": [":play test"],
        },
    }

    merged = _deep_merge(base, override)
    assert merged["server"] == {"host": "127.0.0.1", "port": 9090}
    assert merged["tags"] == ["tag3"]
    assert merged["post_party_create"]["enabled"] is True
    assert merged["post_party_create"]["commands"] == [":play test"]


def test_config_loader_loads_and_merges_local_yaml():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "config.yaml")
        local_path = os.path.join(tmpdir, "config.local.yaml")

        base_yaml = {
            "general": {"name": "test_bot"},
            "commands": [
                {"prefix": "play", "level": 1, "description": "Play"},
                {"prefix": "seat", "level": 1, "description": "Seat old"},
            ],
        }
        local_yaml = {
            "general": {"debug": True},
            "commands": [
                {"prefix": "seat", "description": "Seat new"},
            ],
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(base_yaml, f)
        with open(local_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(local_yaml, f)

        loaded = ConfigLoader.load_config(config_path)

        assert loaded["general"]["name"] == "test_bot"
        assert loaded["general"]["debug"] is True
        assert len(loaded["commands"]) == 2
        assert loaded["commands"][0]["prefix"] == "play"
        assert loaded["commands"][1]["prefix"] == "seat"
        assert loaded["commands"][1]["description"] == "Seat new"
        assert loaded["commands"][1]["level"] == 1

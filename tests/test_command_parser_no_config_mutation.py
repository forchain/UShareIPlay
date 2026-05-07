from ushareiplay.core.command_parser import CommandParser


def test_command_parser_does_not_mutate_shared_config():
    commands = [
        {"prefix": "help", "response_template": "ok"},
        {"prefix": "play", "response_template": "ok"},
    ]
    parser = CommandParser(commands)

    help_result = parser.parse_command("help")
    assert help_result is not None
    assert help_result["prefix"] == "help"
    assert help_result.get("parameters") == []

    play_result = parser.parse_command("play foo")
    assert play_result is not None
    assert play_result["prefix"] == "play"
    assert play_result.get("parameters") == ["foo"]

    assert "parameters" not in commands[0]
    assert "parameters" not in commands[1]

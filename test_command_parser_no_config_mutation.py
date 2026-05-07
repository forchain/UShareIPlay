from ushareiplay.core.command_parser import CommandParser


def main() -> None:
    commands = [
        {"prefix": "help", "response_template": "ok"},
        {"prefix": "play", "response_template": "ok"},
    ]
    parser = CommandParser(commands)

    r1 = parser.parse_command("help")
    assert r1 is not None
    assert r1["prefix"] == "help"
    assert r1.get("parameters") == []

    r2 = parser.parse_command("play foo")
    assert r2 is not None
    assert r2["prefix"] == "play"
    assert r2.get("parameters") == ["foo"]

    # Shared config must not be mutated by parsing.
    assert "parameters" not in commands[0]
    assert "parameters" not in commands[1]


if __name__ == "__main__":
    main()

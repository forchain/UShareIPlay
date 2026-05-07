from pathlib import Path


def test_command_manager_no_longer_contains_legacy_factory_branch():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ushareiplay"
        / "managers"
        / "command_manager.py"
    ).read_text(encoding="utf-8")

    assert "if hasattr(module, 'create_command')" not in source
    assert "module.command = module.create_command(controller)" not in source
    assert "Command module does not define a concrete BaseCommand subclass or create_command" not in source

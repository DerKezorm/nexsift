"""The interface translates the names of the built-in rules by their English text (frontend/src/lib/ruleNames.ts).
A rule renamed here without the list there would silently show up in English in every language."""

from pathlib import Path

from app.services import presets

NAMES_FILE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "ruleNames.ts"


def test_every_built_in_rule_name_is_known_to_the_interface() -> None:
    text = NAMES_FILE.read_text(encoding="utf-8")
    names = [rule["name"] for rule in presets.DEFAULT_RULES]
    names += [rule["name"] for rules in presets.SOURCE_RULES.values() for rule in rules]
    assert len(names) >= 5
    missing = [name for name in names if f"'{name}'" not in text]
    assert missing == []


def test_every_preset_has_a_door_the_server_knows() -> None:
    for key, preset in presets.PRESETS.items():
        assert preset["protocol"] in ("gotify", "ntfy", "discord", "webhook", "smtp", "syslog"), key

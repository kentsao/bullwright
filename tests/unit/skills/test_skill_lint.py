"""Skill lint (docs/AGENT_SKILLS.md §1 authoring rules + invariant A3):
every SKILL.md declares scopes, references only real bw-agent commands,
carries a self-check, and embeds no URLs or key material."""

import re
from pathlib import Path

import pytest
from bullwright_api.auth.keys import VALID_SCOPES

SKILLS_DIR = Path(__file__).parents[3] / "agents" / "skills"
SKILL_FILES = sorted(SKILLS_DIR.glob("*/SKILL.md"))

EXPECTED_SKILLS = {
    "bw-report-writer",
    "bw-rag-search",
    "bw-earnings-review",
    "bw-thesis-update",
}


def _valid_cli_commands() -> set[str]:
    """A3: derive the allowed surface from the actual typer app, so a
    renamed CLI command breaks this test, not an agent at 2am."""
    from bullwright_client.cli import app as cli_app

    commands: set[str] = set()
    for cmd in cli_app.registered_commands:
        assert cmd.callback is not None
        commands.add(cmd.name or cmd.callback.__name__.replace("_", "-"))
    for group in cli_app.registered_groups:
        assert group.typer_instance is not None
        for cmd in group.typer_instance.registered_commands:
            assert cmd.callback is not None
            sub = cmd.name or cmd.callback.__name__.replace("_", "-")
            commands.add(f"{group.name} {sub}")
    return commands


def test_expected_skills_exist() -> None:
    assert {f.parent.name for f in SKILL_FILES} >= EXPECTED_SKILLS


@pytest.mark.parametrize("skill_file", SKILL_FILES, ids=lambda f: f.parent.name)
def test_skill_declares_valid_scopes(skill_file: Path) -> None:
    text = skill_file.read_text(encoding="utf-8")
    m = re.search(r"\*\*Required scopes:\*\*(.+)", text)
    assert m, "SKILL.md must declare **Required scopes:**"
    declared = set(re.findall(r"`([a-z:]+)`", m.group(1)))
    assert declared, "at least one scope must be declared"
    assert declared <= VALID_SCOPES, f"unknown scopes: {declared - VALID_SCOPES}"
    assert "admin" not in declared, "skills must never require admin (A1)"


@pytest.mark.parametrize("skill_file", SKILL_FILES, ids=lambda f: f.parent.name)
def test_skill_references_only_real_commands(skill_file: Path) -> None:
    text = skill_file.read_text(encoding="utf-8")
    valid = _valid_cli_commands()
    two_word = {c for c in valid if " " in c}
    groups = {c.split()[0] for c in two_word}
    for m in re.finditer(r"bw-agent ([a-z-]+)(?: ([a-z-]+))?", text):
        first, second = m.group(1), m.group(2)
        cmd = f"{first} {second}" if first in groups and second else first
        assert cmd in valid, f"{skill_file.parent.name} references unknown command: {cmd!r}"


@pytest.mark.parametrize("skill_file", SKILL_FILES, ids=lambda f: f.parent.name)
def test_skill_has_self_check(skill_file: Path) -> None:
    text = skill_file.read_text(encoding="utf-8")
    assert re.search(r"^## Self-check", text, re.MULTILINE), "missing Self-check section"
    assert text.count("- [ ]") >= 3, "self-check needs at least 3 items"


@pytest.mark.parametrize("skill_file", SKILL_FILES, ids=lambda f: f.parent.name)
def test_skill_embeds_no_urls_or_keys(skill_file: Path) -> None:
    text = skill_file.read_text(encoding="utf-8")
    assert not re.search(r"https?://", text), "skills must not embed URLs"
    assert not re.search(r"bw_(live|test)_[A-Za-z0-9]", text), "skills must not embed keys"


@pytest.mark.parametrize("skill_file", SKILL_FILES, ids=lambda f: f.parent.name)
def test_skill_states_injection_stance_or_validation(skill_file: Path) -> None:
    """Every skill must teach at least one of the two core disciplines:
    data-not-instructions, or validate-before-upload."""
    text = skill_file.read_text(encoding="utf-8").lower()
    has_injection = "not instructions" in text
    has_validation = "report validate" in text
    assert has_injection or has_validation

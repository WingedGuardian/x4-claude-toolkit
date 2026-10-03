"""OpenCode disclosure (Plan 3 lane L Task 8): OpenCode support is BEST EFFORT, from OpenCode's
docs and source, never measured against a running OpenCode -- and the README must say so, name
the unsupported desktop app (anomalyco/opencode#38604), and name what can switch the guards off."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HEADING = "### OpenCode: best effort, CLI only, from docs, not measured"


def _section() -> str:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert HEADING in text, "README.md has no OpenCode section"
    body = text.split(HEADING, 1)[1]
    return body.split("\n### ", 1)[0].split("\n## ", 1)[0]


def test_the_readme_has_the_opencode_section():
    _section()


def test_the_section_names_the_unsupported_desktop_app():
    s = _section()
    assert "anomalyco/opencode#38604" in s or "anomalyco/opencode/issues/38604" in s
    assert "desktop app" in s.lower() and "not supported" in s.lower()


def test_the_section_says_not_measured_and_names_what_turns_the_guards_off():
    s = _section()
    assert "not measured" in s.lower()
    for must in ("OPENCODE_DISABLE_PROJECT_CONFIG", "X4 GUARDS LIVE", "#5894", "x4doctor.py",
                 "opencode_config.py write", "plugin-only"):
        assert must in s, must


def test_the_agent_table_lists_opencode_and_all_includes_it():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert "`--agent claude | codex | generic | opencode | all | auto`" in text
    assert "| `opencode` |" in text

"""ADAPTING.md is executable documentation: every x4guard command it shows parses, every repo path
it cites exists, no number it states can drift from the code, and installers ship it."""
from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "ADAPTING.md"
TEXT = DOC.read_text(encoding="utf-8") if DOC.is_file() else ""
spec = importlib.util.spec_from_file_location("x4guard_src", REPO / "agent/guards/claude-hooks/x4guard.py")


def test_it_exists_and_names_the_product():
    assert "X4 AI Assistant Toolkit" in TEXT


@pytest.mark.parametrize("heading", [
    "Self-assessment", "fail open or closed", "The guard contract", "Worked example: Claude Code",
    "Worked example: Codex", "Where your adapter goes", "Required proof", "Rules", "Upstream submission"])
def test_every_spec_11_section_is_present(heading):
    assert heading.lower() in TEXT.lower()


def _x4guard_lines():
    return [ln.strip().split("x4guard.py", 1)[1] for ln in TEXT.splitlines()
            if "x4guard.py check" in ln and not ln.strip().startswith(("#", ">"))]


def test_every_check_command_it_shows_parses_with_the_real_cli(monkeypatch):
    lines = _x4guard_lines()
    assert len(lines) >= 3                                   # shell, write, delete at least
    x4g = importlib.util.module_from_spec(spec); spec.loader.exec_module(x4g)
    monkeypatch.setattr(x4g, "verdict_for", lambda *a, **k: {"v": 1})
    for ln in lines:
        argv = [t for t in shlex.split(ln.replace("\\", "/")) if t]
        argv = [("x" if "<" in t else t) for t in argv]      # placeholders like <cmd>
        assert x4g.main(argv) == 0, ln


def test_TWIN_a_wrong_flag_would_have_failed(monkeypatch):
    x4g = importlib.util.module_from_spec(spec); spec.loader.exec_module(x4g)
    with pytest.raises(SystemExit) as e:
        x4g.main(["check", "--agent", "toy", "--kind", "write", "--path", "x"])   # the spec's --agent: not real
    assert e.value.code == 2


def test_every_repo_path_it_cites_exists():
    cited = set(re.findall(r"`((?:agent|scripts|tools|docs)/[^`\s*]+)`", TEXT))
    assert cited
    missing = [p for p in sorted(cited) if not (REPO / p.rstrip("/")).exists() and "<" not in p]
    assert not missing, missing


def test_the_timeout_default_is_never_restated_wrongly(monkeypatch):
    monkeypatch.delenv("X4_GUARD_TIMEOUT_S", raising=False)
    x4g = importlib.util.module_from_spec(spec); spec.loader.exec_module(x4g)
    default = x4g._timeout_setting()[0]
    for m in re.finditer(r"X4_GUARD_TIMEOUT_S[^.\n]{0,60}?default\D{0,10}(\d+(?:\.\d+)?)", TEXT):
        assert float(m.group(1)) == default, m.group(0)


def test_capability_report_fields_match_the_upstream_template():
    def fields(section):
        body = TEXT.split(section, 1)[1].split("\n## ", 1)[0]
        return re.findall(r"^\s*([A-Z][A-Z /-]{2,}):", body, re.M)
    assert fields("## 1.") and fields("## 1.") == fields("## 7.")


@pytest.mark.parametrize("installer,pattern", [("install.sh", r"X4_COPY_ITEMS=\"[^\"]*\bADAPTING\.md\b"),
                                               ("install.ps1", r"\$X4CopyItems\s*=\s*@\([^)]*'ADAPTING\.md'")])
def test_installers_ship_it(installer, pattern):
    assert re.search(pattern, (REPO / installer).read_text(encoding="utf-8"), re.S)


def test_the_instruction_core_points_an_unsupported_agent_at_it():
    assert "ADAPTING.md" in (REPO / "AGENTS.md").read_text(encoding="utf-8")


# --- T7: the once-per-release cold exercise ---------------------------------------------- #
COLD = REPO / "docs" / "ADAPTING-COLD-TEST.md"


def test_the_cold_exercise_gives_the_subagent_only_adapting_and_the_toy_docs():
    t = COLD.read_text(encoding="utf-8")
    prompt = t.split("<!-- PROMPT -->", 2)[1]
    assert "ADAPTING.md" in prompt and "TOY-AGENT.md" in prompt
    for leak in ("codex.py", "x4conformance.py", "toy_adapter.py", "profile.json\"", "MUTANTS"):
        assert leak not in prompt, leak


def test_the_cold_exercise_has_a_pass_criterion_and_a_record_location():
    t = COLD.read_text(encoding="utf-8")
    assert "exits 0" in t and "docs/superpowers/measurements/" in t


def test_review_scope_lists_the_cold_exercise():
    assert "ADAPTING-COLD-TEST.md" in (REPO / "docs" / "REVIEW-SCOPE.md").read_text(encoding="utf-8")


# --- T8: the universal setup prompt ---------------------------------------------------------- #
PROMPT = (REPO / "SETUP_PROMPT.txt").read_text(encoding="utf-8")


def test_setup_prompt_is_agent_neutral_and_routes_unknown_agents():
    assert "X4 AI Assistant Toolkit" in PROMPT and "ADAPTING.md" in PROMPT
    assert "x4doctor" in PROMPT and "--help" in PROMPT          # supported agents come from the installer, not a list here
    assert "Claude runs" not in PROMPT and "Claude Code Modding Toolkit" not in PROMPT


def test_setup_prompt_never_tells_the_agent_to_trust_or_approve_hooks_itself():
    low = PROMPT.lower()
    assert "never approve" in low or "do not approve" in low

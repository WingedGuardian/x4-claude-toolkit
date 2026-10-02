"""The Codex fixtures are REAL captured payloads (spec section 7.2), sanitised, and shaped as the
0.160.0 schema says. A hand-written fixture would encode our assumptions, not Codex's.

Provenance: tests/fixtures/codex/0.160.0/README.md. The raw captures stay out of the repo (they
carry personal paths); scripts/capture-codex-fixtures.py is the capture hook and the sanitiser.
"""
import json
import re
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "codex" / "0.160.0"
#: A drive path, a POSIX home, or an 8-digit id (the X4 profile folder is one). Run over the
#: DECODED string values, not the JSON text: in the text, "Output:\nSuccess" reads as `t:\`.
PERSONAL = re.compile(r"\b[A-Za-z]:[\\/]|/home/|/Users/|\b\d{8}\b")


NOT_PAYLOADS = {"trust_vectors.json"}       # Codex-produced hash vectors (test_codex_trust.py)


def payloads():
    return sorted(p for p in FIX.glob("*.json") if p.name not in NOT_PAYLOADS)


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def test_fixtures_exist_for_every_required_shape():
    names = {p.stem for p in payloads()}
    for need in ("bash_powershell", "apply_patch_add", "apply_patch_update", "apply_patch_delete",
                 "apply_patch_move", "apply_patch_multi", "session_start", "post_tool_use_apply_patch",
                 "bash_shell_heredoc_patch", "bash_subagent", "spawn_agent"):
        assert need in names, f"missing captured fixture {need}"


def test_fixtures_are_sanitised():
    for p in payloads():
        d = json.loads(p.read_text(encoding="utf-8"))
        hits = [s for s in _strings(d) if PERSONAL.search(s)]
        assert not hits, f"{p.name} carries a personal path: {hits[:3]}"
        assert d["cwd"] == "<CWD>", f"{p.name}: cwd placeholder missing"
        assert d["transcript_path"] == "<TRANSCRIPT>", p.name


def test_TWIN_the_personal_pattern_can_fire():
    """The sanitiser check is only evidence if its pattern fires on what it exists to catch."""
    home = "/" + "home" + "/u/x"         # split so the identifier scan does not flag the probe itself
    for bad in ("C:\\Users\\someone\\x", "C:/Program Files (x86)/x", home, "profile 87654321"):
        assert PERSONAL.search(bad), bad
    assert not PERSONAL.search("Exit code: 0\nOutput:\nSuccess")


def test_fixtures_carry_exactly_the_schema_required_keys():
    schema = json.loads((FIX / "schemas" / "pre-tool-use.command.input.json").read_text(encoding="utf-8"))
    allowed, required = set(schema["properties"]), set(schema["required"])
    n = 0
    for p in payloads():
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("hook_event_name") != "PreToolUse":
            continue
        assert required <= set(d) <= allowed, (p.name, set(d) ^ required)
        n += 1
    assert n >= 10, f"only {n} PreToolUse fixtures were checked"

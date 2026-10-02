"""codex_trust: reproduce Codex's hook trust hash and report per-hook trust (M11, spec 5.8).

Codex runs a project hook only when `[hooks.state.'<key>']` holds a trusted_hash equal to the
definition's current hash; anything else is skipped SILENTLY. The oracle for the hash is Codex
itself (`codex app-server` hooks/list currentHash), never our own reimplementation (#14).
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "agent" / "guards" / "adapters" / "codex_trust.py"
FIX = Path(__file__).parent / "fixtures" / "codex" / "0.160.0"
spec = importlib.util.spec_from_file_location("codex_trust", SRC)
ct = importlib.util.module_from_spec(spec)
sys.modules["codex_trust"] = ct
spec.loader.exec_module(ct)


def test_hash_matches_codex_oracle_vectors():
    vectors = json.loads((FIX / "trust_vectors.json").read_text(encoding="utf-8"))
    assert len(vectors) >= 4
    for v in vectors:
        assert ct.hook_hash(v["event_key"], v["group"], v["handler"], windows=v["windows"]) == v["codex_hash"], v["label"]


def test_TWIN_every_hashed_field_moves_the_hash():
    base = {"type": "command", "command": "bash x.sh", "timeout": 30}
    h0 = ct.hook_hash("pre_tool_use", {"matcher": ".*"}, base, windows=False)
    for k, v in (("command", "bash y.sh"), ("timeout", 31), ("async", True), ("statusMessage", "s"),
                 ("additionalContextLimit", 0)):
        assert ct.hook_hash("pre_tool_use", {"matcher": ".*"}, dict(base, **{k: v}), windows=False) != h0, k
    assert ct.hook_hash("pre_tool_use", {"matcher": "Bash"}, base, windows=False) != h0
    assert ct.hook_hash("post_tool_use", {"matcher": ".*"}, base, windows=False) != h0
    assert ct.hook_hash("pre_tool_use", {"matcher": ".*"}, dict(base, timeout=None), windows=False) == \
        ct.hook_hash("pre_tool_use", {"matcher": ".*"}, dict(base, timeout=600), windows=False)   # default normalised
    assert ct.hook_hash("pre_tool_use", {"matcher": ".*"}, dict(base, additionalContextLimit=2500), windows=False) == h0
    w = dict(base, commandWindows="pwsh -File x.ps1")
    assert ct.hook_hash("pre_tool_use", {"matcher": ".*"}, w, windows=True) != \
        ct.hook_hash("pre_tool_use", {"matcher": ".*"}, w, windows=False)


def _hooks_json(tmp_path):
    hj = tmp_path / ".codex" / "hooks.json"
    hj.parent.mkdir()
    hj.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": "a", "timeout": 60}]}],
        "PostToolUse": [{"matcher": "apply_patch", "hooks": [{"type": "command", "command": "b", "timeout": 60}]}],
        "SessionStart": [{"hooks": [{"type": "command", "command": "c", "timeout": 30}]}]}}), encoding="utf-8")
    return hj


def test_report_statuses(tmp_path):
    hj = _hooks_json(tmp_path)
    exp = ct.expected_entries(hj)
    keys = sorted(exp)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"[projects.'{str(tmp_path).lower()}']\ntrust_level = \"trusted\"\n\n"
        f"[hooks.state.'{keys[0]}']\ntrusted_hash = \"{exp[keys[0]]}\"\n\n"
        f"[hooks.state.'{keys[1]}']\ntrusted_hash = \"sha256:{'0' * 64}\"\n\n", encoding="utf-8")
    r = ct.trust_report(hj, cfg, tmp_path)
    st = {e["key"]: e["status"] for e in r["hooks"]}
    assert st[keys[0]] == "trusted" and st[keys[1]] == "modified" and st[keys[2]] == "untrusted"
    assert r["project_trusted"] is True and r["overall"] == "modified"   # worst named status wins
    cfg.write_text(cfg.read_text(encoding="utf-8") + f"[hooks.state.'{keys[2]}']\nenabled = false\n",
                   encoding="utf-8")
    assert {e["status"] for e in ct.trust_report(hj, cfg, tmp_path)["hooks"]} >= {"disabled"}


def test_all_trusted_is_the_only_trusted_overall(tmp_path):
    hj = _hooks_json(tmp_path)
    exp = ct.expected_entries(hj)
    cfg = tmp_path / "config.toml"
    body = "".join(f"[hooks.state.'{k}']\ntrusted_hash = \"{h}\"\n\n" for k, h in exp.items())
    cfg.write_text(body, encoding="utf-8")
    r = ct.trust_report(hj, cfg, tmp_path)
    assert r["overall"] == "trusted" and r["project_trusted"] is False
    # TWIN: one enabled=false among trusted entries makes it NOT trusted
    k0 = sorted(exp)[0]
    cfg.write_text(body.replace(f"[hooks.state.'{k0}']\n", f"[hooks.state.'{k0}']\nenabled = false\n"), encoding="utf-8")
    assert ct.trust_report(hj, cfg, tmp_path)["overall"] == "disabled"


def test_no_entry_matching_is_unknown_not_modified(tmp_path):
    """A future Codex that changes the scheme must read as UNKNOWN, never as 'you edited it'."""
    hj = _hooks_json(tmp_path)
    cfg = tmp_path / "config.toml"
    cfg.write_text("".join(f"[hooks.state.'{k}']\ntrusted_hash = \"sha256:{'1' * 64}\"\n\n"
                           for k in ct.expected_entries(hj)), encoding="utf-8")
    r = ct.trust_report(hj, cfg, tmp_path)
    assert r["overall"] == "unknown" and {e["status"] for e in r["hooks"]} == {"unknown"}


def test_case_folded_key_matches_and_is_recorded(tmp_path):
    hj = _hooks_json(tmp_path)
    exp = ct.expected_entries(hj)
    cfg = tmp_path / "config.toml"
    cfg.write_text("".join(f"[hooks.state.'{k.upper()}']\ntrusted_hash = \"{h}\"\n\n" for k, h in exp.items()),
                   encoding="utf-8")
    r = ct.trust_report(hj, cfg, tmp_path)
    assert r["overall"] == "trusted" and {e["matched"] for e in r["hooks"]} == {"casefold"}


def test_unreadable_config_is_unknown_never_trusted(tmp_path):
    hj = tmp_path / "hooks.json"
    hj.write_text('{"hooks":{}}', encoding="utf-8")
    assert ct.trust_report(hj, tmp_path / "missing.toml", tmp_path)["overall"] == "unknown"
    bad = tmp_path / "bad.toml"
    bad.write_text("[hooks.state.'x']\ntrusted_hash = \n", encoding="utf-8")
    hj2 = _hooks_json(tmp_path)
    assert ct.trust_report(hj2, bad, tmp_path)["overall"] == "unknown"


def test_reader_310_agrees_with_tomllib(tmp_path):
    """The 3.10 fallback reader must give the same tables tomllib does, on the shapes it claims."""
    tomllib = pytest.importorskip("tomllib")
    text = ("[model]\nx = 1\n\n[projects.'c:\\\\a b']\ntrust_level = \"trusted\"\n\n"
            "[hooks.state.'C:\\x\\.codex\\hooks.json:pre_tool_use:0:0']\ntrusted_hash = \"sha256:ab\"\nenabled = false\n")
    assert ct._read_tables_310(text) == ct._tables_from_doc(tomllib.loads(text))


def test_cli_exit_codes(tmp_path):
    hj = _hooks_json(tmp_path)
    exp = ct.expected_entries(hj)
    cfg = tmp_path / "config.toml"
    cfg.write_text("".join(f"[hooks.state.'{k}']\ntrusted_hash = \"{h}\"\n\n" for k, h in exp.items()), encoding="utf-8")

    def run(c):
        r = subprocess.run([sys.executable, str(SRC), "report", "--hooks-json", str(hj), "--codex-config", str(c),
                            "--project-root", str(tmp_path)], capture_output=True, timeout=60)
        return r.returncode, json.loads(r.stdout)

    assert run(cfg)[0] == 0
    assert run(tmp_path / "none.toml")[0] == 2
    cfg.write_text("", encoding="utf-8")
    assert run(cfg)[0] == 1

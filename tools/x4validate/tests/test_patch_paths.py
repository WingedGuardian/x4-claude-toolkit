"""The ONE shared apply_patch path parser (spec section 5.2). It refuses any grammar it does not
know: a patch it cannot read must become an inert deny, never a partial list of paths."""
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "agent" / "guards" / "adapters" / "patch_paths.py"
FIX = Path(__file__).parent / "fixtures" / "codex" / "0.160.0"
spec = importlib.util.spec_from_file_location("patch_paths", SRC)
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)


def test_add_update_delete_move_multi():
    text = ("*** Begin Patch\n*** Add File: a/new.xml\n+<x/>\n*** Update File: b/old.xml\n@@\n-a\n+b\n"
            "*** Update File: c/from.xml\n*** Move to: d/to.xml\n@@\n-a\n+b\n*** Delete File: e/gone.xml\n*** End Patch")
    assert pp.parse_patch(text) == [("add", "a/new.xml"), ("update", "b/old.xml"),
                                    ("move_from", "c/from.xml"), ("move_to", "d/to.xml"),
                                    ("delete", "e/gone.xml")]


def test_header_text_inside_added_content_is_content():
    text = "*** Begin Patch\n*** Add File: a.txt\n+*** Delete File: reference/x.xml\n*** End Patch"
    assert pp.parse_patch(text) == [("add", "a.txt")]


def test_crlf_and_end_of_file_marker_tolerated():
    text = ("*** Begin Patch\r\n*** Update File: a.txt\r\n@@\r\n-a\r\n+b\r\n*** End of File\r\n"
            "*** End Patch\r\n")
    assert pp.parse_patch(text) == [("update", "a.txt")]


def test_paths_with_spaces_and_drive_letters_kept_verbatim():
    text = "*** Begin Patch\n*** Update File: C:\\X4 Foundations\\libraries\\wares.xml\n@@\n-a\n+b\n*** End Patch"
    assert pp.parse_patch(text) == [("update", "C:\\X4 Foundations\\libraries\\wares.xml")]


@pytest.mark.parametrize("bad", [
    "*** Add File: a.txt\n+x\n*** End Patch",                          # no Begin
    "*** Begin Patch\n*** Add File: a.txt\n+x",                        # no End
    "*** Begin Patch\n*** Rename File: a -> b\n*** End Patch",         # unknown header
    "*** Begin Patch\n*** Add File:   \n*** End Patch",                # empty path
    "*** Begin Patch\n*** Move to: x\n*** End Patch",                  # Move without Update
    "*** Begin Patch\n*** End Patch",                                  # touches nothing
    "*** Begin Patch\n*** Add File: a\n+x\n*** End Patch\n*** Delete File: b",   # text after End
    "",                                                                # nothing at all
])
def test_malformed_patch_refuses(bad):
    with pytest.raises(pp.PatchParseError):
        pp.parse_patch(bad)


def test_every_captured_fixture_parses():
    n = 0
    for p in sorted(FIX.glob("apply_patch_*.json")):
        ops = pp.parse_patch(json.loads(p.read_text(encoding="utf-8"))["tool_input"]["command"])
        assert ops, p.name
        n += 1
    assert n >= 5, f"only {n} apply_patch fixtures were exercised"


def test_captured_move_fixture_yields_both_ends():
    d = json.loads((FIX / "apply_patch_move.json").read_text(encoding="utf-8"))
    assert pp.parse_patch(d["tool_input"]["command"]) == [("move_from", "mv.txt"), ("move_to", "moved.txt")]


def test_shell_heredoc_body_is_extracted():
    """P3 (MEASURED): `apply_patch <<'PATCH' ... PATCH` through the shell arrives as Bash."""
    d = json.loads((FIX / "bash_shell_heredoc_patch.json").read_text(encoding="utf-8"))
    body = pp.shell_patch_body(d["tool_input"]["command"])
    assert body is not None and pp.parse_patch(body) == [("add", "viashell.txt")]
    assert pp.shell_patch_body("Get-Content notes.txt") is None
    assert pp.shell_patch_body("echo apply_patch") is None            # a mention, not the command


def test_shell_patch_after_cd_reports_the_directory():
    cmd = "cd 'dev/my mod' && apply_patch <<'EOF'\n*** Begin Patch\n*** Add File: a.xml\n+<a/>\n*** End Patch\nEOF"
    body, cd = pp.shell_patch(cmd)
    assert cd == "dev/my mod" and pp.parse_patch(body) == [("add", "a.xml")]


@pytest.mark.parametrize("cmd", [
    "echo hi; apply_patch <<'EOF'\n*** Begin Patch\n*** Add File: a\n+x\n*** End Patch\nEOF",  # unattributable
    "apply_patch",                                                                              # no body at all
])
def test_shell_patch_it_cannot_read_refuses(cmd):
    body, _ = pp.shell_patch(cmd)
    with pytest.raises(pp.PatchParseError):
        pp.parse_patch(body)

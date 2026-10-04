"""The ONE shared apply_patch path parser (spec section 5.2). It refuses any grammar it does not
know: a patch it cannot read must become an inert deny, never a partial list of paths."""
import importlib.util
import json
import os
import shutil
import subprocess
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


# --- R2-F1 (v4.0.0): the guard must read a patch exactly as the AGENT does --------------------
#
# The Codex record is MEASURED: scripts/capture-codex-patch-oracle.py ran every shape through
# `codex --codex-run-as-apply-patch` (Codex's own parser and applier) and wrote down which files
# changed. Before this fix an INDENTED `  *** Delete File: <ref>/x` after an Add was a header to
# Codex and content to the guard: Codex deleted the file, the guard never saw the path.

ORACLE = json.loads((FIX / "patch_grammar_oracle.json").read_text(encoding="utf-8"))
#: what a parsed op does to a file, in the record's words
EFFECT = {"add": "added", "update": "changed", "delete": "removed", "move_from": "removed", "move_to": "added"}
#: rows that MUST be in the record: the R2-F1 shapes and one twin per clause of the header rule
#: (trimmed in Begin/Add/Delete state, only right-trimmed inside an Update, Rust's whitespace set)
REQUIRED = {"indented-after-add", "tab-indented-after-add", "indented-first", "indented-after-delete",
            "indented-after-update", "indented-after-eof", "indented-update-after-add",
            "fs-indented-after-add", "nbsp-indented-after-add", "trailing-ws-header", "lowercase",
            "nospace-after-stars", "two-spaces-after-colon", "heredoc-wrapped", "environment-id"}


def test_the_codex_record_is_whole():
    names = {r["name"] for r in ORACLE["rows"]}
    assert REQUIRED <= names, REQUIRED - names
    assert len(names) == len(ORACLE["rows"]) >= 60
    applied = [r for r in ORACLE["rows"] if r["rc"] == 0]
    refused = [r for r in ORACLE["rows"] if r["rc"] != 0]
    assert len(applied) >= 30 and len(refused) >= 15, (len(applied), len(refused))


@pytest.mark.parametrize("row", ORACLE["rows"], ids=lambda r: r["name"])
def test_the_guard_reads_every_shape_as_codex_does(row):
    """Codex APPLIED it -> the guard names exactly the files Codex changed, each with the op that
    explains the change. Codex refused to PARSE it -> the guard refuses too. The only other
    outcome on record is the empty patch, which Codex parses and the guard refuses on purpose
    (a patch that touches nothing is never a reason to allow)."""
    if row["rc"] == 0:
        ops = pp.parse_patch(row["patch"])
        named = {}
        for op, path in ops:
            named.setdefault(path, set()).add(EFFECT[op])
        assert set(named) == set(row["touched"]), (ops, row["touched"])
        assert all(row["touched"][p] in named[p] for p in named), (ops, row["touched"])
    elif row["stderr"].startswith("Invalid patch"):
        with pytest.raises(pp.PatchParseError):
            pp.parse_patch(row["patch"])
    else:
        assert row["name"] == "empty-patch" and row["stderr"] == "No files were modified.", \
            f"{row['name']}: Codex parsed it but could not apply it -- give the shape a file setup " \
            "in capture-codex-patch-oracle.py so the record shows what it touches"
        with pytest.raises(pp.PatchParseError):
            pp.parse_patch(row["patch"])


def test_an_indented_delete_after_an_add_is_a_delete():
    """The R2-F1 repro, spelled out (the record holds the same shape against a scratch file)."""
    text = "*** Begin Patch\n*** Add File: h.txt\n+hi\n  *** Delete File: C:/X4/reference/libraries/wares.xml\n*** End Patch"
    assert pp.parse_patch(text) == [("add", "h.txt"), ("delete", "C:/X4/reference/libraries/wares.xml")]


# OpenCode runs its OWN parser (packages/opencode/src/patch/index.ts), which differs from Codex's:
# headers only at column 0, unknown lines skipped, `*** Add File:x` accepted, paths trimmed. The
# guard's OpenCode reading is held to that parser, vendored and run under node.

OC_PARSER = Path(__file__).parent / "fixtures" / "opencode" / "patch-v1.18.34.mts"
NODE = shutil.which("node")
OC_EXTRA = [
    "*** Begin Patch\n*** Add File:x.txt\n+a\n*** End Patch",                    # no space after colon
    "*** Begin Patch\n*** Add File: h\n+hi\n  *** Delete File: v\n*** End Patch",  # indented: skipped
    "junk\n*** Begin Patch\n*** Delete File: v\n*** End Patch",                  # junk before Begin
    "*** Begin Patch\n*** Delete File: v\n*** End Patch\n*** Delete File: w",    # text after End
    "*** Begin Patch\n*** Add File: h\nhi\n*** Delete File: v\n*** End Patch",   # bare content skipped
    "*** Begin Patch\n*** Update File: a\n*** Move to:   \n*** End Patch",       # empty move
    "*** Begin Patch\n*** Update File:   \n*** Move to: b\n*** Delete File: v\n*** End Patch",
    "*** Begin Patch\n*** Add File:    \n+x\n*** Delete File: v\n*** End Patch",  # empty add path
    "*** Begin Patch\n*** Update File: a\n@@\n-x\n*** End of File\n*** Delete File: v\n*** End Patch",
    "cat <<'PATCH'\n*** Begin Patch\n*** Delete File: v\n*** End Patch\nPATCH",  # heredoc, any word
    "<<\"X1\"\n*** Begin Patch\n*** Delete File: v\n*** End Patch\nX1  ",
    "\ufeff*** Begin Patch\n*** Delete File: v\n*** End Patch",                 # BOM is JS whitespace
    "\x85*** Begin Patch\n*** Delete File: v\n*** End Patch",                   # NEL is not
    "*** Begin Patch\n*** Delete File: v\u3000\n*** End Patch",
    "*** Begin Patch\r\n*** Update File: a\r\n*** Move to: b\r\n@@\r\n-x\r\n*** End Patch\r\n",
    "  *** End Patch\n*** Begin Patch\n*** Delete File: v\n*** End Patch",     # End before Begin
    "*** Begin Patch\n*** End Patch",
    "",
]


def _oc_node(cases: list, tmp_path: Path) -> list:
    v = subprocess.run([NODE, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    major, minor = (int(x) for x in v.split(".")[:2])
    strip = [] if (major, minor) >= (23, 6) else ["--experimental-strip-types"]
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    driver = tmp_path / "drive.mjs"
    driver.write_text(
        "import { readFileSync } from 'node:fs';\n"
        f"import {{ parsePatch }} from {json.dumps(OC_PARSER.as_uri())};\n"
        "const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));\n"
        "process.stdout.write(JSON.stringify(cases.map((t) => {\n"
        "  try { return parsePatch(t).hunks.map((h) => [h.type, h.path, h.move_path ?? null]); }\n"
        "  catch (e) { return 'ERROR'; } })));\n", encoding="utf-8")
    r = subprocess.run([NODE, "--no-warnings", *strip, str(driver), str(tmp_path / "cases.json")],
                       capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return json.loads(r.stdout)


def _oc_ops(hunks) -> list | str:
    """OpenCode's hunks as the guard's ops; 'REFUSED' where OpenCode's tool would fail the call
    (a parse error, or no hunks: apply_patch.ts rejects both before touching a file)."""
    if hunks == "ERROR" or not hunks:
        return "REFUSED"
    ops = []
    for kind, path, move in hunks:
        if kind == "update" and move:
            ops += [("move_from", path), ("move_to", move)]
        else:
            ops.append((kind, path))
    return ops


def test_the_guard_reads_every_shape_as_opencode_does(tmp_path):
    if not NODE:
        if os.environ.get("CI"):
            pytest.fail("node is required on CI to check the patch reading against OpenCode's own parser")
        pytest.skip("node not installed -- the OpenCode patch reading NOT cross-checked")
    cases = [r["patch"] for r in ORACLE["rows"]] + OC_EXTRA
    theirs = [_oc_ops(h) for h in _oc_node(cases, tmp_path)]
    ours = []
    for t in cases:
        try:
            ours.append(pp.parse_patch_opencode(t))
        except pp.PatchParseError:
            ours.append("REFUSED")
    diff = [(c, a, b) for c, a, b in zip(cases, ours, theirs) if a != b]
    assert diff == [] and len(theirs) == len(cases)
    assert theirs.count("REFUSED") >= 5 and len(theirs) - theirs.count("REFUSED") >= 30


def test_opencode_skips_an_indented_header_codex_obeys():
    """The two agents disagree on this shape; each adapter must use its own agent's reading."""
    text = "*** Begin Patch\n*** Add File: h\n+hi\n  *** Delete File: v\n*** End Patch"
    assert pp.parse_patch(text) == [("add", "h"), ("delete", "v")]
    assert pp.parse_patch_opencode(text) == [("add", "h")]

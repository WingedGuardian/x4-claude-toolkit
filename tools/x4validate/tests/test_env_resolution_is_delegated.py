r"""Configuration is read through `_paths`, never straight from `os.environ`.

THE DEFECT THIS PINS (MEASURED 2026-08-23). `_paths` resolves every setting in
LAYERS — real environment, then `.claude/x4-paths.env`, then a local fallback.
A caller that reads `os.environ` directly sees only the first layer, so a value
the user put in the config file is invisible to it. Two consumers did:

  _nexus.nexus_key()   `setup.sh` documents putting `X4_NEXUS_KEY` in the config
                       file. Following our own instructions produced "not set".
  _effective           read `os.environ` at IMPORT time into `DB_PATH`, which is
                       also an argparse default — while `gates/_env.py` resolved
                       the SAME variable through `_paths`. Two doors to one
                       question: a gate and the CLI could disagree about which
                       store was configured. That is the shape of F30.

The wider family is "an executable that resolves its own environment instead of
delegating". Every environment defect found in the 2.5.0 audit was of that shape,
and the ones that shipped were all in SCRIPTS that hand-rolled a fallback to a
developer's absolute path — indexing zero documents and exiting 0.

WHY AST AND NOT GREP. A text search for `os.environ` matches the word inside the
very docstrings that explain the rule, and would have reported four false hits
on the fixed files. A checker that cannot tell code from prose is the checker
being wrong, not the code — the most repeated defect in this workspace.

ESCAPE HATCH: a legitimate direct read carries `# env-ok: <reason>` on or just
above the line. There is exactly one at the time of writing (building an env dict
to hand to a subprocess), and it is not a configuration lookup at all.

HONEST SCOPE: walks `x4validate/`, `gates/` and `tools/basex/`. A throwaway
script is covered by no linter — the same caveat the sibling guards carry.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = [ROOT / "x4validate", ROOT / "gates", ROOT.parent / "basex"]
MARKER = "env-ok"

#: `_paths.py` IS the resolver — it is the one place allowed to read the
#: environment. `_registry.py` is exempt from nothing here; it already delegates.
EXEMPT_FILES = {"_paths.py"}


def _annotation_window(lines: list[str], start: int, end: int) -> list[str]:
    """The statement itself, plus the CONTIGUOUS comment block directly above it.

    Deliberately not "the previous N lines". A fixed window is a magic number that
    silently decides how long a justification is allowed to be — the first draft
    used 2 and rejected both real exemptions, whose reasons run to three and four
    lines. Walking up while the lines are comments matches how a reader actually
    scopes a rationale, and cannot be defeated by writing one more sentence.
    """
    top = start
    while top > 0 and lines[top - 1].lstrip().startswith("#"):
        top -= 1
    return lines[top:end]


def _env_reads(path: Path) -> list[tuple[int, str]]:
    """(lineno, source) for each direct environment read in *path*.

    Catches both spellings: the `os.environ` mapping (subscript, `.get`, `dict()`,
    iteration — any use of the attribute at all) and `os.getenv(...)`.

    Parse errors RAISE. A guard that skips a file it cannot read reports a clean
    sweep over a population it never scanned — which has bitten here already: an
    ad-hoc scan under Python 3.10 silently dropped `_check.py`, whose PEP 701
    f-string needs 3.12+.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        hit = False
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            hit = isinstance(node.value, ast.Name) and node.value.id == "os"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            hit = (node.func.attr == "getenv"
                   and isinstance(node.func.value, ast.Name)
                   and node.func.value.id == "os")
        if not hit:
            continue
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        if any(MARKER in ln for ln in _annotation_window(lines, start, end)):
            continue
        out.append((node.lineno, (ast.get_source_segment(source, node) or "")[:70]))
    return out


def _files() -> list[Path]:
    out: list[Path] = []
    for root in SCAN_ROOTS:
        if root.is_dir():
            out += [p for p in sorted(root.rglob("*.py"))
                    if "__pycache__" not in p.parts]
    return out


def test_the_scan_covers_a_real_population():
    """State the denominator BEFORE any finding — an empty sweep proves nothing."""
    files = _files()
    assert len(files) >= 40, (
        f"only {len(files)} files found; the scan roots are probably wrong, and a "
        f"guard over nothing passes forever")


def test_no_module_reads_the_environment_directly():
    offenders: list[str] = []
    for path in _files():
        if path.name in EXEMPT_FILES:
            continue
        for lineno, src in _env_reads(path):
            offenders.append(f"{path.relative_to(ROOT.parent)}:{lineno}: {src}")
    assert not offenders, (
        "read configuration through `_paths.value()` / `_paths.path_value()` so the "
        "config-file layer is honoured, or mark a genuine non-config use with "
        f"`# {MARKER}: <reason>`:\n  " + "\n  ".join(offenders))


def test_the_guard_can_actually_fail(tmp_path):
    """If it cannot be made to go red on purpose, it verifies nothing.

    Both spellings, and the marker, are exercised — a guard that catches only the
    form its author happened to think of is the same blind spot one layer up.
    """
    bad = tmp_path / "bad.py"
    bad.write_text("import os\nv = os.environ.get('X4_REFERENCE')\n", encoding="utf-8")
    assert _env_reads(bad), "os.environ went undetected"

    bad2 = tmp_path / "bad2.py"
    bad2.write_text("import os\nv = os.getenv('X4_REFERENCE')\n", encoding="utf-8")
    assert _env_reads(bad2), "os.getenv went undetected"

    ok = tmp_path / "ok.py"
    ok.write_text("import os\ne = dict(os.environ)  # env-ok: subprocess env\n",
                  encoding="utf-8")
    assert not _env_reads(ok), "the escape hatch did not suppress the finding"

    multi = tmp_path / "multi.py"
    multi.write_text("import os\n# env-ok: reason line one\n# continued onto a\n"
                     "# third line, as real justifications do\ne = dict(os.environ)\n",
                     encoding="utf-8")
    assert not _env_reads(multi), "a multi-line justification must be honoured"


def test_a_stale_marker_elsewhere_does_not_grant_an_exemption(tmp_path):
    """The hatch must attach to THIS statement, not to anything above it.

    Widening the search window is how an escape hatch quietly becomes a blanket
    amnesty: an `# env-ok:` written for one line would start excusing every later
    one in the file. Intervening code closes the window.
    """
    sneaky = tmp_path / "sneaky.py"
    sneaky.write_text(
        "import os\n"
        "# env-ok: this justifies the NEXT line only\n"
        "a = dict(os.environ)\n"
        "b = os.environ.get('X4_REFERENCE')\n",
        encoding="utf-8")
    hits = _env_reads(sneaky)
    assert [ln for ln, _ in hits] == [4], f"expected only line 4 to be flagged, got {hits}"


def test_a_file_that_cannot_be_parsed_raises(tmp_path):
    """Never skip an unreadable file — that is a clean sweep over nothing."""
    broken = tmp_path / "broken.py"
    broken.write_text("def (:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        _env_reads(broken)

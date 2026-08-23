r"""A `reference/` walk that is LOOSE-ONLY cannot see the packed DLC.

THE DEFECT THIS PINS. Six of the eight DLC are unpacked under `reference\`; the
two mini-DLC (Hyperion Pack, Envoy Pack) are NEVER unpacked -- their content
lives in `ext_*.cat` inside the game install. A plain `reference.rglob("*.xml")`
therefore enumerates 9,138 documents where 9,280 exist, and says nothing.

MEASURED, the SEVENTH occurrence of this shape (2026-08-22, F34):
`tools/basex/build-effective.py::all_vpaths` walked `reference` loose-only, so
BaseX `x4eff` held **23 of 142 mini-DLC documents (16%)**. The 23 were not a
partial success -- they arrived incidentally, because two unrelated mods happen
to nest patches under `extensions/ego_dlc_mini_0X/`. And the coverage check that
gates negative claims over that index reported COMPLETE the whole time, because
it reconciled produced-against-indexed and a vpath never enumerated cannot fail
(F35).

The prior six were `_input.py`, `_migration.py`, `_effective.py`, `_xref.py`,
`_similarity.py` and `stage.py`. `_effective.py:136` has carried a comment naming
this exact bug, with this exact denominator, since 2026-08-12 -- and the seventh
was written anyway. **A comment in one file does not stop the next file.**

WHAT TO DO INSTEAD: `_effective.base_vpaths(config, pattern)` -- loose THEN
packed, one implementation. For per-mod XML use `_scan.iter_mod_xml`.

HONEST SCOPE, so a green here is not read as more than it is: this walks
`x4validate/`, `gates/` and `tools/basex/` -- the packages and the gates. A
throwaway script is not covered by any linter, and the measured failure in the
`_cat.mod_vfs` sibling guard happened in exactly such a script. This stops the
committed code from re-committing the shape; it is not full coverage.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = [ROOT / "x4validate", ROOT / "gates", ROOT.parent / "basex"]
MARKER = "reference-scope-ok"

#: `_scan.py` IS the sanctioned loose-then-packed per-mod reader; its loose pass is
#: the documented first half, paired with a packed pass a few lines below.
EXEMPT_FILES = {"_scan.py"}

#: A glob receiver that plausibly names the reference tree. `ref`/`root` are the
#: two names this codebase has actually used for it.
_SUSPECT_NAMES = {"ref", "root"}


def _suspect_calls(path: Path) -> list[tuple[int, str]]:
    """(lineno, source) for every unacknowledged reference-rooted glob in *path*.

    A parse failure RAISES rather than returning nothing. A guard that skips the
    file it cannot read reports a clean sweep over a population it never saw --
    which is the same defect class this test exists to police, turned on itself.
    (It has already bitten once: an ad-hoc version of this scan ran on Python
    3.10 and silently dropped `_check.py`, whose PEP 701 f-string needs 3.12+.)
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)  # deliberately unguarded -- see docstring
    lines = source.splitlines()
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"glob", "rglob"}):
            continue
        recv = (ast.get_source_segment(source, node.func.value) or "").strip()
        if "reference" not in recv.lower() and recv not in _SUSPECT_NAMES:
            continue
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        # Look one line ABOVE too, so a multi-line rationale can precede the call.
        window = lines[max(0, start - 4):end]
        if any(MARKER in line for line in window):
            continue
        out.append((node.lineno, (ast.get_source_segment(source, node) or "")[:80]))
    return out


def _python_files() -> list[Path]:
    return [p for root in SCAN_ROOTS if root.is_dir()
            for p in sorted(root.glob("*.py")) if p.name not in EXEMPT_FILES]


def test_the_scan_population_is_not_empty():
    """Denominator guard. Every assertion below passes trivially over an empty
    file list, so the file list is asserted first."""
    files = _python_files()
    assert len(files) >= 40, (
        f"only {len(files)} python file(s) found under {[str(r) for r in SCAN_ROOTS]} -- "
        f"the scan roots are wrong, and a green result here would prove nothing.")


def test_no_unacknowledged_loose_only_reference_walk():
    """THE GATE."""
    offenders = []
    for path in _python_files():
        for lineno, src in _suspect_calls(path):
            offenders.append(f"{path.name}:{lineno}  {src}")
    assert not offenders, (
        "these glob a reference-rooted path without acknowledging the packed DLC:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse `_effective.base_vpaths(config, pattern)` (loose THEN packed), or "
          "`_scan.iter_mod_xml` for per-mod XML. If the walk is genuinely correct as-is "
          f"-- schemas, a staged tree counted elsewhere -- add an inline `# {MARKER}:` "
          "comment SAYING WHY, on or just above the call. A bare marker is not the "
          "point; the reason is.")


def test_the_detector_actually_detects(tmp_path):
    """Proven-to-fail guard. Without this, a detector that had gone blind -- a
    renamed attribute, a changed AST shape -- would report the same reassuring
    green as a clean tree."""
    bad = tmp_path / "offender.py"
    bad.write_text("from pathlib import Path\n"
                   "def f(reference: Path):\n"
                   "    return list(reference.rglob('*.xml'))\n", encoding="utf-8")
    assert _suspect_calls(bad), "the detector no longer sees a plain reference.rglob"

    good = tmp_path / "acknowledged.py"
    good.write_text("from pathlib import Path\n"
                    "def f(reference: Path):\n"
                    f"    # {MARKER}: schemas only, measured\n"
                    "    return list(reference.rglob('*.xsd'))\n", encoding="utf-8")
    assert not _suspect_calls(good), "the marker no longer suppresses a verified site"


def test_a_file_that_will_not_parse_raises_rather_than_reporting_clean(tmp_path):
    """The narrowing-step contract: a file we cannot read is a NON-ANSWER, never
    an absence. Silently skipping it is how a guard reports a clean sweep over a
    population it never scanned."""
    broken = tmp_path / "broken.py"
    broken.write_text("def f(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        _suspect_calls(broken)

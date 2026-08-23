r"""`_cat.mod_vfs` reads CATALOGS ONLY — using it as "every XML a mod owns" is a bug.

THE DEFECT THIS PINS (MEASURED 2026-08-13). An ad-hoc corpus scan built on
`_cat.mod_vfs` alone read **2,681** XML files across 115 mods and reported a name
"NOT FOUND". `mod_vfs` returns `{}` for a loose mod, silently. Adding the loose
half read **4,401** and found the name immediately, in a loose file. The only
thing that caught it was 2,681 looking too low — not a tool, not a test.

`_scan.iter_mod_xml` / `iter_mod_xml_bytes` already enumerate loose THEN packed
with the engine's loose-shadows-packed rule. This is the SEVENTH instance of the
shape `_scan.py`'s own docstring was written about ("six modules each hand-rolled
the same loop... patching the six copies individually guarantees a seventh").

⚠ HONEST SCOPE — read before trusting this green. It walks `x4validate/` and
`gates/` only. The measured failure happened in a THROWAWAY SCRIPT, which no
linter will ever see, so this guard would NOT have caught it. The mechanism that
does reach a scratch script is the runtime warning in `_cat.mod_vfs` itself. This
test exists to stop the package and the gates from re-committing the shape; it is
not, and must not be described as, full coverage.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "x4validate"
GATES = ROOT / "gates"
MARKER = "packed-ok"

#: `_cat.py` defines it; `_scan.py` is the sanctioned packed+loose reader.
EXEMPT_FILES = {"_cat.py", "_scan.py"}


def _is_mod_vfs_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "mod_vfs")


def _acknowledged(node: ast.Call, lines: list[str]) -> bool:
    """Either an explicit packed_only= kwarg, or an inline `# packed-ok:` marker."""
    if any(kw.arg == "packed_only" for kw in node.keywords):
        return True
    start = node.lineno - 1
    end = getattr(node, "end_lineno", node.lineno)
    return any(MARKER in line for line in lines[start:end])


def _offenders(*roots: Path) -> list[str]:
    out = []
    for root in roots:
        for path in sorted(root.glob("*.py")):
            if path.name in EXEMPT_FILES:
                continue
            source = path.read_text(encoding="utf-8")
            lines = source.splitlines()
            for node in ast.walk(ast.parse(source)):
                if _is_mod_vfs_call(node) and not _acknowledged(node, lines):
                    out.append(f"{path.name}:{node.lineno}")
    return out


def test_no_unacknowledged_packed_only_scan():
    offenders = _offenders(PACKAGE, GATES)
    assert not offenders, (
        "these calls use the CATALOGS-ONLY reader without saying they mean it:\n  "
        + "\n  ".join(offenders) +
        "\n\n`_cat.mod_vfs` returns {} for a loose mod. If you want every XML a mod "
        "owns, use `_scan.iter_mod_xml` / `iter_mod_xml_bytes`. If you genuinely mean "
        "catalogs only, pass `packed_only=True` or add an inline `# packed-ok: <reason>`."
    )


def test_the_guard_actually_detects_an_unacknowledged_call(tmp_path):
    """Mutation test for the guard itself.

    A guard that cannot fail reports green forever and teaches you to trust it.
    """
    (tmp_path / "offender.py").write_text(
        "from x4validate import _cat\n"
        "def f(d):\n"
        "    return [v for v in _cat.mod_vfs(d)]\n", encoding="utf-8")
    assert _offenders(tmp_path) == ["offender.py:3"]


def test_the_guard_accepts_both_acknowledgement_forms(tmp_path):
    (tmp_path / "ok.py").write_text(
        "from x4validate import _cat\n"
        "def f(d):\n"
        "    a = _cat.mod_vfs(d, packed_only=True)\n"
        "    b = _cat.mod_vfs(d)  # packed-ok: exercising the reader\n"
        "    return a, b\n", encoding="utf-8")
    assert _offenders(tmp_path) == []

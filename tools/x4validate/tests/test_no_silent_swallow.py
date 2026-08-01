r"""The guard that makes the bug class extinct instead of merely fixed.

Every false pass this package has shipped had one shape::

    except SomeError:
        continue          # or: pass / return set() / return [] / return None

The caller then cannot tell *found nothing* from *could not look*, and silence
renders as OK. It has now been fixed at four layers (`Report.skipped`,
`coverage.json`, `_input.require_mod_dir`, `_scan.iter_mod_xml`) — and it kept
coming back because six modules each hand-rolled the same loop. Fixing instances
without a guard just schedules the seventh.

So: walk the package AST and fail on any handler whose body only swallows.

**Allowlisting is by inline marker comment, never by file+line.** Line numbers
churn on every edit, so a line-based allowlist rots into a rubber stamp within a
week — and it puts the justification somewhere nobody reads. A marker forces the
reason to live at the code it excuses::

    except (AttributeError, ValueError):
        pass  # silent-ok: console encoding shim, failure means default codec

Prototyped before adoption: 28 sites flagged, ~13 of them legitimate. That ratio
is workable only because the reason travels with the code.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "x4validate"
MARKER = "silent-ok:"


def _is_swallow(body: list[ast.stmt]) -> bool:
    """True if the handler body does nothing but discard the failure."""
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, (ast.Pass, ast.Continue)):
        return True
    if isinstance(stmt, ast.Return):
        if stmt.value is None:
            return True
        # `return None` / `return set()` / `return []` / `return {}` / `return ""`
        if isinstance(stmt.value, ast.Constant) and not stmt.value.value:
            return True
        if isinstance(stmt.value, (ast.List, ast.Dict)) and not getattr(stmt.value, "elts", []) \
                and not getattr(stmt.value, "keys", []):
            return True
        if isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name) \
                and stmt.value.func.id in {"set", "list", "dict", "tuple"} \
                and not stmt.value.args:
            return True
    return False


def _marked(source_lines: list[str], handler: ast.ExceptHandler) -> bool:
    """True if the handler carries a `# silent-ok:` marker on any of its lines."""
    start = handler.lineno - 1
    end = getattr(handler, "end_lineno", handler.lineno)
    return any(MARKER in line for line in source_lines[start:end])


def _offenders(package: Path = PACKAGE) -> list[str]:
    out = []
    for path in sorted(package.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if _is_swallow(node.body) and not _marked(lines, node):
                out.append(f"{path.name}:{node.lineno}")
    return out


def test_no_unmarked_silent_swallow():
    """A handler that discards a failure must say why, at the code that does it."""
    offenders = _offenders()
    assert not offenders, (
        "these except-handlers swallow a failure with no channel for the work not "
        "done, and no justification:\n  " + "\n  ".join(offenders) +
        "\n\nEither record the failure (Report.skipped / an `unreadable` list / a "
        "printed exclusion) or add an inline `# silent-ok: <reason>` marker."
    )


def test_the_guard_actually_detects_a_swallow(tmp_path):
    """Mutation test for the guard itself.

    A guard that cannot fail is worse than no guard: it reports green forever and
    everyone stops thinking about the thing it was meant to watch.
    """
    fake = tmp_path / "pkg"
    fake.mkdir()
    (fake / "_bad.py").write_text(
        "def f():\n    try:\n        g()\n    except ValueError:\n        continue\n",
        encoding="utf-8")
    assert _offenders(fake) == ["_bad.py:4"]


def test_the_marker_silences_it(tmp_path):
    fake = tmp_path / "pkg"
    fake.mkdir()
    (fake / "_ok.py").write_text(
        "def f():\n    try:\n        g()\n    except ValueError:\n"
        "        continue  # silent-ok: tested reason\n",
        encoding="utf-8")
    assert _offenders(fake) == []

"""Remove the `@pytest.mark.xfail(strict=True, reason="AUDIT-...")` decorator directly above
each named test -- the step a fix's commit must take once its test XPASSes.

    uv run python scripts/_unxfail.py <test file> <test name> [<test name> ...]

Refuses (rc 2) unless EVERY named test is found with an audit xfail directly above it, and
reports before/after decorator counts, so a partial edit cannot pass as a complete one.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

#: Both shapes the audit files use: the literal marker, and `tests/test_audit0924_merge.py`'s
#: `@_xf("<ID>", "...")` helper (which expands to the same strict xfail).
XF = re.compile(r'^(@pytest\.mark\.xfail\(strict=True, reason="AUDIT-2026-09-24 |@_xf\(")')


def unxfail(text: str, names: list[str]) -> tuple[str, list[str]]:
    lines = text.split("\n")
    missing = []
    for name in names:
        idx = next((i for i, l in enumerate(lines)
                    if re.match(rf"def {re.escape(name)}\(", l)), None)
        if idx is None:
            missing.append(f"{name}: no such test")
            continue
        # The decorator BLOCK above the def: every line up to the previous blank line,
        # def, or class. Decorators may span several lines (a multi-line parametrize).
        top = idx
        while top - 1 >= 0 and lines[top - 1].strip() \
                and not lines[top - 1].startswith(("def ", "class ")):
            top -= 1
        block = range(top, idx)
        starts = [i for i in block if lines[i].startswith("@")]
        xf = [i for i in starts if XF.match(lines[i])]
        if len(xf) != 1:
            missing.append(f"{name}: expected exactly one AUDIT-2026-09-24 xfail in its "
                           f"decorator block, found {len(xf)}")
            continue
        k = xf[0]
        nxt = min([i for i in starts if i > k] + [idx])   # next decorator, or the def
        del lines[k:nxt]
    return "\n".join(lines), missing


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path, names = Path(argv[0]), argv[1:]
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    before = sum(1 for l in text.split("\n") if XF.match(l))
    new, missing = unxfail(text, names)
    if missing:
        print("REFUSED, nothing written:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 2
    path.write_bytes(new.encode("utf-8"))
    after = sum(1 for l in path.read_text(encoding="utf-8").split("\n") if XF.match(l))
    print(f"{path.name}: audit xfail decorators {before} -> {after} (removed {before - after}, "
          f"asked {len(names)})")
    return 0 if before - after == len(names) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

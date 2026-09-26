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

XF = re.compile(r'^@pytest\.mark\.xfail\(strict=True, reason="AUDIT-2026-09-24 ')


def unxfail(text: str, names: list[str]) -> tuple[str, list[str]]:
    lines = text.split("\n")
    missing = []
    for name in names:
        idx = next((i for i, l in enumerate(lines)
                    if re.match(rf"def {re.escape(name)}\(", l)), None)
        if idx is None:
            missing.append(f"{name}: no such test")
            continue
        j = idx - 1
        while j >= 0 and lines[j].startswith("@pytest.mark.parametrize"):
            j -= 1
        # walk up over the xfail decorator's continuation lines to its first line
        k = j
        while k >= 0 and not XF.match(lines[k]) and not lines[k].startswith("def ") \
                and lines[k].strip() and not lines[k].startswith("@pytest.mark.parametrize"):
            k -= 1
        if k < 0 or not XF.match(lines[k]):
            missing.append(f"{name}: no AUDIT-2026-09-24 xfail directly above it")
            continue
        del lines[k:j + 1]
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

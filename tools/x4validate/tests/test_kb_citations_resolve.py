"""A dated KNOWLEDGEBASE citation in shipped code must resolve in the SHIPPED knowledge base.

AUDIT-2026-09-24 RT-10: `_livecli` sent readers to "KNOWLEDGEBASE.md 2026-09-20" for the dps
model, and `_savecli` to "KNOWLEDGEBASE 2026-08-26k" -- both entries exist only in a
maintainer's private knowledge base, not in the `KNOWLEDGEBASE.md` this repo ships. A
pointer a user cannot follow is a claim with no evidence behind it.

The check is by the citation's DATE (with its optional letter suffix stripped): the shipped
KB must contain that date somewhere. It is LOOSE, and that is measured, not assumed: it went
red on the `_livecli` line (no 2026-09-20 anywhere in the shipped KB) but would NOT have
caught the `_savecli` one, because an unrelated 2026-08-26 entry exists. Both lines were
fixed by stating the facts inline; this test guards the shape it can see.
"""
from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "x4validate"
KB = Path(__file__).resolve().parents[3] / "KNOWLEDGEBASE.md"
_CITE = re.compile(r"KNOWLEDGEBASE(?:\.md)?[\s(§]*(\d{4}-\d{2}-\d{2})[a-z]?")


def test_every_dated_kb_citation_in_the_package_resolves_in_the_shipped_kb():
    assert KB.is_file(), f"the shipped knowledge base is missing: {KB}"
    kb = KB.read_text(encoding="utf-8")
    sources = sorted(PKG.glob("*.py"))
    assert len(sources) > 20, f"scanned only {len(sources)} modules under {PKG}"
    dangling = []
    for src in sources:
        for n, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
            for m in _CITE.finditer(line):
                if m.group(1) not in kb:
                    dangling.append(f"{src.name}:{n}: {m.group(0)}")
    assert not dangling, ("dated KNOWLEDGEBASE citations with no entry of that date in the "
                          "shipped KNOWLEDGEBASE.md:\n  " + "\n  ".join(dangling))


def test_the_citation_pattern_matches_both_real_shapes():
    """The scanner's own twin: the two shapes RT-10 found must both be recognised."""
    assert _CITE.search("see KNOWLEDGEBASE.md 2026-09-20.").group(1) == "2026-09-20"
    assert _CITE.search("(KNOWLEDGEBASE 2026-08-26k, CLAUDE.md #33)").group(1) == "2026-08-26"

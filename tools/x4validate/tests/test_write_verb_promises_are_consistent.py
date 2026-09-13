"""A shipped "there is no write verb" must not outlive the write verbs that contradict it.

WHY THIS EXISTS. Until 2026-09-13 the live channel was read-only, and six shipped files
said so to strangers: the mod manifest, both READMEs, the shipped CLAUDE.md, the lua
source and the CLI. Nothing tested any of it. The first write verbs (`pause`/`unpause`)
made every one of those sentences false at once, and a stale safety promise is worse
than none -- it is the sentence a cautious user reads before deciding to load the mod.

It checks the SHIPPED SITES for the specific phrasings those promises used, and only
while the CLI actually carries write verbs. CHANGELOG.md is deliberately NOT scanned:
its entries were true when written and stay as history.
"""
from __future__ import annotations

import re
from pathlib import Path

from x4validate import _livecli

REPO = Path(__file__).resolve().parents[3]

#: Globbed, like the lua tests: the mod folder is located, never spelled out here.
SITE_GLOBS = (
    "mods/*/content.xml",
    "mods/*/ui/*live_query.lua",
    "README.md",
    "CLAUDE.md",
    "tools/x4validate/README.md",
    "tools/x4validate/x4validate/_livecli.py",
)

#: The phrasings the read-only promise was made in, as found on 2026-09-13.
STALE = (
    "no write verb",
    "zero state-changing",
    "read-only companion",
    "only write of any kind",
    "not gated, not present",
    "read-only vocabulary",
)


def _normalise(text: str) -> str:
    """Lowercase, drop markdown emphasis and blockquote markers, collapse whitespace --
    so a promise wrapped across lines or bolded mid-phrase is still one phrase."""
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = text.replace("*", "").replace("`", "")
    return re.sub(r"\s+", " ", text).lower()


def _stale_hits(text: str) -> list[str]:
    norm = _normalise(text)
    return [p for p in STALE if p in norm]


def _sites() -> list[Path]:
    found = []
    for pattern in SITE_GLOBS:
        hits = sorted(REPO.glob(pattern))
        assert hits, f"{pattern} matched nothing under {REPO}; the site list is stale"
        found.extend(hits)
    return found


def test_the_scanner_FINDS_the_promise_in_its_original_wording():
    """The falsification twin. Each sentence is a real 2026-09-13 original; a scanner
    that matched nothing would pass the real test below over any text at all."""
    assert _stale_hits("It is **read-only** -- a fixed, enumerated vocabulary\n"
                       "with no write verb, gated or otherwise") == ["no write verb"]
    assert _stale_hits("a fixed,\n**read-only** vocabulary asked of the running "
                       "engine") == ["read-only vocabulary"]
    assert _stale_hits("> write verb.** Nothing here ... makes **zero** state-changing "
                       "engine calls") == ["zero state-changing"]
    assert _stale_hits("There are no\nwrite verbs in it -- not gated, not present.") == [
        "no write verb", "not gated, not present"]
    assert _stale_hits("Read-only companion for the X4 community toolkit") == [
        "read-only companion"]
    assert _stale_hits("a pause verb that changes the running game") == []


def test_no_shipped_site_still_promises_there_is_NO_write_verb():
    assert _livecli.WRITE_VERBS, "the CLI carries no write verbs; this check has no premise"
    stale = {}
    for path in _sites():
        hits = _stale_hits(path.read_text(encoding="utf-8"))
        if hits:
            stale[str(path.relative_to(REPO))] = hits
    assert not stale, (
        "these shipped files still promise a read-only channel, but x4live now writes "
        f"({', '.join(_livecli.WRITE_VERBS)}):\n  "
        + "\n  ".join(f"{k}: {v}" for k, v in sorted(stale.items())))

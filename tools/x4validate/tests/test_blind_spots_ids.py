"""The blind-spot register must not hand the same F-id to two findings.

2026-08-21: two CONCURRENT sessions each wrote a `## F30` section — one for the SUBTREE
`winner` migration, one for the `<module group=>` gap — and neither could see the other.
It was caught by eye, from a `grep -c` that happened to return 2. Prose ("claim the id by
writing the table row first") does not survive two sessions that cannot see each other;
a test does.

Deliberately narrow. MEASURED 2026-08-21: **11** pre-existing inconsistencies of three
other kinds (below). Gating on those would fail on day one over things this test was not
written to police, and a check that fails for unrelated reasons trains you to ignore it.
Uniqueness is the invariant that broke, so uniqueness is what gates; the rest is PINNED so
new drift is visible without demanding a docs cleanup now.

RE-MEASURED 2026-08-22: **5** (F14 table-only, plus F9/F12/F13/F22 predating the
status/confidence heading convention). The six untabled findings were filed into the
summary table, so that category is now empty -- see `_KNOWN_UNTABLED`.
"""

import collections
import re
from pathlib import Path

import pytest

REGISTER = Path(__file__).resolve().parent.parent / "docs" / "BLIND-SPOTS.md"

#: A heading DECLARES a finding when it carries the status/confidence tail, e.g.
#: ``## F24 — ... · **DEFECT** · confidence 97%``. A heading that merely continues an
#: existing finding (``## F11 — re-scoped after measuring``) is not a second finding, and
#: treating it as one is a false positive — F11 legitimately has two headings today.
_DECLARATION = re.compile(r"^## (F\d+) .*?confidence", re.M)
_ANY_HEADING = re.compile(r"^## (F\d+)\b", re.M)
_TABLE_ROW = re.compile(r"^\| (F\d+) \|", re.M)


@pytest.fixture(scope="module")
def text() -> str:
    """The register, or an explicit SKIP.

    `docs/BLIND-SPOTS.md` is deliberately DEV-ONLY — it names a private modlist, so the
    public toolkit bundle ships `docs/QA-PROCESS.md` and not this. Without the guard the
    whole module ERRORS on a fresh public clone (MEASURED: 5 errors), which is the first
    thing a new user runs.

    A skip, not a silent pass: pytest reports it distinctly, so "not checked here" can
    never read as "checked and fine" — the distinction this register exists to enforce.
    """
    if not REGISTER.is_file():
        pytest.skip(f"no blind-spot register at {REGISTER} (dev-only doc) — not checked")
    return REGISTER.read_text(encoding="utf-8")


def test_the_register_parses_at_all(text):
    """Denominator guard. A regex that matches nothing would make every assertion below
    pass over an empty set — a green result proving nothing, which is the exact defect
    this whole register exists to record."""
    assert len(_DECLARATION.findall(text)) >= 20, (
        "parsed fewer than 20 finding declarations from BLIND-SPOTS.md — the heading "
        "format probably changed. Fix the parser; do NOT let it report green over nothing.")


def test_no_two_findings_claim_the_same_id(text):
    """THE GATE. Two declarations sharing an id means two different findings answer to
    one name, and every cross-reference to it becomes ambiguous."""
    counts = collections.Counter(_DECLARATION.findall(text))
    dupes = {fid: n for fid, n in counts.items() if n > 1}
    assert not dupes, (
        f"these F-ids are declared more than once: {dupes}. Two findings cannot share an "
        f"id — renumber the newer one to the next free id and update every reference "
        f"(the register, KNOWLEDGEBASE.md, CLAUDE.md, memory).")


def test_a_continuation_heading_is_not_counted_as_a_second_finding(text):
    """Pins the distinction the gate above depends on. If this stops holding, the gate is
    either false-positiving or has gone blind."""
    repeated = [f for f, n in collections.Counter(_ANY_HEADING.findall(text)).items() if n > 1]
    for fid in repeated:
        declared = collections.Counter(_DECLARATION.findall(text))[fid]
        assert declared <= 1, f"{fid} has {declared} declaration headings, not a continuation"


#: PINNED 2026-08-21, all pre-existing and none of them id collisions. Frozen so NEW drift
#: fails while the existing gaps stay visible instead of being silently normalised:
#:   - in the summary table with no section anywhere
#:   - a section whose heading predates the status/confidence convention
#:   - a declared finding that was never added to the summary table
#:
#: UPDATED 2026-08-22: `_KNOWN_UNTABLED` is now EMPTY. The summary table was repaired in
#: the same pass that re-verified every entry against the code -- it was missing those six
#: findings outright, and 15 further rows carried only 4 of the header's 5 cells, so their
#: Status column rendered BLANK. Six untabled findings and fifteen blank statuses is the
#: register's own narrowing shape turned on itself: the index that decides what is "filed"
#: had quietly stopped reporting some of it.
#:
#: This assertion is an EQUALITY, not a subset -- so closing a gap fails here just as
#: loudly as opening one. That is deliberate and it is why this edit exists: the pin is a
#: record of known drift, and a fix has to be written down rather than absorbed.
_KNOWN_TABLE_ONLY = {"F14"}
#: F22 gained a status/confidence heading on 2026-08-22, when it was re-scoped
#: from "scope gap costing 0" to a MEASURED defect, so it leaves this pin.
_KNOWN_OLD_FORMAT = {"F9", "F12", "F13"}
_KNOWN_UNTABLED: set[str] = set()


def test_register_bookkeeping_has_not_drifted(text):
    """Not a cleanup demand — a tripwire. Any NEW orphan or untabled finding shows up
    here; the 11 known ones are listed above with their reason."""
    declared = set(_DECLARATION.findall(text))
    headings = set(_ANY_HEADING.findall(text))
    rows = set(_TABLE_ROW.findall(text))

    assert rows - headings == _KNOWN_TABLE_ONLY, (
        f"summary-table rows with no section: {sorted(rows - headings)} "
        f"(known: {sorted(_KNOWN_TABLE_ONLY)})")
    assert headings - declared == _KNOWN_OLD_FORMAT, (
        f"sections not carrying the status/confidence tail: {sorted(headings - declared)} "
        f"(known: {sorted(_KNOWN_OLD_FORMAT)})")
    assert declared - rows == _KNOWN_UNTABLED, (
        f"findings missing a summary-table row: {sorted(declared - rows)} "
        f"(known: {sorted(_KNOWN_UNTABLED)}). The table is how the register is read — a "
        f"finding absent from it is effectively unfiled.")


# --- summary-table integrity -------------------------------------------------
#
# ADDED 2026-08-22, after the table was found holding rows with 4 of the header's 5
# cells. Markdown renders a short row by shifting cells LEFT and blanking the tail, so
# **15 rows displayed an empty Status column** while looking fine in source. Nothing
# noticed for weeks; the register's own defect shape, in the register's own index.
#
# It also removes the reason to hand-roll this check. The ad-hoc version was
# `awk -F'|'`, which splits on the character and cannot see a backslash -- so it called
# a correctly-escaped `\|` cell malformed. See KB 2026-08-22b: the instrument answered an
# adjacent question. A splitter that honours the escape lives here once, tested.

_ROW = re.compile(r"^\| (?:F\d+|—) \|", re.M)
_HEADER = "| # | Narrowing point |"


def split_cells(line: str) -> list[str]:
    r"""Cells of a markdown table row, honouring `\|` as a literal pipe.

    Markdown escapes a pipe inside a cell as `\|`; a naive split on `|` counts it as a
    delimiter and reports a valid row as malformed.
    """
    tmp = line.replace(r"\|", "\x00")
    parts = tmp.split("|")
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [p.replace("\x00", r"\|") for p in parts]


def test_the_escape_aware_splitter_is_not_fooled_by_an_escaped_pipe():
    """Proven-to-fail guard for the splitter itself. A naive `line.split('|')` returns 3
    here; this must return 2, or the assertion below inherits the bug it exists to stop."""
    assert split_cells(r"| a | b\|c |") == [" a ", r" b\|c "]
    assert len(r"| a | b\|c |".split("|")) - 2 == 3, "the naive form really does miscount"


def test_every_summary_row_has_the_header_s_column_count(text):
    """A short row does not fail to render — it renders WRONG, silently."""
    header = [ln for ln in text.splitlines() if ln.startswith(_HEADER)]
    assert len(header) == 1, f"expected exactly one summary-table header, found {len(header)}"
    want = len(split_cells(header[0]))
    assert want >= 4, f"header itself looks malformed ({want} cells)"

    rows = [ln for ln in text.splitlines() if _ROW.match(ln)]
    assert rows, "no summary-table rows matched — the regex has gone blind"

    bad = [(ln.split("|")[1].strip(), len(split_cells(ln))) for ln in rows
           if len(split_cells(ln)) != want]
    assert not bad, (
        f"summary rows whose column count differs from the header's {want}: {bad}. "
        f"Markdown shifts a short row's cells LEFT and blanks the tail, so the Status "
        f"column renders EMPTY while the source looks plausible.")

"""Three-way diff: separate the author's edits from upstream drift.

A two-way diff between an ARCHIVED mod and the CURRENT tree cannot answer the
question anyone actually has -- *which of these changes did the author make?* --
and it fails in a direction that invites damage.

MEASURED by a parallel session on a real 2021 mod, 135 documents:

    two-way (archived vs current)   ~440 attribute deltas
    three-way (vs the 4.04 base)      15 author edits
                                     340 upstream drift
    124 of 135 documents were VERBATIM copies of the baseline

So **96% of what a two-way diff calls "the port" is someone else's work.** Acting
on the two-way number would have re-applied 340 of the upstream author's changes
as if they were the user's, and reverted the current upstream release to 4.04
across 124 files.

⚠ The hard requirement, learned expensively (CLAUDE.md, "a ONE-SIDED ABSENCE in
an OLD document is upstream ADDITION, not author deletion"): 16 macros looked as
though the author had deleted `missile.targetable`; they had not -- upstream
added it after 2021. A two-way diff cannot tell those apart. A three-way CAN,
which is the entire point -- but only where a baseline exists for that document.
Where it does not, the answer is UNKNOWN and must say so, never "removed".
"""

from pathlib import Path

from x4validate import _threeway


def _mod(root: Path, name: str, wares: dict[str, dict[str, str]]) -> Path:
    """A minimal mod dir: libraries/wares.xml with the given id -> attrs."""
    d = root / name
    (d / "libraries").mkdir(parents=True)
    body = "".join(
        "<ware id=\"%s\" %s/>" % (wid, " ".join(f'{k}="{v}"' for k, v in attrs.items()))
        for wid, attrs in wares.items())
    (d / "libraries" / "wares.xml").write_text(
        f"<?xml version='1.0' encoding='utf-8'?><wares>{body}</wares>", encoding="utf-8")
    (d / "content.xml").write_text(
        f"<?xml version='1.0' encoding='utf-8'?><content id='{name}' version='100'/>",
        encoding="utf-8")
    return d


def test_an_author_edit_is_not_confused_with_upstream_drift(tmp_path):
    """The founding case: two changes, one each, must land in different buckets."""
    base = _mod(tmp_path, "base", {"ore": {"price": "100", "volume": "10"}})
    arch = _mod(tmp_path, "arch", {"ore": {"price": "555", "volume": "10"}})   # author moved price
    cur = _mod(tmp_path, "cur", {"ore": {"price": "100", "volume": "99"}})     # upstream moved volume

    r = _threeway.three_way(base, arch, cur)
    assert [c.attr for c in r.author_edits] == ["price"], r.author_edits
    assert [c.attr for c in r.upstream_drift] == ["volume"], r.upstream_drift
    assert r.both_moved == []


def test_a_both_moved_attribute_is_the_only_real_decision(tmp_path):
    """One conflict out of hundreds of deltas is a decision; the deltas are a wall."""
    base = _mod(tmp_path, "base", {"gun": {"damage": "5500"}})
    arch = _mod(tmp_path, "arch", {"gun": {"damage": "30500"}})   # author
    cur = _mod(tmp_path, "cur", {"gun": {"damage": "8500"}})      # upstream, since

    r = _threeway.three_way(base, arch, cur)
    assert len(r.both_moved) == 1
    c = r.both_moved[0]
    assert (c.base, c.archived, c.current) == ("5500", "30500", "8500")
    assert r.author_edits == [] and r.upstream_drift == []


def test_the_same_change_on_both_sides_is_CONVERGED_not_a_conflict(tmp_path):
    base = _mod(tmp_path, "base", {"ore": {"price": "100"}})
    arch = _mod(tmp_path, "arch", {"ore": {"price": "200"}})
    cur = _mod(tmp_path, "cur", {"ore": {"price": "200"}})
    r = _threeway.three_way(base, arch, cur)
    assert len(r.converged) == 1 and r.both_moved == []


def test_an_attribute_UPSTREAM_ADDED_is_never_reported_as_an_author_deletion(tmp_path):
    """The 16-macro case. The archived file predates the attribute; nobody deleted it."""
    base = _mod(tmp_path, "base", {"msl": {"speed": "100"}})
    arch = _mod(tmp_path, "arch", {"msl": {"speed": "100"}})              # untouched
    cur = _mod(tmp_path, "cur", {"msl": {"speed": "100", "targetable": "1"}})

    r = _threeway.three_way(base, arch, cur)
    assert r.author_edits == [], "the author changed nothing here"
    assert [c.attr for c in r.upstream_drift] == ["targetable"]
    assert all("remov" not in c.kind for c in r.upstream_drift), \
        "an upstream ADDITION must never be rendered as a removal"


def test_a_document_with_no_baseline_is_UNKNOWN_and_is_counted(tmp_path):
    """The narrowing step: no baseline means the direction cannot be known."""
    base = _mod(tmp_path, "base", {"ore": {"price": "100"}})
    arch = _mod(tmp_path, "arch", {"ore": {"price": "100"}})
    cur = _mod(tmp_path, "cur", {"ore": {"price": "100"}})
    # a document the baseline never had
    (arch / "libraries" / "extra.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><things><t id='a' v='1'/></things>",
        encoding="utf-8")

    r = _threeway.three_way(base, arch, cur)
    assert any("extra.xml" in v for v in r.no_base), r.no_base
    assert r.author_edits == [], "an unclassifiable document must not leak into a verdict"


def test_verbatim_documents_are_reported_with_a_denominator(tmp_path):
    """124 of 135 verbatim is the headline; a bare list of changes hides it."""
    base = _mod(tmp_path, "base", {"ore": {"price": "100"}})
    arch = _mod(tmp_path, "arch", {"ore": {"price": "100"}})
    cur = _mod(tmp_path, "cur", {"ore": {"price": "100"}})
    r = _threeway.three_way(base, arch, cur)
    assert r.documents_compared >= 1
    assert r.verbatim == r.documents_compared - len(r.author_edited_docs)


def test_every_attribute_lands_in_exactly_one_bucket(tmp_path):
    """Buckets must SUM to the population, or the classification is a non-answer."""
    base = _mod(tmp_path, "base", {"a": {"p": "1", "q": "1", "r": "1", "s": "1"}})
    arch = _mod(tmp_path, "arch", {"a": {"p": "2", "q": "1", "r": "3", "s": "9"}})
    cur = _mod(tmp_path, "cur", {"a": {"p": "1", "q": "2", "r": "4", "s": "9"}})
    r = _threeway.three_way(base, arch, cur)
    total = (len(r.author_edits) + len(r.upstream_drift)
             + len(r.both_moved) + len(r.converged))
    assert total == r.attributes_classified, (
        f"buckets {total} != population {r.attributes_classified}")
    assert total == 4, "p author, q upstream, r both, s converged"


def test_a_document_the_ARCHIVE_never_had_produces_no_drift_rows(tmp_path):
    """The case that kills the mutant my first no-base test could not.

    A document the baseline and the CURRENT tree both have, but the archived mod
    does not, is outside the comparison entirely. Upstream changes to it are not
    "drift the author is behind on" -- the author never had the file. Without the
    exclusion those rows leak into `upstream_drift` and inflate the very number
    this tool exists to deflate.

    ⚠ Written after `excluded = set()` SURVIVED the first pass: the original
    no-base fixture asserted the right outcome for the wrong reason, because a
    document absent from the baseline cannot contribute attribute changes at all.
    Right answer, wrong mechanism -- the shape that makes a green meaningless.
    """
    base = _mod(tmp_path, "base", {"ore": {"price": "100"}})
    arch = _mod(tmp_path, "arch", {"ore": {"price": "100"}})
    cur = _mod(tmp_path, "cur", {"ore": {"price": "100"}})
    for d in (base, cur):
        (d / "libraries" / "only_upstream.xml").write_text(
            "<?xml version='1.0' encoding='utf-8'?><things><t id='a' v='%s'/></things>"
            % ("1" if d is base else "2"), encoding="utf-8")

    r = _threeway.three_way(base, arch, cur)
    assert any("only_upstream" in v for v in r.dropped_by_author), r.dropped_by_author
    assert not any("only_upstream" in c.vpath for c in r.upstream_drift), (
        "a document the archive never had must not generate drift rows")
    assert r.attributes_classified == 0

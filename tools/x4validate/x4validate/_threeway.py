"""Three-way diff: which changes are the AUTHOR's, and which are upstream drift?

A two-way diff between an archived mod and the current tree answers the wrong
question, and it answers it confidently. MEASURED by a parallel session over a
real 2021 mod, 135 documents: **~440 attribute deltas two-way, 15 author edits
three-way**, 340 upstream drift, and **124 of 135 documents byte-verbatim copies
of the baseline**. Acting on the two-way figure would have re-applied 340 of the
upstream author's changes as if they were the user's, and reverted the current
upstream release across 124 files.

The mechanism is a join, not a new differ. Two ordinary two-way diffs share a
common ancestor, so their attribute changes can be keyed on
``(vpath, node-path, attr)`` and compared::

    D1 = diff(base -> archived)   what the AUTHOR did
    D2 = diff(base -> current)    what UPSTREAM did since

    in D1 only ................. author-edit
    in D2 only ................. upstream-drift
    in both, same new value .... converged
    in both, different values .. BOTH-MOVED   <- the only real decision

Reusing `_diff` rather than re-implementing it is deliberate: a second
implementation of the same normalisation is what made an independent measurement
of F64 report 2.6% where the truth was 65.4%.

⚠ **A one-sided absence is UNKNOWN, never a removal.** This is the rule the
workspace paid for: 16 macros appeared to have lost ``missile.targetable`` when
upstream had simply added it after 2021. A three-way diff *can* tell those apart
-- that is its whole purpose -- but only where the baseline actually contains the
document. Where it does not, the document goes to :attr:`ThreeWay.no_base` and is
excluded from every verdict, counted rather than quietly dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from x4validate import _diff


@dataclass(frozen=True)
class Change:
    """One attribute that moved on exactly one side."""
    vpath: str
    node: str
    attr: str
    base: str
    value: str
    kind: str                      # "author-edit" | "upstream-drift" | "converged"


@dataclass(frozen=True)
class Conflict:
    """One attribute both sides moved, to different values. The decision."""
    vpath: str
    node: str
    attr: str
    base: str
    archived: str
    current: str
    kind: str = "both-moved"


@dataclass
class ThreeWay:
    base: str
    archived: str
    current: str
    author_edits: list[Change] = field(default_factory=list)
    upstream_drift: list[Change] = field(default_factory=list)
    converged: list[Change] = field(default_factory=list)
    both_moved: list[Conflict] = field(default_factory=list)

    #: documents present in the archived mod but NOT in the baseline. Direction
    #: is unknowable for these, so they are excluded from every bucket above --
    #: and reported, because a silent exclusion is the narrowing step.
    no_base: list[str] = field(default_factory=list)
    #: documents in the baseline that the archived mod does not have.
    dropped_by_author: list[str] = field(default_factory=list)
    #: could not be parsed on some side; NOT the same as unchanged.
    unreadable: list[str] = field(default_factory=list)
    #: node-level adds/removes are surfaced, not classified -- stated, not hidden.
    node_level: list[str] = field(default_factory=list)

    documents_compared: int = 0
    author_edited_docs: list[str] = field(default_factory=list)

    @property
    def verbatim(self) -> int:
        """Documents the author did not touch at all. Usually the headline."""
        return self.documents_compared - len(self.author_edited_docs)

    @property
    def attributes_classified(self) -> int:
        return (len(self.author_edits) + len(self.upstream_drift)
                + len(self.converged) + len(self.both_moved))


def _attr_index(md: _diff.ModDiff) -> dict[tuple[str, str, str], tuple[str, str]]:
    """(vpath, node, attr) -> (base value, new value) for every changed attribute."""
    out: dict[tuple[str, str, str], tuple[str, str]] = {}
    for fd in md.files:
        if fd.status != "changed":
            continue
        for node, attr, old, new in fd.attr_changes:
            out[(fd.vpath, node, attr)] = (old, new)
    return out


def _status_set(md: _diff.ModDiff, status: str) -> set[str]:
    return {f.vpath for f in md.files if f.status == status}


def three_way(base: Path | list[Path], archived: Path, current: Path) -> ThreeWay:
    """Classify *archived* vs *current* changes using *base* as the common ancestor.

    *base* may be a list, so a baseline can be a stack (pristine core + pristine
    submod), matching `_diff.diff_mods`.
    """
    d_author = _diff.diff_mods(base, archived)
    d_upstream = _diff.diff_mods(base, current)

    r = ThreeWay(base=d_author.old, archived=str(archived), current=str(current))
    r.unreadable = list(dict.fromkeys(d_author.unreadable + d_upstream.unreadable))

    # Documents with no counterpart in the baseline: direction is UNKNOWABLE.
    # They are named and excluded -- never rendered as an author addition or an
    # upstream removal, which is the failure this whole tool exists to prevent.
    r.no_base = sorted(_status_set(d_author, "added"))
    r.dropped_by_author = sorted(_status_set(d_author, "removed"))
    excluded = set(r.no_base) | set(r.dropped_by_author)

    a = {k: v for k, v in _attr_index(d_author).items() if k[0] not in excluded}
    u = {k: v for k, v in _attr_index(d_upstream).items() if k[0] not in excluded}

    for key in sorted(a.keys() | u.keys()):
        vpath, node, attr = key
        in_a, in_u = key in a, key in u
        basev = (a.get(key) or u.get(key))[0]
        if in_a and not in_u:
            r.author_edits.append(Change(vpath, node, attr, basev, a[key][1], "author-edit"))
        elif in_u and not in_a:
            r.upstream_drift.append(Change(vpath, node, attr, basev, u[key][1], "upstream-drift"))
        elif a[key][1] == u[key][1]:
            r.converged.append(Change(vpath, node, attr, basev, a[key][1], "converged"))
        else:
            r.both_moved.append(Conflict(vpath, node, attr, basev, a[key][1], u[key][1]))

    for fd in d_author.files:
        if fd.status == "changed" and (fd.nodes_added or fd.nodes_removed):
            r.node_level.append(
                f"{fd.vpath}: +{len(fd.nodes_added)} / -{len(fd.nodes_removed)} node(s) "
                f"(author side; node-level changes are reported, not classified)")

    compared = {f.vpath for f in d_author.files} - excluded
    # `diff_mods` only records files that actually differ, so unchanged documents
    # are absent from `files` -- count the shared population from the vpath maps.
    shared = set(_diff.mod_xml_vpaths(archived).keys()) & set(
        _diff.merged_vpaths([base] if isinstance(base, Path) else list(base)).keys())
    r.documents_compared = len(shared)
    r.author_edited_docs = sorted(compared)
    return r

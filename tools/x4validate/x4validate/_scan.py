r"""One packed-aware, skip-recording walk over a mod's XML.

Why this module exists
----------------------
Six modules each hand-rolled the same loop — rglob the loose tree, parse, then
walk the `.cat` members — and every copy ended the same way::

    except etree.XMLSyntaxError:
        continue

That `continue` is the bug this package has now fixed at three layers
(`Report.skipped`, `coverage.json`, `_input.require_mod_dir`) and it kept
reappearing because the loop kept being rewritten. Patching the six copies
individually guarantees a seventh. So there is one copy, and it takes a channel
for what it could not read.

Measured before the fix: `_check.iter_mod_xml_roots` dropped **12 files across 3
installed mods, 9 of them `<diff>` files** — precisely what `check_sel_resolution`
exists to examine. Neither existing guard caught it: `MergeResult.skipped` is a
different code path (overlay-tree parses), and the `checked == 0` warning only
fires at *zero*, so five good diffs plus one malformed printed nothing at all.

Ordering contract
-----------------
Loose files win over packed catalog members, matching the engine and
`_merge.overlay_root`. A loose file that will not parse still shadows its packed
twin — it is recorded as unreadable rather than silently falling through to the
packed copy, because the engine would not fall through either.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from lxml import etree

from . import _cat, _merge


@dataclass
class Unreadable:
    """A file the scanner found but could not parse. Never discard these."""
    vpath: str
    why: str
    packed: bool = False

    def __str__(self) -> str:
        return f"{self.vpath} ({'packed' if self.packed else 'loose'}): {self.why}"


#: A predicate takes the mod-relative virtual path (forward slashes, original
#: case) and returns whether to parse the file at all. Filtering here rather
#: than after parsing is what keeps the big scans (x4xref over 100 mods) cheap.
Predicate = Callable[[str], bool]


class under:
    """Match files beneath any of *prefixes* (case-insensitive, e.g. "md/").

    Carries `.prefixes` so `iter_mod_xml` can narrow its `rglob` to just those
    subtrees instead of walking everything and filtering after. That matters:
    x4xref scans the reference root, where a full walk is ~13k files to reach
    the ~2k under md/ and aiscripts/.
    """

    def __init__(self, *prefixes: str):
        self.prefixes = tuple(p.lower() for p in prefixes)

    def __call__(self, vpath: str) -> bool:
        return vpath.lower().startswith(self.prefixes)


def ending(*suffixes: str) -> Predicate:
    lowered = tuple(s.lower() for s in suffixes)
    return lambda vpath: vpath.lower().endswith(lowered)


class all_of:
    """Conjunction that keeps the `.prefixes` narrowing of any `under` inside it."""

    def __init__(self, *predicates: Predicate):
        self.predicates = predicates
        for p in predicates:
            if getattr(p, "prefixes", None):
                self.prefixes = p.prefixes
                break

    def __call__(self, vpath: str) -> bool:
        return all(p(vpath) for p in self.predicates)


def _scan_roots(mod_dir: Path, predicate: Predicate | None) -> list[Path]:
    """Directories to rglob. Narrowed by a predicate's `.prefixes` when it has any."""
    prefixes = getattr(predicate, "prefixes", None)
    if not prefixes:
        return [mod_dir]
    # Narrow to each prefix's leading directory segment. A head that is not a
    # real directory simply contributes nothing — there can be no loose file
    # under it. Deduped so overlapping prefixes ("assets", "assets/units") do
    # not yield the same file twice.
    heads = dict.fromkeys(p.strip("/").split("/")[0] for p in prefixes)
    return [mod_dir / h for h in heads if (mod_dir / h).is_dir()]


def iter_mod_xml(
    mod_dir: Path,
    predicate: Predicate | None = None,
    unreadable: list[Unreadable] | None = None,
) -> Iterator[tuple[str, etree._Element]]:
    """Yield ``(vpath, root)`` for every XML a mod owns, loose then packed.

    A file that will not parse is APPENDED TO *unreadable*, never dropped
    silently. Pass ``unreadable=None`` only where the caller genuinely has no way
    to report — and if you find yourself doing that, that is the bug.
    """
    yielded: set[str] = set()

    loose = sorted(p for root in _scan_roots(mod_dir, predicate)
                   for p in root.rglob("*.xml"))
    for path in loose:
        if not path.is_file():
            continue
        vpath = path.relative_to(mod_dir).as_posix()
        if predicate is not None and not predicate(vpath):
            continue
        # Claim the vpath BEFORE parsing: a malformed loose file shadows its
        # packed twin in the engine too, so silently using the packed copy would
        # model the wrong file.
        yielded.add(vpath.lower())
        try:
            root = _merge.parse_file(path)
        except (etree.XMLSyntaxError, OSError) as exc:
            if unreadable is not None:
                unreadable.append(Unreadable(vpath, str(exc)))
            continue
        yield vpath, root

    for vpath, member in sorted(_cat.mod_vfs(mod_dir).items()):
        if not vpath.lower().endswith(".xml") or vpath.lower() in yielded:
            continue
        if predicate is not None and not predicate(vpath):
            continue
        try:
            root = _merge.parse_bytes(_cat.read_member(member))
        except (etree.XMLSyntaxError, OSError, ValueError) as exc:
            if unreadable is not None:
                unreadable.append(Unreadable(vpath, str(exc), packed=True))
            continue
        yield vpath, root


def count_line(shown: int, total: int, noun: str, flag: str = "--limit") -> str:
    """Render a count that discloses its own bound.

    A bounded result printed as a bare count makes the *number* wrong, not just
    the list: `x4effective` defaulted to `--limit 200` and printed "200 ware(s)"
    against a store of 2,431. Any `[:n]` slice must go through this.
    """
    if total > shown:
        return (f"{shown} of {total} {noun} shown — TRUNCATED by {flag}; "
                f"use {flag} {total} (or 0) for all")
    return f"{shown} {noun}"

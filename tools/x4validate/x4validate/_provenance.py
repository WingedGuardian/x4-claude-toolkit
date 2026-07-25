"""Per-attribute provenance capture for the effective-tree merge.

A :class:`Recorder` rides along with `_merge` (opt-in via the ``recorder=``
kwarg) and records, for every element/attribute the merge mutates, the chain
of :class:`Origin`\\ s that produced the surviving value — oldest first, last
entry wins. Values never touched by any overlay carry no per-node record and
inherit the recorder's ``default_origin`` (normally ``base``), so memory stays
proportional to the number of *modified* nodes, not tree size.

Identity design: chains are keyed by the *live lxml element proxies* (held
strongly in the dicts, which pins proxy identity for the tree's lifetime) —
never by xpath strings, which shift as the tree mutates. Consumers must query
chains while the merged tree and recorder are both alive; element keys are
never persisted. Paths appear only in :attr:`Recorder.removed`, captured at
removal time for display purposes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

BASE = "base"


@dataclass(frozen=True)
class Origin:
    """One provenance event: *source* overlay applied *op* (at *line* of the patching file)."""
    source: str          # "base" | "ego_dlc_split" | mod folder name
    op: str              # base | add | replace | replace-attr | replace-text
                         # | union-add | union-replace | full-override | remove
    line: int = 0        # sourceline of the op in the PATCHING file (0 = n/a)

    def short(self) -> str:
        loc = f":{self.line}" if self.line else ""
        return f"{self.source} {self.op}{loc}"


@dataclass
class Recorder:
    """Collects provenance during one build_effective() run for one vpath."""
    default_origin: Origin = field(default_factory=lambda: Origin(BASE, BASE))
    file_chain: list[Origin] = field(default_factory=list)   # file-level events, in order
    removed: list[tuple[str, Origin]] = field(default_factory=list)  # (path-at-removal, origin)
    # Element proxies are held strongly => identity-stable for the tree's lifetime.
    _elem: dict = field(default_factory=dict)   # etree._Element -> list[Origin]
    _attr: dict = field(default_factory=dict)   # (etree._Element, attr) -> list[Origin]

    # --- capture (called from _merge at mutation time) --------------------------

    def elem_created(self, el: etree._Element, origin: Origin,
                     prior_chain: list[Origin] | None = None) -> None:
        self._elem[el] = list(prior_chain or []) + [origin]

    def elem_replaced(self, old: etree._Element, new: etree._Element, origin: Origin) -> None:
        """*new* took *old*'s place: new's chain continues old's."""
        prior = self._elem.pop(old, None) or self._implicit(old)
        self._elem[new] = prior + [origin]
        # attr-level history inside the clobbered subtree is intentionally dropped
        # (documented: chains restart at a union-replace / element-replace).
        stale = [k for k in self._attr if k[0] is old]
        for k in stale:
            del self._attr[k]

    def attr_set(self, el: etree._Element, attr: str, origin: Origin) -> None:
        key = (el, attr)
        self._attr[key] = self._attr.get(key, self._implicit_attr(el, attr)) + [origin]

    def node_removed(self, path_at_removal: str, origin: Origin) -> None:
        self.removed.append((path_at_removal, origin))

    def full_override(self, origin: Origin) -> None:
        """Whole file replaced: all prior lineage is gone; new default for every node."""
        self._elem.clear()
        self._attr.clear()
        self.default_origin = origin
        self.file_chain.append(origin)

    # --- lookup (called by extractors post-merge, tree still live) ---------------

    def elem_chain(self, el: etree._Element) -> list[Origin]:
        """Chain for *el*: own record, else nearest recorded ancestor, else default."""
        node = el
        while node is not None:
            chain = self._elem.get(node)
            if chain is not None:
                return chain
            node = node.getparent()
        return [self.default_origin]

    def attr_chain(self, el: etree._Element, attr: str) -> list[Origin]:
        chain = self._attr.get((el, attr))
        if chain is not None:
            return chain
        return self.elem_chain(el)

    def winner(self, el: etree._Element, attr: str | None = None) -> Origin:
        chain = self.attr_chain(el, attr) if attr else self.elem_chain(el)
        return chain[-1]

    def is_base(self, el: etree._Element, attr: str | None = None) -> bool:
        """True when the value was never touched by any overlay (pure default lineage)."""
        chain = self.attr_chain(el, attr) if attr else self.elem_chain(el)
        return len(chain) == 1 and chain[0] == self.default_origin

    # --- internals ---------------------------------------------------------------

    def _implicit(self, el: etree._Element) -> list[Origin]:
        # An unrecorded element inherits from its nearest recorded ancestor
        # (e.g. base ware later replaced: prior chain is [base]).
        parent = el.getparent()
        if parent is not None:
            return list(self.elem_chain(parent))
        return [self.default_origin]

    def _implicit_attr(self, el: etree._Element, attr: str) -> list[Origin]:
        return list(self.elem_chain(el))

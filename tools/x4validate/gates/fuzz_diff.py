#!/usr/bin/env python
"""Fuzz the diff grammar — probe shapes no real author happened to write.

The corpus audits prove we handle every op that EXISTS in a real modlist. That
is not the same as handling every op that is LEGAL. The root-`<replace>` defect
lived for months precisely there: `sel="//macros"` is ordinary XML-diff, just
absent from whatever the tests happened to cover.

So: generate random-but-valid ops against a synthetic tree and assert the
invariants that must hold for ANY op, rather than expected values for specific
ones. Seeded, so a failure is reproducible.

Invariants:
  I1  never raises
  I2  a structural op reported applied MUST have changed the tree
  I3  an op reported NOT applied must leave the tree byte-identical
  I4  every not-applied op carries a reason
  I5  applying the same op to the same tree twice gives the same result

Run:  uv run python gates/fuzz_diff.py [--n=2000] [--seed=N]
Exit: 0 all invariants hold, 1 otherwise.
"""
from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from x4validate import _merge  # noqa: E402

N = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--n=")), 2000)
SEED = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--seed=")), 1234)

TAGS = ["wares", "ware", "price", "production", "group", "macros", "macro", "properties"]
ATTRS = ["id", "name", "transport", "volume", "price", "average", "class", "tags"]
VALUES = ["1", "0", "-5", "999999", "", "a b", "liquid", "{20101,1}", "é中", "x" * 200]


def random_tree(rng: random.Random) -> etree._Element:
    root = etree.Element(rng.choice(["wares", "macros"]))
    for i in range(rng.randint(1, 6)):
        child = etree.SubElement(root, rng.choice(TAGS[1:]))
        child.set("id", f"e{i}")
        for _ in range(rng.randint(0, 3)):
            child.set(rng.choice(ATTRS), rng.choice(VALUES))
        if rng.random() < 0.4:
            gc = etree.SubElement(child, rng.choice(TAGS[2:]))
            gc.set(rng.choice(ATTRS), rng.choice(VALUES))
    return root


def random_sel(rng: random.Random, root: etree._Element) -> str:
    ids = [e.get("id") for e in root.iter() if e.get("id")]
    tag = root.tag
    choices = [
        f"//{tag}", f"/{tag}", f"//{rng.choice(TAGS)}",
        f"//{rng.choice(TAGS)}[@id='{rng.choice(ids) if ids else 'nope'}']",
        f"//{rng.choice(TAGS)}/@{rng.choice(ATTRS)}",
        f"//{rng.choice(TAGS)}[@id='{rng.choice(ids) if ids else 'x'}']/@{rng.choice(ATTRS)}",
        f"//{tag}/*[1]", f"//{tag}/{rng.choice(TAGS[1:])}[last()]",
        "//nonexistent", f"//{tag}//{rng.choice(TAGS[1:])}",
    ]
    return rng.choice(choices)


def random_op(rng: random.Random, root: etree._Element) -> etree._Element:
    kind = rng.choice(["add", "replace", "remove"])
    op = etree.Element(kind)
    op.set("sel", random_sel(rng, root))
    if kind == "add" and rng.random() < 0.3:
        op.set("type", f"@{rng.choice(ATTRS)}")
        op.text = rng.choice(VALUES)
    elif kind in ("add", "replace"):
        if rng.random() < 0.75:
            for _ in range(rng.randint(1, 2)):
                c = etree.SubElement(op, rng.choice(TAGS[1:]))
                c.set("id", f"new{rng.randint(0, 99)}")
        else:
            op.text = rng.choice(VALUES)
        if kind == "add" and rng.random() < 0.4:
            op.set("pos", rng.choice(["prepend", "before", "after"]))
    return op


def wrap(op):
    d = etree.Element("diff")
    d.append(copy.deepcopy(op))
    return d


def main() -> int:
    rng = random.Random(SEED)
    fails = []
    structural_applied = 0
    for i in range(N):
        root = random_tree(rng)
        op = random_op(rng, root)
        t1, t2 = copy.deepcopy(root), copy.deepcopy(root)
        before = etree.tostring(t1)
        try:
            r1 = _merge.apply_diff(t1, wrap(op))
        except Exception as exc:                                    # I1
            fails.append((i, op, f"I1 raised {type(exc).__name__}: {exc}"))
            continue
        try:
            r2 = _merge.apply_diff(t2, wrap(op))
        except Exception as exc:
            fails.append((i, op, f"I5 raised on second run: {exc!r}"))
            continue
        if etree.tostring(t1) != etree.tostring(t2):                # I5
            fails.append((i, op, "I5 same op on same tree gave different results"))
            continue
        if not r1:
            continue
        rec = r1[0]
        changed = etree.tostring(t1) != before
        kids = [c for c in op if isinstance(c.tag, str)]
        structural = op.tag == "remove" or bool(kids)
        if rec.ok and structural and not changed and not getattr(rec, "skipped_if", False):
            fails.append((i, op, "I2 reported applied but the tree is unchanged"))
        if not rec.ok:
            if changed:
                fails.append((i, op, "I3 reported NOT applied but the tree changed"))
            if not rec.detail:
                fails.append((i, op, "I4 not-applied with no reason given"))
        if rec.ok and structural and changed:
            structural_applied += 1

    print(f"FUZZ — {N} random ops, seed {SEED}")
    print("=" * 78)
    print(f"  structural ops that applied and changed the tree : {structural_applied}")
    print(f"  invariant violations                             : {len(fails)}")
    for i, op, why in fails[:15]:
        print(f"\n  #{i}  {why}")
        print(f"      {etree.tostring(op).decode()[:150]}")
    if len(fails) > 15:
        print(f"  ... and {len(fails) - 15} more")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

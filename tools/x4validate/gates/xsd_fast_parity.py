#!/usr/bin/env python
r"""The fast required-attribute path must equal the compiled schema. Exactly.

`_xsd.required_attr_table` is a SECOND implementation of a check libxml2 already
performs. A second implementation is only worth having if it is proven
equivalent — otherwise it is a faster way to be wrong, and the class it covers
("attribute X is required but missing") is the one the KB calls the only
reliable 9.0 migration signal.

So: for every installed mod's md/aiscript files, the set of `required but
missing` findings from the fast table must EQUAL the set libxml2 produces.

  fast \ full  -> a FALSE POSITIVE. The worst outcome: a gating ERROR on a
                  working mod. Must be zero.
  full \ fast  -> a MISS. Something the schema knows and the extractor does not
                  — most likely an unresolved `xs:extension base=` or `type=`
                  hop. Must be zero.

This is deliberately slow (it compiles md.xsd AND aiscripts.xsd, ~220s once) —
that is the price of proving the fast path, and it is paid here rather than by
the user on every run.

Run:  uv run python gates/xsd_fast_parity.py [--limit N]
Exit: 0 exact parity, 1 any difference.
"""
from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402
from x4validate import _cat, _merge, _scan, _xsd  # noqa: E402

LIMIT = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), 0)
EXT = _env.extensions()
REQ = "is required but missing"


def script_docs(mod: Path):
    """(display, parsed root) for a mod's md/ + aiscripts/ files, loose AND packed."""
    prefixes = tuple(f"{s}/" for s in _xsd.SCRIPT_DIRS)
    for vpath, root in _scan.iter_mod_xml(
            mod, lambda v: v.lower().startswith(prefixes) and v.lower().count("/") == 1, None):
        yield vpath, root


def main() -> int:
    cfg = _merge.Config()
    lib = cfg.reference / "libraries"
    mods = [d for d in sorted(EXT.iterdir()) if d.is_dir()]
    if LIMIT:
        mods = mods[:LIMIT]

    print("=" * 88)
    print(f"XSD FAST-PATH PARITY — fast table vs compiled schema, {len(mods)} mods")
    print("=" * 88)
    # Report the table PER SCHEMA. Passing the lib DIRECTORY here printed
    # "0 elements with required attrs" next to "exact parity" — a header that
    # reads as though the whole comparison were vacuous. A gate must never
    # describe itself in a way that makes a real result look like nothing.
    for name in ("md.xsd", "aiscripts.xsd"):
        sp = lib / name
        if sp.is_file():
            print(f"  table[{name}]: {len(_xsd.required_attr_table(str(sp)))} elements with "
                  f"required attrs; {_xsd.ambiguous_element_names(str(sp))} ambiguous "
                  f"(intersection applied)")

    files = 0
    false_pos, missed = [], []
    for mod in mods:
        for display, root in script_docs(mod):
            files += 1
            fast = {(f.line, f.message) for f in
                    _xsd.required_attr_findings(root, display, lib)}
            fnds, _reason = _xsd._validate_doc(etree.ElementTree(root), display, lib)
            full = {(f.line, f.message) for f in fnds if REQ in f.message}
            for row in sorted(fast - full):
                false_pos.append((mod.name, display, row))
            for row in sorted(full - fast):
                missed.append((mod.name, display, row))

    print(f"\n  script files compared : {files}")
    print(f"  FALSE POSITIVES (fast says required-missing, schema does not): {len(false_pos)}")
    for m, d, (line, msg) in false_pos[:10]:
        print(f"     {m}  {d}:{line}  {msg[:90]}")
    print(f"  MISSES (schema found it, fast did not): {len(missed)}")
    for m, d, (line, msg) in missed[:10]:
        print(f"     {m}  {d}:{line}  {msg[:90]}")

    print("\n" + "=" * 88)
    if false_pos or missed:
        print(f"PARITY BROKEN: {len(false_pos)} false positive(s), {len(missed)} miss(es)")
        return 1
    print("Exact parity — the fast table reproduces libxml2 on this class, corpus-wide.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

r"""Stage PACKED X4 XML into a temp tree so BaseX can index it.

Why this exists
---------------
Most mod XML ships inside `.cat`/`.dat` archives — 62% when this was first
measured, and 2,822 documents from 45 sources on the install of 2026-08-24.
BaseX only indexes files on disk, so until staging existed every query ran
against a corpus missing most of the interesting content — which means **no
negative claim was supportable**. "Nothing references X" was a statement about
the fraction that happened to be loose.

Stage-and-index, not permanent unpacking: extracted bytes go to a temp tree that
is discarded after the build. Permanent copies would go stale on every mod update
(~5-week cadence), duplicate disk on top of an already-27 GB reference\, and add a
manual step that gets forgotten. The index is the durable artifact, so staging is
correctly transient.

⚠ This paragraph used to read "the 908 MB BaseX index". That number was never
the corpus index: MEASURED 2026-08-24, 908 MB is `basex/data/x4md`, a database
created 2026-07-26 — the day BEFORE packed staging existed — which no current
script builds and nothing reads. The live artifacts measured 942 MB (`x4raw`)
and 949 MB (`x4eff`). A size quoted from a superseded artifact, carried forward
as though it described the current one, is exactly the rot a derived number
develops when it does not say WHEN it was true.

The manifest is the point
-------------------------
A bigger index is not proof. **Proof needs a denominator.** This writes
`manifest.json` recording, per source, how many XML documents exist, how many
were staged, and every single one that was NOT — with the reason. Reconciling
that against what BaseX actually indexed is what lets a zero-result be reported
as "0 hits over N of N documents" rather than "0 hits, probably".

Usage:  cd tools/x4validate && uv run python ../basex/stage.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

from lxml import etree

from x4validate import _cat, _paths, _registry

# Mini-DLC ship only as .cat archives and are NOT unpacked into reference\, so
# they are invisible to the reference tree exactly like a packed mod. _cat reads
# them fine (55 + 104 XML members), so they need no XRCatTool step at all — they
# stage into /base/extensions to mirror where the other DLC live.
def packed_dlc_names() -> tuple[str, ...]:
    """DLC that ship only as .cat archives, asked of Config rather than hardcoded.

    This was a literal `("ego_dlc_mini_01", "ego_dlc_mini_02")` until 2026-08-13 —
    a SIXTH hand-rolled DLC list. The other five (`_input`, `_migration`,
    `_effective`, `_xref`/`_similarity`, `gates/similar_audit`) were each blind to
    the packed mini-DLC, and two of them carried comments explaining the bug while
    the next copy was written anyway. The tuple happened to be correct, which is
    exactly why it survived: a hardcoded list is wrong only on the day a DLC is
    added, and on that day nothing here would say so.

    Falls back to the historical pair if Config cannot be reached, so staging
    never silently covers LESS than it used to.

    `Unconfigured` is in that list deliberately (added 2026-08-24). This runs at
    IMPORT time, so before the fix an unconfigured machine got a raw traceback and
    **rc 1** — which in this toolkit means "the thing you asked about has
    findings", the precise confusion F39 existed to remove — and it fired before
    `main` could refuse cleanly, so no decorator on `main` could ever catch it.
    Falling back is safe HERE and only here: this resolves a list of DLC NAMES,
    not a location, so the fallback cannot silently point at the wrong disk. The
    genuine refusal belongs to `main`, which names `$X4_EXTENSIONS` and exits 2.
    """
    try:
        from x4validate import _merge
        names = tuple(_merge.Config().packed_dlc_names())
    except (ImportError, OSError, AttributeError, _paths.Unconfigured):
        names = ()
    return names or ("ego_dlc_mini_01", "ego_dlc_mini_02")


MINI_DLC = packed_dlc_names()


@dataclass
class SourceCoverage:
    """What we found in one source, and what we could not take."""
    name: str
    root: str            # BaseX path root this lands under ("/mods", "/base/extensions")
    packed_total: int = 0
    staged: int = 0
    loose_shadowed: int = 0          # packed member overridden by a loose file (correct)
    failures: list[str] = field(default_factory=list)
    #: Staged but malformed — BaseX will silently drop these, so record them HERE
    #: while we still hold the bytes. Staging is deleted after the build, and a
    #: deficit we can no longer explain is indistinguishable from a broken build.
    unparseable: list[str] = field(default_factory=list)


def _safe_target(base: Path, vpath: str) -> Path | None:
    """Resolve vpath under base, refusing anything that escapes it."""
    target = (base / vpath).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target


def stage_source(src_dir: Path, out_root: Path, name: str, root_label: str) -> SourceCoverage:
    cov = SourceCoverage(name=name, root=root_label)
    try:
        vfs = _cat.mod_vfs(src_dir, xml_only=True)
    except Exception as exc:                      # noqa: BLE001 - report, never abort
        cov.failures.append(f"<catalog>: could not read archives ({type(exc).__name__}: {exc})")
        return cov

    # _cat's xml_only ALSO admits .xsd (schemas), but BaseX is built with
    # CREATEFILTER *.xml and the loose side is added under the same filter — so
    # a staged .xsd is written, never indexed, and shows up as an unexplained
    # deficit. Found exactly that way: 18 phantom missing documents (17 mini-DLC
    # schemas + chillturrets/md/md.xsd). Match the filter here so the denominator
    # means what it says.
    vfs = {v: m for v, m in vfs.items() if v.lower().endswith(".xml")}
    cov.packed_total = len(vfs)
    if not vfs:
        return cov

    dest_base = out_root / name
    for vpath, member in sorted(vfs.items()):
        # Loose files win over catalog members, matching the engine and
        # _merge.overlay_root. The loose copy is already indexed from its real
        # location, so staging the packed one would double-count it.
        if (src_dir / vpath).is_file():
            cov.loose_shadowed += 1
            continue
        target = _safe_target(dest_base, vpath)
        if target is None:
            cov.failures.append(f"{vpath}: path escapes the staging root, refused")
            continue
        try:
            data = _cat.read_member(member)
        except Exception as exc:                  # noqa: BLE001
            cov.failures.append(f"{vpath}: extract failed ({type(exc).__name__}: {exc})")
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            cov.failures.append(f"{vpath}: write failed ({exc})")
            continue
        try:
            etree.fromstring(data)
        except etree.XMLSyntaxError as exc:
            cov.unparseable.append(f"{vpath}: {str(exc).splitlines()[0][:120]}")
        cov.staged += 1
    return cov


@_paths.refuses_unconfigured
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=str(Path.cwd() / "_stage"),
                   help="staging directory (wiped and recreated)")
    # No default. It used to be a literal `C:\Program Files (x86)\Steam\...`, which
    # on any other machine staged ZERO documents and still exited 0 — the exact
    # shape v2.5.0 removed from the other scripts, and the one the AST guard could
    # not see because it only ever looked for `os.environ` (F44).
    p.add_argument("--extensions", default=None,
                   help="the game's extensions/ dir (default: resolved through _paths)")
    # The manifest must OUTLIVE the staging dir it describes: staging is deleted
    # after the build, and a coverage report you can only run during the build is
    # a coverage report nobody runs.
    p.add_argument("--manifest", default=str(Path(__file__).resolve().parent / "stage-manifest.json"))
    args = p.parse_args(argv)

    out = Path(args.out)
    resolved_ext = args.extensions or _paths.game_extensions()
    if resolved_ext is None:
        print("error: cannot resolve the game's extensions directory. Set "
              "$X4_EXTENSIONS, configure .claude/x4-paths.env, or pass "
              "--extensions.\n"
              "       Refusing to guess: staging a path that does not exist "
              "indexes ZERO documents and still exits 0.", file=sys.stderr)
        return 2
    ext_dir = Path(resolved_ext)
    if out.exists():
        shutil.rmtree(out)
    mods_out = out / "mods"
    base_out = out / "base_extensions"
    mods_out.mkdir(parents=True)
    base_out.mkdir(parents=True)

    coverage: list[SourceCoverage] = []

    for name in MINI_DLC:
        d = ext_dir / name
        if d.is_dir():
            coverage.append(stage_source(d, base_out, name, "/base/extensions"))

    try:
        # INSTALLED, and correctly so: x4raw is "every file AS WRITTEN, per
        # mod". Whether the engine loads it is x4eff's question, not this one.
        mods = _registry.mods("installed")
    except OSError as exc:
        print(f"error: could not scan installed mods: {exc}", file=sys.stderr)
        return 2
    for m in mods:
        d = Path(m["path"])
        if not d.is_dir() or m["folder"] in MINI_DLC:
            continue
        cov = stage_source(d, mods_out, m["folder"], "/mods")
        if cov.packed_total or cov.failures:
            coverage.append(cov)

    staged = sum(c.staged for c in coverage)
    shadowed = sum(c.loose_shadowed for c in coverage)
    failures = [f"{c.name}/{f}" for c in coverage for f in c.failures]
    unparseable = [f"{c.name}/{u}" for c in coverage for u in c.unparseable]

    manifest = {
        "staging_dir": str(out),
        "sources": [asdict(c) for c in coverage],
        "totals": {
            "sources_with_packed_xml": len(coverage),
            "documents_staged": staged,
            "documents_staged_mods": sum(c.staged for c in coverage if c.root == "/mods"),
            "documents_staged_base": sum(c.staged for c in coverage if c.root != "/mods"),
            "loose_shadowed": shadowed,
            "extraction_failures": len(failures),
            "unparseable_staged": len(unparseable),
        },
        "failures": failures,
        "unparseable": unparseable,
    }
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"staged {staged} packed XML documents from {len(coverage)} source(s)")
    print(f"  {shadowed} packed members shadowed by a loose file (correctly not staged)")
    if unparseable:
        print(f"  {len(unparseable)} staged document(s) are MALFORMED — BaseX drops these "
              "SILENTLY,\n     so they are recorded in the manifest to explain the deficit:")
        for u in unparseable:
            print(f"     {u}")
    if failures:
        # Never let extraction failures be silent — that is the exact gap that
        # made a partial index look complete.
        print(f"  !! {len(failures)} EXTRACTION FAILURE(S) — the index will be incomplete:")
        for f in failures[:20]:
            print(f"     {f}")
        if len(failures) > 20:
            print(f"     ... and {len(failures) - 20} more (see manifest.json)")
    print(f"manifest: {manifest_path}")
    print(f"  mods       -> ADD TO /mods            {mods_out}")
    print(f"  mini-DLC   -> ADD TO /base/extensions {base_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

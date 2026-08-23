r"""When was this derived artifact last TRUE?

Coverage answers *how much* was indexed. Nothing answered *as of when*, so an
artifact that no longer describes the world reported success indefinitely — a
third case beside absence and non-answer: **an answer about a world that has
moved on.**

**The case that produced this module.** BaseX's `x4eff` was built 2026-08-02. The
merge engine was then fixed twice — root-`<replace>` ops were being dropped while
reported applied (2026-08-08, 858 ops, VRO alone 848) and nested cross-mod
patches were invisible from one of two doors (2026-08-11). **Neither date changed
one input file**, so any check watching only inputs would have called the index
fresh. MEASURED after rebuilding: **140 of 194 (72%)** engine thrust rows moved,
and a design decision recorded on 08-02 had quoted VANILLA engine values as if
they were VRO's.

Hence two axes:

``content``  the installed world — every extension's identity + manifest
             mtime/size, plus a reference-tree marker.
``engine``   the CODE that produced the artifact, hashed from source BYTES. A git
             commit does not move for a dirty tree, and merge changes here are
             routinely used before they are committed.

Only artifacts *derived through the merge* are engine-dependent. A raw file index
is not, and flagging it anyway would train the reader to ignore the warning —
which is how a noisy check ends up worse than no check.

One implementation, imported by everyone: `_effective` (the sqlite store),
`_xref` (its TSV index) and `tools/basex/staleness.py` all use this. The
DLC-enumeration bug was written five times precisely because each caller rolled
its own copy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

#: Modules that decide what the EFFECTIVE tree contains. Editing any of them
#: changes the answer for identical inputs.
#:
#: `_effective.py` was ADDED 2026-08-22 after a near-miss. The first five decide
#: what a document MERGES TO; `_effective.py` decides which documents and which
#: entities exist at all (`base_vpaths`, `reference_vpaths`, `macro_vpaths`,
#: `component_vpaths`, `build_touch_map`). An enumeration change moves the store
#: for byte-identical inputs just as surely as a merge change does.
#:
#: The near-miss, stated plainly because it is the only reason this line is
#: right: F34's fix edited `reference_vpaths` itself, and the store's
#: `fingerprint_engine` did not move -- `gates/claims_audit.py` returned 21/21
#: green against a store built by the OLD enumeration. It was correct only
#: because set-equality had been proven by hand (4,002 and 7,551 vpaths, 0
#: added / 0 removed / 0 changed). Nothing in the toolkit would have caught the
#: other outcome, which is exactly the eleven-day `x4eff` failure that produced
#: this contract in the first place.
#: `_registry.py` was ADDED 2026-08-22 alongside `_effective.py`, for the same
#: reason one step further out: it decides WHICH MODS EXIST. `_registry.mods()`
#: is now the single definition of "active" (what the engine loads) vs
#: "installed" (what is on disk), and moving a mod between those two worlds
#: changes the effective tree for byte-identical inputs just as surely as a merge
#: change does. MEASURED the day it was written: one installed-but-disabled mod
#: moved x4eff by 10 documents and x4compat by 4 collision rows.
ENGINE_SOURCES = ("_merge.py", "_diff.py", "_cat.py", "_xpath.py", "_scan.py",
                  "_effective.py", "_registry.py")

_PKG = Path(__file__).resolve().parent


def hash_engine(engine_dir: Path | None = None) -> str:
    """Hash the merge-relevant sources, in fixed order.

    A missing file is hashed as ``<ABSENT>`` rather than skipped: silently
    hashing fewer inputs than intended is how a fingerprint stops noticing.
    """
    engine_dir = engine_dir or _PKG
    h = hashlib.sha256()
    for name in ENGINE_SOURCES:
        p = engine_dir / name
        h.update(name.encode())
        h.update(p.read_bytes() if p.is_file() else b"<ABSENT>")
    return h.hexdigest()[:16]


def hash_content(reference: Path, extensions: Path) -> str:
    """Hash the installed world.

    Keyed on each extension's ``content.xml`` (identity + mtime + size) rather
    than a full tree walk: walking 60 GB on every query would make the check too
    expensive to run, and a manifest changes whenever a mod is added, removed or
    updated. A mod present WITHOUT a manifest is recorded as such, so it stays in
    the denominator instead of vanishing from it.
    """
    h = hashlib.sha256()
    if extensions and Path(extensions).is_dir():
        for d in sorted(Path(extensions).iterdir(), key=lambda p: p.name.lower()):
            if not d.is_dir():
                continue
            h.update(d.name.lower().encode())
            manifest = d / "content.xml"
            if manifest.is_file():
                st = manifest.stat()
                h.update(f"{int(st.st_mtime)}:{st.st_size}".encode())
            else:
                h.update(b"<NO-MANIFEST>")
    else:
        h.update(b"<NO-EXTENSIONS-DIR>")
    marker = Path(reference) / "libraries" / "wares.xml"
    if marker.is_file():
        st = marker.stat()
        h.update(f"ref:{int(st.st_mtime)}:{st.st_size}".encode())
    else:
        h.update(b"ref:<ABSENT>")
    return h.hexdigest()[:16]


def fingerprint(config, extensions: Path | None = None,
                engine_dir: Path | None = None) -> dict:
    """Both axes for *config*'s world. *extensions* defaults to its overlay root."""
    ext = extensions
    if ext is None:
        overlays = list(getattr(config, "overlays", ()) or ())
        ext = overlays[0].parent if overlays else Path("")
    return {"content": hash_content(config.reference, ext),
            "engine": hash_engine(engine_dir)}


@dataclass
class Verdict:
    fresh: bool
    reasons: list[str] = field(default_factory=list)

    def banner(self, what: str) -> str:
        """Text a CLI prints on EVERY run until the artifact is rebuilt."""
        if self.fresh:
            return ""
        return ("\n" + "!" * 78
                + f"\n!! STALE — {what} no longer describes the current world.\n!!   "
                + "\n!!   ".join(self.reasons)
                + "\n!! Its answers describe the world as of the build, not now, and it\n"
                  "!! cannot back a NEGATIVE claim until rebuilt.\n"
                + "!" * 78 + "\n")


def compare(stored: dict | None, current: dict, engine_dependent: bool) -> Verdict:
    """Absent is UNKNOWN, never fresh — see the module docstring."""
    if not stored:
        return Verdict(False, ["no fingerprint recorded — built before freshness "
                               "tracking existed, so it cannot be established"])
    reasons = []
    if stored.get("content") != current.get("content"):
        reasons.append("content changed: a mod was added, removed or updated "
                       "(or the reference tree moved)")
    if engine_dependent and stored.get("engine") != current.get("engine"):
        reasons.append("engine changed: the merge code that produced this has been "
                       "edited, so the SAME inputs would now merge differently")
    return Verdict(not reasons, reasons)


# --- persistence -------------------------------------------------------------

_KEYS = ("fingerprint_content", "fingerprint_engine")


def stamp_sqlite(con, fp: dict) -> None:
    """Write into the existing `meta` table — additive, no sidecar to lose."""
    con.execute("create table if not exists meta (key text primary key, value text)")
    for key, val in zip(_KEYS, (fp["content"], fp["engine"])):
        con.execute("insert or replace into meta (key, value) values (?, ?)", (key, val))


def read_sqlite(con) -> dict | None:
    try:
        rows = dict(con.execute("select key, value from meta"))
    except Exception:
        return None  # silent-ok: a store with no meta table predates this and is
        # reported as UNKNOWN by `compare`, which is the correct verdict.
    if not all(k in rows for k in _KEYS):
        return None
    return {"content": rows["fingerprint_content"], "engine": rows["fingerprint_engine"]}


def _sidecar(target: Path) -> Path:
    return Path(str(target) + ".freshness.json")


def stamp_sidecar(target: Path, fp: dict) -> None:
    """For artifacts that are not databases (the x4xref TSV). Payload untouched."""
    _sidecar(target).write_text(json.dumps(fp, indent=2), encoding="utf-8")


def read_sidecar(target: Path) -> dict | None:
    p = _sidecar(target)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # silent-ok: an unreadable sidecar is exactly the UNKNOWN case, and `compare`
        # renders None as "no fingerprint — freshness cannot be established", which
        # is the conservative verdict. Nothing is swallowed; the caller still warns.
        return None
    return data if all(k in data for k in ("content", "engine")) else None

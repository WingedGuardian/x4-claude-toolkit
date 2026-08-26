r"""When was this derived artifact last TRUE — and if it is not, WHAT moved?

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

``content``  the installed world — every extension's identity, its manifest, and
             the mtime/size of every engine-relevant file it ships, plus a
             reference-tree marker.
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

--------------------------------------------------------------------------------
WHAT THE CONTENT AXIS COVERS, AND WHY IT WAS WIDENED (2026-08-25)
--------------------------------------------------------------------------------

It used to stat ONLY each folder's ``content.xml``. That made it blind to a mod
whose FILES changed while its manifest did not — which is the ordinary
overlay-deploy workflow: edit ``libraries/god.xml``, copy it in, manifest
untouched.

    MEASURED 2026-08-25: **72 of 121 non-DLC mods (59.5%)** had at least one file
    newer than their own ``content.xml``. Demonstrated directly against the old
    code: a file-only edit returned the IDENTICAL digest ``03122df005f47fbd``
    before and after.

Every artifact therefore reported **FRESH** while describing a different tree.
That is a false FRESH — it fails in the UNSAFE direction, unlike F53's false
STALE, which merely nags.

**Cost of closing it, MEASURED** (`os.walk`, three stable runs; an earlier figure
of 1.73 s was ~92% process-spawn overhead from a bash loop and is logged as
checker-bug #48):

===========================================  =======  =========
variant                                        files       time
===========================================  =======  =========
whole ``extensions\`` tree                    15,523     0.14 s
filtered to .xml/.cat/.dat/.lua                2,042     0.060 s
filtered + per-file triples + tree_sha         2,042     0.092 s
sha256 of all 129 ``content.xml``                129     0.008 s
===========================================  =======  =========

**The suffix filter is CORRECTNESS, not speed.** MEASURED: 8 mods would otherwise
move the fingerprint purely from ``README``/``CHANGES``/``LICENSE``/
``live_editor_log.json`` churn — manufactured staleness, which trains the reader
to ignore the banner, which is how a noisy check ends up worse than none.

**SCOPE LIMIT, stated because a tool that cannot distinguish a guess from a
measurement is a defect.** Per-file identity is ``(relpath, mtime, size)``, NOT a
content hash: hashing every file would mean reading VRO's multi-hundred-MB
``ext_01.cat`` on every CLI run. Consequences, both real:

* an edit that changes NEITHER size NOR mtime is invisible;
* an edit that keeps the size but moves the mtime is classified ``touched``
  rather than ``content``.

Manifests ARE hashed (``manifest_sha``, 8 ms for all 129) because they are small
and because separating *touched* from *actually changed* is exactly what defeated
us in the ``distances`` incident.

--------------------------------------------------------------------------------
WHY THE VECTOR IS PERSISTED (F56)
--------------------------------------------------------------------------------

A digest says THAT the world moved, never WHAT. MEASURED 2026-08-25: localising
one changed mod (``distances``, v160 -> v170) took **nine investigative steps and
three false leads**, and succeeded only because that mod happened to bump its
``version``. A content-identical rewrite with a new mtime would have been
undiagnosable.

So ``content_detail`` computes the per-folder vector and ``hash_content`` folds
it. The vector is persisted beside the digest (149 KB for 121 mods / 2,042
files), which is what lets ``x4modlist changed --files`` name exact files with no
dependency on a possibly-stale BaseX index or on ``_cat``.

``distances`` also rewrote its 26 files **back-dated** two days. A ``max(mtime)``
signal is precisely what back-dating defeats — ``find -newermt`` failed on this
for that reason — so the per-file triples are hashed as a SET, and an mtime
moving BACKWARD registers just as a forward one does.
"""

from __future__ import annotations

import hashlib
import json
import os
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
#:
#: NOTE `_freshness.py` is deliberately NOT in this list. It does not decide what
#: the tree contains, so widening the CONTENT axis here does not pretend the
#: merge code changed -- that distinction is the whole of F53's complaint.
ENGINE_SOURCES = ("_merge.py", "_diff.py", "_cat.py", "_xpath.py", "_scan.py",
                  "_effective.py", "_registry.py")

#: Files the ENGINE can load. Everything else -- READMEs, changelogs, licences,
#: tool logs -- is excluded, because 8 real mods would otherwise mark every
#: artifact stale for documentation churn. See the module docstring.
ENGINE_FILE_SUFFIXES = frozenset({".xml", ".cat", ".dat", ".lua"})

_PKG = Path(__file__).resolve().parent

#: Distinguishes "read the configured profile" from "there is no profile".
#: Passing `profile=None` explicitly means the latter, and every mod then counts
#: as enabled -- which is also what an unreadable profile must mean (see
#: `_profile_decisions`).
_UNSET = object()


class NoBaseline(Exception):
    """Asked to diff against a baseline that carries no vector.

    Not an error in the world -- an error in the QUESTION. Artifacts built before
    the vector existed cannot answer "what changed", and reporting "nothing
    changed" for them would be a wrong answer where a non-answer is the honest
    one. Same contract as `tools/basex/ask.py` refusing a zero-result without a
    coverage denominator.
    """


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


# --- the content vector -------------------------------------------------------

def _as_dirs(dirs) -> list[Path]:
    """Accept one root or many.

    `hash_content` walked a SINGLE directory, so the profile and Workshop roots
    were invisible to it -- the same narrowing shape the blind-spot register
    exists to police. A bare Path is still accepted because four production call
    sites and fifteen tests pass one.
    """
    if dirs is None:
        return []
    if isinstance(dirs, (str, os.PathLike)):
        return [Path(dirs)]
    return [Path(d) for d in dirs]


def _profile_decisions(profile) -> dict[str, bool]:
    """manifest id -> enabled, from the profile content.xml.

    Keyed by MANIFEST ID, never folder name (gotcha #30b: `amphitrite` is the
    folder, `ws_3616342050` the id; MEASURED 60 of 123 match by id, only 9 by
    folder). An unreadable or absent profile yields {} and therefore "everything
    enabled" -- failing OPEN, because failing closed would empty the world model
    on any machine without a profile and report that emptiness as fact.
    """
    if profile is _UNSET:
        from x4validate import _registry
        profile = _registry.PROFILE_CONTENT
    if profile is None:
        return {}
    try:
        from lxml import etree
        root = etree.parse(str(profile)).getroot()
    except Exception:
        # silent-ok: an absent/unreadable profile must FAIL OPEN -- {} means
        # "no decisions recorded", and every mod then counts as enabled, which
        # is what X4 itself does with a folder it has not seen (gotcha #30a).
        # Failing CLOSED would mark all 121 mods disabled and silently shrink
        # the fingerprint's world model to nothing on any machine without a
        # profile. The freshness verdict is unaffected either way: the profile
        # contributes one bit per mod, and a machine with no profile simply has
        # a constant for it.
        return {}
    out: dict[str, bool] = {}
    for ext in root.xpath("//extension[@id]"):
        out[ext.get("id")] = str(ext.get("enabled", "false")).lower() == "true"
    return out


def _read_manifest(manifest: Path) -> dict:
    """id/version/sha/mtime/size for one content.xml, tolerant of malformed XML.

    A mod with a broken manifest must stay in the denominator rather than crash
    the fingerprint or vanish from it -- `id`/`version` simply read as None.
    """
    try:
        body = manifest.read_bytes()
        st = manifest.stat()
    except OSError:
        return {"manifest_id": None, "manifest_version": None,
                "manifest_sha": None, "manifest_mtime": None,
                "manifest_size": None, "no_manifest": True}
    mid = ver = None
    try:
        from lxml import etree
        root = etree.fromstring(
            body, parser=etree.XMLParser(recover=True, resolve_entities=False))
        if root is not None:
            mid, ver = root.get("id"), root.get("version")
    except Exception:
        # silent-ok: id/version are CONVENIENCES for localisation, not inputs to
        # the digest. A malformed manifest still contributes its bytes via
        # `manifest_sha` and its files via `tree_sha`, so the mod stays in the
        # denominator and any change to it is still detected -- it just cannot
        # be labelled "version 1.6 -> 1.7". MEASURED 2026-08-23: 12 of 4,383
        # mod documents are malformed, so this is a real case, not a defensive
        # hypothetical. Raising here would let one broken manifest take the
        # whole fingerprint down.
        pass
    return {"manifest_id": mid, "manifest_version": ver,
            "manifest_sha": hashlib.sha256(body).hexdigest()[:12],
            "manifest_mtime": int(st.st_mtime), "manifest_size": st.st_size,
            "no_manifest": False}


def _walk_mod(folder: Path) -> tuple[list[list], int]:
    """Sorted (relpath, mtime, size) for every engine-relevant file, + unreadable.

    A file we could not stat is COUNTED rather than dropped, so the record can
    say it narrowed instead of quietly shrinking -- the one shape every tool
    defect in this workspace has had.
    """
    entries: list[list] = []
    unreadable = 0
    for dirpath, _dirnames, filenames in os.walk(folder):
        for name in filenames:
            if os.path.splitext(name)[1].lower() not in ENGINE_FILE_SUFFIXES:
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                unreadable += 1
                continue
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            entries.append([rel, int(st.st_mtime), st.st_size])
    entries.sort()
    return entries, unreadable


def content_detail(reference: Path, dirs, profile=_UNSET) -> list[dict]:
    """The per-folder vector the digest is folded from. See the module docstring.

    Sorted by (folder, root) so the fold is deterministic. Note the sort key is a
    PAIR: the same folder name can legally exist in two install roots, and every
    consumer must keep them apart (see `diff_detail`).

    *reference* is accepted but not read here -- the reference marker belongs to
    the FOLD, not to the per-mod vector. It stays in the signature so this and
    `hash_content` take the same arguments, which is what lets a caller swap one
    for the other without re-deriving anything.
    """
    decisions = _profile_decisions(profile)
    out: list[dict] = []
    for root in _as_dirs(dirs):
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not d.is_dir():
                continue
            rec: dict = {"folder": d.name, "root": str(root)}
            rec.update(_read_manifest(d / "content.xml"))
            entries, unreadable = _walk_mod(d)
            payload = "\n".join(f"{p}|{m}|{s}" for p, m, s in entries)
            rec["files"] = len(entries)
            rec["unreadable"] = unreadable
            rec["tree_sha"] = hashlib.sha256(payload.encode()).hexdigest()[:12]
            rec["enabled_in_profile"] = decisions.get(rec["manifest_id"], True)
            rec["entries"] = entries
            out.append(rec)
    out.sort(key=lambda r: (r["folder"].lower(), r["root"]))
    return out


def _fold(detail: list[dict], reference: Path) -> str:
    """The ONE place a vector becomes a digest.

    Written once on purpose. Two independent code paths answering the same
    question is the single most repeated defect shape in this toolkit -- the
    nested-patch door gave Tier B and `x4effective` contradictory answers, each
    internally consistent. `hash_content` and `fingerprint` both fold through
    here so they cannot drift apart.
    """
    h = hashlib.sha256()
    if not detail:
        h.update(b"<NO-EXTENSIONS-DIR>")
    for rec in detail:
        h.update(rec["folder"].lower().encode())
        if rec["no_manifest"]:
            h.update(b"<NO-MANIFEST>")
        else:
            h.update(f"{rec['manifest_mtime']}:{rec['manifest_size']}"
                     f":{rec['manifest_sha']}".encode())
        h.update(f":{rec['tree_sha']}:{int(rec['enabled_in_profile'])}".encode())
    marker = Path(reference) / "libraries" / "wares.xml"
    if marker.is_file():
        st = marker.stat()
        h.update(f"ref:{int(st.st_mtime)}:{st.st_size}".encode())
    else:
        h.update(b"ref:<ABSENT>")
    return h.hexdigest()[:16]


def hash_content(reference: Path, dirs, profile=_UNSET) -> str:
    """Fold :func:`content_detail` into one digest.

    Keyed on identity + manifest + every engine-relevant file's (mtime, size),
    rather than a full byte hash: reading 60 GB on every query would make the
    check too expensive to run, and a check nobody runs protects nothing.
    """
    return _fold(content_detail(reference, dirs, profile=profile), reference)


def _entry_map(rec: dict) -> dict[str, tuple[int, int]]:
    return {p: (m, s) for p, m, s in rec.get("entries", ())}


def diff_detail(before, after) -> list[dict]:
    """Localise a moved fingerprint: which mod, and how.

    Kinds, in precedence order — ``added``, ``removed``, ``toggled`` (profile
    enable-list), ``version`` (manifest version moved), ``content`` (a file's
    SIZE moved, or the manifest bytes did), ``touched`` (mtime moved, bytes did
    not). The content/touched split is why `manifest_sha` is stored beside the
    mtime; without it the `distances` incident could not have been called either
    way.

    Raises :class:`NoBaseline` when *before* is None, rather than returning [] —
    an artifact predating the vector cannot answer this, and "nothing changed"
    would be a wrong answer where a non-answer is the honest one.
    """
    if before is None:
        raise NoBaseline(
            "the baseline carries no content vector (built before the vector "
            "existed), so WHAT changed cannot be derived from it -- rebuild the "
            "artifact, or take a snapshot, to establish one")
    # Keyed by (root, folder), NEVER by folder alone. The same folder name can
    # exist in two install roots (game-root vs profile vs Workshop), and a
    # folder-keyed dict silently collapses them last-write-wins. That is exactly
    # checker-bug #47: a change-detector keyed by FOLDER met a mod shipping two
    # manifests and invented a phantom identity change -- the most alarming shape
    # it could have produced. Same family, so it does not get to happen twice.
    def _key(r):
        return (r.get("root", ""), r["folder"])

    old = {_key(r): r for r in before}
    new = {_key(r): r for r in after}
    changes: list[dict] = []

    for key in sorted(set(old) | set(new), key=lambda k: (k[1].lower(), k[0])):
        folder = key[1]
        a, b = old.get(key), new.get(key)
        # `root` travels with every change: with the same folder name legal in
        # two install roots, naming only the folder would make the answer
        # ambiguous exactly when it matters most.
        root = (b or a).get("root", "")
        if b is None:
            changes.append({"folder": folder, "root": root, "kind": "removed",
                            "detail": f"{a['files']} file(s) gone"})
            continue
        if a is None:
            changes.append({"folder": folder, "root": root, "kind": "added",
                            "detail": f"{b['files']} file(s), "
                                      f"version {b.get('manifest_version')}"})
            continue

        am, bm = _entry_map(a), _entry_map(b)
        changed = sorted({p for p in set(am) | set(bm)
                          if am.get(p, (None, None))[1] != bm.get(p, (None, None))[1]})
        touched = sorted({p for p in set(am) & set(bm)
                          if p not in changed and am[p][0] != bm[p][0]})

        if a["enabled_in_profile"] != b["enabled_in_profile"]:
            kind = "toggled"
            detail = ("enabled in the profile" if b["enabled_in_profile"]
                      else "DISABLED in the profile")
        elif a.get("manifest_version") != b.get("manifest_version"):
            kind = "version"
            detail = f"{a.get('manifest_version')} -> {b.get('manifest_version')}"
        elif changed or a["manifest_sha"] != b["manifest_sha"]:
            kind = "content"
            detail = f"{len(changed)} file(s) changed"
        elif touched or a["manifest_mtime"] != b["manifest_mtime"]:
            kind = "touched"
            detail = (f"{len(touched)} file(s) rewritten with identical size "
                      "(mtime only)")
        else:
            continue

        changes.append({"folder": folder, "root": root, "kind": kind,
                        "detail": detail, "files_changed": changed,
                        "files_touched": touched})
    return changes


def fingerprint(config, extensions=None, engine_dir: Path | None = None,
                profile=_UNSET) -> dict:
    """Both axes for *config*'s world, plus the vector the content axis folds.

    *extensions* defaults to its overlay root. It used to fall back to
    ``Path("")`` -- which is ``Path(".")``, so a bare call hashed whatever
    directory you happened to be standing in and reported it as the installed
    world. That is F46's mechanism, and it produced a wrong number in an audit
    the same day it was registered elsewhere. It now REFUSES: a tool that cannot
    tell a guess from a measurement is a defect, not a limitation.
    """
    ext = extensions
    if ext is None:
        overlays = list(getattr(config, "overlays", ()) or ())
        if not overlays:
            raise ValueError(
                "fingerprint() cannot infer the extensions root: `config` has no "
                "overlays and no `extensions` was passed. Pass one explicitly "
                "(e.g. _registry.GAME_EXTENSIONS or "
                "_registry.default_installed_dirs()). Refusing to fall back to "
                "the current directory -- that is F46, and it silently hashes "
                "whatever you are standing in.")
        ext = overlays[0].parent
    detail = content_detail(config.reference, ext, profile=profile)
    return {"content": _fold(detail, config.reference),
            "engine": hash_engine(engine_dir), "detail": detail}


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
    # Both reasons quote STORED -> NOW. A consumer's first question on hitting a
    # stale artifact is "moved how far, and by whose change?", and without the two
    # hashes answering it takes a hand-written script against `fingerprint()`.
    # They are also what lets someone match the move against a commit. Raised by a
    # downstream session that hit this for real (F59).
    if stored.get("content") != current.get("content"):
        reasons.append("content changed: a mod was added, removed, updated, "
                       "toggled, or one of its files was edited "
                       "(run `x4modlist changed` to see which) "
                       f"[{stored.get('content')} -> {current.get('content')}]")
    if engine_dependent and stored.get("engine") != current.get("engine"):
        reasons.append("engine changed: the merge code that produced this has been "
                       "edited, so the SAME inputs would now merge differently "
                       f"[{stored.get('engine')} -> {current.get('engine')}]")
    return Verdict(not reasons, reasons)


# --- persistence -------------------------------------------------------------

_KEYS = ("fingerprint_content", "fingerprint_engine")
#: Stored separately and read OPTIONALLY. An artifact written before the vector
#: existed must stay readable and keep giving a correct FRESH/STALE verdict --
#: requiring this key would flip every artifact on disk to UNKNOWN at once, which
#: is a far worse failure than not being able to localise.
_DETAIL_KEY = "fingerprint_detail"


def stamp_sqlite(con, fp: dict) -> None:
    """Write into the existing `meta` table — additive, no sidecar to lose."""
    con.execute("create table if not exists meta (key text primary key, value text)")
    for key, val in zip(_KEYS, (fp["content"], fp["engine"])):
        con.execute("insert or replace into meta (key, value) values (?, ?)", (key, val))
    if fp.get("detail") is not None:
        con.execute("insert or replace into meta (key, value) values (?, ?)",
                    (_DETAIL_KEY, json.dumps(fp["detail"], separators=(",", ":"))))


def read_sqlite(con) -> dict | None:
    try:
        rows = dict(con.execute("select key, value from meta"))
    except Exception:
        return None  # silent-ok: a store with no meta table predates this and is
        # reported as UNKNOWN by `compare`, which is the correct verdict.
    if not all(k in rows for k in _KEYS):
        return None
    out = {"content": rows["fingerprint_content"],
           "engine": rows["fingerprint_engine"], "detail": None}
    if _DETAIL_KEY in rows:
        try:
            out["detail"] = json.loads(rows[_DETAIL_KEY])
        except (TypeError, ValueError):
            out["detail"] = None  # unreadable vector -> NoBaseline, not a wrong answer
    return out


def _sidecar(target: Path) -> Path:
    return Path(str(target) + ".freshness.json")


def stamp_sidecar(target: Path, fp: dict) -> None:
    """For artifacts that are not databases (the x4xref TSV). Payload untouched."""
    _sidecar(target).write_text(json.dumps(fp, separators=(",", ":")),
                                encoding="utf-8")


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
    if not all(k in data for k in ("content", "engine")):
        return None
    data.setdefault("detail", None)
    return data

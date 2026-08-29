r"""WHICH mod moved, and how — the localiser behind a moved content fingerprint.

`_freshness` answers *whether* the installed world changed. Until 2026-08-25 that
was the only answer available, and it cost **nine investigative steps and three
false leads** to turn "content changed" into "`distances` was updated" (F56).
Worse, three of those steps were themselves wrong instruments:

    set-diff installed vs indexed   identical 120/120  -- right answer, wrong question
    folder count                    unchanged 129      -- a rewrite is not a count change
    find -newermt <build time>      nothing since 17:10 -- STRUCTURALLY blind to a
                                                          BACK-DATED write, which is
                                                          exactly what happened

This module diffs two persisted vectors instead, so the same question is one
command. It deliberately owns no enumeration of its own: the vector comes from
`_freshness.content_detail`, the mod set from `_registry`, and the reference
paths from `_paths`. Re-deriving any of those here would be an eighth hand-rolled
copy of a walk this toolkit has already got wrong seven times.

THREE BASELINES, because an expensive one is not always current:

``store``     `effective.sqlite` `meta.fingerprint_detail` — moves on a rebuild
``xref``      the `md_xref.tsv` sidecar — moves on `x4xref build`
``snapshot``  written by `x4modlist snapshot` in milliseconds, for the gap between

The snapshot rung exists because the other two only advance when something
expensive runs. Drop three mods in over three days without rebuilding and a
store-based answer is one cumulative delta with no way to sequence it — which is
correct, but not the question being asked.

**A baseline with no vector raises `NoBaseline` rather than reporting "nothing
changed".** Every artifact written before 2026-08-25 is in that state, and a
confident empty answer from one of them is precisely the failure this toolkit
exists to prevent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from x4validate import _freshness, _merge, _registry

#: Kinds `diff_detail` emits, in the order a reader wants them: structural
#: changes first, then value changes, then the merely-touched.
_ORDER = {"added": 0, "removed": 1, "toggled": 2, "version": 3,
          "content": 4, "touched": 5}

_GLYPH = {"added": "+", "removed": "-", "toggled": "~",
          "version": "^", "content": "*", "touched": "."}

#: Per-mod, per-category cap on the file list. A mod can legitimately rewrite
#: thousands of files (Station_ink ships 7,508), and an unbounded dump buries the
#: answer. The cap is ANNOUNCED whenever it bites -- see `render`.
_FILE_CAP = 200


def snapshots_dir(registry: str | Path | None = None) -> Path:
    """Beside the other derived artifacts, not in a temp dir.

    A baseline that evaporates is not a baseline.

    ⚠ `registry` is NOT optional decoration. This used to resolve
    `DEFAULT_REGISTRY` unconditionally, so `x4modlist --registry <somewhere>
    snapshot` honoured the override for every read and then wrote its output
    into the DEFAULT registry's folder anyway. MEASURED 2026-08-29 while adding
    a `snapshot` cell to `gates/qa_sweep.py`: the sweep points every x4modlist
    cell at a throwaway copy precisely so a gate cannot mutate the state it
    inspects, and this one wrote a real snapshot into `dev/_registry/snapshots/`
    regardless. A documented override that ONE code path ignores is worse than
    no override, because everything else honouring it is what makes you trust it.
    """
    base = Path(registry) if registry else _registry.require(
        _registry.DEFAULT_REGISTRY, "the registry location",
        "set X4_MODS (or X4_REGISTRY), or pass --registry")
    return _registry._registry_file(Path(base)).parent / "snapshots"


def _dirs() -> list[Path]:
    """Every configured install root.

    `hash_content` used to walk ONE, so a mod deployed to the PROFILE extensions
    root was invisible to it. That root is empty today, which is why the omission
    cost nothing and survived -- but deploying there is a real and damaging
    mistake (it makes X4 report every dependency MISSING), so a tool that cannot
    see it cannot warn about it either.
    """
    return _registry.default_installed_dirs()


def take_snapshot(label: str | None = None,
                  registry: str | Path | None = None) -> Path:
    """Record the current vector, cheaply. ~0.1 s."""
    config = _merge.Config()
    fp = _freshness.fingerprint(config, _dirs())
    out_dir = snapshots_dir(registry)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Named by CONTENT, not by clock: two snapshots of an unchanged world collapse
    # onto one file instead of accumulating look-alike baselines, and the name
    # itself tells you which world it describes.
    name = f"snapshot-{fp['content']}"
    if label:
        safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in label)
        name += f"-{safe}"
    out = out_dir / f"{name}.json"
    out.write_text(json.dumps(fp, separators=(",", ":")), encoding="utf-8")
    return out


def _from_store() -> tuple[list | None, str]:
    from x4validate import _effective
    import sqlite3
    db = _effective.effective_db()
    if db is None or not Path(db).is_file():
        return None, f"the effective store ({db or 'not configured'}) — NOT FOUND"
    con = sqlite3.connect(str(db))
    try:
        stored = _freshness.read_sqlite(con)
    finally:
        con.close()
    if stored is None:
        return None, f"the effective store ({db}) — no fingerprint recorded"
    return stored.get("detail"), f"the effective store ({db})"


def _from_xref() -> tuple[list | None, str]:
    from x4validate import _xref
    tsv = _xref._default_tsv()
    stored = _freshness.read_sidecar(tsv)
    if stored is None:
        return None, f"the x4xref index ({tsv}) — no fingerprint recorded"
    return stored.get("detail"), f"the x4xref index ({tsv})"


def _from_snapshot(path: Path) -> tuple[list | None, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"snapshot {path} — unreadable ({exc})"
    return data.get("detail"), f"snapshot {path.name}"


def load_baseline(spec: str,
                  registry: str | Path | None = None) -> tuple[list | None, str]:
    """Resolve ``--since`` to (vector, human description).

    A missing vector comes back as None WITH its description, so the caller can
    say which baseline could not answer rather than emitting a bare failure.
    """
    if spec in ("store", "auto"):
        return _from_store()
    if spec == "xref":
        return _from_xref()
    if spec == "latest":
        # The READ side of the same override. Fixing only the write would leave
        # `--registry X changed --since latest` writing to X and reading from the
        # default -- a half-taught lookup chain, which is how a fix becomes a
        # subtler bug than the one it replaced.
        sd = snapshots_dir(registry)
        snaps = sorted(sd.glob("snapshot-*.json"),
                       key=lambda p: p.stat().st_mtime) if sd.is_dir() else []
        if not snaps:
            return None, "the latest snapshot — none taken yet"
        return _from_snapshot(snaps[-1])
    return _from_snapshot(Path(spec))


# --- the advisory USN rung ----------------------------------------------------

def usn_supplement(folders: list[str]) -> list[str]:
    """NTFS change-journal corroboration. ADVISORY, and usually unavailable.

    It is the only source immune to two things the vector cannot see: a
    BACK-DATED write, and NTFS **tunneling** (ON at Windows default), where a
    delete+recreate of the same name in the same directory within ~15 s PRESERVES
    the original CreationTime.

    It is also the only rung that needs privilege, and **the two fsutil verbs do
    not need the same amount of it.** MEASURED 2026-08-26 on a shell independently
    confirmed unelevated (`IsInRole(Administrator) == False`):

        fsutil usn queryjournal C:   rc=0   prints id, First/Next/Lowest USN
        fsutil usn readjournal  C:   rc=1   Error 5: Access is denied.

    The first version of this function probed with `queryjournal` and therefore
    announced *"USN journal: readable"* on a shell that cannot read one record --
    a tool claiming a capability it does not have, which is the worst direction
    for a check to fail in. **Probe the operation you NEED, not a cheaper
    neighbour.** It was found by running the command for real; the unit test had
    been written to the same wrong contract and agreed with the bug.

    `startusn=<Next Usn>` keeps the permission probe cheap: it asks for records
    from the END of the journal, so a permitted read returns almost nothing
    rather than dumping the entire change history just to test access.

    This degrades to a message rather than an error -- a tool that hard-fails on
    a capability the session cannot have is a tool people stop running.
    """
    if sys.platform != "win32":
        return ["USN journal: not available on this platform (NTFS only)."]
    drive = None
    for d in _dirs():
        if d and d.drive:
            drive = d.drive
            break
    if not drive:
        return ["USN journal: could not determine the volume."]
    # Returns None when fsutil could not be RUN at all -- distinct from running
    # and being refused, which is the case we actually expect. Signalling that
    # with a sentinel rather than by type-sniffing the return value keeps the two
    # apart without making the caller depend on subprocess internals.
    failure: list[str] = []

    def _run(*args):
        try:
            return subprocess.run(["fsutil", "usn", *args], capture_output=True,
                                  text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            failure.append(str(exc))
            return None

    hint = (f"    fsutil usn readjournal {drive} | findstr /i "
            + '"' + (folders[0] if folders else "<mod folder>") + '"')

    q = _run("queryjournal", drive)
    if q is None:
        return [f"USN journal: could not run fsutil ({failure[-1]})."]
    if q.returncode != 0:
        err = (q.stderr or q.stdout or "").strip().splitlines()
        return [f"USN journal: unavailable — {err[0] if err else f'exit {q.returncode}'}.",
                "  The other rungs above are unaffected by this."]

    # ⚠ `queryjournal` SUCCEEDS UNELEVATED and `readjournal` does NOT.
    # MEASURED 2026-08-26 on an unelevated shell: queryjournal rc=0 and printed the
    # journal id, while `readjournal` returned **Error 5: Access is denied**. Probing
    # with queryjournal therefore reported "readable" for a capability we do not
    # have -- a tool claiming a power it lacks, which is the exact false-positive
    # this package exists to refuse. So probe the operation actually needed.
    #
    # `startusn=<Next Usn>` makes the probe cheap: it asks for records from the END
    # of the journal, so a permitted read returns almost nothing instead of dumping
    # the whole change history.
    next_usn = ""
    for line in q.stdout.splitlines():
        if line.lower().replace(" ", "").startswith("nextusn:"):
            next_usn = line.split(":", 1)[1].strip()
            break

    probe = _run("readjournal", drive, *([f"startusn={next_usn}"] if next_usn else []))
    if probe is None:
        return [f"USN journal: could not run fsutil ({failure[-1]})."]
    if probe.returncode != 0:
        err = (probe.stderr or probe.stdout or "").strip().splitlines()
        return ["USN journal: NOT READABLE — "
                + (err[0] if err else f"exit {probe.returncode}"),
                "  `queryjournal` succeeds unelevated but `readjournal` does not;",
                "  change-journal READS require Administrator.",
                "  For a tunneling-proof check, run in an ELEVATED shell:",
                hint,
                "  The other rungs above are unaffected by this."]
    return ["USN journal: READABLE (this shell can read records).",
            "  It records the EVENT rather than a timestamp, so it is the one",
            "  source a back-dated write cannot hide from.",
            "  Corroborate with:",
            hint]


# --- rendering ----------------------------------------------------------------

def render(changes: list[dict], baseline_desc: str, show_files: bool) -> list[str]:
    lines = [f"baseline: {baseline_desc}"]
    if not changes:
        lines.append("")
        lines.append("no change: every installed mod matches the baseline, "
                     "file-for-file.")
        return lines
    changes = sorted(changes, key=lambda c: (_ORDER.get(c["kind"], 9),
                                             c["folder"].lower()))
    counts: dict[str, int] = {}
    for c in changes:
        counts[c["kind"]] = counts.get(c["kind"], 0) + 1
    lines.append("")
    for c in changes:
        lines.append(f"  {_GLYPH.get(c['kind'], '?')} {c['folder']:<44} "
                     f"{c['kind']:<8} {c.get('detail', '')}")
        if show_files:
            # A cap that does not ANNOUNCE itself is the founding defect shape of
            # this toolkit: a step that narrows the data and reports success
            # anyway. If the list is truncated, the omission is printed.
            for label, key in (("changed", "files_changed"),
                               ("touched", "files_touched")):
                names = c.get(key, [])
                for f in names[:_FILE_CAP]:
                    lines.append(f"        {label}  {f}")
                if len(names) > _FILE_CAP:
                    lines.append(f"        ... and {len(names) - _FILE_CAP} more "
                                 f"{label} file(s) NOT LISTED (cap {_FILE_CAP})")
    lines.append("")
    lines.append("  " + " | ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if not show_files:
        lines.append("  (--files names the exact files inside each mod)")
    return lines


def cmd_snapshot(args) -> int:
    out = take_snapshot(getattr(args, "label", None),
                        getattr(args, "registry", None))
    print(f"snapshot written: {out}")
    print("  Use it as a baseline:  x4modlist changed --since latest")
    return 0


def cmd_changed(args) -> int:
    baseline, desc = load_baseline(args.since, getattr(args, "registry", None))
    config = _merge.Config()
    now = _freshness.content_detail(config.reference, _dirs())

    if baseline is None:
        # A NON-ANSWER, and it must not read as "nothing changed".
        print(f"cannot localise: {desc} carries no content vector.", file=sys.stderr)
        print("", file=sys.stderr)
        print("This is a NON-ANSWER, not a finding of 'no change'. Artifacts built",
              file=sys.stderr)
        print("before 2026-08-25 predate the per-folder vector and cannot say WHICH",
              file=sys.stderr)
        print("mod moved -- only that something did.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Establish a baseline with either:", file=sys.stderr)
        print("    x4modlist snapshot                 (milliseconds, from now on)",
              file=sys.stderr)
        print("    uv run x4effective build           (rebuilds the store)",
              file=sys.stderr)
        return 3

    try:
        changes = _freshness.diff_detail(baseline, now)
    except _freshness.NoBaseline as exc:
        print(f"cannot localise: {exc}", file=sys.stderr)
        return 3

    for line in render(changes, desc, getattr(args, "files", False)):
        print(line)

    if getattr(args, "usn", False):
        print("")
        for line in usn_supplement([c["folder"] for c in changes]):
            print(line)

    return 1 if changes else 0


def register(sub) -> None:
    """Wire both subcommands into `x4modlist`'s parser.

    Registered here rather than in `_modlist.main` so the localiser owns its own
    surface -- and so a future caller cannot add one without the other.
    """
    pc = sub.add_parser("changed",
                        help="localise a moved content fingerprint: WHICH mod "
                             "changed, and how")
    pc.add_argument("--since", default="store",
                    help="baseline: store (default) | xref | latest | <path to a "
                         "snapshot json>")
    pc.add_argument("--files", action="store_true",
                    help="name the exact files that changed inside each mod")
    pc.add_argument("--usn", action="store_true",
                    help="advisory NTFS change-journal corroboration (needs an "
                         "elevated shell; immune to back-dating and to NTFS "
                         "tunneling)")
    pc.set_defaults(func=cmd_changed)

    ps = sub.add_parser("snapshot",
                        help="record the current mod vector as a cheap baseline "
                             "(~0.1s), for the gap between expensive rebuilds")
    ps.add_argument("--label", help="short name to append to the file")
    ps.set_defaults(func=cmd_snapshot)

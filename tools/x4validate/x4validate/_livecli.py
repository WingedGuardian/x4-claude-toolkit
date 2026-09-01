"""`x4live` - ask the RUNNING ENGINE what it saw, and diff it against our model.

Every other tool here reasons about files. This one reports what X4 itself had in
memory: the extension list it built, its error log, and the fully-resolved stats it
computed for a macro. That makes it the only ORACLE in the toolkit - the one thing
that can tell us our merged tree is wrong rather than merely self-consistent.

HOW THE DATA ARRIVES. A read-only lua probe assigns a TSV payload to a lua global
declared as a `<savedvariable>`; the engine serialises it into `{profile}/uidata.xml`
on exit. `_livedump` decodes and self-checks it. See that module for the three
escaping layers and for why a mid-session read is a NON-ANSWER rather than a zero.

TWO RULES THIS CLI EXISTS TO KEEP, both learned expensively elsewhere:

  * **Compare PER ITEM, never totals.** The first real run of this channel produced
    132 extensions from the engine and 132 from our model - and the MEMBERSHIP was
    wrong on both sides, two errors cancelling. A matching total is the shape a real
    divergence hides in (CLAUDE.md 1b).
  * **`GetExtensionList()` is an installed INVENTORY with an `enabled` flag, NOT the
    load set.** Comparing it to `mods("active")` without saying which scope you mean
    is the same category error as reading `Collision.winner` as an owner (#18). The
    scope is therefore explicit and printed in the output.

A dump that is missing, stale or malformed exits 2 or 3 and never 0: "I could not
ask" must not look like "there is no disagreement".
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import os
import sys
from pathlib import Path

from . import __version__, _livedump, _paths, _registry


def _fmt_rc(msg: str, rc: int) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return rc


def _load(path: str | None):
    return _livedump.load(Path(path) if path else None)


# --------------------------------------------------------------------------- dump

def cmd_dump(path: str | None, out=None) -> int:
    # Resolved at CALL time, never bound as a default: `out=sys.stdout` in the
    # signature captures whatever stdout was at IMPORT, so main()'s own
    # reconfigure() -- and any caller redirecting output -- would be ignored.
    out = sys.stdout if out is None else out
    d = _load(path)
    src = Path(path) if path else _livedump.uidata_path()
    print(f"dump from {src}", file=out)
    print(f"  probe    {d.header.get('probe', '(unnamed)')} "
          f"schema={d.header.get('schema', '?')}", file=out)
    print(f"  captured {d.header.get('elapsed', '?')} s after the menus loaded", file=out)
    print(f"  rows     {len(d.rows)} (self-checked against the terminator the game "
          f"itself wrote)", file=out)
    print("\n  row kinds:", file=out)
    for kind, n in sorted(d.kinds.items()):
        print(f"    {kind:<18} {n:>6}", file=out)
    total = sum(d.kinds.values())
    print(f"    {'TOTAL':<18} {total:>6}", file=out)
    if not d.accounts_for_every_row():
        print("  !! row kinds do not sum to the row count - unexplained remainder",
              file=out)
        return 3
    print("  every row is accounted for by a kind; no remainder.", file=out)

    st = d.one("ERR_STATUS")
    if st and len(st) > 2:
        print(f"\n  engine error log: {st[2]} errors at capture time; the probe "
              f"emitted {len(d.of('ERR'))}", file=out)
    print("\n  SCOPE -- this is what ONE probe emitted, not everything the engine "
          "knows.", file=out)
    print("  A kind that is absent here was never asked for.", file=out)
    _archive_hint(path, out)
    return 0


# --------------------------------------------------------------------- extensions

def cmd_extensions(path: str | None, scope: str, out=None) -> int:
    out = sys.stdout if out is None else out
    d = _load(path)
    ext = d.extensions()
    if not ext:
        print("the dump carries no EXT rows with named columns - the probe did not "
              "emit an extension list, so this is a NON-ANSWER", file=sys.stderr)
        return 3

    ego = [e for e in ext if e.get("egosoftextension") == "true"]
    mods = [e for e in ext if e.get("egosoftextension") != "true"]
    enabled = [e for e in mods if e.get("enabled") == "true"]
    assert len(ego) + len(mods) == len(ext)

    print(f"engine extension list ({len(ext)} entries)", file=out)
    print(f"  Egosoft extensions   {len(ego):>4}", file=out)
    print(f"  mods                 {len(mods):>4}  "
          f"({len(enabled)} enabled, {len(mods) - len(enabled)} disabled)", file=out)
    print("\n  NOTE: GetExtensionList() is an INSTALLED INVENTORY carrying an "
          "`enabled` flag.", file=out)
    print("  It is not the load set, and comparing it to the wrong scope is a "
          "category error.", file=out)

    # Both scopes are written out as LITERALS rather than passed through a variable.
    # The whole defect behind CLAUDE.md #24 was that a caller never had to say which
    # world it meant, so a reader could not tell either -- and comparing the engine's
    # inventory against the wrong population is exactly this tool's failure mode.
    if scope == "active":
        ours = {m["id"]: m for m in _registry.mods("active")}
        theirs = {e["id"]: e for e in enabled}
    else:
        ours = {m["id"]: m for m in _registry.mods("installed")}
        theirs = {e["id"]: e for e in mods}

    only_engine = sorted(set(theirs) - set(ours))
    only_ours = sorted(set(ours) - set(theirs))
    both = set(theirs) & set(ours)

    print(f"\n  comparing engine `{'enabled' if scope == 'active' else 'all'}` mods "
          f"against registry scope '{scope}', PER ITEM:", file=out)
    print(f"    engine {len(theirs)}   ours {len(ours)}   agreed {len(both)}", file=out)
    if only_engine:
        print(f"\n    the engine listed, our registry did not ({len(only_engine)}):",
              file=out)
        for i in only_engine:
            print(f"      + {i}", file=out)
    if only_ours:
        print(f"\n    our registry listed, the engine did not ({len(only_ours)}):",
              file=out)
        for i in only_ours:
            print(f"      - {i}", file=out)
    if not only_engine and not only_ours:
        print("    membership agrees item by item, not merely in total.", file=out)

    print(f"\n  Egosoft extensions the engine listed ({len(ego)}):", file=out)
    for e in sorted(ego, key=lambda x: x.get("id", "")):
        print(f"      {e.get('id')}", file=out)
    print("\n  An Egosoft extension absent from this list is NOT proven unloaded - "
          "the list", file=out)
    print("  is what the UI enumerates. Resolve one of its macros to settle that.",
          file=out)

    return 1 if (only_engine or only_ours) else 0


# ------------------------------------------------------------------------- errors

def cmd_errors(path: str | None, limit: int, out=None) -> int:
    out = sys.stdout if out is None else out
    d = _load(path)
    st = d.one("ERR_STATUS")
    rows = d.of("ERR")
    if st is None:
        print("the dump carries no ERR_STATUS row - the probe never asked the engine "
              "for its error log; this is a NON-ANSWER, not an empty log",
              file=sys.stderr)
        return 3
    if len(st) > 1 and st[1] != "OK":
        return _fmt_rc(f"the probe could not read the error log: {' '.join(st[1:])}", 3)

    total = st[2] if len(st) > 2 else "?"
    print(f"engine error log at capture time: {total} errors", file=out)
    print(f"  the probe emitted {len(rows)} of them "
          f"({' '.join(st[3:]) if len(st) > 3 else 'no cap declared'})", file=out)
    for r in rows[:limit]:
        sev = r[2] if len(r) > 2 else "?"
        ts = r[3] if len(r) > 3 else "?"
        msg = r[4] if len(r) > 4 else ""
        print(f"    [{sev}] {ts}  {msg}", file=out)
    if len(rows) > limit:
        print(f"    ... {len(rows) - limit} more emitted rows not shown "
              f"(--limit {limit})", file=out)
    print("\n  This is the engine's OWN log, capped by the probe. It is a SAMPLE of "
          "the total", file=out)
    print("  above, so a shape absent here is not proven absent from the run.",
          file=out)
    return 1 if rows else 0


# ------------------------------------------------------------------------- oracle

#: Unit transforms applied to the ENGINE value before comparing it to ours.
#:
#: The engine does not always answer in the units the XML declares. MEASURED
#: 2026-08-27 on `thruster_gen_s_allround_01_mk1_macro`: rotational thrust comes
#: back in RADIANS/sec where the store holds the XML value in DEGREES/sec --
#: 3.8397243022919 rad = 220.0000 deg = `thrust.pitch`, roll 4.1887903213501 =
#: 240.0000, yaw likewise. Three axes, exact to four decimals. Corroborated on
#: the store side: across 47 macros `thrust.pitch` ranges 0..2651, which is
#: degrees-shaped -- as radians, 2651 would be 422 rotations per second.
#:
#: Without this the oracle reports THREE false disagreements on every thruster in
#: the game, and a check that cries wolf is one you stop reading.
_TRANSFORMS = {
    "identity": lambda v: v,
    "degrees": lambda v: v * 180.0 / 3.141592653589793,
}

#: THE MAP IS KEYED BY LIBRARY TYPE, because a field NAME does not determine its
#: meaning. `shield` on a shieldgentypes entry is that generator's own capacity
#: (`recharge.max` = 2287); `shield` on a shiptypes_* entry is the ship's TOTAL
#: shielding, which the engine derives through `libraries/loadouts.xml` and our
#: store does not model at all. Same for `hull`: `hull.max` on a ship (2500), but
#: on an engine/shield/thruster the engine answers a flat 1000 matching no stored
#: property. A flat field->prop map silently applies one meaning to the other --
#: the `Collision.winner` category error (CLAUDE.md #18) inside a lookup table.
#:
#: EVERY entry is VERIFIED against a real dump on a NON-DEGENERATE value (never 0
#: or 1, which match anything); the confirming value is in the comment. Do not add
#: a speculative one: a guessed mapping sits in the same slot, in the same grammar,
#: as a measured one, and reports a DISAGREEMENT against our own store as though
#: the MODEL were wrong. Use `x4live mappings` to propose, never to auto-apply.
#:
#: THE TRANSFORM IS DECLARED, NEVER INFERRED AT COMPARISON TIME. Picking whichever
#: transform makes the values agree would produce a check that CANNOT FAIL -- the
#: exact shape CLAUDE.md #26 exists to refuse.

#: Hull-carrying mobile objects; `satellites` shares the ship field vocabulary.
_SHIPLIKE = {
    "hull": ("hull.max", "identity"),                             # 2500 scout
    "mass": ("physics.mass", "identity"),                         # 6.3429999351501
    "drag_forward": ("physics.drag.forward", "identity"),         # 2
    "drag_reverse": ("physics.drag.reverse", "identity"),         # 7.4
    "drag_horizontal": ("physics.drag.horizontal", "identity"),   # 4.8
    "drag_vertical": ("physics.drag.vertical", "identity"),       # 4.8
    "drag_pitch": ("physics.drag.pitch", "identity"),             # 3.9
    "drag_yaw": ("physics.drag.yaw", "identity"),                 # 3.9
    "drag_roll": ("physics.drag.roll", "identity"),               # 3.9
    "inertia_pitch": ("physics.inertia.pitch", "identity"),       # 1.8
    "inertia_yaw": ("physics.inertia.yaw", "identity"),           # 1.8
    "inertia_roll": ("physics.inertia.roll", "identity"),         # 1.43
    "radarrange": ("radar.range", "identity"),                    # 50000
    "purpose": ("purpose.primary", "identity"),                   # "fight"
    #: proposed by `x4live mappings` and confirmed unambiguous on satellites and
    #: shiptypes_s ("ship_s_scout_01"); applied to the whole ship-like family
    #: because identification.icon is a universal ship-macro property.
    "icon": ("identification.icon", "identity"),                  # "ship_s_scout_01"
}

_ENGINELIKE = {
    "boost_maxduration": ("boost.duration", "identity"),          # 9
    "boost_rechargetime": ("boost.recharge", "identity"),         # 92
    "boost_thrustfactor": ("boost.thrust", "identity"),           # 3.4
    "travel_chargetime": ("travel.charge", "identity"),           # 0.5
    "travel_thrustfactor": ("travel.thrust", "identity"),         # 21
    "thrust_pitch": ("thrust.pitch", "degrees"),                  # 3.8397243 = 220
    "thrust_yaw": ("thrust.yaw", "degrees"),                      # 3.8397243 = 220
    "thrust_roll": ("thrust.roll", "degrees"),                    # 4.1887903 = 240
    #: The store models ONE strafe figure for both lateral axes; the engine reports
    #: them separately and both read 300. A macro that ever set them differently
    #: could not be represented, and would surface here as a real disagreement --
    #: which is the correct outcome, not a bug in this table.
    "thrust_horizontal": ("thrust.strafe", "identity"),           # 300
    "thrust_vertical": ("thrust.strafe", "identity"),             # 300
}

#: `unitcapacity`, mapped where the evidence reaches and no further.
#:
#: MEASURED IN GAME 2026-08-31, both directions, because a mapping verified only on
#: the NULL case is a mapping you have never seen discriminate:
#:   POSITIVE  ship_arg_m_frigate_01_a_macro    engine 15 == store storage.unit 15
#:   POSITIVE  ship_arg_xl_builder_01_a_macro   engine 100 == 100   (2026-08-31)
#:   POSITIVE  ship_arg_l_trans_container_05_a  engine 15  == 15
#:   NULL      ship_arg_s_scout_01_a_macro      engine 0, store ABSENT
#:   NULL      ship_arg_m_trans_container_02_b  engine 0, store ABSENT
#:   NULL      ship_arg_s_heavyfighter_02_a     engine 0, store ABSENT
#:
#: ⚠ S IS DELIBERATELY EXCLUDED, and not out of caution -- MEASURED over the effective
#: store: exactly TWO S-class macros carry `storage.unit` in the entire corpus
#: (`ship_kha_s_fighter_01_a_macro`, `_02_a_`) and BOTH ARE ZERO. There is no positive
#: case to verify and none to get wrong, so the mapping could never discriminate. M by
#: contrast has 16 carriers, 12 of them nonzero, one verified against the engine.
#:
#: ⚠ ABSENT IS NOT ZERO. Three ships report engine 0 while the store holds no
#: `storage.unit` at all. The oracle compares what the store HAS; it does not coerce an
#: absence into a 0, because a fabricated 0 could AGREE with the engine by accident and
#: record a comparison that never happened. Same rule as `_derive_storagecapacity`
#: returning None rather than 0.
_SHIPLIKE_UNIT = {**_SHIPLIKE, "unitcapacity": ("storage.unit", "identity")}

_BY_TYPE: dict[str, dict[str, tuple[str, str]]] = {
    "shiptypes_xs": _SHIPLIKE, "shiptypes_s": _SHIPLIKE,
    "shiptypes_m": _SHIPLIKE_UNIT,
    "shiptypes_l": _SHIPLIKE_UNIT, "shiptypes_xl": _SHIPLIKE_UNIT,
    "satellites": _SHIPLIKE,
    "enginetypes": _ENGINELIKE, "thrustertypes": _ENGINELIKE,
    "shieldgentypes": {
        "shield": ("recharge.max", "identity"),                   # 2287
        "recharge": ("recharge.rate", "identity"),                # 20
        "rechargedelay": ("recharge.delay", "identity"),
    },
    "weapons_lasers": {
        "coolingrate": ("heat.coolrate", "identity"),             # 2000
    },
    # --- adopted 2026-08-30 from `x4live mappings --from-groundtruth` ------------ #
    # Every one came back nd=1 (a single non-degenerate agreement), so the tool's own
    # rule could not separate them and the deciding evidence is that each field NAME
    # matches its prop exactly. That is a weaker warrant than nd>=2 and is recorded as
    # such rather than dressed up.
    "missiletypes": {
        "hull": ("hull.max", "identity"),          # n=3 nd=1; 1/1/300 all agreed
        "locktime": ("lock.time", "identity"),     # n=1 nd=1; 2 == 2
    },
    "weapons_turrets": {
        # ⚠ `coolingrate` was ALSO proposed here, for this same prop, and is REJECTED.
        # MEASURED: on the one sampled turret engine coolingrate=200 and
        # rotationspeed.max=200 by coincidence, while the real prop `heat.coolrate` is
        # ABSENT so nothing else could match. Cooling rate is not a rotation speed. Two
        # different engine fields claiming one prop is the tell.
        "rotation": ("rotationspeed.max", "identity"),   # n=1 nd=1; 199.99998 ~= 200
    },
}

#: Fields the ENGINE derives by following refs our store only records: weapon DPS
#: (from the bullet) and ship aggregates (connections, dockareas, loadouts). We do
#: NOT reimplement X4's maths -- see `oracle --show-derived` and BLIND-SPOTS F72.
#: Naming them separately keeps a known modelling gap from hiding inside a generic
#: "unmapped" bucket, where it would look like a table that needs more entries.
_DERIVED = {
    "dps", "sustaineddps", "hullonlydps", "shieldonlydps", "hullnoshielddps",
    "hullshielddps", "timetooverheat", "timetocool", "range", "shielddisruption",
    # `storagecapacity` REMOVED 2026-08-30: it now has a measured traversal in
    # _DERIVE (sum cargo.max over connected macros), verified 5 of 5 exact across
    # the fixture. `shipstoragecapacity` stays -- see P5: the engine reports 0 for
    # a scout that carries a shipstorage macro with dock.capacity=10, so it is NOT
    # a sum of connected capacities and no traversal has been shown to reproduce it.
    "shipstoragecapacity",
    # ⚠ `unitcapacity` WAS here and has been REMOVED, 2026-08-30. It was classified
    # as an aggregate needing a traversal; MEASURED, it is stored DIRECTLY -- engine
    # unitcapacity=25 on ship_arg_l_destroyer_01_a_macro and the store's
    # `storage.unit` is 25. The classification was a hypothesis and the measurement
    # refuted it, so the mapping stays and this entry goes: a field cannot be both
    # "we cannot compute this" and "here is how we compute it", which is exactly what
    # test_derived_fields_are_named_not_folded_into_unmapped protects.
    # shiptypes_m/l/xl carry the mapping (see _SHIPLIKE_UNIT). S is excluded because
    # MEASURED: both S-class macros carrying storage.unit are ZERO, so there is no
    # positive case anywhere in the corpus for the mapping to discriminate on.
    "docks_s", "docks_m", "docks_l", "docks_xl", "launchtubes_s", "launchtubes_m",
    "efficiencyfactor", "efficiencybonus",
}


def _mapping_for(ltype: str, field: str) -> tuple[str, str] | None:
    """The (store prop, transform name) for *field* on a *ltype* entry, or None."""
    return _BY_TYPE.get(ltype, {}).get(field)


def _agree(a: str, b: str) -> bool:
    """Numeric fields compare at FLOAT32 precision, not as strings.

    The engine returns float32 values widened to double, so `4.8` reaches us as
    `4.8000001907349`. A string compare would report every float as a disagreement
    and bury any real one under the noise.
    """
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    return abs(fa - fb) <= max(abs(fa), abs(fb)) * 1e-6 + 1e-9


def _store_props(con, macro: str) -> dict[str, str] | None:
    """Every effective property of *macro*, or None when the store has no such entity."""
    ent = con.execute("SELECT id FROM entities WHERE kind=? AND name=?",
                      ("macro", macro)).fetchone()
    if ent is None:
        return None
    rows = con.execute("SELECT prop, value FROM attrs WHERE entity_id=?",
                       (ent["id"],)).fetchall()
    return {r["prop"]: r["value"] for r in rows}



#: A connection ref key looks like `connections.connection[con_storage01].macro.ref`.
_CONN_REF_SUFFIX = "].macro.ref"
_CONN_REF_PREFIX = "connections.connection["


def _connected_macros(props: dict[str, str]) -> list[str]:
    """The macros this one connects to, in store order.

    The flatten keeps the whole connection subtree, so the refs are simply attrs:
    `connections.connection[con_storage01].macro.ref = storage_arg_s_scout_01_a_macro`.
    This is the traversal F72 called unmodelled -- the data was always there.
    """
    return [v for k, v in props.items()
            if k.startswith(_CONN_REF_PREFIX) and k.endswith(_CONN_REF_SUFFIX)]


def _sum_over_connections(con, props: dict[str, str], prop: str) -> tuple[float, int]:
    """(sum of *prop* over connected macros, how many carried it)."""
    total, seen = 0.0, 0
    for ref in _connected_macros(props):
        sub = _store_props(con, ref)
        if sub is None or prop not in sub:
            continue
        try:
            total += float(sub[prop])
        except (TypeError, ValueError):
            # silent-ok: NOT swallowed -- `seen` is the channel. A ref whose prop
            # will not parse as a number contributes nothing AND is not counted, so
            # if none of them parse the caller gets seen==0 and returns None rather
            # than a fabricated 0. The absence survives to the caller.
            continue
        seen += 1
    return total, seen


def _derive_storagecapacity(con, props: dict[str, str]) -> str | None:
    """Sum `cargo.max` over the macros this one connects to.

    MEASURED 2026-08-30 against every ship in the groundtruth fixture -- 5 of 5 exact,
    0 mismatches, spanning S through XL and 540 to 38000:

        ship_arg_s_scout_01_a_macro          540
        ship_gen_s_fighter_01_a_macro        700
        ship_arg_l_destroyer_01_a_macro     2300
        ship_arg_m_trans_container_01_a     8200
        ship_arg_xl_carrier_01_a_macro     38000

    ⚠ Returns None when NO connected macro carries `cargo.max`, rather than 0. A zero
    would be indistinguishable from "this ship genuinely holds nothing", and the oracle
    would then compare a fabricated 0 against the engine and call it agreement. An
    absence must stay an absence.
    """
    total, seen = _sum_over_connections(con, props, "cargo.max")
    if seen == 0:
        return None
    return str(int(total)) if total == int(total) else str(total)


#: Fields we can COMPUTE from the store by following refs, rather than read from one
#: prop. Consulted after the direct map and before `_DERIVED`, so a field that gains a
#: traversal stops being counted as an unmodelled gap.
#:
#: ⚠ Everything here must be MEASURED against the fixture before it is added. F72's own
#: warning is that several of these aggregates have more than one defensible definition:
#: on a carrier `docks_s` could be dockingbays reached through one dockarea, or that plus
#: launch tubes, or that plus ship storage. Writing a traversal without checking is
#: picking one and calling it modelled.
_DERIVE: dict[str, object] = {
    "storagecapacity": _derive_storagecapacity,
}

def cmd_oracle(path: str | None, out=None, show_derived: bool = False,
               groundtruth: str | None = None) -> int:
    out = sys.stdout if out is None else out
    from ._effective import _connect, effective_db, store_freshness

    # THE SAME BLOCKER AS cmd_mappings HAD, IN A SECOND PLACE. Both read a uidata dump,
    # which needs the engine-probe mod deployed and the game CLOSED. With that mod removed
    # the whole F72 oracle was unreachable -- `x4live oracle` exits 2 with "the probe did
    # not run" -- so no comparison could be made at all. `groundtruth` produces the
    # identical (librarytype, macro, field, value) data over the live pipe.
    if groundtruth:
        gt = Path(groundtruth)
        if not gt.is_file():
            return _fmt_rc(f"no such groundtruth file: {gt}", 2)
        entries, st = _entries_from_groundtruth(gt)
        print(f"source: {gt.name}  rows={st['lines']} parsed={st['parsed']} "
              f"(all-field {st['star_rows']}, per-field {st['field_rows']}) "
              f"UNPARSEABLE={st['unparseable']}", file=out)
        if st["unparseable"]:
            print(f"  {st['unparseable']} line(s) excluded, not repaired "
                  f"(written before the escaping fix)", file=out)
    else:
        d = _load(path)
        entries = d.library_entries()
    if not entries:
        print("no resolved engine values to compare against - NON-ANSWER, not "
              "'the model agrees'.", file=sys.stderr)
        return 3

    db = effective_db()
    if db is None or not db.exists():
        return _fmt_rc(
            "the effective store does not exist - run `x4effective build` first", 2)
    try:
        con = _connect(db)
    except Exception as exc:                       # noqa: BLE001 - reported, not hidden
        return _fmt_rc(f"the effective store could not be opened: {exc}", 2)

    # A STALE store is refused here, not merely warned about. Everywhere else a
    # stale answer is still an answer about a slightly older world; here the whole
    # output is a VERDICT on whether our model matches the engine, so staleness
    # does not degrade the result, it inverts what it means.
    fresh = store_freshness(con)
    if not fresh.fresh:
        print(fresh.banner("the effective store"), file=sys.stderr)
        print("!! Rebuild first:  uv run x4effective build", file=sys.stderr)
        print("   Refusing to compare the engine against a store that may not "
              "describe the current world.", file=sys.stderr)
        return 3

    match = differ = derived = unmapped = 0
    diffs: list[tuple[str, str, str, str, str, bool]] = []
    derived_rows: list[tuple[str, str, str]] = []
    missing: list[str] = []

    for (ltype, macro), fields in sorted(entries.items()):
        props = _store_props(con, macro)
        if props is None:
            missing.append(macro)
            continue
        for f, ev in sorted(fields.items()):
            mapped = _mapping_for(ltype, f)
            sv = None
            if mapped is not None and mapped[0] in props:
                prop, tname = mapped
                sv = str(props[prop])
            elif f in _DERIVE:
                # A field we can COMPUTE by following refs. It stops being an unmodelled
                # gap and becomes a real comparison -- which is the point of F72.
                computed = _DERIVE[f](con, props)
                if computed is not None:
                    prop, tname, sv = f"<derived:{f}>", "identity", computed
            if sv is None:
                # Split the old catch-all: a field the ENGINE derives is a known
                # modelling gap (F72) and gets named; anything else is simply not
                # mapped yet. Folding them together hid which was which.
                if f in _DERIVED:
                    derived += 1
                    derived_rows.append((macro, f, ev))
                else:
                    unmapped += 1
                continue
            try:
                cooked = str(_TRANSFORMS[tname](float(ev)))
            except (TypeError, ValueError):
                cooked = ev
            if _agree(cooked, sv):
                match += 1
            else:
                # TRANSFORM-SUSPECT: the declared transform disagrees but the RAW
                # value would have agreed. Still a disagreement -- the transform is
                # never auto-corrected -- but the likely cause is named.
                suspect = tname != "identity" and _agree(ev, sv)
                differ += 1
                diffs.append((macro, f, ev, prop, sv, suspect))

    compared = sum(len(f) for (k, f) in entries.items() if k[1] not in missing)
    accounted = match + differ + derived + unmapped
    print("engine values vs the effective store, PER FIELD", file=out)
    print(f"  entities in the dump      {len(entries)}", file=out)
    print(f"  not found in the store    {len(missing)}", file=out)
    print(f"  fields on compared items  {compared}", file=out)
    print(f"    directly comparable     {match + differ}  "
          f"({match} agree, {differ} DISAGREE)", file=out)
    print(f"    engine-DERIVED (F72)    {derived}  "
          f"(our store cannot produce these)", file=out)
    print(f"    not mapped yet          {unmapped}", file=out)
    if accounted != compared:
        print(f"  !! {compared - accounted} fields unaccounted for - "
              f"a remainder is a lead, not a rounding error", file=out)
        return 3
    if missing:
        print("\n  not in the store (a faction or ware is legitimately not a macro):",
              file=out)
        for m in missing:
            print(f"      {m}", file=out)
    if diffs:
        print("\n  DISAGREEMENTS - the engine and our model differ:", file=out)
        for macro, f, ev, prop, sv, suspect in diffs:
            note = ("   <- TRANSFORM-SUSPECT: the RAW engine value agrees, so the "
                    "declared unit transform is probably wrong" if suspect else "")
            print(f"      {macro}\n        engine {f} = {ev}\n"
                  f"        store  {prop} = {sv}{note}", file=out)
    else:
        print("\n  no disagreement on any directly-comparable field.", file=out)

    if show_derived and derived_rows:
        print(f"\n  ENGINE-DERIVED values our store does not model ({len(derived_rows)})"
              f" - recorded as", file=out)
        print("  ground truth, NOT compared. These become the test fixture for the "
              "traversal", file=out)
        print("  when we build it (BLIND-SPOTS F72):", file=out)
        for macro, f, ev in derived_rows:
            print(f"      {macro:<44} {f:<22} = {ev}", file=out)
    print("\n  SCOPE -- only the fields in the DIRECT map are compared; localised "
          "strings and", file=out)
    print("  derived aggregates (storage, docks, shield) are counted, not checked. "
          "A zero", file=out)
    print("  here is 'nothing disagreed among what was compared', not 'the model is "
          "correct'.", file=out)
    # The caveat that bounds the whole oracle, and it is easy to miss because the
    # numbers look so strong. `GetLibraryEntry` is the ENCYCLOPEDIA/UI library API --
    # what it exposes is what the MENU needs. For most stats that is the same resolved
    # value the simulation uses, but it is not guaranteed to be, and nothing here can
    # tell the two apart. So agreement means "our store matches what the game SHOWS",
    # which is one step short of "matches what the game SIMULATES".
    print("  ⚠ and these are ENCYCLOPEDIA (UI-library) values. Agreement means our "
          "store matches", file=out)
    print("  what the game SHOWS, which is one step short of what it SIMULATES. "
          "Weaker than it looks", file=out)
    print("  wherever a field is UI-facing. (Raised by a peer session, 2026-08-29.)",
          file=out)
    return 1 if diffs else 0



# ------------------------------------------------------------------- mappings

#: A value that matches everything proves nothing. 0 and 1 are the obvious ones;
#: a value shared by several props of the SAME macro is the subtler one, and it
#: is how the first attempt at this "discovered" `docks_l -> storage.missile`.
_DEGENERATE_SHARE = 3


def _is_degenerate(value: str, props: dict[str, str]) -> bool:
    """True when agreeing on *value* carries no information."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return not value.strip()
    if f in (0.0, 1.0):
        return True
    shared = sum(1 for v in props.values() if _agree(value, v))
    return shared >= _DEGENERATE_SHARE



def _entries_from_groundtruth(path: Path) -> tuple[dict[tuple[str, str], dict[str, str]],
                                                   dict[str, int]]:
    """Read a `groundtruth` TSV into the same shape `Dump.library_entries()` returns.

    WHY THIS EXISTS, and it is the whole reason F72 sat open for three days. `cmd_mappings`
    was already written and already sound -- it just took its input from a **uidata dump**,
    which needs the engine-probe mod deployed and the game CLOSED. `groundtruth` writes the
    IDENTICAL data over the live pipe, as a TSV whose columns are literally
    `librarytype / macro / field / engine_value`. Nobody ever connected the two, so the
    tool that could widen the map had no input it could reach. That is a file-format
    mismatch, not a modelling problem.

    TWO ROW SHAPES, both carried into the same dict:
      * a per-field row   -> one field
      * a `*` row         -> the engine's ALL-FIELDS reply, tab-joined inside column 4.
        These are the RICH ones and a naive 4-way split drops every one of them. Split
        with maxsplit=3.

    ⚠ RETURNS ITS OWN DENOMINATORS. Older fixtures were written before the escaping fix
    below, so a value containing a tab or newline can still break a row. Those lines are
    COUNTED and reported, never silently skipped -- a fixture that quietly lost rows reads
    downstream as "the engine does not report that field".
    """
    TAB, NL = chr(9), chr(10)
    entries: dict[tuple[str, str], dict[str, str]] = {}
    stats = {"lines": 0, "parsed": 0, "unparseable": 0, "star_rows": 0, "field_rows": 0}

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        stats["lines"] += 1
        parts = line.split(TAB, 3)
        if len(parts) != 4:
            stats["unparseable"] += 1
            continue
        ltype, macro, field, value = parts
        if ltype == "librarytype":            # the header row
            stats["lines"] -= 1
            continue
        stats["parsed"] += 1
        bucket = entries.setdefault((ltype, macro), {})
        if field == "*":
            stats["star_rows"] += 1
            # ⚠ SPLIT ON THE ESCAPE, NOT ON A REAL TAB. The `*` payload is the
            # engine's all-fields reply, tab-joined INTERNALLY, and the writer's
            # escaping (added 2026-08-30) turns every one of those separators into a
            # two-character `	`. Splitting on a real tab therefore found NONE and
            # parsed only the FIRST key=value -- MEASURED: it cut the scout from 37
            # fields to 10, losing hull, mass and all six drag and three inertia axes,
            # which are exactly the directly-comparable ones. The fixture then looked
            # merely "equipment-heavy" rather than gutted.
            # Pre-2026-08-30 fixtures carry REAL tabs and must still parse, so pick
            # the separator that is actually present rather than assuming a vintage.
            esc_tab = chr(92) + "t"
            sep = esc_tab if esc_tab in value else TAB
            for kv in value.split(sep):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    # A per-field row is the more precise record of the same cell, so it
                    # WINS: the all-fields reply is one flattened string and a value
                    # containing "=" or a tab is ambiguous inside it.
                    bucket.setdefault(k, _unescape(v))
        else:
            stats["field_rows"] += 1
            bucket[field] = _unescape(value)
    return entries, stats


def _unescape(s: str) -> str:
    """Reverse the writer's escaping. A fixture written before that existed is
    unaffected, because it contains no escapes to reverse."""
    B = chr(92)
    return (s.replace(B + "t", chr(9))
             .replace(B + "n", chr(10))
             .replace(B + B, B))

def cmd_mappings(path: str | None, out=None, groundtruth: str | None = None) -> int:
    """DERIVE candidate engine-field -> store-prop mappings from data.

    ⚠ Value-matching alone INVENTS mappings. Run naively over a real dump it
    "discovers" `docks_l = 0 -> storage.missile` and `drag_forward = 1 ->
    identification.deployable`, because any zero matches any zero. It is a lead
    generator, not an answer.

    Two rules make it sound, and both are reported rather than assumed:
      * a candidate must agree on EVERY macro of that library type carrying both
        the field and the prop -- one disagreement disqualifies it outright;
      * at least one of those agreements must be on a NON-DEGENERATE value.

    Anything surviving with exactly one candidate prop is proposed. Anything with
    several is printed as AMBIGUOUS for a human to resolve. Nothing is written to
    `_BY_TYPE` automatically: a guessed entry would sit in the same slot, in the
    same grammar, as a measured one.
    """
    out = sys.stdout if out is None else out
    from ._effective import _connect, effective_db, store_freshness

    if groundtruth:
        gt = Path(groundtruth)
        if not gt.is_file():
            return _fmt_rc(f"no such groundtruth file: {gt}", 2)
        entries, st = _entries_from_groundtruth(gt)
        # Denominators BEFORE the finding. A fixture that lost rows reads downstream as
        # "the engine does not report that field".
        print(f"source: {gt.name}  rows={st['lines']} parsed={st['parsed']} "
              f"(all-field {st['star_rows']}, per-field {st['field_rows']}) "
              f"UNPARSEABLE={st['unparseable']}", file=out)
        if st["unparseable"]:
            print(f"  ⚠ {st['unparseable']} line(s) could not be split into 4 columns -- "
                  f"written before the escaping fix. They are EXCLUDED, not repaired.",
                  file=out)
        if not entries:
            print("the groundtruth file carries no usable rows - NON-ANSWER, not "
                  "'no mappings exist'.", file=sys.stderr)
            return 3
    else:
        d = _load(path)
        entries = d.library_entries()
        if not entries:
            print("the dump carries no LIB_ENTRY_VAL rows - nothing to derive from. "
                  "NON-ANSWER.", file=sys.stderr)
            return 3

    db = effective_db()
    if db is None or not db.exists():
        return _fmt_rc("the effective store does not exist - run `x4effective build`", 2)
    con = _connect(db)
    fresh = store_freshness(con)
    if not fresh.fresh:
        print(fresh.banner("the effective store"), file=sys.stderr)
        print("!! Rebuild first:  uv run x4effective build", file=sys.stderr)
        return 3

    # (ltype, field) -> prop -> [agreed_bool...]  plus whether any was informative
    votes: dict[tuple[str, str], dict[str, list[bool]]] = {}
    informative: dict[tuple[str, str], set[str]] = {}
    #: How many entities backed each candidate with a NON-DEGENERATE value.
    #: ⚠ The soundness rule ("agrees on EVERY macro carrying both") is trivially
    #: satisfied at n=1, so a coincidence survives it looking exactly like a
    #: measurement. MEASURED 2026-08-30: `weapons_turrets coolingrate ->
    #: rotationspeed.max` was proposed on ONE turret where coolingrate happened to
    #: be 200 and rotationspeed.max was 200, while the real prop (heat.coolrate)
    #: was ABSENT so nothing else could match. Semantically absurd, structurally
    #: indistinguishable -- until the support count is printed.
    informative_n: dict[tuple[str, str], dict[str, int]] = {}
    seen_fields: dict[str, set[str]] = {}
    n_entities = 0

    for (ltype, macro), fields in sorted(entries.items()):
        props = _store_props(con, macro)
        if props is None:
            continue
        n_entities += 1
        for f, ev in fields.items():
            seen_fields.setdefault(ltype, set()).add(f)
            key = (ltype, f)
            for prop, sv in props.items():
                for tname, fn in _TRANSFORMS.items():
                    try:
                        cooked = str(fn(float(ev)))
                    except (TypeError, ValueError):
                        cooked = ev if tname == "identity" else None
                    if cooked is None:
                        continue
                    if _agree(cooked, sv):
                        slot = prop if tname == "identity" else f"{prop} [{tname}]"
                        votes.setdefault(key, {}).setdefault(slot, []).append(True)
                        if not _is_degenerate(ev, props):
                            informative.setdefault(key, set()).add(slot)
                            d = informative_n.setdefault(key, {})
                            d[slot] = d.get(slot, 0) + 1

    proposed: list[tuple[str, str, str, int, int]] = []
    ambiguous: list[tuple[str, str, list[str]]] = []
    for key in sorted(votes):
        ltype, field = key
        good = sorted(informative.get(key, ()))
        if not good:
            continue
        if len(good) == 1:
            slot = good[0]
            proposed.append((ltype, field, slot,
                             len(votes[key].get(slot, ())),
                             informative_n.get(key, {}).get(slot, 0)))
        else:
            ambiguous.append((ltype, field, good))

    known = {(lt, f) for lt, m in _BY_TYPE.items() for f in m}
    fresh_props = [p for p in proposed if (p[0], p[1]) not in known]

    print("candidate engine-field -> store-prop mappings, DERIVED from the dump",
          file=out)
    print(f"  entities compared        {n_entities}", file=out)
    print(f"  library types seen       {len(seen_fields)}", file=out)
    print(f"  already in _BY_TYPE      {len(known)}", file=out)
    print(f"  proposed (unambiguous)   {len(proposed)}  "
          f"of which NEW: {len(fresh_props)}", file=out)
    print(f"  AMBIGUOUS (need a human) {len(ambiguous)}", file=out)

    if fresh_props:
        print("", file=out)
        print("  NEW, unambiguous, confirmed on a non-degenerate value.", file=out)
        print("  n = entities that agreed; nd = of those, on a NON-DEGENERATE value.",
              file=out)
        print("  n=1 IS A LEAD, NOT AN ANSWER: the soundness rule (agrees on "
              "EVERY macro carrying both) is trivially true at n=1, so a coincidence "
              "survives it looking identical to a measurement. Read the field NAME and "
              "ask whether the mapping makes SENSE before adopting a low-n row.", file=out)
        for lt, f, prop, n, nd in sorted(fresh_props, key=lambda r: (-r[4], -r[3])):
            flag = "" if nd >= 2 else "   <- nd=1, VERIFY BY HAND"
            print(f'      {lt:<16} "{f}": ("{prop}"),'
                  f'   [n={n} nd={nd}]{flag}', file=out)
    if ambiguous:
        print("\n  AMBIGUOUS - several props agree; resolve by hand, do NOT guess:",
              file=out)
        for lt, f, ps in ambiguous:
            print(f"      {lt:<16} {f:<22} -> {', '.join(ps)}", file=out)

    print("\n  SCOPE -- a candidate is only as good as the sample. These come from "
          f"{n_entities}", file=out)
    print("  entities in ONE dump; a mapping that happens to hold there can still be", file=out)
    print("  coincidence. NOTHING here is written to _BY_TYPE automatically.", file=out)
    return 1 if (fresh_props or ambiguous) else 0

# --------------------------------------------------------------------------- main

@contextlib.contextmanager
def _live_open(pipe: str | None, timeout: float):
    """Open the channel, wait for the game, and always close it again.

    A CONTEXT MANAGER rather than a plain factory, and that is not style. `LivePipe`
    is itself a context manager, so a factory that pre-opened and was then used in a
    `with` would call `CreateNamedPipe` TWICE -- and with `nMaxInstances=1` the second
    call fails, leaking the first handle and leaving a live pipe nothing will ever
    close. Opening in exactly one place makes that unrepresentable.

    Every verb gets the same three-state diagnosis through here: never connected (mod
    not loaded, or game not running), connected then silent (loaded but paused or
    hung), or answering.
    """
    from . import _livepipe

    lp = _livepipe.LivePipe(name=pipe, timeout=timeout)
    lp.open()
    try:
        lp.wait_for_game()
        yield lp
    finally:
        lp.close()


def cmd_query(verb: str, args: list[str], pipe: str | None, timeout: float,
              out=None) -> int:
    """Ask the RUNNING engine one fixed-vocabulary question.

    This is the LIVE half of the oracle. `x4live oracle` reads uidata.xml, which the
    engine truncates to 61 bytes while it is running -- so that half only works with
    the game CLOSED. They are complements.
    """
    out = out or sys.stdout
    from . import _livepipe

    with _live_open(pipe, timeout) as lp:
        path = lp.path
        r = lp.ask(verb, *args)

    print(f"pipe    : {path}", file=out)
    print(f"verb    : {verb} {' '.join(args)}".rstrip(), file=out)
    print(f"status  : {r.status}", file=out)

    if r.status == "ERR":
        # The GAME reported a problem with the question. That is an answer about the
        # question, not a channel fault -- so it is a finding (1), not a non-answer.
        print(f"engine  : {r.payload}", file=out)
        print("\nthe engine answered, and the answer is that the question was bad.",
              file=out)
        return 1
    if r.status == "ABSENT":
        # ABSENT is an ANSWER: asked, and there is no such thing. Never rc 2.
        print(f"absent  : {r.payload}", file=out)
        print("\nthe engine was asked and reports no such entry. This is a FINDING, "
              "not a failure to ask.", file=out)
        return 1

    for line in r.fields or [""]:
        print(f"  {line}", file=out)
    print(f"\n{len(r.fields)} field(s), {_livepipe.byte_len(r.payload)} payload "
          f"bytes, length and checksum both verified.", file=out)
    return 0


#: Payload sizes for the cap ramp. Deliberately spans BOTH candidate answers -- the
#: unsourced 2047-byte figure and python's 64 KB buffer -- with steps either side of
#: each, because a ramp that stops below the real ceiling reports the ramp's own
#: limit as a finding.
#:
#: ⚠ THE TOP MUST STAY BELOW OUR OWN READ BUFFER. `_livepipe._BUF` is 64 KiB and the
#: frame adds a ~24-byte header, so a 65536-byte payload is a 65560-byte MESSAGE that
#: overflows the buffer on OUR side. MEASURED 2026-08-29 by the E2E ramp test against a
#: stand-in that truncates nothing: the ramp reported "the ceiling lies in (60000,
#: 65536]" -- which is this module's buffer, not the game's transport, and it would have
#: gone into F74 as an engine measurement. `test_the_ramp_cannot_probe_past_our_own_buffer`
#: pins the invariant.
RAMP_SIZES = (256, 512, 1024, 1536, 2000, 2048, 3072, 4096,
              8192, 16384, 32768, 60000, 64000,
              # Above the OLD 64 KiB buffer. Every one of these previously
              # measured US, not the engine; `_BUF` is now 1 MiB so they do not.
              96000, 131072, 262144, 524288)


def cmd_ramp(pipe: str | None, timeout: float, out=None) -> int:
    """MEASURE the message-size ceiling, because nobody has written it down.

    `pipes.lua:698`: *"If the message is larger than the lua side buffer, returns
    partial data and error ERROR_MORE_DATA. TODO: look into this."* The TODO is
    unhandled -- but CORRECTED 2026-08-29 by reading the packed source: that comment
    is on the READ path (the game reading our COMMAND), and it does not truncate. It
    raises, reaches `Close_Pipe`, and DESTROYS THE PIPE, ERRORing every pending read
    and write. Replies fail the same way by the api's own docs. So the ramp is
    measuring where a message stops surviving, and an over-long one costs the whole
    connection rather than a few bytes off the end.

    Python buffers 64 KB; an earlier session recorded 2047 bytes from the winpipe DLL
    with no traceable source (REFUTED in game 2026-08-29 -- 64,000 bytes round-trips);
    the mod's own readme documents no limit at all. Different layers, so this measures
    rather than picks.

    Stops at the first failure and reports the last size that round-tripped intact.
    It does NOT keep going: a truncation can leave the FIFO out of step, and every
    later result would then be a reply to the previous question.
    """
    out = out or sys.stdout
    from . import _livepipe

    last_ok = None
    first_bad = None
    reason = ""
    # The header is printed only AFTER the game connects. Printing it first would
    # leave a table header above nothing on a failed run -- which reads as "zero
    # results" when the truth is "never ran", and that is the precise confusion this
    # whole module exists to refuse.
    with _live_open(pipe, timeout) as lp:
        return _ramp_over(lp, out)


def _ramp_over(lp, out) -> int:
    """The ramp itself, against an ALREADY-OPEN pipe.

    Split out because the lua client does not reconnect after a disconnect, so a
    session's whole budget is one connection. One implementation, two callers.
    """
    from . import _livepipe

    last_ok = None
    first_bad = None
    reason = ""
    path = lp.path
    print("MESSAGE-SIZE RAMP", file=out)
    print("=" * 72, file=out)
    print("payload bytes | frame bytes | result", file=out)
    for n in RAMP_SIZES:
        # The cap applies to the whole MESSAGE, so the frame header counts. A
        # ramp reported in payload bytes alone would misplace the ceiling by the
        # header width and look like an off-by-a-constant in the transport.
        try:
            r = lp.ask("echo", str(n))
        except _livepipe.LiveQueryDegraded as exc:
            first_bad, reason = n, str(exc)
            print(f"{n:>13} | {'?':>11} | FAILED", file=out)
            break
        except _livepipe.LiveQueryUnavailable as exc:
            first_bad, reason = n, str(exc)
            print(f"{n:>13} | {'?':>11} | NO REPLY", file=out)
            break
        if r.status != "OK":
            first_bad, reason = n, f"{r.status}: {r.payload}"
            print(f"{n:>13} | {'?':>11} | {r.status}", file=out)
            break
        frame = _livepipe.byte_len(r.payload) + 24  # tag+proto+seq+status+len+sum
        print(f"{n:>13} | {frame:>11} | ok", file=out)
        last_ok = n

    print("", file=out)
    if last_ok is None:
        # Nothing at all round-tripped. That is a NON-ANSWER about the ceiling: we
        # have not bounded it, we have failed to measure it.
        print(f"NOTHING round-tripped, not even {RAMP_SIZES[0]} bytes.", file=out)
        print(f"  {reason}", file=out)
        print("This does not bound the cap. It says the channel is not working.",
              file=out)
        return 2

    print(f"largest payload that round-tripped INTACT: {last_ok} bytes "
          f"(~{last_ok + 24} on the wire), over {path}", file=out)
    if first_bad is None:
        # Every size passed. The ceiling is ABOVE the ramp, so the ramp did not find
        # it -- and saying "the cap is 65536" here would be reporting the
        # instrument's own limit as a measurement.
        print(f"every size up to {RAMP_SIZES[-1]} passed, so the ceiling is ABOVE "
              f"this ramp. NOT a measured cap.", file=out)
        print(f"  and it cannot be widened much: our own read buffer is "
              f"{_livepipe._BUF} bytes, so anything past ~{_livepipe._BUF - 64} would "
              f"measure THIS module, not the game.", file=out)
        return 0
    print(f"first size that did NOT: {first_bad} bytes", file=out)
    print(f"  {reason}", file=out)
    print(f"\nso the ceiling lies in ({last_ok}, {first_bad}]. Chunk any reply below "
          f"{last_ok} bytes.", file=out)
    return 0


def _archive_dir() -> Path | None:
    m = _paths.mods()
    return None if m is None else m / "_reports"


def _dump_sha(path: str | None) -> str | None:
    """sha8 of the DUMP PAYLOAD in uidata.xml, or None if there isn't one.

    Identity is the payload, not the surrounding file: the same engine dump inside two
    slightly different `uidata.xml` files is one piece of evidence, not two.

    Deliberately swallows the whole ladder -- this feeds an ADVISORY, and an advisory
    that raises would turn "I could not check whether you have a backup" into a failure
    of the command you actually ran.
    """
    try:
        p = Path(path) if path else _livedump.uidata_path()
        if p is None or not p.exists():
            return None
        raw = _livedump.extract_raw(p.read_text(encoding="utf-8", errors="replace"),
                                    _livedump.var_name())
    except Exception:  # silent-ok: advisory only; the real read reports its own errors
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def _archive_hint(path: str | None, out) -> None:
    """One line if this dump is not archived anywhere. Costs a directory listing.

    Exists because the ground truth WAS ALREADY LOST ONCE. The engine's resolved values
    lived only in `uidata.xml`; the probe was removed, X4 rewrote the file on exit, and
    the fixture for the F72 traversals went with it -- leaving four example values that
    survived only because they had been quoted into a document. **A file the GAME owns
    is not storage.**
    """
    d, sha = _archive_dir(), _dump_sha(path)
    if d is None or sha is None:
        return
    if d.is_dir() and any(d.glob(f"livedump-*-{sha}.uidata.xml")):
        return
    print(f"\nnote: this dump ({sha}) is not archived. X4 OVERWRITES uidata.xml on exit "
          f"-- `x4live archive` keeps it.", file=out)


def cmd_archive(path: str | None, out_dir: str | None = None, out=None) -> int:
    """Copy the dump OUT of `uidata.xml`, which the game owns and overwrites.

    Not a convenience. The engine's resolved values are the only ground truth we have
    for what our merged tree *should* say, they cost a play session to produce, and they
    live in a file X4 rewrites on every exit. One has already been lost that way, which
    is what stalled the F72 traversal work.

    ARCHIVES THE WHOLE FILE, BYTE-FOR-BYTE, rather than the extracted payload. Two
    reasons, and the second is the real one: `x4live --file <archive>` then replays it
    directly with no special case, and **a copy that transforms nothing cannot have a
    transformation bug.** Storing the decoded payload would mean re-applying three
    escaping layers to read it back, which is exactly the code most likely to be wrong.

    Content-addressed on the payload, so re-archiving the same dump is a no-op rather
    than a second copy -- an archive full of near-duplicates is one nobody can quote
    from with confidence.
    """
    out = out or sys.stdout
    d = Path(out_dir) if out_dir else _archive_dir()
    if d is None:
        raise _livedump.LiveDumpUnavailable(
            "no archive directory: $X4_MODS is not configured, so there is nowhere to "
            "put this. Pass --out, or see --paths")

    src = Path(path) if path else _livedump.uidata_path()
    if src is None:
        raise _livedump.LiveDumpUnavailable(
            "the X4 profile is not configured - set $X4_PROFILE (see --paths)")

    # Parse BEFORE copying. Archiving a file we cannot decode would preserve bytes and
    # lose the only thing that makes them evidence -- and it would report success.
    dump = _load(path)
    sha = _dump_sha(path)
    if sha is None:
        raise _livedump.LiveDumpCorrupt(
            "the dump parsed but its raw payload could not be re-extracted -- refusing "
            "to archive something I cannot fingerprint")

    existing = sorted(d.glob(f"livedump-*-{sha}.uidata.xml")) if d.is_dir() else []
    if existing:
        print(f"already archived, same payload: {existing[0].name}", file=out)
        print(f"  {len(dump.rows)} rows, sha {sha}. Nothing written.", file=out)
        return 0

    data = src.read_bytes()
    if len(data) < 4096:
        raise _livedump.LiveDumpCorrupt(
            f"refusing to archive {len(data)} bytes -- a uidata.xml carrying a dump is "
            f"hundreds of kilobytes, so this is a truncated read, not a small answer")

    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = d / f"livedump-{stamp}-{sha}.uidata.xml"

    # WRITE ASIDE, VERIFY, THEN RENAME. A direct write that fails partway leaves a file
    # whose NAME already satisfies the content-address glob -- so the next run would say
    # "already archived" and the reminder would fall silent, both for a truncated file.
    # A partial artifact that cannot say what it is is neither present nor absent, and
    # it is worse than an absence because it reports success. `os.replace` is atomic on
    # Windows and POSIX alike, so the final name only ever appears on a verified file.
    tmp = dest.with_name(dest.name + ".partial")
    try:
        tmp.write_bytes(data)
        back = tmp.read_bytes()     # re-read: "N written" is intent, not the file's state
        if back != data:
            raise _livedump.LiveDumpCorrupt(
                f"wrote {len(data)} bytes to {tmp} but read back {len(back)} -- not archived")
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)  # never leave a .partial behind to be puzzled over

    print(f"archived: {dest}", file=out)
    print(f"  {len(dump.rows)} rows, {len(data)} bytes, payload sha {sha}", file=out)
    print(f"  byte-identical to the source, verified by re-read.", file=out)
    print(f"  replay it with:  x4live --file {dest} oracle", file=out)
    return 0


#: Macros to harvest ground truth for, stratified across the library types whose
#: DERIVED fields we cannot compute (F74's sibling gap, F72). Deliberately small and
#: FIXED rather than discovered: a harvest whose subject list changes between runs
#: cannot be diffed against an earlier one, and being able to diff two harvests is
#: the whole point of writing them to disk.
GROUND_TRUTH_MACROS: tuple[tuple[str, str], ...] = (
    ("shiptypes_s",  "ship_arg_s_scout_01_a_macro"),
    ("shiptypes_s",  "ship_gen_s_fighter_01_a_macro"),
    ("shiptypes_m",  "ship_arg_m_trans_container_01_a_macro"),
    ("shiptypes_l",  "ship_arg_l_destroyer_01_a_macro"),
    ("shiptypes_xl", "ship_arg_xl_carrier_01_a_macro"),
    ("weapons_lasers",  "weapon_gen_s_laser_01_mk1_macro"),
    ("weapons_turrets", "turret_arg_m_laser_01_mk1_macro"),
    ("enginetypes",     "engine_arg_s_travel_01_mk2_macro"),
    ("shieldgentypes",  "shield_arg_s_standard_01_mk1_macro"),
    ("thrustertypes",   "thruster_gen_s_allround_01_mk1_macro"),
    # missiletypes, 2026-08-29. ⚠ MY FIRST THREE NAMES WERE INVENTED -- plausible
    # shapes, none of which exist. They would have returned three ABSENT rows reading
    # as "missiletypes exposes nothing for missiles": a confident negative manufactured
    # by a typo, in the very feature added to avoid guessing. Caught by the mod session
    # before the run. Every name below is MEASURED present in the effective store.
    #
    # Three NAMESPACES differ and we do not know which one `missiletypes` keys on, so
    # the first two are the same missile in both forms -- the run itself answers it.
    ("missiletypes", "missile_gen_s_dumbfire_01_mk1"),        # ware-id form
    ("missiletypes", "missile_gen_s_dumbfire_01_mk1_macro"),  # macro form
    # One per question, and the last two CONTRAST deliberately.
    ("missiletypes", "missile_gen_s_emp_01_mk1_macro"),     # speed: the 100,887 m/s one
    ("missiletypes", "missile_gen_s_swarm_01_mk1_macro"),   # salvo: amount=8, warhead 210
    ("missiletypes", "missile_gen_l_torpedo_01_mk1_macro"), # targetable=1, hull 300
    ("missiletypes", "missile_gen_s_guided_01_mk1_macro"),  # OMITS targetable, hull 1
)


def cmd_groundtruth(pipe: str | None, timeout: float, out_file: str | None = None,
                    out=None, with_ramp: bool = False) -> int:
    """Harvest the engine's DERIVED values live, and write them down.

    THE PROBLEM THIS SOLVES. Our store records a macro's `<connection>` refs; the
    engine follows them and reports a SUM (`storagecapacity`, `docks_*`, `shield`,
    weapon `dps`). We cannot compute those yet (F72), and a derived aggregate is
    exactly where a merge error hides *without any single attribute being wrong* --
    so the engine's answers are the fixture any future traversal must reproduce.

    Those answers previously came from a uidata dump, and one was LOST to a game
    restart, which stalled the work. This gets them over the live pipe instead: no
    probe mod, no `uidata.xml`, nothing the game can overwrite -- and it writes them
    to `dev/_reports/` immediately, in the same breath.

    ⚠ IT RECORDS, IT DOES NOT COMPARE. Several of these fields have MORE THAN ONE
    defensible definition and nothing offline distinguishes them. On
    `ship_arg_xl_carrier_01_a_macro`, `docks_s` could be 8 (dockingbays reached
    through one dockarea), 18 (plus 10 launch tubes, which carry `dock.allow=0`), or
    78 (plus a 70-berth ship storage). Writing a traversal now would be picking one
    of those and calling it modelled. The harvest is what turns that guess into a
    lookup.
    """
    out = out or sys.stdout
    from . import _livepipe

    dest = Path(out_file) if out_file else None
    if dest is None:
        d = _archive_dir()
        if d is None:
            raise _livedump.LiveDumpUnavailable(
                "no output directory: $X4_MODS is not configured. Pass --out, or see "
                "--paths")
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"groundtruth-{datetime.datetime.now():%Y%m%d-%H%M%S}.tsv"

    fields = sorted(_DERIVED)
    rows: list[tuple[str, str, str, str]] = []
    asked = absent = errored = 0

    with _live_open(pipe, timeout) as lp:
        path = lp.path
        # ⚠ CORRECTED 2026-08-29. This comment previously asserted, in the grammar of
        # a verified fact -- "MEASURED against the live game" -- that the lua client
        # does NOT reconnect after our server closes the pipe, and that re-arming
        # needs a `/reloadui`. THAT WAS FALSE, and instructively so: it was written
        # at 16:22, ten minutes AFTER the deferred re-arm was deployed at 16:12:40,
        # but the game session it measured had LAUNCHED BEFORE that deploy. So it
        # measured the OLD lua and recorded the result as a current fact. A
        # measurement is only about the version that was actually running.
        #
        # The mod DOES reconnect, proven by the engine's own log: 18 sentinel/re-arm
        # cycles in one session (elapsed 2.02 -> 573.16), plus two `groundtruth` runs
        # 24s apart, each opening its own pipe, both 22,733 bytes.
        #
        # So the single-connection shape below is no longer REQUIRED. It is kept
        # because it is still the right shape for a different reason: the game only
        # executes while it is in the foreground, so one connection means the user
        # alt-tabs ONCE per harvest instead of once per query.
        if with_ramp:
            _ramp_over(lp, out)
            print("", file=out)
        print(f"harvesting over {path}", file=out)
        print(f"{len(GROUND_TRUTH_MACROS)} macros x ({len(fields)} derived + 1 all-fields)\n",
              file=out)
        for ltype, macro in GROUND_TRUTH_MACROS:
            got = 0
            # ONE all-fields call first, recorded under the field name "*". This is what
            # answers "does the engine expose <x> for this type AT ALL" -- a question the
            # per-field loop below structurally cannot answer, because it only asks about
            # names we already thought of, and an ABSENT for a name we never sent is
            # indistinguishable from a field that does not exist.
            #
            # Kept ALONGSIDE the per-field calls, not instead of them: this is the largest
            # single payload the channel will carry and therefore the likeliest to hit the
            # unmeasured truncation cap (F74). If it truncates we detect it and still have
            # the small per-field answers.
            asked += 1
            try:
                rv = lp.ask("macro", ltype, macro)
                if rv.status == "OK":
                    rows.append((ltype, macro, "*", rv.payload))
                elif rv.status == "ABSENT":
                    absent += 1
                else:
                    rows.append((ltype, macro, "*", f"!ERR {rv.payload}"))
                    errored += 1
            except _livepipe.LiveQueryDegraded as exc:
                rows.append((ltype, macro, "*", f"!DEGRADED {exc}"))
                errored += 1

            for f in fields:
                asked += 1
                try:
                    r = lp.ask("macro", ltype, macro, f)
                except _livepipe.LiveQueryDegraded as exc:
                    # A degraded reply is a NON-ANSWER about this cell, and it is
                    # recorded as one. Dropping it would leave a gap indistinguishable
                    # from "the engine has no such field".
                    rows.append((ltype, macro, f, f"!DEGRADED {exc}"))
                    errored += 1
                    continue
                if r.status == "OK":
                    rows.append((ltype, macro, f, r.payload))
                    got += 1
                elif r.status == "ABSENT":
                    absent += 1          # a real answer: the engine has no such field here
                else:
                    rows.append((ltype, macro, f, f"!ERR {r.payload}"))
                    errored += 1
            print(f"  {macro:<44} {got:>2}/{len(fields)} present", file=out)

    # Every cell is accounted for: present + absent + errored == asked. An unexplained
    # remainder means the harvest lost rows, and a fixture that quietly lost rows is
    # worse than no fixture -- it would read as "the engine does not report that".
    present = len(rows) - errored
    if present + absent + errored != asked:
        raise _livedump.LiveDumpCorrupt(
            f"harvest does not account for every cell: {present} present + {absent} "
            f"absent + {errored} errored != {asked} asked")

    header = ["# x4live groundtruth -- ENGINE values for fields our store cannot compute",
              "# RECORDED, NOT COMPARED. Several fields have more than one defensible",
              "# definition; this file is what decides between them.",
              f"# asked={asked} present={present} absent={absent} errored={errored}",
              "librarytype\tmacro\tfield\tengine_value"]
    # Values can contain TABS and NEWLINES -- a description does, and the "*"
    # all-fields row is itself tab-joined. Unescaped, those break the row
    # structure: MEASURED on the 08-29 fixture, 4 of 104 lines are unparseable
    # for exactly this reason. Same defect as `harvest` had, second location.
    def _gesc(x: str) -> str:
        return (x.replace(chr(92), chr(92) * 2)
                 .replace(chr(9), chr(92) + "t")
                 .replace(chr(10), chr(92) + "n"))
    body = "\n".join("\t".join(_gesc(x) for x in r) for r in rows)
    data = ("\n".join(header) + "\n" + body + "\n").encode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    back = dest.read_bytes()          # re-read: "N written" is intent, not state
    if back != data:
        raise _livedump.LiveDumpCorrupt(f"wrote {len(data)} bytes to {dest}, read back "
                                        f"{len(back)}")

    print(f"\nwrote {dest}", file=out)
    print(f"  {present} value(s) from {len(GROUND_TRUTH_MACROS)} macros; "
          f"{absent} field(s) absent (a real answer), {errored} errored", file=out)
    if present == 0:
        # Nothing harvested is a NON-ANSWER about the engine, not a finding about it.
        print("\nNOTHING was harvested. This does not say the engine reports no "
              "derived values - it says the harvest did not work.", file=out)
        return 2
    return 0




#: Every distinct field literal vanilla passes to `GetComponentData`, MEASURED
#: 2026-08-30 over 887 call-site lines in `ui/addons`: **182 names**. The mod itself
#: reads 16 of them.
#:
#: WHY THIS LIST EXISTS AT ALL. `GetComponentData` accepts ARBITRARY names, so the
#: engine's real vocabulary is unbounded and unknowable from outside. That makes an
#: absent answer ambiguous in the worst way: "the engine has no such field" and "nobody
#: ever asked" look identical. Vanilla's own usage is the one denominator available, and
#: it is a real one -- these are names the engine demonstrably answers for SOMETHING.
#:
#: Cross-checked on extraction: all 16 fields the mod already reads appear in this set.
#: An extraction that could not reproduce a total it did not choose is a rumour.
COMPONENT_FIELDS: tuple[str, ...] = (
    "agenticon", "aicommand", "aicommandaction", "aicommandactionparam",
    "aicommandactionraw", "aicommandparam", "aicommandstack", "aipilot",
    "allresources", "assignedaipilot", "assigneddock", "assignedpilot",
    "assignment", "assignmentname", "availableproducts", "basename", "basestation",
    "blacklistgroup", "boardingresistance", "boardingstrength", "buildcomponents",
    "buildingprocessor", "buildstorage", "canbeclaimed", "canbuildships",
    "canequipships", "canhavetradeoffers", "caninitiatecomm", "cansupplyships",
    "cargo", "classid", "cluster", "clusterid", "combinedskill", "container",
    "containsthewave", "countermeasurecapacity", "currentyield",
    "datavaultunlockstate", "deployablecapacity", "description", "destination",
    "destinationsector", "discounts", "engineer", "entrygate", "fleetname",
    "formation", "hasanymod", "hasavailablemarines", "hasshipdockingbays",
    "hasturret", "haswaveprotectionmodule", "height", "hiringdiscounts", "hull",
    "hullmax", "hullpercent", "icon", "idcode", "image", "individualtrainee",
    "intermediatewares", "isactive", "isally", "isattachedaslimpet", "iscapturable",
    "iscovered", "isdatavault", "isdefencestation",
    "isdefendingfromboardingoperation", "isdeployable", "isdock", "isdocked",
    "isdockedinternally", "isdocking", "isdockingenabled", "isenemy",
    "isequipmentdock", "isfemale", "isfleetlead", "isfriend", "isfunctional",
    "ishacked", "ishostile", "isinliveview", "isinnormalspace",
    "isinternallystored", "isknown", "islandmark", "ismasstraffic",
    "ismissingresources", "ismissionactor", "ismissiontarget", "ismodule",
    "isnpcassignmentrestricted", "isonlineobject", "isorphaned", "ispausedmanually",
    "isplayerowned", "isradarvisible", "isreallyenemy", "isreallyplayerowned",
    "issellable", "isshipyard", "isshowroommodule", "issuperhighway",
    "issupplyship", "istradestation", "isunit", "iswharf", "iswreck", "length",
    "macro", "maxradarrange", "missilecapacity", "moddingdiscounts", "modulesets",
    "money", "name", "npcfacecutscenekey", "numdockingbays", "numlocks",
    "numlockslots", "numtrips", "occupationname", "owner", "ownericon", "ownername",
    "ownershortname", "paintmodlocked", "pilot", "policefaction",
    "populationworkforcefactor", "postname", "poststring", "prestigename",
    "primarypurpose", "productionmoney", "products", "pureresources",
    "rawdescription", "rawname", "realclassid", "recyclingcomponents",
    "recyclingwares", "repairdiscounts", "resourcebuffer", "resourcedetectionrange",
    "revealpercent", "rolename", "scrapbuffer", "sector", "sectorid", "shield",
    "shieldmax", "shieldpercent", "shipstoragecapacity", "shiptrader", "shiptype",
    "shiptypename", "size", "skills", "subordinategroup", "sunlight", "systemid",
    "tradenpc", "tradercommissions", "traderdiscounts", "tradesubscription",
    "tradewares", "typeicon", "typename", "typestring", "uirelation",
    "venturetransactionid", "ventureuserid", "wantedmoney", "wares", "width",
    "workforcebonus", "zoneid",
)


def _harvest_ask(lp, rows, counts, section, key, verb, *args):
    """One question, one accounted row. Never drops a cell.

    A DEGRADED or errored reply is RECORDED, not skipped: a gap in the fixture would be
    indistinguishable from "the engine has nothing here", which is the exact ambiguity
    this harvest exists to remove.
    """
    from . import _livepipe

    counts["asked"] += 1
    try:
        r = lp.ask(verb, *args)
    except _livepipe.LiveQueryDegraded as exc:
        rows.append((section, key, f"!DEGRADED {exc}"))
        counts["errored"] += 1
        return None
    if r.status == "OK":
        rows.append((section, key, r.payload))
        # AN OK REPLY IS NOT AN ANSWER. MEASURED in game 2026-08-30: a field the
        # engine has never heard of returns status OK with the value `nil`
        # (`component <id> __no_such_field_zq` -> "__no_such_field_zq=nil"). Counting
        # those as present made "182/182 answered" true about the PROTOCOL and empty
        # about the ENGINE. A nil IS a real answer -- the engine has nothing here --
        # so it belongs in absent, which is where the denominator becomes honest.
        if r.payload.endswith("=nil") or r.payload == "nil":
            counts["absent"] += 1
        else:
            counts["present"] += 1
        return r
    if r.status == "ABSENT":
        counts["absent"] += 1          # a real answer: the engine has nothing here
        return None
    rows.append((section, key, f"!ERR {r.payload}"))
    counts["errored"] += 1
    return None


def cmd_harvest(pipe: str | None, timeout: float, out_file: str | None = None,
                out=None, faction: str = "argon") -> int:
    """Ask the running engine EVERYTHING we can think to ask, in ONE connection.

    WHY ONE COMMAND RATHER THAN A SESSION OF THEM. X4 executes only while it is in the
    FOREGROUND, so every separate query costs the user an alt-tab. One connection means
    they click in once. That is not a micro-optimisation: incremental probing is what
    turns a five-minute answer into an evening.

    WHY ENUMERATIONS RATHER THAN A QUESTION LIST. A list of questions can only return
    what somebody already thought to ask, and this channel's whole history is capability
    found by guessing a name out of vanilla. `globals` enumerates what the engine
    actually injected; the field sweep asks all 182 names vanilla uses rather than the 16
    we happen to read. Both can surprise us; a question list cannot.

    IT RECORDS, IT DOES NOT CONCLUDE. Nothing is built on these answers here. The output
    is a dated fixture, and every count carries its own denominator so a later reader can
    tell an ABSENCE from a NON-ANSWER.
    """
    out = out or sys.stdout
    from . import _livepipe

    dest = Path(out_file) if out_file else None
    if dest is None:
        d = _archive_dir()
        if d is None:
            raise _livedump.LiveDumpUnavailable(
                "no output directory: $X4_MODS is not configured. Pass --out, or see "
                "--paths")
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"harvest-{datetime.datetime.now():%Y%m%d-%H%M%S}.tsv"

    rows: list[tuple[str, str, str]] = []
    counts = {"asked": 0, "present": 0, "absent": 0, "errored": 0}

    with _live_open(pipe, timeout) as lp:
        print(f"harvesting over {lp.path}\n", file=out)

        # 1. BUILD GATE. If the game is not running the file on disk, nothing after
        #    this describes the code we think we are measuring.
        r = _harvest_ask(lp, rows, counts, "probe", "probe", "probe")
        build = "?"
        if r is not None:
            for f in r.fields:
                if f.startswith("build="):
                    build = f.split("=", 1)[1]
        print(f"  probe        build={build}", file=out)

        # 2. The galaxy primitives -- existence, the two undocumented booleans, and
        #    whether GetSectors is knowledge-limited.
        r = _harvest_ask(lp, rows, counts, "galaxyprobe", "galaxyprobe", "galaxyprobe")
        if r is not None and r.fields:
            h = dict(kv.split("=", 1) for kv in r.fields[0].split(" ") if "=" in kv)
            print(f"  galaxyprobe  sectors={h.get('sectors.total','?')} "
                  f"clusters(true/false)={h.get('clusters.arg_true','?')}/"
                  f"{h.get('clusters.arg_false','?')} "
                  f"isknown t/f/?={h.get('sectors.isknown_true','?')}/"
                  f"{h.get('sectors.isknown_false','?')}/"
                  f"{h.get('sectors.isknown_undecidable','?')}", file=out)

        # 3. The _G inventory, every page. Paged because the reply cap is hard: an
        #    over-long message tears the pipe down rather than arriving short.
        page, pages, ngl = 1, 1, 0
        while page <= pages and page <= 40:
            r = _harvest_ask(lp, rows, counts, "globals", f"page{page}",
                             "globals", "-", str(page))
            if r is None or not r.fields:
                break
            h = dict(kv.split("=", 1) for kv in r.fields[0].split(" ") if "=" in kv)
            pages = int(h.get("pages", 1))
            ngl = int(h.get("matched", 0))
            page += 1
        print(f"  globals      {ngl} name(s) over {pages} page(s)", file=out)

        # 4. Who and where we are. The sector token is per-session and must be read
        #    fresh: MEASURED, it changes every launch.
        ship_id = sector = None
        r = _harvest_ask(lp, rows, counts, "player", "player", "player")
        if r is not None:
            for f in r.fields:
                if f.startswith("occupiedship="):
                    ship_id = f.split("=", 1)[1]
                elif f.startswith("sectorid="):
                    sector = f.split("=", 1)[1]
        print(f"  player       ship={ship_id} sector={sector!r}", file=out)

        # 5. A complete galaxy-wide station census. Doubles as the end-to-end proof
        #    that the channel still works at this build, and supplies a STATION id --
        #    a different class from the player's ship, which is the point.
        station_id = None
        r = _harvest_ask(lp, rows, counts, "stations", faction, "stations", faction)
        if r is not None and len(r.fields) > 1:
            station_id = r.fields[1].split("|")[0]
            h = dict(kv.split("=", 1) for kv in r.fields[0].split(" ") if "=" in kv)
            print(f"  stations     shown={h.get('shown','?')} "
                  f"matched={h.get('matched','?')} CAPPED={h.get('CAPPED','?')}", file=out)

        # 6. THE FIELD SWEEP. 182 names against one object of each class, because a
        #    field name does not mean the same thing -- or exist -- for every class.
        for label, oid in (("ship", ship_id), ("station", station_id)):
            if oid is None:
                rows.append((f"fields.{label}", "*", "!SKIPPED no id of this class"))
                print(f"  fields.{label:<7} SKIPPED (no id)", file=out)
                continue
            got = 0
            for name in COMPONENT_FIELDS:
                r = _harvest_ask(lp, rows, counts, f"fields.{label}", name,
                                 "component", oid, name)
                # Count REAL VALUES, not replies. Printing "182/182 answered" over
                # a total that says absent=78 is one report contradicting itself in
                # two channels, which is worse than either number alone.
                if r is not None and not r.payload.endswith("=nil"):
                    got += 1
            print(f"  fields.{label:<7} {got}/{len(COMPONENT_FIELDS)} with a REAL "
                  f"value ({len(COMPONENT_FIELDS) - got} nil)", file=out)

        # 7. A per-object flag census in the player's own sector.
        if sector:
            r = _harvest_ask(lp, rows, counts, "objects", sector, "objects", sector)
            if r is not None and r.fields:
                h = dict(kv.split("=", 1) for kv in r.fields[0].split(" ") if "=" in kv)
                print(f"  objects      shown={h.get('shown','?')} "
                      f"matched={h.get('matched','?')}", file=out)

    # Every cell accounted for. An unexplained remainder means the harvest LOST rows,
    # and a fixture that quietly lost rows is worse than no fixture: it reads as "the
    # engine does not report that".
    tot = counts["present"] + counts["absent"] + counts["errored"]
    if tot != counts["asked"]:
        raise _livedump.LiveDumpCorrupt(
            f"harvest does not account for every cell: {counts['present']} present + "
            f"{counts['absent']} absent + {counts['errored']} errored != "
            f"{counts['asked']} asked")

    header = [
        "# x4live harvest -- what the RUNNING engine will answer, enumerated not guessed",
        "# RECORDED, NOT CONCLUDED. Nothing is built on these answers here.",
        f"# build={build} faction={faction} fields={len(COMPONENT_FIELDS)}",
        f"# asked={counts['asked']} present={counts['present']} "
        f"absent={counts['absent']} errored={counts['errored']}",
        "section\tkey\tvalue",
    ]
    # Tabs inside a payload are ROW separators (station rows, globals pages) and
    # names contain spaces, so collapsing them to spaces made the FIRST fixture's
    # census unparseable -- 93 station rows became one unsplittable blob. Escape
    # instead of destroy: the file stays 3-column and a reader splits the value
    # back on the escape.
    def _esc(x: str) -> str:
        return (x.replace(chr(92), chr(92) * 2)
                 .replace(chr(9), chr(92) + "t")
                 .replace(chr(10), chr(92) + "n"))
    body = "\n".join("\t".join(_esc(x) for x in r) for r in rows)
    data = ("\n".join(header) + "\n" + body + "\n").encode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    if dest.read_bytes() != data:          # re-read: "N written" is intent, not state
        raise _livedump.LiveDumpCorrupt(f"harvest did not land intact at {dest}")

    print(f"\nwrote {dest}", file=out)
    print(f"  asked={counts['asked']} present={counts['present']} "
          f"absent={counts['absent']} errored={counts['errored']}", file=out)
    if counts["present"] == 0:
        # Nothing harvested is a NON-ANSWER about the engine, not a finding about it.
        print("\nNOTHING was harvested. That does not say the engine answers nothing "
              "- it says the harvest did not work.", file=out)
        return 2
    return 0


@_paths.refuses_unconfigured
def main(argv: list[str] | None = None) -> int:
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # silent-ok: console encoding shim. Changes how output LOOKS, never
        # what was examined.

    p = argparse.ArgumentParser(
        prog="x4live",
        description="Read what the running engine saw, out of the profile's "
                    "uidata.xml, and diff it against our model.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--file", help="read this uidata.xml instead of the profile's")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("dump", help="what the probe captured, with its denominators")

    pe = sub.add_parser("extensions",
                        help="the engine's extension list, diffed PER ITEM")
    pe.add_argument("--scope", choices=("active", "installed"), default="active",
                    help="which registry population to compare against "
                         "(active = what the engine would load; default)")

    pr = sub.add_parser("errors", help="the engine's own error log, as captured")
    pr.add_argument("--limit", type=int, default=25)

    po = sub.add_parser("oracle",
                        help="engine-resolved macro values vs the effective store")
    po.add_argument("--show-derived", action="store_true",
                    help="list the engine-DERIVED values our store cannot produce "
                         "(F72), recorded as ground truth rather than compared")
    po.add_argument(
        "--from-groundtruth", dest="from_groundtruth",
        help="compare against a `x4live groundtruth` .tsv instead of a uidata dump. "
             "Without it the oracle needs the probe mod deployed and the game closed, "
             "which is why it was unrunnable")

    pa = sub.add_parser("archive",
                        help="copy the dump OUT of uidata.xml, which X4 OVERWRITES "
                             "on exit (ground truth has been lost this way once)")
    pa.add_argument("--out", help="archive directory (default: $X4_MODS/_reports)")

    pmap = sub.add_parser(
        "mappings",
        help="DERIVE candidate field mappings from a dump or a groundtruth "
             "TSV (proposals only - never auto-applied)")
    pmap.add_argument(
        "--from-groundtruth", dest="from_groundtruth",
        help="read a `x4live groundtruth` .tsv instead of a uidata dump. That "
             "file carries the SAME (librarytype, macro, field, value) data and "
             "is produced over the live pipe, so it needs no probe mod and no "
             "closed game -- which is why this option exists at all")

    # ---- the LIVE half. Everything above reads uidata.xml, which is 61 bytes
    # while the game runs; these two need the game RUNNING and the live-query mod
    # deployed. READ-ONLY vocabulary, no write verbs.
    pq = sub.add_parser("query",
                        help="ask the RUNNING engine one question over the pipe")
    pq.add_argument(
        "verb",
        help="ping | probe | containerprobe | echo | errors | ext | macro | player | "
             "component | objects | stations | ships | compare. "
             "START WITH `probe`: it reports build= (is the game running the file on "
             "disk) and loaded_at= (when this chunk last ran -- a UI reload empties the "
             "id allowlist, and both alt-enter and loading a save cause one, while the "
             "build stays the same). "
             "TWO TOKEN KINDS, never interconverted: an OBJECT id looks like "
             "`33556742ULL`, a SECTOR token looks like `ID: 7479` (quote it -- it "
             "contains a space) and comes from `player`. Sector tokens are NOT stable "
             "across launches; never save one. "
             "`objects <sector|-> [ship|station|all] [faction] [--hidden] [--wide]` is "
             "the enumeration core; `stations`/`ships <faction> [sector]` are wrappers "
             "over it. Rows are id|class|name|owner|sector|x,y,z|flags where flags is "
             "k=known d=docked m=masstraffic u=unit w=wreck e=enemy and a trailing v "
             "for vanilla's isObjectValid verdict (? = undecidable). "
             "NOT A CENSUS: ownerless objects are invisible to any owner query, hidden "
             "factions need --hidden, and ~93%% of rows are Unknown because names are "
             "player-knowledge -- ids, positions and flags are still exact. "
             "`compare <faction> <sector>` runs the container and --wide paths in ONE "
             "call and diffs them per id; two separate queries cannot be compared "
             "because the population drifts by tens of objects a minute")
    # REMAINDER, not "*": the game-side vocabulary has its own flags (--wide, --hidden)
    # and argparse would claim them as unknown OPTIONS, failing the command before it
    # ever reached the pipe. MEASURED 2026-08-30: `objects ... --wide` died at the CLI
    # with "unrecognized arguments", which looks exactly like an empty in-game result if
    # you only read the reply body. Everything after the verb is now passed through
    # verbatim -- so x4live's own options (--pipe, --timeout) must precede the verb.
    pq.add_argument("args", nargs=argparse.REMAINDER,
                    help="arguments for the verb, passed through verbatim (including "
                         "game-side flags like --wide and --hidden). Put --pipe and "
                         "--timeout BEFORE the verb")
    pq.add_argument("--pipe", help="pipe name (default: $X4_LIVE_PIPE or built-in)")
    pq.add_argument("--timeout", type=float, default=10.0,
                    help="seconds to wait for the game, and for each reply")

    ph = sub.add_parser(
        "harvest",
        help="ask the RUNNING engine EVERYTHING we can think to ask, in ONE "
             "connection, and write it down")
    ph.add_argument("--pipe")
    ph.add_argument("--timeout", type=float, default=10.0)
    ph.add_argument("--out",
                    help="output .tsv (default: $X4_MODS/_reports/harvest-*.tsv)")
    ph.add_argument("--faction", default="argon",
                    help="faction for the station census, which also supplies a "
                         "STATION id for the field sweep (default: argon)")

    pg = sub.add_parser("groundtruth",
                        help="harvest the engine's DERIVED values live and WRITE THEM "
                             "DOWN (the fixture any future traversal must reproduce)")
    pg.add_argument("--pipe")
    pg.add_argument("--timeout", type=float, default=10.0)
    pg.add_argument("--out", help="output .tsv (default: $X4_MODS/_reports/groundtruth-*.tsv)")
    pg.add_argument("--with-ramp", action="store_true",
                    help="run the size ramp FIRST, in the SAME connection -- the lua "
                         "client does not reconnect after a disconnect, so a session's "
                         "whole budget is one connection")

    pm = sub.add_parser("ramp",
                        help="MEASURE the message-size cap. An over-long message does "
                             "NOT truncate -- it TEARS THE PIPE DOWN, costing the whole "
                             "connection (F74, corrected 2026-08-29). Bounded below at "
                             "64,000 bytes; the ceiling above that is unmeasured")
    pm.add_argument("--pipe")
    pm.add_argument("--timeout", type=float, default=10.0)

    args = p.parse_args(argv)
    try:
        if args.cmd == "dump":
            return cmd_dump(args.file)
        if args.cmd == "extensions":
            return cmd_extensions(args.file, args.scope)
        if args.cmd == "errors":
            return cmd_errors(args.file, args.limit)
        if args.cmd == "oracle":
            return cmd_oracle(args.file, show_derived=args.show_derived,
                              groundtruth=args.from_groundtruth)
        if args.cmd == "archive":
            return cmd_archive(args.file, args.out)
        if args.cmd == "query":
            return cmd_query(args.verb, args.args, args.pipe, args.timeout)
        if args.cmd == "harvest":
            return cmd_harvest(args.pipe, args.timeout, args.out,
                               faction=args.faction)
        if args.cmd == "groundtruth":
            return cmd_groundtruth(args.pipe, args.timeout, args.out,
                                   with_ramp=args.with_ramp)
        if args.cmd == "ramp":
            return cmd_ramp(args.pipe, args.timeout)
        return cmd_mappings(args.file, groundtruth=args.from_groundtruth)
    except _livedump.LiveDumpCorrupt as exc:
        # rc 3: something was there and cannot be trusted. NOT a clean result.
        print(f"error: {exc}", file=sys.stderr)
        print("this is a DEGRADED result, not a pass.", file=sys.stderr)
        return 3
    except _livedump.LiveDumpUnavailable as exc:
        # rc 2: the question was not answered.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # The live channel's own ladder, imported lazily so that a machine without
        # pywin32 can still run every offline subcommand above. Mapped to the SAME
        # two exit codes, because a caller must not have to know which half of the
        # oracle answered in order to read the result.
        from . import _livepipe

        if isinstance(exc, _livepipe.LiveQueryDegraded):
            print(f"error: {exc}", file=sys.stderr)
            print("this is a DEGRADED result, not a pass.", file=sys.stderr)
            return 3
        if isinstance(exc, _livepipe.LiveQueryUnavailable):
            print(f"error: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

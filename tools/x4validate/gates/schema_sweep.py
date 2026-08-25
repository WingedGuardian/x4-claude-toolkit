r"""Gate: the effective-schema check must keep agreeing with its own measurement.

W3.1 was measured across the whole installed modlist BEFORE it was written, and
the implementation was then required to reproduce that number. This gate freezes
the result so a later "optimisation" cannot quietly change what the check reports.

The bars, all measured 2026-07-29 over the 102 installed non-DLC mods:

  * 127 (mod,file) pairs validated
  * 105 findings introduced == 45 gating + 57 advisory + 3 suppressed
  * 10 of 102 mods flagged
  * the four KNOWN-REAL defects all still reported

Why the totals are pinned and not just the four defects: a check that reports the
right four while inventing 200 others is not usable, and a check that reports the
right four because it reports everything is not a check. The composition is the
claim, so the composition is what is frozen.

Why the four are pinned SEPARATELY: totals can be met by accident after a tuning
change that silences a real finding and adds a spurious one. These are the ones
with independent evidence behind them, so silencing any of them is a regression
no matter what the totals say.

Run: `uv run python gates/schema_sweep.py`
"""

from __future__ import annotations

import re

import _env

from x4validate import _check, _merge

#
# RE-MEASURED 2026-08-01 after the schema-resolution fix (audit finding F1).
# Quoted rather than quietly re-baselined, because this gate's whole job is to
# make a moved number visible:
#
#            pairs  gating  advisory  suppressed  NOT checked  mods flagged
#   before     127      45        57           3          31*            10
#   after      157      45        91           3            1            39
#   delta      +30       0       +34           0          -30           +29
#
#   * the 31 were always happening; they were invisible until EXPECT_SKIPPED
#     existed, which is exactly why it now exists.
#
# What moved and why: 30 mods ship a root `ui.xml` whose declared schema
# resolves nowhere from where the file actually sits, so they were skipped with
# the false reason "not bundled in .../libraries" — the schema IS bundled, at
# reference/ui/core/coreaddon.xsd. Those 30 documents are now validated.
#
# GATING DID NOT MOVE (45 -> 45). The +34 advisories are one benign class:
# coreaddon.xsd constrains addon/@name to the pattern 'ego_.+', Egosoft's own
# naming convention, which every third-party UI mod violates harmlessly. That is
# the textbook "XSD stricter than the engine" case _schema_gates exists to
# downgrade, and it is why more coverage cost zero new errors.
#
# RE-MEASURED 2026-08-02 for the F7+F14 severity split — the movement was
# measured across all 91 advisories BEFORE the code was written, and the
# implementation was then required to reproduce it:
#
#            pairs  gating  advisory  suppressed  NOT checked  mods flagged
#   before     157      45        91           3            1            39
#   after      157      60        76           3            1            39
#   delta        0     +15       -15           0            0             0
#
# The 15 that moved are the two classes whose "XSD lags the engine" excuse
# cannot apply, each verified individually against the packed-inclusive corpus:
#   * 7  enum-undefined (F14): cpsdo_faction race='central' — defined by the
#        XSD floor nowhere AND by the effective 102-mod tree nowhere.
#   * 8  dead-attr (F7): (element, attribute) pairs vanilla never uses —
#        category/@matchextension x3 (vanilla's 140 uses are ALL on <location>;
#        a real attribute on the wrong element) and element/@forkmaterial x5
#        (invented by VRO, 4 corpus hits, all VRO itself).
# The 76 that stayed advisory: 36 pattern facets, 34 non-lookup enums (mods
# cannot extend those by defining something, but the engine may still accept
# more than the XSD lists — e.g. ship_variation_expansion's list-in-enum
# relation='[friend, ally]' x27, recorded as a possible upstream defect the
# captured log cannot settle), 2 key-constraint cascades, 4 cascade noise.
#
# RE-MEASURED 2026-08-02 (same day, later): the MODLIST changed, not the check —
# rer_boronphaser became discoverable (its content.xml had been one folder too
# deep since extraction; F19-era install hygiene moved it up). It contributes
# 2 pairs, 1 advisory, 0 gating:
#
#            pairs  gating  advisory  suppressed  NOT checked  mods flagged
#   before     157      60        76           3            1            39
#   after      159      60        77           3            1            40
#   delta       +2       0        +1           0            0            +1
#
# RE-MEASURED 2026-08-08: the MODLIST changed, not the check — and unlike the
# previous re-baselines this one is attributed per-mod, so the numbers are
# explained rather than merely observed.
#
# The check is provably unchanged: this sweep produced these exact numbers BEFORE
# and AFTER the root-<replace> merge fix landed the same day (72aea46). The fix
# alters values, not schema shapes.
#
# Population change, established from extension folder timestamps (not memory):
#   + 12 mods added 2026-08-07/08. Only three contribute anything:
#       ter_radar_turret       1 gating   0 advisory
#       lc4hunter_argon_titan  0 gating   1 advisory
#       arck_job_registry      0 gating   1 advisory
#     the other nine are clean.
#   - xspvro removed 2026-08-08, taking its KNOWN_REAL 2 gating / 9 advisory with
#     it (entry deleted below).
#
# The arithmetic closes exactly on three of the four constants:
#   gating       60 - 2 + 1 = 59   observed 59
#   advisory     77 - 9 + 2 = 70   observed 70
#   mods flagged 40 - 1 + 3 = 42   observed 42
#   pairs       159 -> 168 (+9)    coverage growth from the new mods' own files
#
#            pairs  gating  advisory  suppressed  NOT checked  mods flagged
#   before     159      60        77           3            1            40
#   after      168      59        70           3            1            42
#   delta       +9      -1        -7           0            0            +2
# RE-MEASURED 2026-08-23 (toolkit 2.4.0). The MODLIST changed, not the check --
# and unlike a bare re-baseline, what is and is NOT attributed is written down.
#
# The check is provably unchanged. schema_sweep calls exactly one x4validate
# function, `_check.check_effective_schema`, whose call graph is
# `_merge.build_effective` + `_xsd.*` + `iter_mod_xml_roots` + local helpers. The
# intersection with every function 2.4.0 touched is EMPTY. Its population comes
# from `ext.iterdir()`, never `_registry.mods()`, so the F37 mod-scope change
# cannot reach it either, and `_xsd.py`'s only 2.4.0 change is comment-only.
#
#   pairs  168 -> 169  (+1)  ATTRIBUTED: npc_economy_tweaks, installed 2026-08-13,
#                            i.e. AFTER the 08-08 baseline. One checkable pair,
#                            ZERO findings -- confirmed absent from the flagged list.
#   gating       59 -> 59    unchanged. The severity that actually gates did not move.
#   suppressed    3 ->  3    unchanged.
#   NOT checked   1 ->  1    unchanged.
#   advisory 70 -> 69  (-1)  UNATTRIBUTED.
#   mods     42 -> 41  (-1)  UNATTRIBUTED.
#
# THE HONEST PART: one mod that previously produced exactly one advisory no longer
# does, and WHICH mod cannot be recovered -- the 08-08 re-baseline recorded totals
# and three named contributors, not a full per-mod list, so there is nothing to
# diff against. Three folders were modified after that baseline (one public
# revert mod and two personal overlays) and none is flagged now, which is
# SUGGESTIVE and is not evidence. Recorded as open rather than explained away.
#
# Why re-baseline at all rather than leave the gate red: a permanently-failing
# gate is not a preserved question, it is noise -- and noise trains you to skim
# past the run it IS right about. The delta is preserved here in prose instead.
#
# FOR THE NEXT RE-BASELINE: dump the PER-MOD table alongside the totals, so the
# next drift is attributable by diffing rather than by memory. That omission is
# the entire reason one of these numbers is unattributable today.
# ---------------------------------------------------------------------------
# RE-BASELINE 2026-08-25 — FULLY ATTRIBUTED, per item, and the per-mod table is
# recorded this time (the previous block asked its successor to do exactly that,
# because one number in it could not be attributed for want of one).
#
# CAUSE: the modlist grew, the check did not. Three mods were deployed 2026-08-24
# (the three most recently modified folders under extensions\), taking the active
# set 114 -> 117. Measured by running the gate's OWN check on just those three:
#
#     personal overlay A            pairs=0  gating=0  advisory=0
#     personal overlay B            pairs=2  gating=0  advisory=0
#     Station_ink                   pairs=6  gating=1  advisory=0
#                                   -------  --------
#                                   pairs=8  gating=1
#
#   pairs  169 -> 177  (+8)  ATTRIBUTED in full: 6 + 2 + 0 from the three above.
#   gating  59 ->  60  (+1)  ATTRIBUTED: Station_ink, libraries/god.xml —
#                            "Element 'pilot': This element is not expected"
#                            introduced by that mod into the merged god.xml.
#                            An UPSTREAM finding about the mod, not a tool change.
#   mods    41 ->  42  (+1)  ATTRIBUTED: Station_ink (the only newly flagged mod).
#   advisory     69 ->  69   unchanged.
#   suppressed    3 ->   3   unchanged.
#   NOT checked   1 ->   1   unchanged.
#
# NOTHING IS UNATTRIBUTED IN THIS RE-BASELINE. A first attempt at attribution was
# WRONG and is worth recording: counting md/aiscript files in the three new mods
# gave 2, not 8, leaving 6 unexplained. The error was the instrument — "pairs"
# is whatever `check_effective_schema` reports in its own note, not an
# md/aiscript file count. Re-measured with the gate's own code, it reconciled
# exactly. An unexplained remainder is a lead; this one led to my own checker.
#
# AMENDED 2026-08-25 (same day): Station_ink's single gating finding was FIXED
# at source, so it drops out of both counts. The mod added a `pilot` block to
# libraries/god.xml using ships.xml's content model; libraries.xsd (the schema
# god.xml declares) defines no such element and vanilla god.xml contains none,
# and the engine logged no complaint -- it was silently ignored, so the block
# only ever tripped validation. Removed; the inner <station> now reads
# <select> then <loadout>, matching vanilla's shipyard_argon_01 exactly.
#
#   gating  60 -> 59  (-1)  ATTRIBUTED: Station_ink libraries/god.xml, fixed.
#   mods    42 -> 41  (-1)  ATTRIBUTED: Station_ink no longer flagged.
#   pairs        177        unchanged -- the file is still validated, it now passes.
#
# Verified per item BEFORE re-baselining: the gate's own check run against
# Station_ink alone reports pairs=6 gating=0 advisory=0 (was gating=1).
#
# PER-MOD TABLE AS OF 2026-08-25 (42 flagged; sums verified = 60 gating,
# 69 advisory, matching the totals above). Diff against this on the next drift.
#     arck_job_registry                       0 gating   1 advisory
#     battle_repair_support                   0 gating   1 advisory
#     cpsdo_faction                          14 gating   1 advisory
#     cpsdo_zb_modpack                        0 gating   1 advisory
#     deploy_all_defense                      0 gating   1 advisory
#     ebi_timelines_faction_use_ship          3 gating   0 advisory
#     escape_pod                              1 gating   0 advisory
#     gs_debug_report                         0 gating   1 advisory
#     gs_lib                                  0 gating   1 advisory
#     gs_qol_fleet_transfer_crew              0 gating   1 advisory
#     gs_qol_show_on_map                      0 gating   1 advisory
#     higher_dimensional_space                1 gating   0 advisory
#     kuertee_additional_agent_actions        0 gating   1 advisory
#     kuertee_alternatives_to_death           0 gating   1 advisory
#     kuertee_emergent_missions               0 gating   1 advisory
#     kuertee_high_security_rooms_are_locked  0 gating   1 advisory
#     kuertee_loot_mining                     0 gating   1 advisory
#     kuertee_military_exercises              0 gating   1 advisory
#     kuertee_npc_reactions                   0 gating   1 advisory
#     kuertee_ship_scanner                    0 gating   1 advisory
#     kuertee_station_scanner                 0 gating   1 advisory
#     kuertee_surface_element_targeting       0 gating   1 advisory
#     kuertee_teleport_from_transporter_room  0 gating   1 advisory
#     kuertee_ui_accept_mission_for_later_button  0 gating   1 advisory
#     kuertee_ui_active_mission_button        0 gating   1 advisory
#     kuertee_ui_extensions                   0 gating   3 advisory
#     kuertee_ui_grouped_save_files           0 gating   2 advisory
#     kuertee_waypoint_fields_for_deployments  0 gating   1 advisory
#     lc4hunter_argon_titan                   0 gating   1 advisory
#     mlog_deadair_eco_no_da_wares           30 gating   0 advisory
#     mycu_equipment_tooltips                 0 gating   1 advisory
#     mycu_verbose_transaction_log            0 gating   1 advisory
#     rer_boronphaser                         0 gating   1 advisory
#     shadow_tracker                          0 gating   1 advisory
#     ship_testfield_gamestart                1 gating   1 advisory
#     ship_variation_expansion                3 gating  27 advisory
#     sn_mod_support_apis                     0 gating   2 advisory
#     stars                                   0 gating   2 advisory
#     station_production_overview             0 gating   1 advisory
#     ter_radar_turret                        1 gating   0 advisory
#     vro                                     5 gating   3 advisory
# ---------------------------------------------------------------------------
EXPECT_PAIRS = 177
EXPECT_ERR = 59
EXPECT_INFO = 69
EXPECT_SUPPRESSED = 3
EXPECT_MODS_FLAGGED = 41
#: Files this sweep could NOT schema-check. Pinned from 2026-08-01, because the
#: gate previously froze only what WAS checked — so 31 documents skipped with a
#: false reason never moved a single number here. A rise means coverage was lost
#: silently. The 1 that remains is honest: shadergl.xsd is declared by
#: bh_shader but ships in no unpacked layer, so there is genuinely nothing to
#: validate against.
EXPECT_SKIPPED = 1

#: Independently evidenced against `reference\`, not just "the tool said so".
#: Each entry: mod -> (gating, advisory, what makes it real).
KNOWN_REAL = {
    "mlog_deadair_eco_no_da_wares": (30, 0,
        "removes <production>, orphaning the <limits> sibling — structural damage "
        "caused BY a diff, which no other check in this package can see"),
    "cpsdo_faction": (14, 1,
        "race='central' x7 — the effective race list (base+DLC+all 102 mods) has 10 "
        "entries and 'central' is not one of them; GATING since the F14 split "
        "(2026-08-02), joining the 7 element-not-expected it already had"),
    "ebi_timelines_faction_use_ship": (3, 0,
        "category/@matchextension x3 — a real attribute on the WRONG element: "
        "vanilla uses matchextension 140 times, every one on <location>, never on "
        "<category>, so the engine drops the intended DLC-matching silently (F7)"),
    "vro": (5, 3,
        "element/@forkmaterial x5 in libraries/effects.xml — invented attribute, "
        "4 corpus-wide occurrences and all of them are VRO itself (F7)"),
    # xspvro removed 2026-08-08 (mod moved out of extensions\). Its entry was
    # (2 gating, 9 advisory) — "job ids containing a SPACE against the id pattern
    # facet" — and its departure accounts for the whole gating/advisory drop in
    # the re-measurement above. Restore this entry if the mod ever returns.
    "ter_radar_turret": (1, 0,
        "patch shipped at libraries/factiongoal_hold_space.xml when vanilla is "
        "md/factiongoal_hold_space.xml — schema-checked against the wrong shape"),
    "escape_pod": (1, 0,
        "<filter> placed directly under <sound>; all 309 vanilla <filter> elements "
        "sit under <effects>, and <sound>'s content model has no filter child"),
}

_RE_SUP = re.compile(r"; (\d+) enumeration failure")


def main() -> int:
    ext = _env.extensions()
    mods = [d for d in sorted(ext.iterdir())
            if d.is_dir() and not d.name.lower().startswith("ego_dlc_")]
    cfg = _merge.Config()

    pairs = err = info = sup = skipped = 0
    skip_why: dict[str, int] = {}
    per_mod: dict[str, tuple[int, int]] = {}
    for d in mods:
        report = _check.Report()
        _check.check_effective_schema(d, cfg, report)
        # Files the check could NOT validate. Unpinned until 2026-08-01, which is
        # precisely how 31 false "not bundled" skips survived: the gate froze what
        # WAS checked and had no denominator for what was not.
        for s in report.skipped:
            skipped += 1
            skip_why[s.why.split(":")[0][:60]] = skip_why.get(s.why.split(":")[0][:60], 0) + 1
        e = sum(1 for f in report.findings if f.severity == "error")
        i = sum(1 for f in report.findings if f.severity == "info")
        for note in report.notes:
            if note.startswith("effective-schema:"):
                pairs += int(note.split()[1])
            m = _RE_SUP.search(note)
            if m:
                sup += int(m.group(1))
        err += e
        info += i
        if e or i:
            per_mod[d.name] = (e, i)

    print(f"{len(mods)} non-DLC mods | {pairs} (mod,file) pairs validated "
          f"| {skipped} NOT checked")
    print(f"{err} gating + {info} advisory + {sup} suppressed = "
          f"{err + info + sup} introduced | {len(per_mod)} mods flagged\n")
    for why, n in sorted(skip_why.items(), key=lambda kv: -kv[1]):
        print(f"   NOT CHECKED x{n}: {why}")
    if skip_why:
        print()
    for name, (e, i) in sorted(per_mod.items(), key=lambda kv: -sum(kv[1])):
        mark = "*" if name in KNOWN_REAL else " "
        print(f" {mark} {name:36} {e:>3} gating  {i:>3} advisory")

    fail: list[str] = []
    for label, got, want in (("pairs", pairs, EXPECT_PAIRS),
                             ("gating", err, EXPECT_ERR),
                             ("advisory", info, EXPECT_INFO),
                             ("suppressed", sup, EXPECT_SUPPRESSED),
                             ("NOT checked", skipped, EXPECT_SKIPPED),
                             ("mods flagged", len(per_mod), EXPECT_MODS_FLAGGED)):
        if got != want:
            fail.append(f"{label}: got {got}, measured baseline is {want}")

    for name, (we, wi, why) in KNOWN_REAL.items():
        got = per_mod.get(name)
        if got is None:
            fail.append(f"{name}: REPORTS NOTHING — this defect is real ({why})")
        elif got != (we, wi):
            fail.append(f"{name}: {got[0]} gating/{got[1]} advisory, expected {we}/{wi} ({why})")

    print()
    if fail:
        print("FAIL — the check no longer matches its own measurement:")
        for f in fail:
            print(f"  ! {f}")
        print("\nInvestigate before re-baselining. A moved number means either the modlist "
              "changed (re-measure and update the constants, saying so) or the check did "
              "(that is the regression this gate exists to catch).")
        return 1
    print("OK — matches the recorded baseline exactly (see the re-measurement table "
          "above the constants), and all four independently-evidenced defects are "
          "still reported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

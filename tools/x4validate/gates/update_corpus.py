#!/usr/bin/env python
r"""Differential gate for `--update`: one mod carrying every documented 9.0 break.

`--update` was only ever smoke-tested — run, exits 0, looks fine. That proves
nothing about DETECTION, and a migration checker that silently detects nothing is
indistinguishable from a clean mod. The failure is invisible in exactly the case
it matters: a user ports a mod, sees no findings, and ships it broken.

So: build a corpus where every break is planted deliberately, and require each to
be found. Rules come from KNOWLEDGEBASE.md "Version Migration Map":

  Tier 1 (XSD, gating)  — `space=` required on the find_*/count_* family.
  Tier 2 (runtime grep) — Lua_Loader, kuertee_hud, `.keys.list.clone`.
  Tier 2 (exprlint)     — random(min,max), 'fmt'[…] missing dot, `in="{…}"`,
                          `.keys.list.count`.

Each case is planted TWICE — once loose, once inside a `.cat` — because the
packed half was a real, measured blind spot: `_migration.scan_mod` walked only
the loose tree, so `--update` scanned nothing at all on a packed mod and reported
a clean port (`sn_mod_support_apis`: 4 `Lua_Loader.Load` hits in `ext_01.cat`,
0 reported).

A CLEAN control mod is asserted too. A gate that only pins "the bad thing is
flagged" passes just as well against a checker that flags everything.

Run:  uv run python gates/update_corpus.py [--keep]
Exit: 0 every planted break detected and the control is clean, 1 otherwise.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402
from x4validate import _check, _merge  # noqa: E402

KEEP = "--keep" in sys.argv


@dataclass
class Case:
    """One planted break and the finding that must come back."""
    case_id: str
    vpath: str
    body: str
    #: substring that must appear in some finding's message
    wants: str
    #: category the finding must carry
    category: str


def _md(cue_body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<mdscript name="GateProbe" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="../libraries/md.xsd">\n'
        '  <cues>\n'
        '    <cue name="Probe">\n'
        '      <actions>\n'
        f'{cue_body}\n'
        '      </actions>\n'
        '    </cue>\n'
        '  </cues>\n'
        '</mdscript>\n'
    )


CASES: list[Case] = [
    # ---- Tier 1: XSD, the one class the KB calls a reliable migration signal --
    Case("space_required", "md/probe_space.xml",
         _md('        <find_station name="$s" '
             'multiple="true"/>'),
         wants="space", category="xsd"),

    # ---- Tier 2: runtime grep (_migration) ---------------------------------
    Case("lua_loader", "md/probe_lua.xml",
         _md('        <raise_lua_event name="\'Lua_Loader.Load\'" '
             'param="\'ui/x.lua\'"/>'),
         wants="Lua_Loader", category="migration"),
    Case("keys_list_clone", "md/probe_clone.xml",
         _md('        <set_value name="$k" exact="$tbl.keys.list.clone"/>'),
         wants=".keys.list", category="migration"),
    Case("kuertee_hud", "md/probe_hud.xml",
         _md('        <set_value name="$m" exact="\'kuertee_hud\'"/>'),
         wants="kuertee_hud", category="migration"),

    # ---- Tier 2: expression grammar (_exprlint) ----------------------------
    Case("random_call", "md/probe_random.xml",
         _md('        <set_value name="$p" exact="$list.{random(1, $list.count)}"/>'),
         wants="random", category="exprlint"),
    Case("fmt_missing_dot", "md/probe_fmt.xml",
         _md('        <set_value name="$t" exact="\'%s bottles\'[$n]"/>'),
         wants="'.'", category="exprlint"),
    Case("list_literal_braces", "md/probe_list.xml",
         _md('        <do_for_each name="$i" in="{class.production, class.buildmodule}"/>'),
         wants="[...]", category="exprlint"),
    Case("keys_list_count", "md/probe_count.xml",
         _md('        <set_value name="$n" exact="$tbl.keys.list.count"/>'),
         wants=".keys.count", category="exprlint"),
]

#: A file with none of the above. Uses the CORRECT 9.0 form of each construct,
#: so it also proves the rules are not matching the fix as well as the break.
CLEAN = _md(
    '        <find_station name="$s" space="player.galaxy" multiple="true"/>\n'
    '        <set_value name="$k" exact="$tbl.keys.list"/>\n'
    '        <set_value name="$n" exact="$tbl.keys.count"/>\n'
    '        <set_value name="$p" exact="$list.random"/>\n'
    '        <set_value name="$t" exact="\'%s bottles\'.[$n]"/>\n'
    '        <do_for_each name="$i" in="[class.production, class.buildmodule]"/>'
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_cat(mod_dir: Path, members: list[tuple[str, bytes]]) -> None:
    """Pack *members* into ext_01.cat/.dat — the real documented format."""
    mod_dir.mkdir(parents=True, exist_ok=True)
    lines, blob = [], bytearray()
    for vpath, data in members:
        lines.append(f"{vpath} {len(data)} 1700000000 {hashlib.md5(data).hexdigest()}")
        blob += data
    (mod_dir / "ext_01.cat").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (mod_dir / "ext_01.dat").write_bytes(bytes(blob))


def build(tmp: Path) -> tuple[Path, Path, Path]:
    loose = tmp / "gate_update_loose"
    _write(loose / "content.xml", '<content id="gate_update_loose" version="100"/>')
    for c in CASES:
        _write(loose / c.vpath, c.body)

    packed = tmp / "gate_update_packed"
    _write(packed / "content.xml", '<content id="gate_update_packed" version="100"/>')
    _write_cat(packed, [(c.vpath, c.body.encode()) for c in CASES])

    control = tmp / "gate_update_clean"
    _write(control / "content.xml", '<content id="gate_update_clean" version="100"/>')
    _write(control / "md/probe_clean.xml", CLEAN)
    return loose, packed, control


def findings_for(mod: Path) -> list[tuple[str, str]]:
    """(category, message) for every finding `--update` produces on *mod*."""
    report = _check.validate(mod, _merge.Config(), update=True)
    return [(f.category, f.message) for f in report.findings]


def check(label: str, mod: Path, failures: list[str]) -> None:
    found = findings_for(mod)
    print(f"\n{label}  ({len(found)} findings)")
    for c in CASES:
        hit = [m for cat, m in found if cat == c.category and c.wants in m]
        # An xsd finding may be categorized strict/advisory; accept either, since
        # this gate is about DETECTION, not about which bucket it lands in.
        if not hit and c.category == "xsd":
            hit = [m for cat, m in found if cat.startswith("xsd") and c.wants in m]
        mark = "  ok " if hit else " MISS"
        print(f"  {mark}  {c.case_id:<22} [{c.category}] wants {c.wants!r}")
        if not hit:
            failures.append(f"{label}: {c.case_id} NOT DETECTED "
                            f"(category={c.category}, wants={c.wants!r})")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="x4gate_update_"))
    failures: list[str] = []
    try:
        loose, packed, control = build(tmp)
        print("=" * 88)
        print(f"UPDATE CORPUS GATE — {len(CASES)} planted 9.0 breaks, loose + packed + control")
        print("=" * 88)

        check("LOOSE  mod", loose, failures)
        check("PACKED mod (inside ext_01.cat)", packed, failures)

        ctrl = findings_for(control)
        noisy = [(c, m) for c, m in ctrl
                 if c in {"migration", "exprlint"} or c.startswith("xsd")]
        print(f"\nCLEAN control  ({len(ctrl)} findings, "
              f"{len(noisy)} in migration/exprlint/xsd)")
        for c, m in noisy:
            print(f"   FALSE POSITIVE  [{c}] {m[:100]}")
            failures.append(f"clean control flagged [{c}]: {m[:100]}")
        if not noisy:
            print("   ok  the correct 9.0 forms are not flagged")

        print("\n" + "=" * 88)
        if failures:
            print(f"FAILURES: {len(failures)}")
            for f in failures:
                print(f"  - {f}")
            return 1
        print(f"All {len(CASES)} breaks detected loose AND packed; control clean.")
        return 0
    finally:
        if KEEP:
            print(f"\ncorpus kept at {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

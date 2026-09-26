"""EXHAUSTIVE x4similar audit — every reported pair recomputed independently.

x4similar's output had NEVER been verified for truth (only monotonicity and
no-crash). For each pair the tool reports at the default 0.85 threshold, this:
  1. locates BOTH macros itself (fresh scan of reference + DLC + mods, loose and
     packed — not the tool's own scanner),
  2. re-extracts the stat vector with its own flattener -- from the EFFECTIVE
     (merged) document, since x4similar scores patched ships at their patched
     values (AUDIT-2026-09-24 AN-6). The merge engine is shared (it is tested on its
     own); locating the definition, choosing the layers, flattening and scoring are
     not,
  3. recomputes the documented score (1 - weighted mean relative diff, weights
     from the module head, class+purpose hard scope, >=4 shared keys),
  4. asserts the recomputed score clears the threshold and class/purpose match.
Also verifies the printed percentage matches the recomputed score within 1%.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402
from lxml import etree

from x4validate import _cat, _loadorder, _merge, _registry

REF = _env.reference()
EXT = _env.extensions()
THRESHOLD = 0.85

WEIGHTS = {
    "hull.max": 2.0, "people.capacity": 1.5, "storage.missile": 0.5,
    "storage.unit": 1.0, "rotationspeed.max": 0.75,
    "rotationacceleration.max": 0.5, "secrecy.level": 0.25,
}

# ---- independent extraction --------------------------------------------------

def all_ship_macros() -> dict[tuple, dict]:
    """{(macro_name, source): {class, purpose, stats}} — own scan, loose + packed.

    Keyed by SOURCE too: the first version collapsed by name and kept whichever
    copy scanned first, so it compared an lc4hunter original (hull 307,500)
    where the tool had compared VRO's rebalance (hull 950,000) — accusing the
    tool of a wrong score that was actually my wrong copy.
    """
    out: dict[tuple, dict] = {}

    def eat(root, source, base, vpath):
        for m in root.iter("macro"):
            name, klass = m.get("name"), (m.get("class") or "")
            if not name or not klass.startswith("ship_"):
                continue
            props = m.find("properties")
            if props is None:
                continue
            purpose = ""
            stats: dict[str, float] = {}
            for el in props:
                if not isinstance(el.tag, str):
                    continue
                for k, v in el.attrib.items():
                    key = f"{el.tag}.{k}"
                    if el.tag == "purpose" and k == "primary":
                        purpose = v
                    try:
                        stats[key] = float(v)
                    except ValueError:
                        pass  # silent-ok: non-numeric attr is not a stat; the
                        # tool's own vectors carry numerics only
            out.setdefault((name.lower(), source), {"class": klass, "purpose": purpose,
                                                    "stats": stats, "root": base,
                                                    "vpath": vpath})

    roots = [("base", REF)]
    if (REF / "extensions").is_dir():
        roots += [(f"dlc:{d.name}", d)
                  for d in (REF / "extensions").iterdir() if d.is_dir()]
    # A DLC installed in the GAME tree (the packed mini-DLC are only ever there,
    # never unpacked into reference\) must carry the same `dlc:` label the tool
    # uses, or the (name, source) lookup below misses and the pair is scored
    # UNRESOLVED. This scan already read them via _cat — the labels just did not
    # agree, which is a verifier bug, not a tool bug. Keep the independent scan;
    # only the naming is shared.
    roots += [(f"dlc:{d.name}" if d.name.lower().startswith("ego_dlc_") else d.name, d)
              for d in sorted(EXT.iterdir()) if d.is_dir()]
    for source, base in roots:
        for f in base.rglob("*_macro.xml"):
            try:
                eat(etree.parse(str(f)).getroot(), source, base,
                    f.relative_to(base).as_posix())
            except (etree.XMLSyntaxError, OSError):
                continue  # silent-ok: an unreadable macro shrinks MY scan, and any
                # pair the tool reports from it then counts as UNRESOLVED (which
                # fails the gate) — the miss cannot hide
        try:
            for v, mem in _cat.mod_vfs(base, packed_only=True).items():  # packed-ok: loose rglob above
                if v.lower().endswith("_macro.xml"):
                    try:
                        eat(etree.fromstring(_cat.read_member(mem)), source, base, v)
                    except (etree.XMLSyntaxError, OSError, ValueError):
                        continue  # silent-ok: same as above — surfaces as UNRESOLVED
        except OSError:
            continue  # silent-ok: mod with no readable catalog; same UNRESOLVED backstop
    return out


# ---- the EFFECTIVE values of a located definition -----------------------------

#: The engine's layers, chosen HERE rather than borrowed from x4similar: every
#: ACTIVE mod in load order. `build_effective` skips an overlay that does not ship the
#: file and applies a nested mod-on-mod patch itself, so no touch map is needed.
_ACTIVE = _registry.mods("active", [EXT])
_ACTIVE_ORDER = [Path(m["path"]) for f in _loadorder.compute_load_order(_ACTIVE)
                 for m in _ACTIVE if m["folder"] == f]
_ACTIVE_NAMES = {p.name.lower() for p in _ACTIVE_ORDER}
_MERGED: dict[tuple, dict | None] = {}


def effective(entry: dict, name: str) -> dict | None:
    """*entry* with its stats re-read from the merged document, or None if the merge
    yields no such macro (counted UNRESOLVED by the caller, never excused)."""
    base, vpath = entry["root"], entry["vpath"]
    if base == REF:
        mvpath, overlays = vpath, _ACTIVE_ORDER
    elif base.name.lower().startswith("ego_dlc_"):
        mvpath, overlays = f"extensions/{base.name}/{vpath}", _ACTIVE_ORDER
    elif base.name.lower() in _ACTIVE_NAMES:
        mvpath, overlays = vpath, _ACTIVE_ORDER
    else:
        mvpath, overlays = vpath, [base]      # disabled: scored as it would be alone
    key = (mvpath.lower(), tuple(overlays))
    if key not in _MERGED:
        try:
            tree = _merge.build_effective(mvpath, _merge.Config(),
                                          extra_overlays=overlays).tree
        except (etree.XMLSyntaxError, OSError):
            tree = None  # silent-ok: the pair is then UNRESOLVED, which fails the gate
        found: dict = {}
        if tree is not None:
            probe: dict = {}
            _eat_into(tree, probe)
            found = probe
        _MERGED[key] = found
    return _MERGED[key].get(name)


def _eat_into(root, out: dict) -> None:
    """Same flattening rule as `all_ship_macros.eat`, keyed by lowercased name."""
    for m in root.iter("macro"):
        name, klass = m.get("name"), (m.get("class") or "")
        if not name or not klass.startswith("ship_"):
            continue
        props = m.find("properties")
        if props is None:
            continue
        purpose = ""
        stats: dict[str, float] = {}
        for el in props:
            if not isinstance(el.tag, str):
                continue
            for k, v in el.attrib.items():
                if el.tag == "purpose" and k == "primary":
                    purpose = v
                try:
                    stats[f"{el.tag}.{k}"] = float(v)
                except ValueError:
                    pass  # silent-ok: a non-numeric attr is not a stat
        out.setdefault(name.lower(), {"class": klass, "purpose": purpose, "stats": stats})


def score(a: dict, b: dict, keys: list[str]) -> float | None:
    if a["class"] != b["class"] or a["purpose"] != b["purpose"]:
        return None
    tw = td = 0.0
    for k in keys:
        if k not in a["stats"] or k not in b["stats"]:
            return None
        w = WEIGHTS.get(k, 1.0)
        va, vb = a["stats"][k], b["stats"][k]
        denom = max(abs(va), abs(vb), 1e-9)
        td += w * min(abs(va - vb) / denom, 1.0)
        tw += w
    return 1.0 - td / tw if tw else None


# ---- parse the tool's report -------------------------------------------------

ROW = re.compile(r"^\s*(\d+)%\s+\(\d+ stats compared\)\s+(\S+)\s+\[([^\]]+)\]\s+<->\s+(\S+)\s+\[([^\]]+)\]")
DET = re.compile(r"^\s*class=(\S+)\s+purpose=(\S+)\s+compared=(\S+)")

proc = subprocess.run(["uv", "run", "x4similar", "--threshold", str(THRESHOLD)],
                      capture_output=True, text=True, encoding="utf-8",
                      errors="replace", timeout=1800)
lines = (proc.stdout or "").splitlines()
# THE TOOL'S EXIT CODE IS EVIDENCE. Before 2026-09-24 a crashed or refusing
# x4similar printed nothing, 0 pairs parsed, and the audit exited 0
# (AUDIT-2026-09-24 GT-3). 0 = pairs reported, anything else is not a report.
if proc.returncode != 0:
    print(f"REFUSING: x4similar exited {proc.returncode}, so there is no report to "
          "audit:", file=sys.stderr)
    print((proc.stderr or proc.stdout or "").strip()[-600:], file=sys.stderr)
    sys.exit(2)

pairs = []
for i, ln in enumerate(lines):
    m = ROW.match(ln)
    if m and i + 1 < len(lines):
        d = DET.match(lines[i + 1])
        if d:
            pairs.append((int(m.group(1)),
                          (m.group(2).lower(), m.group(3)),
                          (m.group(4).lower(), m.group(5)),
                          d.group(1), d.group(2), d.group(3).split(",")))
print(f"pairs reported by the tool: {len(pairs)}")

ships = all_ship_macros()
print(f"ship macros found by independent scan: {len(ships)}")

checked = bad = unresolved = 0
samples = []
for pct, akey, bkey, klass, purpose, keys in pairs:
    an, bn = akey[0], bkey[0]
    a, b = ships.get(akey), ships.get(bkey)
    a = effective(a, an) if a is not None else None
    b = effective(b, bn) if b is not None else None
    if a is None or b is None:
        unresolved += 1
        continue
    checked += 1
    problems = []
    if a["class"] != klass or b["class"] != klass:
        problems.append(f"class mismatch ({a['class']}/{b['class']} vs {klass})")
    if a["purpose"] != purpose or b["purpose"] != purpose:
        problems.append(f"purpose mismatch ({a['purpose']}/{b['purpose']} vs {purpose})")
    s = score(a, b, keys)
    if s is None:
        problems.append("pair not comparable on the tool's own compared keys")
    else:
        if s < THRESHOLD - 1e-9:
            problems.append(f"recomputed score {s:.3f} below threshold {THRESHOLD}")
        if abs(s * 100 - pct) > 1.0:
            problems.append(f"printed {pct}% vs recomputed {s * 100:.1f}%")
    if len(keys) < 4:
        problems.append(f"only {len(keys)} compared keys (<4 documented minimum)")
    if problems:
        bad += 1
        if len(samples) < 6:
            samples.append(f"{an} <-> {bn}: " + "; ".join(problems))

print(f"pairs verified       : {checked}")
if not checked and not bad and not unresolved:
    # A FLOOR: zero pairs parsed is a report that could not be read (a changed row
    # format parses to nothing), not a tool with no defects.
    sys.exit(_env.nothing_checked("similar_audit", "no x4similar pair was parsed"))
print(f"VIOLATIONS           : {bad}")
for s in samples:
    print(f"   {s}")
print(f"unresolved (macro not found by my scan — counted, not excused): {unresolved}")
sys.exit(1 if bad or unresolved else 0)

"""EXHAUSTIVE x4similar audit — every reported pair recomputed independently.

x4similar's output had NEVER been verified for truth (only monotonicity and
no-crash). For each pair the tool reports at the default 0.85 threshold, this:
  1. locates BOTH macros itself (fresh scan of reference + DLC + mods, loose and
     packed — not the tool's own scanner),
  2. re-extracts the stat vector with its own flattener,
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

from x4validate import _cat, _merge

REF = _env.reference()
EXT = _env.extensions()
THRESHOLD = 0.85

WEIGHTS = {
    "hull.max": 2.0, "people.capacity": 1.5, "storage.missile": 0.5,
    "storage.unit": 1.0, "cargo.max": 1.5, "rotationspeed.max": 0.75,
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

    def eat(root, source):
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
                                                    "stats": stats})

    roots = [("base", REF)]
    if (REF / "extensions").is_dir():
        roots += [(f"dlc:{d.name}", d)
                  for d in (REF / "extensions").iterdir() if d.is_dir()]
    roots += [(d.name, d) for d in sorted(EXT.iterdir()) if d.is_dir()]
    for source, base in roots:
        for f in base.rglob("*_macro.xml"):
            try:
                eat(etree.parse(str(f)).getroot(), source)
            except (etree.XMLSyntaxError, OSError):
                continue  # silent-ok: an unreadable macro shrinks MY scan, and any
                # pair the tool reports from it then counts as UNRESOLVED (which
                # fails the gate) — the miss cannot hide
        try:
            for v, mem in _cat.mod_vfs(base).items():
                if v.lower().endswith("_macro.xml"):
                    try:
                        eat(etree.fromstring(_cat.read_member(mem)), source)
                    except (etree.XMLSyntaxError, OSError, ValueError):
                        continue  # silent-ok: same as above — surfaces as UNRESOLVED
        except OSError:
            continue  # silent-ok: mod with no readable catalog; same UNRESOLVED backstop
    return out


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
print(f"VIOLATIONS           : {bad}")
for s in samples:
    print(f"   {s}")
print(f"unresolved (macro not found by my scan — counted, not excused): {unresolved}")
sys.exit(1 if bad or unresolved else 0)

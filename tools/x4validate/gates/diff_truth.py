"""x4diff change-list verification against PLANTED ground truth on real content.

Identity/antisymmetry/sensitivity are already gated; what was never verified is
the per-attribute change LIST on real mod content. So: copy a real installed
mod, mutate N numeric attributes chosen by a seeded RNG (recording exactly
which), and require `x4diff --detail` to report exactly that set — every planted
change found, nothing invented.
"""
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402
from lxml import etree

EXT = _env.extensions()
N_MUTATIONS = 30
SEED = 20260809

# a loose mod with plenty of XML attr surface, discovered not named
candidates = [d for d in sorted(EXT.iterdir())
              if d.is_dir() and not d.name.lower().startswith("ego_dlc_")
              and len(list(d.rglob("*.xml"))) >= 5]
src = max(candidates, key=lambda d: len(list(d.rglob("*.xml"))))
print(f"source mod: {src.name} ({len(list(src.rglob('*.xml')))} xml files)")

tmp = Path(tempfile.mkdtemp(prefix="x4diff_truth_"))
a, b = tmp / "old", tmp / "new"
shutil.copytree(src, a)
shutil.copytree(src, b)

# collect mutable numeric attributes in the copy
rng = random.Random(SEED)
slots = []                                # (file, xpath-ish id, attr, old)
for f in sorted(b.rglob("*.xml")):
    try:
        tree = etree.parse(str(f))
    except (etree.XMLSyntaxError, OSError):
        continue  # silent-ok: choosing mutation SLOTS from readable files only;
        # unreadable files are simply not mutated, so nothing planted is lost
    for el in tree.getroot().iter():
        if not isinstance(el.tag, str):
            continue
        for k, v in el.attrib.items():
            # NEVER mutate identity attributes. Changing `id`/`name`/`ref`
            # changes which element it IS — a diff keyed on identity correctly
            # reports that as structure (remove+add), not a value edit. The
            # first run planted 3 `id` mutations and then accused the tool of
            # missing them and over-counting; the harness was wrong, not x4diff.
            if k.lower() in {"id", "name", "ref", "macro", "connection"}:
                continue
            try:
                float(v)
            except ValueError:
                continue  # silent-ok: non-numeric attr is just not a mutation slot
            slots.append((f, el, k, v, tree))

if len(slots) < N_MUTATIONS:
    print(f"only {len(slots)} numeric slots; reducing mutations")
chosen = rng.sample(slots, min(N_MUTATIONS, len(slots)))

planted = set()                           # (relpath, attr, old, new)
by_tree = {}
for f, el, k, old, tree in chosen:
    new = str(float(old) + 7331.5)        # unmistakable, never a no-op
    el.set(k, new)
    rel = f.relative_to(b).as_posix()
    planted.add((rel, k, old, new))
    by_tree[str(f)] = tree
for path, tree in by_tree.items():
    tree.write(path, encoding="utf-8", xml_declaration=True)
print(f"planted mutations: {len(planted)} across {len(by_tree)} file(s)")

out = subprocess.run(["uv", "run", "x4diff", str(a), str(b), "--detail"],
                     capture_output=True, text=True, encoding="utf-8",
                     errors="replace", timeout=1800).stdout or ""

# headline counts
m = re.search(r"changed files:\s*(\d+)\s+added:\s*(\d+)\s+removed:\s*(\d+)", out)
n = re.search(r"total attr changes:\s*(\d+)", out)
print(f"tool headline: changed={m.group(1)} added={m.group(2)} removed={m.group(3)} "
      f"attr_changes={n.group(1)}")

ok = True
if int(m.group(2)) or int(m.group(3)):
    print("FAIL: files added/removed where only attrs were mutated")
    ok = False
if int(m.group(1)) != len(by_tree):
    print(f"NOTE: changed files {m.group(1)} vs mutated files {len(by_tree)}")

# every planted (attr old->new) must appear in the detail; count detail rows
found = 0
missing = []
for rel, k, old, new in sorted(planted):
    # detail rows carry attr and values; accept any whitespace/arrow format
    pat = re.compile(re.escape(k) + r"[^\n]*" + re.escape(old) + r"[^\n]*" + re.escape(new))
    if pat.search(out):
        found += 1
    else:
        missing.append((rel, k, old, new))
print(f"planted changes found in --detail: {found}/{len(planted)}")
for rel, k, old, new in missing[:5]:
    print(f"   MISSING {rel} {k}: {old} -> {new}")
if missing:
    ok = False
if int(n.group(1)) != len(planted):
    print(f"FAIL: tool counts {n.group(1)} attr changes, planted {len(planted)} "
          f"(invented or merged rows)")
    ok = False

shutil.rmtree(tmp, ignore_errors=True)
print("RESULT:", "exact" if ok else "MISMATCH")
sys.exit(0 if ok else 1)

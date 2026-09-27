"""x4diff change-list verification against PLANTED ground truth on real content.

Identity/antisymmetry/sensitivity are already gated; what was never verified is
the per-attribute change LIST on real mod content. So: copy a real installed
mod, mutate N numeric attributes chosen by a seeded RNG (recording exactly
which), and require `x4diff --detail` to report exactly that set — every planted
change found, nothing invented.

"Exact" needs something planted (AUDIT-2026-09-24 GT-6): a source mod with no
numeric attribute slot used to plant 0 mutations and print `RESULT: exact`, and a
changed-files count that disagreed with the files actually mutated was only a NOTE.
Both are now verdicts.

Run:  uv run python gates/diff_truth.py
Exit: 0 exact -- every planted change found, nothing invented, and the changed-
        files count equals the files mutated
      1 MISMATCH (or x4diff's output could not be read)
      2 nothing could be planted -- no candidate mod, or 0 numeric slots
"""
import collections
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402
from lxml import etree  # noqa: E402

N_MUTATIONS = 30
SEED = 20260809


def pick_source(ext: Path) -> Path | None:
    """A loose mod with plenty of XML attr surface, discovered not named."""
    candidates = [d for d in sorted(ext.iterdir())
                  if d.is_dir() and not d.name.lower().startswith("ego_dlc_")
                  and len(list(d.rglob("*.xml"))) >= 5]
    if not candidates:
        return None
    return max(candidates, key=lambda d: len(list(d.rglob("*.xml"))))


def plant(b: Path, rng: random.Random) -> tuple[list, dict]:
    """Mutate up to N numeric attributes under *b*. (planted rows, {path: tree}).

    The planted rows are a LIST -- a multiset. Two sibling elements carrying the same
    attr and value produce IDENTICAL (rel, attr, old, new) rows; a set collapsed them,
    and the count check then went red against a tool that correctly reported both
    (release review 2026-09-26)."""
    slots = []                                # (file, element, attr, old, tree)
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

    planted = []                              # (relpath, attr, old, new), repeats kept
    by_tree = {}
    for f, el, k, old, tree in chosen:
        new = str(float(old) + 7331.5)        # unmistakable, never a no-op
        el.set(k, new)
        rel = f.relative_to(b).as_posix()
        planted.append((rel, k, old, new))
        by_tree[str(f)] = tree
    for path, tree in by_tree.items():
        tree.write(path, encoding="utf-8", xml_declaration=True)
    return planted, by_tree


def judge(out: str, planted, files_mutated: int) -> bool:
    """Compare x4diff's --detail output against the planted rows (a multiset: an
    identical row planted twice must appear twice). True = exact."""
    m = re.search(r"changed files:\s*(\d+)\s+added:\s*(\d+)\s+removed:\s*(\d+)", out)
    n = re.search(r"total attr changes:\s*(\d+)", out)
    if m is None or n is None:
        tail = (out.strip().splitlines() or ["<no output>"])[-1]
        print(f"FAIL: x4diff printed no headline counts -- cannot compare. Last line: {tail[:120]}")
        return False
    print(f"tool headline: changed={m.group(1)} added={m.group(2)} removed={m.group(3)} "
          f"attr_changes={n.group(1)}")

    ok = True
    if int(m.group(2)) or int(m.group(3)):
        print("FAIL: files added/removed where only attrs were mutated")
        ok = False
    if int(m.group(1)) != files_mutated:
        # A verdict, not a NOTE: a tool reporting a different number of changed files
        # than were changed is either inventing or merging files.
        print(f"FAIL: changed files {m.group(1)} vs mutated files {files_mutated}")
        ok = False

    # every planted (attr old->new) must appear in the detail AS OFTEN AS IT WAS PLANTED;
    # the detail is matched per LINE, so two identical rows need two matching lines.
    found = 0
    missing = []
    need = collections.Counter((k, old, new) for _rel, k, old, new in planted)
    lines = out.splitlines()
    for (k, old, new), times in sorted(need.items()):
        # detail rows carry attr and values; accept any whitespace/arrow format
        pat = re.compile(re.escape(k) + r".*" + re.escape(old) + r".*" + re.escape(new))
        hits = sum(1 for ln in lines if pat.search(ln))
        found += min(hits, times)
        missing += [row for row in planted if row[1:] == (k, old, new)][:max(0, times - hits)]
    print(f"planted changes found in --detail: {found}/{len(planted)}")
    for rel, k, old, new in missing[:5]:
        print(f"   MISSING {rel} {k}: {old} -> {new}")
    if missing:
        ok = False
    if int(n.group(1)) != len(planted):
        print(f"FAIL: tool counts {n.group(1)} attr changes, planted {len(planted)} "
              f"(invented or merged rows)")
        ok = False
    return ok


def run_x4diff(a: Path, b: Path) -> str:
    return subprocess.run(["uv", "run", "x4diff", str(a), str(b), "--detail"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=1800).stdout or ""


def main() -> int:
    src = pick_source(_env.extensions())
    if src is None:
        return _env.nothing_checked("diff_truth", "no installed non-DLC mod with >= 5 XML "
                                    "files to copy and mutate")
    print(f"source mod: {src.name} ({len(list(src.rglob('*.xml')))} xml files)")

    tmp = Path(tempfile.mkdtemp(prefix="x4diff_truth_"))
    try:
        a, b = tmp / "old", tmp / "new"
        shutil.copytree(src, a)
        shutil.copytree(src, b)
        planted, by_tree = plant(b, random.Random(SEED))
        print(f"planted mutations: {len(planted)} across {len(by_tree)} file(s)")
        if not planted:
            # 0 planted and 0 found is not "exact" -- it is a comparison that never ran.
            return _env.nothing_checked("diff_truth", f"{src.name} has no numeric "
                                        "attribute slot to mutate")
        ok = judge(run_x4diff(a, b), planted, len(by_tree))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("RESULT:", "exact" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

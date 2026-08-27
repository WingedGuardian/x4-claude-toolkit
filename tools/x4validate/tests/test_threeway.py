"""Three-way diff: separate the author's edits from upstream drift.

A two-way diff between an ARCHIVED mod and the CURRENT tree cannot answer the
question anyone actually has -- *which of these changes did the author make?* --
and it fails in a direction that invites damage.

MEASURED by a parallel session on a real 2021 mod, 135 documents:

    two-way (archived vs current)   ~440 attribute deltas
    three-way (vs the 4.04 base)      15 author edits
                                     340 upstream drift
    124 of 135 documents were VERBATIM copies of the baseline

So **96% of what a two-way diff calls "the port" is someone else's work.** Acting
on the two-way number would have re-applied 340 of the upstream author's changes
as if they were the user's, and reverted the current upstream release to 4.04
across 124 files.

⚠ The hard requirement, learned expensively (CLAUDE.md, "a ONE-SIDED ABSENCE in
an OLD document is upstream ADDITION, not author deletion"): 16 macros looked as
though the author had deleted `missile.targetable`; they had not -- upstream
added it after 2021. A two-way diff cannot tell those apart. A three-way CAN,
which is the entire point -- but only where a baseline exists for that document.
Where it does not, the answer is UNKNOWN and must say so, never "removed".
"""

from pathlib import Path

from x4validate import _threeway


def _mod(root: Path, name: str, wares: dict[str, dict[str, str]]) -> Path:
    """A minimal mod dir: libraries/wares.xml with the given id -> attrs."""
    d = root / name
    (d / "libraries").mkdir(parents=True)
    body = "".join(
        "<ware id=\"%s\" %s/>" % (wid, " ".join(f'{k}="{v}"' for k, v in attrs.items()))
        for wid, attrs in wares.items())
    (d / "libraries" / "wares.xml").write_text(
        f"<?xml version='1.0' encoding='utf-8'?><wares>{body}</wares>", encoding="utf-8")
    (d / "content.xml").write_text(
        f"<?xml version='1.0' encoding='utf-8'?><content id='{name}' version='100'/>",
        encoding="utf-8")
    return d


def test_an_author_edit_is_not_confused_with_upstream_drift(tmp_path):
    """The founding case: two changes, one each, must land in different buckets."""
    base = _mod(tmp_path, "base", {"ore": {"price": "100", "volume": "10"}})
    arch = _mod(tmp_path, "arch", {"ore": {"price": "555", "volume": "10"}})   # author moved price
    cur = _mod(tmp_path, "cur", {"ore": {"price": "100", "volume": "99"}})     # upstream moved volume

    r = _threeway.three_way(base, arch, cur)
    assert [c.attr for c in r.author_edits] == ["price"], r.author_edits
    assert [c.attr for c in r.upstream_drift] == ["volume"], r.upstream_drift
    assert r.both_moved == []


def test_a_both_moved_attribute_is_the_only_real_decision(tmp_path):
    """One conflict out of hundreds of deltas is a decision; the deltas are a wall."""
    base = _mod(tmp_path, "base", {"gun": {"damage": "5500"}})
    arch = _mod(tmp_path, "arch", {"gun": {"damage": "30500"}})   # author
    cur = _mod(tmp_path, "cur", {"gun": {"damage": "8500"}})      # upstream, since

    r = _threeway.three_way(base, arch, cur)
    assert len(r.both_moved) == 1
    c = r.both_moved[0]
    assert (c.base, c.archived, c.current) == ("5500", "30500", "8500")
    assert r.author_edits == [] and r.upstream_drift == []


def test_the_same_change_on_both_sides_is_CONVERGED_not_a_conflict(tmp_path):
    base = _mod(tmp_path, "base", {"ore": {"price": "100"}})
    arch = _mod(tmp_path, "arch", {"ore": {"price": "200"}})
    cur = _mod(tmp_path, "cur", {"ore": {"price": "200"}})
    r = _threeway.three_way(base, arch, cur)
    assert len(r.converged) == 1 and r.both_moved == []


def test_an_attribute_UPSTREAM_ADDED_is_never_reported_as_an_author_deletion(tmp_path):
    """The 16-macro case. The archived file predates the attribute; nobody deleted it."""
    base = _mod(tmp_path, "base", {"msl": {"speed": "100"}})
    arch = _mod(tmp_path, "arch", {"msl": {"speed": "100"}})              # untouched
    cur = _mod(tmp_path, "cur", {"msl": {"speed": "100", "targetable": "1"}})

    r = _threeway.three_way(base, arch, cur)
    assert r.author_edits == [], "the author changed nothing here"
    assert [c.attr for c in r.upstream_drift] == ["targetable"]
    assert all("remov" not in c.kind for c in r.upstream_drift), \
        "an upstream ADDITION must never be rendered as a removal"


def test_a_document_with_no_baseline_is_UNKNOWN_and_is_counted(tmp_path):
    """The narrowing step: no baseline means the direction cannot be known."""
    base = _mod(tmp_path, "base", {"ore": {"price": "100"}})
    arch = _mod(tmp_path, "arch", {"ore": {"price": "100"}})
    cur = _mod(tmp_path, "cur", {"ore": {"price": "100"}})
    # a document the baseline never had
    (arch / "libraries" / "extra.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><things><t id='a' v='1'/></things>",
        encoding="utf-8")

    r = _threeway.three_way(base, arch, cur)
    assert any("extra.xml" in v for v in r.no_base), r.no_base
    assert r.author_edits == [], "an unclassifiable document must not leak into a verdict"


def test_verbatim_documents_are_reported_with_a_denominator(tmp_path):
    """124 of 135 verbatim is the headline; a bare list of changes hides it."""
    base = _mod(tmp_path, "base", {"ore": {"price": "100"}})
    arch = _mod(tmp_path, "arch", {"ore": {"price": "100"}})
    cur = _mod(tmp_path, "cur", {"ore": {"price": "100"}})
    r = _threeway.three_way(base, arch, cur)
    assert r.documents_compared >= 1
    assert r.verbatim == r.documents_compared - len(r.author_edited_docs)


def test_every_attribute_lands_in_exactly_one_bucket(tmp_path):
    """Buckets must SUM to the population, or the classification is a non-answer."""
    base = _mod(tmp_path, "base", {"a": {"p": "1", "q": "1", "r": "1", "s": "1"}})
    arch = _mod(tmp_path, "arch", {"a": {"p": "2", "q": "1", "r": "3", "s": "9"}})
    cur = _mod(tmp_path, "cur", {"a": {"p": "1", "q": "2", "r": "4", "s": "9"}})
    r = _threeway.three_way(base, arch, cur)
    total = (len(r.author_edits) + len(r.upstream_drift)
             + len(r.both_moved) + len(r.converged))
    assert total == r.attributes_classified, (
        f"buckets {total} != population {r.attributes_classified}")
    assert total == 4, "p author, q upstream, r both, s converged"


def test_a_document_the_ARCHIVE_never_had_produces_no_drift_rows(tmp_path):
    """The case that kills the mutant my first no-base test could not.

    A document the baseline and the CURRENT tree both have, but the archived mod
    does not, is outside the comparison entirely. Upstream changes to it are not
    "drift the author is behind on" -- the author never had the file. Without the
    exclusion those rows leak into `upstream_drift` and inflate the very number
    this tool exists to deflate.

    ⚠ Written after `excluded = set()` SURVIVED the first pass: the original
    no-base fixture asserted the right outcome for the wrong reason, because a
    document absent from the baseline cannot contribute attribute changes at all.
    Right answer, wrong mechanism -- the shape that makes a green meaningless.
    """
    base = _mod(tmp_path, "base", {"ore": {"price": "100"}})
    arch = _mod(tmp_path, "arch", {"ore": {"price": "100"}})
    cur = _mod(tmp_path, "cur", {"ore": {"price": "100"}})
    for d in (base, cur):
        (d / "libraries" / "only_upstream.xml").write_text(
            "<?xml version='1.0' encoding='utf-8'?><things><t id='a' v='%s'/></things>"
            % ("1" if d is base else "2"), encoding="utf-8")

    r = _threeway.three_way(base, arch, cur)
    assert any("only_upstream" in v for v in r.dropped_by_author), r.dropped_by_author
    assert not any("only_upstream" in c.vpath for c in r.upstream_drift), (
        "a document the archive never had must not generate drift rows")
    assert r.attributes_classified == 0


# --- reported from real use, 2026-08-27 ------------------------------------------
# The first outing of this tool on a real mod found two defects in it. Both are
# reproduced here before being fixed.

def _nested_mod(root: Path, name: str, target: str, wares: dict[str, dict[str, str]]) -> Path:
    """A mod that patches ANOTHER mod through the nested form (CLAUDE.md #6).

    `<mymod>/extensions/<target>/<mirrored path>` is how a personal overlay patches
    another mod -- the normal shape for exactly the porting job this tool is for.
    Every zzz_* overlay that touches VRO or a DLC looks like this.
    """
    d = root / name
    inner = d / "extensions" / target / "libraries"
    inner.mkdir(parents=True)
    body = "".join(
        '<ware id="%s" %s/>' % (w, " ".join(f'{k}="{v}"' for k, v in a.items()))
        for w, a in wares.items())
    (inner / "wares.xml").write_text(
        f"<?xml version='1.0' encoding='utf-8'?><wares>{body}</wares>", encoding="utf-8")
    (d / "content.xml").write_text(
        f"<?xml version='1.0' encoding='utf-8'?><content id='{name}' version='100'/>",
        encoding="utf-8")
    return d


def test_a_nested_overlay_is_compared_against_the_mod_it_patches(tmp_path):
    """MEASURED as broken on first real use: 0 documents compared.

    The archive's vpaths are `extensions/vro/assets/...` while the baseline's are
    `assets/...`, so nothing joined. The SAME logical file appeared in both
    exclusion lists at once -- NO BASELINE under the nested path and NOT IN THE
    ARCHIVE under the plain one -- which is the tell. Reported against a real mod
    where all four files of interest were excluded.
    """
    base = _mod(tmp_path, "vro", {"gun": {"damage": "5500"}})
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "8500"}})
    arch = _nested_mod(tmp_path, "myoverlay", "vro", {"gun": {"damage": "30500"}})

    r = _threeway.three_way(base, arch, cur)
    assert r.documents_compared == 1, (
        f"the nested overlay must be paired with the mod it patches; "
        f"no_base={r.no_base} dropped={r.dropped_by_author}")
    assert len(r.both_moved) == 1, r.both_moved
    c = r.both_moved[0]
    assert (c.base, c.archived, c.current) == ("5500", "30500", "8500")


def test_unwrapping_is_REPORTED_not_silent(tmp_path):
    """Rewriting a path is a transforming step, so it has to announce itself."""
    base = _mod(tmp_path, "vro", {"gun": {"damage": "5500"}})
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "8500"}})
    arch = _nested_mod(tmp_path, "myoverlay", "vro", {"gun": {"damage": "30500"}})
    r = _threeway.three_way(base, arch, cur)
    assert r.unwrapped, "a rewritten vpath must be stated, never applied silently"
    assert any("vro" in u for u in r.unwrapped)


def test_a_nested_path_aimed_at_a_DIFFERENT_mod_is_NOT_unwrapped(tmp_path):
    """Falsification twin: unwrapping everything would invent comparisons.

    A patch against some third mod is genuinely outside this comparison and must
    stay excluded -- otherwise the fix trades a false negative for a false positive.
    """
    base = _mod(tmp_path, "vro", {"gun": {"damage": "5500"}})
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "8500"}})
    arch = _nested_mod(tmp_path, "myoverlay", "someothermod", {"gun": {"damage": "30500"}})
    r = _threeway.three_way(base, arch, cur)
    assert r.documents_compared == 0
    assert r.unwrapped == [], "nothing should have been unwrapped"
    assert any("someothermod" in v for v in r.no_base)


def test_the_baseline_may_be_named_by_its_content_xml_id(tmp_path):
    """The nested FOLDER uses the folder name, but a mod's id can differ (#6)."""
    base = _mod(tmp_path, "vro_folder", {"gun": {"damage": "5500"}})
    (base / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='vro' version='100'/>",
        encoding="utf-8")
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "8500"}})
    arch = _nested_mod(tmp_path, "myoverlay", "vro", {"gun": {"damage": "30500"}})
    r = _threeway.three_way(base, arch, cur)
    assert r.documents_compared == 1, "folder name and content.xml id must both match"


# --- second round from real use: DOCUMENT SHAPE across the join -------------------

def _diff_mod(root: Path, name: str, target: str, wares: dict[str, dict[str, str]]) -> Path:
    """A nested overlay that supplies its payload via `<diff><replace sel="//wares">`.

    This is the whole-file override idiom (CLAUDE.md #10; VRO alone ships 848).
    """
    d = root / name
    inner = d / "extensions" / target / "libraries"
    inner.mkdir(parents=True)
    body = "".join(
        '<ware id="%s" %s/>' % (w, " ".join(f'{k}="{v}"' for k, v in a.items()))
        for w, a in wares.items())
    (inner / "wares.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?>"
        f'<diff><replace sel="//wares"><wares>{body}</wares></replace></diff>',
        encoding="utf-8")
    (d / "content.xml").write_text(
        f"<?xml version='1.0' encoding='utf-8'?><content id='{name}' version='100'/>",
        encoding="utf-8")
    return d


def test_a_root_replace_payload_is_joined_against_a_plain_document(tmp_path):
    """MEASURED as broken on real use: 0 BOTH-MOVED, the conflict invisible.

    The archive supplies `<diff><replace sel="//wares">PAYLOAD</replace></diff>`
    while the baseline is a plain `<wares>`, so every attribute path differs by a
    `/diff/replace/` prefix and nothing joins. The whole document then falls to
    node-level counts -- honest, but useless for the files that matter.

    ⚠ The earlier nested fixture could NOT have caught this: both of its sides
    were plain documents, so the shapes matched and it went green for a reason
    unrelated to the defect. A fixture that cannot exhibit the failure is not a
    test of it.
    """
    base = _mod(tmp_path, "vro", {"gun": {"damage": "5500"}})
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "8500"}})
    arch = _diff_mod(tmp_path, "myoverlay", "vro", {"gun": {"damage": "30500"}})

    r = _threeway.three_way(base, arch, cur)
    assert len(r.both_moved) == 1, (
        f"the root-replace payload must join the plain document; "
        f"node_level={r.node_level}")
    c = r.both_moved[0]
    assert (c.base, c.archived, c.current) == ("5500", "30500", "8500")


def test_root_replace_unwrapping_is_REPORTED(tmp_path):
    base = _mod(tmp_path, "vro", {"gun": {"damage": "5500"}})
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "8500"}})
    arch = _diff_mod(tmp_path, "myoverlay", "vro", {"gun": {"damage": "30500"}})
    r = _threeway.three_way(base, arch, cur)
    assert any("replace" in u.lower() for u in r.unwrapped), r.unwrapped


def test_a_NON_root_diff_is_left_alone(tmp_path):
    """Falsification twin: an ordinary attribute patch is not a whole-document swap.

    Unwrapping it would discard the diff structure and invent a comparison.
    """
    base = _mod(tmp_path, "vro", {"gun": {"damage": "5500"}})
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "8500"}})
    d = tmp_path / "narrow"
    inner = d / "extensions" / "vro" / "libraries"
    inner.mkdir(parents=True)
    (inner / "wares.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?>"
        '<diff><replace sel="//ware[@id=\'gun\']/@damage">30500</replace></diff>',
        encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='narrow' version='100'/>",
        encoding="utf-8")
    r = _threeway.three_way(base, d, cur)
    assert not any("replace" in u.lower() for u in r.unwrapped), (
        "a targeted attribute patch is not a whole-document override")


def test_an_author_REMOVAL_is_labelled_as_such(tmp_path):
    """base has it, archive dropped it, upstream kept it.

    Reported from real use: `explosiondamage@shield` 7500 in base and current,
    absent in the archive. That is neither drift nor a value edit, and a consumer
    applying it as a value edit would write the sentinel instead of deleting the
    attribute.
    """
    base = _mod(tmp_path, "vro", {"gun": {"damage": "5500", "shield": "7500"}})
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "5500", "shield": "7500"}})
    arch = _diff_mod(tmp_path, "myoverlay", "vro", {"gun": {"damage": "5500"}})

    r = _threeway.three_way(base, arch, cur)
    kinds = {c.attr: c.kind for c in r.author_edits}
    assert kinds.get("shield") == "author-removal", kinds


def test_an_upstream_ADDITION_is_labelled_as_such(tmp_path):
    """The 16-macro case, now stated by the tool rather than inferred by a reader."""
    base = _mod(tmp_path, "vro", {"msl": {"speed": "100"}})
    cur = _mod(tmp_path, "vro_current", {"msl": {"speed": "100", "targetable": "1"}})
    arch = _mod(tmp_path, "arch", {"msl": {"speed": "100"}})
    r = _threeway.three_way(base, arch, cur)
    kinds = {c.attr: c.kind for c in r.upstream_drift}
    assert kinds.get("targetable") == "upstream-addition", kinds


def _one_op_mod(root: Path, name: str, target: str, op: str, sel: str, payload: str) -> Path:
    """A nested overlay whose diff holds exactly ONE op with exactly ONE element payload.

    This shape is what actually reaches the root-selector check. The earlier
    `test_a_NON_root_diff_is_left_alone` twin used a TEXT payload, so the
    "exactly one element payload" guard fired first and the selector and op-tag
    checks were never evaluated -- it passed for an unrelated reason, and two
    planted mutants survived it. Third instance today of a green that could not
    have gone red.
    """
    d = root / name
    inner = d / "extensions" / target / "libraries"
    inner.mkdir(parents=True)
    (inner / "wares.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?>"
        f'<diff><{op} sel="{sel}">{payload}</{op}></diff>', encoding="utf-8")
    (d / "content.xml").write_text(
        f"<?xml version='1.0' encoding='utf-8'?><content id='{name}' version='100'/>",
        encoding="utf-8")
    return d


def test_a_replace_targeting_a_NODE_is_not_treated_as_a_root_override(tmp_path):
    """One op, one ELEMENT payload, but the selector names a node, not the root.

    Unwrapping this would replace the whole document with a single <ware>.
    Kills the mutant that drops the root-selector check.
    """
    base = _mod(tmp_path, "vro", {"gun": {"damage": "5500"}})
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "8500"}})
    arch = _one_op_mod(tmp_path, "nodepatch", "vro", "replace",
                       "//wares/ware[@id='gun']", '<ware id="gun" damage="30500"/>')
    r = _threeway.three_way(base, arch, cur)
    assert not any("payload unwrapped" in u for u in r.unwrapped), (
        f"a node-targeted replace is not a whole-document override: {r.unwrapped}")


def test_an_ADD_op_is_never_unwrapped(tmp_path):
    """One op, one element payload, root-ish selector -- but it is an <add>.

    An add EXTENDS the document; unwrapping it would substitute the added node
    for the whole file. Kills the mutant that drops the op-tag check.
    """
    base = _mod(tmp_path, "vro", {"gun": {"damage": "5500"}})
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "8500"}})
    arch = _one_op_mod(tmp_path, "addpatch", "vro", "add",
                       "//wares", '<ware id="brandnew" damage="1"/>')
    r = _threeway.three_way(base, arch, cur)
    assert not any("payload unwrapped" in u for u in r.unwrapped), (
        f"an <add> is not a whole-document override: {r.unwrapped}")


def test_an_ADD_whose_selector_names_the_payload_tag_is_still_not_unwrapped(tmp_path):
    """Reaches the OP-TAG check specifically.

    `<add sel="//wares"><wares>...</wares></add>` passes the one-payload check AND
    the root-selector check, so only the op-tag check can stop it. The earlier add
    twin used a `<ware>` payload, whose tag does not match the selector -- so the
    selector check stopped it first and the op-tag mutant survived. A compound
    condition needs a twin per clause.
    """
    base = _mod(tmp_path, "vro", {"gun": {"damage": "5500"}})
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "8500"}})
    arch = _one_op_mod(tmp_path, "addwares", "vro", "add", "//wares",
                       '<wares><ware id="brandnew" damage="1"/></wares>')
    r = _threeway.three_way(base, arch, cur)
    assert not any("payload unwrapped" in u for u in r.unwrapped), (
        f"an <add> is not a whole-document override: {r.unwrapped}")


def test_a_diff_with_MORE_THAN_ONE_op_is_not_unwrapped(tmp_path):
    """Reaches the SINGLE-OP clause.

    A document supplied by a root replace has exactly one op. Two ops means the
    later one patches the payload the first installed (CLAUDE.md #17 -- ops apply
    in order, to a tree earlier ops have changed), so the file is not a plain
    whole-document override and unwrapping it would discard the second op.
    """
    base = _mod(tmp_path, "vro", {"gun": {"damage": "5500"}})
    cur = _mod(tmp_path, "vro_current", {"gun": {"damage": "8500"}})
    d = tmp_path / "twoop"
    inner = d / "extensions" / "vro" / "libraries"
    inner.mkdir(parents=True)
    (inner / "wares.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><diff>"
        '<replace sel="//wares"><wares><ware id="gun" damage="30500"/></wares></replace>'
        '<replace sel="//ware[@id=\'gun\']/@damage">31000</replace>'
        "</diff>", encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='twoop' version='100'/>",
        encoding="utf-8")
    r = _threeway.three_way(base, d, cur)
    assert not any("payload unwrapped" in u for u in r.unwrapped), (
        f"a multi-op diff is not a plain whole-document override: {r.unwrapped}")

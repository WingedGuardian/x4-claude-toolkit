"""AUDIT-2026-09-24, VA lane: x4validate findings reproduced as failing tests.

Every test here asserts the CORRECT behaviour and is marked
``xfail(strict=True)`` because the current code does not have it. When a fix
lands, the matching test XPASSes, strict mode turns that into a failure, and the
marker must be removed in the same commit as the fix -- so a fix cannot land
without its test going live.

Each test runs the REAL validator (``_check.validate`` / ``_cli.main`` / the
named check function) against tiny fixture trees in ``tmp_path``. The only
things monkeypatched are ENVIRONMENT locations (which extension roots and
profile the registry reads, where the game root is), never the subject.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from x4validate import _check, _cli, _merge, _registry


# --------------------------------------------------------------------- fixtures

def _w(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _ref(tmp_path: Path) -> Path:
    """A reference tree complete enough that a clean mod reports NOTHING.

    Without races/modulegroups/index the run carries its own NOT CHECKED lines
    and an unrelated WARN, which would let a test pass or fail for the wrong
    reason.
    """
    ref = tmp_path / "reference"
    _w(ref / "libraries/wares.xml", '<wares><ware id="ore" price="1"/></wares>')
    _w(ref / "libraries/races.xml", '<races><race id="argon"/></races>')
    _w(ref / "libraries/modulegroups.xml", '<groups><group name="g"/></groups>')
    _w(ref / "index/macros.xml",
       '<index><entry name="x_macro" value="assets\\x\\x_macro"/></index>')
    _w(ref / "t/0001-l044.xml",
       '<language id="44"><page id="1001"><t id="1">Base string</t></page></language>')
    return ref


def _mod(tmp_path: Path, name: str = "mymod", mod_id: str = "mymod") -> Path:
    mod = tmp_path / name
    _w(mod / "content.xml",
       f'<?xml version="1.0"?><content id="{mod_id}" name="{mod_id}" version="100" enabled="1"/>')
    return mod


_CLEAN_WARES_DIFF = "<diff><replace sel=\"//ware[@id='ore']/@price\">5</replace></diff>"

#: A shape-A engine line naming `extensions\<folder>\libraries\wares.xml`.
def _engine_error_for(folder: str) -> str:
    return ("[=ERROR=] 84.60 extensions\\" + folder
            + "\\libraries\\wares.xml(1): Error while parsing expression: '}' expected\n")


def _run_cli(argv, capsys) -> tuple[int, str]:
    rc = _cli.main([str(a) for a in argv])
    return rc, capsys.readouterr().out


def _isolated_registry(monkeypatch, tmp_path: Path, mods: dict[str, bool]) -> Path:
    """Point the registry at a throwaway extensions root + profile.

    *mods* maps folder (== id) -> profile-enabled. Environment only: the code
    under test still does its own scan, profile read and load-order walk.
    """
    exts = tmp_path / "game_extensions"
    for name in mods:
        _w(exts / name / "content.xml",
           f'<content id="{name}" name="{name}" version="100" enabled="1"/>')
    rows = "".join(f'<extension id="{n}" enabled="{"true" if on else "false"}"/>'
                   for n, on in mods.items())
    profile = _w(tmp_path / "profile" / "content.xml", f"<content>{rows}</content>")
    monkeypatch.setattr(_registry, "GAME_EXTENSIONS", exts)
    monkeypatch.setattr(_registry, "PROFILE_EXTENSIONS", None)
    monkeypatch.setattr(_registry, "WORKSHOP_CONTENT", None)
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", profile)
    return exts


#: A target folder name no real install will ever have.
ABSENT = "zz_audit0924_absent_target"


# ----------------------------------------------------------------------- VA-1

def test_va1_missing_debug_log_is_not_a_clean_pass(tmp_path, capsys):
    ref = _ref(tmp_path)
    mod = _mod(tmp_path)
    _w(mod / "libraries/wares.xml", _CLEAN_WARES_DIFF)
    missing = tmp_path / "no_such_dir" / "debug.txt"

    rc, out = _run_cli([mod, "--reference", ref, "--debug", missing], capsys)

    # The authoritative layer the user asked for examined NOTHING. That is a
    # non-answer (exit 3) or a usage error (exit 2) -- never a pass.
    assert rc in (2, 3), f"rc={rc}\n{out}"
    assert "OK: no issues found" not in out


# ----------------------------------------------------------------------- VA-2

def test_va2_file_mode_agrees_with_full_run_on_an_inactive_nested_patch(tmp_path):
    ref = _ref(tmp_path)
    mod = _mod(tmp_path)
    f = _w(mod / "extensions" / ABSENT / "libraries/wares.xml",
           "<diff><replace sel=\"//ware[@id='x']/@price\">5</replace></diff>")
    cfg = _merge.Config(reference=ref)

    full = _check.validate(mod, cfg)
    one = _check.validate(mod, cfg, only_file=f)

    # Control: the full run must really classify it as a designed no-op, or this
    # test would be comparing two wrong answers.
    assert not full.errors
    assert any(x.category in ("inactive", "unverifiable") for x in full.findings)

    # The per-edit hook runs --file and advises on error_count > 0.
    assert not one.errors, [(x.severity, x.category, x.message) for x in one.errors]


def test_va2_file_mode_reports_an_inert_bare_path_patch(tmp_path):
    ref = _ref(tmp_path)
    other = tmp_path / "other_mod"
    _w(other / "libraries/other_things.xml", '<things><thing id="a" v="1"/></things>')
    mod = _mod(tmp_path)
    f = _w(mod / "libraries/other_things.xml",
           "<diff><replace sel=\"//thing[@id='a']/@v\">2</replace></diff>")
    cfg = _merge.Config(reference=ref, overlays=(other,))

    full = _check.validate(mod, cfg)
    one = _check.validate(mod, cfg, only_file=f)

    assert any(x.category == "path" for x in full.errors), "control: full run flags it"
    assert any(x.category == "path" for x in one.errors), \
        [(x.severity, x.category, x.message) for x in one.findings]


# ----------------------------------------------------------------------- VA-3

def test_va3_file_mode_does_not_silently_drop_debug(tmp_path, capsys):
    ref = _ref(tmp_path)
    mod = _mod(tmp_path)
    f = _w(mod / "libraries/wares.xml", _CLEAN_WARES_DIFF)
    log = _w(tmp_path / "debug.txt", _engine_error_for("mymod"))

    rc_full, _ = _run_cli([mod, "--reference", ref, "--debug", log], capsys)
    assert rc_full == 1, "control: without --file the engine error gates"

    rc, out = _run_cli([mod, "--reference", ref, "--debug", log, "--file", f, "--json"],
                       capsys)
    payload = json.loads(out)
    # Honour it (rc 1), refuse the combination (rc 2), or disclose the drop
    # (a skipped entry). Silently printing a clean result is the only wrong answer.
    assert rc != 0 or payload["skipped"], out


@pytest.mark.parametrize("extra", [
    ["--entity", "ware:ore", "--like", "ware:ore"],
    ["--update"],
], ids=["entity-like", "update"])
def test_va3_file_mode_does_not_silently_drop_other_requests(tmp_path, capsys, extra):
    ref = _ref(tmp_path)
    mod = _mod(tmp_path)
    f = _w(mod / "libraries/wares.xml", _CLEAN_WARES_DIFF)

    rc, out = _run_cli([mod, "--reference", ref, "--file", f, "--json", *extra], capsys)
    payload = json.loads(out)
    assert rc != 0 or payload["skipped"], out


# ----------------------------------------------------------------------- VA-4

def test_va4_relative_mod_dir_with_absolute_file(tmp_path, monkeypatch):
    ref = _ref(tmp_path)
    _mod(tmp_path)
    f = _w(tmp_path / "mymod" / "libraries/wares.xml", _CLEAN_WARES_DIFF)
    monkeypatch.chdir(tmp_path)

    rep = _check.validate(Path("mymod"), _merge.Config(reference=ref),
                          only_file=f.resolve())

    assert not rep.errors, [(x.vpath, x.message) for x in rep.errors]


# ----------------------------------------------------------------------- VA-5

def test_va5_refs_in_an_inactive_patch_do_not_gate_under_tier_b(tmp_path):
    ref = _ref(tmp_path)
    other = tmp_path / "other_mod"
    _w(other / "libraries/other_things.xml", "<things/>")
    mod = _mod(tmp_path)
    vpath = f"extensions/{ABSENT}/libraries/wares.xml"
    _w(mod / vpath,
       '<diff><add sel="/wares"><ware id="newware"><production><primary>'
       '<ware ware="zz_audit_nosuch_ware" amount="1"/></primary></production>'
       '</ware></add></diff>')

    tier_b = _check.validate(mod, _merge.Config(reference=ref, overlays=(other,)))

    # Control: the SAME run already calls the file a designed no-op.
    assert any(x.category == "inactive" and x.vpath == vpath for x in tier_b.findings)
    # ...so a reference inside it cannot be a gating defect of this mod.
    ref_errs = [x for x in tier_b.errors if x.category == "ref" and x.vpath == vpath]
    assert not ref_errs, [x.message for x in ref_errs]


# ----------------------------------------------------------------------- VA-6

def test_va6_nested_patch_for_a_disabled_target_is_not_a_path_mismatch(tmp_path, monkeypatch):
    ref = _ref(tmp_path)
    exts = _isolated_registry(monkeypatch, tmp_path,
                              {"zz_enabled_other": True, "zz_disabled_tgt": False})
    # The disabled target really does ship the file the patch names.
    _w(exts / "zz_disabled_tgt" / "md/tgt_script.xml",
       '<mdscript name="TgtScript"><cues><cue name="A"/></cues></mdscript>')
    _w(exts / "zz_enabled_other" / "libraries/other_things.xml", "<things/>")
    mod = _mod(tmp_path)
    vpath = "extensions/zz_disabled_tgt/md/tgt_script.xml"
    _w(mod / vpath, "<diff><add sel=\"//cue[@name='A']\"><cues/></add></diff>")

    rep = _check.validate(mod, _merge.Config(reference=ref), tier="b")

    assert not rep.degraded, "control: Tier B must have been built, not fallen back"
    path_errs = [x for x in rep.errors if x.vpath == vpath]
    assert not path_errs, [(x.category, x.message) for x in path_errs]


# ----------------------------------------------------------------------- VA-7

def _write_cat(mod_dir: Path, cat_name: str, members):
    import hashlib
    mod_dir.mkdir(parents=True, exist_ok=True)
    cat = mod_dir / cat_name
    lines, blob = [], bytearray()
    for vp, data in members:
        lines.append(f"{vp} {len(data)} 1700000000 {hashlib.md5(data).hexdigest()}")
        blob += data
    cat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cat.with_suffix(".dat").write_bytes(bytes(blob))


def test_va7_dangling_ref_in_a_packed_dlc_patch_still_gates(tmp_path, monkeypatch):
    ref = _ref(tmp_path)
    game = tmp_path / "game"
    _write_cat(game / "extensions" / "ego_dlc_mini_01", "ext_01.cat", [
        ("libraries/god.xml", b"<god><products/></god>"),
    ])
    monkeypatch.setattr(_merge, "GAME_ROOT", game)
    monkeypatch.setattr(_merge, "REFERENCE", ref)
    cfg = _merge.Config(reference=ref)
    assert cfg.packed_dlc_names() == {"ego_dlc_mini_01"}, "control: DLC is packed-only"

    mod = _mod(tmp_path)
    vpath = "extensions/ego_dlc_mini_01/libraries/god.xml"
    _w(mod / vpath, '<diff><add sel="/god/products"><product ware="zz_audit_nosuch_ware"/>'
                    '</add></diff>')

    rep = _check.validate(mod, cfg)

    refs = [x for x in rep.findings if x.category == "ref" and x.vpath == vpath]
    assert refs, "control: the dangling ref is found at all"
    # Tier A DOES merge this DLC (dlc_dirs), so the question is answerable here.
    assert all(x.severity == "error" for x in refs), [(x.severity, x.message) for x in refs]


# ----------------------------------------------------------------------- VA-8

def test_va8_sel_only_runs_only_sel_resolution(tmp_path, capsys):
    ref = _ref(tmp_path)
    mod = _mod(tmp_path)
    _w(mod / "libraries/wares.xml",
       '<diff><add sel="/wares"><ware id="newware"><production><primary>'
       '<ware ware="zz_audit_nosuch_ware" amount="1"/></primary></production>'
       '</ware></add></diff>')

    rc_all, out_all = _run_cli([mod, "--reference", ref, "--json"], capsys)
    assert any(f["category"] == "ref" for f in json.loads(out_all)["findings"]), \
        "control: the default run reports the dangling ref"

    rc, out = _run_cli([mod, "--reference", ref, "--json", "--sel-only"], capsys)
    cats = {f["category"] for f in json.loads(out)["findings"]}
    assert cats <= {"sel", "path", "inactive", "unverifiable"}, cats


# ----------------------------------------------------------------------- VA-9

def test_va9_full_t_file_redefining_a_base_string_is_flagged(tmp_path):
    ref = _ref(tmp_path)
    cfg = _merge.Config(reference=ref)

    via_diff = _mod(tmp_path, "diffmod", "diffmod")
    _w(via_diff / "t/0001-l044.xml",
       '<diff><add sel="/language"><page id="1001"><t id="1">Mine</t></page></add></diff>')
    rep_diff = _check.validate(via_diff, cfg)
    assert any(x.category == "text" for x in rep_diff.findings), \
        "control: the <diff> form of the same clobber is warned"

    full = _mod(tmp_path, "fullmod", "fullmod")
    _w(full / "t/0001-l044.xml",
       '<language id="44"><page id="1001"><t id="1">Mine</t></page></language>')
    rep_full = _check.validate(full, cfg)
    assert any(x.category == "text" and "1001" in x.message for x in rep_full.findings), \
        [(x.severity, x.category, x.message) for x in rep_full.findings]


# ---------------------------------------------------------------------- VA-10

def _broken_overlay(tmp_path: Path, rel: str) -> Path:
    ov = tmp_path / "ov_broken"
    _w(ov / rel, "<index><entry name='a' value='b'/>")  # missing close tag
    return ov


def test_va10_dropped_macro_index_overlay_is_degraded(tmp_path):
    ref = _ref(tmp_path)
    ov = _broken_overlay(tmp_path, "index/macros.xml")
    rep = _check.Report()

    _check.collect_macro_defs(_merge.Config(reference=ref, overlays=(ov,)), report=rep)

    assert rep.skipped, "control: the dropped overlay is recorded at all"
    assert all(s.degraded for s in rep.skipped), [(s.what, s.degraded) for s in rep.skipped]


def test_va10_dropped_modulegroups_overlay_is_degraded(tmp_path):
    ref = _ref(tmp_path)
    ov = tmp_path / "ov_broken"
    _w(ov / "libraries/modulegroups.xml", "<groups><group name='h'/>")  # malformed
    mod = _mod(tmp_path)
    rep = _check.Report()

    _check.check_module_groups(mod, _merge.Config(reference=ref, overlays=(ov,)), rep)

    assert rep.skipped, "control: the dropped overlay is recorded at all"
    assert all(s.degraded for s in rep.skipped), [(s.what, s.degraded) for s in rep.skipped]


# ---------------------------------------------------------------------- VA-11

def test_va11a_checked_count_excludes_unexamined_files(tmp_path):
    ref = _ref(tmp_path)
    mod = _mod(tmp_path)
    _w(mod / "extensions" / ABSENT / "libraries/wares.xml",
       "<diff><replace sel=\"//ware[@id='x']/@price\">5</replace></diff>")

    rep = _check.validate(mod, _merge.Config(reference=ref))

    m = [re.search(r"sel-resolution: (\d+) diff file\(s\) checked", n) for n in rep.notes]
    m = [x for x in m if x]
    assert m, rep.notes
    assert int(m[0].group(1)) == 0, rep.notes  # the only diff was inactive: 0 ops examined


def test_va11b_lookup_errors_are_attributed_or_disclosed(tmp_path):
    mod = _mod(tmp_path)
    _w(mod / "libraries/wares.xml",
       '<diff><add sel="/wares"><ware id="w"><component ref="zz_audit_mod_macro"/></ware>'
       '</add></diff>')
    log = _w(tmp_path / "debug.txt",
             "[=ERROR=] 12.00 Cannot find XML file macro 'zz_audit_mod_macro' "
             "in index 'macros'\n")
    rep = _check.Report()

    _check.check_debug_correlation(mod, _merge.Config(reference=_ref(tmp_path)), rep, log)

    dbg = [x for x in rep.findings if x.category == "debug"]
    # Strip the log path first: tmp_path embeds this test's NAME, which contains
    # the word "lookup" -- the first draft of this test passed on that alone.
    notes = [n.replace(str(log), "<log>") for n in rep.notes]
    assert dbg or any("lookup" in n.lower() for n in notes), notes


def test_va11c_dot_mod_dir_keeps_its_folder_identity(tmp_path, monkeypatch):
    ref = _ref(tmp_path)
    mod = _mod(tmp_path, name="folder_name", mod_id="different_id")
    _w(mod / "libraries/wares.xml", _CLEAN_WARES_DIFF)
    log = _w(tmp_path / "debug.txt", _engine_error_for("folder_name"))

    by_path = _check.Report()
    _check.check_debug_correlation(mod, _merge.Config(reference=ref), by_path, log)
    assert by_path.errors, "control: addressed by path, the engine error matches"

    monkeypatch.chdir(mod)
    by_dot = _check.Report()
    _check.check_debug_correlation(Path("."), _merge.Config(reference=ref), by_dot, log)
    assert by_dot.errors, by_dot.notes


def test_va11d_tier_help_names_the_active_set(capsys):
    with pytest.raises(SystemExit):
        _cli.main(["--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    # The OPTIONS entry, not the usage line (which also starts with "--tier").
    tier = help_text[help_text.index("--tier {a,b} a ="):]
    tier = tier[:tier.index("--profile")]
    assert "INSTALLED extensions" not in tier, tier


def test_va11e_race_table_failure_is_a_skip(tmp_path):
    ref = _ref(tmp_path)
    (ref / "libraries/races.xml").unlink()
    mod = _mod(tmp_path)
    _w(mod / "libraries/wares.xml", _CLEAN_WARES_DIFF)

    rep = _check.validate(mod, _merge.Config(reference=ref))

    assert not [x for x in rep.findings if x.category == "identity"], \
        [(x.severity, x.message) for x in rep.findings]
    assert any("race" in (s.what + s.why).lower() for s in rep.skipped), rep.skipped


def test_va11f_page_collision_names_the_real_definer(tmp_path):
    ref = _ref(tmp_path)
    other = tmp_path / "other_mod"
    _w(other / "t/0001-l044.xml",
       '<language id="44"><page id="77001"><t id="5">Other mod</t></page></language>')
    mod = _mod(tmp_path)
    _w(mod / "t/0001-l044.xml",
       '<diff><add sel="/language"><page id="77001"><t id="5">Mine</t></page></add></diff>')
    rep = _check.Report()

    _check.check_page_collisions(mod, _merge.Config(reference=ref, overlays=(other,)), rep)

    hits = [x for x in rep.findings if x.category == "text"]
    assert hits, "control: the collision is found"
    assert all("base/DLC" not in x.message for x in hits), [x.message for x in hits]


# ---------------------------------------------------------------------- VA-12

def test_va12_unreadable_overlay_index_is_a_degraded_skip(tmp_path):
    """An overlay's index/macros.xml that will not parse leaves the registry
    incomplete, so every "registered but missing" / connection verdict built on it
    is computed against a partial index. It was recorded as a NON-degraded skip
    (fired twice in a real run), so the run exited 0/1 instead of 3."""
    from x4validate import _resolve
    ref = _ref(tmp_path)
    ov = _broken_overlay(tmp_path, "index/macros.xml")
    rep = _check.Report()

    _resolve.build_index(_merge.Config(reference=ref, overlays=(ov,)), [],
                         _resolve.MACRO_INDEX, rep)
    _resolve.build_index(_merge.Config(reference=ref, overlays=(ov,)), [],
                         _resolve.MACRO_INDEX, rep)

    assert rep.skipped, "control: the unreadable index is recorded at all"
    assert all(s.degraded for s in rep.skipped), [(s.what, s.degraded) for s in rep.skipped]
    assert len(rep.skipped) == 1, "one cause, one line -- not one per build"


def test_va12_a_readable_overlay_index_records_nothing(tmp_path):
    """The twin: a well-formed overlay index is not a skip at all."""
    from x4validate import _resolve
    ref = _ref(tmp_path)
    ov = tmp_path / "ov_ok"
    _w(ov / "index/macros.xml", "<index><entry name='a' value='b'/></index>")
    rep = _check.Report()
    idx = _resolve.build_index(_merge.Config(reference=ref, overlays=(ov,)), [],
                               _resolve.MACRO_INDEX, rep)
    assert "a" in idx and not rep.skipped


# ---------------------------------------------------------------------- VA-13

def _va13_ref_without_modulegroups(tmp_path: Path) -> Path:
    ref = _ref(tmp_path)
    (ref / "libraries/modulegroups.xml").unlink()
    return ref


def test_va13_module_groups_that_did_not_merge_are_degraded(tmp_path):
    """The whole check OFF, for a mod that HAS a `<module group=>` to verify, is a
    non-answer -- technical default: a DEGRADED skip (exit 3), not a disclosure."""
    ref = _va13_ref_without_modulegroups(tmp_path)
    mod = _mod(tmp_path)
    _w(mod / "libraries/constructionplans.xml",
       '<plans><plan id="p"><entry><module id="m" group="zz_nosuch"/></entry></plan></plans>')
    rep = _check.Report()

    _check.check_module_groups(mod, _merge.Config(reference=ref), rep)

    mg = [s for s in rep.skipped if s.what == "module group checks"]
    assert mg and all(s.degraded for s in mg), [(s.what, s.why, s.degraded) for s in rep.skipped]


def test_va13_nothing_to_verify_is_not_degraded(tmp_path):
    """The twin: with no `<module group=>` in the mod nothing was lost, so the same
    missing file must not become a permanent exit 3 on every mod."""
    ref = _va13_ref_without_modulegroups(tmp_path)
    mod = _mod(tmp_path)
    _w(mod / "libraries/wares.xml", _CLEAN_WARES_DIFF)
    rep = _check.Report()

    _check.check_module_groups(mod, _merge.Config(reference=ref), rep)

    assert rep.skipped and not rep.degraded, [(s.what, s.degraded) for s in rep.skipped]


# ---------------------------------------------------------------------- VA-14

def test_va14_file_mode_prints_its_denominator_and_what_it_skipped(tmp_path, capsys):
    """`--file` printed "OK: no issues found" with no notes at all -- not even the
    sel-resolution count -- so one checked file and zero read the same."""
    ref = _ref(tmp_path)
    mod = _mod(tmp_path)
    f = _w(mod / "libraries/wares.xml", _CLEAN_WARES_DIFF)

    rc, out = _run_cli([mod, "--reference", ref, "--file", f], capsys)

    assert rc == 0, out
    assert re.search(r"sel-resolution: 1 diff file\(s\) checked", out), out
    assert "libraries/wares.xml" in out, out
    assert "OK: no issues found" not in out, "only ONE check ran; that is not an unqualified OK"
    assert "NOT CHECKED" in out, out


# ------------------------------------------------------ VA-9 review (flooding)

def test_va9_a_complete_t_file_override_is_ONE_info_finding_per_file(tmp_path):
    """A complete t-file overriding base strings is the normal rename idiom (VRO
    ships one: 304 {page,t} per language file). One INFO per file with the count,
    never one WARN per string."""
    ref = _ref(tmp_path)
    _w(ref / "t/0001-l044.xml",
       '<language id="44"><page id="1001">'
       + "".join(f'<t id="{i}">Base {i}</t>' for i in range(1, 51))
       + "</page></language>")
    mod = _mod(tmp_path, "fullmod", "fullmod")
    _w(mod / "t/0001-l044.xml",
       '<language id="44"><page id="1001">'
       + "".join(f'<t id="{i}">Mine {i}</t>' for i in range(1, 51))
       + "</page></language>")
    rep = _check.Report()
    _check.check_page_collisions(mod, _merge.Config(reference=ref), rep)
    hits = [x for x in rep.findings if x.category == "text"]
    assert len(hits) == 1, [(x.severity, x.message) for x in hits]
    assert hits[0].severity == "info" and "50" in hits[0].message, hits[0].message


def test_va9_a_complete_t_file_colliding_with_ANOTHER_MOD_still_warns(tmp_path):
    ref = _ref(tmp_path)
    other = tmp_path / "other_mod"
    _w(other / "t/0001-l044.xml",
       '<language id="44"><page id="77001"><t id="5">Other</t></page></language>')
    mod = _mod(tmp_path)
    _w(mod / "t/0001-l044.xml",
       '<language id="44"><page id="77001"><t id="5">Mine</t></page></language>')
    rep = _check.Report()
    _check.check_page_collisions(mod, _merge.Config(reference=ref, overlays=(other,)), rep)
    hits = [x for x in rep.findings if x.category == "text"]
    assert [x.severity for x in hits] == ["warn"], [(x.severity, x.message) for x in hits]
    assert "other_mod" in hits[0].message

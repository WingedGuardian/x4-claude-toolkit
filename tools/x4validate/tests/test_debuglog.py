"""debug.txt correlation — the authoritative layer that gates on the engine's
own verdict. Covers all 6 real log shapes (the two runtime shapes were the ones
the first design missed; the MD-cue shape carries the `'null' is not a list`
error), plus script-name -> file resolution and other-mod filtering.

Shapes E/F (diff-op cardinality) were added 2026-07-26 after measuring that the
parser saw only 26% of a real 2463-error log and *none* of the 453 cardinality
failures — the exact class this tool exists to catch. Every E/F line below is
copied verbatim from that log, so these are real-data tests, not synthetic ones."""

from x4validate import _check, _debuglog, _merge

# Real shapes lifted from a live 9.0 debug.txt (escape_pod + a vanilla runtime error).
_SAMPLE = "\n".join([
    r"[General] 84.60 ======================================",
    r"[=ERROR=] 84.60 extensions\escape_pod\aiscripts\order.move.escapepod.xml(97): Error while parsing expression: '}' expected",
    r"[General] 84.60 ======================================",
    r'[=ERROR=] 84.60 LookupKeyName::LookupName(): The key name "show_text" is not recognized in lookup ScriptXML. Originated from: extensions\escape_pod\md\escape_pod_npc.xml.(xml|xml.gz)',
    r"[=ERROR=] 84.60 extensions\escape_pod\md\escape_pod_npc.xml(494): Warning while parsing expression: Inefficient lookup pattern " + '"<table>.keys.list.count"; use "<table>.keys.count" instead',
    r"[=ERROR=] 175.21 Error in MD cue md.EscapePodNPC.PlayerOwnedKilled<inst:1b4f55>: Evaluated value 'null' is not a list, group or table",
    r"* Action: <do_for_each>, line 158",
    r"[General] 175.21 ======================================",
    r"[=ERROR=] 84.60 Error in AI script move.generic on entity 0x281e7: Property lookup failed: $gatedestination",
    r"* Expression: $gatedestination.sector != this.sector",
    r"* Action: <do_if>, line 996",
])


def test_parse_debug_all_four_shapes(tmp_path):
    log = tmp_path / "debug.txt"
    log.write_text(_SAMPLE, encoding="utf-8")
    errs = _debuglog.parse_debug(log)

    # A — load parse error: file path + line
    a = [e for e in errs if e.ident_kind == "path" and e.vpath == "aiscripts/order.move.escapepod.xml"]
    assert a and a[0].line == 97 and a[0].severity == "error" and a[0].folder == "escape_pod"

    # B — load lookup error: file path, no line
    b = [e for e in errs if e.ident_kind == "path" and "show_text" in e.message]
    assert b and b[0].vpath == "md/escape_pod_npc.xml" and b[0].line == 0 and b[0].severity == "error"

    # C — runtime MD cue: script name + line-from-continuation (the null-list)
    c = [e for e in errs if e.ident_kind == "script" and e.script_name == "EscapePodNPC"]
    assert c and c[0].line == 158 and "not a list" in c[0].message and c[0].severity == "error"

    # warning line classified as warn, not error
    w = [e for e in errs if e.ident_kind == "path" and e.line == 494]
    assert w and w[0].severity == "warn"

    # D — runtime AI script: skips the * Expression: line, reads the * Action: line
    d = [e for e in errs if e.ident_kind == "script" and e.script_name == "move.generic"]
    assert d and d[0].line == 996


def test_correlation_resolves_scripts_filters_others_and_gates(tmp_path):
    mod = tmp_path / "escape_pod"
    (mod / "md").mkdir(parents=True)
    (mod / "aiscripts").mkdir(parents=True)
    (mod / "content.xml").write_text('<content id="escape_pod"/>', encoding="utf-8")
    (mod / "md" / "escape_pod_npc.xml").write_text(
        '<mdscript name="EscapePodNPC"><cues/></mdscript>', encoding="utf-8")
    (mod / "aiscripts" / "order.move.escapepod.xml").write_text(
        '<aiscript name="order.move.escapepod"/>', encoding="utf-8")
    log = tmp_path / "debug.txt"
    log.write_text(_SAMPLE, encoding="utf-8")

    rep = _check.Report()
    cfg = _merge.Config(reference=tmp_path / "reference")
    _check.check_debug_correlation(mod, cfg, rep, log)
    dbg = [f for f in rep.findings if f.category == "debug"]

    # the null-list runtime error (script EscapePodNPC) resolved to its file + line
    nl = [f for f in dbg if "not a list" in f.message]
    assert nl and nl[0].vpath == "md/escape_pod_npc.xml" and nl[0].line == 158

    # the path-form load error is kept too
    assert any(f.vpath == "aiscripts/order.move.escapepod.xml" for f in dbg)

    # vanilla move.generic (not one of this mod's scripts) is dropped -> every
    # surviving finding maps to one of the mod's own files
    assert all(f.vpath in {"md/escape_pod_npc.xml", "aiscripts/order.move.escapepod.xml"} for f in dbg)

    # engine errors gate the build; the warning stays advisory
    assert rep.errors
    assert any(f.severity == "warn" for f in dbg)


# Shapes E/F — copied verbatim from the 2026-07-26 log. Each line encodes one of the
# quirks that silently breaks a naive parser (see _debuglog's module docstring).
_SAMPLE_EF = "\n".join([
    # quirk 1: patch file printed WITHOUT its .xml extension (441 of 453 lines)
    # quirk 2: the sel contains single quotes (413 of 453) -> the group must be greedy
    r"[=ERROR=] 0.00 No matching node for path '/factions/faction[@id='scaleplate']/relations/relation[@faction='teladi']/@relation' in patch file 'extensions\ebi_pirate_chaos_conflict\libraries\factions'. Skipping node.",
    r"[=ERROR=] 0.00 Multiple matching nodes for path '/materiallibrary/collection[@name='map']' in patch file 'extensions\stars\libraries\material_library'. Skipping node.",
    # a sel with no quotes at all (40 of 453), and a path that DOES carry an extension (12 of 453)
    r"[=ERROR=] 0.00 No matching node for path '//wares' in patch file 'extensions\mymod\libraries\wares.xml'. Skipping node.",
])


def test_parse_debug_shapes_e_f_cardinality(tmp_path):
    log = tmp_path / "debug.txt"
    log.write_text(_SAMPLE_EF, encoding="utf-8")
    errs = _debuglog.parse_debug(log)
    ops = [e for e in errs if e.cardinality]
    assert len(ops) == 3, "every cardinality failure must be captured"

    none_ = [e for e in ops if e.cardinality == "none"]
    mult = [e for e in ops if e.cardinality == "multiple"]
    assert len(none_) == 2 and len(mult) == 1

    # quirk 2 — the greedy group must keep the WHOLE selector, quotes and all.
    # A `[^']*` group truncates this to "/factions/faction[@id=" and the op is unusable.
    e = [x for x in ops if x.folder == "ebi_pirate_chaos_conflict"][0]
    assert e.sel == ("/factions/faction[@id='scaleplate']/relations/"
                     "relation[@faction='teladi']/@relation")
    assert e.vpath == "libraries/factions"   # quirk 1: no extension, as the engine printed it
    assert e.severity == "error" and e.line == 0

    m = mult[0]
    assert m.folder == "stars" and m.sel == "/materiallibrary/collection[@name='map']"

    # the `extensions\` prefix must be consumed, exactly as shapes A/B do
    assert all(x.folder != "extensions" for x in ops)


def test_xml_candidates_resolves_the_missing_extension():
    # engine printed it without an extension -> try the literal form, then .xml
    assert _debuglog.xml_candidates("libraries/factions") == (
        "libraries/factions", "libraries/factions.xml")
    # already has one -> don't invent a second
    assert _debuglog.xml_candidates("libraries/wares.xml") == ("libraries/wares.xml",)
    assert _debuglog.xml_candidates("") == ()


def test_correlation_reports_cardinality_failures_against_real_file(tmp_path):
    """End-to-end: an extension-less engine path must land on the real file on disk."""
    mod = tmp_path / "ebi_pirate_chaos_conflict"
    (mod / "libraries").mkdir(parents=True)
    (mod / "content.xml").write_text('<content id="ebi_pirate_chaos_conflict"/>',
                                     encoding="utf-8")
    (mod / "libraries" / "factions.xml").write_text("<diff/>", encoding="utf-8")
    log = tmp_path / "debug.txt"
    log.write_text(_SAMPLE_EF, encoding="utf-8")

    rep = _check.Report()
    _check.check_debug_correlation(mod, _merge.Config(reference=tmp_path / "ref"), rep, log)
    dbg = [f for f in rep.findings if f.category == "debug"]

    assert len(dbg) == 1, "only this mod's failure is kept; stars/mymod are filtered out"
    # resolved from 'libraries/factions' to the file that actually exists
    assert dbg[0].vpath == "libraries/factions.xml"
    assert rep.errors, "a skipped diff op is a real error and must gate"
    assert any("silently did nothing" in n for n in rep.notes)


def test_correlation_empty_log_notes_not_crashes(tmp_path):
    (tmp_path / "content.xml").write_text('<content id="m"/>', encoding="utf-8")
    log = tmp_path / "debug.txt"
    log.write_text("[General] 1.0 nothing to see\n", encoding="utf-8")
    rep = _check.Report()
    cfg = _merge.Config(reference=tmp_path / "reference")
    _check.check_debug_correlation(tmp_path, cfg, rep, log)
    assert not rep.errors and rep.notes  # a clean/irrelevant log is a note, not a failure

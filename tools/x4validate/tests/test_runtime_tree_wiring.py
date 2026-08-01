"""L9, second half: `validate()` must actually ROUTE each check to the right tree.

`test_tier_b_trees` pins the mechanism (`Config.for_runtime`, the `TierB` split).
Mechanism alone is not the fix — mutation-testing proved it: reverting
`runtime = config.for_runtime()` to `runtime = config` in `validate()` left all 226
of those tests green while restoring the exact bug. That is the half-fix shape this
codebase keeps re-learning, so the wiring gets its own end-to-end pin.

The world below is the measured `X4CapturableXenonXL` / `xspvro` case in miniature:
a mod references something that only a LATER-loading extension defines. At patch
time it looks dangling; at runtime it resolves. The engine resolves references after
every extension has loaded, so "no error" is the correct answer.
"""

from __future__ import annotations

from pathlib import Path

from x4validate import _check, _merge


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _world(tmp_path):
    """reference + a LATE-loading overlay that registers `late_macro` + a mod using it."""
    ref = tmp_path / "reference"
    _write(ref / "libraries" / "wares.xml", "<wares/>")
    _write(ref / "index" / "macros.xml", "<index><entry name='base_macro' value='a\\b'/></index>")
    _write(ref / "index" / "components.xml", "<index/>")

    late = tmp_path / "late"
    _write(late / "index" / "macros.xml",
           "<diff><add sel='/index'><entry name='late_macro' value='x\\y'/></add></diff>")
    # The index entry must point at a real file, or check_file_existence reports a
    # (correct) 'registered but file missing' that has nothing to do with tree choice.
    _write(late / "x" / "y.xml", "<macros><macro name='late_macro'/></macros>")

    mod = tmp_path / "mod"
    _write(mod / "libraries" / "wares.xml",
           "<diff><add sel='/wares'>"
           "<ware id='w_test'><component ref='late_macro'/></ware>"
           "</add></diff>")
    return ref, late, mod


def _macro_errors(report):
    return [f for f in report.findings
            if f.severity == "error" and "late_macro" in f.message]


def test_a_reference_defined_only_by_a_later_mod_is_not_an_error(tmp_path):
    """THE regression pin. Fails if validate() routes references to the patch-time tree."""
    ref, late, mod = _world(tmp_path)
    cfg = _merge.Config(reference=ref, overlays=(), final_overlays=(late,),
                        include_packed_dlc=False)
    report = _check.validate(mod, cfg)
    assert not _macro_errors(report), (
        "'late_macro' is registered by an extension that loads after this mod. The engine "
        "resolves the index once everything has loaded, so this must NOT be reported. "
        "Seeing it here means references are being checked against the patch-time tree.")


def test_the_same_reference_IS_an_error_when_nothing_defines_it(tmp_path):
    """The other side of the pin: the check must still be capable of firing.

    Without this, a `for_runtime` that returned a tree registering everything would
    pass the test above for entirely the wrong reason.
    """
    ref, _late, mod = _world(tmp_path)
    cfg = _merge.Config(reference=ref, overlays=(), final_overlays=(),
                        include_packed_dlc=False)
    report = _check.validate(mod, cfg)
    assert _macro_errors(report), \
        "no extension defines 'late_macro' at all — this genuinely IS a dangling reference"


def test_selectors_still_use_the_patch_time_tree(tmp_path):
    """The opposite direction, which the 234/234 diff oracle protects.

    A `sel=` must NOT see a node added by a later-loading mod: the engine applies
    this mod's diff before that mod loads, so the op is skipped.
    """
    ref = tmp_path / "reference"
    _write(ref / "libraries" / "wares.xml", "<wares/>")
    _write(ref / "index" / "macros.xml", "<index/>")

    late = tmp_path / "late"
    _write(late / "libraries" / "wares.xml",
           "<diff><add sel='/wares'><ware id='added_by_late'/></add></diff>")

    mod = tmp_path / "mod"
    _write(mod / "libraries" / "wares.xml",
           "<diff><replace sel=\"/wares/ware[@id='added_by_late']/@name\">x</replace></diff>")

    cfg = _merge.Config(reference=ref, overlays=(), final_overlays=(late,),
                        include_packed_dlc=False)
    report = _check.validate(mod, cfg)
    assert [f for f in report.findings if f.category == "sel" and f.severity == "error"], \
        ("the targeted ware is added by a LATER mod, so the engine skips this op — "
         "reporting it OK would be the FALSE OK the patch-time tree exists to prevent")

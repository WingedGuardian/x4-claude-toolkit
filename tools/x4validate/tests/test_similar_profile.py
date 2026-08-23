"""C4 (F8): x4similar reports HOW two near-duplicate ships differ.

The original plan was a `--with-handling` flag that changed the SCORE. Superseded
by the actual requirement: *"strictly, duplicate means same in every way. but the
idea was to be able to see if it is different, and then if so, how."*

So scoring is untouched — the candidate list and the 816-pair audit baseline hold
byte-for-byte — and each reported pair gains a per-axis DIFFERENCE PROFILE.

Why this is worth having, MEASURED over the 816 pairs at the default 0.85:
  - only **35** are identical on every shared numeric axis (the strict duplicates)
  - the other 781 differ, and the dominant axes are all handling ones the score
    never looks at: physics.drag.forward (624 pairs), physics.mass (514),
    physics.inertia.pitch/yaw (497 each), steeringcurve.point.value (482)
A ship macro exposes **34 numeric axes; only 5 are scored**, because `_WEIGHTS` is
an 8-key whitelist written before the flight model was visible at all (it was
0 rows until the depth-1 flatten was fixed on 2026-08-12).
"""

from lxml import etree

from x4validate import _similarity


def _macro(name, **props):
    body = "".join(f'<{k.split(".")[0]} {k.split(".")[1]}="{v}"/>' for k, v in props.items())
    return etree.fromstring(
        f'<macros><macro name="{name}" class="ship_s"><properties>'
        f'<purpose primary="fight"/>{body}</properties></macro></macros>'.encode())


A = _macro("ship_a", **{"hull.max": 1000, "people.capacity": 2, "cargo.max": 100,
                        "storage.unit": 5, "physics.mass": 8.0, "drag.forward": 2.0})
B_same = _macro("ship_b", **{"hull.max": 1000, "people.capacity": 2, "cargo.max": 100,
                             "storage.unit": 5, "physics.mass": 8.0, "drag.forward": 2.0})
B_handling = _macro("ship_c", **{"hull.max": 1000, "people.capacity": 2, "cargo.max": 100,
                                 "storage.unit": 5, "physics.mass": 16.0, "drag.forward": 2.0})


def _vec(root, name="s"):
    return _similarity.extract_ship_vector(root, name, f"assets/units/{name}.xml")


def test_unscored_axes_are_captured_on_the_vector():
    """`stats` stays the scored subset; `all_stats` carries everything numeric.
    Without this the profile has nothing to report — the flight model is exactly
    the part `_WEIGHTS` omits."""
    v = _vec(A)
    assert set(v.stats) <= set(_similarity._WEIGHTS), "scored set must not grow"
    assert "physics.mass" in v.all_stats, "unscored numeric axes must still be captured"
    assert "hull.max" in v.all_stats, "all_stats is a superset, not a complement"


def test_identical_ships_report_no_differences():
    """The strict reading of 'duplicate'. MEASURED: 35 of 816 real pairs."""
    prof = _similarity.difference_profile(_vec(A, "a"), _vec(B_same, "b"))
    assert prof.differing == []
    assert "physics.mass" in prof.identical
    assert prof.only_in_a == [] and prof.only_in_b == []


def test_a_handling_only_difference_is_reported_though_it_does_not_score():
    """physics.mass 8 -> 16 is invisible to the score and must be visible here."""
    a, b = _vec(A, "a"), _vec(B_handling, "b")
    assert _similarity.similarity(a, b).score == 1.0, (
        "precondition: the scored axes are identical, so the score is unchanged")
    prof = _similarity.difference_profile(a, b)
    keys = [d.key for d in prof.differing]
    assert keys == ["physics.mass"], keys
    assert abs(prof.differing[0].rel_diff - 0.5) < 1e-9
    assert (prof.differing[0].a_value, prof.differing[0].b_value) == (8.0, 16.0)


def test_axes_present_on_only_one_ship_are_reported_not_dropped():
    """An axis one ship has and the other lacks IS a difference. Silently
    intersecting the key sets would be the narrowing shape all over again."""
    lean = _macro("ship_lean", **{"hull.max": 1000, "people.capacity": 2,
                                  "cargo.max": 100, "storage.unit": 5})
    prof = _similarity.difference_profile(_vec(A, "a"), _vec(lean, "b"))
    assert "physics.mass" in prof.only_in_a
    assert prof.only_in_b == []


def test_differences_are_sorted_largest_first():
    far = _macro("ship_far", **{"hull.max": 1000, "people.capacity": 2, "cargo.max": 100,
                                "storage.unit": 5, "physics.mass": 9.0, "drag.forward": 20.0})
    prof = _similarity.difference_profile(_vec(A, "a"), _vec(far, "b"))
    rel = [d.rel_diff for d in prof.differing]
    assert rel == sorted(rel, reverse=True)
    assert prof.differing[0].key == "drag.forward"


def test_scoring_is_untouched_by_the_profile():
    """The 816-pair audit baseline must hold: profiling is additive reporting,
    never a scoring change."""
    a, b = _vec(A, "a"), _vec(B_handling, "b")
    pair = _similarity.similarity(a, b)
    assert set(pair.compared_keys) <= set(_similarity._WEIGHTS)
    assert "physics.mass" not in pair.compared_keys


def test_a_sub_one_percent_difference_is_not_printed_as_zero():
    """Real case from the live output: `physics.mass 205.27->204.245 (0%)` on a
    line that says "differs on 4". A finding that contradicts itself teaches the
    reader to ignore the whole line."""
    near = _macro("ship_near", **{"hull.max": 1000, "people.capacity": 2, "cargo.max": 100,
                                  "storage.unit": 5, "physics.mass": 8.04,
                                  "drag.forward": 2.0})
    prof = _similarity.difference_profile(_vec(A, "a"), _vec(near, "b"))
    line = _similarity.summarise_profile(prof)
    assert "(0%)" not in line, line
    assert "0.498%" in line, line


def test_render_shows_the_profile_without_breaking_the_first_two_lines():
    """`gates/similar_audit.py` parses the score row and reads the NEXT line for
    class/purpose/compared. The profile must be a third line, or the exhaustive
    audit stops resolving pairs."""
    a, b = _vec(A, "a"), _vec(B_handling, "b")
    pair = _similarity.similarity(a, b)
    out = _similarity.render([pair]).splitlines()
    row = [i for i, ln in enumerate(out) if "<->" in ln][0]
    assert out[row + 1].strip().startswith("class="), "line 2 must stay the detail line"
    assert "physics.mass" in out[row + 2], "line 3 should carry the difference profile"

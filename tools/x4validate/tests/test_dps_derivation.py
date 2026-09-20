"""Weapon DPS is COMPUTED from the bullet macro, not listed as an unmodelled gap.

WHY THIS FILE EXISTS. `dps` and its four per-channel siblings sat in `_DERIVED` -- the
"the engine derives this by following refs we only record" bucket -- on the finding that DPS
was weapon-type-dependent across six variants and not expressible as one formula. MEASURED
2026-09-20 against a live `groundtruth --contents` harvest, that was THREE MISSING INPUTS and
not three different physics:

  * `reload.time` is the RECIPROCAL SPELLING of `reload.rate` (174 / 119 / 0 both / 6 neither,
    over 299 bullet macros -- reading one spelling drops 40% of bullets);
  * `bullet.chargetime` is part of the firing period;
  * area damage folds into the SAME channel as its direct damage.

THE ONE BRANCH IS BEAM-VS-NOT, AND IT MUST NOT READ THE ENGINE. `_DERIVE` feeds the oracle
that compares our value against the engine, so a model taking `isbeamweapon` as an input
would be circular -- it would score well and prove nothing. `bullet.attach` is the store-side
discriminator, measured to agree with `isbeamweapon` 39 of 39.

These tests use SYNTHETIC bullets so each clause can be falsified on its own. The
whole-population check (38 of 39 exact against the real harvest) lives in the oracle, which
needs a live game; `gates/` owns that, and the numbers are recorded in BLIND-SPOTS and
KNOWLEDGEBASE.md.
"""
from __future__ import annotations

import pytest

from x4validate import _livecli as C


class _Con:
    """A stand-in for the store connection: `_store_props` is patched, so nothing here
    touches sqlite. Only identity matters."""


@pytest.fixture
def store(monkeypatch):
    """A tiny macro -> props store, with `_store_props` pointed at it."""
    data: dict[str, dict[str, str]] = {}
    monkeypatch.setattr(C, "_store_props", lambda con, name: data.get(name))
    return data


def _weapon(store, bullet_props, name="w_macro", bullet="b_macro"):
    store[name] = {"bullet.class": bullet}
    store[bullet] = {k: str(v) for k, v in bullet_props.items()}
    return store[name]


# --- the firing period, which is where every form difference actually lives ---- #

def test_reload_RATE_gives_its_reciprocal_as_the_period():
    assert C._firing_period({"reload.rate": "0.5"}) == pytest.approx(2.0)


def test_reload_TIME_is_the_SAME_QUANTITY_spelled_the_other_way():
    """★ The input whose absence made this look like a different weapon form. A bullet
    carries one spelling or the other; MEASURED over 299 bullet macros, never both."""
    assert C._firing_period({"reload.time": "2"}) == pytest.approx(2.0)


def test_reload_RATE_WINS_when_a_bullet_somehow_carries_both():
    """No bullet in the corpus carries both (0 of 299), so this pins the tie-break rather
    than describing the data -- an unspecified precedence is how a corpus change becomes a
    silent answer change."""
    assert C._firing_period({"reload.rate": "0.5", "reload.time": "99"}) == pytest.approx(2.0)


def test_a_CLIP_averages_the_reload_over_the_whole_magazine():
    """n shots at `base` apart, then one long reload, divided by n. Worked from the real
    numbers of bullet_gen_l_laser_01_mk1_macro: 3 shots at 0.5/s with a 10s reload is
    ((3-1)*2 + 10)/3 = 14/3 s per shot, i.e. the engine's reloadrate 3/14 = 0.2142857."""
    period = C._firing_period(
        {"reload.rate": "0.5", "ammunition.value": "3", "ammunition.reload": "10"})
    assert period == pytest.approx(14.0 / 3.0)
    assert 1.0 / period == pytest.approx(0.2142857, rel=1e-6)


def test_CHARGE_TIME_is_ADDED_to_the_period():
    """bullet_bor_l_beam_01_mk1_macro: reload.time 4.1 + chargetime 4 = 8.1s, and the engine
    reports reloadrate 0.12345678 = 1/8.1. Without this term it reads 1/4.1 -- twice too fast."""
    assert C._firing_period({"reload.time": "4.1", "bullet.chargetime": "4"}) == pytest.approx(8.1)


def test_a_NEGATIVE_chargetime_means_NONE_and_is_not_subtracted():
    """The engine spells "no charge" as -1. Treating it as a number would SHORTEN the period
    and inflate DPS on every weapon that has no charge at all -- which is most of them."""
    assert C._firing_period({"reload.time": "8", "bullet.chargetime": "-1"}) == pytest.approx(8.0)


def test_a_bullet_that_spells_NEITHER_rate_nor_time_REFUSES():
    """6 of 299 (spacesuit/story/scenario). A fabricated rate would be compared against the
    engine and could be called agreement."""
    assert C._firing_period({"damage.value": "100"}) is None


def test_a_ZERO_or_NEGATIVE_rate_REFUSES_rather_than_dividing():
    assert C._firing_period({"reload.rate": "0"}) is None
    assert C._firing_period({"reload.time": "0"}) is None


# --- the one branch: beam vs not ---------------------------------------------- #

def test_a_NON_BEAM_scales_damage_by_the_SHOT_RATE(store):
    props = _weapon(store, {"reload.rate": "0.75", "damage.value": "990",
                            "damage.noshield": "520", "bullet.attach": "0"})
    chans = C._dps_channels(_Con(), props)
    assert chans["hullshielddps"] == pytest.approx(742.5)      # 990 * 0.75
    assert chans["hullnoshielddps"] == pytest.approx(390.0)    # 520 * 0.75
    assert C._derive_dps(_Con(), props) == str(1132.5)         # the engine's own total


def test_a_BEAM_scales_damage_by_the_DUTY_CYCLE_instead(store):
    """★ THE BRANCH. bullet_atf_xl_mjolnir_macro: lifetime 7 within a period of 8, damage
    32000 + noshield 18000 -> the engine's 43750, not the 6250 a shot-rate model gives."""
    props = _weapon(store, {"reload.time": "8", "damage.value": "32000",
                            "damage.noshield": "18000", "bullet.lifetime": "7",
                            "bullet.attach": "1"})
    chans = C._dps_channels(_Con(), props)
    assert chans["hullshielddps"] == pytest.approx(28000.0)    # 32000 * 7/8
    assert C._derive_dps(_Con(), props) == str(43750)


def test_the_branch_reads_the_STORE_not_the_ENGINE(store):
    """⚠ THE CIRCULARITY GUARD. `_DERIVE` feeds the oracle that compares this value AGAINST
    the engine, so the beam test must come from the store. Here the bullet says beam
    (`bullet.attach=1`) while an engine-shaped `isbeamweapon=0` sits right next to it: if the
    model ever reads the engine field, the duty-cycle branch stops firing and this goes red."""
    props = _weapon(store, {"reload.time": "4", "damage.value": "40",
                            "bullet.lifetime": "4", "bullet.attach": "1",
                            "isbeamweapon": "0"})
    # duty 4/4 = 1.0, so a mining beam reports dps == damage exactly (MEASURED: it does)
    assert C._derive_dps(_Con(), props) == str(40)


def test_a_beam_with_NO_lifetime_reports_zero_not_the_shot_rate(store):
    """The twin for the branch: a beam's factor is lifetime/period, so a missing lifetime is
    a zero duty cycle. It must NOT silently fall back to the non-beam factor, which would
    give a confident wrong number instead of an obviously wrong one."""
    props = _weapon(store, {"reload.time": "4", "damage.value": "40", "bullet.attach": "1"})
    assert C._derive_dps(_Con(), props) == str(0)


# --- channels and multipliers -------------------------------------------------- #

def test_AREA_damage_folds_into_the_SAME_channel_as_its_direct_damage(store):
    """bullet_bor_m_flak_01_mk1_macro: hull+shield 100 direct and 615 area at reloadrate
    0.888..., which the engine reports as 635.5555 -- i.e. (100+615)*rate, one channel."""
    props = _weapon(store, {"reload.rate": "1", "ammunition.value": "4",
                            "ammunition.reload": "1.5", "damage.value": "100",
                            "areadamage.value": "615", "bullet.attach": "0"})
    chans = C._dps_channels(_Con(), props)
    assert chans["hullshielddps"] == pytest.approx(635.5555, rel=1e-5)


def test_area_damage_ALONE_still_produces_a_channel(store):
    """The twin: a gatling with `areadamage.shield` and no `damage.shield` reports a nonzero
    shieldonlydps. Requiring a direct damage first would zero it."""
    props = _weapon(store, {"reload.time": "0.2", "areadamage.shield": "45",
                            "bullet.attach": "0"})
    assert C._dps_channels(_Con(), props)["shieldonlydps"] == pytest.approx(225.0)


def test_bullet_amount_and_barrelamount_BOTH_multiply(store):
    """⚠ Left out of the first model because the first worked example had both at 1 --
    UNCONSTRAINED data read as "not in the formula". bullet_xen_l_waver_macro has
    barrelamount 9 and the engine's dps is exactly 9x the single-barrel figure."""
    base = {"reload.rate": "0.035", "damage.value": "30500", "bullet.lifetime": "5",
            "bullet.attach": "1"}
    one = C._dps_channels(_Con(), _weapon(store, base, "w1", "b1"))["hullshielddps"]
    nine = C._dps_channels(
        _Con(), _weapon(store, {**base, "bullet.barrelamount": "9"}, "w9", "b9"))["hullshielddps"]
    assert nine == pytest.approx(one * 9)
    assert nine == pytest.approx(48037.5, rel=1e-6)      # the engine's own value


def test_a_ZERO_channel_is_reported_as_zero_not_as_a_gap(store):
    """Unlike storagecapacity, where a zero would be fabricated, here zero is the engine's
    OWN answer (it reports shieldonlydps=0 on 24 of 39). Returning None would turn a correct
    agreement into an unmapped field and make the oracle look worse than it is."""
    props = _weapon(store, {"reload.rate": "1", "damage.value": "100", "bullet.attach": "0"})
    assert C._DERIVE["shieldonlydps"](_Con(), props) == str(0)


def test_dps_is_the_SUM_of_the_channels(store):
    props = _weapon(store, {"reload.rate": "0.2142857", "damage.value": "9350",
                            "damage.shield": "4000", "bullet.attach": "0"})
    chans = C._dps_channels(_Con(), props)
    assert float(C._derive_dps(_Con(), props)) == pytest.approx(sum(chans.values()))


# --- refusing ------------------------------------------------------------------ #

def test_a_weapon_with_NO_bullet_class_REFUSES(store):
    """6 of the 45 harvested macros are decorative `*_video_macro` with no bullet at all."""
    store["w_macro"] = {"identification.name": "a video prop"}
    assert C._derive_dps(_Con(), store["w_macro"]) is None


def test_a_bullet_MISSING_FROM_THE_STORE_REFUSES(store):
    store["w_macro"] = {"bullet.class": "bullet_that_is_not_there_macro"}
    assert C._derive_dps(_Con(), store["w_macro"]) is None


def test_an_UNMODELLABLE_bullet_REFUSES_rather_than_reporting_zero(store):
    """A bullet with damage but no rate at all. Zero would be compared against the engine
    and could be called agreement on a weapon that does plenty of damage."""
    props = _weapon(store, {"damage.value": "500", "bullet.attach": "0"})
    assert C._derive_dps(_Con(), props) is None
    assert C._DERIVE["hullshielddps"](_Con(), props) is None


# --- the registry itself ------------------------------------------------------- #

def test_dps_is_no_longer_listed_as_an_unmodelled_gap():
    """A field cannot be both "we cannot compute this" and "here is how we compute it".
    `test_derived_fields_are_named_not_folded_into_unmapped` polices the other direction;
    this pins the move itself, so a revert has to be deliberate."""
    for f in ("dps", "hullshielddps", "shieldonlydps", "hullnoshielddps", "hullonlydps"):
        assert f in C._DERIVE, f"{f} lost its traversal"
        assert f not in C._DERIVED, f"{f} is claimed by BOTH registries"


def test_sustaineddps_is_STILL_an_unmodelled_gap():
    """The twin that stops this becoming "move everything". `sustaineddps` folds in the heat
    model -- overheat, cooling rate, re-enable -- which the shot-rate formula does not
    reproduce, so it stays named as a gap rather than being quietly included."""
    assert "sustaineddps" in C._DERIVED
    assert "sustaineddps" not in C._DERIVE


# --- the SALVO transform: the engine totals a salvo, the store holds one warhead ----

def test_per_salvo_divides_the_engine_total_by_the_missile_count():
    """MEASURED 2026-09-20 on missile_gen_s_swarm_01_mk1_macro: the engine answers
    explosiondamage 1680 while the store holds explosiondamage.value 210 and
    missile.amount 8. Mapped as `identity`, the oracle reported a DISAGREEMENT against
    our own store -- a false red, and the only one in the fixture, which was then
    attributed in the release notes to the dps promotion instead."""
    f = C._CONTEXT_TRANSFORMS["per_salvo"]
    assert f(1680.0, {"missile.amount": "8", "explosiondamage.value": "210"}) == 210.0


def test_TWIN_a_single_missile_is_left_alone():
    """amount=1 is the common case and must pass through unchanged, or every non-salvo
    missile would break instead."""
    f = C._CONTEXT_TRANSFORMS["per_salvo"]
    assert f(5000.0, {"missile.amount": "1"}) == 5000.0
    assert f(5000.0, {}) == 5000.0, "a missing amount must not change the value"


def test_TWIN_a_zero_or_unparsable_amount_does_not_raise():
    """A refusal is an answer; a ZeroDivisionError inside the oracle is not."""
    f = C._CONTEXT_TRANSFORMS["per_salvo"]
    assert f(5000.0, {"missile.amount": "0"}) == 5000.0
    assert f(5000.0, {"missile.amount": "not a number"}) == 5000.0

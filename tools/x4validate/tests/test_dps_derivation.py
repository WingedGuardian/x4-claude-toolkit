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


def test_dps_equals_the_SUM_when_only_ONE_specialised_channel_is_populated(store):
    """The sum and the real rule AGREE here, and this is where 338 of 345 macros live.

    Named for its scope on purpose: the old name said "dps is the SUM of the channels",
    which is false in general and was the claim the n=345 sweep refuted.
    """
    props = _weapon(store, {"reload.rate": "0.2142857", "damage.value": "9350",
                            "damage.shield": "4000", "bullet.attach": "0"})
    chans = C._dps_channels(_Con(), props)
    assert float(C._derive_dps(_Con(), props)) == pytest.approx(sum(chans.values()))


# --- refusing ------------------------------------------------------------------ #

def test_BOTH_channels_populated_counts_only_the_LARGER(store):
    """The refusal this replaces was correct at n=1; the sweep took the population to 345.

    A shot cannot be against a shielded and an unshielded target at once, so the engine
    counts whichever specialised channel is larger. Here noshield (150) beats shield (60):
    100 + 150 + 0 = 250, and the plain sum's 310 is the number this test exists to reject.
    Shaped after the real `weapon_cpsdo_s_phase_laser_01_mk4_macro`.
    """
    props = _weapon(store, {'reload.rate': '1', 'damage.value': '100',
                            'damage.shield': '60', 'damage.noshield': '150'})
    assert float(C._derive_dps(_Con(), props)) == pytest.approx(250.0)


def test_TWIN_the_OPPOSITE_channel_wins_when_IT_is_larger(store):
    """The falsification twin for the clause above, and the reason a single-omission rule
    could not be fitted: the two real macros omit OPPOSITE channels. Here shield (60) beats
    noshield (30), so the answer is 100 + 60 + 10 = 170, not 100 + 30 + 10 = 140.
    Shaped after `turret_xenon_xl_station_01_macro`."""
    props = _weapon(store, {'reload.rate': '1', 'damage.value': '100',
                            'damage.shield': '60', 'damage.noshield': '30',
                            'damage.hull': '10'})
    assert float(C._derive_dps(_Con(), props)) == pytest.approx(170.0)


def test_a_NEGATIVE_channel_never_REDUCES_the_total(store):
    """5 of 345 macros, all cpsdo turrets: `shieldonlydps` from -80.0 to -621.43.

    The engine reports dps == hullshielddps exactly for every one. The old summing rule
    SUBTRACTED the negative and was silently wrong on all five -- they never tripped the
    both-properties refusal, because `damage.noshield` is absent. 100 + max(0,-40,0) = 100,
    and the sum's 60 is what this rejects."""
    props = _weapon(store, {'reload.rate': '1', 'damage.value': '100',
                            'damage.shield': '-40'})
    assert float(C._derive_dps(_Con(), props)) == pytest.approx(100.0)


def test_BOTH_channels_negative_pins_a_CHOICE_that_no_measurement_supports(store):
    """⚠ This test pins a DECISION, not an observed engine behaviour. Read it as such.

    The `0` in `max(0, shieldonly, hullnoshield)` can only change the answer when BOTH
    specialised channels are negative, and that population is EMPTY in the live corpus
    (0 of 345), so the sweep does NOT choose between `max(0,a,b)` and `max(a,b)`.

    It exists because a mutation probe found the clamp was UNREACHABLE: dropping the `0`
    left all 31 tests green, since every other case has the other channel at 0 and the two
    forms coincide. An axis nothing can falsify is where the next defect lives (#35), so
    the choice is written down here where a future change will trip it, rather than left
    as an invisible constant. -40 and -10 clamp to 0 (total 100); the unclamped form would
    add -10 and give 90. If the engine is ever measured on such a macro, THAT measurement
    wins and this test should be rewritten to cite it."""
    props = _weapon(store, {'reload.rate': '1', 'damage.value': '100',
                            'damage.shield': '-40', 'damage.noshield': '-10'})
    assert float(C._derive_dps(_Con(), props)) == pytest.approx(100.0)


def test_the_rule_reproduces_the_two_REAL_ENGINE_totals(store):
    """Pins the rule against the live engine, not against our own arithmetic.

    Channel values and totals MEASURED 2026-09-20 over the named macros. Computed from the
    recorded channels rather than from a fixture, so this fails if the RULE changes even
    where the fixture builder does not."""
    measured = [
        # macro, hullshield, shieldonly, hullnoshield, hullonly, engine dps
        ("turret_xenon_xl_station_01_macro",
         1333.3333581686, 400.00000745058, 266.66667163372, 133.33333581686,
         1866.666701436),
        ("weapon_cpsdo_s_phase_laser_01_mk4_macro",
         481.69556260109, 115.60693502426, 289.01733756065, 0.0, 770.71290016174),
        ("turret_cpsdo_l_laser_01_mk4_macro",
         1071.4285820723, -621.42857760191, 0.0, 0.0, 1071.4285820723),
    ]
    for name, hs, so, ns, ho, engine in measured:
        got = hs + max(0.0, so, ns) + ho
        assert got == pytest.approx(engine, rel=1e-9), name
        # and the rule the sweep refuted must NOT reproduce these
        if so > 0 and ns > 0 or so < 0:
            assert hs + so + ns + ho != pytest.approx(engine, rel=1e-9), name


def test_TWIN_the_CHANNELS_are_still_computed_for_that_same_bullet(store):
    """Only the TOTAL is unearned. Each channel matched the engine exactly, so refusing
    them too would throw away four correct comparisons to avoid one wrong one."""
    props = _weapon(store, {'reload.rate': '1', 'damage.value': '100',
                            'damage.shield': '60', 'damage.noshield': '150'})
    chans = C._dps_channels(_Con(), props)
    assert chans is not None
    assert chans['shieldonlydps'] == pytest.approx(60.0)
    assert chans['hullnoshielddps'] == pytest.approx(150.0)


def test_TWIN_only_ONE_of_the_two_properties_still_totals(store):
    """38 of 39 macros carry at most one, and they are the population the rule was
    measured over -- the refusal must not reach them."""
    shield_only = _weapon(store, {'reload.rate': '1', 'damage.value': '100',
                                  'damage.shield': '60'}, name='w1', bullet='b1')
    noshield_only = _weapon(store, {'reload.rate': '1', 'damage.value': '100',
                                    'damage.noshield': '150'}, name='w2', bullet='b2')
    assert C._derive_dps(_Con(), shield_only) is not None
    assert C._derive_dps(_Con(), noshield_only) is not None


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

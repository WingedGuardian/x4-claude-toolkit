"""Full-depth <properties> flattening (docs/BLIND-SPOTS.md F1, F4, F5, F6).

Until 2026-08-12 `_effective.flatten_with_prov` and `_stats.flatten_macro_props`
walked exactly ONE level of children, which made the entire flight model
(`physics/drag`, `physics/inertia`, `jerk`, `steeringcurve`) and ware recipe
inputs (`production/primary/ware`) invisible to x4effective and x4stats, while
the merged tree carried them correctly all along.

The load-bearing guarantee is that the fix is purely ADDITIVE: depth-1 keys must
come out byte-identical, or every stored value silently re-keys.
"""

from lxml import etree

from x4validate import _effective, _merge, _stats
from x4validate._provenance import BASE, Recorder


SHIP = (
    '<macros><macro name="ship_x_macro" class="ship_s"><properties>'
    '<hull max="4000"/>'
    '<physics mass="6">'
    '  <inertia pitch="0.9" yaw="0.9" roll="1.1"/>'
    '  <drag forward="2.0" reverse="6" pitch="4.62"/>'
    '</physics>'
    '<steeringcurve><point position="0" value="1"/><point position="1" value="2"/></steeringcurve>'
    '</properties></macro></macros>')


def _rows(xml):
    root = etree.fromstring(xml)
    rec = Recorder(BASE)
    macro = root.find("macro")
    props = macro.find("properties")
    out = _effective.flatten_with_prov(
        macro, rec, no_recurse=(props,) if props is not None else ())
    out += _effective.flatten_with_prov(props, rec, child_scope=props)
    return {prop: value for prop, value, _num, _chain in out}


def test_depth_two_and_three_attrs_are_flattened():
    r = _rows(SHIP)
    assert r["physics.mass"] == "6"                 # depth 1, unchanged
    assert r["physics.drag.forward"] == "2.0"       # depth 2, previously invisible
    assert r["physics.inertia.roll"] == "1.1"


def test_depth_one_keys_are_unchanged_by_the_recursion():
    """The golden-vector guard: recursion must ADD keys, never re-key existing ones."""
    r = _rows(SHIP)
    assert r["hull.max"] == "4000"
    assert r["@name"] == "ship_x_macro"
    assert r["@class"] == "ship_s"


def test_repeated_grandchildren_are_disambiguated_positionally():
    r = _rows(SHIP)
    # <point> repeats with no id/name, so it takes the zero-based positional key
    # -- the same grammar the depth-1 walk has always used for repeated siblings.
    assert r["steeringcurve.point[0].value"] == "1"
    assert r["steeringcurve.point[1].value"] == "2"


def test_properties_subtree_is_not_emitted_twice():
    """`extract_macros` walks a macro twice (whole macro, then scoped to
    <properties>). Without `no_recurse` the second walk's rows reappeared under a
    `properties.` prefix -- MEASURED 67,333 duplicate rows, 23.1% of the store."""
    r = _rows(SHIP)
    assert not [k for k in r if k.startswith("properties.")]


def test_recursion_depth_guard_reports_rather_than_truncating_silently():
    deep = "<properties>" + "<a>" * 12 + '<leaf v="1"/>' + "</a>" * 12 + "</properties>"
    root = etree.fromstring(f'<macro name="m">{deep}</macro>')
    props = root.find("properties")
    _effective.truncated_props.clear()
    _effective.flatten_with_prov(props, Recorder(BASE), child_scope=props)
    assert _effective.truncated_props, "hitting the guard must be recorded, never silent"
    _effective.truncated_props.clear()


def test_ware_recipe_inputs_are_flattened():
    """`production/primary/ware` is depth 3 -- the actual recipe, invisible before."""
    root = etree.fromstring(
        '<wares><ware id="hullparts"><price min="1"/>'
        '<production time="900" method="default"><primary>'
        '<ware ware="energycells" amount="80"/>'
        '<ware ware="graphene" amount="40"/></primary></production>'
        '</ware></wares>')
    rec = Recorder(BASE)
    rows = {p: v for p, v, _n, _c in
            _effective.flatten_with_prov(root.find("ware"), rec)}
    # Repeated <ware> siblings take the keyed form via _child_ident's "ware" attr;
    # a single non-repeating child stays bare (production.primary...), which is
    # why this fixture ships two inputs.
    assert rows["production.primary.ware[energycells].amount"] == "80"
    assert rows["production.primary.ware[graphene].amount"] == "40"
    assert rows["price.min"] == "1"          # depth 1 still intact


# --- x4stats / x4similar side (same defect, separate implementation) ----------

def test_stats_flatten_is_depth_recursive():
    v = _stats.flatten_macro_props(etree.fromstring(SHIP))
    assert v["physics.mass"] == 6.0
    assert v["physics.drag.forward"] == 2.0      # previously absent
    assert v["hull.max"] == 4000.0               # depth 1 unchanged
    assert v["class"] == "ship_s"


def test_iter_macros_sees_every_macro_not_just_the_first():
    """`_effective`/`_compat` read all macros via `iter`; `_stats`/`_similarity`
    read only the first. Two tools disagreeing about a file's contents is how the
    nested-door defect started, so they now share one reader."""
    root = etree.fromstring(
        '<macros><macro name="a" class="ship_s"><properties><hull max="1"/></properties></macro>'
        '<macro name="b" class="ship_m"><properties><hull max="2"/></properties></macro></macros>')
    assert [m.get("name") for m in _stats.iter_macros(root)] == ["a", "b"]
    assert _stats.flatten_props_of(_stats.iter_macros(root)[1])["hull.max"] == 2.0


# --- F4: packed mini-DLC enumeration -----------------------------------------

def test_packed_dlc_assets_are_enumerated(monkeypatch, tmp_path):
    """A DLC with no loose assets/ on disk is a PACKED mini-DLC; its macro files
    must still be enumerated (via _cat), not silently skipped.

    Real cost of the old `continue`: 26 of 40 mini-DLC macros absent from the
    store, including the Envoy Pack's disabler/gatling/shieldpierce weapons.
    """
    ref = tmp_path / "reference"
    (ref / "assets").mkdir(parents=True)
    (ref / "assets" / "base_macro.xml").write_bytes(b"<macros/>")
    packed = tmp_path / "ego_dlc_mini_99"
    packed.mkdir()

    cfg = _merge.Config(reference=ref)
    monkeypatch.setattr(type(cfg), "dlc_dirs", lambda self: [packed], raising=False)
    monkeypatch.setattr(type(cfg), "packed_dlc_names",
                        lambda self: {"ego_dlc_mini_99"}, raising=False)
    monkeypatch.setattr(_effective._cat, "mod_vfs",
                        lambda p, **kw: ["assets/props/weapon_x_macro.xml",
                                         "assets/notes.txt",
                                         "libraries/wares.xml"])

    out = _effective.reference_vpaths(cfg, "*_macro.xml")
    assert "extensions/ego_dlc_mini_99/assets/props/weapon_x_macro.xml" in out
    assert "assets/base_macro.xml" in out            # loose path still works
    assert not any("notes.txt" in k for k in out)    # pattern still filters
    assert not any("wares.xml" in k for k in out)    # assets/-only still holds


def test_unpacked_dlc_without_assets_is_not_invented(monkeypatch, tmp_path):
    """Only PACKED dlc take the _cat route -- a non-packed dir with no assets/
    must still be skipped, or a missing unpack would silently fabricate vpaths."""
    ref = tmp_path / "reference"
    (ref / "assets").mkdir(parents=True)
    empty = tmp_path / "ego_dlc_real"
    empty.mkdir()
    cfg = _merge.Config(reference=ref)
    monkeypatch.setattr(type(cfg), "dlc_dirs", lambda self: [empty], raising=False)
    monkeypatch.setattr(type(cfg), "packed_dlc_names", lambda self: set(), raising=False)
    monkeypatch.setattr(_effective._cat, "mod_vfs",
                        lambda p, **kw: ["assets/should_not_appear_macro.xml"])
    assert _effective.reference_vpaths(cfg, "*_macro.xml") == {}


# --- F5: admit macro files by content, not filename ---------------------------

def test_macro_file_admitted_by_content_when_filename_does_not_match():
    """VRO ships live macro files not named *_macro.xml (`bullet_ter_m_graviton`,
    and two with a `_marco.xml` typo). The engine loads them via index/macros.xml,
    so a filename rule loses real balance data."""
    vpath = "assets/fx/weaponfx/macros/bullet_ter_m_graviton.xml"
    touch = {vpath: [("vro", "REAL")]}

    def macro_file(base, real):
        return b'<macros><macro name="bullet_ter_m_graviton" class="bullet"/></macros>'

    def plain_file(base, real):
        return b"<components><component name='x'/></components>"

    orig = _effective._cat.read_path
    try:
        _effective._cat.read_path = macro_file
        assert _effective._defines_macro({"vro": "BASE"}, touch[vpath]) is True
        _effective._cat.read_path = plain_file
        assert _effective._defines_macro({"vro": "BASE"}, touch[vpath]) is False
    finally:
        _effective._cat.read_path = orig


def test_unreadable_candidate_fails_OPEN_not_closed():
    """"I could not read it" is not "it holds no macros". Failing closed would be
    the exact silent-narrowing defect this whole change removes."""
    def boom(base, real):
        raise OSError("locked")

    orig = _effective._cat.read_path
    try:
        _effective._cat.read_path = boom
        assert _effective._defines_macro({"m": "BASE"}, [("m", "x.xml")]) is True
    finally:
        _effective._cat.read_path = orig


# --- F34: base_vpaths is the WHOLE tree; reference_vpaths is its assets subset --

def _mini_dlc_cfg(monkeypatch, tmp_path):
    """reference/ with content in and out of assets/, plus one PACKED mini-DLC."""
    ref = tmp_path / "reference"
    (ref / "assets" / "props").mkdir(parents=True)
    (ref / "libraries").mkdir(parents=True)
    (ref / "maps" / "xu_ep2_universe").mkdir(parents=True)
    (ref / "assets" / "props" / "weapon_a_macro.xml").write_bytes(b"<macros/>")
    (ref / "libraries" / "character_macros.xml").write_bytes(b"<macros/>")
    (ref / "maps" / "xu_ep2_universe" / "clusters.xml").write_bytes(b"<macros/>")

    packed = tmp_path / "ego_dlc_mini_99"
    packed.mkdir()
    cfg = _merge.Config(reference=ref)
    monkeypatch.setattr(type(cfg), "dlc_dirs", lambda self: [packed], raising=False)
    monkeypatch.setattr(type(cfg), "packed_dlc_names",
                        lambda self: {"ego_dlc_mini_99"}, raising=False)
    monkeypatch.setattr(_effective._cat, "mod_vfs",
                        lambda p, **kw: ["assets/units/ship_z_macro.xml",
                                         "libraries/god.xml",
                                         "md/setup.xml"])
    return cfg


def test_base_vpaths_covers_the_whole_tree_loose_and_packed(monkeypatch, tmp_path):
    """x4eff indexes the whole game, not just `assets/`. The loose-only form held
    23 of 142 mini-DLC documents; the assets-only form would ALSO have dropped
    every `libraries/`, `maps/`, `index/` and `md/` document in the base tree."""
    cfg = _mini_dlc_cfg(monkeypatch, tmp_path)
    out = _effective.base_vpaths(cfg, "*.xml")

    # loose, outside assets/ -- invisible to reference_vpaths by design
    assert "libraries/character_macros.xml" in out
    assert "maps/xu_ep2_universe/clusters.xml" in out
    # packed, outside assets/ -- invisible to BOTH of the old walks
    assert "extensions/ego_dlc_mini_99/libraries/god.xml" in out
    assert "extensions/ego_dlc_mini_99/md/setup.xml" in out
    # and the ordinary cases still hold
    assert "assets/props/weapon_a_macro.xml" in out
    assert "extensions/ego_dlc_mini_99/assets/units/ship_z_macro.xml" in out


def test_reference_vpaths_is_exactly_the_assets_subset(monkeypatch, tmp_path):
    """F3's scope is a documented decision, and this pins that the refactor to
    `base_vpaths` did not quietly widen or narrow it.

    MEASURED against the live corpus at the moment of the refactor: both call
    patterns were SET-EQUAL before and after -- 4,002 for `*_macro.xml` and 7,551
    for `*.xml`, 0 added, 0 removed, 0 changed.
    """
    cfg = _mini_dlc_cfg(monkeypatch, tmp_path)
    base = _effective.base_vpaths(cfg, "*.xml")
    ref = _effective.reference_vpaths(cfg, "*.xml")

    assert ref == {k: v for k, v in base.items() if _effective._under_assets(k)}
    assert set(ref) < set(base), "the filter must actually exclude something"
    assert not any("/libraries/" in k or k.startswith("libraries/") for k in ref)
    assert not any("/md/" in k or k.startswith("md/") for k in ref)


def test_under_assets_is_exact_not_a_substring_match():
    """`"assets/" in low` also matches `libraries/assets/...`. A filter that is
    NEARLY the old walk is how a documented scope quietly becomes a different one."""
    assert _effective._under_assets("assets/units/x.xml")
    assert _effective._under_assets("extensions/ego_dlc_mini_01/assets/units/x.xml")
    assert not _effective._under_assets("libraries/assets/decoy.xml")
    assert not _effective._under_assets("extensions/ego_dlc_x/libraries/assets/d.xml")
    assert not _effective._under_assets("md/setup.xml")


# --- F33 attr axis: a repeated bracket must not collapse onto one key ---------

def _flatten_props(xml: str) -> list[tuple[str, str]]:
    """(prop, value) rows for a fragment, through the real walker."""
    el = etree.fromstring(xml)
    rec = _effective.Recorder()
    rows: list = []
    _effective._walk_props(el, rec, "", 1, rows)
    return [(p, v) for p, v, _num, _chain in rows]


def test_siblings_sharing_a_bracket_get_distinct_keys():
    """THE FIX. The discriminator is an ATTRIBUTE, and attributes repeat.

    Real worst case, MEASURED: `faction/player` had EIGHT rows under
    `licences.licence[generaluseequipment].factions`, holding eight DIFFERENT
    faction lists. `select value ... where prop=?` + `fetchone()` returned an
    arbitrary one of them, and nothing indicated there were seven more.
    """
    rows = _flatten_props(
        '<licences>'
        '  <licence type="generaluseequipment" factions="argon"/>'
        '  <licence type="generaluseequipment" factions="boron"/>'
        '  <licence type="generaluseequipment" factions="teladi"/>'
        '</licences>')
    props = [p for p, _ in rows if p.endswith(".factions")]
    assert len(props) == len(set(props)), f"keys still collide: {props}"
    assert props == ["licence[generaluseequipment].factions",
                     "licence[generaluseequipment#1].factions",
                     "licence[generaluseequipment#2].factions"]
    assert [v for p, v in rows if p.endswith(".factions")] == ["argon", "boron", "teladi"]


def test_the_first_claimant_keeps_the_original_key():
    """Collision-ONLY. Indexing every key positionally would have rewritten
    358,415 rows (61.6%) to repair 1,071 (0.18%), broken the golden-vector
    regression guard, and invalidated every stored baseline for nothing."""
    rows = _flatten_props(
        '<licences>'
        '  <licence type="a" factions="x"/>'
        '  <licence type="b" factions="y"/>'
        '</licences>')
    assert [p for p, _ in rows] == ["licence[a].type", "licence[a].factions",
                                    "licence[b].type", "licence[b].factions"]


def test_an_only_child_is_still_keyed_by_bare_tag():
    """The `tag_counts[tag] > 1` gate is untouched -- a lone child must not
    suddenly acquire a bracket."""
    assert _flatten_props('<physics><drag forward="1.5"/></physics>') == [
        ("drag.forward", "1.5")]


def test_identless_siblings_keep_their_original_positional_numbering():
    """The pre-existing ident-less path is byte-identical -- 0/1/2, not 0/0#1/0#2."""
    rows = _flatten_props('<a><b v="1"/><b v="2"/><b v="3"/></a>')
    assert [p for p, _ in rows] == ["b[0].v", "b[1].v", "b[2].v"]

"""C2: the 16 flat libraries/*.xml registries (docs/BLIND-SPOTS.md F2).

`_extract_registry` read `el.get("id")` and SKIPPED SILENTLY when absent. MEASURED:
7 of 18 registries key by `@name` (shipgroups 183, icons 1,372, effects 917,
region_definitions 160, roomgroups 31, stationgroups 65) and mapdefaults by
`@macro`. Adding them as planned would have indexed ZERO entities for those seven
while reporting success -- the exact defect this whole effort exists to remove.

So the key attribute is a parameter, AND a registry that yields nothing has to say
so. All 18 were verified to merge, to be 100% keyed on the attribute claimed here,
and to be patched by 4-28 real mods each.
"""

import pytest
from lxml import etree

from x4validate import _effective
from x4validate._provenance import Recorder


def _reg(xml, kind="shipgroup", child="group", key="name", klass="tags"):
    root = etree.fromstring(xml)
    return _effective._extract_registry(root, kind, child, klass, "libraries/x.xml",
                                        Recorder(), key_attr=key)


def test_a_registry_keyed_by_name_is_indexed():
    ents = _reg('<groups><group name="g1" tags="a"/><group name="g2" tags="b"/></groups>')
    assert [e.name for e in ents] == ["g1", "g2"]
    assert ents[0].kind == "shipgroup"


def test_the_default_key_is_still_id_so_wares_and_jobs_are_unchanged():
    root = etree.fromstring('<wares><ware id="ore" group="minerals"/></wares>')
    [e] = _effective._extract_registry(root, "ware", "ware", "group",
                                       "libraries/wares.xml", Recorder())
    assert e.name == "ore"


def test_a_registry_that_yields_NOTHING_raises_instead_of_passing_quietly():
    """The load-bearing guard. Wrong key attr => zero entities => a confident empty
    answer downstream, with nothing anywhere saying the name was wrong."""
    with pytest.raises(ValueError, match="yielded no entities"):
        _reg('<groups><group name="g1"/></groups>', key="id")


def test_an_empty_registry_FILE_is_not_treated_as_a_misconfiguration():
    """A file that genuinely has no children is different from a key that matches
    nothing: the first is data, the second is a bug. They must not be conflated."""
    ents = _reg("<groups/>")
    assert ents == []


def test_every_planned_registry_key_matches_the_real_vanilla_file():
    r"""Pins the measured key-attr table against reference\ so a wrong entry cannot
    silently ship. Skips cleanly when the reference tree is not configured."""
    from pathlib import Path
    from x4validate import _paths
    ref = _paths.reference()
    if ref is None or not (ref / "libraries").is_dir():
        pytest.skip("reference tree not configured")
    for kind, (vpath, child, klass, key) in _effective.LIBRARY_REGISTRIES.items():
        f = ref / vpath
        if not f.is_file():
            continue
        root = etree.parse(str(f)).getroot()
        els = root.findall(child)
        if not els:
            pytest.fail(f"{kind}: child tag {child!r} matches nothing in {vpath}")
        keyed = sum(1 for e in els if e.get(key))
        assert keyed == len(els), (
            f"{kind}: {len(els) - keyed} of {len(els)} <{child}> lack @{key} "
            f"— wrong key attribute would index them as nothing")

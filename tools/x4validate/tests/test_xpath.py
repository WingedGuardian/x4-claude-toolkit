"""The x4cat spike cases — lxml must get these right where x4cat does not."""

from lxml import etree

from x4validate import _xpath

BASE = etree.fromstring(b"""<wares>
  <ware id="ore" price_average="120"><price min="80" average="120" max="160"/></ware>
  <ware id="energycells" price_average="16"/>
</wares>""")


def m(xp):
    return _xpath.matches(BASE, xp).matched


def test_descendant_idiom_matches():          # x4cat FALSE-NEGATIVES this
    assert m("//ware[@id='ore']")


def test_descendant_attribute_matches():
    assert m("//ware[@id='ore']/@price_average")


def test_nested_descendant_matches():
    assert m("//ware[@id='ore']/price/@average")


def test_absolute_path_matches():
    assert m("/wares/ware[@id='ore']")


def test_missing_id_does_not_match():
    assert not m("//ware[@id='nonexistent']")


def test_typo_attribute_does_not_match():
    assert not m("//ware[@id='ore']/@prce_average")


def test_invalid_xpath_is_flagged_not_silently_false():
    r = _xpath.matches(BASE, "//ware[")
    assert r.error and not r.matched

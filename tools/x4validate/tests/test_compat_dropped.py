"""F7: an unreadable content.xml must not silently cost a mod its dependencies.

Dependencies force a mod to load EARLIER, so losing them changes the computed
load order -- which decides every collision winner x4compat reports. MEASURED
2026-08-12: 0 of 122 installed manifests are malformed, so this is latent; the
cost is zero today and unbounded the day it isn't.
"""

from pathlib import Path

from x4validate import _compat


def test_malformed_manifest_is_reported_not_swallowed(tmp_path):
    mod = tmp_path / "brokenmod"
    mod.mkdir()
    (mod / "content.xml").write_text('<content id="x"><dependency id="y"')  # truncated
    dropped: list[str] = []
    mod_id, deps = _compat._mod_deps(mod, dropped)
    assert deps == []
    assert dropped and "brokenmod" in dropped[0] and "will not parse" in dropped[0]


def test_missing_manifest_is_reported(tmp_path):
    mod = tmp_path / "nomanifest"
    mod.mkdir()
    dropped: list[str] = []
    _compat._mod_deps(mod, dropped)
    assert dropped and "no content.xml" in dropped[0]


def test_healthy_manifest_reports_nothing(tmp_path):
    mod = tmp_path / "goodmod"
    mod.mkdir()
    (mod / "content.xml").write_text(
        '<content id="good"><dependency id="dep_a"/></content>')
    dropped: list[str] = []
    mod_id, deps = _compat._mod_deps(mod, dropped)
    assert (mod_id, deps) == ("good", ["dep_a"])
    assert dropped == []


def test_compute_load_order_propagates_the_channel(tmp_path):
    a = tmp_path / "a"; a.mkdir()
    (a / "content.xml").write_text('<content id="a"/>')
    b = tmp_path / "b"; b.mkdir()
    (b / "content.xml").write_text("<content id=")           # malformed
    mods = [{"folder": "a", "path": str(a)}, {"folder": "b", "path": str(b)}]
    dropped: list[str] = []
    order = _compat.compute_load_order(mods, dropped)
    assert set(order) == {"a", "b"}          # still ordered, just degraded
    assert any("b" in d for d in dropped)
    # Default (no channel passed) must not raise -- back-compat for other callers.
    assert _compat.compute_load_order(mods)

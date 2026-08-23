"""A corpus scan must be unable to report a zero over a population of zero.

The seventh instance of this workspace's most-repeated bug (docs/BLIND-SPOTS.md): an
ad-hoc sweep called `etree.fromstring()` on roots `iter_mod_xml` had already parsed,
raised TypeError on every one of 4,391 files, swallowed it in `except Exception:
continue`, and reported "0 dangling across 115 mods". The truth was 3, in 1 mod.

`Coverage` already answered "how much of ONE mod did I see". `CorpusScan` answers the
question that was actually being got wrong -- did the sweep look at anything at all --
and refuses to render a finding when the answer is no.
"""

from pathlib import Path

import pytest

from x4validate import _scan


def _mod(root: Path, name: str, files: dict[str, str]) -> Path:
    """A mod is a folder WITH a content.xml — that is what the engine loads and what
    `_registry.scan_installed` (the single source of "what is installed") requires."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "content.xml").write_text(
        f'<content id="{name}" version="100" name="{name}"/>', encoding="utf-8")
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return d


def test_a_zero_over_an_empty_population_is_REFUSED_not_reported():
    """The load-bearing guard. This is the exact shape that shipped a wrong finding."""
    rep = _scan.CorpusScan()
    with pytest.raises(ValueError, match="NOTHING WAS PARSED"):
        rep.verdict(0, "dangling refs")


def test_a_real_zero_is_reported_WITH_its_denominator():
    rep = _scan.CorpusScan(mods_scanned=3, files_parsed=120)
    out = rep.verdict(0, "dangling refs")
    assert "0 dangling refs" in out
    assert "3 mod(s)" in out and "120 XML file(s)" in out


def test_ego_dlc_is_excluded_by_default(tmp_path):
    """CLAUDE.md #20: the reference tree IS the unpacked base+DLC, so walking both
    double-counts every DLC. That error shipped twice in one session."""
    ext = tmp_path / "extensions"
    _mod(ext, "some_mod", {"libraries/a.xml": "<a/>"})
    _mod(ext, "ego_dlc_terran", {"libraries/b.xml": "<b/>"})

    rep = _scan.CorpusScan()
    seen = {m for m, _v, _r in _scan.iter_corpus_xml(ext, rep)}
    assert seen == {"some_mod"}
    assert rep.mods_scanned == 1


def test_a_mod_whose_MANIFEST_will_not_parse_lands_in_skipped_mods(tmp_path):
    """Excluding it is right; excluding it silently is not — it shrinks the
    denominator of every sweep built on this helper."""
    ext = tmp_path / "extensions"
    good = _mod(ext, "good", {"libraries/a.xml": "<a/>"})
    bad = _mod(ext, "bad", {"libraries/b.xml": "<b/>"})
    (bad / "content.xml").write_text("<content id='bad'", encoding="utf-8")

    rep = _scan.CorpusScan()
    seen = {m for m, _v, _r in _scan.iter_corpus_xml(ext, rep)}
    assert seen == {"good"}
    assert rep.skipped_mods, "a mod dropped for a broken manifest must be reported"
    assert "SKIPPED ENTIRELY" in rep.denominator()


def test_an_unparseable_file_is_RECORDED_not_silently_dropped(tmp_path):
    """A file that will not parse must reduce confidence, not vanish. The ad-hoc
    version of this scan dropped 4,391 of them without a word."""
    ext = tmp_path / "extensions"
    _mod(ext, "m", {"libraries/ok.xml": "<a/>", "libraries/bad.xml": "<a><unclosed>"})

    rep = _scan.CorpusScan()
    got = [v for _m, v, _r in _scan.iter_corpus_xml(ext, rep)]
    # content.xml is yielded too — it IS XML the mod owns, and every recorded
    # corpus denominator (4,391 files) counts it. Filter in the caller if unwanted.
    assert set(got) == {"content.xml", "libraries/ok.xml"}
    assert rep.files_parsed == 2
    assert len(rep.unreadable) == 1
    assert "bad.xml" in rep.unreadable[0].vpath
    assert "unreadable" in rep.denominator()


def test_the_denominator_names_the_scanned_set_not_only_the_failures(tmp_path):
    """A blind spot is by definition absent from the list of things that failed —
    so the source set has to be stated, not just the errors."""
    ext = tmp_path / "extensions"
    _mod(ext, "m", {"libraries/a.xml": "<a/>"})
    rep = _scan.CorpusScan()
    list(_scan.iter_corpus_xml(ext, rep))
    assert "SCANNED SOURCE SET" in rep.denominator()
    assert "1 mod(s)" in rep.denominator()

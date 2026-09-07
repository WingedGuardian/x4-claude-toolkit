"""x4xref's two denominator holes (v3.1.0 release review, group B2, both PRE-ARC).

x4xref exists to make a NEGATIVE admissible -- "nobody calls X" -- and both defects
attacked exactly that.

1. `_sidecar()` had ONE caller, `_exclusions()`, a READER. Nothing ever wrote the
   file. Unreadable files were printed once at build time to stderr and discarded,
   so every later answer rendered with no exclusion list at all -- which
   `_exclusions`' own docstring calls "the most confidently wrong answer this tool
   can give".
2. `if ext_dir.is_dir():` skipped the whole mod walk in silence when the directory
   did not exist, and `build` returned 0 over an index covering base + DLC only.
   `_registry.default_installed_dirs` already states the rule this broke: "0
   installed mods" must not read as "you have no mods" when the truth is "I looked
   in the wrong place".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from x4validate import _xref


def _tree(tmp_path):
    ref = tmp_path / "reference"
    (ref / "md").mkdir(parents=True)
    (ref / "md" / "ok.xml").write_text(
        '<mdscript name="S"><cues><cue name="C"/></cues></mdscript>', encoding="utf-8")
    ext = tmp_path / "extensions"
    ext.mkdir()
    return ref, ext


def _build(tmp_path, ref, ext, out):
    return _xref.main(["build", "--reference", str(ref), "--ext-dir", str(ext),
                       "--out", str(out)])


def test_the_sidecar_the_QUERY_PATH_READS_is_actually_written(tmp_path):
    """A mod with an unparseable md file must leave its name where `_exclusions`
    looks for it, not only in the build's stderr."""
    ref, ext = _tree(tmp_path)
    bad = ext / "badmod"
    (bad / "md").mkdir(parents=True)
    (bad / "content.xml").write_text('<content id="badmod" version="1"/>', encoding="utf-8")
    (bad / "md" / "broken.xml").write_text("<mdscript><unclosed>", encoding="utf-8")
    out = tmp_path / "md_xref.tsv"
    assert _build(tmp_path, ref, ext, out) == 0
    side = _xref._sidecar(out)
    assert side.is_file(), "the sidecar every negative is rendered against was not written"
    assert "broken.xml" in side.read_text(encoding="utf-8")
    assert "EXCEPT" in _xref._exclusions(out)


def test_a_CLEAN_build_writes_an_EMPTY_sidecar_rather_than_leaving_a_stale_one(tmp_path):
    """The twin, and the reason it is written unconditionally: a sidecar from an
    earlier build would otherwise attach exclusions that no longer exist to an index
    that is now clean. A wrong denominator is not safer than none."""
    ref, ext = _tree(tmp_path)
    out = tmp_path / "md_xref.tsv"
    _xref._sidecar(out).write_text("leftover/from/a/previous/build.xml\n", encoding="utf-8")
    assert _build(tmp_path, ref, ext, out) == 0
    assert _xref._sidecar(out).read_text(encoding="utf-8") == ""
    assert _xref._exclusions(out) == ""


def test_a_NONEXISTENT_extensions_dir_is_REFUSED_not_indexed_as_zero_mods(tmp_path):
    """Pre-fix: rc 0 and a written index covering base + DLC only."""
    ref, _ = _tree(tmp_path)
    out = tmp_path / "md_xref.tsv"
    rc = _build(tmp_path, ref, tmp_path / "no_such_extensions", out)
    assert rc == 2
    assert not out.is_file(), "an index that cannot support a negative must not be left behind"


def test_build_index_RECORDS_a_missing_extensions_dir_for_a_library_caller(tmp_path):
    """The CLI refuses; `build_index` is also called directly, and there the state
    has to reach the `unreadable` channel every caller already renders."""
    ref, _ = _tree(tmp_path)
    unreadable: list = []
    _xref.build_index(ref, tmp_path / "no_such_extensions", unreadable, dlc_dirs=[])
    assert any("does not exist" in str(u) for u in unreadable), unreadable


def test_an_EXISTING_but_EMPTY_extensions_dir_is_NOT_refused(tmp_path):
    """The twin that keeps the refusal honest. An empty modlist is a real state a
    user can be in; only a missing DIRECTORY is the look-in-the-wrong-place case."""
    ref, ext = _tree(tmp_path)
    out = tmp_path / "md_xref.tsv"
    assert _build(tmp_path, ref, ext, out) == 0
    assert out.is_file()

"""The control-byte sweep must cover the whole repository, and must be able to go red.

This gate had ZERO tests, while its own source comment cited
`test_labels_are_two_char_escapes` as though it existed -- a citation is not a test,
and nothing noticed for a release.

MEASURED 2026-09-02: `ROOT` was the PACKAGE root and `git ls-files` ran there, so the
sweep saw **171 of 241** tracked files. Everything outside `tools/x4validate` was
invisible -- the whole of `.claude/hooks/` and `scripts/`, which is exactly where file
content gets written through interpreter strings and where these escapes collapse. The
gate was structurally blind to the file carrying the defect it exists to find: a literal
0x08 sat in `scripts/fuzz-guard.py` for a release while this sweep reported clean.

Control bytes below are built with `bytes([n])` and backslashes with `chr(92)`, never as
escapes. The first draft of the gate wrote "backslash-a" style literals, the tool
boundary collapsed them into the very characters being hunted, and the expectations
collapsed identically so the tests still passed. That trap fired again while writing
THIS file: a doubled backslash in the patch script became a real NUL byte on disk.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gates"))
import control_bytes as cb  # noqa: E402

BS = chr(92)
NUL = bytes([0])


# --- the citation made real --------------------------------------------------

def test_labels_are_two_char_escapes():
    """Named in the gate's own comment since it was written; never existed until now."""
    assert cb.ESCAPES, "the escape table is empty, so every label below is vacuous"
    for code, label in cb.ESCAPES.items():
        assert len(label) == 2, f"0x{code:02x} -> {label!r} is not a two-character escape"
        assert label[0] == BS, f"0x{code:02x} -> {label!r} does not start with a backslash"
        assert label[1].isalpha(), f"0x{code:02x} -> {label!r} has no escape letter"


def test_scan_bytes_finds_every_escape_and_ignores_tab_lf_cr():
    data = b"a" + bytes([8]) + b"b" + bytes([9, 10, 13]) + b"c" + bytes([27])
    found = cb.scan_bytes(data)
    assert [c for _, c, _ in found] == [8, 27], found
    assert all(e[0] == BS for _, _, e in found)


# --- scope: the regression this file exists for ------------------------------

def test_ROOT_is_the_REPOSITORY_root_not_the_package_root():
    assert (cb.ROOT / "install.sh").is_file(), (
        f"ROOT={cb.ROOT} does not contain install.sh, so it is not the repo root")
    assert cb.ROOT != cb._PKG, "ROOT collapsed back onto the package root"


def test_the_sweep_reaches_files_OUTSIDE_the_package():
    """The measured hole: hooks and scripts were never scanned."""
    tracked = cb.tracked_text_files()
    if not tracked:
        pytest.skip("not a git checkout -- scope NOT CHECKED")
    names = {p.as_posix() for p in tracked}
    for outside in (".claude/hooks/hook_facts.py",
                    ".claude/hooks/protect-bash.sh",
                    "scripts/fuzz-guard.py"):
        assert any(n.endswith(outside) for n in names), (
            f"{outside} is not in the swept set -- the sweep is package-scoped again")


def test_tracked_files_are_not_filtered_by_extension():
    """An allowlist is a narrowing step that reports success; this one dropped
    .xml, .lua and .ps1 from a repo that ships all three."""
    tracked = cb.tracked_text_files()
    if not tracked:
        pytest.skip("not a git checkout -- NOT CHECKED")
    suffixes = {p.suffix.lower() for p in tracked}
    assert ".lua" in suffixes and ".ps1" in suffixes, sorted(suffixes)


# --- it must be able to go RED ------------------------------------------------

def test_it_goes_RED_on_a_planted_control_byte(tmp_path, capsys):
    planted = tmp_path / "note.md"
    planted.write_bytes(b"a line" + bytes([8]) + b"more text" + bytes([10]))
    assert cb.main([str(planted)]) == 1
    assert "0x08" in capsys.readouterr().out


def test_a_CLEAN_file_is_green(tmp_path):
    """The twin of the one above: without it, a gate that always returned 1 would
    also pass that test."""
    clean = tmp_path / "clean.md"
    clean.write_bytes(b"nothing to see here" + bytes([10]))
    assert cb.main([str(clean)]) == 0


# --- refusals -----------------------------------------------------------------

def test_a_BINARY_file_is_skipped_NAMED_and_does_not_refuse(tmp_path, monkeypatch, capsys):
    """A binary is CORRECTLY not scanned, so it must not trip the
    hole-in-the-denominator refusal -- but it must still be named.

    The tracked set is stubbed out so the counts below are about THESE two files.
    Without that, `main` also sweeps the repo and `scanned` is 241, not 1 -- which is
    the gate behaving correctly and the assertion measuring the wrong population."""
    monkeypatch.setattr(cb, "tracked_text_files", lambda: [])
    blob = tmp_path / "thing.bin"
    blob.write_bytes(b"MZ" + NUL + bytes([8]) + NUL * 4)
    text = tmp_path / "ok.md"
    text.write_bytes(b"fine" + bytes([10]))
    rc = cb.main([str(blob), str(text)])
    out = capsys.readouterr().out
    assert rc == 0, "a binary must not be reported as a defect"
    assert "binary (correctly not scanned)" in out
    assert "thing.bin" in out
    assert "scanned 1 file(s)" in out, out
    assert "binary-skipped 1" in out, out


def test_nothing_scanned_REFUSES_rather_than_reporting_clean(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cb, "tracked_text_files", lambda: [])
    assert cb.main([]) == 2
    assert "REFUSING" in capsys.readouterr().err


def test_an_UNREADABLE_path_REFUSES(tmp_path, capsys):
    missing = tmp_path / "gone.md"
    present = tmp_path / "here.md"
    present.write_bytes(b"ok" + bytes([10]))
    assert cb.main([str(missing), str(present)]) == 2
    assert "hole in it" in capsys.readouterr().err


def test_a_directory_argument_is_expanded(tmp_path):
    d = tmp_path / "memory"
    d.mkdir()
    (d / "a.md").write_bytes(b"clean" + bytes([10]))
    (d / "b.md").write_bytes(b"dirty" + bytes([7]) + bytes([10]))
    rep = cb.scan_paths([d])
    assert rep["scanned"] == 2, rep
    assert len(rep["hits"]) == 1, rep

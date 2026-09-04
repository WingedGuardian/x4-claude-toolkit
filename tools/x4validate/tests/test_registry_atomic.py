r"""The registry must survive a failed or wrong save. MEASURED, twice, in anger.

WHY THIS EXISTS. `save_registry` opened the destination `"w"` and then dumped into
it. `"w"` truncates AT OPEN, so a dump that raised left the file EMPTY rather than
unchanged -- and the traceback reads like "nothing happened" while the content is
gone. Reproduced 2026-09-03: 213 -> 7 bytes, 0 of 2 human decisions surviving.

The second failure is the one atomicity does NOT fix, and it is the one that
actually cost the user data. On 2026-09-03 the live registry went from 196,363
bytes / 258 entries to a 46-byte fresh registry. The dump SUCCEEDED; the content
was simply empty, because something loaded a registry that was not there (or was
already truncated) and saved the fresh one over the real one. Only a refusal to
SHRINK catches that, which is why the entry-count guard is the load-bearing half.

The registry is append-only in practice -- `merge_installed` never removes, and the
filtered lists in `_modlist` are report-only -- measured across three recovered
copies: 243 (08-13) -> 258 (08-22) -> 266 (08-29), a strict superset each time.
A caller that genuinely means to shrink it says so with `allow_shrink=True`.
"""

from __future__ import annotations

import pytest
from ruamel.yaml.comments import CommentedMap

from x4validate import _registry


def _reg(n: int) -> CommentedMap:
    reg = _registry._new_registry()
    for i in range(n):
        e = _registry._new_entry(f"mod_{i:03d}", True)
        e["human"]["notes"] = "a hand-written decision that exists nowhere else"
        reg["mods"].append(e)
    return reg


def _entries(path) -> int:
    b = path.read_bytes()
    return b.count(b"\n- id: ") + (1 if b.startswith(b"- id: ") else 0)


def test_a_failing_dump_leaves_the_previous_registry_intact(tmp_path, monkeypatch):
    """The 08-22 / 08-27 shape: an exception mid-write must not truncate."""
    p = tmp_path / "modlist.yaml"
    _registry.save_registry(_reg(30), p)
    before = p.read_bytes()
    assert _entries(p) == 30

    class Boom(Exception):
        pass

    def exploding_dump(data, stream):
        stream.write("meta:\n")          # a partial write, as a real failure does
        raise Boom("dump failed mid-write")

    monkeypatch.setattr(_registry._yaml, "dump", exploding_dump)
    with pytest.raises(Boom):
        _registry.save_registry(_reg(31), p)

    assert p.read_bytes() == before, "a failed save destroyed the previous registry"
    assert not list(tmp_path.glob("*.tmp*")), "a temp file was left behind"


def test_saving_FEWER_entries_than_are_on_disk_is_refused(tmp_path):
    """The 09-03 shape: a SUCCESSFUL dump of an empty registry over a full one."""
    p = tmp_path / "modlist.yaml"
    _registry.save_registry(_reg(258), p)
    before = p.read_bytes()

    with pytest.raises(_registry.RegistryShrink) as exc:
        _registry.save_registry(_registry._new_registry(), p)   # the 46-byte write

    assert "258" in str(exc.value) and "0" in str(exc.value)
    assert p.read_bytes() == before, "the registry was overwritten anyway"


def test_a_deliberate_shrink_is_still_possible(tmp_path):
    p = tmp_path / "modlist.yaml"
    _registry.save_registry(_reg(10), p)
    _registry.save_registry(_reg(3), p, allow_shrink=True)
    assert _entries(p) == 3


def test_growing_and_equal_saves_are_untouched(tmp_path):
    p = tmp_path / "modlist.yaml"
    _registry.save_registry(_reg(10), p)
    _registry.save_registry(_reg(10), p)      # equal: the common refresh case
    assert _entries(p) == 10
    _registry.save_registry(_reg(11), p)      # grow: ingest
    assert _entries(p) == 11


def test_a_first_save_to_a_new_location_works(tmp_path):
    """A fresh install has no registry; the guard must not block creating one."""
    p = tmp_path / "nested" / "modlist.yaml"
    _registry.save_registry(_registry._new_registry(), p)
    assert p.is_file() and _entries(p) == 0


def test_an_empty_file_on_disk_does_not_block_a_fresh_registry(tmp_path):
    """A 0-entry file is not evidence of loss, so writing 0 over it is allowed."""
    p = tmp_path / "modlist.yaml"
    p.write_text("", encoding="utf-8")
    _registry.save_registry(_registry._new_registry(), p)
    assert _entries(p) == 0


def test_a_directory_destination_still_works(tmp_path):
    """Pre-existing behaviour (`_registry_file`) must survive the rewrite."""
    d = tmp_path / "reg_dir"
    d.mkdir()
    _registry.save_registry(_reg(4), d)
    assert (d / _registry.REGISTRY_FILENAME).is_file()
    _registry.save_registry(_reg(5), d)       # and the guard reads the same file
    assert _entries(d / _registry.REGISTRY_FILENAME) == 5


def test_the_bytes_on_disk_are_unchanged_by_the_rewrite(tmp_path):
    """The temp+replace path must produce the same file the old code did --
    same encoding, same line endings. A silent CRLF->LF flip would show up as a
    whole-file diff in the user's git history (gotcha #57)."""
    p = tmp_path / "modlist.yaml"
    reg = _reg(6)
    _registry.save_registry(reg, p)
    got = p.read_bytes()
    import io
    buf = io.StringIO()
    _registry._yaml.dump(reg, buf)
    import os as _os
    expected = buf.getvalue().replace("\n", _os.linesep).encode("utf-8")
    assert got == expected, "line-ending or encoding behaviour changed"


def test_a_huge_shrink_is_refused_even_if_entry_counting_is_fooled(tmp_path):
    """Second, independent clause: the entry count is a byte heuristic on a file
    a human may have reformatted. Size is the backstop -- the 09-03 write was
    46 bytes over 196,363."""
    p = tmp_path / "modlist.yaml"
    _registry.save_registry(_reg(258), p)
    # Reformat so the '- id: ' anchor no longer appears at line start, exactly as
    # a hand edit or a different dumper would: the count guard now sees 0 on disk.
    text = p.read_text(encoding="utf-8")
    p.write_text(text.replace("\n- id: ", "\n-   id: "), encoding="utf-8")
    assert _entries(p) == 0, "precondition: the count heuristic is now blind"
    with pytest.raises(_registry.RegistryShrink):
        _registry.save_registry(_registry._new_registry(), p)

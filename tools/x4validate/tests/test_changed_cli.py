r"""`x4modlist changed` — localise a moved fingerprint instead of investigating it.

The command exists because localising ONE changed mod cost nine investigative
steps on 2026-08-25 (F56). What is pinned here is not the diffing (that is
`test_freshness_vector.py`) but the CONTRACT around it:

* a baseline with no vector must produce a **non-answer**, never "no change";
* the exit code must separate "no change" (0) from "changes found" (1) from
  "could not answer" (3), because a caller that cannot tell 0 from 3 will read a
  refusal as an all-clear -- the exact shape `Report.skipped` exists to prevent;
* the advisory USN rung must DEGRADE, never fail the command, because reading the
  NTFS change journal requires Administrator and the session usually is not.
"""

import json
import types

import pytest

from x4validate import _changed, _freshness


def _detail(**mods):
    """A minimal vector: folder -> (files, tree_sha, version)."""
    out = []
    for folder, (files, sha, ver) in sorted(mods.items()):
        out.append({"folder": folder, "root": "R", "manifest_id": folder,
                    "manifest_version": ver, "manifest_sha": "aa",
                    "manifest_mtime": 1, "manifest_size": 10,
                    "no_manifest": False, "files": files, "unreadable": 0,
                    "tree_sha": sha, "enabled_in_profile": True,
                    "entries": [["libraries/god.xml", 1, files]]})
    return out


# --- the non-answer contract --------------------------------------------------

def test_a_vectorless_baseline_is_a_NON_ANSWER_with_its_own_exit_code(capsys, monkeypatch):
    """rc 3, and nothing on stdout that could be mistaken for a result."""
    monkeypatch.setattr(_changed, "load_baseline",
                        lambda spec: (None, "the effective store (built 08-02)"))
    monkeypatch.setattr(_changed, "_dirs", lambda: [])
    monkeypatch.setattr(_freshness, "content_detail", lambda *a, **k: _detail())
    rc = _changed.cmd_changed(types.SimpleNamespace(since="store", files=False, usn=False))
    out = capsys.readouterr()
    assert rc == 3, "a refusal must not share an exit code with 'no change'"
    assert out.out.strip() == "", "a non-answer must not print a result to stdout"
    assert "NON-ANSWER" in out.err and "no change" not in out.out


def test_no_change_and_changes_found_have_DIFFERENT_exit_codes(capsys, monkeypatch):
    same = _detail(mod_a=(1, "sha1", "100"))
    monkeypatch.setattr(_changed, "_dirs", lambda: [])
    monkeypatch.setattr(_changed, "load_baseline", lambda spec: (same, "snap"))
    monkeypatch.setattr(_freshness, "content_detail", lambda *a, **k: same)
    args = types.SimpleNamespace(since="latest", files=False, usn=False)
    assert _changed.cmd_changed(args) == 0
    assert "no change" in capsys.readouterr().out

    monkeypatch.setattr(_freshness, "content_detail",
                        lambda *a, **k: _detail(mod_a=(2, "sha2", "100")))
    assert _changed.cmd_changed(args) == 1, "a real change must be distinguishable"


# --- rendering ----------------------------------------------------------------

def test_render_orders_structural_changes_before_cosmetic_ones():
    changes = [{"folder": "z", "kind": "touched", "detail": ""},
               {"folder": "a", "kind": "added", "detail": ""},
               {"folder": "m", "kind": "content", "detail": ""}]
    body = "\n".join(_changed.render(changes, "snap", False))
    assert body.index("added") < body.index("content") < body.index("touched")


def test_render_names_files_only_when_asked():
    changes = [{"folder": "m", "kind": "content", "detail": "1 file(s) changed",
                "files_changed": ["libraries/god.xml"], "files_touched": []}]
    assert "libraries/god.xml" not in "\n".join(_changed.render(changes, "s", False))
    assert "libraries/god.xml" in "\n".join(_changed.render(changes, "s", True))


def test_render_ANNOUNCES_a_truncated_file_list():
    """A cap that does not announce itself is this toolkit's founding defect shape.

    Station_ink alone ships 7,508 files, so the cap is real -- and a silent one
    would render "12 file(s) changed" above a list of 200 with nothing saying the
    rest exist.
    """
    many = [f"libraries/f{i}.xml" for i in range(_changed._FILE_CAP + 37)]
    body = "\n".join(_changed.render(
        [{"folder": "m", "kind": "content", "detail": "", "files_changed": many,
          "files_touched": []}], "s", True))
    assert "NOT LISTED" in body and "37 more" in body

    # ...and it must stay quiet when nothing was dropped.
    few = "\n".join(_changed.render(
        [{"folder": "m", "kind": "content", "detail": "",
          "files_changed": many[:3], "files_touched": []}], "s", True))
    assert "NOT LISTED" not in few


def test_render_says_no_change_UNAMBIGUOUSLY():
    """It must not be confusable with the refusal above."""
    body = "\n".join(_changed.render([], "snap", False))
    assert "no change" in body and "NON-ANSWER" not in body


# --- snapshots ----------------------------------------------------------------

def test_a_snapshot_is_named_by_CONTENT_not_by_CLOCK(tmp_path, monkeypatch):
    """Two snapshots of an unchanged world must collapse onto one file.

    Naming by timestamp would accumulate look-alike baselines that cannot be told
    apart without opening them -- and the name would say WHEN it was taken rather
    than WHICH world it describes."""
    monkeypatch.setattr(_changed, "snapshots_dir", lambda: tmp_path)
    monkeypatch.setattr(_changed, "_dirs", lambda: [])
    monkeypatch.setattr(_freshness, "fingerprint",
                        lambda *a, **k: {"content": "cafe1234", "engine": "e",
                                         "detail": _detail(m=(1, "s", "1"))})
    a = _changed.take_snapshot()
    b = _changed.take_snapshot()
    assert a == b and len(list(tmp_path.glob("*.json"))) == 1
    assert "cafe1234" in a.name
    assert json.loads(a.read_text(encoding="utf-8"))["detail"], "vector must be stored"

    labelled = _changed.take_snapshot("pre-wave")
    assert labelled != a and "pre-wave" in labelled.name


def test_a_snapshot_label_cannot_escape_the_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(_changed, "snapshots_dir", lambda: tmp_path)
    monkeypatch.setattr(_changed, "_dirs", lambda: [])
    monkeypatch.setattr(_freshness, "fingerprint",
                        lambda *a, **k: {"content": "c", "engine": "e", "detail": []})
    out = _changed.take_snapshot("../../etc/passwd")
    assert out.parent == tmp_path and "/" not in out.name and "\\" not in out.name


def test_load_baseline_reports_WHICH_source_could_not_answer(tmp_path):
    """A bare failure would leave the reader guessing which artifact was consulted."""
    detail, desc = _changed.load_baseline(str(tmp_path / "nope.json"))
    assert detail is None and "nope.json" in desc


# --- the advisory USN rung ----------------------------------------------------

def test_usn_DEGRADES_and_never_raises(monkeypatch):
    """Change-journal reads need Administrator. A tool that hard-fails on a
    privilege the session cannot have is a tool people stop running."""
    import subprocess
    monkeypatch.setattr(_changed.sys, "platform", "win32")
    monkeypatch.setattr(_changed, "_dirs",
                        lambda: [__import__("pathlib").PureWindowsPath("C:/x")])

    # THE CASE THAT MATTERS, MEASURED on a real unelevated shell 2026-08-26:
    # `queryjournal` returns 0 and prints the journal id, while `readjournal`
    # returns **Error 5: Access is denied**. Probing with queryjournal alone
    # reported "readable" for a capability we do not have.
    def _split(*a, **k):
        verb = a[0][2] if a and len(a[0]) > 2 else ""
        if verb == "queryjournal":
            return types.SimpleNamespace(
                returncode=0, stderr="",
                stdout="Usn Journal ID   : 0x01db\nNext Usn         : 0x05e28\n")
        return types.SimpleNamespace(returncode=1, stdout="",
                                     stderr="Error 5: Access is denied.")

    monkeypatch.setattr(subprocess, "run", _split)
    lines = _changed.usn_supplement(["distances"])
    assert any("NOT READABLE" in ln for ln in lines), (
        "queryjournal succeeding must NOT be reported as the journal being "
        "readable -- readjournal is the operation we actually need")
    assert any("Administrator" in ln for ln in lines)
    assert any("unaffected" in ln for ln in lines), (
        "it must say the other rungs still hold, or a denial reads as total failure")

    # ...and when readjournal DOES work, it must say so. The twin: without this,
    # a function that always printed NOT READABLE would pass the check above.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=0, stdout="Usn Journal ID : 0x1\nNext Usn : 0x2\n", stderr=""))
    assert any("READABLE" in ln for ln in _changed.usn_supplement(["distances"]))


def test_usn_says_so_on_a_NON_WINDOWS_platform(monkeypatch):
    """The branch public CI runs on, and which nothing pinned until it went red.

    `usn_supplement` returns early on anything but win32. That early return was
    correct and untested, so the two tests above -- which force win32 -- were the
    only coverage, and they silently exercised the WRONG path on Linux: a
    `Path("C:/x")` is a PosixPath there, its `.drive` is '', and the function bailed
    at "could not determine the volume" long before fsutil. Both now use
    PureWindowsPath, which carries a drive on every platform; this pins the real
    POSIX behaviour separately so the two concerns cannot be confused again.
    """
    monkeypatch.setattr(_changed.sys, "platform", "linux")
    lines = _changed.usn_supplement(["distances"])
    assert len(lines) == 1 and "not available on this platform" in lines[0], lines
    assert "NOT READABLE" not in lines[0], (
        "a platform without the journal is not a PERMISSION problem, and saying so "
        "would send someone hunting for an elevated shell they cannot use")


def test_usn_probes_readjournal_not_just_queryjournal(monkeypatch):
    """Pin the exact call, because the distinction is invisible in the output."""
    import subprocess
    seen = []
    monkeypatch.setattr(_changed.sys, "platform", "win32")
    monkeypatch.setattr(_changed, "_dirs",
                        lambda: [__import__("pathlib").PureWindowsPath("C:/x")])

    def _record(*a, **k):
        seen.append(list(a[0]))
        return types.SimpleNamespace(
            returncode=0, stderr="",
            stdout="Usn Journal ID : 0x1\nNext Usn         : 0xABC\n")

    monkeypatch.setattr(subprocess, "run", _record)
    _changed.usn_supplement([])
    verbs = [c[2] for c in seen]
    assert "queryjournal" in verbs and "readjournal" in verbs, verbs
    read = next(c for c in seen if c[2] == "readjournal")
    assert any(str(x).startswith("startusn=") for x in read), (
        "the probe must start at the journal END, or it dumps the whole change "
        "history just to test permission")


def test_usn_on_a_non_windows_platform_says_so(monkeypatch):
    monkeypatch.setattr(_changed.sys, "platform", "linux")
    lines = _changed.usn_supplement([])
    assert len(lines) == 1 and "not available on this platform" in lines[0]


# --- wiring -------------------------------------------------------------------

def test_both_subcommands_are_registered_on_x4modlist():
    """`changed` without `snapshot` would leave the gap between rebuilds unfillable."""
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    _changed.register(sub)
    assert {"changed", "snapshot"} <= set(sub.choices)
    assert p.parse_args(["changed", "--since", "xref", "--files"]).files is True


def test_x4modlist_main_exposes_them(capsys):
    """The register() call must actually be wired into the real parser.

    ⚠ Asserting only `pytest.raises(SystemExit)` here would be VACUOUS: argparse
    exits 2 for an UNKNOWN subcommand and 0 for a valid `--help`, so the bare
    form passes either way and cannot go red. The exit CODE is the whole test.
    That is F54 mitigation 2 applied to this file, and it was caught by writing
    the falsification twin below rather than by reading the test.
    """
    from x4validate import _modlist
    for cmd in ("changed", "snapshot"):
        with pytest.raises(SystemExit) as exc:
            _modlist.main([cmd, "--help"])
        assert exc.value.code == 0, f"`x4modlist {cmd}` is not wired into main()"
        assert cmd in capsys.readouterr().out

    # The twin: prove the assertion above can actually fail.
    with pytest.raises(SystemExit) as exc:
        _modlist.main(["definitely-not-a-subcommand", "--help"])
    assert exc.value.code != 0, (
        "if an unknown subcommand also exited 0, the check above would prove "
        "nothing")

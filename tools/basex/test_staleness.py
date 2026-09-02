"""A BaseX index must know when the world it describes has moved on.

The register's rule is that a tool returning nothing must distinguish an ABSENCE
from a NON-ANSWER. A stale index is a third case — **an answer from a world that
no longer exists** — and until 2026-08-13 nothing detected it.

The case that produced this module: `x4eff` was built 2026-08-02. The merge
engine was then fixed twice — root-`<replace>` ops were being dropped while
reported applied (2026-08-08, 858 ops) and nested cross-mod patches were invisible
from one of two doors (2026-08-11). **The content did not change on either date.**
So a staleness check that watched only inputs would have reported the index fresh
while it served 858 wrong values. The fingerprint must therefore cover the CODE
that produced the database, not just the data that went into it.

Engine identity is hashed from the source BYTES rather than a git commit: a dirty
working tree does not move a commit hash, and half this workspace's merge changes
were uncommitted when they were first used.
"""

import pytest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Imported directly, NOT via pytest.importorskip: a skip when the module is
# missing is a test that can never fail, which is the same "reports success
# while examining nothing" shape this whole register tracks.
import staleness  # noqa: E402


def _fake_tree(tmp_path):
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_bytes(b"<wares/>")
    ext = tmp_path / "extensions"
    for name in ("mod_a", "mod_b"):
        (ext / name).mkdir(parents=True)
        (ext / name / "content.xml").write_bytes(
            f'<content id="{name}" version="100"/>'.encode())
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "_merge.py").write_bytes(b"# merge v1\n")
    (engine / "_diff.py").write_bytes(b"# diff v1\n")
    return ref, ext, engine


def test_identical_world_fingerprints_identical(tmp_path):
    ref, ext, engine = _fake_tree(tmp_path)
    a = staleness.fingerprint(ref, ext, engine)
    b = staleness.fingerprint(ref, ext, engine)
    assert a == b, "fingerprinting must be deterministic or every run reads as stale"


def test_adding_a_mod_changes_the_content_fingerprint(tmp_path):
    ref, ext, engine = _fake_tree(tmp_path)
    before = staleness.fingerprint(ref, ext, engine)
    (ext / "mod_c").mkdir()
    (ext / "mod_c" / "content.xml").write_bytes(b'<content id="mod_c" version="100"/>')
    after = staleness.fingerprint(ref, ext, engine)
    assert before["content"] != after["content"]
    assert before["engine"] == after["engine"], "adding a mod is not an engine change"


def test_removing_a_mod_changes_the_content_fingerprint(tmp_path):
    """xspvro and kuertee_auto_camera both left the modlist between builds."""
    ref, ext, engine = _fake_tree(tmp_path)
    before = staleness.fingerprint(ref, ext, engine)
    import shutil
    shutil.rmtree(ext / "mod_b")
    assert staleness.fingerprint(ref, ext, engine)["content"] != before["content"]


def test_editing_the_merge_engine_changes_the_ENGINE_fingerprint(tmp_path):
    """THE case this exists for: content identical, engine fixed, answers wrong.

    A checker watching only inputs reports 'fresh' here — which is exactly what
    happened for eleven days across two merge fixes."""
    ref, ext, engine = _fake_tree(tmp_path)
    before = staleness.fingerprint(ref, ext, engine)
    (engine / "_merge.py").write_bytes(b"# merge v2 - root <replace> fix\n")
    after = staleness.fingerprint(ref, ext, engine)
    assert before["engine"] != after["engine"], (
        "an engine-only change went undetected — the exact 2026-08-08 blind spot")
    assert before["content"] == after["content"], "no content changed"


def test_check_reports_fresh_when_nothing_moved(tmp_path):
    ref, ext, engine = _fake_tree(tmp_path)
    cov = tmp_path / "coverage-x4eff.json"
    cov.write_text(json.dumps({"db": "x4eff",
                               "fingerprint": staleness.fingerprint(ref, ext, engine)}))
    verdict = staleness.check(cov, ref, ext, engine)
    assert verdict.fresh
    assert verdict.reasons == []


def test_check_names_WHAT_moved_not_just_that_something_did(tmp_path):
    """'stale' with no reason is a non-answer. The banner has to say which axis
    moved, or the reader cannot tell a mod update from a merge fix."""
    ref, ext, engine = _fake_tree(tmp_path)
    cov = tmp_path / "coverage-x4eff.json"
    cov.write_text(json.dumps({"db": "x4eff",
                               "fingerprint": staleness.fingerprint(ref, ext, engine)}))
    (ext / "mod_c").mkdir()
    (ext / "mod_c" / "content.xml").write_bytes(b'<content id="mod_c" version="100"/>')
    (engine / "_merge.py").write_bytes(b"# merge v2\n")

    verdict = staleness.check(cov, ref, ext, engine)
    assert not verdict.fresh
    joined = " ".join(verdict.reasons).lower()
    assert "content" in joined and "engine" in joined, verdict.reasons


def test_a_coverage_file_with_NO_fingerprint_is_unknown_not_fresh(tmp_path):
    """Every coverage file written before today lacks the field. Treating
    'absent' as 'fine' would make the first run after this change silently
    trust the very databases that prompted it."""
    ref, ext, engine = _fake_tree(tmp_path)
    cov = tmp_path / "coverage-x4eff.json"
    cov.write_text(json.dumps({"db": "x4eff", "status": "complete"}))
    verdict = staleness.check(cov, ref, ext, engine)
    assert not verdict.fresh
    assert any("no fingerprint" in r.lower() for r in verdict.reasons), verdict.reasons


def test_a_missing_coverage_file_is_unknown_not_fresh(tmp_path):
    ref, ext, engine = _fake_tree(tmp_path)
    verdict = staleness.check(tmp_path / "nope.json", ref, ext, engine)
    assert not verdict.fresh


def test_write_stamps_an_existing_coverage_file_without_losing_it(tmp_path):
    """`--write` must be additive: the coverage contract (status,
    supports_negative_claim) is what makes a negative admissible at all."""
    ref, ext, engine = _fake_tree(tmp_path)
    cov = tmp_path / "coverage-x4raw.json"
    cov.write_text(json.dumps({"db": "x4raw", "status": "complete",
                               "supports_negative_claim": True, "indexed": {"total": 7}}))
    staleness.write(cov, ref, ext, engine)
    data = json.loads(cov.read_text())
    assert data["status"] == "complete"
    assert data["supports_negative_claim"] is True
    assert data["indexed"] == {"total": 7}
    assert "fingerprint" in data
    assert staleness.check(cov, ref, ext, engine).fresh


def test_unimportable_engine_reports_UNKNOWN_not_a_traceback(monkeypatch, capsys,
                                                             tmp_path):
    """`staleness.py --check` run with plain `python` (not `uv run`) cannot import
    x4validate. It used to die on a bare ModuleNotFoundError traceback — which is
    the worst possible answer to "is my index fresh?": it is neither FRESH nor
    STALE, it is UNANSWERED, and a traceback does not say which.

    Same rule the register enforces everywhere else: a tool that cannot answer
    must say so, with a reason and a distinct exit code.

    HERMETIC SINCE 2026-08-24, and that is the point of the fixture. This used to
    call `main` with no `--coverage`, so it read the REAL `basex/coverage-x4raw.json`
    and its outcome depended on that live artifact: `check()` returns early when the
    file is missing or carries no fingerprint, never reaching the monkeypatched
    `_core`, so the test fell through to rc 5 and failed. It passed for months only
    because a healthy artifact happened to be sitting there. MEASURED: strip the
    fingerprint from that file and this test goes red while the code is untouched.
    A unit test whose verdict depends on mutable state outside its own tmp_path is
    not testing the code — it is sampling the machine.
    """
    def boom():
        raise ModuleNotFoundError("No module named 'x4validate'")
    monkeypatch.setattr(staleness, "_core", boom)

    cov = tmp_path / "coverage-x4raw.json"
    cov.write_text(json.dumps({
        "db": "x4raw",
        "fingerprint": {"content": "deadbeef", "engine": "cafebabe"},
    }), encoding="utf-8")

    rc = staleness.main(["--check", "--db", "x4raw", "--coverage", str(cov)])
    err = capsys.readouterr().err
    assert rc == 6, f"expected the distinct 'cannot determine' code, got {rc}"
    assert "cannot determine" in err.lower()
    assert "uv run" in err, "the message must name the working invocation"
    assert "Traceback" not in err


def test_unresolvable_paths_report_UNKNOWN_not_a_traceback(monkeypatch, capsys):
    """The EARLIEST failure, which the sibling test above does not reach.

    `main` calls `_defaults()` BEFORE the try/except blocks that guard `write()`
    and `check()`. The sibling test monkeypatches `_core`, so it exercises the
    GUARDED path and passes honestly -- while the unguarded one produced a raw
    traceback and **rc 1**. MEASURED 2026-08-24 on a genuinely cold checkout
    (every `X4_*` cleared, no config file reachable): rc 1, one traceback.

    rc 1 is the actively harmful part: in this toolkit it means "the thing you
    asked about has findings". The truth was "this toolkit is not set up", and
    those two demand opposite responses -- the same confusion F39 removed from
    the CLIs and F44 found still living in the BaseX scripts.
    """
    def boom():
        raise staleness.EngineUnavailable("cannot resolve reference and extensions")
    monkeypatch.setattr(staleness, "_defaults", boom)

    rc = staleness.main(["--check", "--db", "x4raw"])
    err = capsys.readouterr().err
    assert rc == 6, f"expected the distinct 'cannot determine' code, got {rc}"
    assert "Traceback" not in err
    assert "uv run" in err, "the message must name the working invocation"


# --- the engine axis must REFUSE a tree that is not there (2026-09-02) --------

def test_a_MISSING_engine_tree_is_a_refusal_not_a_constant(tmp_path, monkeypatch):
    """`hash_engine` over a missing tree hashes seven fixed names plus seven <ABSENT>
    markers, so EVERY nonexistent path folds to the SAME digest -- and `check()` then
    reports the artifact fresh against any of them, forever. Two of the three axes
    already refused for exactly this reason; the engine axis did not."""
    import staleness
    # The other two axes are pinned so ONLY the engine axis is under test.
    # _defaults() validates reference and extensions FIRST, so on a machine with
    # no X4 installed this raised for THOSE and the assertion below measured the
    # wrong refusal -- green configured, red cold.
    monkeypatch.setenv("X4_REFERENCE", str(tmp_path / "ref"))
    monkeypatch.setenv("X4_EXTENSIONS", str(tmp_path / "ext"))
    monkeypatch.setenv("X4VALIDATE_DIR", str(tmp_path / "not-a-checkout"))
    with pytest.raises(staleness.EngineUnavailable) as ei:
        staleness._defaults()
    assert "_merge.py" in str(ei.value)


def test_pointing_at_the_PACKAGE_instead_of_the_CHECKOUT_refuses(tmp_path, monkeypatch):
    """The reachable misconfiguration: the variable is named for the checkout, this
    code appends `/x4validate` to it, so aiming it one level too deep silently yields
    .../x4validate/x4validate/x4validate. `cd` there succeeds and `uv run` works, so
    nothing else in the build notices."""
    import staleness
    pkg = tmp_path / "x4validate" / "x4validate"
    pkg.mkdir(parents=True)
    (pkg / "_merge.py").write_text("# engine\n", encoding="utf-8")
    # The other two axes are pinned so ONLY the engine axis is under test.
    # _defaults() validates reference and extensions FIRST, so on a machine with
    # no X4 installed this raised for THOSE and the assertion below measured the
    # wrong refusal -- green configured, red cold.
    monkeypatch.setenv("X4_REFERENCE", str(tmp_path / "ref"))
    monkeypatch.setenv("X4_EXTENSIONS", str(tmp_path / "ext"))
    monkeypatch.setenv("X4VALIDATE_DIR", str(pkg))       # one level too deep
    with pytest.raises(staleness.EngineUnavailable):
        staleness._defaults()


def test_a_REAL_checkout_is_accepted(tmp_path, monkeypatch):
    """The twin. A guard that refused everything would pass both tests above while
    making every build impossible."""
    import staleness
    root = tmp_path / "x4validate"
    (root / "x4validate").mkdir(parents=True)
    (root / "x4validate" / "_merge.py").write_text("# engine\n", encoding="utf-8")
    monkeypatch.setenv("X4VALIDATE_DIR", str(root))
    monkeypatch.setenv("X4_REFERENCE", str(tmp_path / "ref"))
    monkeypatch.setenv("X4_EXTENSIONS", str(tmp_path / "ext"))
    _ref, _ext, engine = staleness._defaults()
    assert (engine / "_merge.py").is_file(), engine

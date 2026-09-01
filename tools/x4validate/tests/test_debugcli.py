r"""`x4debug` — turn a debug.txt into a triage, and compare it to what we predicted.

Two things this must never do, both learned expensively:

**Never present a bucket table whose rows do not sum to the input.** Every triage
before this one was hand-rolled `grep | sort | uniq -c`, and a hand-rolled table
has no way to notice that it dropped a shape. The residue row is therefore
mandatory output, printed even when it is zero — a table that only shows residue
when residue exists teaches the reader that its absence means nothing happened.

**Never compare two states by their totals.** The 2026-08-13 log has 342 failing
ops in one cpsdo file; x4validate independently predicted 310 for that mod. Those
two numbers are close enough to look like agreement and are not the same set. The
crosscheck reports per item, in three buckets, and `observed-not-predicted` — the
validator's blind spot — is the one that has to be impossible to overlook.
"""

from pathlib import Path

from x4validate import _debugcli, _freshness

SAMPLE = "\n".join([
    r"Logfile started, time Thu Aug 13 14:06:37 2026",
    r"[General] 0.00 Universe generation begins",
    r"[=ERROR=] 0.00 No matching node for path '//wares/ware[@id='x']/owner/@faction' in patch file 'extensions\modA\libraries\wares'. Skipping node.",
    r"[=ERROR=] 0.00 Multiple matching nodes for path '//wares/ware[@id='y']' in patch file 'extensions\modA\libraries\wares'. Skipping node.",
    r"[=ERROR=] 0.00 [JobEngine] No ship generated for JobID: 'argon_heavyfrigate_patrol_l_sector'. Probably invalid ship macro/group/ref definition.",
    r"[=ERROR=] 0.00 TotallyNovelSubsystem::Boom(): nobody has ever parsed this",
])


def _write(tmp_path, text=SAMPLE, name="debug.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_triage_rows_sum_to_the_input(tmp_path, capsys):
    """The invariant, as output. If the buckets do not add up to the lines read,
    the table is lying and must say so rather than print a plausible total."""
    rc = _debugcli.main(["triage", str(_write(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0
    assert "4 [=ERROR=] line(s) read" in out
    assert "1 UNCLASSIFIED" in out, out


def test_triage_prints_the_residue_row_even_when_it_is_ZERO(tmp_path, capsys):
    """A row that appears only when non-zero trains the reader to read its absence
    as 'not measured'. It has to be present either way."""
    text = "\n".join(SAMPLE.splitlines()[:-1])  # drop the novel shape
    _debugcli.main(["triage", str(_write(tmp_path, text))])
    out = capsys.readouterr().out
    assert "unclassified" in out.lower()
    assert "0" in out


def test_triage_states_the_logs_age_and_whether_it_is_a_new_game(tmp_path, capsys):
    """A stale log looks exactly like a fresh one. And error COUNTS are not
    comparable across the new-game/save-load boundary, so the boundary has to be
    stated before any number is."""
    _debugcli.main(["triage", str(_write(tmp_path))])
    out = capsys.readouterr().out
    assert "new game" in out.lower(), out
    assert "captured" in out.lower() or "mtime" in out.lower(), out


def test_triage_attributes_diff_op_failures_to_the_owning_mod(tmp_path, capsys):
    _debugcli.main(["triage", str(_write(tmp_path))])
    out = capsys.readouterr().out
    assert "modA" in out
    assert "jobengine" in out.lower()


def test_a_missing_log_is_a_NON_ANSWER_not_a_clean_one(tmp_path, capsys):
    """The single most dangerous outcome: exit 0 on a log that was never read,
    which renders 'nothing examined' as 'nothing wrong'."""
    rc = _debugcli.main(["triage", str(tmp_path / "nope.txt")])
    err = capsys.readouterr().err
    assert rc != 0, "a log that could not be read must never exit 0"
    assert "could not" in err.lower() or "not found" in err.lower()


def test_crosscheck_splits_into_three_buckets_not_two_counts(tmp_path):
    """Predicted-and-observed is the boring one. The two asymmetric buckets are
    the findings: one is a stale prediction, the other is a validator blind spot."""
    observed = ["//a[@id='1']", "//b[@id='2']"]
    predicted = ["//a[@id='1']", "//c[@id='3']"]
    r = _debugcli.compare_ops(observed=observed, predicted=predicted)
    assert r.both == ["//a[@id='1']"]
    assert r.predicted_only == ["//c[@id='3']"]
    assert r.observed_only == ["//b[@id='2']"], (
        "an op the engine skipped but we never predicted is a blind spot in the "
        "validator — it must surface as its own bucket, never fold into a total")


def test_crosscheck_counts_duplicates_rather_than_collapsing_them(tmp_path):
    """The engine logs an op once per application pass, so the same sel legitimately
    appears twice. Collapsing to a set would silently reconcile 342 with 310 and
    hide whichever gap is real."""
    r = _debugcli.compare_ops(observed=["//a", "//a"], predicted=["//a"])
    assert r.observed_total == 2 and r.predicted_total == 1
    assert r.both == ["//a"]


def test_baseline_stamps_a_content_fingerprint_but_NOT_an_engine_one(tmp_path):
    """A log is a record of a game launch, not a merge product. Flagging it as
    engine-dependent would make it read STALE every time we touch _merge.py, and a
    banner that cries wolf is one the reader learns to skip."""
    log = _write(tmp_path)
    out = _debugcli.archive(log, tmp_path / "archive")
    assert out.is_file(), "the log itself must be copied, not just described"
    meta = _debugcli.read_archive_meta(out)
    assert meta["engine_dependent"] is False
    assert meta["fingerprint"]["content"]
    assert meta["total_errors"] == 4


class _F:
    def __init__(self, category, message):
        self.category, self.message = category, message


class _R:
    def __init__(self, findings):
        self.findings = findings


def test_predicted_ops_reads_BOTH_cardinality_shapes():
    r"""The bug this tool committed against itself, on its first real run.

    x4validate reports two distinct cardinality failures, and RFC 5261 makes both
    fatal — a `sel` must match exactly one node, so 0 and 2 are equally skipped by
    the engine:

        <replace> sel matched nothing: <sel>
        <replace> sel matched 2 nodes (must match exactly 1 ...): <sel>

    The first extractor matched only "matched nothing", silently dropped all 116
    multi-match predictions on cpsdo_faction, and then reported those same 116 as
    "the engine skipped it and we never predicted it — a VALIDATOR BLIND SPOT".
    A narrowing step that reports its own residue as someone else's defect: the
    register's shape, written into the tool built to find it.
    """
    r = _R([
        _F("sel", "<replace> sel matched nothing: //a[@id='1']"),
        _F("sel", "<replace> sel matched 2 nodes (must match exactly 1 — the engine "
                  "SKIPS ambiguous ops, so this silently does nothing): //b[@id='2']"),
        _F("sel", "<add> sel matched nothing: //c[@id='3']"),
        _F("path", "some other category entirely"),
    ])
    assert _debugcli.predicted_ops(r) == ["//a[@id='1']", "//b[@id='2']", "//c[@id='3']"]


def test_an_unrecognised_sel_finding_RAISES_rather_than_being_skipped():
    """The generalisation. Any future reword of a `sel` message must fail loudly
    here, not shrink the prediction set in silence — silence is what turned a
    working validator into a fabricated blind spot."""
    import pytest
    r = _R([_F("sel", "<replace> sel did something we have never phrased before")])
    with pytest.raises(_debugcli.UnparsedFinding) as exc:
        _debugcli.predicted_ops(r)
    assert "never phrased before" in str(exc.value)


def test_predicted_ops_prefers_the_STRUCTURED_sel_over_the_message():
    r"""Second extraction bug of the same class, found by the same sweep.

    x4validate's message is `sel matched nothing: <sel>` plus OPTIONAL suffixes
    — ` (silent)` and ` [if= passed: <cond>]`. A tail-anchored regex swallows
    them, so `/wares/ware[@id='resourceprobe_02_sm'] (silent)` was compared
    against the engine's `/wares/ware[@id='resourceprobe_02_sm']` and could never
    match: 6 fabricated "predicted-only" rows on xenon_backup alone.

    The fix is to stop scraping prose that has structure behind it. `Finding.sel`
    carries the selector verbatim; the regex survives only as a fallback for
    findings that predate the field.
    """
    class F:
        category, message, sel = "sel", "<add> sel matched nothing: /a/b (silent)", "/a/b"

    assert _debugcli.predicted_ops(_R([F()])) == ["/a/b"], (
        "the structured field must win — the message carries suffixes that are "
        "not part of the selector")


def test_the_message_fallback_also_strips_the_known_suffixes():
    """Belt and braces: even without the structured field, the suffixes must go."""
    r = _R([
        _F("sel", "<add> sel matched nothing: /a/b (silent)"),
        _F("sel", "<replace> sel matched nothing: /c/d [if= passed: //x]"),
        _F("sel", "<add> sel matched nothing: /e/f (silent) [if= passed: //y]"),
    ])
    assert _debugcli.predicted_ops(r) == ["/a/b", "/c/d", "/e/f"]


def test_an_unreadable_sel_finding_ends_the_CLI_cleanly_not_in_a_traceback(monkeypatch, capsys, tmp_path):
    """`predicted_ops` RAISES on purpose, so the CLI has to catch it.

    Same rule the staleness CLI already follows: a tool that cannot answer says
    so, with a reason and a distinct exit code. A traceback tells the reader
    nothing about WHICH of the three states they are in — and here the state is
    "the prediction set is incomplete, so every bucket below would be wrong",
    which is far worse than no answer at all.
    """
    log = tmp_path / "debug.txt"
    log.write_text(SAMPLE, encoding="utf-8")
    mod = tmp_path / "modA"
    mod.mkdir()
    (mod / "content.xml").write_text('<content id="modA" version="100"/>', encoding="utf-8")

    def boom(_report):
        raise _debugcli.UnparsedFinding("<replace> sel did something new: //x")

    from x4validate import _check
    monkeypatch.setattr(_debugcli, "predicted_ops", boom)
    monkeypatch.setattr(_check, "validate", lambda *a, **k: _R([]))

    rc = _debugcli.main(["crosscheck", str(mod), str(log)])
    err = capsys.readouterr().err
    assert rc == 4, f"expected the distinct 'cannot compare' code, got {rc}"
    assert "Traceback" not in err
    assert "incomplete" in err.lower() or "cannot compare" in err.lower()
    assert "_SEL_SHAPES" in err, "the message must name the fix"


def test_archive_never_leaves_a_log_whose_meta_cannot_be_read(tmp_path, monkeypatch):
    """A VOLATILE source must not produce a half-archived entry.

    `archive()` copies the log FIRST -- deliberately, and that is right for a file
    the GAME owns: `debug.txt` and `{profile}/uidata.xml` are rewritten by X4 on
    exit, so the bytes are the one thing that cannot be re-obtained without another
    play session. Losing them to a metadata failure would be the expensive mistake.

    But copy-first left the other half open: if parsing or fingerprinting raised,
    the archive kept a log with NO `.meta.json`, and `read_archive_meta` on it threw.
    A partial artifact that reports nothing is the shape this toolkit exists to
    refuse -- an entry that cannot say what it is is neither present nor absent.

    So: keep the bytes, ALWAYS write a meta, and make the meta say it is degraded.
    Prompted by a peer's `x4live archive` design note, not by a failure in the wild.
    """
    log = tmp_path / "debug.txt"
    log.write_text("[=ERROR=] something\n", encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("fingerprint unavailable")
    monkeypatch.setattr(_freshness, "fingerprint", boom)

    out = _debugcli.archive(log, tmp_path / "archive")
    assert out.is_file(), "the bytes must survive -- the source may be gone by now"
    assert out.read_text(encoding="utf-8") == log.read_text(encoding="utf-8")

    meta = _debugcli.read_archive_meta(out)          # must NOT raise
    assert meta.get("degraded") is True
    assert "fingerprint" in str(meta.get("degraded_reason", "")).lower()

"""The live-query frame contract.

ONE FIXTURE PER CLAUSE, and that is not tidiness -- it is the only design that
works. A guard that fires first SHADOWS every guard behind it, so a single
malformed-reply test proves only that the FIRST clause it trips is present; the
others could be deleted and the suite would stay green. MEASURED the hard way on
2026-08-27 (register #86/#99), twice, including once in the repair for it.

So each test below is built to pass every clause EXCEPT the one it targets.
`gates/mutation_probe.py` then mutates each clause separately -- `A and B` -> `A`,
then -> `B` -- because mutating a whole condition to False cannot distinguish "B is
untested" from "A already covers it".
"""
from __future__ import annotations

import pytest

from x4validate import _livepipe as lp
from x4validate._livepipe import LiveQueryDegraded, LiveQueryUnavailable


def frame(seq=1, status="OK", payload="hello", proto=None, tag=None,
          blen=None, csum=None):
    """A VALID reply, with any one field overridable.

    The point is that every test starts from something that decodes cleanly, so a
    failure can only be the field it broke. A helper that built a subtly-invalid
    baseline would make every test vacuous at once.
    """
    return "\t".join((
        lp.REPLY_TAG if tag is None else tag,
        str(lp.PROTO if proto is None else proto),
        str(seq),
        status,
        str(lp.byte_len(payload) if blen is None else blen),
        str(lp.checksum(payload) if csum is None else csum),
        payload,
    ))


# --------------------------------------------------------------------------- #
# the baseline must actually decode -- otherwise every test below is vacuous
# --------------------------------------------------------------------------- #

def test_the_baseline_frame_decodes_cleanly():
    r = lp.decode_reply(frame(), 1)
    assert (r.seq, r.status, r.payload) == (1, "OK", "hello")
    assert r.ok is True


def test_a_payload_containing_tabs_survives_intact():
    """The payload is everything after the 6th tab; it may contain tabs itself.

    A split without maxsplit would silently drop every field after the first tab
    of a multi-column answer -- and a shortened row is still a well-formed row.
    """
    r = lp.decode_reply(frame(payload="a\tb\tc"), 1)
    assert r.payload == "a\tb\tc"
    assert r.fields == ["a", "b", "c"]


def test_an_empty_payload_yields_no_fields_not_one_empty_field():
    r = lp.decode_reply(frame(payload=""), 1)
    assert r.fields == []


# --------------------------------------------------------------------------- #
# clause 1 -- empty
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("empty", ["", None])
def test_clause1_an_empty_reply_is_a_framing_fault_not_an_empty_answer(empty):
    """The lua api delivers an empty write as nil, so '' cannot mean 'no data'."""
    with pytest.raises(LiveQueryDegraded, match="empty reply"):
        lp.decode_reply(empty, 1)


# --------------------------------------------------------------------------- #
# clause 2 -- not our frame, including the api's reserved sentinels
# --------------------------------------------------------------------------- #

def test_clause2_a_foreign_frame_is_refused():
    with pytest.raises(LiveQueryDegraded, match="not a MR frame"):
        lp.decode_reply(frame(tag="XX"), 1)


@pytest.mark.parametrize("sentinel", ["ERROR", "TIMEOUT", "CANCELLED"])
def test_clause2_a_reserved_sentinel_is_NAMED_as_one(sentinel):
    """`ERROR`/`TIMEOUT`/`CANCELLED` live in the api's DATA channel.

    A naive reader cannot tell them from a payload that happens to equal one. Ours
    can -- they carry no tabs -- and it must SAY so, because "the pipe errored" and
    "the answer is the string ERROR" call for opposite next actions.
    """
    with pytest.raises(LiveQueryDegraded, match="reserved sentinel"):
        lp.decode_reply(sentinel, 1)


def test_clause2_a_payload_that_merely_equals_a_sentinel_is_ACCEPTED():
    """The falsification twin for the clause above.

    If this raised, the sentinel check would be over-broad and the channel could
    never carry the literal string 'ERROR' as data.
    """
    r = lp.decode_reply(frame(payload="ERROR"), 1)
    assert r.payload == "ERROR" and r.ok


# --------------------------------------------------------------------------- #
# clause 3 -- protocol skew
# --------------------------------------------------------------------------- #

def test_clause3_a_protocol_mismatch_names_the_redeploy():
    """Everything else about this frame is valid, so only clause 3 can fire."""
    with pytest.raises(LiveQueryDegraded, match="protocol"):
        lp.decode_reply(frame(proto=lp.PROTO + 1), 1)


# --------------------------------------------------------------------------- #
# clause 4 -- header truncated (distinct from clause 7)
# --------------------------------------------------------------------------- #

def test_clause4_a_frame_too_short_to_carry_its_own_length_is_refused():
    """Cut BEFORE the length field, so clause 7 has nothing to check.

    This is why 4 and 7 are separate clauses rather than one: a frame that lost
    its header cannot be diagnosed as 'truncated payload', because the declared
    length is exactly what went missing.
    """
    short = "\t".join((lp.REPLY_TAG, str(lp.PROTO), "1", "OK"))
    with pytest.raises(LiveQueryDegraded, match="header itself is truncated"):
        lp.decode_reply(short, 1)


# --------------------------------------------------------------------------- #
# clause 5 -- FIFO desync
# --------------------------------------------------------------------------- #

def test_clause5_a_reply_for_another_command_is_refused():
    """Correlation in the lua api is POSITIONAL, so a dropped reply shifts every
    later one by a whole message. Without this clause the caller would be handed
    the previous question's answer, correctly framed and completely wrong."""
    with pytest.raises(LiveQueryDegraded, match="out of step"):
        lp.decode_reply(frame(seq=7), 8)


def test_clause5_a_non_numeric_sequence_is_refused():
    with pytest.raises(LiveQueryDegraded, match="not a number"):
        lp.decode_reply(frame(seq="x"), 1)


# --------------------------------------------------------------------------- #
# clause 6 -- unknown status
# --------------------------------------------------------------------------- #

def test_clause6_an_unmodelled_status_is_refused():
    with pytest.raises(LiveQueryDegraded, match="unknown reply status"):
        lp.decode_reply(frame(status="MAYBE"), 1)


def test_clause6_ABSENT_is_an_ANSWER_not_an_error():
    """The distinction the whole exit-code ladder rests on.

    ABSENT means the engine was asked and said there is no such thing. That is a
    finding. It must never be reported as 'we could not ask' (rc 2).
    """
    r = lp.decode_reply(frame(status="ABSENT", payload=""), 1)
    assert r.status == "ABSENT" and r.ok is False


# --------------------------------------------------------------------------- #
# clause 7 -- TRUNCATION. the clause the module exists for.
# --------------------------------------------------------------------------- #

def test_clause7_a_short_payload_is_caught_and_NAMED_as_truncation():
    """Simulates `pipes.lua:698`: the game declares N bytes and fewer arrive.

    The declared length and checksum are computed over the FULL payload, then the
    payload is cut -- exactly what the unhandled `ERROR_MORE_DATA` case does.
    """
    full = "x" * 200
    cut = full[:50]
    bad = "\t".join((lp.REPLY_TAG, str(lp.PROTO), "1", "OK",
                     str(lp.byte_len(full)), str(lp.checksum(full)), cut))
    with pytest.raises(LiveQueryDegraded, match="TRUNCATED"):
        lp.decode_reply(bad, 1)


def test_clause7_length_is_BYTES_not_characters():
    """A codepoint-based length would disagree with lua's `#s` on any non-ASCII
    payload, and disagree SILENTLY -- reporting truncation where there is none.

    This test goes red the moment either side starts counting characters.
    """
    payload = "\u00e9\u00e9\u00e9"          # 3 chars, 6 UTF-8 bytes
    assert len(payload) == 3 and lp.byte_len(payload) == 6
    r = lp.decode_reply(frame(payload=payload), 1)
    assert r.payload == payload


def test_clause7_a_non_numeric_length_is_refused():
    with pytest.raises(LiveQueryDegraded, match="declared length"):
        lp.decode_reply(frame(blen="?"), 1)


# --------------------------------------------------------------------------- #
# clause 8 -- corruption that preserved the length
# --------------------------------------------------------------------------- #

def test_clause8_bytes_changed_in_transit_are_caught():
    """Length-preserving corruption. Only reachable because clause 7 passed, which
    is precisely what lets the message say 'truncation alone does not explain'."""
    with pytest.raises(LiveQueryDegraded, match="checksum mismatch"):
        lp.decode_reply(frame(csum=12345), 1)


def test_clause8_runs_AFTER_clause7_so_truncation_is_diagnosed_as_truncation():
    """Ordering is a contract, not an accident.

    A short payload also fails the checksum. If clause 8 ran first the caller would
    be told 'corrupted' for the common case, and 'ask for less or chunk the reply'
    -- the only actionable advice -- would never be printed.
    """
    full = "y" * 300
    bad = "\t".join((lp.REPLY_TAG, str(lp.PROTO), "1", "OK",
                     str(lp.byte_len(full)), str(lp.checksum(full)), full[:10]))
    with pytest.raises(LiveQueryDegraded) as exc:
        lp.decode_reply(bad, 1)
    assert "TRUNCATED" in str(exc.value)
    assert "checksum mismatch" not in str(exc.value)


# --------------------------------------------------------------------------- #
# the checksum must agree with the lua side, byte for byte
# --------------------------------------------------------------------------- #

def test_checksum_is_djb2_over_utf8_bytes():
    """Pinned by hand-computed values, so a refactor cannot quietly redefine it
    while both sides still agree with each other and with nothing else."""
    assert lp.checksum("") == 5381
    assert lp.checksum("A") == (5381 * 33 + 65) & 0xFFFFFFFF
    assert lp.checksum("AB") == ((5381 * 33 + 65) * 33 + 66) & 0xFFFFFFFF


def test_checksum_wraps_at_32_bits():
    """LuaJIT arithmetic is doubles; anything above 2**53 stops being exact.
    Masking to 32 bits on both sides is what keeps them comparable."""
    assert lp.checksum("z" * 500) < 2 ** 32


def test_checksum_differs_for_transposed_bytes():
    """Falsification twin: a checksum that ignored ORDER would pass every test
    above and catch none of the corruption it exists for."""
    assert lp.checksum("AB") != lp.checksum("BA")


# --------------------------------------------------------------------------- #
# command encoding
# --------------------------------------------------------------------------- #

def test_encode_command_round_trips_through_the_reply_shape():
    cmd = lp.encode_command(4, "macro", ("shiptypes_s", "ship_arg_s_scout_01_a_macro"))
    parts = cmd.split("\t")
    assert parts[:4] == [lp.CMD_TAG, str(lp.PROTO), "4", "macro"]
    assert parts[4:] == ["shiptypes_s", "ship_arg_s_scout_01_a_macro"]


def test_encode_command_refuses_an_empty_verb():
    """An empty message arrives game-side as nil -- indistinguishable from no
    message at all. Refusing here is cheaper than diagnosing it there."""
    with pytest.raises(ValueError, match="empty message arrives as nil"):
        lp.encode_command(1, "")


@pytest.mark.parametrize("bad", ["a\tb", "a\nb"])
def test_encode_command_refuses_an_argument_carrying_a_separator(bad):
    """Otherwise an argument silently becomes two arguments, and the game
    dispatches on a verb whose arity no longer matches."""
    with pytest.raises(ValueError, match="frame separator"):
        lp.encode_command(1, "macro", (bad,))


# --------------------------------------------------------------------------- #
# the NON-ANSWER floor: refusing must never look like a finding
# --------------------------------------------------------------------------- #

def test_a_non_windows_platform_refuses_rather_than_returning_nothing(monkeypatch):
    """rc 2, not an empty result. `x4live oracle` still works everywhere, and the
    message says so -- a refusal that names the alternative is not a dead end."""
    import sys
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(LiveQueryUnavailable, match="Windows-only"):
        lp._win32()


def test_pipe_name_is_configurable_and_defaults(monkeypatch):
    monkeypatch.setattr(lp._paths, "value", lambda *a: None)
    assert lp.pipe_name() == lp.DEFAULT_PIPE
    monkeypatch.setattr(lp._paths, "value", lambda *a: "custom_pipe")
    assert lp.pipe_name() == "custom_pipe"


def test_the_pipe_path_is_a_UNC_pipe_path_not_a_filesystem_path():
    """⚠ `_paths.path_value()` would run `native()` over this and mangle it.
    Pinned because the mangled form fails at CreateNamedPipe with an error that
    points nowhere near the cause."""
    p = lp.LivePipe(name="abc")
    assert p.path == r"\\.\pipe\abc"


# --------------------------------------------------------------------------- #
# gaps found by asking "which mutant would SURVIVE this suite?" before mutating
# --------------------------------------------------------------------------- #

def test_clause3_a_bare_tag_with_no_protocol_field_is_refused_not_crashed():
    """The `len(parts) < 2` half of clause 3, which the protocol-skew test above
    can never reach.

    Clause 3 is COMPOUND (`len(parts) < 2 or parts[1] != str(PROTO)`), and a
    compound condition needs a twin PER CLAUSE: the skew test supplies a full frame,
    so the length half is shadowed and could be deleted unnoticed. Without it a bare
    `MR` raises IndexError -- a crash, not a refusal, and a crash is not one of the
    four outcomes.
    """
    with pytest.raises(LiveQueryDegraded, match="protocol"):
        lp.decode_reply(lp.REPLY_TAG, 1)


def test_checksum_of_non_ascii_is_over_UTF8_BYTES_pinned_independently():
    """The checksum tests above are all ASCII, where utf-8 and latin-1 agree.

    That makes them blind to an encoding change: swap the codec and BOTH the frame
    helper and the decoder move together, so every round-trip test still passes
    while the game side -- which is fixed at bytes -- silently disagrees. Pinning
    the expected value from the byte sequence itself is the only version of this
    assertion that can go red.
    """
    payload = "\u00e9"                       # U+00E9: utf-8 = C3 A9, latin-1 = E9
    assert payload.encode("utf-8") == b"\xc3\xa9"
    expected = 5381
    for b in (0xC3, 0xA9):
        expected = ((expected * 33) + b) & 0xFFFFFFFF
    assert lp.checksum(payload) == expected


def test_byte_len_of_non_ascii_is_pinned_independently_of_the_frame_helper():
    """Same trap, the length half: `frame()` computes the declared length with the
    very function under test, so a chars-not-bytes mutation agrees with itself."""
    assert lp.byte_len("\u00e9\u00e9\u00e9") == 6
    assert lp.byte_len("abc") == 3


# --- the shipped hint carries an EVIDENCE TIER, and it must survive ----------- #


def test_the_hint_keeps_the_two_focus_measurements_SEPARATE():
    """★ This text SHIPS, and until 2026-08-31 it was wrong in the direction that
    sends a user to the wrong fix.

    It said, in capitals, that X4 STOPS EXECUTING WHEN IT IS NOT IN THE FOREGROUND.
    MEASURED 2026-08-30 by sampling the engine's own getElapsedTime() over a 30 s wall
    window: windowed UNFOCUSED is 32.98/32.98 and windowed FOCUSED is 32.24/32.24 --
    a ratio of **1.00 in both**. Windowed and unfocused, the game runs at full speed.

    The 13.6% figure is real but is a DIFFERENT condition (minimized in exclusive
    fullscreen), is OLDER, has NOT been re-measured, and never separated minimized
    from merely unfocused -- which is exactly how it came to be generalised.

    Two measurements of different ages must not be flattened into one claim. Telling a
    windowed user to foreground the game costs them the real diagnosis, which is the
    failure this message exists to prevent.
    """
    from x4validate._livepipe import MINIMIZED_HINT as h

    assert "1.00" in h and "13.6%" in h, "one of the two measurements was dropped"
    # ⚠ NOT `"older" in h`. That substring matches "f-OLDER" in "extensions folder",
    # so the assertion could never fail while the text mentions a folder -- a green
    # with no reachable red branch, in the very test written to enforce an evidence
    # tier. Found by the mutant that strips the qualifier surviving. Match the phrase.
    assert "OLDER figure" in h and "NOT re-measured" in h, (
        "the 13.6% figure is presented without its age -- that is the flattening")
    assert "DO NOT MINIMIZE" in h
    assert "STOPS EXECUTING WHEN IT IS NOT" not in h, (
        "the over-strong claim is back; windowed-unfocused measured 1.00")


def test_the_hint_names_the_extension_and_its_dependency():
    """A refusal that cannot tell the user WHAT to install is only half a refusal.
    Two separate installs are involved and naming one is not enough."""
    from x4validate._livepipe import MINIMIZED_HINT as h

    assert "X4 Toolkit Helper" in h, "the refusal never names the extension"
    assert "ws_2042901274" in h, "the refusal never names the pipe-api dependency"
    assert "_LIVE loaded" in h, "no way for the user to check whether it loaded at all"

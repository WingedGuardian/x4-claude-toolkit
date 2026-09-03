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


def frame_bytes(payload_bytes, seq=1, status="OK", blen=None, csum=None):
    """A valid reply whose PAYLOAD is arbitrary bytes.

    The str helper above cannot express this: `decode_reply` encodes a str losslessly,
    so no test built on it can produce a payload that is not valid UTF-8, and clause 9
    was therefore unreachable from the entire suite. The header stays ASCII, which is
    what the frame format guarantees.
    """
    head = "\t".join((
        lp.REPLY_TAG,
        str(lp.PROTO),
        str(seq),
        status,
        str(lp.byte_len(payload_bytes) if blen is None else blen),
        str(lp.checksum(payload_bytes) if csum is None else csum),
        "",
    ))
    return head.encode("utf-8") + payload_bytes


#: A multibyte character, kept as bytes so a split can be expressed at all.
_EURO = "\u20ac".encode("utf-8")            # 3 bytes: e2 82 ac


def test_the_byte_baseline_decodes_cleanly():
    """Same reason as the str baseline: if this frame did not decode, every test below
    would pass for the wrong reason."""
    r = lp.decode_reply(frame_bytes("caf\u00e9".encode("utf-8")), 1)
    assert r.payload == "caf\u00e9"


def test_clause9_invalid_utf8_that_PASSES_length_and_checksum_is_UNDECODABLE():
    """The bytes are intact -- the length and the checksum both agree -- so the fault is
    the game's encoding, and that is a third distinct fact rather than corruption. A
    lenient decode here reports a clean answer over a payload it silently rewrote."""
    bad = b"ab" + bytes([0xFF]) + b"cd"
    with pytest.raises(LiveQueryDegraded, match="UNDECODABLE"):
        lp.decode_reply(frame_bytes(bad), 1)


def test_clause9_names_the_offending_byte_and_the_reason():
    bad = b"ab" + bytes([0xFF]) + b"cd"
    with pytest.raises(LiveQueryDegraded) as exc:
        lp.decode_reply(frame_bytes(bad), 1)
    msg = str(exc.value)
    assert "byte 2" in msg, msg
    assert "5 payload bytes" in msg, msg


def test_a_multibyte_char_CUT_at_the_buffer_edge_is_TRUNCATED_not_undecodable():
    """The distinction the clause ORDER exists to preserve. Two bytes of a three-byte
    character arrived and the header still declares three, so the caller's problem is a
    short read -- something they can act on -- not an encoding fault."""
    cut = _EURO[:2]
    with pytest.raises(LiveQueryDegraded, match="TRUNCATED"):
        lp.decode_reply(frame_bytes(cut, blen=3, csum=lp.checksum(_EURO)), 1)


def test_a_SELF_CONSISTENT_cut_multibyte_char_is_UNDECODABLE():
    """The same physical damage, but with a header that agrees with it: length and
    checksum are computed over the truncated bytes, so clauses 7 and 8 both pass and
    only the strict decode can still tell that something is wrong. This is the case a
    lenient decode CANCELS -- it would return a replacement character and call it OK."""
    cut = _EURO[:2]
    with pytest.raises(LiveQueryDegraded, match="UNDECODABLE"):
        lp.decode_reply(frame_bytes(cut), 1)


def test_a_lenient_decode_would_INVENT_a_length_mismatch():
    """Why clause 9 runs last and on bytes. Decoding leniently first turns each bad byte
    into U+FFFD (+2 bytes on re-encode), so the length clause then measures a string we
    invented. Here the frame is VALID and must decode -- the arithmetic is the point:
    a repaired copy would be longer than the bytes that actually arrived."""
    payload = _EURO * 3
    r = lp.decode_reply(frame_bytes(payload), 1)
    assert r.payload == "\u20ac" * 3
    repaired = payload.decode("utf-8", errors="replace").encode("utf-8")
    assert len(repaired) == len(payload), "control: a VALID payload survives either way"

    broken = b"a" + bytes([0xFF]) + b"b"
    assert len(broken.decode("utf-8", errors="replace").encode("utf-8")) > len(broken), (
        "a lenient decode grows the payload, which is what silently moved the length")


def test_a_str_argument_is_still_accepted():
    """The twin for the bytes work: every existing caller passes a str and must keep
    working. A rewrite that demanded bytes would break all 20 call sites."""
    assert lp.decode_reply(frame(payload="hello"), 1).payload == "hello"


class _FakeWin32File:
    """Just enough win32file for `_read_raw`: one ReadFile that returns bytes."""

    def __init__(self, payload):
        self.payload = payload

    def ReadFile(self, handle, size):
        return 0, self.payload


class _FakeWinError:
    ERROR_NO_DATA = 232
    ERROR_PIPE_LISTENING = 536


def test_read_raw_returns_RAW_BYTES_not_a_decoded_string(monkeypatch):
    """The transport must hand `decode_reply` exactly what arrived.

    Decoding here with errors="replace" repairs the frame before anything has measured
    it, and the length and checksum clauses then measure the repair -- each replacement
    character adding +2 bytes, which both invents truncations and CANCELS real ones. A
    cancelled truncation is a corrupt frame served as a clean answer.

    Nothing exercised this path, so that exact reversion survived the whole suite.
    `_win32` is stubbed rather than mocked at the pipe level: it is already a lazy
    indirection so the package stays installable where there is no pywin32, which makes
    it the seam that needs neither Windows nor a real pipe.
    """
    payload = b"ok" + bytes([0xFF]) + b"raw"
    monkeypatch.setattr(
        lp, "_win32",
        lambda: (None, _FakeWin32File(payload), _FakeWinError))
    pipe = lp.LivePipe.__new__(lp.LivePipe)
    pipe._h = object()
    pipe.timeout = 1.0
    got = pipe._read_raw(deadline=float("inf"))
    assert isinstance(got, bytes), "the transport decoded; it must not"
    assert got == payload, "the bytes must arrive unaltered"


def test_read_raw_does_NOT_repair_an_undecodable_byte(monkeypatch):
    """The twin, stated as the property rather than the type: an invalid byte must still
    be that byte when decode_reply measures it. `bytes(...)` alone would be satisfied by
    a lenient round-trip on a payload that happened to be valid UTF-8."""
    payload = b"a" + bytes([0xFF]) + b"b"
    monkeypatch.setattr(
        lp, "_win32",
        lambda: (None, _FakeWin32File(payload), _FakeWinError))
    pipe = lp.LivePipe.__new__(lp.LivePipe)
    pipe._h = object()
    pipe.timeout = 1.0
    got = pipe._read_raw(deadline=float("inf"))
    assert bytes([0xFF]) in got, "the invalid byte was repaired in transit"
    repaired = payload.decode("utf-8", errors="replace").encode("utf-8")
    assert len(got) < len(repaired), (
        "a repaired payload is LONGER, which is how a lenient read moved the length")


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

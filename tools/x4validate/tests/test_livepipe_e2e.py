"""End-to-end over a REAL Windows named pipe, with Python standing in for X4.

WHY THIS EXISTS. `test_livepipe.py` proves the frame contract by calling
`decode_reply` directly. That is necessary and not sufficient: it never opens a pipe,
so it cannot catch a wrong `CreateNamedPipe` flag, a blocking call that should not
block, a message-mode/byte-mode mix-up, or a timeout that never fires. Every one of
those is invisible to a codec test and fatal in the game.

Running it against a Python client rather than the game is the point, not a
compromise: the game costs a launch, cannot be made to truncate on purpose, and
cannot be asked to go silent on demand. Here all three are one line each. The game
launch then tests the ONE thing this cannot -- that the lua side speaks the same
frame -- instead of testing the transport for the first time.

⚠ WHAT THIS DOES NOT PROVE. The stand-in is written from the same understanding of
the protocol as the code under test, so agreement here is agreement with MYSELF. It
cannot show that `pipes.lua` truncates where we think, that a passive
`Schedule_Read` fires without a preceding write, or that lua's `#s` and our
`byte_len` agree on a real payload. Those need the game. Recorded here so a green run
is not read as more than it is.
"""
from __future__ import annotations

import io
import threading
import time

import pytest

win32file = pytest.importorskip("win32file", reason="pywin32; Windows-only channel")
win32pipe = pytest.importorskip("win32pipe")

from x4validate import _livepipe as lp                      # noqa: E402
from x4validate._livepipe import LiveQueryDegraded, LiveQueryUnavailable  # noqa: E402


def _unique(name: str) -> str:
    """A distinct pipe per test.

    Shared names would make two tests -- or two concurrent sessions on this machine
    -- collide over `nMaxInstances=1`, and the failure would look like a transport
    bug rather than a fixture bug.
    """
    return f"x4live_test_{name}_{threading.get_ident()}_{int(time.monotonic()*1000)%100000}"


class FakeGame:
    """The X4 side, in Python. Mirrors the game-side lua mod's framing.

    `behaviour` selects what it does with a reply, so the transport can be pushed
    into each failure mode ON PURPOSE. A test harness that can only produce the happy
    path proves the happy path.
    """

    def __init__(self, path: str, behaviour: str = "ok", n: int = 1):
        self.path = path
        self.behaviour = behaviour
        self.n = n
        self.error: BaseException | None = None
        self.seen: list[str] = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _connect(self, deadline: float):
        while time.monotonic() < deadline:
            try:
                h = win32file.CreateFile(
                    self.path,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None)
                win32pipe.SetNamedPipeHandleState(
                    h, win32pipe.PIPE_READMODE_MESSAGE, None, None)
                return h
            except Exception:  # silent-ok: server may not be listening yet
                time.sleep(0.01)
        raise TimeoutError(f"could not connect to {self.path}")

    def _frame(self, seq: str, status: str, payload: str) -> str:
        blen = lp.byte_len(payload)
        csum = lp.checksum(payload)
        if self.behaviour == "truncate":
            # Exactly `pipes.lua:698`: declare the full length, send less. The
            # unhandled ERROR_MORE_DATA case, reproduced deliberately.
            payload = payload[: max(0, len(payload) // 2)]
        elif self.behaviour == "corrupt":
            csum += 1
        elif self.behaviour == "badseq":
            seq = str(int(seq) + 5)
        elif self.behaviour == "badproto":
            return "\t".join((lp.REPLY_TAG, "99", seq, status, str(blen), str(csum), payload))
        elif self.behaviour == "sentinel":
            return "ERROR"
        return "\t".join((lp.REPLY_TAG, str(lp.PROTO), seq, status, str(blen),
                          str(csum), payload))

    def _run(self) -> None:
        h = None
        try:
            h = self._connect(time.monotonic() + 10)
            for _ in range(self.n):
                _err, data = win32file.ReadFile(h, 64 * 1024)
                msg = data.decode("utf-8")
                self.seen.append(msg)
                f = msg.split("\t")
                seq, verb, args = f[2], f[3], f[4:]
                if self.behaviour == "silent":
                    # Connected, then nothing. The "loaded but paused or hung" state,
                    # which must NOT be reported the same way as "never loaded".
                    time.sleep(30)
                    return
                if verb == "ping":
                    out = self._frame(seq, "OK", "pong\t1\t123.5")
                elif verb == "echo":
                    out = self._frame(seq, "OK", "x" * int(args[0]))
                elif verb == "macro":
                    # ltype, name, field. ABSENT for a deliberate subset, so the
                    # harvest's present/absent/errored accounting is exercised rather
                    # than only its happy path.
                    field = args[2] if len(args) > 2 else ""
                    if field.startswith(("docks_", "launchtubes_")):
                        out = self._frame(seq, "ABSENT", field)
                    else:
                        out = self._frame(seq, "OK", f"{len(field)}.5")
                elif verb == "missing":
                    out = self._frame(seq, "ABSENT", "no such thing")
                else:
                    out = self._frame(seq, "ERR", f"unknown verb: {verb}")
                win32file.WriteFile(h, out.encode("utf-8"))
        except BaseException as exc:                      # noqa: BLE001
            self.error = exc
        finally:
            if h is not None:
                try:
                    win32file.CloseHandle(h)
                except Exception:  # silent-ok: teardown
                    pass


def run(name: str, behaviour: str = "ok", n: int = 1, timeout: float = 8.0):
    """Stand up the server, connect the fake game, hand back both."""
    pipe = lp.LivePipe(name=_unique(name), timeout=timeout)
    pipe.open()
    game = FakeGame(pipe.path, behaviour=behaviour, n=n)
    game.start()
    pipe.wait_for_game()
    return pipe, game


# --------------------------------------------------------------------------- #
# the happy path -- proves the transport, not just the codec
# --------------------------------------------------------------------------- #

def test_a_real_round_trip_over_a_real_pipe():
    pipe, game = run("ok")
    try:
        r = pipe.ask("ping")
        assert r.status == "OK"
        assert r.fields == ["pong", "1", "123.5"]
        assert game.seen[0].startswith(f"{lp.CMD_TAG}\t{lp.PROTO}\t1\tping")
    finally:
        pipe.close()
    assert game.error is None, game.error


def test_sequence_numbers_advance_across_several_questions():
    """Correlation is positional in the lua api, so the sequence has to move and be
    checked. A fixed sequence would pass every single-question test ever written."""
    pipe, game = run("multi", n=3)
    try:
        for expected in (1, 2, 3):
            assert pipe.ask("ping").seq == expected
    finally:
        pipe.close()
    assert game.error is None, game.error


def test_a_large_payload_survives_intact():
    """8 KB through the real pipe, length and checksum verified.

    Deliberately above the unsourced 2047-byte figure, so if that limit is real at
    THIS layer the test says so here rather than in the game.
    """
    pipe, game = run("big")
    try:
        r = pipe.ask("echo", "8192")
        assert r.status == "OK"
        assert lp.byte_len(r.payload) == 8192
    finally:
        pipe.close()
    assert game.error is None, game.error


def test_ABSENT_arrives_as_an_answer_not_an_error():
    pipe, _ = run("absent")
    try:
        r = pipe.ask("missing")
        assert r.status == "ABSENT" and not r.ok
    finally:
        pipe.close()


# --------------------------------------------------------------------------- #
# the failure modes, each induced ON PURPOSE -- this is the half that matters
# --------------------------------------------------------------------------- #

def test_truncation_is_caught_over_the_wire():
    """The falsification twin for the whole module.

    If this passes cleanly, `pipes.lua`'s silent cut would reach a caller as a
    short-but-well-formed answer -- the exact defect the length field exists for.
    """
    pipe, _ = run("trunc", behaviour="truncate")
    try:
        with pytest.raises(LiveQueryDegraded, match="TRUNCATED"):
            pipe.ask("echo", "400")
    finally:
        pipe.close()


def test_corruption_is_caught_over_the_wire():
    pipe, _ = run("corrupt", behaviour="corrupt")
    try:
        with pytest.raises(LiveQueryDegraded, match="checksum mismatch"):
            pipe.ask("ping")
    finally:
        pipe.close()


def test_a_desynced_reply_is_caught_over_the_wire():
    pipe, _ = run("desync", behaviour="badseq")
    try:
        with pytest.raises(LiveQueryDegraded, match="out of step"):
            pipe.ask("ping")
    finally:
        pipe.close()


def test_protocol_skew_is_caught_over_the_wire():
    pipe, _ = run("skew", behaviour="badproto")
    try:
        with pytest.raises(LiveQueryDegraded, match="protocol"):
            pipe.ask("ping")
    finally:
        pipe.close()


def test_a_reserved_sentinel_on_the_wire_is_not_mistaken_for_data():
    pipe, _ = run("sentinel", behaviour="sentinel")
    try:
        with pytest.raises(LiveQueryDegraded, match="reserved sentinel"):
            pipe.ask("ping")
    finally:
        pipe.close()


# --------------------------------------------------------------------------- #
# the three liveness states, which must never collapse into one verdict
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("running,must_contain", [
    # The anchor moved from "MINIMIZED" to "X4 IS RUNNING" on 2026-08-29, when the
    # cause was pinned down: the game stops executing whenever it is not in the
    # FOREGROUND (the frame loop drives the pipe poller), and minimize is only one
    # way to get there. The old anchor tested the WORDING of a since-corrected
    # theory; this one tests the PROPERTY -- that this branch names the state it
    # found. It is still a real discriminator: the other two branches render
    # "running" in lower case, so a collapse of the trio fails here.
    (True,  "X4 IS RUNNING"),  # the retryable state -- the whole point of the branch
    (False, "NOT RUNNING"),
    (None,  "could not determine"),
])
def test_NEVER_CONNECTED_names_WHICH_of_three_states_it_is(monkeypatch, running, must_contain):
    """Nothing connected is THREE states, and conflating them cost a session.

    Until 2026-08-29 all three produced "the game is not running, or the mod is not
    deployed" -- so a MINIMIZED game read as a deployment failure, and the correct
    response (restore the window and retry) looked like the wrong one (go debug the
    mod). A future session must be able to tell a RETRYABLE state from a broken one.

    `game_is_running` is monkeypatched rather than observed, because otherwise this
    test's outcome depends on whether X4 happens to be running on the machine -- which
    it did, briefly, and which is ambient state leaking into a result.
    """
    monkeypatch.setattr(lp, "game_is_running", lambda: running)
    pipe = lp.LivePipe(name=_unique("nobody"), timeout=0.4)
    pipe.open()
    try:
        with pytest.raises(LiveQueryUnavailable) as exc:
            pipe.wait_for_game()
        assert must_contain in str(exc.value)
    finally:
        pipe.close()


def test_the_retryable_states_SAY_they_are_retryable(monkeypatch):
    """A message that diagnoses but does not prescribe still gets shrugged at."""
    for running in (True, None):
        monkeypatch.setattr(lp, "game_is_running", lambda r=running: r)
        pipe = lp.LivePipe(name=_unique("hint"), timeout=0.3)
        pipe.open()
        try:
            with pytest.raises(LiveQueryUnavailable) as exc:
                pipe.wait_for_game()
            msg = str(exc.value)
            assert "RETRYABLE" in msg and "re-arms" in msg, msg
        finally:
            pipe.close()


def test_the_three_messages_are_ACTUALLY_DIFFERENT(monkeypatch):
    """Guards the trio against a refactor that unifies the wording. Three states
    reported in identical language are one state, however carefully the code
    distinguishes them internally."""
    msgs = []
    for running in (True, False, None):
        monkeypatch.setattr(lp, "game_is_running", lambda r=running: r)
        pipe = lp.LivePipe(name=_unique("distinct"), timeout=0.3)
        pipe.open()
        try:
            with pytest.raises(LiveQueryUnavailable) as exc:
                pipe.wait_for_game()
            msgs.append(str(exc.value))
        finally:
            pipe.close()
    assert len(set(msgs)) == 3, "two of the three states are worded identically"


def test_CONNECTED_THEN_SILENT_is_reported_as_paused_or_hung_not_as_not_loaded():
    """The distinction a sibling project's probe collapsed, and was wrong about for
    three releases: it hung in exactly the case it existed to detect.

    Here the client IS connected, so the mod is demonstrably loaded -- and the
    message has to say so, because the next action differs completely.
    """
    pipe, _ = run("silent", behaviour="silent", timeout=0.5)
    try:
        with pytest.raises(LiveQueryUnavailable) as exc:
            pipe.ask("ping")
        msg = str(exc.value)
        assert "The mod IS loaded" in msg
        assert "paused" in msg and "hung" in msg
    finally:
        pipe.close()


def test_the_two_silence_messages_are_actually_different():
    """Guards the pair above against a refactor that unifies the wording.

    Two states reported in identical language are one state, however carefully the
    code distinguishes them internally.
    """
    a = lp.LivePipe(name=_unique("m1"), timeout=0.3)
    a.open()
    try:
        with pytest.raises(LiveQueryUnavailable) as never:
            a.wait_for_game()
    finally:
        a.close()

    b, _ = run("m2", behaviour="silent", timeout=0.4)
    try:
        with pytest.raises(LiveQueryUnavailable) as silent:
            b.ask("ping")
    finally:
        b.close()

    assert str(never.value) != str(silent.value)


# --------------------------------------------------------------------------- #
# the ground-truth harvest, end to end
# --------------------------------------------------------------------------- #

def _harvest(tmp_path, name):
    """Start the fake game BEFORE the server exists, then let the command create it.

    `FakeGame._connect` retries for 10s, so it will find the pipe once
    `cmd_groundtruth` opens it. The obvious alternative -- open a pipe, connect the
    game, close it, then call the command -- does not work and is worth naming: closing
    the server kills the connection, the already-connected game never retries, and the
    command sits waiting for a client that is gone. The test would then fail with the
    production "nothing connected" message and look like a transport bug.
    """
    from x4validate import _livecli as C

    # Build the path via LivePipe rather than re-spelling it. One implementation of the
    # `\\.\pipe\...` form, and a hand-written literal here already lost its leading
    # backslashes once -- which failed as "nothing connected", i.e. exactly the
    # production message, and read as a transport bug rather than a typo.
    game = FakeGame(lp.LivePipe(name=name).path, n=10_000)
    game.start()
    dest = tmp_path / f"{name}.tsv"
    buf = io.StringIO()
    rc = C.cmd_groundtruth(name, 12.0, str(dest), out=buf)
    return rc, dest, buf.getvalue(), game


def test_groundtruth_harvests_and_WRITES_THE_FIXTURE(tmp_path):
    """One launch must produce a durable fixture, because the last one did not.

    The engine's derived values previously came from a uidata dump that a game restart
    destroyed, which stalled the F72 traversals. This path never touches a file the
    game owns.
    """
    from x4validate import _livecli as C

    rc, dest, out, game = _harvest(tmp_path, _unique("gt"))
    assert rc == 0, out
    assert dest.is_file()
    text = dest.read_text(encoding="utf-8")
    assert "librarytype	macro	field	engine_value" in text
    body = [l for l in text.splitlines() if l and not l.startswith(("#", "librarytype"))]
    assert len(body) > 50, f"only {len(body)} harvested rows"
    # docks_* were answered ABSENT, so they must NOT appear as recorded values --
    # an absence written down as a value is the whole failure mode this guards.
    assert not any("	docks_s	" in l for l in body), "an ABSENT field became a value"
    # 109 = ERROR_BROKEN_PIPE. The fake game is armed for 10,000 messages and the
    # command sends ~200, so it is still reading when the pipe closes. That is normal
    # teardown, NOT a transport fault -- and asserting `error is None` here would fail
    # a correct subject because of the HARNESS, which is this workspace's single most
    # repeated defect shape. Any OTHER error still fails.
    assert game.error is None or getattr(game.error, "winerror", None) == 109, game.error


def test_groundtruth_ACCOUNTS_for_every_cell_it_asked_about(tmp_path):
    """present + absent + errored == asked, asserted by the command itself.

    A harvest that quietly loses rows is worse than none: the gap reads as "the engine
    does not report that field", which is a claim about the ENGINE made from a bug in
    the harvester.
    """
    from x4validate import _livecli as C

    rc, dest, out, _ = _harvest(tmp_path, _unique("gt2"))
    assert rc == 0, out
    head = [l for l in dest.read_text(encoding="utf-8").splitlines()
            if l.startswith("# asked=")]
    assert len(head) == 1
    nums = dict(kv.split("=") for kv in head[0].lstrip("# ").split())
    assert int(nums["present"]) + int(nums["absent"]) + int(nums["errored"])         == int(nums["asked"])
    # macros x (each derived field + ONE all-fields probe). The all-fields call is
    # what answers "does the engine expose <x> at all", which the named-field loop
    # structurally cannot -- so it is part of the arity, not an extra.
    assert int(nums["asked"]) == len(C.GROUND_TRUTH_MACROS) * (len(C._DERIVED) + 1)


def test_the_RAMP_runs_end_to_end_and_reports_a_bound():
    """The ramp had no E2E test until 2026-08-29, and it is half of what a live run does.

    The fake game echoes exactly n bytes, so every size round-trips and the command must
    take its "every size passed" branch -- the one that REFUSES to report its own top
    size as a measured cap. That refusal is the whole reason a ramp cannot quietly hand
    back the instrument's limit as a finding.
    """
    import io

    from x4validate import _livecli as C

    name = _unique("ramp")
    FakeGame(lp.LivePipe(name=name).path, n=10_000).start()
    buf = io.StringIO()
    rc = C.cmd_ramp(name, 12.0, out=buf)
    out = buf.getvalue()

    assert rc == 0, out
    assert "MESSAGE-SIZE RAMP" in out
    assert "largest payload that round-tripped INTACT" in out
    assert "NOT a measured cap" in out, (
        "every size passed, so the ceiling is above the ramp -- the command must say so "
        "rather than report its own top size")


def test_the_ramp_reports_TRUNCATION_as_a_NON_ANSWER_not_a_cap_of_zero():
    """The other branch. Every size truncates, so nothing round-trips -- and that is a
    non-answer about the cap (rc 2), never a measured cap of zero."""
    import io

    from x4validate import _livecli as C

    name = _unique("ramptrunc")
    FakeGame(lp.LivePipe(name=name).path, behaviour="truncate", n=10_000).start()
    buf = io.StringIO()
    rc = C.cmd_ramp(name, 12.0, out=buf)
    out = buf.getvalue()
    assert rc == 2, out
    assert "NOTHING round-tripped" in out
    assert "does not bound the cap" in out

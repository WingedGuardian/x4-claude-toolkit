r"""Ask the RUNNING engine a question, over a Windows named pipe.

THE COMPLEMENT TO `_livedump`. That module reads `{profile}/uidata.xml`, which the
engine truncates to 61 bytes while the game is running and writes back only on exit
-- an OFFLINE BULK oracle. This one is the LIVE SPOT CHECK: a fixed vocabulary asked
of the engine mid-session. They are complements, not alternatives.

THE TRANSPORT, AND WHY WE ARE THE SERVER. `sn_mod_support_apis` ships a lua pipe API
whose `ui/named_pipes/pipes.lua` opens a CLIENT handle to `\\.\pipe\<name>`. It does
not care who created that pipe, so `Pipe_Server_Host` / `Register_Module` /
`permissions.json` -- which exist only so a mod can ship a python file the HOST
auto-launches -- are not needed. We create the pipe; the game connects to it. That
makes the game-side mod three files and zero MD.

READ `pipes.lua:127`: `Schedule_Read(pipe_name, callback, continuous_read)`. With
`continuous_read` true the callback stays armed (`pipes.lua:513-515` declines to pop
the FIFO entry), so the SERVER PUSHES and the game never polls. `md/hotkey_api.xml`
runs exactly this shape in production.

    ---------------------------------------------------------------------------
    THE HAZARD THIS MODULE EXISTS TO REFUSE
    ---------------------------------------------------------------------------
    `pipes.lua:698`, verbatim:

        If the message is larger than the lua side buffer, returns partial
        data and error ERROR_MORE_DATA.  TODO: look into this.

    CORRECTED 2026-08-29 by reading the PACKED `pipes.lua` (it ships in a .cat,
    not loose; extracted from `ext_01.dat` at offset 400716, length 33966). The
    TODO is unhandled, but until today this docstring described the consequence
    wrongly in TWO ways, and both corrections matter:

      * DIRECTION. That comment sits on `_Read_Pipe_Raw` -- the game reading OUR
        COMMAND. It says nothing about our replies.
      * OUTCOME. It is NOT silent truncation. `winpipe` exposes only
        ERROR_IO_PENDING and ERROR_NO_DATA (`strings` on the DLL), so there is no
        constant to compare against and ERROR_MORE_DATA (234) falls through to
        `pipes.lua:720` `error(...)`. That is caught by `Read_Pipe`'s pcall,
        reaches `Poll_For_Reads:560` -> `Close_Pipe`, and ERRORs every pending
        read AND write while destroying the pipe. The partial data is discarded.

    The REPLY direction fails the same way, by the api's own documentation:
    "If the write buffer to the server fills up ... or the new message is larger
    than the entire buffer, the pipe will be treated as bad and closed."

    So an over-long message in EITHER direction is a loud, total pipe teardown --
    never a quiet short answer. That is the safer failure (a torn pipe cannot be
    mistaken for data), but it inverts the mitigation: SIZE MUST BE BOUNDED
    BEFORE SENDING, not detected afterwards. Any verb whose result set is
    unbounded caps itself and reports `shown=N of M`.

    The ceiling is still not fully known: python buffers 1 MiB (`_BUF`, raised from
    ramp MEASURED every size up to 64,000 bytes round-tripping intact on
    2026-08-29 -- which refuted an earlier untraceable 2047-byte figure. The true
    ceiling lies above our own buffer and cannot be probed without raising it.
    See BLIND-SPOTS F74.

    Every reply still carries its own BYTE LENGTH and a checksum computed
    game-side over the payload, so a short read fails clause 7 by construction.
    ---------------------------------------------------------------------------

THE FOUR OUTCOMES, matching `_livedump` so the two oracles ladder identically:

  | outcome                                   | meaning                    | exit |
  |-------------------------------------------|----------------------------|------|
  | not Windows / no pywin32 / never connects  | cannot ask                 | 2    |
  | connects, then silence                     | loaded but paused/hung     | 2    |
  | reply malformed, short, or mis-sequenced   | a NON-ANSWER               | 3    |
  | reply self-checks                          | a real answer, even ABSENT | 0/1  |

Note the third row. `ERROR`, `TIMEOUT` and `CANCELLED` are reserved sentinels in the
lua api's DATA channel, so a naive reader cannot tell them from a payload that
happens to equal one. Ours can: every real reply is a 7-field frame led by `MR`, and
a bare sentinel has no tabs at all.

Never collapse "not loaded" into "not answering". The Skyrim VR session shipped a
liveness probe that was wrong for three releases because it hung in exactly the case
it existed to detect.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import _paths

#: Default pipe name. Override with `X4_LIVE_PIPE`.
#: ⚠ Resolved through `_paths.value()`, NEVER `path_value()` -- the latter runs
#: `native()`, which would mangle a `\\.\pipe\...` string into a filesystem path.
DEFAULT_PIPE = "x4live"

#: Bumped only on a frame change. A mod and a toolkit that disagree must say so
#: rather than mis-parse each other; clause 3 enforces it.
PROTO = 1

CMD_TAG = "MQ"
REPLY_TAG = "MR"
_REPLY_FIELDS = 7

#: A reply's `status`. ABSENT is an ANSWER -- the engine was asked and said no such
#: thing -- and must never be confused with "we could not ask", which is rc 2.
STATUSES = ("OK", "ABSENT", "ERR")

#: Our read buffer, and the size hint for both named-pipe buffers.
#:
#: ESTABLISHED 2026-08-31 by reading the code rather than repeating this module's own
#: docstring: OUR SIDE CAPS FIRST on the reply path. `_read_raw` does a SINGLE
#: `ReadFile(self._h, _BUF)` -- no loop on ERROR_MORE_DATA -- so a reply larger than
#: this cannot arrive whole. It is DETECTED rather than silent: `decode_reply` checks
#: the declared LENGTH before the checksum, precisely so the diagnosis is "truncated"
#: and not "corrupt". But detected-and-refused still means the ramp stops HERE, and a
#: ramp that stops at its own limit reports that limit as an engine finding (which it
#: did once, as "the ceiling lies in (60000, 65536]").
#:
#: Raised 64 KiB -> 1 MiB so F74's ceiling can be probed at all. This does NOT measure
#: the engine; it removes US from the measurement. The send path is still bounded by
#: the game's own lua buffer (`pipes.lua:698`), which is the thing F74 is about, and
#: an over-long message there TEARS THE PIPE DOWN rather than truncating.
_BUF = 1024 * 1024


#: Appended to every "nothing connected" refusal. A future session reading one of
#: these must be able to tell a RETRYABLE state from a broken one -- shrugging at a
#: paused game and reporting "failed" is exactly the outcome this text prevents.
#:
#: NB the grep target below is deliberately the GENERIC suffix. The mod's marker
#: carries a deployment-specific prefix, and spelling it here would put a personal
#: identifier into a shipped file -- the exact defect F73 was raised for.
MINIMIZED_HINT = (
    " DO NOT MINIMIZE THE GAME -- and note that merely UNFOCUSED is fine, which is "
    "the opposite of what this text said until 2026-08-31. TWO MEASUREMENTS OF "
    "DIFFERENT AGES, kept separate on purpose because collapsing them is what made "
    "the old advice wrong: (1) WINDOWED, measured 2026-08-30 by sampling the engine's "
    "own getElapsedTime() over a 30 s wall window -- unfocused 32.98 s engine / "
    "32.98 s wall and focused 32.24 / 32.24, a ratio of 1.00 in BOTH. Windowed and "
    "unfocused, the game runs at FULL SPEED, and a 370-query harvest completed "
    "cleanly that way. (2) MINIMIZED IN EXCLUSIVE FULLSCREEN, an OLDER figure and "
    "NOT re-measured since: 574.76 s of engine time across 70.4 min of wall clock "
    "(13.6%), and zero bytes written to debug.txt for 5.5 min. That case did not "
    "separate minimized from merely unfocused, which is how it came to be "
    "generalised to 'not in the foreground'. MECHANISM, read from source: the pipe "
    "is polled by `Poll_For_Reads` via `Time.Register_NewFrame_Callback`, driven by "
    "`SetScript(\"onUpdate\", ...)` plus an MD heartbeat the api documents as firing "
    "'every UNPAUSED frame' -- so a PAUSED game goes silent while the process stays "
    "alive and responding. Either way this is RETRYABLE, not a failure: restore the "
    "window, unpause, and run it again. Retrying costs nothing, because the mod "
    "re-arms itself every ~2s. IF THE GAME IS RUNNING AND VISIBLE and this still "
    "fails, the mod is probably not installed: grep debug.txt for '_LIVE loaded'. "
    "Absent means it never loaded -- a different problem with a different fix. The "
    "channel needs the X4 Toolkit Helper extension in the game's extensions folder, "
    "and its pipe half additionally needs Mod Support APIs (Steam Workshop "
    "ws_2042901274), which is a separate install."
)


class LiveQueryUnavailable(Exception):
    """Exit 2 -- a NON-ANSWER. We could not ask, so there is no finding here.

    Raised when the platform cannot host the channel at all, when the game never
    connects, and when it connects but stays silent. The message must always name
    WHICH of those it is: a probe that collapses "not loaded", "paused" and "hung"
    into one verdict is wrong in exactly the case it exists for.
    """


class LiveQueryDegraded(Exception):
    """Exit 3 -- degraded. Something answered, but the answer cannot be trusted.

    Truncation, corruption, protocol skew and FIFO desync all land here. This is
    NOT exit 2: a mangled reply is evidence the channel is misbehaving, which is a
    louder fact than silence, not a quieter one.
    """


# --------------------------------------------------------------------------- #
# codec -- pure, no win32, so the whole frame contract is unit-testable off-Windows
# --------------------------------------------------------------------------- #

def checksum(payload: str) -> int:
    """djb2 over the UTF-8 BYTES of `payload`, mod 2**32.

    Byte-wise, not character-wise, and the game side must agree exactly: lua's `#s`
    and `string.byte` are both byte operations, so a codepoint-based checksum here
    would disagree with the game on every non-ASCII payload -- and disagree SILENTLY,
    reporting corruption where there is none. Chosen over CRC32 because LuaJIT has no
    CRC32 and a hand-rolled one is a second thing to get wrong; djb2 is four lines on
    each side and truncation (the actual threat) is caught by the length clause
    regardless.
    """
    h = 5381
    for b in payload.encode("utf-8"):
        h = ((h * 33) + b) & 0xFFFFFFFF
    return h


def byte_len(payload: str) -> int:
    """Length in BYTES, because lua's `#s` is bytes. See `checksum`."""
    return len(payload.encode("utf-8"))


def encode_command(seq: int, verb: str, args: tuple[str, ...] = ()) -> str:
    """Frame a command for the game.

    ⚠ Never emits an empty string: the lua pipe api delivers an empty write as nil,
    so an empty message is indistinguishable from no message. The tag and sequence
    make that structurally impossible.
    """
    if not verb:
        raise ValueError("a command needs a verb; an empty message arrives as nil")
    for a in args:
        if "\t" in a or "\n" in a:
            raise ValueError(f"argument {a!r} contains a frame separator")
    return "\t".join((CMD_TAG, str(PROTO), str(seq), verb, *args))


@dataclass(frozen=True)
class Reply:
    """One decoded, self-checked reply. Reaching here means all 8 clauses passed."""

    seq: int
    status: str
    payload: str

    @property
    def ok(self) -> bool:
        return self.status == "OK"

    @property
    def fields(self) -> list[str]:
        """The payload split on tabs. Empty payload -> empty list, never `['']`."""
        return self.payload.split("\t") if self.payload else []


def decode_reply(text: str | None, expect_seq: int) -> Reply:
    """Decode one reply, or raise.

    EIGHT clauses, each with its own fixture and its own separately-applied mutant.
    They are listed in this order deliberately: a guard that fires first SHADOWS the
    ones behind it, so a single falsification twin only ever exercises the first
    clause it trips (CLAUDE.md #26, register #86/#99). Ordering choice worth naming:
    the LENGTH check precedes the CHECKSUM check so that a truncated reply is
    reported as TRUNCATED -- the diagnosis a caller can act on -- rather than as
    generic corruption.
    """
    # 1. Nothing at all. The lua api hands an empty write over as nil.
    if not text:
        raise LiveQueryDegraded(
            "empty reply: the lua pipe api delivers an empty write as nil, so this "
            "is a framing fault game-side, not an empty answer"
        )

    parts = text.split("\t", _REPLY_FIELDS - 1)

    # 2. Not one of our frames. Catches the api's reserved data-channel sentinels
    #    (ERROR / TIMEOUT / CANCELLED), which a naive reader cannot tell from data.
    if parts[0] != REPLY_TAG:
        head = text[:40].replace("\n", " ")
        hint = (
            " -- this is one of the lua api's reserved sentinels, not a payload"
            if text.strip() in ("ERROR", "TIMEOUT", "CANCELLED")
            else ""
        )
        raise LiveQueryDegraded(
            f"reply is not a {REPLY_TAG} frame (starts {head!r}){hint}"
        )

    # 3. Protocol skew: a mod and a toolkit from different versions.
    if len(parts) < 2 or parts[1] != str(PROTO):
        got = parts[1] if len(parts) > 1 else "<absent>"
        raise LiveQueryDegraded(
            f"protocol {got!r}, expected {PROTO!r} -- the deployed mod and this "
            f"toolkit disagree about the frame; redeploy the live-query mod"
        )

    # 4. Header truncated. Distinct from clause 7: this is a frame too short to
    #    even carry its own length, so nothing downstream can be trusted.
    if len(parts) != _REPLY_FIELDS:
        raise LiveQueryDegraded(
            f"reply has {len(parts)} fields, expected {_REPLY_FIELDS} -- the frame "
            f"header itself is truncated"
        )

    _, _, raw_seq, status, raw_len, raw_sum, payload = parts

    # 5. FIFO desync. Correlation is positional in the lua api, so the sequence
    #    number travels INSIDE the message; this is what makes it worth having.
    try:
        seq = int(raw_seq)
    except ValueError:
        raise LiveQueryDegraded(f"reply sequence {raw_seq!r} is not a number") from None
    if seq != expect_seq:
        raise LiveQueryDegraded(
            f"reply is for sequence {seq}, expected {expect_seq} -- the pipe FIFO is "
            f"out of step; a previous reply was probably dropped"
        )

    # 6. Unknown status: the game answered in a vocabulary we do not model.
    if status not in STATUSES:
        raise LiveQueryDegraded(
            f"unknown reply status {status!r}, expected one of {', '.join(STATUSES)}"
        )

    # 7. TRUNCATION -- the clause this whole module is built around. See the
    #    module docstring: the lua side cuts an over-long message short and says
    #    nothing, and a short TSV row is still a well-formed TSV row.
    try:
        declared = int(raw_len)
    except ValueError:
        raise LiveQueryDegraded(f"declared length {raw_len!r} is not a number") from None
    actual = byte_len(payload)
    if declared != actual:
        raise LiveQueryDegraded(
            f"TRUNCATED: the game declared {declared} payload bytes and {actual} "
            f"arrived. This is the `ERROR_MORE_DATA` case pipes.lua:698 leaves "
            f"unhandled -- ask for less, or chunk the reply"
        )

    # 8. Corruption that preserved the length. Rarer than truncation, and it is
    #    only because clause 7 runs first that this one gets to mean that.
    try:
        declared_sum = int(raw_sum)
    except ValueError:
        raise LiveQueryDegraded(f"declared checksum {raw_sum!r} is not a number") from None
    if declared_sum != checksum(payload):
        raise LiveQueryDegraded(
            f"checksum mismatch on a payload of the declared length -- the bytes "
            f"changed in transit, which truncation alone does not explain"
        )

    return Reply(seq=seq, status=status, payload=payload)


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #

def game_is_running() -> bool | None:
    """True / False / **None when we cannot tell** -- three states, never two.

    Delegates to _livedump.game_is_running, which is the same question with the same
    answer. This was a SECOND implementation, and it broke its own promise: it chained
    `.stdout` straight onto subprocess.run, so the RETURNCODE was structurally
    unavailable and a query that FAILED returned a confident False.

    MEASURED 2026-09-01 with a deliberately failing tasklist filter (rc=1, empty
    stdout): this shape returned False -- 'the game is not running' -- where the honest
    answer is None. wait_for_game would then tell a user whose game IS running to launch
    it. The only reason it never decided an outcome is that it is used solely to shape a
    message.
    """
    from . import _livedump
    return _livedump.game_is_running()


def pipe_name() -> str:
    return _paths.value("X4_LIVE_PIPE") or DEFAULT_PIPE


def _win32():
    """Import pywin32, or refuse with a NON-ANSWER naming the reason.

    Deliberately lazy and deliberately optional. The toolkit's CI runs ubuntu, and
    a hard Windows-only dependency would make the whole package uninstallable
    there; `winpipe.lua:44` gates itself on `package.config` for the same reason.
    """
    import sys

    if sys.platform != "win32":
        raise LiveQueryUnavailable(
            f"named pipes to X4 are Windows-only; this is {sys.platform}. The "
            f"offline oracle (`x4live oracle`) works everywhere"
        )
    try:
        import win32file
        import win32pipe
        import winerror
    except ImportError as exc:
        raise LiveQueryUnavailable(
            f"pywin32 is not installed ({exc}); the live channel needs it. "
            f"`uv add --group dev pywin32`, or use the offline `x4live oracle`"
        ) from exc
    return win32pipe, win32file, winerror


class LivePipe:
    """A named-pipe server the running game connects to. Context manager.

    Non-blocking throughout, with an explicit deadline on every wait, because a CLI
    that hangs is indistinguishable from a game that is hung -- which is the exact
    failure this channel exists to diagnose.
    """

    def __init__(self, name: str | None = None, timeout: float = 10.0) -> None:
        self.name = name or pipe_name()
        self.path = r"\\.\pipe" + "\\" + self.name
        self.timeout = timeout
        self._h = None
        self._seq = 0
        self._connected = False

    # -- lifecycle ---------------------------------------------------------- #

    def __enter__(self) -> LivePipe:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        win32pipe, _win32file, winerror = _win32()
        try:
            self._h = self._create(win32pipe)
        except Exception as exc:
            # ERROR_PIPE_BUSY (231): `nMaxInstances` is 1, so exactly one process can
            # serve this pipe. MEASURED 2026-08-29 -- a concurrent session was holding
            # it and this raised a raw pywintypes.error, i.e. an unhandled traceback,
            # which is NONE of the four outcomes. A collision is a NON-ANSWER with a
            # specific and actionable cause, so it says so.
            if getattr(exc, "winerror", None) == winerror.ERROR_PIPE_BUSY:
                raise LiveQueryUnavailable(
                    f"another process is already serving {self.path}. Only one server "
                    f"can hold it (nMaxInstances=1) -- a concurrent x4live, or another "
                    f"session. Stop that one, or use --pipe with a different name"
                ) from exc
            raise LiveQueryUnavailable(
                f"could not create {self.path}: {exc}") from exc

    def _create(self, win32pipe):
        return win32pipe.CreateNamedPipe(
            self.path,
            win32pipe.PIPE_ACCESS_DUPLEX,
            # MESSAGE mode both ways, so one Read yields exactly one Write and we
            # never have to re-frame a byte stream. NOWAIT so every wait below is
            # ours to bound -- see the class docstring.
            (win32pipe.PIPE_TYPE_MESSAGE
             | win32pipe.PIPE_READMODE_MESSAGE
             | win32pipe.PIPE_NOWAIT),
            1,          # nMaxInstances
            _BUF,       # out buffer
            _BUF,       # in buffer -- must exceed any single message, else the
                        # client's write fails with error code 0 (Pipe.py:238)
            300,        # default timeout, ms
            None,       # security: system defaults
        )

    def close(self) -> None:
        if self._h is not None:
            _win32pipe, win32file, _winerror = _win32()
            try:
                win32file.CloseHandle(self._h)
            except Exception:  # silent-ok: closing a dead handle is not a finding
                pass
            self._h = None
            self._connected = False

    # -- connection --------------------------------------------------------- #

    def wait_for_game(self, timeout: float | None = None) -> None:
        """Block until the game connects, or refuse with a NON-ANSWER.

        A timeout here means the mod is not loaded (or the game is not running).
        That is a DIFFERENT state from "connected but silent", which `ask` reports,
        and the two must never be merged.
        """
        win32pipe, _win32file, winerror = _win32()
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            try:
                win32pipe.ConnectNamedPipe(self._h, None)
                self._connected = True
                return
            except Exception as exc:
                code = getattr(exc, "winerror", None)
                if code == winerror.ERROR_PIPE_CONNECTED:
                    self._connected = True
                    return
                if code not in (winerror.ERROR_PIPE_LISTENING, winerror.ERROR_NO_DATA):
                    raise LiveQueryDegraded(
                        f"the pipe {self.path} failed unexpectedly: {exc}"
                    ) from exc
            if time.monotonic() >= deadline:
                # THREE distinct states, and the middle one is the trap. Until
                # 2026-08-29 this said "not running, or not deployed" for ALL of
                # them -- so a PAUSED game read as a deployment failure, and the
                # correct response (foreground the window, retry) looked like the
                # wrong one (go debug the mod).
                #
                # The cause is stated once, in MINIMIZED_HINT, and this comment
                # deliberately does NOT restate it. An earlier version of these two
                # texts disagreed about the evidence tier of the same claim -- this
                # comment said MEASURED where the hint said "INFERRED, not verified"
                # -- on the same code path. One source of truth, or they drift again.
                running = game_is_running()
                if running is True:
                    raise LiveQueryUnavailable(
                        f"X4 IS RUNNING but nothing connected to {self.path} within "
                        f"{self.timeout:.0f}s." + MINIMIZED_HINT)
                if running is False:
                    raise LiveQueryUnavailable(
                        f"X4 is NOT RUNNING, so nothing could connect to {self.path}. "
                        f"Launch the game -- a FRESH launch if the mod's lua changed, "
                        f"since a save/load is not verified to re-read it from disk.")
                raise LiveQueryUnavailable(
                    f"nothing connected to {self.path} within {self.timeout:.0f}s, "
                    f"and I could not determine whether X4 is running." + MINIMIZED_HINT)
            time.sleep(0.05)

    # -- exchange ----------------------------------------------------------- #

    def _read_raw(self, deadline: float) -> str:
        _win32pipe, win32file, winerror = _win32()
        while True:
            try:
                _err, data = win32file.ReadFile(self._h, _BUF)
                return data.decode("utf-8", errors="replace")
            except Exception as exc:
                if getattr(exc, "winerror", None) not in (
                    winerror.ERROR_NO_DATA,
                    winerror.ERROR_PIPE_LISTENING,
                ):
                    raise LiveQueryDegraded(f"read failed: {exc}") from exc
            if time.monotonic() >= deadline:
                raise LiveQueryUnavailable(
                    f"the game connected to {self.path} but sent nothing within "
                    f"{self.timeout:.0f}s. The mod IS loaded -- so this is the "
                    f"game not EXECUTING, not a deployment problem. It is paused, "
                    f"in a menu, hung, or (by far the most common) no longer in "
                    f"the foreground: the poller stops with the frame loop."
                    + MINIMIZED_HINT
                )
            time.sleep(0.02)

    def ask(self, verb: str, *args: str) -> Reply:
        """Send one command and return its self-checked reply."""
        _win32pipe, win32file, _winerror = _win32()
        if not self._connected:
            self.wait_for_game()
        self._seq += 1
        msg = encode_command(self._seq, verb, tuple(args))
        try:
            win32file.WriteFile(self._h, msg.encode("utf-8"))
        except Exception as exc:
            raise LiveQueryUnavailable(
                f"could not write to {self.path}: {exc}. The game most likely "
                f"closed the pipe (a save/load or /reloadui destroys it SILENTLY, "
                f"with no signal to the mod)"
            ) from exc
        return decode_reply(self._read_raw(time.monotonic() + self.timeout), self._seq)

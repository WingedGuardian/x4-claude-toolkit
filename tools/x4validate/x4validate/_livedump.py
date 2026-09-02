r"""Read what the RUNNING ENGINE knew, out of the profile's `uidata.xml`.

THE CHANNEL. A mod may declare `<savedvariable name="X" storage="userdata"/>` in its
`ui.xml`; the engine then serialises that lua global into `{profile}/uidata.xml` on
exit. So a read-only lua probe can export the engine's own view -- the extension list
it loaded, its error log, resolved macro stats -- and Python reads it back with no
pipe, no launch flag and no permissions grant.

WHY THIS MODULE IS NOT JUST `re.search`. THREE escaping layers sit between the file
and the data, and they were discovered by reading a real file, not assumed:

  1. XML entities   -- the payload is wrapped in `&quot; ... &quot;`.
  2. Lua escapes    -- a real TAB is written `\9`, but `\009` when the NEXT character
                       is a digit (`\9132` would be ambiguous). A real NEWLINE is a
                       backslash-newline continuation, not `\n`.
  3. Our own field escaping, applied by the probe before it ever reached lua.

Decode 1 -> 2 -> split -> 3. Any other order silently yields a well-formed table with
wrong contents, which is the worst failure available here.

THE TRAP THIS MODULE EXISTS TO REFUSE. **X4 truncates `uidata.xml` at startup and
writes it back on exit.** MEASURED: 342,342 bytes closed, 61 bytes (`<uidata
version="1"/>`) while running. That stub is VALID XML and parses perfectly to zero
variables -- so a naive reader run mid-session reports "0 extensions" in the exact
grammar of a real answer. Four outcomes must stay distinct and never collapse:

  | outcome                       | meaning                        | exit |
  |-------------------------------|--------------------------------|------|
  | file absent / holds no data   | game running, or never saved   | 2    |
  | data present, variable absent | the probe never ran            | 2    |
  | variable present, malformed   | truncated -- a NON-ANSWER      | 3    |
  | parses and self-checks        | a real finding, even if empty  | 0/1  |

The dump carries its own terminator row and row count, so a truncated payload is
detectable rather than merely short. `parse()` refuses unless the header is present,
the last row is the terminator, and the count the game itself wrote matches the count
we parsed -- three INDEPENDENT clauses, each with its own test, because a guard that
fires first shadows the ones behind it (CLAUDE.md #26).
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import _paths

#: The lua global the probe assigns; also the savedvariable name in its `ui.xml`.
#: Generic on purpose -- a probe is a personal mod, and its name must not be baked
#: into a shipped package. Override with `X4_LIVE_VAR` to read a differently-named
#: probe's dump.
DEFAULT_VAR = "__x4live_dump"

#: First field of the header row and of the terminator row.
HDR = "HDR"
#: Every row kind engine_probe.lua can emit, read off its `row(...)` calls. `EXT` is
#: built as a table literal rather than a string constant, which is exactly why this
#: list is written down here and pinned by a test rather than inferred.
KNOWN_KINDS = frozenset({
    "HDR", "END", "DELAYED_CAPABLE",
    "EXT", "EXT_FIELDS", "EXT_STATUS",
    "LIB", "LIB_ELEM_FIELDS", "LIB_ENTRY_FIELDS", "LIB_ENTRY_VAL", "LIB_STATUS",
    "ERR", "ERR_ROWS", "ERR_STATUS", "ERR_WRITTEN",
})
END = "END"


class LiveDumpUnavailable(Exception):
    """No dump could be read. **rc 2 -- a NON-ANSWER, never a zero.**

    Raised for every cause that means "the question was not answered": the profile
    is unresolved, the file is missing, the file holds no saved data at all (the
    running-game stub), or the variable is simply not there.
    """


class LiveDumpFatal(Exception):
    """The probe RAN and died, and said why.

    Distinct from LiveDumpCorrupt on purpose. `emit()` writes a single
    `HDR<TAB>schema=N<TAB>FATAL<TAB><message>` row when `build()` raises -- it goes out
    of its way to preserve the error. Without this class that frame has no END row, so
    it tripped the truncation clause and the reader was told "the dump is TRUNCATED and
    the true length is unknown": a diagnosis pointing at the transport, while the real
    cause sat unread in the payload.
    """


class LiveDumpCorrupt(Exception):
    """A dump was found but does not self-check. **rc 3 -- degraded.**

    Distinct from `LiveDumpUnavailable` on purpose: "there is nothing to read" and
    "what I read cannot be trusted" are different states, and collapsing them would
    reintroduce the very ambiguity this module exists to remove.
    """


# --------------------------------------------------------------------- location

def uidata_path() -> Path | None:
    """`{profile}/uidata.xml`, or None when the profile is unresolved."""
    p = _paths.profile()
    return None if p is None else p / "uidata.xml"


def game_is_running() -> bool | None:
    """True / False / **None when it could not be determined** -- never a bare bool.

    Only ever used to make a message more specific. The stub is detected from the
    file's CONTENT, so this never decides an outcome; if it did, a machine where the
    process query fails would silently change which answer the tool gives.
    """
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq X4.exe"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        # silent-ok: the THIRD state is the channel. This never decides an outcome --
        # the stub is detected from file content -- so a failed process query returns
        # None ("could not determine") and only makes the message less specific.
        return None
    if out.returncode != 0:
        return None
    return "X4.exe" in out.stdout


# --------------------------------------------------------------------- decoding

def extract_raw(text: str, var: str = DEFAULT_VAR) -> str:
    """The still-escaped payload assigned to *var*, as it sits in the file.

    The closing delimiter is the first `&quot;` NOT preceded by an odd number of
    backslashes -- an escaped quote inside the payload is not the end of it.
    """
    m = re.search(rf"(?m)^{re.escape(var)}\s*=\s*&quot;", text)
    if not m:
        raise LiveDumpUnavailable(
            f"the variable {var!r} is not assigned in this uidata.xml - the probe "
            f"did not run, or its ui.xml does not declare the savedvariable")
    start = pos = m.end()
    while True:
        end = text.find("&quot;", pos)
        if end == -1:
            raise LiveDumpCorrupt(
                f"{var} has no closing delimiter - the payload is TRUNCATED")
        run = len(text[:end]) - len(text[:end].rstrip("\\"))
        if run % 2 == 0:
            return text[start:end]
        pos = end + len("&quot;")


def xml_unescape(s: str) -> str:
    """Layer 1. `&amp;` is decoded LAST, or `&amp;quot;` would double-decode."""
    for ent, ch in (("&quot;", '"'), ("&lt;", "<"), ("&gt;", ">"),
                    ("&apos;", "'"), ("&amp;", "&")):
        s = s.replace(ent, ch)
    return s


def lua_unescape(s: str) -> str:
    r"""Layer 2. Lua string escapes as the engine's serialiser writes them.

    The decimal form takes UP TO THREE digits (`\9`, `\09`, `\009`). Reading only one
    is the specific bug this docstring exists to prevent: the engine emits `\009`
    whenever the next character is itself a digit, so a one-digit reader turns a tab
    into chr(0) followed by the literal text "09" and every field on that row shifts
    by one.
    """
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= n:                      # trailing lone backslash: keep it verbatim
            out.append("\\")
            break
        d = s[i]
        if d == "\n":                   # backslash-newline continuation = a newline
            out.append("\n")
            i += 1
        elif d.isdigit():
            j = i
            while j < n and j - i < 3 and s[j].isdigit():
                j += 1
            out.append(chr(int(s[i:j])))
            i = j
        elif d in "\\\"'":
            out.append(d)
            i += 1
        else:
            out.append({"n": "\n", "t": "\t", "r": "\r", "a": "\a",
                        "b": "\b", "f": "\f", "v": "\v"}.get(d, d))
            i += 1
    return "".join(out)


def unesc_field(v: str) -> str:
    """Layer 3. Undo the probe's own per-field escaping of tab/newline/backslash."""
    out: list[str] = []
    i, n = 0, len(v)
    while i < n:
        if v[i] == "\\" and i + 1 < n:
            out.append({"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}
                       .get(v[i + 1], v[i + 1]))
            i += 2
        else:
            out.append(v[i])
            i += 1
    return "".join(out)


# ------------------------------------------------------------------- the record

@dataclass
class Dump:
    """A parsed, self-checked probe dump."""

    rows: list[list[str]] = field(default_factory=list)
    header: dict[str, str] = field(default_factory=dict)

    @property
    def kinds(self) -> Counter:
        return Counter(r[0] for r in self.rows)

    def of(self, kind: str) -> list[list[str]]:
        return [r for r in self.rows if r[0] == kind]

    def one(self, kind: str) -> list[str] | None:
        got = self.of(kind)
        return got[0] if got else None

    def extensions(self) -> list[dict[str, str]]:
        """`EXT` rows as dicts, keyed by the field names the probe declared.

        Returns [] when the probe emitted no `EXT_FIELDS` header -- the field
        vocabulary comes from the engine at runtime and is not hard-coded here, so
        without it the columns have no names, and inventing some would be worse than
        returning nothing.
        """
        hdr = self.one("EXT_FIELDS")
        if not hdr or len(hdr) < 2:
            return []
        names = [f for f in hdr[1].split(",") if f]
        return [dict(zip(names, r[1:])) for r in self.of("EXT")]

    def library_entries(self) -> dict[tuple[str, str], dict[str, str]]:
        """`LIB_ENTRY_VAL` rows collated to {(librarytype, id): {field: value}}."""
        out: dict[tuple[str, str], dict[str, str]] = {}
        for r in self.of("LIB_ENTRY_VAL"):
            if len(r) >= 4:
                out.setdefault((r[1], r[2]), {})[r[3]] = r[4] if len(r) > 4 else ""
        return out

    def unknown_kinds(self) -> Counter:
        """Rows whose KIND is not in KNOWN_KINDS, counted per kind.

        Named, never merely counted: a kind nobody recognises is a lead about a probe
        this toolkit no longer models, and the whole point is that it cannot be
        absorbed into a total.
        """
        return Counter({k: n for k, n in self.kinds.items() if k not in KNOWN_KINDS})

    def accounts_for_every_row(self) -> bool:
        """Is every row a kind we know about? No unexplained remainder (#23).

        This used to be `sum(self.kinds.values()) == len(self.rows)` -- and `kinds` is
        a Counter built from `rows`, so it was TRUE BY CONSTRUCTION. MEASURED over
        20,000 randomised dumps: never False, never raised. Three tests used it as a
        control that "must PASS", and _livecli's whole error branch (including its
        `return 3`) was unreachable.

        The row-COUNT question it looked like it was asking is already answered, and
        answered independently, by parse(): the END row carries the game's own count
        and is compared against the rows actually parsed. Duplicating that here bought
        nothing; asking about KINDS is the question nothing else asks.
        """
        return not self.unknown_kinds()


# ---------------------------------------------------------------------- parsing

def parse(text: str, var: str = DEFAULT_VAR) -> Dump:
    """Decode and SELF-CHECK a dump out of `uidata.xml` text.

    Raises `LiveDumpUnavailable` when there is nothing to read, and
    `LiveDumpCorrupt` when what is there does not check out.
    """
    if "<uidata" not in text:
        # Not a uidata.xml at all. Worth its own message: the stub explanation below
        # is a claim about how X4 saves, and asserting it about an arbitrary file
        # would be a confident wrong reason attached to a correct exit code.
        raise LiveDumpUnavailable(
            f"this is not a uidata.xml - no <uidata> element in {len(text)} bytes")

    if "<data" not in text:
        # The stub. It is valid XML and would parse to zero of everything.
        running = game_is_running()
        if running is True:
            why = ("X4 is running right now - it truncates uidata.xml at startup and "
                   "writes it back on exit")
        elif running is False:
            why = "no X4 process is running, so nothing has ever been saved to it"
        else:
            why = ("either X4 is running (it truncates this file at startup and writes "
                   "it back on exit), or nothing has ever been saved to it")
        raise LiveDumpUnavailable(
            f"uidata.xml holds no saved data at all ({len(text)} bytes): {why}. "
            f"Quit the game and read it again - this is NOT 'the probe found nothing'.")

    rows = [[unesc_field(f) for f in line.split("\t")]
            for line in lua_unescape(xml_unescape(extract_raw(text, var))).split("\n")
            if line]

    # Three INDEPENDENT clauses. Each is tested by its own fixture, because a guard
    # that fires first hides the ones behind it (CLAUDE.md #26).
    if not rows or rows[0][0] != HDR:
        raise LiveDumpCorrupt(
            f"no {HDR} row - the payload is truncated at the FRONT, or is not a dump")
    # BEFORE the END check. A FATAL frame is a single HDR row by construction, so the
    # truncation clause below would otherwise claim it, and the probe's own account of
    # what went wrong would be discarded in favour of a guess about the transport.
    if "FATAL" in rows[0]:
        i = rows[0].index("FATAL")
        why = rows[0][i + 1] if i + 1 < len(rows[0]) else "no reason recorded"
        raise LiveDumpFatal(
            f"the probe ran and FAILED while building its dump: {why}. The dump is not "
            f"truncated - there is nothing more to read.")
    if rows[-1][0] != END:
        raise LiveDumpCorrupt(
            f"last row is {rows[-1][0]!r}, not {END} - the dump is TRUNCATED. "
            f"{len(rows)} rows were read, and the true length is unknown.")
    try:
        claimed = int(rows[-1][1])
    except (IndexError, ValueError):
        raise LiveDumpCorrupt(f"the {END} row carries no readable row count") from None
    if claimed != len(rows):
        raise LiveDumpCorrupt(
            f"the game wrote {claimed} rows; {len(rows)} parsed. The payload was "
            f"truncated or mis-decoded - reporting it would be a confident wrong answer.")

    header = {}
    for f in rows[0][1:]:
        k, _, v = f.partition("=")
        header[k] = v
    return Dump(rows=rows, header=header)


def var_name() -> str:
    """The savedvariable to read, honouring `X4_LIVE_VAR`.

    A probe is a PERSONAL mod and picks its own global's name, so the package must
    not bake one in. Resolved through `_paths.value()` -- not `os.environ` -- because
    the config file is a layer too, and two earlier consumers read the environment
    directly and so could not see a value users had been told to put in
    `.claude/x4-paths.env`.
    """
    return _paths.value("X4_LIVE_VAR") or DEFAULT_VAR


def load(path: Path | None = None, var: str | None = None) -> Dump:
    """Read, decode and self-check the dump in `uidata.xml`."""
    var = var or var_name()
    p = path or uidata_path()
    if p is None:
        raise LiveDumpUnavailable(
            "the X4 profile is not configured - set $X4_PROFILE (see --paths)")
    if not p.exists():
        raise LiveDumpUnavailable(f"{p} does not exist")
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise LiveDumpUnavailable(f"{p} could not be read: {exc}") from exc
    return parse(text, var)

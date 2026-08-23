r"""Parse X4's `debug.txt` engine log into structured errors, for correlation.

x4validate's static checks (XSD, exprlint heuristic) are *necessary but not
sufficient* — the authoritative verdict on what actually breaks at load/runtime is
the game engine's own `[=ERROR=]` output. This module parses that log so
`_check.check_debug_correlation` can fold the engine's errors for *this* mod into
the same report and GATE on them (a real engine error = exit 1).

Seven real shapes occur (all verified against a live 9.0 log):
  A. load parse error   `[=ERROR=] <t> extensions\<folder>\<rel>(<line>): <msg>`
  B. load lookup error  `... Originated from: extensions\<folder>\<rel>.(xml|xml.gz)`  (no line)
  C. runtime MD cue     `[=ERROR=] <t> Error in MD cue md.<Script>.<Cue><inst:..>: <msg>`
                        followed by  `* Action: <tag>, line <N>`
  D. runtime AI script  `[=ERROR=] <t> Error in AI script <name> on entity <id>: <msg>`
                        followed by  `* Action: <tag>, line <N>`
  E. diff op, 0 matches `<t> No matching node for path '<sel>' in patch file '<f>'. Skipping node.`
  F. diff op, >1 match  `<t> Multiple matching nodes for path '<sel>' in patch file '<f>'. ...`
  G. index lookup miss  `<t> Cannot find XML file component macro '<name>' in index '<index>'`
A/B/E/F identify a FILE (path); C/D identify a SCRIPT by NAME (resolved to a file by
the caller, via each mdscript/aiscript's `name=` attribute). The `'null' is not a
list` runtime error is shape C — hence why the file-path-only parse would miss it.

G identifies NEITHER — the engine names the macro and the index, never the mod that
referenced it or the mod whose index entry is broken. That is the whole reason it is
worth parsing: it is the only ground truth we have for the INDEX layer (does a macro
name resolve to a loadable file?), which is a different question from E/F's diff-op
layer and had never been measured before 2026-07-28. Attribution back to a mod is the
consumer's job, and is inherently a search, not a lookup.

E/F are the **diff-op cardinality failures** — the exact class x4validate exists to
catch (RFC 5261: a `sel` must match exactly one node; the engine skips the op and
continues, so the patch SILENTLY does nothing). They were unparsed until 2026-07-26,
which made `--debug` blind to 453 of 2463 error lines in a real log. Three quirks,
each measured over that log — get any of them wrong and the shape silently drops:
  1. The engine prints the patch file **without its extension** (441 of 453):
     `'extensions\stars\libraries\material_library'`, not `...material_library.xml`.
     Use `xml_candidates()` to resolve against a real VFS.
  2. The `<sel>` itself contains single quotes (`@id='ore'`) in 413 of 453 lines, so
     the sel group MUST be greedy `.*` anchored on the literal `' in patch file '`.
     A `[^']*` group truncates 91% of real selectors.
  3. Unlike A–D these carry a `sel` and a cardinality, not just a location — which is
     what lets us compare the engine's verdict to ours op-for-op rather than by file.

Shapes A–G identify a MOD (or resolve to one). The engine also emits a large class
of SUBSYSTEM errors that identify a game ENTITY instead — a job that could not spawn,
a station group with no macros, a ware with a broken licence. Until 2026-08-13 those
were not parsed at all, and worse, not *counted*: `parse_debug` walked every line,
matched six regexes and `continue`d past everything else in silence. MEASURED over
the 2026-08-13 log: **1,067 of 2,430 lines (43.9%) were dropped without a word**,
while `check_debug_correlation` printed "(of 1363 total in the log)" — a denominator
it had never measured. Sixth occurrence of the register's one recurring shape.

What sat in that missing 44% is the argument for the change. The most consequential
finding of that day — a mod adding 22 jobs whose `ship.select.tags` no ship in the
effective tree carries, so they can never spawn — is a `[JobEngine]` line, and every
one of them was invisible.

So `parse_log` accounts for **every** `[=ERROR=]` line: classified into a shape, or
labelled `unclassified` and counted. An unclassified line is an honest account; a
dropped one is not. `parse_debug` keeps returning only A–G, byte-for-byte as before,
because two corpus-wide gates and one GATING check consume it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_RE_PARSE = re.compile(r"extensions[\\/](?P<path>[^()\r\n]+?)\((?P<line>\d+)\):\s*(?P<msg>.*)")
_RE_ORIG = re.compile(r"(?P<msg>.*?)\s*Originated from:\s*extensions[\\/](?P<path>[^\r\n]+?)\.\(xml")
_RE_MDCUE = re.compile(r"Error in MD cue\s+md\.(?P<script>[^.]+)\.(?P<cue>[^<:]+?)(?:<[^>]*>)?:\s*(?P<msg>.*)")
_RE_AISCR = re.compile(r"Error in AI script\s+(?P<script>\S+)\s+on entity\s+[^:]+:\s*(?P<msg>.*)")
_RE_ACTION_LINE = re.compile(r"\bline\s+(?P<line>\d+)")
# E/F. `sel` is greedy by necessity — see quirk 2 in the module docstring.
# The `extensions[\\/]` prefix is consumed here so `path` is <folder>\<rel>, matching
# what _RE_PARSE/_RE_ORIG hand to _split_path. (Forgetting it yields folder="extensions".)
_RE_DIFFOP = re.compile(
    r"(?P<kind>No matching node|Multiple matching nodes) for path "
    r"'(?P<sel>.*)' in patch file '(?:\.[\\/])?extensions[\\/](?P<path>[^']*)'")
# G. Neither name nor index can contain a quote (they are XML ids / index paths), so
# `[^']*` is correct here — unlike quirk 2's selectors, which routinely do.
_RE_INDEXMISS = re.compile(
    r"Cannot find XML file (?P<kind>[a-z ]+?) '(?P<name>[^']*)' in index '(?P<index>[^']*)'")


@dataclass
class DebugError:
    ident_kind: str   # "path" (A/B/E/F) | "script" (C/D)
    folder: str       # A/B/E/F: the extensions\<folder> token; else ""
    vpath: str        # A/B/E/F: mod-relative posix path; else ""
    script_name: str  # C/D: the mdscript/aiscript name; else ""
    line: int         # 0 if unknown
    message: str
    severity: str     # "error" | "warn"
    # E/F only — the engine's own per-op verdict, for op-for-op comparison.
    sel: str = ""            # the XPath the op used
    cardinality: str = ""    # "" (not a diff op) | "none" (0 matches) | "multiple" (>1)
    # G only — the index-layer lookup the engine could not satisfy.
    lookup: str = ""         # the name it looked for, e.g. `ishield_xen_s_scout_01_a_macro`
    lookup_kind: str = ""    # "" (not shape G) | what it was looking for, e.g. "component macro"
    lookup_index: str = ""   # the index it searched, e.g. `index\macros`
    # SUBSYSTEM shapes only — the engine names a game ENTITY, never a mod. Attribution
    # back to a mod is therefore a SEARCH against the effective store, not a lookup,
    # and is the consumer's job (see `x4debug triage`).
    subsystem: str = ""      # "" (not a subsystem shape) | "jobengine", "waredb", ...
    entity: str = ""         # the id the engine named, e.g. `dockarea_ter_hightech`
    entity_kind: str = ""    # what that id IS: "job", "stationgroup", "ware", "tags", ...


def xml_candidates(vpath: str) -> tuple[str, ...]:
    """Resolve shape E/F's extension-less patch path against a real file list.

    The engine drops the extension for these lines (quirk 1), so `libraries/factions`
    must be matched against `libraries/factions.xml`. Returns the forms to try, most
    literal first — the caller picks whichever exists in the mod's VFS.
    """
    if not vpath:
        return ()
    tail = vpath.rsplit("/", 1)[-1]
    if "." in tail:  # already carries an extension (12 of 453 in the reference log)
        return (vpath,)
    return (vpath, vpath + ".xml")


def _sev(msg: str) -> str:
    low = msg.lower()
    if "warning" in low or "not recommended" in low or "inefficient" in low:
        return "warn"
    return "error"


def _split_path(p: str) -> tuple[str, str]:
    parts = [x for x in re.split(r"[\\/]", p.strip()) if x]
    if not parts:
        return "", ""
    return parts[0], "/".join(parts[1:])


def _lookahead_line(lines: list[str], i: int) -> int:
    """Runtime errors put their source line on a `* Action: ..., line N`
    continuation line following the `[=ERROR=]` header. Scan the `*`-prefixed
    continuation block for it."""
    for j in range(i + 1, min(i + 8, len(lines))):
        s = lines[j].strip()
        if not s.startswith("*"):
            break
        m = _RE_ACTION_LINE.search(s)
        if m:
            return int(m.group("line"))
    return 0


# --- SUBSYSTEM shapes --------------------------------------------------------
#
# Data, not code branches, so this table and the KB's triage catalogue can be read
# against each other. Each row is (subsystem, entity_kind, compiled regex) and the
# regex MUST expose a group named `entity` (the id the engine named). Rows are tried
# in order, AFTER shapes A-G, so `parse_debug`'s output is unchanged byte-for-byte.
#
# Counts are from the 2026-08-13 log (2,430 errors) and are the denominator for
# "how much of the unclassified 1,067 does this table actually cover?".
_SUBSYSTEM_SHAPES = (
    # 67 — the shape that carried the SVE finding. The job exists and is valid XML;
    # nothing in the effective tree satisfies its ship selector.
    ("jobengine", "job",
     re.compile(r"\[JobEngine\][^']*JobID:\s*'(?P<entity>[^']*)'")),
    ("jobdb", "job",
     re.compile(r"\[JobDB\][^']*JobID:\s*'(?P<entity>[^']*)'")),
    # 43 + 16 — no id exists in this shape, so the TAGS are the identity. Keeping them
    # is what turns "nothing carries tag.heavyfrigate" into a measurable claim.
    ("shipgenerator", "tags",
     re.compile(r"No suitable ShipGenerator found with tags=\[(?P<entity>[^\]]*)\]")),
    # 43 — a STATION group. Deliberately distinct from the ship-group row below:
    # collapsing them makes "who emptied dockarea_ter_hightech" unanswerable.
    ("factorygenerator", "stationgroup",
     re.compile(r"FactoryGenerator::\w+\(\):\s*Station group reference '(?P<entity>[^']*)'")),
    ("shipgenerator", "shipgroup",
     re.compile(r"ShipGenerator::\w+\(\):\s*Ship group reference '(?P<entity>[^']*)'")),
    ("shipgenerator", "basket",
     re.compile(r"ShipGenerator:\s*default basket '(?P<entity>[^']*)'")),
    # 44 — the engine names an index entry, a file AND a component template. The
    # actionable one is the template that owns the broken connection, so anchor there.
    ("parttemplate", "component",
     # NB `.*?` not `[^']*`: the intervening text quotes BOTH the index entry and the
     # file (`from index 'x' in file 'y', referenced from ...`), so a no-quote class
     # can never reach the component template. Same trap as quirk 2 above.
     re.compile(r"Cannot find referenced part template.*?"
                r"referenced from component template '(?P<entity>[^']*)'")),
    # 310 — benign at game start (anarchy/chaos tags are acquired at runtime), but it
    # is counted, not filtered: a benign-bucket decision is the KB's to make, not the
    # parser's, and a suppression baked into code outlives the reason for it.
    ("godengine", "godentry",
     re.compile(r"\[God Engine\][^']*God Entry ID:\s*'(?P<entity>[^']*)'")),
    ("godentry", "godentry",
     re.compile(r"\[God(?:Production|Station)Entry\][^']*GodEntryID:\s*'(?P<entity>[^']*)'")),
    # 106 — several message bodies, one subsystem; anchor on the first quoted id.
    ("waredb", "ware",
     re.compile(r"WareDB::\w+\(\):[^']*'(?P<entity>[^']*)'")),
    ("waredb", "ware",
     re.compile(r"Crafting ware '(?P<entity>[^']*)'")),
    ("effectlibrary", "effect",
     re.compile(r"EffectLibrary::\w+\(\)\s*Effect '(?P<entity>[^']*)' not found")),
    ("iconlibrary", "icon",
     re.compile(r"IconLibrary::\w+\(\):[^']*'(?P<entity>[^']*)'")),
    # Quoted with DOUBLE quotes in this shape, unlike every other row.
    ("soundlibrary", "macro",
     re.compile(r'Invalid SoundID[^"]*"[^"]*"\s*on macro:\s*"(?P<entity>[^"]*)"')),
    ("macrolibrary", "macro",
     re.compile(r"Duplicate macro ID '(?P<entity>[^']*)'")),
    ("textpage", "macro",
     re.compile(r"GetTextPage\(\)[^:]*Source:\s*(?P<entity>\S+)")),
    # No entity at all — matched last, so a row above always wins if it applies.
    ("aicontext", "",
     re.compile(r"^aicontext<(?P<entity>[^>]*)>")),
)


@dataclass
class ParsedLog:
    """Every `[=ERROR=]` line, accounted for.

    `total` is the number of lines READ, not the number successfully classified.
    That distinction is the whole point: the previous code reported the latter as
    the former, which is a false denominator in user-facing output.
    """

    total: int
    entries: list["DebugError"]          # classified + unclassified, in log order
    unclassified: list["DebugError"]     # subset of `entries`, for the residue count

    @property
    def classified(self) -> list["DebugError"]:
        return [e for e in self.entries if e.ident_kind != "unclassified"]

    def coverage_note(self) -> str:
        """The line every consumer prints. Names the residue rather than hiding it."""
        n = len(self.unclassified)
        if not self.total:
            return "debug: no [=ERROR=] lines in the log"
        pct = 100.0 * (self.total - n) / self.total
        note = (f"debug: {self.total} [=ERROR=] line(s) read, "
                f"{self.total - n} classified ({pct:.1f}%)")
        if n:
            note += (f", {n} UNCLASSIFIED — a shape this parser does not know, "
                     "so treat any count derived from it as a floor, not a total")
        return note


def _classify(content: str, lines: list[str], i: int) -> "DebugError | None":
    """Shapes A-G — the mod-identifying ones. Order is load-bearing and unchanged."""
    m = _RE_DIFFOP.search(content)  # E/F — checked first: they carry the richest data
    if m:
        folder, vpath = _split_path(m.group("path"))
        return DebugError("path", folder, vpath, "", 0, content, "error",
                          sel=m.group("sel"),
                          cardinality=("none" if m.group("kind").startswith("No")
                                       else "multiple"))
    m = _RE_INDEXMISS.search(content)  # G — before A, whose `(<line>):` shape it lacks
    if m:
        return DebugError("lookup", "", "", "", 0, content, "error",
                          lookup=m.group("name"),
                          lookup_kind=m.group("kind").strip(),
                          lookup_index=m.group("index"))
    m = _RE_PARSE.search(content)  # A
    if m:
        folder, vpath = _split_path(m.group("path"))
        return DebugError("path", folder, vpath, "", int(m.group("line")),
                          m.group("msg").strip(), _sev(m.group("msg")))
    m = _RE_ORIG.search(content)  # B
    if m:
        folder, vpath = _split_path(m.group("path"))
        return DebugError("path", folder, vpath, "", 0,
                          m.group("msg").strip(), _sev(m.group("msg")))
    m = _RE_MDCUE.search(content)  # C
    if m:
        return DebugError("script", "", "", m.group("script").strip(),
                          _lookahead_line(lines, i), m.group("msg").strip(),
                          _sev(m.group("msg")))
    m = _RE_AISCR.search(content)  # D
    if m:
        return DebugError("script", "", "", m.group("script").strip(),
                          _lookahead_line(lines, i), m.group("msg").strip(),
                          _sev(m.group("msg")))
    return None


def _classify_subsystem(content: str) -> "DebugError | None":
    """The engine-subsystem shapes, tried only after A-G have all missed."""
    for subsystem, entity_kind, rx in _SUBSYSTEM_SHAPES:
        m = rx.search(content)
        if m:
            return DebugError("subsystem", "", "", "", 0, content, _sev(content),
                              subsystem=subsystem, entity=m.group("entity").strip(),
                              entity_kind=entity_kind)
    return None


def parse_log_text(text: str) -> ParsedLog:
    """Parse log TEXT, accounting for every `[=ERROR=]` line.

    The invariant, which `tests/test_debuglog_residue.py` pins: `total` equals
    `len(entries)`. Nothing is ever dropped — a line this parser cannot classify
    becomes an `unclassified` entry carrying its verbatim message, so a shape we
    have never seen survives as evidence instead of vanishing.
    """
    lines = text.splitlines()
    entries: list[DebugError] = []
    unclassified: list[DebugError] = []
    total = 0
    for i, raw in enumerate(lines):
        if "[=ERROR=]" not in raw:
            continue
        total += 1
        content = raw.split("[=ERROR=]", 1)[1]
        content = re.sub(r"^\s*[\d.]+\s+", "", content).strip()  # drop game-time stamp

        entry = _classify(content, lines, i) or _classify_subsystem(content)
        if entry is None:
            entry = DebugError("unclassified", "", "", "", 0, content, _sev(content))
            unclassified.append(entry)
        entries.append(entry)
    return ParsedLog(total=total, entries=entries, unclassified=unclassified)


def parse_log(path: str | Path) -> ParsedLog:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        # An unreadable log is a NON-ANSWER, not an empty one. total=0 with no
        # entries is the honest rendering; the caller's coverage_note() says so.
        return ParsedLog(total=0, entries=[], unclassified=[])
    return parse_log_text(text)


def parse_debug_text(text: str) -> list[DebugError]:
    """Shapes A-G only — the mod-identifying subset, unchanged.

    Two corpus-wide gates (`gates/oracle.py`, `gates/oracle_index.py`) and the
    GATING `check_debug_correlation` consume this. Widening it would silently
    change what those gates measure, so the subsystem shapes stay behind
    `parse_log` until they are promoted deliberately.
    """
    return [e for e in parse_log_text(text).entries
            if e.ident_kind in ("path", "script", "lookup")]


def parse_debug(path: str | Path) -> list[DebugError]:
    return parse_debug_text(Path(path).read_text(encoding="utf-8", errors="replace")
                            if Path(path).is_file() else "")

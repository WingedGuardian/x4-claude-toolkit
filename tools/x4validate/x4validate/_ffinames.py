r"""Which C functions vanilla's ui lua DECLARES in `ffi.cdef` -- the source side of the FFI census.

WHY THIS EXISTS. `x4live query globals` walks `_G`, and its answers were quoted as "the engine
surface". MEASURED 2026-09-07: vanilla's ui lua declares 2,066 C functions in `ffi.cdef` blocks,
2,046 of them invisible to `_G` -- so every negative drawn from `globals` covered ~30% of its
subject. The census verb (`x4live ffi-census`) asks the RUNNING game about each name; this module
decides which names, and says what it could not read.

WHAT A NAME HERE MEANS, AND DOES NOT. A name is DECLARED by some vanilla file. Whether the engine
EXPORTS it, and whether that file's block ever ran in this session, are questions only the game can
answer -- which is why the census verb exists. A commented-out block is still parsed (lua comments
are not stripped), so its names surface in game as `undeclared`, with this module's provenance.

RULES, each a shape vanilla uses (tests/test_ffinames.py pins a twin for every one):
  * blocks are string LITERALS: `ffi.cdef[[...]]`, `ffi.cdef([[...]])`, `[=[ ... ]=]` levels.
    Any other `ffi.cdef` call (a variable, a concatenation) is COUNTED in `unparsed`, never dropped;
  * C comments are removed, then brace bodies (struct/union/enum), innermost first -- a
    function-pointer MEMBER is not a function;
  * a declaration is a function when it has a parameter list, is not a `typedef`, and its name is
    not itself parenthesised (`int (*fp)(void)` is a pointer variable).

KNOWN MISSES, each MEASURED on synthetic input by review 2026-09-14 and each at ZERO cost on
vanilla today (reference/ uses only `ffi.cdef[[` blocks): `__attribute__((x)) int F(void);`
yields the name `__attribute__`; `void (*GetHandler(int))(int);` (a function returning a
function pointer) is dropped; `int A(void), B(void);` loses `B`. These are declarator shapes
inside a block the parser DID read, so they are not counted in `unparsed` -- which is why they
are written down here instead.

SOURCE SET. Loose files come from `_effective.base_vpaths(config, "*.lua")`, the one sanctioned
enumeration. Its PACKED pass lists XML only, so `.lua` inside a packed-only DLC catalog is read here
directly from the catalog index instead. MEASURED 2026-09-14 on build 23660954: the eight DLC
catalogs hold ONE lua file between them (ventures, also unpacked), so that pass currently adds nothing
-- and is here so that stays a measurement rather than an assumption.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_OPEN = re.compile(r"ffi\.cdef\s*(\()?\s*\[(=*)\[")
#: Every mention of `ffi.cdef`. Each one that is not the start of a literal block counts as
#: unparsed -- `ffi.cdef(src)`, an alias `local c = ffi.cdef`, and `ffi.cdef"int A(void);"`
#: (lua allows a string argument without parentheses) -- EXCEPT a mention quoted on BOTH
#: sides, which is data: MEASURED 2026-09-14, the one vanilla instance is LuaJIT's own name
#: table (`ui/core/lua/jit/vmdef.lua:352`, `"ffi.cdef",`). An exemption checking EITHER side
#: swallowed the quote-call form (review 2026-09-14).
_FFI_CDEF = re.compile(r"\bffi\.cdef\b")
#: A `.cdef` CALL through any receiver other than the bare name `ffi` --
#: `require("ffi").cdef[[...]]`, `mylib.cdef(...)`. It declares just the same, and a parser
#: keyed on `ffi.cdef` cannot read it, so it is counted rather than invisible.
_OTHER_CDEF = re.compile(r"([\w)\]]+)\s*\.\s*cdef\s*[\[(\"']")
_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_BRACES = re.compile(r"\{[^{}]*\}")
_TYPEDEF = re.compile(r"typedef\b")
_NAME = re.compile(r"([A-Za-z_]\w*)\s*$")


def cdef_blocks(text: str) -> tuple[list[str], int]:
    """(bodies of every literal `ffi.cdef` block, count of `ffi.cdef` calls that were NOT one)."""
    blocks: list[str] = []
    literal_at: set[int] = set()
    for m in _OPEN.finditer(text):
        close = "]" + m.group(2) + "]"
        end = text.find(close, m.end())
        if end < 0:
            continue                        # unterminated: falls into `unparsed` below
        blocks.append(text[m.end():end])
        literal_at.add(m.start())
    unparsed = 0
    for m in _FFI_CDEF.finditer(text):
        if m.start() in literal_at:
            continue
        before = text[m.start() - 1] if m.start() > 0 else ""
        after = text[m.end()] if m.end() < len(text) else ""
        if before and before in "\"'" and after and after in "\"'":
            continue                        # "ffi.cdef" -- quoted on both sides: data
        unparsed += 1
    unparsed += sum(1 for m in _OTHER_CDEF.finditer(text) if m.group(1) != "ffi")
    return blocks, unparsed


def functions_in_cdef(body: str) -> set[str]:
    """Names of the FUNCTIONS a cdef body declares (see the module rules)."""
    body = _COMMENT.sub(" ", body)
    prev = None
    while prev != body:
        prev, body = body, _BRACES.sub(" ", body)
    out: set[str] = set()
    for decl in body.split(";"):
        d = " ".join(decl.split())
        if not d or "(" not in d or _TYPEDEF.match(d):
            continue
        head, rest = d.split("(", 1)
        if rest.lstrip().startswith("*"):   # `int (*fp)(void)`: a pointer variable
            continue
        m = _NAME.search(head)
        if m:
            out.add(m.group(1))
    return out


@dataclass
class Census:
    #: name -> the vpaths declaring it, sorted. Provenance travels with every name.
    names: dict[str, list[str]]
    files_scanned: int
    files_with_names: int
    blocks: int
    #: (vpath, count) of `ffi.cdef` calls whose declarations this parser cannot see.
    unparsed: list[tuple[str, int]]
    #: vpaths enumerated but not readable -- never silently absent.
    unreadable: list[str] = field(default_factory=list)


def census_from_texts(files: dict[str, str]) -> Census:
    names: dict[str, set[str]] = {}
    blocks_total, with_names, unparsed = 0, 0, []
    for vpath in sorted(files):
        blocks, bad = cdef_blocks(files[vpath])
        blocks_total += len(blocks)
        if bad:
            unparsed.append((vpath, bad))
        found: set[str] = set()
        for b in blocks:
            found |= functions_in_cdef(b)
        if found:
            with_names += 1
        for n in found:
            names.setdefault(n, set()).add(vpath)
    return Census(names={n: sorted(v) for n, v in sorted(names.items())},
                  files_scanned=len(files), files_with_names=with_names,
                  blocks=blocks_total, unparsed=unparsed)


def census(config) -> Census:
    """The census over this installation's base game and DLC ui lua."""
    from . import _cat, _effective

    texts: dict[str, str] = {}
    unreadable: list[str] = []
    for low, vpath in sorted(_effective.base_vpaths(config, "*.lua").items()):
        try:
            texts[vpath] = (config.reference / vpath).read_text(encoding="utf-8",
                                                                errors="replace")
        except OSError:
            unreadable.append(vpath)
    packed = {n.lower() for n in config.packed_dlc_names()}
    seen = {v.lower() for v in texts} | {v.lower() for v in unreadable}
    for d in config.dlc_dirs():
        if d.name.lower() not in packed:
            continue
        for rel, member in _cat.build_mod_vfs(d, xml_only=False).items():
            vpath = f"extensions/{d.name}/{rel.replace(chr(92), '/')}"
            if not rel.lower().endswith(".lua") or vpath.lower() in seen:
                continue
            try:
                texts[vpath] = _cat.read_member(member).decode("utf-8", errors="replace")
            except Exception:                   # noqa: BLE001 - recorded, not hidden
                unreadable.append(vpath)
    c = census_from_texts(texts)
    c.unreadable = sorted(unreadable)
    return c

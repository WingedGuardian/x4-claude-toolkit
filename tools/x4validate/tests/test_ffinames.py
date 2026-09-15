"""The FFI census's SOURCE side: which C functions vanilla's ui lua declares in `ffi.cdef`.

WHY. `x4live query globals` walks `_G` and was, for a while, quoted as "the engine
surface". MEASURED 2026-09-07: vanilla declares 2,066 C functions in `ffi.cdef` blocks
across its ui lua, 2,046 of which are invisible to `globals` -- so a negative from
`globals` was scoped to 30% of its subject. The census verb asks the running game about
each of these names; this module decides WHICH names, and must say what it could not read.

Every rule below is a C-declaration shape vanilla actually uses, and each has a twin
that looks similar and is NOT a function.
"""
from __future__ import annotations

import pytest

from x4validate import _ffinames as F


def names(src: str) -> set[str]:
    blocks, unparsed = F.cdef_blocks(src)
    assert unparsed == 0, unparsed
    out: set[str] = set()
    for b in blocks:
        out |= F.functions_in_cdef(b)
    return out


def test_a_plain_block_yields_its_prototypes():
    src = 'local ffi = require("ffi")\nffi.cdef[[\n  uint32_t GetNumFoo(void);\n  const char* GetName(UniverseID id);\n]]\n'
    assert names(src) == {"GetNumFoo", "GetName"}


def test_the_PARENTHESISED_call_form_is_read():
    assert names("ffi.cdef([[ bool IsGamePaused(void); ]])") == {"IsGamePaused"}


def test_a_LEVELLED_long_bracket_is_read_to_its_OWN_close():
    """`[=[ ... ]=]` may legally contain `]]`; stopping at the first `]]` would cut it."""
    src = "ffi.cdef[=[ int A(int x[2]); /* ]] */ int B(void); ]=]"
    assert names(src) == {"A", "B"}


def test_C_comments_are_not_declarations():
    src = "ffi.cdef[[ /* int NotMe(void); */ // int NorMe(void);\n int Me(void); ]]"
    assert names(src) == {"Me"}


def test_a_struct_body_is_not_a_list_of_functions():
    """A function-pointer MEMBER has a name and a parameter list, and is not a function."""
    src = ("ffi.cdef[[ typedef struct { int id; void (*callback)(int); } Thing;\n"
           " Thing GetThing(int id); ]]")
    assert names(src) == {"GetThing"}
    # The twin the pointer rule cannot shadow: a parenthesised array size inside a body.
    # MEASURED: dropping the brace-strip survived the function-pointer member above.
    assert names("ffi.cdef[[ struct Holder { char tag[sizeof(int)]; }; int Real(void); ]]") == {"Real"}


def test_a_function_pointer_TYPEDEF_is_not_a_function():
    assert names("ffi.cdef[[ typedef void (*Handler)(int); int Real(void); ]]") == {"Real"}


def test_a_function_TYPE_typedef_is_not_a_function():
    """The twin the pointer rule cannot shadow: no `(*`, so only the typedef rule stops it.
    MEASURED: dropping the typedef rule survived the pointer-typedef test above."""
    assert names("ffi.cdef[[ typedef void Callback(int); int Real(void); ]]") == {"Real"}


def test_a_function_pointer_VARIABLE_is_not_a_function():
    assert names("ffi.cdef[[ int (*fp)(void); int Real(void); ]]") == {"Real"}


def test_a_MULTI_LINE_prototype_is_one_function():
    src = "ffi.cdef[[\n uint32_t GetAllFactions(\n   const char** result,\n   uint32_t n,\n   bool hidden);\n]]"
    assert names(src) == {"GetAllFactions"}


def test_an_enum_or_plain_struct_declares_nothing():
    src = "ffi.cdef[[ enum { A = (1 << 2), B }; struct Foo; typedef int32_t BuildTaskID; ]]"
    assert names(src) == set()


def test_a_cdef_whose_source_is_NOT_a_literal_is_COUNTED_not_dropped():
    """`ffi.cdef(src)` declares something this parser cannot see. Returning nothing for it
    would be a narrowing step that reports success."""
    blocks, unparsed = F.cdef_blocks("local src = build()\nffi.cdef(src)\nffi.cdef[[ int A(void); ]]")
    assert len(blocks) == 1
    assert unparsed == 1


def test_a_QUOTED_mention_is_data_not_a_call():
    """LuaJIT's own vmdef.lua lists `"ffi.cdef",` in a name table. Counting it as an
    unreadable declaration would put a false entry in the census's refusal list."""
    blocks, unparsed = F.cdef_blocks('local ffnames = {\n"ffi.cdef",\n\'ffi.new\',\n}')
    assert (blocks, unparsed) == ([], 0)


def test_an_ALIAS_is_still_counted_as_unparsed():
    """The twin: a declaration made through an alias is invisible to a literal parser, so
    the quote exemption must not reach it."""
    blocks, unparsed = F.cdef_blocks("local cdef = ffi.cdef\ncdef[[ int Hidden(void); ]]")
    assert blocks == []
    assert unparsed == 1


def test_a_QUOTE_CALL_with_no_space_is_counted_not_exempted():
    """`ffi.cdef"..."` is a real call (lua allows a string argument without parentheses).
    MEASURED by review: the quote exemption, which checked either side, swallowed it --
    0 blocks and 0 unparsed. Only a mention quoted on BOTH sides is data."""
    blocks, unparsed = F.cdef_blocks("ffi.cdef\"int A(void);\"\nffi.cdef'int B(void);'")
    assert blocks == []
    assert unparsed == 2


def test_a_cdef_through_ANOTHER_receiver_is_counted():
    """`require("ffi").cdef[[...]]` declares through a receiver that is not the name `ffi`;
    a literal parser keyed on `ffi.cdef` cannot read it, so it must at least be counted."""
    blocks, unparsed = F.cdef_blocks('require("ffi").cdef[[ int Hidden(void); ]]\n'
                                     "local x = mylib.cdef([[ int AlsoHidden(void); ]])")
    assert blocks == []
    assert unparsed == 2


def test_a_SPACED_ffi_receiver_is_counted():
    """Review round 2, MEASURED: `ffi .cdef[[...]]` gave 0 and 0 -- the other-receiver pass
    skipped receiver `ffi` assuming the ffi pass counted it, and that pass allowed no spaces."""
    blocks, unparsed = F.cdef_blocks("ffi .cdef[[ int A(void); ]]\nffi. cdef([[ int B(void); ]])")
    assert blocks == []
    assert unparsed == 2


def test_a_LONGER_receiver_ending_in_ffi_is_counted_ONCE_and_not_parsed():
    """`myffi.cdef[[...]]` was read as a block AND counted unparsed (review round 2)."""
    blocks, unparsed = F.cdef_blocks("myffi.cdef[[ int A(void); ]]")
    assert (blocks, unparsed) == ([], 1)


def test_two_blocks_in_one_file_are_both_read():
    assert names("ffi.cdef[[ int A(void); ]]\nx = 1\nffi.cdef[[ int B(void); ]]") == {"A", "B"}


def test_the_census_keeps_PROVENANCE_per_name(tmp_path):
    files = {
        "ui/a.lua": "ffi.cdef[[ int Shared(void); int OnlyA(void); ]]",
        "ui/b.lua": "ffi.cdef[[ int Shared(void); ]]\nffi.cdef(dynamic)",
        "ui/none.lua": "print('no ffi here')",
    }
    c = F.census_from_texts(files)
    assert c.names == {"Shared": ["ui/a.lua", "ui/b.lua"], "OnlyA": ["ui/a.lua"]}
    assert c.files_scanned == 3
    assert c.files_with_names == 2
    assert c.blocks == 2
    assert c.unparsed == [("ui/b.lua", 1)]


def test_the_REAL_corpus_reproduces_the_independent_strict_parse():
    """External oracle: SPEC_2026-09-07 counted 2,066 names over the 81 BASE-GAME ui lua
    files with a separate strict cdef-scoped parse. Only meaningful on that game build, so
    it is pinned to the build the reference tree records -- and skips, naming why, on
    any other."""
    from x4validate import _merge
    cfg = _merge.Config()
    marker = cfg.reference / ".unpacked-and-locked"
    if not cfg.reference.is_dir() or not marker.is_file():
        pytest.skip("no locked reference/ tree -- the corpus census is NOT checked here")
    if "23660954" not in marker.read_text(encoding="utf-8", errors="replace"):
        pytest.skip("reference/ is not build 23660954, where 2,066 was measured")
    c = F.census(cfg)
    base = {n for n, files in c.names.items()
            if any(not f.lower().startswith("extensions/") for f in files)}
    assert c.files_scanned >= 82
    assert len(base) == 2066, len(base)
    assert c.unparsed == [], c.unparsed

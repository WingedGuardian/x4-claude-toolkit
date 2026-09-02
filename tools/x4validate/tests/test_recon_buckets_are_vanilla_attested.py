"""Every recon bucket must match what VANILLA ACTUALLY PASSES -- mechanised.

F88 was one name in the wrong bucket: `GetMacroUnitStorageCapacity` sat in the
object-id list while vanilla passes it a macro, and the engine answered `OK number:0`
-- no error, a plausible value, and 0 is exactly what a ship with no unit storage
reports. It sat in a committed report for a day looking like data.

Fixing that one name established nothing about the other ninety. Re-deriving them by
hand found FOUR more, and the important half is how they failed:

    name                                corpus says      engine did
    GetUIElementRectangleScreenPosition  needs 3 args     RAISED       <- loud
    GetTargetMonitorDetailsBridge        needs 3 args     OK | nil     <- SILENT
    GetLiveData                          never called     OK | nil     <- SILENT
    GetTargetMonitorDetails              never called     OK |         <- SILENT

THREE OF FOUR ANSWERED SILENTLY. So the live run's `ok=90 raised=1` was never evidence
that 90 calls were sound -- a wrong-arity call returns a benign nil that is
indistinguishable from "this genuinely has no value". Only the corpus can tell them
apart, which is why this is a test and not a play session.

Two of the four also violated the mod's OWN documented admission rule ("ATTESTED IN
VANILLA -- 46 of the 308 candidates are NOT called anywhere in vanilla and are
therefore NOT probed"). A rule that is only written down is not enforced; this file is
the enforcement.

⚠ WHY THE EXTRACTOR STRIPS COMMENTS AND ffi.cdef FIRST. The first version of this
measurement reported ZERO defects, because:
  * a COMMENT (`-- ... GetUIElementRectangleScreenPosition() function which is used`)
    made a 0-arity look attested for the one function the engine had already caught
    raising, and
  * an ffi.cdef SIGNATURE (`uint32_t GetAllCommanders(CommanderInfo* result, ...)`)
    invented an arity of 4 for a lua global vanilla always calls with one argument.
Counting a declaration or a comment as evidence of how something is CALLED is exactly
the substitution this whole register is about (F92). The engine disagreeing with the
script is what exposed it.
"""
from __future__ import annotations

import pathlib
import os
import re

import pytest

from x4validate import _paths

MOD_GLOB = "*/ui/*live_query.lua"
#: The arity each bucket asserts by putting a name in it.
EXPECTED_ARITY = {"RECON_ZERO": 0, "RECON_OBJ": 1, "RECON_FAC": 1, "RECON_MACRO": 1}


def _find_mod_lua(pattern):
    """The shipped game extension, wherever it lives: mods/ in the public toolkit,
    dev/ in the private workspace.

    MEASURED 2026-09-01: these tests looked ONLY at `parents[3]/"dev"`, which does not
    exist in the public repo -- the extension ships at mods/. 125 tests skipped silently,
    guarding a Lua contract whose violation HANGS X4 and needs a force-kill. A skip that
    is structurally guaranteed is not coverage; it is a green tick over untested code.

    Returns (path, roots_searched). The caller FAILS rather than skips when a root exists
    but holds no match, because that is a broken layout, not an absent one.
    """
    root = pathlib.Path(__file__).resolve().parents[3]
    searched = []
    for name in ("mods", "dev"):
        d = root / name
        if not d.is_dir():
            continue
        searched.append(str(d))
        hits = sorted(d.glob(pattern))
        if hits:
            return hits[0], searched
    return None, searched

def _require_mod_lua(hit, roots, what):
    """Skip only when there is nowhere to look; FAIL when a root exists and is empty.

    "mods/ is present but holds no live_query.lua" is a BROKEN LAYOUT, not an absent
    one, and a skip there is a green tick over untested code -- which is exactly what
    happened when these tests looked only in dev/: 125 skipped, silently, guarding a Lua
    contract whose violation hangs X4 and needs a force-kill.
    """
    if hit is not None:
        return hit
    if roots:
        raise AssertionError(
            "searched %s and found no %s. A root exists but holds no game-side mod, "
            "which is a broken layout -- refusing to skip over it." % (roots, what))
    pytest.skip("no mods/ or dev/ root in this tree, so there is nothing to check")



def _mod_lua():
    # Located by GLOB, like tests/test_modlua_rearm.py: the mod folder carries a
    # personal prefix and this file ships, so the name must not be spelled here.
    import pathlib
    # mods/ (public toolkit) then dev/ (private workspace). Looking only in dev/
    # skipped this silently in the public repo -- see _find_mod_lua's note.
    hit, _roots = _find_mod_lua(MOD_GLOB)
    return hit


def _strip_noncode(txt: str) -> str:
    """Remove ffi.cdef blocks and comments -- see the module docstring."""
    txt = re.sub(r"ffi\.cdef\s*\[\[.*?\]\]", "", txt, flags=re.S)
    txt = re.sub(r"--\[\[.*?\]\]", "", txt, flags=re.S)
    return re.sub(r"(?m)--.*$", "", txt)


def _split_args(txt: str, i: int):
    """(args, end) for the call whose '(' is at i, by PAREN DEPTH.

    A regex cannot do this: `f(g(a, b), c)` has two args, not three.
    """
    depth, start, args, j = 0, i + 1, [], i
    while j < len(txt):
        c = txt[j]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                tail = txt[start:j].strip()
                if tail:
                    args.append(tail)
                return args, j
        elif c == "," and depth == 1:
            args.append(txt[start:j].strip())
            start = j + 1
        elif c in "\"'":
            q, j = c, j + 1
            while j < len(txt) and txt[j] != q:
                j += 2 if txt[j] == chr(92) else 1
        j += 1
    return None, len(txt)


@pytest.fixture(scope="module")
def corpus():
    ref = _paths.reference()
    if ref is None or not (ref / "ui").is_dir():
        pytest.skip("no reference tree configured; this check needs vanilla ui lua")
    out = []
    for root, _, names in os.walk(ref / "ui"):
        for n in names:
            if n.endswith(".lua"):
                p = os.path.join(root, n)
                try:
                    out.append(_strip_noncode(
                        open(p, encoding="utf-8", errors="replace").read()))
                except OSError:
                    pass
    # REFUSE rather than pass vacuously: with no files every name reads as
    # "unattested" and the test would go green over nothing.
    assert len(out) > 20, (
        f"read only {len(out)} vanilla ui lua files -- refusing to judge attestation "
        f"from a corpus that small, because every name would look unattested")
    return out


@pytest.fixture(scope="module")
def buckets():
    p = _mod_lua()
    if p is None:
        _require_mod_lua(None, _ROOTS if "_ROOTS" in dir() else [], "game-side mod lua")
    src = p.read_text(encoding="utf-8")
    out = {}
    for name in EXPECTED_ARITY:
        m = re.search(r"local %s = \{(.*?)\n\}" % name, src, re.S)
        assert m, f"{name} not found in the mod"
        # Strip comments FIRST. A quoted word inside an explanatory comment -- e.g.
        # a cited vanilla call site mentioning "macro" -- is otherwise read as a list
        # entry, inventing a probe name that does not exist. The same defect as
        # counting a comment as a call site, one level in, and it bit within the hour
        # of the strippers being added for exactly that reason.
        out[name] = re.findall(r'"(\w+)"', _strip_noncode(m.group(1)))
    assert sum(len(v) for v in out.values()) > 50, out
    return out


def _arities(corpus, name):
    pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"\s*\(")
    found = []
    for txt in corpus:
        for m in pat.finditer(txt):
            if txt[max(0, m.start() - 12):m.start()].rstrip().endswith("function"):
                continue                       # a definition, not a call
            args, _ = _split_args(txt, m.end() - 1)
            if args is not None:
                found.append(len(args))
    return found


def test_every_probed_name_is_called_by_vanilla_at_the_bucket_arity(corpus, buckets):
    """The rule the mod states in prose, enforced.

    A name vanilla never calls, or never calls with the arity its bucket assumes, is
    not a probe -- it is a guess whose most likely reply is a benign nil.
    """
    bad = []
    for bucket, names in buckets.items():
        want = EXPECTED_ARITY[bucket]
        for nm in names:
            ar = _arities(corpus, nm)
            if not ar:
                bad.append(f"{bucket}: {nm} -- vanilla NEVER calls it (unattested)")
            elif want not in ar:
                bad.append(f"{bucket}: {nm} -- bucket wants {want} arg(s), "
                           f"vanilla uses {sorted(set(ar))}")
    assert not bad, (
        "recon would call these with an argument shape vanilla never uses:\n  "
        + "\n  ".join(bad)
        + "\n\nThe engine does NOT reliably raise on this: measured 2026-08-31, three "
          "of four such calls returned `OK | nil`, indistinguishable from a real "
          "absence. Move the name to the right bucket, or drop it.")


def test_the_extractor_ignores_comments_and_cdef_declarations():
    """The falsification twin for the extractor itself, targeting BOTH strippers
    separately -- a single fixture exercising only one of them would leave the other
    untested, and the first version of this measurement was wrong for exactly that
    reason (it reported 0 defects)."""
    commented = "-- see Foo() for details\nlocal x = 1\n"
    assert _arities([_strip_noncode(commented)], "Foo") == [], "counted a COMMENT"

    cdef = 'ffi.cdef[[ uint32_t Foo(Info* result, uint32_t len); ]]\n'
    assert _arities([_strip_noncode(cdef)], "Foo") == [], "counted a CDEF declaration"

    real = "local y = Foo(a, b)\n"
    assert _arities([_strip_noncode(real)], "Foo") == [2], (
        "the strippers ate a REAL call -- this test must be able to see one, or the "
        "two assertions above pass vacuously")


def test_nested_call_arguments_are_counted_by_depth_not_commas():
    """`f(g(a, b), c)` is two arguments. A comma-splitting regex says three, and would
    silently reclassify a one-argument function as taking more."""
    assert _arities([_strip_noncode("Foo(Bar(a, b), c)\n")], "Foo") == [2]
    assert _arities([_strip_noncode('Foo("a, b")\n')], "Foo") == [1], "split a STRING"


def test_a_qualified_or_method_call_is_not_the_lua_global(corpus):
    """`C.GetAllCommanders(buf, n, id, 0)` is the ffi symbol and takes four arguments;
    the lua global `GetAllCommanders(component)` takes one. Conflating them invented an
    arity that made a real mismatch disappear."""
    assert _arities([_strip_noncode("C.Foo(a, b, c, d)\n")], "Foo") == []
    assert _arities([_strip_noncode("obj:Foo(a)\n")], "Foo") == []


def _first_args(corpus, name):
    """Every first argument vanilla passes to `name`, as written."""
    pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"\s*\(")
    out = []
    for txt in corpus:
        for m in pat.finditer(txt):
            if txt[max(0, m.start() - 12):m.start()].rstrip().endswith("function"):
                continue
            args, _ = _split_args(txt, m.end() - 1)
            if args:
                out.append(args[0])
    return out


def _macro_shaped(arg: str) -> bool:
    """Is this argument LITERALLY a macro, as vanilla writes one?

    Deliberately textual and narrow. It matches the two forms vanilla actually uses
    and nothing else -- no heuristic about variable names. Guessing that `foo64` is
    an object id, or that anything containing "mac" is a macro, would be the very
    substitution this file exists to catch (F92).
    """
    a = arg.replace(" ", "")
    return a.endswith(".macro") or ('"macro")' in a) or ("'macro')" in a)


def test_a_name_vanilla_passes_a_MACRO_is_not_in_the_OBJECT_bucket(corpus, buckets):
    """★ THE GAP THE ARITY CHECK CANNOT SEE, and the reason this test exists.

    F88 is a TYPE error, not an arity error: `GetMacroUnitStorageCapacity` takes ONE
    argument and so does every RECON_OBJ name, so the arity check above passes it
    happily. MEASURED: putting that name back into RECON_OBJ left the arity test GREEN
    -- a mutant that survived, which is how this gap was found.

    Re-deriving the whole list on that basis then found a FIFTH instance nobody had
    looked for: `GetTransportUnitMacros`, which vanilla calls as
    `GetTransportUnitMacros(GetComponentData(ship.shipid, [macro]))` at
    menu_map.lua:30321. It had been sitting in RECON_OBJ, and live it answered `OK|`
    -- empty, no error. Silent, like the other four.

    Scope, stated: this catches the MACRO-vs-OBJECT confusion only, because that is
    the only argument type we can identify from vanilla's own text without guessing.
    It does not make the buckets type-safe in general.
    """
    bad = []
    for nm in buckets["RECON_OBJ"]:
        fa = _first_args(corpus, nm)
        hits = [a for a in fa if _macro_shaped(a)]
        if hits and len(hits) == len(fa):
            bad.append(f"{nm}: vanilla passes a MACRO ({hits[0][:60]}) at "
                       f"{len(hits)}/{len(fa)} call sites, but it is in RECON_OBJ")
    assert not bad, (
        "these would be handed an object id where vanilla passes a macro -- F88's "
        "exact defect, which does NOT raise; it returns a benign empty answer:\n  "
        + "\n  ".join(bad))


def test_every_RECON_MACRO_name_is_one_vanilla_passes_a_macro(corpus, buckets):
    """The twin, targeting the other direction. Without it the rule above could be
    satisfied by emptying RECON_OBJ into RECON_MACRO, which would be just as wrong
    and would still pass."""
    for nm in buckets["RECON_MACRO"]:
        fa = _first_args(corpus, nm)
        assert fa, f"{nm} is in RECON_MACRO but vanilla never calls it"
        assert any(_macro_shaped(a) for a in fa), (
            f"{nm} is in RECON_MACRO but vanilla never passes it a macro: {fa[:3]}")


def test_the_macro_shape_test_recognises_vanillas_two_forms_and_rejects_an_id():
    """Falsification per clause: both accepted forms, and the rejected one. If
    `_macro_shaped` returned True for an object id, the OBJECT bucket would empty
    itself into MACRO and both tests above would still pass."""
    assert _macro_shaped("menu.macro")
    assert _macro_shaped('GetComponentData(ship.shipid, "macro")')
    assert not _macro_shaped("convertedComponent")
    assert not _macro_shaped("pickedcomponent64")
    assert not _macro_shaped('GetComponentData(id, "owner")')

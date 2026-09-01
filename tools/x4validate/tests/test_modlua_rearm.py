"""Behavioural tests for the GAME-SIDE lua, run against a real Lua interpreter.

WHY THIS EXISTS. Everything else about the live channel is testable in Python, but the
half that decides whether the channel survives a disconnect is 40 lines of lua that only
ever ran inside X4 — where a mistake costs a game launch, and one specific mistake costs
a FORCE-KILL.

THE HANG THIS GUARDS. `sn_mod_support_apis/ui/named_pipes/pipes.lua:440` `Close_Pipe`
drains the read FIFO in a `while not FIFO.Is_Empty(...)` loop, calling every callback
with `"ERROR"`, and only sets `pipes[name] = nil` AFTERWARDS. `Declare_Pipe` reuses
existing state. So a `Schedule_Read` called synchronously from inside that callback
writes into **the very FIFO being drained** — the loop never terminates and the game
hangs on the UI thread.

So the contract is not "it re-arms". It is **"it re-arms LATER, never synchronously"**,
and the test below can tell those two apart. A test that only asserted "re-arms" would
pass on the hanging version.

The stubs are deliberately thin — they record calls rather than emulate the API — because
the questions here are *how many times* and *from where*, not *what came back*.
"""
from __future__ import annotations

import pathlib
import re

import pytest

lupa = pytest.importorskip("lupa", reason="lua runtime; dev-only check of the game-side mod")

#: Located by GLOB, not by a spelled-out folder name. The game-side mod is a personal
#: artifact and its folder carries a personal prefix; this file ships, so naming it here
#: would put that identifier in the public package -- which the mirror's scanner catches
#: only AFTER a push. Same reason the marker assertions below match a suffix.
_DEV = pathlib.Path(__file__).resolve().parents[3] / "dev"
_FOUND = sorted(_DEV.glob("*/ui/*live_query.lua")) if _DEV.is_dir() else []
MOD_LUA = _FOUND[0] if _FOUND else None

HARNESS = r"""
local src, pre = ...
_G.log = {}
_G.sched_reads = {}     -- every Schedule_Read call
_G.writes = {}          -- every Schedule_Write call
_G.deferred = {}        -- every Helper.addDelayedOneTimeCallbackOnUpdate call
_G.now = 100.0

function DebugError(s) _G.log[#_G.log+1] = tostring(s) end
function getElapsedTime() return _G.now end

Helper = {
    addDelayedOneTimeCallbackOnUpdate = function(cb, blockinput, delaytime)
        _G.deferred[#_G.deferred+1] = {cb = cb, blockinput = blockinput, t = delaytime}
    end,
}

local fake_pipes = {
    Schedule_Read = function(name, cb, continuous)
        -- Injectable failure: the api can throw here, and until 2026-08-29 that
        -- killed the channel until the next reload.
        if _G.fail_reads then error("simulated Schedule_Read failure") end
        _G.sched_reads[#_G.sched_reads+1] = {name = name, cb = cb, continuous = continuous}
    end,
    Schedule_Write = function(name, cb, msg)
        -- Injectable failure: this is the only way a reply can fail to reach the
        -- wire, which is the case that must still leave a log line.
        if _G.fail_writes then error("simulated pipe write failure") end
        _G.writes[#_G.writes+1] = {name = name, msg = msg}
    end,
}

-- A fake FFI, so the ffi-only verbs (player/stations/ships) are testable offline.
-- Deliberately thin: it records rather than emulates, because the questions here are
-- about the GUARDS -- allowlist, validity, the payload cap, the denominator -- not
-- about LuaJIT's semantics.
_G.cdefs = {}
_G.fake_ids = {}          -- what ffi.new("UniverseID[?]", n) hands back
local fake_ffi = {
    cdef = function(src) _G.cdefs[#_G.cdefs+1] = src end,
    string = function(p) return tostring(p) end,
    new = function(spec, n)
        local buf = {}
        local ischar = tostring(spec):find("char") ~= nil
        for i = 0, (n or 0) - 1 do
            if ischar then
                -- const char*[?] -- the faction-id buffer, NOT an id buffer. Returning
                -- ULL strings here would make `objects` enumerate factions named
                -- "100000ULL" and quietly find nothing.
                buf[i] = (_G.fake_factions and _G.fake_factions[i+1]) or ("fac" .. tostring(i))
            else
                -- ffi buffers carry UniverseID cdata, which stringifies with a ULL
                -- suffix. Modelled as that string: it is what `wire` and rows see.
                buf[i] = _G.fake_ids[i+1] or (tostring(100000 + i) .. "ULL")
            end
        end
        return buf
    end,
    -- `wire` casts a lua number back to the canonical UniverseID rendering. Returning
    -- the finished string is exactly what tostring() of the real cdata would give.
    cast = function(ctype, v)
        local n = tonumber(tostring(v))
        if n == nil then return tostring(v) end
        return string.format("%.0f", n) .. "ULL"
    end,
    -- Indexing a symbol the engine does not export RAISES in real ffi rather than
    -- returning nil. Mirrored, because the probe's pcall depends on it.
    C = setmetatable({}, {__index = function(_, k)
        local f = _G.fake_C and _G.fake_C[k]
        if f == nil then error("C." .. tostring(k) .. " is not exported") end
        return f
    end}),
}

function require(path)
    if path == "ffi" then
        if _G.no_ffi then error("ffi unavailable") end
        return fake_ffi
    end
    return fake_pipes
end
function Register_OnLoad_Init(fn, path) _G.captured_init = fn end

-- The engine's ui event registry. md/lua_loader.xml raises
-- "Lua_Loader.Send_Priority_Ready" from a Reload_Listener whose <check_any> covers
-- BOTH <event_game_loaded/> and <event_game_started/>, so this is the hook a mod uses
-- to notice a save load. `__fire_game_load` lets a test raise it.
_G.ui_events = {}
function RegisterEvent(name, cb)
    _G.ui_events[name] = _G.ui_events[name] or {}
    table.insert(_G.ui_events[name], cb)
end
function _G.__fire_game_load()
    local subs = _G.ui_events["Lua_Loader.Send_Priority_Ready"] or {}
    for _, cb in ipairs(subs) do cb() end
    return #subs
end

-- Engine globals the live-view verbs call BARE (measured in game 2026-08-29).
--
-- ⚠ THESE MODEL TWO ID REPRESENTATIONS, because that distinction is now load-bearing.
-- MEASURED in game 2026-08-30: the ffi entry points yield `uint64` cdata that
-- stringifies as `1046331ULL`, while the BARE globals yield plain lua NUMBERS that
-- stringify as `282463` -- same id to the engine, two strings on our side. `wire`
-- exists to collapse them, so a fake that returned one shape for everything could not
-- test the thing the code is for.
--
-- A cdata UniverseID is modelled as the STRING "<n>ULL": lupa cannot produce a real
-- cdata, and `wire` deliberately keys on what a value renders as rather than on its
-- lua type, so this models it exactly where it matters.
local function to_number(s)
    s = tostring(s)
    local ull = s:match("^(%d+)ULL$")
    if ull then return tonumber(ull) end
    local luaid = s:match("^ID:%s*(%d+)$")
    if luaid then return tonumber(luaid) end
    return tonumber(s)
end
function ConvertStringTo64Bit(s) return to_number(s) end
function ConvertIDTo64Bit(s) return to_number(s) end
function ConvertStringToLuaID(s) return "luaid:" .. tostring(s) end
function IsValidComponent(id)
    if _G.invalid_ids and _G.invalid_ids[tostring(id)] then return false end
    return true
end
function GetComponentData(id, ...)
    local names = {...}
    local out = {}
    -- ⚠ THE ENGINE DOES NOT ACCEPT A RAW UniverseID cdata HERE, and it does not raise
    -- on one -- it just returns nothing about any object. MEASURED in game: the --wide
    -- path passed `buf[i]` straight through and got 1539 of 1539 unclassified, with
    -- zero read failures. Vanilla always converts first. Modelled by returning nils for
    -- a ULL-shaped id, so a caller that forgets the conversion FAILS a test instead of
    -- being discovered in game.
    if tostring(id):match("^%d+ULL$") then
        local up0 = table.unpack or unpack
        return up0({}, 1, #names)
    end
    for i = 1, #names do
        -- ⚠ NOT `planted or fallback`. A planted value of FALSE is falsy, so `or` would
        -- hand back the fallback STRING -- which is truthy -- and every boolean flag a
        -- test set to false would read as true. It did exactly that: `isObjectValid`
        -- accepted a wreck and an asteroid, and the flag column rendered every letter.
        local v
        if _G.component_data ~= nil then v = _G.component_data[names[i]] end
        if v == nil then v = names[i] .. "-of-" .. tostring(id) end
        -- `nil_fields` models a field the engine has NOTHING for. It cannot be
        -- expressed through component_data, because a nil there is indistinguishable
        -- from "not planted" and falls through to the fallback string. MEASURED in
        -- game: a nil classid makes Helper.isComponentClass raise, and that killed
        -- both compare and objects --wide.
        if _G.nil_fields ~= nil and _G.nil_fields[names[i]] then v = nil end
        out[i] = v
    end
    -- ⚠ NOT `table.unpack and table.unpack(out) or unpack(out)`. An and/or expression
    -- ADJUSTS ITS RESULT TO ONE VALUE, so that form silently returns only the first
    -- field -- and the real GetComponentData is variadic multi-return. It made the
    -- sector-filter test report 0 rows against code that was correct.
    -- ⚠ EXPLICIT BOUNDS. A nil_fields entry leaves a HOLE in `out`, and unpack stops
    -- at a hole -- so every field after the nil would silently vanish and the caller
    -- would map values to the WRONG NAMES. Passing 1, #names forces the real length.
    local up = table.unpack or unpack
    return up(out, 1, #names)
end

-- Container enumeration and class discrimination, for the `objects` design. Thin and
-- table-driven for the same reason as the rest of this fake: the questions offline are
-- about the GUARDS -- does the probe refuse cleanly, does it report BOTH container
-- forms separately, does it walk the list it was given -- not about engine semantics,
-- which only the running game can answer.
--
-- ⚠ These are deliberately NOT faithful. ConvertStringTo64Bit prefixes, so a wire-form
-- round trip does NOT come back identical here. That is correct: a test asserting the
-- round trip is IDENTICAL offline would be asserting a property of this file, not of
-- the engine, and would go green while the real answer stayed unknown.
_G.contained = nil          -- {["owner|container"] = {obj, ...}}
_G.contained_stations = nil -- {[owner] = {obj, ...}}
_G.class_by_field = nil     -- {["classid-of-A"] = "ship", ...}  (Helper form)
_G.obj_class = nil          -- {[obj] = "ship"}                  (bare form)

function GetContainedObjectsByOwner(owner, container)
    if _G.contained == nil then return {} end
    local key = tostring(owner) .. "|" .. tostring(container)
    return _G.contained[key] or _G.contained[tostring(owner)] or {}
end
function GetContainedStationsByOwner(owner, container)
    if _G.contained_stations == nil then return {} end
    return _G.contained_stations[tostring(owner)] or {}
end
function IsComponentClass(obj, cls)
    return (_G.obj_class and _G.obj_class[tostring(obj)]) == cls
end
-- Default is plain string equality, so a test can say `component_data = {classid =
-- "station"}` and mean it. `class_by_field` overrides that when a test needs DIFFERENT
-- classes per object, which is the only case the simple form cannot express.
Helper.isComponentClass = function(classid, cls)
    if _G.class_by_field ~= nil then
        return _G.class_by_field[tostring(classid)] == cls
    end
    return tostring(classid) == tostring(cls)
end

-- Anything that must be true BEFORE the mod's chunk runs goes here. The mod requires
-- ffi at LOAD time, so a flag set afterwards arrives too late -- which is exactly how
-- the no-ffi test first "passed" against a runtime that had a working ffi all along.
if pre ~= nil and pre ~= "" then
    local pchunk, perr = load(pre)
    if pchunk == nil then error("pre-chunk did not compile: " .. tostring(perr)) end
    pchunk()
end

-- A full UI RELOAD, as the engine performs it: every registered ui lua file is
-- RE-EXECUTED in the same environment. MEASURED in game 2026-08-29 with controls both
-- ways -- pressing ALT-ENTER causes one (2 presses, 2 reloads) and so does LOADING A
-- SAVE, while alt-TAB does not (75.7 s foregrounded, and 1190 s in an earlier session,
-- zero). Re-running the same source is exactly what the engine does, so this models
-- the one thing that matters here: what a SECOND incarnation inherits from the first.
_G.__src = src
function _G.__reload()
    local c2, e2 = load(_G.__src)
    if c2 == nil then error("reload did not compile: " .. tostring(e2)) end
    c2()
    return true
end

local chunk, err = load(src)
if chunk == nil then error("lua did not compile: " .. tostring(err)) end
chunk()
return true
"""


def _build(extra: str = "", pre: str = ""):
    """Load the mod, optionally with EXTRA lua appended to the same chunk.

    Appending is sound because the mod is a single chunk with no top-level `return`
    (asserted below), so appended code shares its lexical scope and can see the
    file-local `verbs` and `reply` tables. That is the only way to install a verb
    that behaves the way a FUTURE verb will.

    It matters because every verb shipped today pcalls internally and therefore
    CANNOT reach the dispatch error path at all. A guard that no current caller can
    reach is exactly the kind that rots untested and is found broken later by the
    first verb that does reach it.
    """
    if MOD_LUA is None:
        pytest.skip("game-side live-query mod not present in dev/")
    src = MOD_LUA.read_text(encoding="utf-8")
    assert not any(ln.startswith("return") for ln in src.splitlines()), (
        "the mod grew a top-level `return`; appended test verbs would be unreachable "
        "and every test using _build(extra) would silently test nothing")
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.eval("function(...) " + HARNESS + " end")(src + "\n" + extra + "\n", pre)
    return rt


@pytest.fixture
def lua():
    return _build()


@pytest.fixture
def lua_factory():
    return _build


#: A verb that answers and THEN fails. No shipped verb can do this today; the live
#: view's verbs will be complex enough to.
REPLY_THEN_RAISE = """
verbs.__t_reply_then_raise = function(seq)
    reply(seq, "OK", "first")
    error("boom AFTER replying")
end
"""

#: A verb that fails before answering. The frame must still be produced.
RAISE_ONLY = """
verbs.__t_raise_only = function(seq)
    error("boom BEFORE replying")
end
"""


def g(rt, name):
    return rt.globals()[name]


def init(rt):
    g(rt, "captured_init")()


def deliver(rt, msg):
    """Hand *msg* to the callback the mod registered, exactly as pipes.lua would."""
    cb = g(rt, "sched_reads")[len(g(rt, "sched_reads"))]["cb"]
    cb(msg)


# --------------------------------------------------------------------------- #
# it loads and arms
# --------------------------------------------------------------------------- #

def test_the_mod_loads_and_arms_a_continuous_read(lua):
    init(lua)
    reads = g(lua, "sched_reads")
    assert len(reads) == 1
    assert reads[1]["name"] == "x4live"
    assert reads[1]["continuous"] is True
    assert any("_LIVE loaded" in s for s in g(lua, "log").values())


def test_the_load_marker_is_emitted_BEFORE_any_pipe_work(lua):
    """PROVE IT RAN BEFORE DEBUGGING WHAT IT DID. If the marker came after the pipe
    logic, a failure in that logic would look identical to the mod not loading — which
    is precisely the confusion that cost three attempts on 2026-08-29."""
    init(lua)
    logs = list(g(lua, "log").values())
    assert "_LIVE loaded" in logs[0]


# --------------------------------------------------------------------------- #
# THE HANG GUARD -- the reason this file exists
# --------------------------------------------------------------------------- #

def test_an_ERROR_sentinel_does_NOT_re_arm_SYNCHRONOUSLY(lua):
    """The whole point. A synchronous re-arm writes into the FIFO `Close_Pipe` is
    draining, and the game hangs on the UI thread.

    Note what this asserts: not "it re-armed", but "it did NOT re-arm *yet*". A test
    asserting only the former passes on the hanging version.
    """
    init(lua)
    before = len(g(lua, "sched_reads"))
    deliver(lua, "ERROR")
    assert len(g(lua, "sched_reads")) == before, (
        "re-armed synchronously from inside the disconnect callback -- this hangs X4")


def test_an_ERROR_sentinel_DEFERS_the_re_arm_to_the_next_update(lua):
    init(lua)
    deliver(lua, "ERROR")
    d = g(lua, "deferred")
    assert len(d) == 1, "the re-arm was not scheduled at all -- channel dies silently"


def test_the_deferred_re_arm_does_NOT_block_player_input(lua):
    """`blockinput=true` calls `C.SetAllUIInputIgnored(true)` and freezes the player's
    controls until the callback fires. Pinned because it is one positional argument
    away, and the failure is invisible in code review."""
    init(lua)
    deliver(lua, "ERROR")
    assert g(lua, "deferred")[1]["blockinput"] is False


def test_the_deferred_time_is_ABSOLUTE_and_in_the_FUTURE(lua):
    """`delaytime` is compared against `getElapsedTime()`, not treated as a duration.
    Passing a bare `2` would schedule it in the past and fire immediately -- which
    reintroduces the synchronous re-arm by another route."""
    init(lua)
    lua.globals()["now"] = 500.0
    deliver(lua, "ERROR")
    assert g(lua, "deferred")[1]["t"] > 500.0


def test_running_the_deferred_callback_DOES_re_arm(lua):
    """The other half. Deferring is only correct if the deferred thing actually arms."""
    init(lua)
    before = len(g(lua, "sched_reads"))
    deliver(lua, "ERROR")
    g(lua, "deferred")[1]["cb"]()
    assert len(g(lua, "sched_reads")) == before + 1


def test_a_disconnect_is_survivable_REPEATEDLY(lua):
    """Three disconnect/recover cycles. A fix that recovers once and then wedges would
    pass every single-cycle test above, and would present in-game as "it worked for a
    while" -- the hardest kind of report to act on."""
    init(lua)
    for cycle in range(3):
        deliver(lua, "ERROR")
        d = g(lua, "deferred")
        d[len(d)]["cb"]()
        assert len(g(lua, "sched_reads")) == cycle + 2, f"stopped recovering at cycle {cycle}"


# --------------------------------------------------------------------------- #
# the throttle -- debug.txt is x4debug's INPUT, so spam corrupts another instrument
# --------------------------------------------------------------------------- #

def test_repeated_disconnects_do_not_flood_the_debug_log(lua):
    """With no server listening the cycle is re-arm -> ERROR -> re-arm forever. The
    delay throttles the RATE; this throttles the LOG. Unbounded, it would add lines to
    debug.txt indefinitely -- and debug.txt is what `x4debug triage` reads."""
    init(lua)
    for _ in range(50):
        deliver(lua, "ERROR")
        d = g(lua, "deferred")
        d[len(d)]["cb"]()
    sentinel_lines = [s for s in g(lua, "log").values() if "pipe sentinel" in s]
    assert len(sentinel_lines) <= 5, f"{len(sentinel_lines)} sentinel lines from 50 disconnects"


def test_the_throttle_reopens_after_a_long_quiet_period(lua):
    """The falsification twin for the throttle: it must suppress, not silence. A
    channel that stops reporting disconnects forever is a channel that cannot tell you
    it is broken."""
    init(lua)
    for _ in range(10):
        deliver(lua, "ERROR")
    quiet = len([s for s in g(lua, "log").values() if "pipe sentinel" in s])
    lua.globals()["now"] = g(lua, "now") + 600.0
    deliver(lua, "ERROR")
    after = len([s for s in g(lua, "log").values() if "pipe sentinel" in s])
    assert after > quiet, "the throttle silenced disconnect reporting permanently"


# --------------------------------------------------------------------------- #
# refusal beats a hang
# --------------------------------------------------------------------------- #

def test_without_Helper_it_REFUSES_rather_than_re_arming_synchronously(lua):
    """If the deferral mechanism is missing we must NOT fall back to a synchronous
    re-arm. A channel that needs a reload is a nuisance; a hung game is a force-kill,
    and the message has to say which state we are in."""
    init(lua)
    lua.execute("Helper = nil")
    before = len(g(lua, "sched_reads"))
    deliver(lua, "ERROR")
    assert len(g(lua, "sched_reads")) == before, "re-armed synchronously without Helper"
    assert any("cannot re-arm" in s for s in g(lua, "log").values())


# --------------------------------------------------------------------------- #
# the reply framing must agree with the Python decoder
# --------------------------------------------------------------------------- #

def test_a_ping_produces_a_frame_the_python_side_accepts(lua):
    """Cross-checks the two halves of the protocol against each other in one process.
    Every other test of the frame contract feeds Python a frame PYTHON built."""
    from x4validate import _livepipe as lp

    init(lua)
    deliver(lua, "MQ\t1\t7\tping")
    w = g(lua, "writes")
    assert len(w) == 1, "the mod did not reply to a well-formed ping"
    reply = lp.decode_reply(w[1]["msg"], 7)
    assert reply.status == "OK"
    assert reply.fields[0] == "pong"


def test_an_unknown_verb_is_answered_not_ignored(lua):
    """Silence is indistinguishable from a paused game, so every command must produce
    a frame -- including a bad one."""
    from x4validate import _livepipe as lp

    init(lua)
    deliver(lua, "MQ\t1\t3\t__no_such_verb__")
    reply = lp.decode_reply(g(lua, "writes")[1]["msg"], 3)
    assert reply.status == "ERR"


# --------------------------------------------------------------------------- #
# EXACTLY ONE FRAME PER QUESTION -- the double-frame desync
# --------------------------------------------------------------------------- #

def test_a_verb_that_raises_WITHOUT_replying_still_produces_a_frame(lua_factory):
    """Silence on the wire is indistinguishable from a paused game, so a failed verb
    must still answer. This is the twin of the test below: together they pin that the
    guard suppresses a DUPLICATE frame and never the ONLY frame."""
    from x4validate import _livepipe as lp

    rt = _build(RAISE_ONLY)
    init(rt)
    deliver(rt, "MQ\t1\t5\t__t_raise_only")
    w = g(rt, "writes")
    assert len(w) == 1, f"{len(w)} frames; a raising verb must answer exactly once"
    assert lp.decode_reply(w[1]["msg"], 5).status == "ERR"


def test_a_verb_that_replies_THEN_raises_produces_exactly_ONE_frame(lua_factory):
    """The bug this guard exists for. Python reads one message per ask(), so a second
    frame stays queued and becomes the answer to the NEXT question -- tripping the
    sequence check one query AFTER the real fault, with nothing pointing back at it."""
    from x4validate import _livepipe as lp

    rt = _build(REPLY_THEN_RAISE)
    init(rt)
    deliver(rt, "MQ\t1\t7\t__t_reply_then_raise")
    w = g(rt, "writes")
    assert len(w) == 1, f"{len(w)} frames for one seq -- the next query will desync"
    r = lp.decode_reply(w[1]["msg"], 7)
    assert r.status == "OK" and r.payload == "first", (
        "the surviving frame must be the verb's real answer, not the error")


def test_the_post_reply_raise_is_still_LOGGED(lua_factory):
    """Suppressing the second FRAME must not suppress the second FACT. A verb that
    raised after answering is a real defect and has to leave a trace somewhere."""
    rt = _build(REPLY_THEN_RAISE)
    init(rt)
    deliver(rt, "MQ\t1\t7\t__t_reply_then_raise")
    assert any("raised AFTER replying" in s for s in g(rt, "log").values())


def test_a_post_reply_raise_does_not_poison_the_NEXT_query(lua_factory):
    """The consequence test, which is what actually hurt: under the old behaviour a
    stale seq-7 frame sat in the queue and became the answer to seq 8."""
    from x4validate import _livepipe as lp

    rt = _build(REPLY_THEN_RAISE)
    init(rt)
    deliver(rt, "MQ\t1\t7\t__t_reply_then_raise")
    deliver(rt, "MQ\t1\t8\tping")
    w = g(rt, "writes")
    assert len(w) == 2, f"expected one frame per question, got {len(w)}"
    assert lp.decode_reply(w[2]["msg"], 8).status == "OK"


def test_a_reply_that_CANNOT_be_sent_is_LOGGED_not_swallowed(lua_factory):
    """If even the error reply fails there is total silence on the wire, which reads
    as a paused game. The log line is then the only evidence -- and it was previously
    swallowed by a bare pcall, i.e. the exact failure its own comment claimed to
    prevent, one layer down."""
    rt = _build(RAISE_ONLY)
    init(rt)
    rt.execute("_G.fail_writes = true")
    deliver(rt, "MQ\t1\t9\t__t_raise_only")
    # len(), NOT `not ...values()`. A LuaIter is an object with no __bool__, so it is
    # truthy even when the table is empty -- that assertion could never have passed,
    # and it failed against code that was correct. The instrument, again.
    assert len(g(rt, "writes")) == 0, "the write was supposed to fail"
    assert any("could not reply to seq" in s for s in g(rt, "log").values())


# --------------------------------------------------------------------------- #
# a failed ARM must retry, and a missing CLOCK must refuse
# --------------------------------------------------------------------------- #

def test_a_FAILED_arm_schedules_a_RETRY_instead_of_dying(lua_factory):
    """Until 2026-08-29 one failed Schedule_Read killed the channel until the next
    reload, with a single log line as the only symptom."""
    rt = _build()
    rt.execute("_G.fail_reads = true")
    init(rt)
    assert any("Schedule_Read failed" in s for s in g(rt, "log").values())
    assert len(g(rt, "deferred")) == 1, "a failed arm did not schedule a retry"


def test_without_a_CLOCK_it_REFUSES_rather_than_losing_the_throttle(lua_factory):
    """An absolute deadline built from now = 0 is already in the past, so the callback
    fires on the NEXT FRAME and the 2s throttle silently disappears -- turning the
    no-server cycle into ~60 re-arms a second, each able to log, into debug.txt.
    debug.txt is x4debug's INPUT, so degrading quietly here corrupts an unrelated
    instrument. Refuse loudly instead."""
    rt = _build()
    init(rt)
    rt.execute("getElapsedTime = function() error('no clock') end")
    before = len(g(rt, "deferred"))
    deliver(rt, "ERROR")
    assert len(g(rt, "deferred")) == before, "scheduled an UNTHROTTLED re-arm"
    assert any("throttle cannot be honoured" in s for s in g(rt, "log").values())


def test_WITH_a_clock_it_still_schedules(lua_factory):
    """Falsification twin for the test above: the refusal must be caused by the
    MISSING CLOCK specifically, not by the sentinel path being broken outright."""
    rt = _build()
    init(rt)
    deliver(rt, "ERROR")
    assert len(g(rt, "deferred")) == 1


# --------------------------------------------------------------------------- #
# the capability probe
# --------------------------------------------------------------------------- #

def test_the_probe_reports_types_and_NEVER_invokes_a_symbol(lua_factory):
    """The probe's whole safety argument is that it only type()s. If it ever called
    one, a bad argument becomes reachable and the 'cannot crash' claim is void."""
    from x4validate import _livepipe as lp

    rt = _build()
    init(rt)
    rt.execute("_G.GetComponentData = function() _G.CALLED = true end")
    deliver(rt, "MQ\t1\t3\tprobe")
    r = lp.decode_reply(g(rt, "writes")[1]["msg"], 3)
    assert r.status == "OK"
    fields = dict(f.split("=", 1) for f in r.fields if "=" in f)
    assert fields["GetComponentData"] == "function"
    assert rt.globals()["CALLED"] is None, "the probe INVOKED a symbol"


def test_the_probe_reports_an_ABSENT_symbol_rather_than_omitting_it(lua_factory):
    """An absent symbol must come back as nil. Omitting it makes 'not reachable' and
    'we never asked' identical -- the narrowing-step defect, in the one instrument
    built to rule that out."""
    from x4validate import _livepipe as lp

    rt = _build()
    init(rt)
    deliver(rt, "MQ\t1\t4\tprobe")
    r = lp.decode_reply(g(rt, "writes")[1]["msg"], 4)
    names = [f.split("=", 1)[0] for f in r.fields if "=" in f]
    for required in ("GetComponentData", "GetNumAllFactionStations",
                     "GetObjectPositionInSector", "IsValidComponent"):
        assert required in names, f"probe never reported {required}"
    assert "=nil" in r.payload, (
        "nothing came back nil in a bare harness -- the probe is not actually looking")


def test_a_REUSED_seq_still_gets_its_own_frame(lua_factory):
    """The per-dispatch reset of the reply flag. `seq` comes from the CLIENT, so the
    mod must not assume it increments: if a caller reuses one, a stale flag from the
    previous query would suppress a legitimate error frame and the caller would wait
    out its timeout for an answer that was deliberately withheld."""
    from x4validate import _livepipe as lp

    rt = _build(REPLY_THEN_RAISE + RAISE_ONLY)
    init(rt)
    deliver(rt, "MQ\t1\t4\t__t_reply_then_raise")   # replies, sets the flag for seq 4
    deliver(rt, "MQ\t1\t4\t__t_raise_only")         # SAME seq, must still answer
    w = g(rt, "writes")
    assert len(w) == 2, f"the reused seq was silently dropped ({len(w)} frames)"
    assert lp.decode_reply(w[2]["msg"], 4).status == "ERR"


# --------------------------------------------------------------------------- #
# THE LIVE VIEW -- player / component / stations / ships
# --------------------------------------------------------------------------- #

FAKE_C = """
_G.fake_C = {
    -- ULL-suffixed, because these are ffi entry points returning UniverseID cdata.
    GetPlayerOccupiedShipID = function() return "1046331ULL" end,
    GetPlayerID             = function() return "77ULL" end,
    GetComponentClass       = function(id) return "ship_l" end,
    GetObjectPositionInSector = function(id)
        return {x = 1.5, y = 2.5, z = 3.5, yaw = 0.1, pitch = 0.2, roll = 0.3}
    end,
    GetNumAllFactionStations = function(f) return _G.n_stations or 0 end,
    GetAllFactionStations    = function(buf, n, f) return n end,
    GetNumAllFactionShips    = function(f) return _G.n_ships or 0 end,
    GetAllFactionShips       = function(buf, n, f) return n end,
    -- The faction list, for the cross-faction `objects` verb. Present here, but the
    -- fake ffi.C RAISES on a symbol this table lacks, so a test can delete either one
    -- to reach the "<not exported>" branch -- which is what keeps that branch a real
    -- one rather than decoration.
    -- `hidden` genuinely changes the count, so --hidden has an observable effect and a
    -- test asserting it cannot pass vacuously.
    GetNumAllFactions        = function(hidden)
        if hidden then return _G.n_factions_hidden or _G.n_factions or 0 end
        return _G.n_factions or 0
    end,
    GetAllFactions           = function(buf, n, hidden) return n end,
}
"""


def live(rt=None, **globals_):
    """A runtime with the fake engine wired up and `player` already run, so the
    allowlist is seeded the way it is in real use."""
    rt = rt or _build()
    rt.execute(FAKE_C)
    for k, v in globals_.items():
        rt.execute(f"_G.{k} = {v}")
    init(rt)
    return rt


def ask(rt, seq, *parts):
    from x4validate import _livepipe as lp

    deliver(rt, "MQ\t1\t%d\t%s" % (seq, "\t".join(parts)))
    w = g(rt, "writes")
    return lp.decode_reply(w[len(w)]["msg"], seq)


def reload_ui(rt):
    """Re-execute the mod's chunk and run the NEW chunk's Init, as a UI reload does.

    `deliver` always targets the most recent `Schedule_Read`, so after this the tests
    are talking to the new incarnation -- which is the engine's behaviour too.
    """
    g(rt, "__reload")()
    init(rt)


def probe_fields(rt, seq=99):
    r = ask(rt, seq, "probe")
    assert r.status == "OK", r.payload
    return dict(f.split("=", 1) for f in r.fields if "=" in f)


def test_component_REFUSES_an_id_this_session_never_issued(lua_factory):
    """The allowlist. MEASURED: 0 of 888 vanilla GetComponentData calls pass a foreign
    id, so the engine's behaviour on a fabricated one is unknown in BOTH directions --
    it may be harmless, it may crash the game. Never find out by accident."""
    rt = live()
    r = ask(rt, 1, "component", "999999999")
    assert r.status == "ERR"
    assert "not issued by this session" in r.payload


def test_player_SEEDS_the_allowlist_so_component_then_works(lua_factory):
    """The two halves are useless apart: without an issuer the allowlist is empty and
    `component` can never be used at all."""
    rt = live()
    p = ask(rt, 1, "player")
    assert p.status == "OK", p.payload
    ids = [f.split("=", 1)[1] for f in p.fields if f.startswith("occupiedship=")]
    assert ids, f"player did not report an occupied ship id: {p.payload}"
    r = ask(rt, 2, "component", ids[0])
    assert r.status == "OK", r.payload


def test_player_reports_position_via_the_ffi_STRUCT_not_a_data_field(lua_factory):
    """Position is not a GetComponentData field (zero such literals in vanilla); it
    comes back as a UIPosRot struct, which is why the cdef carries that typedef."""
    rt = live()
    p = ask(rt, 1, "player")
    assert any(f.startswith("pos=1.5,2.5,3.5") for f in p.fields), p.payload
    assert any(f.startswith("class=ship_l") for f in p.fields), p.payload


def test_a_STALE_component_is_ABSENT_not_ERR(lua_factory):
    """We asked and it is gone -- that is an ANSWER. Reporting it as ERR would make a
    destroyed ship indistinguishable from a malformed question."""
    rt = live()
    p = ask(rt, 1, "player")
    sid = [f.split("=", 1)[1] for f in p.fields if f.startswith("occupiedship=")][0]
    # ConvertStringTo64Bit now models the real bare global: it returns a NUMBER,
    # so the key IsValidComponent is looked up under is that number's string form.
    numeric = sid.replace("ULL", "")
    rt.execute('_G.invalid_ids = {["' + numeric + '"] = true}')
    r = ask(rt, 2, "component", sid)
    assert r.status == "ABSENT", f"{r.status}: {r.payload}"


def test_component_honours_a_CALLER_SUPPLIED_field_list(lua_factory):
    """The DevBench property: the vocabulary is the caller's, not something this mod
    has to predict. Also pins that dispatch forwards MORE than three arguments."""
    rt = live()
    p = ask(rt, 1, "player")
    sid = [f.split("=", 1)[1] for f in p.fields if f.startswith("occupiedship=")][0]
    r = ask(rt, 2, "component", sid, "hull", "shieldpercent", "owner", "macro")
    assert r.status == "OK", r.payload
    names = [f.split("=", 1)[0] for f in r.fields]
    assert names == ["hull", "shieldpercent", "owner", "macro"], names


def test_an_EMPTY_faction_list_is_OK_with_a_zero_count_never_ABSENT(lua_factory):
    """Asked, and the faction owns none. ABSENT would say 'no such question'."""
    rt = live(n_stations=0)
    r = ask(rt, 1, "stations", "xenon")
    assert r.status == "OK", r.payload
    assert "shown=0 matched=0 enumerated=0 total=0" in r.payload
    assert "CAPPED=no" in r.payload


def test_a_capped_list_REPORTS_ITS_OWN_DENOMINATOR(lua_factory):
    """A step that narrows data must announce it. GetNum* gives the true total for
    free, so there is no excuse for a silently truncated list."""
    rt = live(n_stations=4000, component_data='{classid = "station", realclassid = "station"}')
    r = ask(rt, 1, "stations", "argon", "--wide")
    assert r.status == "OK", r.payload[:200]
    header = r.fields[0]
    assert header.startswith("shown="), header
    shown = int(header.split("shown=")[1].split(" ")[0])
    assert "enumerated=4000" in header and "total=4000" in header, header
    assert shown < 4000, "nothing was capped, so this test proves nothing about capping"
    assert shown == len(r.fields) - 1, "header count disagrees with the rows actually sent"


def test_a_capped_list_STAYS_UNDER_the_payload_bound(lua_factory):
    """The bound is what stops an over-long reply, and an over-long reply does not
    truncate -- it tears the pipe down. Detection after the fact cannot help here."""
    from x4validate import _livepipe as lp

    rt = live(n_stations=4000, component_data='{classid = "station", realclassid = "station"}')
    r = ask(rt, 1, "stations", "argon", "--wide")
    # EXACT, no tolerance. This assertion used to read `<= 32000 + 200`, and that
    # 200-byte slack -- added for comfort, derived from nothing -- is precisely what
    # let a real 143-byte overrun through: the cap bounded the ROWS while the header
    # was prepended afterwards and never counted. MEASURED in game at 32143 bytes
    # against a "32000-byte" budget. A tolerance nobody derived is a place for
    # defects to live.
    assert lp.byte_len(r.payload) <= 32000, lp.byte_len(r.payload)


def test_the_cap_is_REACHABLE_so_the_bound_test_can_fail(lua_factory):
    """Falsification twin for the two above: with a small list nothing is capped, so
    a passing bound test on a small list would have proved nothing."""
    rt = live(n_stations=3, component_data='{classid = "station", realclassid = "station"}')
    r = ask(rt, 1, "stations", "argon", "--wide")
    assert "shown=3 matched=3 enumerated=3 total=3" in r.fields[0], r.fields[0]
    assert "CAPPED=no" in r.fields[0], "nothing was capped, so it must say so"


def test_enumeration_ISSUES_ids_so_they_can_then_be_inspected(lua_factory):
    rt = live(n_stations=2, component_data='{classid = "station", realclassid = "station"}')
    s = ask(rt, 1, "stations", "argon", "--wide")
    first_id = s.fields[1].split("|")[0]
    r = ask(rt, 2, "component", first_id)
    assert r.status == "OK", r.payload


def test_a_SECTOR_FILTER_narrows_the_list_and_says_so(lua_factory):
    """'What is around ME' is this, plus the sectorid that `player` hands out."""
    rt = live(n_stations=5)
    rt.execute('_G.component_data = {sectorid = "ID: 1", classid = "station", realclassid = "station"}')
    r = ask(rt, 1, "stations", "argon", "ID: 1", "--wide")
    assert "sector=ID:1" in r.fields[0], r.fields[0]
    assert len(r.fields) - 1 == 5, r.fields[0]
    r2 = ask(rt, 2, "stations", "argon", "ID: 2", "--wide")
    assert r2.status == "OK", r2.fields[0]
    assert "shown=0 matched=0 enumerated=5 total=5" in r2.fields[0], r2.fields[0]


def test_without_ffi_the_live_verbs_ERR_and_the_others_keep_working(lua_factory):
    """Graceful degradation. A missing cdef must not take the whole channel down --
    ping, macro and probe need no ffi at all."""
    # BEFORE the chunk loads. The mod requires ffi at LOAD time, so setting this
    # afterwards leaves it with a working ffi and the test passes vacuously -- which
    # is what it did on the first attempt, reporting OK where it demanded ERR.
    rt = _build(pre="_G.no_ffi = true")
    rt.execute(FAKE_C)
    init(rt)

    # Assert the MESSAGE, not just the status. Without the cdef guard these verbs
    # still fail -- `C` is nil, so the engine call raises and the dispatch pcall turns
    # it into an ERR anyway. So status alone cannot tell a deliberate refusal from an
    # accidental crash, and a mutation test proved exactly that: deleting the guard
    # left this test green. What the guard actually buys is a DIAGNOSABLE answer.
    p = ask(rt, 1, "player")
    assert p.status == "ERR"
    assert "ffi cdef block" in p.payload, f"undiagnosable failure: {p.payload}"

    s = ask(rt, 2, "stations", "argon")
    assert s.status == "ERR"
    assert "ffi cdef block" in s.payload, f"undiagnosable failure: {s.payload}"

    assert ask(rt, 3, "ping").status == "OK", "a non-ffi verb broke when ffi was absent"


def test_a_capped_FILTERED_list_separates_the_two_narrowings(lua_factory):
    """The defect the first in-game run exposed. TWO steps narrow the result here --
    the sector filter and the reply cap -- and the original header reported one number
    for both, so `shown=215 of 1785` could not distinguish "215 matched your filter"
    from "more matched and the cap ate some". A reader had no way to know rows were
    missing, which is the un-announced narrowing this workspace exists to refuse.

    Everything matches the filter here, so any shortfall is the cap and only the cap.
    """
    rt = live(n_stations=4000)
    rt.execute('_G.component_data = {sectorid = "ID: 1", classid = "station", realclassid = "station"}')
    r = ask(rt, 1, "stations", "argon", "ID: 1", "--wide")
    h = r.fields[0]

    matched = int(h.split("matched=")[1].split(" ")[0])
    shown = int(h.split("shown=")[1].split(" ")[0])
    omitted = int(h.split("omitted=")[1].split(" ")[0])

    assert matched == 4000, f"matched must count EVERY filter hit, capped or not: {h}"
    assert shown < matched, "nothing was capped, so this proves nothing about capping"
    assert "CAPPED=yes" in h, h
    assert omitted == matched - shown, f"omitted disagrees with shown/matched: {h}"
    assert shown == len(r.fields) - 1, "header count disagrees with the rows sent"


def test_an_UNCAPPED_list_says_CAPPED_no_explicitly(lua_factory):
    """Falsification twin. The flag must distinguish, not merely be present -- a
    header that always said CAPPED=yes would pass the test above."""
    rt = live(n_stations=3)
    h = ask(rt, 1, "stations", "argon").fields[0]
    assert "CAPPED=no" in h, h
    assert "omitted=" not in h, f"claimed omissions on an uncapped list: {h}"


# --------------------------------------------------------------------------- #
# the BUILD fingerprint -- "is the GAME running the file on disk?"
# --------------------------------------------------------------------------- #

def test_the_BUILD_constant_matches_the_file():
    """Keeps the stamp honest. Editing the lua and forgetting to re-stamp would make
    the probe report a build that no longer describes the code -- worse than no
    fingerprint, because it would be believed.

    This is the mechanised half of a lesson that cost two cycles in one session: a
    deployed file is not a loaded file, and a staleness check that keys on ONE new
    field only proves 'not the build before last'. A content hash cannot fail that
    way, because it moves for changes nobody enumerated.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "stamp", pathlib.Path(__file__).resolve().parents[1] / "scripts/stamp-mod-build.py")
    stamp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stamp)

    p = stamp.mod_lua()
    if p is None:
        pytest.skip("game-side mod not present in dev/")
    text = p.read_text(encoding="utf-8")
    cur, exp = stamp.current(text), stamp.expected(text)
    assert cur is not None, "the mod lost its BUILD line"
    assert cur == exp, (
        f"BUILD is stale: stamped {cur}, content hashes to {exp}. "
        f"Run: uv run python scripts/stamp-mod-build.py")


def test_the_probe_REPORTS_the_build(lua_factory):
    """The fingerprint is only useful if it crosses the wire."""
    from x4validate import _livepipe as lp

    rt = live()
    rr = ask(rt, 1, "probe")
    builds = [f.split("=", 1)[1] for f in rr.fields if f.startswith("build=")]
    assert builds and len(builds[0]) == 8, f"no usable build= field: {rr.payload[:200]}"


def test_a_save_load_CLEARS_the_id_allowlist(lua_factory):
    """Ids do not survive a save load, and neither may the allowlist. IsValidComponent
    catches a DESTROYED object, but not a REUSED handle -- and a reused handle would
    return another object's data under the id you asked about, which is a wrong answer
    wearing the grammar of a right one."""
    rt = live()
    p = ask(rt, 1, "player")
    sid = [f.split("=", 1)[1] for f in p.fields if f.startswith("occupiedship=")][0]
    assert ask(rt, 2, "component", sid).status == "OK", "id was not usable to begin with"

    # Fire the same MD signal md/lua_loader.xml raises on game start AND game load.
    #
    # ⚠ CAVEAT ADDED 2026-08-29, and it is the point of the tests below. This test is
    # GREEN and the mechanism it exercises HAS NEVER RUN IN THE GAME: measured across a
    # game start and a save load, the hook's log line appears 0 times. It cannot fire --
    # it subscribes from inside Init, and Init is itself driven by that signal. So this
    # asserts "the callback does the right thing IF called", which is true and was read
    # for weeks as "ids are cleared on save load". They ARE, but by chunk re-creation
    # instead. A test can be correct and still license a false belief about production.
    rt.execute('_G.__fire_game_load()')

    r = ask(rt, 3, "component", sid)
    assert r.status == "ERR" and "not issued by this session" in r.payload, (
        f"a pre-load id survived the save load: {r.status} {r.payload[:120]}")


# --------------------------------------------------------------------------- #
# UI RELOAD -- alt-enter and save load both re-execute this chunk
# --------------------------------------------------------------------------- #

def test_a_ui_reload_EMPTIES_the_id_allowlist():
    """CONFIRMED IN GAME 2026-08-29, twice, each time with a control that passed first.

    A reload builds a FRESH chunk, so `issued_ids` starts empty and an id accepted
    seconds earlier is refused. For a save load that is REQUIRED (a reused handle would
    return another object's data under the id you asked about). For an alt-enter it is
    merely surprising. This pins the behaviour -- it is the real clearing mechanism,
    not the dead hook above.
    """
    rt = live()
    p = ask(rt, 1, "player")
    ident = [f.split("=", 1)[1] for f in p.fields if f.startswith("occupiedship=")][0]
    # CONTROL: it must resolve BEFORE the reload, or the assertion after proves nothing.
    assert ask(rt, 2, "component", ident).status == "OK", "id was not usable to begin with"

    reload_ui(rt)

    r = ask(rt, 3, "component", ident)
    assert r.status == "ERR", "the allowlist survived a reload; ids would outlive a save"
    assert "not issued by this session" in r.payload


def test_the_refusal_after_a_reload_NAMES_the_reload():
    """Two very different causes produce one refusal. Until the message distinguished
    them, 'the UI reloaded' looked exactly like 'you typed a bad id' -- so the refusal
    blamed the caller for something the engine had done."""
    rt = live()
    ask(rt, 1, "player")            # seed the allowlist, so emptiness means the reload
    reload_ui(rt)
    r = ask(rt, 2, "component", "1234ULL")
    assert r.status == "ERR"
    low = r.payload.lower()
    assert "reload" in low, f"the refusal does not mention a reload: {r.payload[:160]}"
    assert "alt-enter" in low and "save" in low, (
        f"the refusal does not name the two actions that cause one: {r.payload[:160]}")


def test_a_BOGUS_id_does_not_blame_a_reload_when_ids_ARE_issued():
    """The twin of the test above, and it targets the OTHER branch. Without it the
    message could hard-code the reload wording and both tests would still pass, which
    would make the diagnosis useless exactly when it matters."""
    rt = live()
    ask(rt, 1, "player")
    r = ask(rt, 2, "component", "1234ULL")
    assert r.status == "ERR"
    low = r.payload.lower()
    assert "mistyped" in low, f"a bogus id was not diagnosed as one: {r.payload[:160]}"


def test_probe_reports_loaded_at_and_build_CANNOT_detect_a_reload():
    """`build=` answers 'is the game running the file on disk'. It CANNOT answer 'has
    the chunk been re-executed', because a reload runs the SAME file -- which is why
    loaded_at is reported beside it.

    The `_G.now` change models a MEASURED fact: getElapsedTime() RESETS with the UI
    (0.89 then 0.82 across reloads that debug.txt timestamped 254.56 and 425.42). So
    loaded_at is a CHANGE detector, not a time.
    """
    rt = live()
    before = probe_fields(rt, 1)
    assert before["loaded_at"] == "100.00", before
    assert before["load_hook_fired"] == "false", before

    rt.execute("_G.now = 0.82")
    reload_ui(rt)
    after = probe_fields(rt, 2)

    assert after["loaded_at"] == "0.82", "loaded_at did not follow the new chunk"
    assert after["build"] == before["build"], (
        "build changed across a reload; then this test is measuring the wrong thing")


def test_probe_does_NOT_claim_a_reload_COUNTER():
    """It briefly did, and the counter could not work.

    MEASURED IN GAME 2026-08-29: `_G` does not survive a UI reload -- the engine
    rebuilds the whole lua environment -- so a global counter read 1, then 1, across
    two real reloads. Only its "no reload happened" branch was ever reachable, which
    is an instrument whose failure branch does not exist.

    Pinned so nobody reintroduces it, and so the reasoning survives with the decision:
    the same fact is why the allowlist could NOT have been persisted across reloads
    even if we had wanted to.
    """
    rt = live()
    assert "incarnation" not in probe_fields(rt, 1)


def test_the_dead_load_hook_is_INSTRUMENTED_so_its_deadness_stays_visible():
    """MEASURED IN GAME: the hook has never fired. Kept as defence in depth, but now
    reported, because 'RegisterEvent is present' was read as 'the handler runs' -- a
    symbol existing says nothing about a callback executing.

    Asserting BOTH states matters: a field hard-coded to "false" would look identical
    in game and would be worthless the day the hook came alive.
    """
    rt = live()
    assert probe_fields(rt, 1)["load_hook_fired"] == "false"
    fired = g(rt, "__fire_game_load")()
    assert fired >= 1, "the hook is not registered at all; the probe field would be a lie"
    assert probe_fields(rt, 2)["load_hook_fired"] == "true"


def test_the_container_probe_makes_a_LIVE_CALL_and_can_DISCRIMINATE():
    """Probe before building. A symbol's TYPE says nothing about whether a given
    ARGUMENT SHAPE works, and that is the open question for a cross-faction `objects`:
    0 of 6 vanilla call sites pass a SECTOR as the container.

    ⚠ The owner must be a FACTION THAT SPANS SECTORS. The first version asked about the
    player and reported `table:1` for both calls in game -- because the player owns one
    ship, so "filtered correctly" and "ignored the container" are the SAME OUTPUT. A
    probe whose two branches cannot produce different answers cannot answer its own
    question, and this test exists to keep that fix from being undone.
    """
    rt = _build()
    rt.execute(FAKE_C)
    rt.execute('_G.component_data = {sectorid = "ID: 7479"}')
    rt.execute("""
        _G.seen = {}
        function GetContainedObjectsByOwner(owner, container)
            _G.seen[#_G.seen+1] = tostring(owner) .. "/" .. tostring(container)
            if container == nil then return {1, 2, 3, 4, 5} end
            return {1, 2}
        end
    """)
    init(rt)
    f = probe_fields(rt, 1)
    assert f["contained_all_argon"] == "table:5", f
    assert f["contained_in_my_sector"] == "table:2", f
    seen = list(g(rt, "seen").values())
    assert any(s.endswith("/nil") for s in seen), "the owner-only call was never made"
    assert any(not s.endswith("/nil") for s in seen), "the sector call was never made"
    assert all(s.startswith("argon/") for s in seen), (
        "the probe asked about the player again; with one owned object both calls "
        f"return table:1 and the result proves nothing: {seen}")


def test_probe_still_reports_the_objects_verb_CANDIDATE_SYMBOLS():
    """If a symbol silently drops out of PROBE_SYMBOLS we lose the one cheap way to
    find out whether the design is even possible, and would discover it from a broken
    verb in game instead."""
    rt = live()
    f = probe_fields(rt, 1)
    for name in ("GetContainedObjectsByOwner", "GetNumAllFactions", "GetAllFactions"):
        assert name in f, f"probe stopped reporting {name}"


# --------------------------------------------------------------------------- #
# STEP-0 -- the containerprobe instrument
# --------------------------------------------------------------------------- #
#
# WHAT THESE CAN AND CANNOT PROVE, said out loud so a green here is not misread as an
# answer to the engine question. They assert the probe's STRUCTURE: that it refuses
# cleanly, never raises, keeps the two container forms as SEPARATE numbers, walks the
# list it was handed, and computes its verdicts rather than hard-coding them. They do
# NOT assert the engine's answers -- the fake is not the engine, and the wire-form
# round trip comes back NON-identical here by construction. Only the running game
# settles Q1/Q2/Q3; these keep the instrument honest until it gets there.

#: A REAL sector token shape. `player` reports `ID: 7479`, and both container
#: conversions accept it -- ConvertStringToLuaID wraps it, ConvertStringTo64Bit parses
#: the number out. A made-up token like "SECTOR1" converts to nil on the 64-bit path,
#: which silently collapses the two forms this test exists to tell apart.
SECT = '{sectorid = "ID: 7479"}'


def cprobe(rt, seq=1, *args):
    r = ask(rt, seq, "containerprobe", *args)
    assert r.status == "OK", r.payload
    return dict(f.split("=", 1) for f in r.fields if "=" in f)


def test_containerprobe_REFUSES_when_the_primitive_is_ABSENT():
    """An absent primitive must be an ERR naming the symbol, not a raise and not a
    reply full of blanks that reads like an answer."""
    rt = live()
    rt.execute("GetContainedObjectsByOwner = nil")
    r = ask(rt, 1, "containerprobe")
    assert r.status == "ERR"
    assert "GetContainedObjectsByOwner" in r.payload


def test_containerprobe_reports_BOTH_container_forms_SEPARATELY():
    """Q2's whole point. Agreement settles which idiom to copy; a DISAGREEMENT is the
    more valuable finding. A single merged number could express neither, so the three
    populations here are deliberately all different sizes -- 3 / 2 / 1 -- and no two
    can be confused for each other."""
    rt = live(component_data=SECT, contained=(
        '{["argon|luaid:ID: 7479"] = {"A", "B"},'
        ' ["argon|7479"] = {"A"},'
        ' argon = {"A", "B", "C"}}'))
    f = cprobe(rt)
    assert f["n.owner_only"] == "3"
    assert f["n.sector_via_luaid"] == "2"
    assert f["n.sector_via_64bit"] == "1"
    # And it must SAY which list the rest of the reply describes, because that cannot
    # be inferred from the counts.
    assert f["used_handle"] == "luaid"


def test_containerprobe_REPORTS_every_missing_symbol_rather_than_RAISING():
    """A probe that can raise is not a probe. Every optional symbol is removed at once
    -- the reply must still arrive, with each loss named in its own field."""
    rt = live(component_data=SECT, contained='{argon = {"A"}}')
    rt.execute("ConvertIDTo64Bit = nil ; GetContainedStationsByOwner = nil ; "
               "IsComponentClass = nil ; Helper.isComponentClass = nil")
    f = cprobe(rt)
    assert f["class.stations_engine_control"] == "<symbol absent>"
    assert f["wire.via_ConvertIDTo64Bit"].startswith("raised:")
    assert f["class.helper_usable"] == "false"
    assert f["class.bare_usable"] == "false"


def test_containerprobe_counts_classes_TWO_WAYS_and_against_an_ENGINE_CONTROL():
    """Q3. Three independent readings of the same question -- Helper.isComponentClass
    over classid/realclassid, bare IsComponentClass over the handle, and
    GetContainedStationsByOwner asking the engine directly. Agreement is the evidence;
    one number alone would be an assertion."""
    rt = live(
        component_data=SECT,
        contained='{["argon|luaid:ID: 7479"] = {"A", "B", "C"}}',
        class_by_field=('{["classid-of-A"] = "ship", ["classid-of-B"] = "ship",'
                        ' ["realclassid-of-C"] = "station"}'),
        obj_class='{A = "ship", B = "ship", C = "station"}',
        contained_stations='{argon = {"C"}}',
    )
    f = cprobe(rt)
    assert f["class.rows_walked"] == "3"
    assert f["class.ships_helper"] == "2" and f["class.ships_bare"] == "2"
    assert f["class.stations_helper"] == "1" and f["class.stations_bare"] == "1"
    assert f["class.stations_engine_control"] == "1"


def test_the_wire_roundtrip_verdict_CAN_go_BOTH_ways():
    """A verdict field that always reads the same is decoration, not an instrument.

    Both branches are reached. With the faithful fake -- where the bare globals return
    lua numbers, as MEASURED in game -- the round trip agrees, which is the answer the
    real engine also gave. So the falsifying half plants a conversion that DISAGREES,
    proving the field is computed rather than constant. Which value the engine produces
    is not knowable here; that it can render either is."""
    plant = '{["argon|luaid:ID: 7479"] = {"A"}}'
    rt = live(component_data=SECT, contained=plant)
    assert cprobe(rt)["wire.roundtrip_identical"] == "true"

    rt2 = live(component_data=SECT, contained=plant)
    # A conversion that does NOT round-trip: the verdict must notice.
    rt2.execute("function ConvertStringTo64Bit(s) return tostring(s) .. 'X' end")
    assert cprobe(rt2)["wire.roundtrip_identical"] == "false"


def test_an_EMPTY_sector_SAYS_SO_rather_than_omitting_the_wire_fields():
    """Nothing-to-look-at and could-not-look must not render alike. A dropped field
    would read as a non-answer; this makes the absence explicit and says what to do."""
    rt = live(component_data=SECT, contained='{}')
    f = cprobe(rt)
    assert "wire" in f
    assert "no objects here" in f["wire"]


def test_containerprobe_reports_whether_the_FACTION_LIST_is_reachable():
    """Q5. `objects` with no faction argument is built entirely on this pair, so an
    unexported symbol changes the design rather than merely degrading a field. Both
    branches are reached: exported, and deleted from the fake C table (which raises on
    lookup, as real ffi does)."""
    rt = live(component_data=SECT, contained='{}', n_factions=7)
    f = cprobe(rt)
    assert f["C.GetNumAllFactions"] == "function"
    assert f["n.factions"] == "7"

    rt2 = live(component_data=SECT, contained='{}')
    rt2.execute("_G.fake_C.GetNumAllFactions = nil")
    f2 = cprobe(rt2, 2)
    assert f2["C.GetNumAllFactions"] == "<not exported>"
    assert f2["n.factions"].startswith("raised:")


def test_a_faction_call_that_SUCCEEDS_but_yields_nil_does_NOT_blame_a_raise():
    """Three outcomes, three distinct reports. The `okn and nfac or "raised:"` idiom
    collapses the middle one into the third, so a call that worked and returned
    something unusable would be reported as an error that never happened -- a
    diagnostic misattributing its own failure, which is worse than no diagnostic.

    This branch was found UNASSERTED by a mutation probe, which had appeared to kill
    the mutant only because every edit to the mod file also fails the BUILD-fingerprint
    test. That is an adjacent question, not this one."""
    rt = live(component_data=SECT, contained='{}')
    rt.execute('_G.fake_C.GetNumAllFactions = function() return "not-a-number" end')
    f = cprobe(rt)
    assert f["n.factions"] == "<call ok but not a number>"
    assert "raised" not in f["n.factions"]


# --------------------------------------------------------------------------- #
# `objects` -- the container primitive, the flag columns, and the id wire form
# --------------------------------------------------------------------------- #
#
# WHAT THESE PROVE, and what they cannot. They pin the GUARDS: one id form per object,
# every narrowing announced, both paths reachable, and vanilla's validity predicate
# ported clause for clause. They do NOT prove what the engine returns -- the fake is
# not the engine. The in-game `compare` run is what settles method equivalence.

#: A realistic sector token. `player` reports exactly this shape, and BOTH container
#: conversions accept it: ConvertStringToLuaID wraps it, ConvertStringTo64Bit parses
#: the number out of it.
TOKEN = "ID: 7479"
LUAKEY = "argon|luaid:ID: 7479"


def objects_reply(rt, seq, *args):
    r = ask(rt, seq, "objects", *args)
    assert r.status == "OK", r.payload[:250]
    return r


def hdr(r):
    return dict(kv.split("=", 1) for kv in r.fields[0].split(" ") if "=" in kv)


# --- the id wire form -------------------------------------------------------- #

def test_wire_gives_ONE_string_for_every_shape_of_the_SAME_id(lua_factory):
    """The contract the whole migration rests on. The ffi entry points hand back cdata
    that stringifies `1046331ULL`; the bare globals hand back a lua NUMBER that
    stringifies `1046331`. Same id, two strings -- so without one choke point the same
    object gets two ids, dedupe breaks, and any set comparison between the two
    enumeration paths is meaningless."""
    rt = _build(extra="function _T_wire(v) return wire(v) end")
    rt.execute(FAKE_C)
    init(rt)
    w = g(rt, "_T_wire")
    forms = [w("1046331ULL"), w(1046331), w("1046331"), w("ID: 1046331")]
    assert len(set(forms)) == 1, f"one object rendered as several ids: {forms}"
    assert forms[0] == "1046331ULL", forms[0]


def test_wire_REFUSES_an_id_at_or_above_2_pow_53(lua_factory):
    """The bare globals return lua numbers, which are doubles: above 2^53 a double can
    no longer hold every distinct uint64, so ids would silently collide. The rule was
    written in a comment for months; this is the check that ENFORCES it."""
    rt = _build(extra="function _T_wire(v) return pcall(wire, v) end")
    rt.execute(FAKE_C)
    init(rt)
    w = g(rt, "_T_wire")
    ok_lo, val = w(2 ** 53 - 1)
    assert ok_lo is True, f"a representable id must still be accepted: {val}"
    assert val == "9007199254740991ULL", val
    ok_hi, err = w(2 ** 53)
    assert ok_hi is False, "an id at 2^53 must be refused, not silently truncated"
    assert "2^53" in str(err), err


def test_a_SECTOR_TOKEN_is_NOT_canonicalised_into_an_id(lua_factory):
    """Sector tokens are a DIFFERENT KIND. `player` hands out `ID: 7479` and every
    sector-scoped verb takes it back verbatim; running it through `wire` would rewrite
    the token and silently break every sector query."""
    rt = live(component_data='{sectorid = "ID: 7479"}')
    p = ask(rt, 1, "player")
    assert any(f == "sectorid=ID: 7479" for f in p.fields), p.payload
    # It is allowlisted in its OWN form, so it can be inspected like anything else.
    r = ask(rt, 2, "component", "ID: 7479", "name")
    assert r.status == "OK", r.payload


# --- the container path, and both paths being reachable ---------------------- #

def test_objects_uses_the_CONTAINER_and_says_which_path_ran(lua_factory):
    rt = live(n_factions=1, fake_factions='{"argon"}',
              component_data='{classid = "ship", realclassid = "ship"}',
              contained='{["' + LUAKEY + '"] = {"A", "B", "C"}}')
    r = objects_reply(rt, 1, TOKEN)
    h = hdr(r)
    assert h["path"] == "container", h
    assert h["enumerated"] == "3" and h["matched"] == "3" and h["shown"] == "3", h
    assert len(r.fields) - 1 == 3


def test_objects_and_wide_are_BOTH_reachable_and_DISTINGUISHABLE(lua_factory):
    """--wide is retained as an explicit opt-in, never an automatic fallback: an empty
    sector and a failed call must not render alike. Both populations are planted at
    DIFFERENT sizes so neither can be mistaken for the other."""
    rt = live(n_stations=4, n_ships=0,
              component_data='{classid = "station", realclassid = "station", sectorid = "' + TOKEN + '"}',
              contained='{["' + LUAKEY + '"] = {"A", "B"}}')
    c = objects_reply(rt, 1, TOKEN, "station", "argon")
    w = objects_reply(rt, 2, TOKEN, "station", "argon", "--wide")
    assert hdr(c)["path"] == "container" and hdr(c)["enumerated"] == "2", hdr(c)
    assert hdr(w)["path"] == "wide" and hdr(w)["enumerated"] == "4", hdr(w)
    # `enumerated` alone is NOT enough: it counts handles the primitive returned and is
    # unaffected by whether we could read any of them. MEASURED in game -- the wide path
    # reported enumerated=1539 with unclassified=1539, every object unreadable, because
    # GetComponentData was handed a raw UniverseID cdata instead of a converted id.
    # Assert the objects were actually READ.
    assert hdr(w)["matched"] == "4", f"wide enumerated but read nothing: {hdr(w)}"
    assert "unclassified" not in hdr(w), f"wide could not classify its own rows: {hdr(w)}"
    assert hdr(c)["matched"] == "2", hdr(c)


def test_wide_without_a_faction_is_REFUSED_not_silently_empty(lua_factory):
    """The old walk has no all-factions form. Returning an empty list would be a
    silent narrowing; the refusal names the reason and what to do."""
    rt = live()
    r = ask(rt, 1, "objects", TOKEN, "all", "--wide")
    assert r.status == "ERR"
    assert "faction" in r.payload.lower(), r.payload


def test_an_EMPTY_sector_is_OK_with_zeros_never_ABSENT(lua_factory):
    """We asked and the answer is none. ABSENT would mean we could not ask."""
    # A faction IS asked -- otherwise this would pass vacuously, proving only that we
    # enumerated nobody rather than that an empty sector answers cleanly.
    rt = live(n_factions=1, fake_factions='{"argon"}', contained="{}")
    r = objects_reply(rt, 1, TOKEN)
    h = hdr(r)
    assert h["shown"] == "0" and h["matched"] == "0" and h["enumerated"] == "0", h
    assert h["CAPPED"] == "no"


# --- class filtering, and the objects that are NEITHER ----------------------- #

def test_class_filter_keeps_ships_stations_and_NEITHER_visible_under_all(lua_factory):
    """MEASURED in game: an in-sector argon list is 205 ships + 15 stations + 23
    objects that are neither (drones, deployables, lockboxes). `all` must show them and
    every row must carry its class, or those 23 are a silent remainder."""
    rt = live(
        n_factions=1, fake_factions='{"argon"}',
        contained='{["' + LUAKEY + '"] = {"A", "B", "C"}}',
        # TWO ships and ONE station, deliberately unequal: with 1 and 1 a filter that
        # confused the two classes would produce the SAME count and the test could not
        # tell. That is the shape the and/or fall-through bug hid in.
        class_by_field=('{["classid-of-A"] = "ship", ["classid-of-B"] = "ship",'
                        ' ["realclassid-of-C"] = "station"}'),
    )
    assert hdr(objects_reply(rt, 1, TOKEN, "ship"))["matched"] == "2"
    assert hdr(objects_reply(rt, 2, TOKEN, "station"))["matched"] == "1"
    assert hdr(objects_reply(rt, 3, TOKEN, "all"))["matched"] == "3"


def test_an_UNKNOWN_class_is_REFUSED_rather_than_treated_as_all(lua_factory):
    rt = live(contained='{["' + LUAKEY + '"] = {"A"}}')
    r = ask(rt, 1, "objects", TOKEN, "shp")
    assert r.status == "ERR"
    assert "ship, station or all" in r.payload, r.payload


# --- the faction axis -------------------------------------------------------- #

def test_no_faction_enumerates_EVERY_faction_and_says_how_many(lua_factory):
    rt = live(n_factions=3,
              fake_factions='{"argon", "teladi", "paranid"}',
              contained='{["argon|luaid:' + TOKEN + '"] = {"A"},'
                        ' ["teladi|luaid:' + TOKEN + '"] = {"B"},'
                        ' ["paranid|luaid:' + TOKEN + '"] = {"C"}}')
    h = hdr(objects_reply(rt, 1, TOKEN))
    assert h["factions"] == "3", h
    assert h["enumerated"] == "3", h


def test_hidden_CHANGES_the_faction_scope_and_the_header_says_so(lua_factory):
    """civilian (mass traffic) and criminal carry tags="hidden" in factions.xml, so
    GetAllFactions(false) omits them. Default excludes; --hidden widens; and the scope
    is stated either way so a narrower answer is never silent."""
    rt = live(n_factions=1, n_factions_hidden=2,
              fake_factions='{"argon", "civilian"}',
              contained='{["argon|luaid:' + TOKEN + '"] = {"A"},'
                        ' ["civilian|luaid:' + TOKEN + '"] = {"B", "C"}}')
    plain = hdr(objects_reply(rt, 1, TOKEN))
    wide = hdr(objects_reply(rt, 2, TOKEN, "all", "--hidden"))
    assert plain["hidden"] == "no" and plain["factions"] == "1", plain
    assert wide["hidden"] == "yes" and wide["factions"] == "2", wide
    assert int(wide["enumerated"]) > int(plain["enumerated"]), (plain, wide)


def test_a_faction_whose_call_FAILS_is_NAMED_not_absorbed(lua_factory):
    """One faction the engine dislikes must not quietly cost us the others. A smaller
    number with no explanation is the narrowing-without-announcement defect."""
    rt = live(n_factions=2, fake_factions='{"argon", "boom"}',
              contained='{["argon|luaid:' + TOKEN + '"] = {"A"}}')
    rt.execute("""
        local real = GetContainedObjectsByOwner
        function GetContainedObjectsByOwner(owner, container)
            if owner == "boom" then error("engine said no") end
            return real(owner, container)
        end
    """)
    r = objects_reply(rt, 1, TOKEN)
    assert "factions_failed=1(boom)" in r.fields[0], r.fields[0]


# --- vanilla's validity predicate: one twin per clause ----------------------- #

def _valid_rt(lua_factory, **flags):
    """One object, all flags true-by-default for a VALID ship, overridden per test."""
    base = {"classid": "ship", "realclassid": "ship", "isknown": "true",
            "isradarvisible": "true", "iswreck": "false", "isunit": "false",
            "isdeployable": "false", "isorphaned": "false",
            "isattachedaslimpet": "false", "ismasstraffic": "false",
            "isenemy": "false", "isdocked": "false"}
    base.update(flags)
    body = ", ".join(
        f'{k} = {v}' if v in ("true", "false") else f'{k} = "{v}"'
        for k, v in base.items())
    return live(n_factions=1, fake_factions='{"argon"}',
                component_data="{" + body + "}",
                contained='{["' + LUAKEY + '"] = {"A"}}')


def test_isObjectValid_ACCEPTS_a_plain_known_ship(lua_factory):
    """The control. Without this, every rejection test below could be passing because
    the predicate rejects everything."""
    assert hdr(objects_reply(_valid_rt(lua_factory), 1, TOKEN))["valid"] == "1"


@pytest.mark.parametrize("clause,flags", [
    ("not a listed class", {"classid": "asteroid", "realclassid": "asteroid"}),
    ("a unit",             {"isunit": "true"}),
    ("not known",          {"isknown": "false"}),
    ("not radar visible",  {"isradarvisible": "false"}),
    ("a limpet",           {"isattachedaslimpet": "true"}),
    ("a station wreck",    {"classid": "station", "realclassid": "station", "iswreck": "true"}),
    ("non-enemy traffic",  {"ismasstraffic": "true", "isenemy": "false"}),
])
def test_isObjectValid_REJECTS_each_clause_SEPARATELY(lua_factory, clause, flags):
    """SEVEN twins for seven clauses. A single twin against a compound condition only
    ever tests the FIRST clause it trips -- every guard behind it is shadowed and never
    evaluated. Each case here differs from the accepted control by ONE predicate.

    The predicate is menu_map.lua:7548-7564 plus the mass-traffic drop at :7419,
    COPIED. An earlier version of this design composed a two-field class test from the
    schema and missed five of these."""
    h = hdr(objects_reply(_valid_rt(lua_factory, **flags), 1, TOKEN))
    assert h["valid"] == "0", f"{clause} should not be valid: {h}"
    # Still LISTED -- rejection is a column, not a filter. The engine returns ids and
    # positions for these and the research use case needs them.
    assert h["matched"] != "0", f"{clause} was dropped from the list, not just marked"


def test_an_UNDECIDABLE_validity_is_reported_SEPARATELY_from_false(lua_factory):
    """`nil` is not `false`. If Helper is missing we cannot tell, and "could not tell"
    must never render as "no" -- that is a narrowing wearing the grammar of an answer."""
    rt = _valid_rt(lua_factory)
    rt.execute("Helper.isComponentClass = nil")
    h = hdr(objects_reply(rt, 1, TOKEN))
    assert h["valid"] == "0", h
    assert h.get("undecided") == "1", f"an undecidable verdict was reported as false: {h}"


def test_the_flag_column_reports_each_flag_and_the_verdict(lua_factory):
    rt = _valid_rt(lua_factory, isdocked="true", isknown="true")
    r = objects_reply(rt, 1, TOKEN)
    flags = r.fields[1].split("|")[-1]
    assert flags[0] == "k", f"known not reported: {flags}"
    assert flags[1] == "d", f"docked not reported: {flags}"
    assert flags[-1] == "v", f"validity verdict not reported: {flags}"


# --- compare: the atomic proof ---------------------------------------------- #

def test_compare_runs_BOTH_paths_in_ONE_call_and_diffs_them(lua_factory):
    """MEASURED in game: argon gained 86 objects in about five minutes. Two separate
    queries therefore differ by drift, which cannot be told apart from a real method
    difference -- so the comparison only means anything inside one call."""
    rt = live(n_stations=0, n_ships=3,
              component_data='{classid = "ship", realclassid = "ship", sectorid = "' + TOKEN + '"}',
              fake_ids='{"1ULL", "2ULL", "3ULL"}',
              contained='{["' + LUAKEY + '"] = {"ID: 1", "ID: 2"}}')
    r = ask(rt, 1, "compare", "argon", TOKEN)
    assert r.status == "OK", r.payload[:250]
    h = hdr(r)
    assert h["old"] == "3" and h["new"] == "2", h
    assert h["both"] == "2" and h["old_only"] == "1" and h["new_only"] == "0", h
    assert any(f.startswith("old_only=3ULL") for f in r.fields), r.fields


def test_compare_renders_ONE_object_through_BOTH_id_paths(lua_factory):
    """This is the measurement that settles the wire-form question. Up to here it was
    inferred from two DIFFERENT objects, which is not evidence about either."""
    rt = live(n_stations=0, n_ships=1,
              component_data='{classid = "ship", realclassid = "ship", sectorid = "' + TOKEN + '"}',
              fake_ids='{"7ULL"}',
              contained='{["' + LUAKEY + '"] = {"ID: 7"}}')
    r = ask(rt, 1, "compare", "argon", TOKEN)
    assert r.status == "OK", r.payload[:250]
    verdict = [f for f in r.fields if f.startswith("wire_same_object=")][0]
    assert "DIFFERS" in verdict, (
        "the ffi form is 7ULL and the bare form is 7; the verdict must SAY they differ "
        f"rather than hiding it behind the canonicaliser: {verdict}")


def test_compare_says_so_when_NO_object_is_in_both_sets(lua_factory):
    """A verdict computed from an empty intersection would be a fabrication."""
    rt = live(n_stations=0, n_ships=0, contained="{}")
    r = ask(rt, 1, "compare", "argon", TOKEN)
    assert r.status == "OK", r.payload[:250]
    assert any("wire_same_object=<no object in both sets>" in f for f in r.fields), r.fields


def test_the_header_is_PARSEABLE_as_key_value_pairs(lua_factory):
    """The header is space-delimited `key=value`, and a SECTOR TOKEN CONTAINS A SPACE:
    the engine writes sectorid as `ID: 7479`. Emitting it raw produced
    `sector=ID: 7479`, which any consumer splitting on whitespace reads as `sector=ID:`
    plus a stray `7479` -- a corrupt field and a phantom one, from a value that looked
    fine to the eye.

    Nothing asserted the header was parseable at all, so the bug was invisible to the
    suite even after it was fixed: the helper that parses headers just skipped the
    malformed token. This is the assertion that can actually go red."""
    rt = live(n_factions=1, fake_factions='{"argon"}',
              component_data='{classid = "ship", realclassid = "ship"}',
              contained='{["' + LUAKEY + '"] = {"A"}}')
    header = objects_reply(rt, 1, TOKEN).fields[0]
    for token in header.split(" "):
        if token.startswith("(") or token.endswith(")") or "=" not in token:
            # the CAPPED= explanation is deliberately prose, in parentheses
            continue
    tokens = header.split(" ")
    cut = tokens.index("CAPPED=no") if "CAPPED=no" in tokens else len(tokens)
    for token in tokens[:cut]:
        assert "=" in token, (
            f"header token {token!r} has no '=', so a key=value parse breaks: {header}")
    parsed = dict(t.split("=", 1) for t in tokens[:cut])
    assert parsed["sector"] == "ID:7479", (
        f"the sector token must survive into the header without a space: {header}")
    assert parsed["path"] == "container", header


def test_an_UNCLASSIFIABLE_object_is_COUNTED_not_silently_dropped(lua_factory):
    """FOUND IN GAME 2026-08-30, and it would have shipped. Some objects in the
    galaxy-wide faction list have NO class data, and `Helper.isComponentClass` is
    `lookup[class1 * 1000 + ...]` (helper.lua:782) -- so a nil classid is arithmetic on
    nil and RAISES. `compare` and `objects --wide` both died on the first one; the
    container path never hit it, which is exactly why the old path had to stay
    reachable and be exercised.

    The fix makes classification tri-state. This pins the half that is easy to get
    wrong: an object we could not classify is NOT an object we classified as "not a
    ship", so it must be counted and announced rather than folded into the miss."""
    rt = live(n_factions=1, fake_factions='{"argon"}',
              contained='{["' + LUAKEY + '"] = {"A", "B"}}',
              nil_fields='{classid = true, realclassid = true}')
    r = objects_reply(rt, 1, TOKEN, "ship")
    h = hdr(r)
    assert h["matched"] == "0", h
    assert h.get("unclassified") == "2", (
        f"objects with no class data were dropped without being counted: {h}")


def test_a_MALFORMED_sector_token_is_REFUSED_not_silently_widened(lua_factory):
    """★ MEASURED in game 2026-08-30, and it is the most dangerous shape there is: the
    engine SILENTLY IGNORES a container it does not recognise and returns every object
    the owner has anywhere -- labelled as the sector you asked for.

        objects "ID: 514068"   -> 310 objects
        objects "ID:"          -> 1961, header still said sector=ID:
        objects "NOT_A_SECTOR" -> 1961, header still said sector=NOT_A_SECTOR

    No error, no flag, six times the data. That is the narrowing-without-announcement
    defect inverted: a step that FAILED to narrow, reporting as though it had. Sector
    tokens change every launch, so a stale one is the ordinary case."""
    rt = live(n_factions=1, fake_factions='{"argon"}',
              contained='{argon = {"A", "B", "C"}, ["' + LUAKEY + '"] = {"A"}}')
    for bad in ("ID:", "NOT_A_SECTOR", "514068", "ID 514068"):
        r = ask(rt, 1, "objects", bad, "all", "argon")
        assert r.status == "ERR", f"{bad!r} was accepted: {r.payload[:120]}"
        assert "SILENTLY IGNORED" in r.payload, r.payload
    # The two DELIBERATE galaxy forms are not tokens and must still work.
    for ok_tok in ("-", "galaxy"):
        assert ask(rt, 2, "objects", ok_tok, "all", "argon").status == "OK", ok_tok
    # And a real token still works.
    assert ask(rt, 3, "objects", TOKEN, "all", "argon").status == "OK"


def test_compare_ALSO_refuses_a_malformed_sector_token(lua_factory):
    """compare takes a sector too, and there a silently-widened container would
    manufacture a huge bogus new_only set that reads as a method difference -- the
    exact wrong conclusion the verb exists to prevent."""
    rt = live(n_factions=1, fake_factions='{"argon"}', contained="{}")
    r = ask(rt, 1, "compare", "argon", "NOT_A_SECTOR")
    assert r.status == "ERR", r.payload[:120]
    assert "SILENTLY IGNORED" in r.payload, r.payload


def test_total_COUNTS_THE_SAME_POPULATION_as_enumerated(lua_factory):
    """★ A denominator that counts a DIFFERENT population is not a denominator, it is
    another number standing next to one. MEASURED in game 2026-08-30: a class=all query
    printed `matched=1909 total=1813` -- more matches than the total -- because
    GetNumAllFaction* counts ships and stations while the container returns every class
    (drones, buildstorage, deployables).

    So a class-scoped query gets the matching count, and a mixed-class query says
    outright that it has no cheap true denominator rather than borrowing one."""
    rt = live(n_factions=1, fake_factions='{"argon"}',
              n_ships=10, n_stations=5,
              component_data='{classid = "ship", realclassid = "ship"}',
              contained='{["' + LUAKEY + '"] = {"A", "B"}}')

    ship = hdr(objects_reply(rt, 1, TOKEN, "ship", "argon"))
    assert ship["total"] == "10", f"ship total must be the SHIP count alone: {ship}"
    assert int(ship["matched"]) <= int(ship["total"]), ship

    station = hdr(objects_reply(rt, 2, TOKEN, "station", "argon"))
    assert station["total"] == "5", f"station total must be the STATION count: {station}"

    mixed = hdr(objects_reply(rt, 3, TOKEN, "all", "argon"))
    assert mixed["total"].startswith("n/a(mixed-classes)"), (
        f"a mixed-class query must NOT borrow the ship+station total: {mixed}")
    assert mixed["ships_stations"] == "15", mixed


# --- the capability harvest: `globals` and `galaxyprobe` ---------------------- #
#
# These two verbs exist to ENUMERATE the engine surface rather than guess names out of
# vanilla. Guessing can only ever confirm names somebody already thought of, so "the
# engine has no such thing" and "nobody asked" produce an identical silence.

PAD = "for i = 1, 4000 do _G['ZZPAD' .. string.rep('x', 40) .. i] = 1 end"


def test_globals_lists_names_and_types_and_NEVER_CALLS_them(lua_factory):
    """The safety property this verb lives or dies by.

    `type(v)` cannot run a function; `v()` can, and an unknown engine global may mutate
    game state. This mod is read-only BY CONTRACT, so a regression here does not make it
    buggy -- it makes it a different kind of mod. The planted global counts its own
    invocations, so the assertion can actually go red.
    """
    rt = live()
    rt.execute("_G.__called = 0\n"
               "_G.LandMine = function() _G.__called = _G.__called + 1 end")
    r = ask(rt, 1, "globals", "landmine")
    assert r.status == "OK", r.payload[:200]
    assert any(f.startswith("LandMine|function") for f in r.fields), r.fields[:8]
    assert g(rt, "__called") == 0, "the verb INVOKED a global it merely enumerated"


def test_globals_filter_is_a_SUBSTRING_not_a_prefix(lua_factory):
    """Engine names are not consistently prefixed -- GetSectors, IsValidComponent,
    ConvertStringToLuaID -- so an anchored match would hide most of what a caller is
    hunting for. The planted name does NOT start with the filter, so a prefix
    implementation fails this."""
    rt = live()
    rt.execute("_G.WeirdlyNamedSectorThing = 1")
    r = ask(rt, 1, "globals", "sector")
    assert any(f.startswith("WeirdlyNamedSectorThing|") for f in r.fields), r.fields[:8]


def test_globals_header_denominators_cannot_exceed_each_other(lua_factory):
    """shown <= matched <= enumerated, and functions <= enumerated. A narrowing step
    that reports a wider number than the population it narrowed is the defect this whole
    toolkit exists to refuse."""
    rt = live()
    r = ask(rt, 1, "globals", "-")
    h = hdr(r)
    assert int(h["shown"]) <= int(h["matched"]) <= int(h["enumerated"]), h
    assert int(h["functions"]) <= int(h["enumerated"]), h


def test_globals_PAGES_rather_than_silently_dropping(lua_factory):
    """An enumeration that does not fit must page, not truncate. The reply cap is a hard
    one: an over-long message tears the pipe down instead of arriving short."""
    rt = live()
    rt.execute(PAD)
    r = ask(rt, 1, "globals", "zzpad")
    h = hdr(r)
    assert int(h["pages"]) > 1, h
    assert int(h["matched"]) >= 4000, h
    assert int(h["shown"]) < int(h["matched"]), "one page cannot hold them all"


def test_globals_a_page_past_the_end_is_ABSENT_not_ERR(lua_factory):
    """A well-formed question with no rows behind it is an ANSWER. Rendering it as ERR
    would make "you asked for page 9" indistinguishable from "the verb broke"."""
    rt = live()
    rt.execute(PAD)
    pages = int(hdr(ask(rt, 1, "globals", "zzpad"))["pages"])
    beyond = ask(rt, 2, "globals", "zzpad", str(pages + 1))
    assert beyond.status == "ABSENT", (beyond.status, beyond.payload[:120])


def test_globals_never_exceeds_the_payload_cap(lua_factory):
    rt = live()
    rt.execute(PAD)
    for page in (1, 2):
        r = ask(rt, page, "globals", "zzpad", str(page))
        assert len(r.payload) <= 32000, (page, len(r.payload))


def test_globals_reply_is_TAB_separated_like_every_other_verb(lua_factory):
    """Reply.fields splits on TABS. Joining with a newline instead collapses the whole
    reply into ONE field -- and every caller keeps "working", reading the rows as part of
    the header. This was written wrong the first time and caught only by reading the
    convention."""
    rt = live()
    rt.execute("_G.OnlyOneMatch_zq = 1")
    r = ask(rt, 1, "globals", "onlyonematch_zq")
    assert len(r.fields) == 2, r.fields          # header + exactly one row
    assert "\n" not in r.payload, "rows were joined with a newline, not a tab"


# --- galaxyprobe -------------------------------------------------------------- #

GALAXY = """
_G.seen_cluster_args = {}
_G.seen_station_args = {}
function GetClusters(flag)
    _G.seen_cluster_args[#_G.seen_cluster_args+1] = tostring(flag)
    if flag then return {"c1", "c2"} end
    return {"c1"}
end
function GetSectors(c) return {"s1", "s2", "s3"} end
function GetContainedStations(container, flag)
    _G.seen_station_args[#_G.seen_station_args+1] = tostring(flag)
    if flag then return {"st1", "st2"} end
    return {"st1"}
end
"""


def test_galaxyprobe_asks_GetClusters_BOTH_WAYS(lua_factory):
    """The boolean is UNDOCUMENTED and all 8 vanilla call sites pass `true`. Asking one
    way and reporting the number would record a guess in the grammar of a measurement."""
    rt = live()
    rt.execute(GALAXY)
    h = hdr(ask(rt, 1, "galaxyprobe"))
    assert h["clusters.arg_true"] == "2", h
    assert h["clusters.arg_false"] == "1", h
    assert sorted(set(g(rt, "seen_cluster_args").values())) == ["false", "true"]


def test_galaxyprobe_asks_GetContainedStations_BOTH_WAYS(lua_factory):
    rt = live()
    rt.execute(GALAXY)
    h = hdr(ask(rt, 1, "galaxyprobe"))
    assert h["stations.arg_true"] == "2", h
    assert h["stations.arg_false"] == "1", h
    assert sorted(set(g(rt, "seen_station_args").values())) == ["false", "true"]


def test_galaxyprobe_isknown_buckets_SUM_to_the_sector_total(lua_factory):
    """This is the question everything turned on: is GetSectors knowledge-limited?
    Buckets that do not sum to the population cannot answer it -- a missing sector would
    be indistinguishable from an undiscovered one."""
    rt = live()
    rt.execute(GALAXY)
    rt.execute("""
        function GetComponentData(id, ...)
            local names = {...}
            local out = {}
            for i = 1, #names do
                if names[i] == "isknown" then
                    out[i] = (tostring(id) == "s1")
                else
                    out[i] = names[i] .. "-of-" .. tostring(id)
                end
            end
            local up0 = table.unpack or unpack
            return up0(out, 1, #names)
        end
    """)
    h = hdr(ask(rt, 1, "galaxyprobe"))
    total = int(h["sectors.total"])
    assert total == 6, h        # 2 clusters x 3 sectors
    got = (int(h["sectors.isknown_true"]) + int(h["sectors.isknown_false"])
           + int(h["sectors.isknown_undecidable"]))
    assert got == total, (got, total, h)
    assert int(h["sectors.isknown_true"]) == 2, h     # s1 in each of two clusters
    assert int(h["sectors.isknown_false"]) == 4, h


def test_galaxyprobe_DEGRADES_when_a_primitive_is_absent_and_does_not_raise(lua_factory):
    """Reachability from OUR chunk is unmeasured, so the verb has to survive every
    primitive being missing and SAY so, rather than raising and returning nothing. A `?`
    is a reported non-answer; a raise is a lost run."""
    rt = live()
    rt.execute("_G.GetClusters = nil\n_G.GetSectors = nil\n_G.GetContainedStations = nil")
    r = ask(rt, 1, "galaxyprobe")
    assert r.status == "OK", r.payload[:200]
    h = hdr(r)
    assert h["type.GetClusters"] == "nil", h
    assert h["clusters.arg_true"] == "?", h
    assert h["stations.arg_true"] == "?", h
    assert h["sectors.total"] == "0", h


def test_galaxyprobe_reports_the_TYPE_of_every_primitive_it_names(lua_factory):
    """A type line for a name nobody planted is what turns "we never asked" into "the
    engine does not have it"."""
    rt = live()
    rt.execute(GALAXY)
    h = hdr(ask(rt, 1, "galaxyprobe"))
    for name in ("GetClusters", "GetSectors", "GetContainedStations",
                 "GetContainedObjectsByOwner", "GetSectorsByOwner",
                 "GetContainedBuildStoragesByOwner", "GetSectorControlStation",
                 "GetComponentData", "ConvertStringToLuaID", "ConvertIDTo64Bit"):
        assert "type." + name in h, (name, sorted(h))


def test_galaxyprobe_NEVER_CALLS_a_global_it_only_reports_the_type_of(lua_factory):
    """Same contract as `globals`: the type table is a READ. GetSectorsByOwner is in the
    reported list and is never invoked by this verb."""
    rt = live()
    rt.execute(GALAXY)
    rt.execute("_G.__soc = 0\n"
               "_G.GetSectorsByOwner = function() _G.__soc = _G.__soc + 1 end")
    ask(rt, 1, "galaxyprobe")
    assert g(rt, "__soc") == 0, "galaxyprobe INVOKED GetSectorsByOwner"


def test_galaxyprobe_stays_inside_the_payload_cap_with_many_sectors(lua_factory):
    rt = live()
    rt.execute("""
        function GetClusters(f) return {"c1"} end
        function GetSectors(c)
            local t = {}
            for i = 1, 3000 do t[i] = "sector_with_a_long_name_" .. i end
            return t
        end
        function GetContainedStations(x, f) return {} end
    """)
    r = ask(rt, 1, "galaxyprobe")
    assert r.status == "OK", r.payload[:200]
    assert len(r.payload) <= 32000, len(r.payload)
    h = hdr(r)
    assert h["sectors.total"] == "3000", h
    assert int(h["sample.shown"]) < 3000, "the sample was not bounded"


def test_galaxyprobe_survives_a_primitive_that_EXISTS_but_RAISES(lua_factory):
    """The DEGRADES test above is stopped by the type-check guard and never reaches the
    pcall behind it -- a guard that fires first SHADOWS the clause behind it (CLAUDE.md
    #26), and a mutant that removed that pcall SURVIVED until this test existed. Two
    clauses, two twins.

    A primitive that exists and throws is a real case, not a contrived one: a wrong
    argument shape, or engine state the call cannot cope with.
    """
    rt = live()
    rt.execute("function GetClusters(f) error('engine says no') end")
    r = ask(rt, 1, "galaxyprobe")
    assert r.status == "OK", r.payload[:200]
    h = hdr(r)
    assert h["type.GetClusters"] == "function", h   # it EXISTS, so the type guard passes
    assert h["clusters.arg_true"] == "?", h         # the pcall is what saved the run
    assert h["sectors.total"] == "0", h


def test_recon_ONLY_calls_names_from_its_HARDCODED_lists(lua_factory):
    """The safety property that lets `recon` exist at all.

    Every other verb refuses to call what it finds. This one calls, so the set of names it
    may touch must be fixed in the SOURCE, never supplied by the caller -- otherwise it is
    an arbitrary-execution primitive wearing a read-only label.

    THE FIRST VERSION OF THIS TEST WAS VACUOUS AND PASSED. lupa's _G contains none of the
    recon names, so every probe returned ABSENT (ok=0, absent=73), nothing was ever
    called, and "no stray calls" was true by construction -- a green that could not have
    gone red (CLAUDE.md #26). The fixture now PLANTS the real names as functions so the
    calls actually happen, and plants a DECOY in no list. If the verb ever reaches a
    global it was not given, the decoy fires and this fails.
    """
    rt = live()
    src = MOD_LUA.read_text(encoding="utf-8")
    listed = set()
    for block in re.findall(r"local RECON_\w+ = \{(.*?)\}", src, re.S):
        listed.update(re.findall(r'"(\w+)"', block))
    assert len(listed) > 50, f"only {len(listed)} names parsed out of the RECON lists"

    plant = chr(10).join(
        '_G["%s"] = function(...) _G.__called["%s"] = true return 1 end' % (n, n)
        for n in sorted(listed))
    rt.execute("_G.__called = {}" + chr(10) + plant + chr(10) +
               '_G.DECOY_NotInAnyList = function() _G.__called["DECOY"] = true end')

    r = ask(rt, 1, "recon")
    assert r.status == "OK", r.payload[:200]
    h = hdr(r)

    # NOT VACUOUS: real calls must have happened, or this proves nothing.
    assert int(h["ok"]) >= 50, f"only {h['ok']} calls succeeded; the fixture did not plant"
    called = set(g(rt, "__called").keys())
    assert len(called) >= 50, f"only {len(called)} names were actually invoked"

    assert "DECOY" not in called, (
        "recon called a global in NO hardcoded list -- it is not a fixed-vocabulary probe "
        "any more")
    stray = {c for c in called if c not in listed and c != "DECOY"}
    assert not stray, f"recon called globals outside its lists: {sorted(stray)}"


def test_recon_REFUSES_an_id_this_session_never_issued(lua_factory):
    """Same allowlist rule as `component`. A fabricated id is never handed to the engine,
    because vanilla never passes one and the behaviour on one is unknown both ways."""
    rt = live()
    r = ask(rt, 1, "recon", "999999ULL")
    assert r.status == "OK", r.payload[:200]
    assert any("SKIPPED" in f and "not issued" in f for f in r.fields), r.fields[:6]


def test_recon_header_accounts_for_every_call(lua_factory):
    """ok + raised + absent must equal called. A probe whose buckets do not sum has lost
    rows, and a lost row reads as 'the engine does not have that'."""
    rt = live()
    h = hdr(ask(rt, 1, "recon"))
    assert (int(h["ok"]) + int(h["raised"]) + int(h["absent"])) == int(h["called"]), h
    assert int(h["shown"]) <= int(h["called"]), h


# --- F88: a probe list keyed on ARGUMENT POSITION is keyed on nothing ---------- #
#
# Every regex below uses character classes rather than backslash escapes. Not style:
# backslashes collapse crossing a tool boundary, which corrupted this mod's own source
# earlier today (a lua "[|<tab><nl><cr>,]" written as real control bytes). Avoiding the
# construct is cheaper than remembering to check it.


def _issued(rt):
    """An id this session really issued, taken from the reply rather than invented."""
    r = ask(rt, 1, "player")
    f = dict(x.split("=", 1) for x in r.fields if "=" in x)
    return f["occupiedship"]


def test_GetMacroUnitStorageCapacity_is_NOT_in_the_object_id_list(lua_factory):
    """F88, structural half. It sat in RECON_OBJ and was called with an OBJECT id,
    returning `OK number:0` -- a benign-looking wrong answer with no error raised, and
    0 is indistinguishable from "this ship carries no units".

    MEASURED in recon-20260830-211605.tsv:
        GetMacroUnitStorageCapacity(33879739ULL)   OK   number:0
    Vanilla passes a MACRO (menu_map.lua:10461, :10468).

    ⚠ The explicit skip is load-bearing. `lua_factory` guards MOD_LUA is None, but only
    when it is CALLED -- this test takes the fixture and never invokes it, so on a
    fresh clone with no dev tree it sailed past the guard into `None.read_text()`.
    MEASURED by scripts/verify-cold.sh, which is the only run that has no dev tree.
    """
    if MOD_LUA is None:
        pytest.skip("game-side mod not present in dev/")
    src = MOD_LUA.read_text(encoding="utf-8")
    obj = re.search("local RECON_OBJ = [{](.*?)[}]", src, re.S).group(1)
    mac = re.search("local RECON_MACRO = [{](.*?)[}]", src, re.S).group(1)
    assert "GetMacroUnitStorageCapacity" not in obj, "still in the OBJECT-id list"
    assert "GetMacroUnitStorageCapacity" in mac


def test_recon_calls_the_macro_probe_with_a_MACRO_STRING_not_the_object_id(lua_factory):
    """F88, behavioural half -- the one that would actually have caught it.

    The structural test above passes the moment the name is moved between two lists.
    Only this one proves the ARGUMENT changed, which is the whole defect.
    """
    rt = live()
    oid = _issued(rt)
    rt.execute(
        "_G.__macro_args = {} "
        "_G.GetMacroUnitStorageCapacity = function(a) "
        "  _G.__macro_args[#_G.__macro_args+1] = tostring(a) return 42 end")

    r = ask(rt, 2, "recon", oid)
    assert r.status == "OK", r.payload[:200]
    args = list(g(rt, "__macro_args").values())
    assert args, "the macro probe was never called at all"
    # The harness stubs GetComponentData(id, key) -> "key-of-<id>", so this is the
    # exact value the vanilla hop yields -- not a shape check.
    assert args[0] == "macro-of-" + oid.replace("ULL", ""), args
    assert oid not in args, "STILL passing the object id -- F88 is not fixed"


def test_recon_SKIPS_the_macro_probe_rather_than_FALLING_BACK_to_the_id(lua_factory):
    """The falsification twin, and it targets a DIFFERENT clause than the test above.

    The guard is `mok AND type(macro)=='string' AND macro ~= ''`. The test above only
    ever exercises the success path, so a fallback that passed the object id when the
    hop failed would survive it untouched. Here the hop returns a non-string: the probe
    must NOT run, and the run must SAY so rather than quietly skipping.
    """
    rt = live()
    oid = _issued(rt)
    rt.execute(
        "_G.__macro_args = {} "
        "_G.GetMacroUnitStorageCapacity = function(a) "
        "  _G.__macro_args[#_G.__macro_args+1] = tostring(a) return 42 end "
        "_G.GetComponentData = function(id, key) return 12345 end")

    r = ask(rt, 2, "recon", oid)
    assert r.status == "OK", r.payload[:200]
    assert not list(g(rt, "__macro_args").values()), (
        "it fell back to calling the probe with a non-macro -- the exact F88 defect")
    assert any("macro-for:" in f and "SKIPPED" in f for f in r.fields), (
        "the skip is SILENT; an unrun probe must be visible in the output")
    assert hdr(r)["macros_resolved"] == "0"


# --- recon --contents: opt-in, bounded, scalar leaves only, one level --------- #


def _contents_rt(lua_payload):
    """A runtime whose GetStorageData returns `lua_payload`, plus an issued id."""
    rt = live()
    oid = _issued(rt)
    rt.execute("_G.GetStorageData = function(o) return " + lua_payload + " end")
    return rt, oid


def _storage_row(r):
    return [f for f in r.fields if f.startswith("GetStorageData(")][0]


def test_contents_is_OPT_IN_so_the_recorded_fixture_stays_comparable(lua_factory):
    """109 calls in recon-20260830-211605.tsv were recorded with the shape-only
    summary. Were contents the default, this run and that fixture would not be
    comparable while LOOKING like the same command."""
    rt, oid = _contents_rt("{alpha = 1, beta = 2}")
    r = ask(rt, 2, "recon", oid)
    row = _storage_row(r)
    assert "keys=2" in row
    assert "{" not in row, "contents leaked into the DEFAULT summary: " + row
    assert hdr(r)["contents"] == "no"


def test_contents_renders_scalar_leaves_when_asked(lua_factory):
    rt, oid = _contents_rt("{alpha = 1, beta = 'two', gamma = true}")
    r = ask(rt, 2, "recon", oid, "--contents")
    row = _storage_row(r)
    assert "alpha=1" in row and "beta=two" in row and "gamma=true" in row, row
    assert hdr(r)["contents"] == "yes"


def test_contents_does_NOT_descend_into_a_nested_table(lua_factory):
    """One level deep is what makes a cycle guard unnecessary rather than merely
    absent. A nested table must be VISIBLE as elided, never dropped."""
    rt, oid = _contents_rt("{outer = 1, inner = {secret = 99}}")
    r = ask(rt, 2, "recon", oid, "--contents")
    row = _storage_row(r)
    assert "inner=<table>" in row, row
    assert "secret" not in row, "it descended a level: " + row


def test_contents_TERMINATES_on_a_cyclic_table(lua_factory):
    """Why 'one level' is a safety property and not a convenience. If this ever starts
    recursing, this test HANGS rather than fails -- which is itself the signal."""
    rt = live()
    oid = _issued(rt)
    rt.execute("local t = {name = 'loop'} t.self = t "
               "_G.GetStorageData = function(o) return t end")
    r = ask(rt, 2, "recon", oid, "--contents")
    row = _storage_row(r)
    assert "self=<table>" in row and "name=loop" in row, row


def test_contents_is_BOUNDED_and_NAMES_what_it_omitted(lua_factory):
    """F74: an over-long reply does not truncate, it TEARS THE PIPE DOWN, costing the
    whole connection. So the bound is enforced here rather than detected afterwards --
    and a bounded cell must say how much it left out, because a silent stop reads as
    'that is all there was'."""
    big = "{" + ", ".join(
        "k%03d = 'vvvvvvvvvvvvvvvvvvvv'" % i for i in range(200)) + "}"
    rt, oid = _contents_rt(big)
    r = ask(rt, 2, "recon", oid, "--contents")
    row = _storage_row(r)
    assert "-more" in row, "bounded but silent about it: " + row[:200]
    omitted = int(re.search("[+]([0-9]+)-more", row).group(1))
    assert 0 < omitted < 200
    assert len(row) < 1200, "the bound did not hold: %d bytes" % len(row)


def test_contents_keys_are_SORTED_so_two_runs_are_DIFFABLE(lua_factory):
    """An engine table's pairs() order is not guaranteed stable. Unsorted, every diff
    between two harvests would look like a change."""
    rt, oid = _contents_rt("{zulu = 1, alpha = 2, mike = 3}")
    r = ask(rt, 2, "recon", oid, "--contents")
    row = _storage_row(r)
    body = row[row.index("{") + 1:row.index("}")]
    keys = [c.split("=")[0] for c in body.split(",")]
    assert keys == sorted(keys), keys


# --- censusprobe: the SECOND cause of the census caveat, measured per item ----- #


def _census_rt(stations_all, stations_by_owner):
    """A runtime where the two station enumerators return controlled id lists."""
    rt = live()
    ask(rt, 1, "player")
    def _lua_list(ids):
        return "{" + ", ".join("'%s'" % i for i in ids) + "}"
    rt.execute(
        "_G.GetContainedStations = function(c, flag) return " + _lua_list(stations_all) + " end "
        "_G.GetContainedStationsByOwner = function(fac, c) "
        "  if fac == 'argon' then return " + _lua_list(stations_by_owner) + " end return {} end "
        "_G.GetContainedShips = function(c, flag) return {} end "
        "_G.GetContainedShipsByOwner = function(fac, c) return {} end "
        "_G.GetContainedSpacesByOwner = function(fac, c) return {} end "
        "_G.GetContainedBuildStoragesByOwner = function(fac, c) return {} end")
    return rt


def _cmp_row(r, a="GetContainedStations", flag="true"):
    return [f for f in r.fields if f.startswith("CMP:" + a + ":" + flag)][0]


def test_censusprobe_REFUSES_a_bad_sector_token(lua_factory):
    """F85: an unrecognised container is SILENTLY IGNORED and the engine hands back the
    whole galaxy labelled as your sector -- MEASURED 310 vs 1961. A census verb that
    accepted a stale token would report a galaxy-wide count as a sector count, which is
    the worst possible failure for this specific verb. Sector tokens change EVERY
    launch, so a stale one is the normal case."""
    rt = _census_rt([], [])
    r = ask(rt, 2, "censusprobe", "NOT_A_SECTOR")
    assert r.status == "ERR", r.payload[:160]
    assert "SILENTLY IGNORED" in r.payload


def test_censusprobe_accepts_the_shape_the_engine_actually_uses(lua_factory):
    """The twin of the guard above, targeting the OTHER branch. Without it the verb
    could refuse everything and the test above would still pass."""
    rt = _census_rt(["a"], ["a"])
    r = ask(rt, 2, "censusprobe", "ID: 4301")
    assert r.status == "OK", r.payload[:200]
    assert hdr(r)["sector"] == "ID:4301"


def test_censusprobe_compares_SETS_not_totals(lua_factory):
    """★ The property the verb exists for. Two totals can agree while naming DIFFERENT
    objects -- a count is exactly the aggregate a real difference hides in. Here both
    sides have THREE ids and the sets differ on two of them; a count comparison would
    report perfect agreement."""
    rt = _census_rt(["a", "b", "x"], ["a", "b", "y"])
    r = ask(rt, 2, "censusprobe", "ID: 4301", "argon")
    row = _cmp_row(r)
    assert "n_container=3" in row and "n_owner=3" in row, row
    assert "container_only=1" in row, "equal totals hid a real difference: " + row
    assert "owner_only=1" in row, row


def test_censusprobe_REFUSES_a_vacuous_comparison_when_no_factions_resolve(lua_factory):
    """★ Found by a test going red for the right reason, and it fails TOWARDS the
    conclusion we are hunting. With an empty faction list the owner-scoped side is empty
    by construction, so every container-scoped id lands in `container_only` and the row
    reads 'the non-owner call sees N objects the per-faction walk missed' -- this verb's
    target finding, manufactured out of nothing. It must refuse instead."""
    rt = live()
    ask(rt, 1, "player")
    rt.execute(
        "_G.GetContainedStations = function(c, f) return {'a', 'b'} end "
        "_G.GetContainedStationsByOwner = function(fac, c) return {} end "
        "_G.GetContainedShips = function(c, f) return {} end "
        "_G.GetContainedShipsByOwner = function(fac, c) return {} end "
        "_G.GetContainedSpacesByOwner = function(fac, c) return {} end "
        "_G.GetContainedBuildStoragesByOwner = function(fac, c) return {} end")
    r = ask(rt, 2, "censusprobe", "ID: 4301")
    assert r.status == "OK", r.payload[:200]
    assert hdr(r)["factions"] == "0"
    row = _cmp_row(r)
    assert "SKIPPED" in row and "vacuously empty" in row, (
        "it reported a manufactured difference as a finding: " + row)
    assert "container_only=2" not in row


def test_censusprobe_reports_FOUR_ZEROES_as_a_real_answer(lua_factory):
    """A row of zeroes must be reachable and legible: it is the finding 'the
    non-owner-scoped call sees nothing the per-faction walk missed', which is a real
    result and the one that would retire this line of enquiry."""
    rt = _census_rt(["a", "b"], ["a", "b"])
    r = ask(rt, 2, "censusprobe", "ID: 4301", "argon")
    row = _cmp_row(r)
    assert "container_only=0" in row and "owner_only=0" in row, row


def test_censusprobe_probes_BOTH_booleans_and_LABELS_the_guessed_one(lua_factory):
    """Vanilla passes `true` at all 7 of its call sites and never `false`, so `false` is
    a GUESS. It gets probed -- that is the point -- but it must not be recorded in the
    same grammar as the attested one."""
    rt = _census_rt(["a"], ["a"])
    r = ask(rt, 2, "censusprobe", "ID: 4301", "argon")
    rows = [f for f in r.fields if f.startswith("GetContainedStations(")]
    assert len(rows) == 2, rows
    assert any("true)" in x and "vanilla-attested" in x for x in rows), rows
    assert any("false)" in x and "GUESSED" in x for x in rows), rows


def test_censusprobe_records_an_ABSENT_function_rather_than_crashing(lua_factory):
    """Four of the five names have ZERO vanilla call sites. 'It exists in _G' is not
    evidence that calling it is safe, and F88 was a wrong-argument call that answered
    `OK number:0`. An absent or raising probe is a RECORDED RESULT, never a failure of
    the run."""
    rt = _census_rt(["a"], ["a"])
    rt.execute("_G.GetContainedSpacesByOwner = nil")
    r = ask(rt, 2, "censusprobe", "ID: 4301", "argon")
    assert r.status == "OK", r.payload[:200]
    assert any(f.startswith("GetContainedSpacesByOwner|ABSENT") for f in r.fields), r.fields

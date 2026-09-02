-- X4 Toolkit live query channel (dev-only, READ-ONLY).
--
-- Answers a fixed vocabulary of questions from an external Python server over a
-- named pipe, so the toolkit can ask the RUNNING engine something without a
-- quit-and-relaunch. Complement to the uidata probe: that one is an offline bulk
-- oracle (uidata.xml is 61 bytes while the game runs), this one is live spot checks.
--
-- SHAPE COPIED, NOT COMPOSED. Modelled line-for-line on
-- sn_mod_support_apis/ui/time/pipe_time.lua, which is a working 90-line example of
-- this exact round trip. A schema tells you what is well-formed; it cannot tell you
-- what is wired up, and composing from one cost three play sessions on 2026-08-27.
--
-- WE ARE THE CLIENT. The external Python creates the pipe; pipes.lua opens a client
-- handle to it and does not care who served it. That is why this mod needs no MD, no
-- Pipe_Server_Host registration and no permissions.json grant.
--
-- CONTRACTS THIS FILE KEEPS (each because something got it wrong before):
--  * A LOAD MARKER is the first thing emitted, before any pipe logic. Absent marker
--    means the mod did not load, and nothing downstream is worth debugging.
--    "PROVE IT RAN BEFORE DEBUGGING WHAT IT DID."
--  * Every reply declares its own BYTE length and checksum.
--    CORRECTED 2026-08-29 after reading the PACKED pipes.lua out of its .cat: the
--    unhandled ERROR_MORE_DATA at :698 is on the READ path (the game reading OUR
--    COMMAND), and it does NOT truncate. winpipe exposes only ERROR_IO_PENDING and
--    ERROR_NO_DATA, so 234 falls through to :720 error(), is caught by Read_Pipe's
--    pcall, reaches Poll_For_Reads:560 -> Close_Pipe, and DESTROYS THE PIPE. Replies
--    fail the same way by the api's own docs. So an over-long message is a loud
--    total teardown in either direction, never a quiet short answer -- which means
--    SIZE MUST BE BOUNDED BEFORE SENDING. The length and checksum catch a short
--    read; they cannot prevent a teardown. Any unbounded verb caps itself.
--  * Three states, never a bare zero: OK / ABSENT / ERR. "the engine says no such
--    macro" and "we could not ask" must never share a representation.
--  * string.format("%.0f", n) for the checksum, NEVER tostring(n). Lua renders a
--    number above ~1e14 in exponent form, so tostring(3000000000) is "3e+09" and the
--    Python side's int() would raise on a perfectly correct checksum.

local PIPE  = "x4live"
local PROTO = 1

--: BUILD FINGERPRINT -- the first 8 hex of a sha256 over this file with this very
--: line masked out. Reported by `probe`, so the caller can prove the GAME is running
--: the file on DISK rather than assuming it.
--:
--: ⚠ THIS EXISTS BECAUSE "A DEPLOYED FILE IS NOT A LOADED FILE" COST TWO CYCLES IN
--: ONE SESSION. The first cost was believing a reload had happened; the second was a
--: staleness check that fingerprinted on ONE new field (`our_ffi=`). That field was
--: added in the PREVIOUS build, so it proved "not the build before last" and said
--: nothing about the current one -- a check whose pass branch did not mean what it
--: claimed. A content hash cannot have that failure: it changes whenever the file
--: changes, including changes nobody thought to enumerate.
--:
--: Kept honest by `test_the_BUILD_constant_matches_the_file`, so editing the lua and
--: forgetting to re-stamp this fails the suite rather than silently lying in game.
local BUILD = "e1af07d7"
local TAG_CMD, TAG_REPLY = "MQ", "MR"

-- Cap on echo, the ramp instrument. Generous: the point of the ramp is to FIND the
-- real ceiling, so this must sit well above any plausible one and only exists to
-- stop a typo allocating gigabytes.
local ECHO_MAX = 1024 * 1024

local armed = false

--: RELOAD BOOKKEEPING -- how a caller tells that the game RE-EXECUTED this chunk.
--:
--: ⚠ MEASURED IN GAME 2026-08-29, with controls in both directions. The engine
--: re-executes every registered UI lua file on a full UI reload, and TWO ordinary
--: actions cause one:
--:   * pressing ALT-ENTER (a graphics MODE change) -- 2 presses, 2 reloads;
--:   * LOADING A SAVE -- new chunk, and DEBUG.TXT's timestamp clock resets with it
--:     (1289.31 -> 143.77). NB that is debug.txt's clock, not getElapsedTime(); the two
--:     are different, which is a distinction this file got wrong once already (below).
--: Alt-TAB does NOT: 75.7 s of foreground time here and 1190 s in an earlier session,
--: zero reloads across both. The variable is the mode change, not the focus change.
--:
--: A reload builds a FRESH chunk, so `issued_ids` starts empty and every id the caller
--: holds stops resolving. For a save load that is REQUIRED (see Init). For an
--: alt-enter it is merely surprising -- and until `component` learned to say so, the
--: caller could not tell a reload from a fabricated id: both produced one refusal with
--: identical wording, and the wording blamed the caller.
--:
--: ★★ NO LUA STATE SURVIVES A UI RELOAD. MEASURED IN GAME 2026-08-29/30 (the session
--: crossed midnight), and it is the single fact that explains every other observation
--: of that session.
--:
--: This block briefly carried a second field, `incarnation`: a counter kept on a
--: SHARED GLOBAL (`_G`) and incremented once per chunk execution. Across two real
--: reloads it read 1, then 1. The counter was not wrong -- `_G` ITSELF DOES NOT
--: PERSIST. The engine rebuilds the whole lua environment, not merely our chunk.
--:
--: Three things follow, and the second is why the field was worth building anyway:
--:  * A count of reloads CANNOT be kept game-side. Any such detection has to live in
--:    the client, or in a value that differs per chunk by construction.
--:  * The design we nearly shipped -- persist `issued_ids` across reloads via a global
--:    so alt-enter stops invalidating ids -- was not merely UNSAFE, it was IMPOSSIBLE.
--:    No global could have carried the allowlist either. We rejected it for the right
--:    reason (after a save load a REUSED handle returns another object's data under
--:    the id you asked about) and got a second, stronger one for free.
--:  * It unifies the rest: no stale closures accumulate, no duplicate RegisterEvent
--:    listeners build up, and the allowlist empties -- ONE cause, not three.
--:
--: ⚠ The counter was also a textbook instrument-that-cannot-move: only its "no reload
--: happened" branch was ever reachable. It was caught ONLY because the prediction was
--: written down before the second reload, so the result was able to contradict it.
--: Recorded here rather than quietly deleted.
--:
--:   loaded_at   getElapsedTime() at chunk load. ⚠ NOT session time, and NOT per-save.
--:               MEASURED 0.89 then 0.82 across two reloads that debug.txt timestamped
--:               254.56 and 425.42 -- a DIFFERENT CLOCK, which resets with the UI. So
--:               this is usable ONLY as a change detector: a fresh chunk almost always
--:               reports a different value. Treat a difference as strong evidence of a
--:               reload and a match as weak, since two chunks can collide at 2 decimal
--:               places. An earlier version of this comment said it "goes BACKWARDS on
--:               a save load, because the clock is per-save" -- that was reasoned from
--:               debug.txt timestamps rather than from this function, and was wrong.
local LOADED_AT = (type(getElapsedTime) == "function") and getElapsedTime() or -1

--: Set true by the save-load hook in Init if it EVER runs. MEASURED 2026-08-29 across
--: a game start AND a save load: it never has -- 0 occurrences of its log line, while
--: `RegisterEvent absent` and `could not hook game load` are also 0, so it registers
--: successfully and simply never fires. Reported by `probe` so its deadness is VISIBLE
--: rather than assumed. See Init for why it cannot fire and what actually protects us.
local load_hook_fired = false

-- Forward-declared as LOCALS. The menus lua environment is SHARED between every
-- mod that loads through ui.xml, so a global named `pipes` or `Init` is a collision
-- waiting to happen -- pipe_time.lua gets away with it only because it is first.
--: X4 runs LuaJIT (5.1), where this is the global `unpack`; the offline lupa harness
--: may be 5.2+, where it moved to `table.unpack`. Bound once so the dispatch does not
--: have to care, and so a missing one fails HERE rather than inside a verb.
local table_unpack = table.unpack or unpack

local pipes = nil
local Init
local on_message          -- forward-declared: arm_read() references it before its definition
local schedule_rearm      -- forward-declared: arm_read() re-arms through it on failure

--: Set by reply(). The dispatch error path consults it so a verb that replied and
--: THEN raised cannot emit a SECOND frame for one seq. Two frames for one question
--: desync the FIFO, and the NEXT query reads the stale one and fails clause 5 --
--: surfacing the failure one question AFTER its cause, the worst possible place.
local last_replied_seq = nil

-- Re-arm state. See schedule_rearm() for why the delay is not optional.
local REARM_DELAY   = 2.0   -- seconds; also the throttle, see below
local rearm_logs    = 0     -- how many re-arm lines we have written
local last_rearm_log = -1e9 -- getElapsedTime() of the last one

-- --------------------------------------------------------------------------- --
-- framing
-- --------------------------------------------------------------------------- --

-- djb2 over BYTES. Must agree exactly with _livepipe.checksum on the Python side.
-- #s and string.byte are both byte operations in Lua, which is why the Python side
-- encodes to UTF-8 first rather than iterating codepoints.
local function checksum(s)
    local h = 5381
    for i = 1, #s do
        h = (h * 33 + s:byte(i)) % 4294967296
    end
    return h
end

local function split_tabs(s)
    -- Preserves EMPTY fields, which string.gmatch("[^\t]+") silently collapses --
    -- and a collapsed empty argument shifts every later one by a position.
    local out, pos = {}, 1
    while true do
        local i = string.find(s, "\t", pos, true)
        if not i then
            out[#out + 1] = string.sub(s, pos)
            return out
        end
        out[#out + 1] = string.sub(s, pos, i - 1)
        pos = i + 1
    end
end

local function reply(seq, status, payload)
    payload = payload or ""
    -- seq is echoed as the RAW STRING it arrived as. Round-tripping it through
    -- tonumber/tostring risks the same exponent rendering as the checksum.
    local frame = table.concat({
        TAG_REPLY,
        tostring(PROTO),
        seq,
        status,
        string.format("%d", #payload),
        string.format("%.0f", checksum(payload)),
        payload,
    }, "\t")
    pipes.Schedule_Write(PIPE, nil, frame)
    last_replied_seq = seq
end

-- --------------------------------------------------------------------------- --
-- verbs -- a fixed dispatcher, not a console. MD has no eval and we ship no lua one.
-- READ ONLY: there is no write verb here, gated or otherwise.
-- --------------------------------------------------------------------------- --

local function sorted_keys(t)
    local ks = {}
    for k in pairs(t) do ks[#ks + 1] = tostring(k) end
    table.sort(ks)
    return ks
end

-- --------------------------------------------------------------------------- --
-- FFI -- for the symbols the engine does NOT expose as bare globals
-- --------------------------------------------------------------------------- --
--
-- MEASURED IN GAME 2026-08-29 by the `probe` verb, which is exactly why it shipped
-- first. The split is not guesswork and it is not uniform:
--
--   bare globals : GetComponentData, IsValidComponent, ConvertStringTo64Bit,
--                  ConvertIDTo64Bit, GetMacroData, GetLibraryEntry
--   ffi only     : GetPlayerOccupiedShipID, GetPlayerID, GetComponentClass,
--                  the four faction-enumeration calls, GetObjectPositionInSector
--
-- It matches vanilla's own usage exactly: every bare-available symbol is one vanilla
-- calls bare, every nil one is a symbol vanilla declares in ffi.cdef and calls as
-- `C.*`. Had these verbs been written against bare globals as first planned, all
-- seven would have been nil and the whole slice would have failed in game.
--
-- REDEFINITION IS SAFE HERE and that is measured, not assumed: vanilla declares
-- `GetPlayerOccupiedShipID` identically in 10 files, `typedef uint64_t UniverseID`
-- in 27, and `UIPosRot` in 8 -- all sharing ONE FFI state. Our file loads after all
-- of them, so this block is a redefinition every time.
--
-- ⚠ SIGNATURES ARE COPIED CHARACTER-FOR-CHARACTER FROM VANILLA, never composed.
-- A wrong signature here is not a lua error, it is a memory-layout error.
--   helper.lua:154-161  UIPosRot        helper.lua:366  GetObjectPositionInSector
--   helper.lua:371,373  GetPlayerID, GetPlayerOccupiedShipID
--   menu_docked.lua:105 GetPlayerObjectID
--   menu_map.lua:587    GetComponentClass
--   menu_playerinfo.lua:185-186, 205-206  the faction enumeration pairs
local ffi, C = nil, nil
local ffi_ok, cdef_ok = false, false
do
    local ok, mod = pcall(require, "ffi")
    if ok and type(mod) == "table" then
        ffi, ffi_ok = mod, true
        -- pcall'd: if a future patch makes redefinition fatal, the ffi verbs degrade
        -- to a clean ERR and every bare-global verb keeps working.
        local cok, cerr = pcall(ffi.cdef, [[
            typedef uint64_t UniverseID;
            typedef struct { float x; float y; float z; float yaw; float pitch; float roll; } UIPosRot;
            UniverseID GetPlayerID(void);
            UniverseID GetPlayerObjectID(void);
            UniverseID GetPlayerOccupiedShipID(void);
            const char* GetComponentClass(UniverseID componentid);
            uint32_t GetNumAllFactionShips(const char* factionid);
            uint32_t GetAllFactionShips(UniverseID* result, uint32_t resultlen, const char* factionid);
            uint32_t GetNumAllFactionStations(const char* factionid);
            uint32_t GetAllFactionStations(UniverseID* result, uint32_t resultlen, const char* factionid);
            UIPosRot GetObjectPositionInSector(UniverseID objectid);
            /* The faction list, for a future cross-faction `objects <sector>`. Copied
               VERBATIM from vanilla (customgame.lua:279 and :224, same pair again in
               menu_mapeditor.lua:70) rather than composed from the shape of the others:
               a signature guessed from a pattern is a crash, not a compile error.
               Declared now only so `probe` can report whether they are EXPORTED --
               indexing ffi.C for an undeclared symbol raises rather than returning nil,
               so an undeclared symbol cannot be probed at all. */
            uint32_t GetNumAllFactions(bool includehidden);
            uint32_t GetAllFactions(const char** result, uint32_t resultlen, bool includehidden);
        ]])
        cdef_ok = cok and true or false
        if cok then C = ffi.C
        else DebugError("X4TOOLKIT_LIVE ffi.cdef failed: " .. tostring(cerr)) end
    end
end

-- --------------------------------------------------------------------------- --
-- the SESSION ID ALLOWLIST
-- --------------------------------------------------------------------------- --
--
-- ⚠ MEASURED over vanilla: of 888 `GetComponentData` call sites, ZERO pass an id
-- that did not come out of the engine in the same code path. There is therefore no
-- evidence in EITHER direction about what a fabricated or stale 64-bit id does, and
-- no defensive idiom to copy. An id typed at a CLI is precisely that unknown case.
--
-- So this channel inspects only ids it HANDED OUT itself. `IsValidComponent` is
-- still checked on top, because vanilla's own guards say handles go stale between
-- frames -- but the allowlist is what keeps a fabricated integer from ever reaching
-- the engine at all. Cleared on reload, which is correct: ids do not outlive a
-- session.
local issued_ids = {}

--: The wire form of a UniverseID is `tostring(cdata)` VERBATIM -- LuaJIT renders it
--: with a ULL suffix, and vanilla's own round trip is
--: `ConvertStringTo64Bit(tostring(id))` (553 bare uses). Treat it as an OPAQUE
--: string on both sides: never parse it, never int() it in Python. A uint64 above
--: 2^53 does not survive a double.
--:
--: ★ THERE ARE TWO ID REPRESENTATIONS AND THEY STRINGIFY DIFFERENTLY. MEASURED in
--: game 2026-08-30:
--:     tostring(C.GetPlayerOccupiedShipID())    = 1046331ULL   ffi cdata
--:     tostring(ConvertIDTo64Bit(<luaid>))      = 282463       lua number
--:     tostring(ConvertStringTo64Bit("282463")) = 282463       lua number
--: Same uint64 to the engine; two different strings on our side. The ffi verbs issue
--: the first form, and `GetContainedObjectsByOwner` hands back LuaIDs that normalise
--: to the second -- so without a single choke point the SAME OBJECT would get TWO
--: ids, which breaks dedupe and makes any set comparison between two enumeration
--: paths meaningless. (The two lines above are different objects, so the difference
--: is INFERRED, not proven; `compare` renders one object both ways and settles it.
--: This is written so that it does not matter: if they never differ, `wire` is a
--: no-op.)
local function wire(v)
    --: ALREADY CANONICAL? Decided by what the value RENDERS AS, not by its lua type.
    --: A `uint64` cdata stringifies to exactly this, so the ffi path needs no special
    --: case -- which also means the branch is reachable offline. Keying it on
    --: `type(v) == "cdata"` instead made it untestable in the harness, and a branch no
    --: test can reach is a branch nothing defends.
    --: A LuaID renders as `ID: 282463`, so it can never collide with this pattern.
    local s = tostring(v)
    if s:match("^%d+ULL$") then return s end

    local n
    local t = type(v)
    if t == "number" then n = v
    elseif t == "string" then n = ConvertStringTo64Bit(v)
    else n = ConvertIDTo64Bit(v) end     -- a LuaID, or whatever else the engine hands us
    if type(n) ~= "number" then return tostring(ffi.cast("UniverseID", n)) end
    --: ENFORCE the 2^53 rule rather than remembering it. A lua number is a double, so
    --: above 2^53 it silently stops being able to hold a distinct uint64 -- and the
    --: bare engine globals return lua numbers. Observed ids are ~10^7 (33556742), so
    --: there is a large margin today; this is the check that notices if that changes.
    if n >= 9007199254740992 then
        error("id " .. string.format("%.0f", n) .. " is at or above 2^53 and cannot be "
              .. "represented exactly as a lua number; the bare-global conversion path "
              .. "is no longer safe for this save")
    end
    return tostring(ffi.cast("UniverseID", n))
end

--: For OBJECT ids. Canonicalises, so every verb emits one string per object.
local function issue(v)
    local s = wire(v)
    issued_ids[s] = true
    return s
end

--: For SECTOR tokens, which are a DIFFERENT KIND and must not be canonicalised.
--: `GetComponentData(id, "sectorid")` returns `ID: 7479`, vanilla feeds exactly that
--: to `ConvertStringToLuaID(tostring(...))` (menu_diplomacy.lua:1925), and it is what
--: `stations`/`ships`/`objects` take as their sector argument. Running it through
--: `wire` would rewrite the token `player` hands out and silently break every
--: sector-scoped query. ⚠ Sector tokens are NOT stable across launches (MEASURED:
--: ID: 4305 then ID: 7479 for the same sector) -- never persist one.
local function issue_token(s)
    issued_ids[s] = true
    return s
end

--: Bound REPLIES before sending. An over-long message does not truncate, it tears
--: the pipe down (see the header), so an unbounded enumeration is a connection
--: killer rather than a short answer. 32000 is well under the 524,288 bytes proven to
--: round-trip in game, which leaves room for the frame header and any single
--: oversized row.
local MAX_PAYLOAD = 32000

--: Reserved out of MAX_PAYLOAD for the header line, which is prepended AFTER the row
--: loop and so cannot be measured during it.
--:
--: ⚠ MEASURED IN GAME 2026-08-29: without this, `ships argon` capped its rows at
--: exactly 32000 and then added a 143-byte header, shipping 32143 bytes against a
--: "32000-byte" budget. Harmless in itself -- the proven ceiling is 524,288 -- but the
--: number did not mean what it said, and a budget you cannot trust is not a budget.
--:
--: ★ The test was complicit: it asserted `<= 32000 + 200`. That 200-byte slack was
--: added for comfort and is exactly what let a 143-byte overrun through. A tolerance
--: nobody derived is a place for defects to live; the assertion is now exact.
local HEADER_RESERVE = 512

--: Per-VALUE budget for `recon --contents`. Deliberately far below ROW_BUDGET: one
--: fat table must not be able to crowd out the other 100-odd probe results, and the
--: point of the mode is to see the SHAPE of a payload, not to exfiltrate all of it.
--: A truncated cell says `+N-more` rather than ending silently.
local CONTENTS_BUDGET = 400
local ROW_BUDGET = MAX_PAYLOAD - HEADER_RESERVE

local verbs = {}

-- ping also carries the engine's elapsed time, which is what distinguishes PAUSED
-- from RUNNING: two pings whose elapsed time is identical mean the game is not
-- advancing. Collapsing paused/hung/not-loaded into one verdict is the bug that
-- made a sibling project's liveness probe wrong for three releases.
verbs.ping = function(seq)
    local t = "unknown"
    if type(getElapsedTime) == "function" then
        local ok, v = pcall(getElapsedTime)
        if ok then t = tostring(v) end
    end
    reply(seq, "OK", table.concat({ "pong", tostring(PROTO), t }, "\t"))
end

-- The CAPABILITY PROBE, and the reason it ships BEFORE the verbs that need it.
--
-- Our lua loads into the shared `menus` environment (ui.xml declares
-- environment type="menus"). MEASURED across vanilla: all 25 files that call
-- GetComponentData are menus-registered, and the one file that is NOT
-- (ui/core/lua/monitors.lua) had to reach IsValidComponent through ffi.cdef
-- instead -- the only cdef of that symbol in the tree. So reachability from OUR
-- file is a strong inference, not a measurement, and the answer decides whether
-- the live view is written against bare globals or a private cdef block. Getting
-- that wrong costs a full build against the wrong shape.
--
-- It reports TYPES ONLY and never invokes a symbol, so no argument can be wrong
-- and there is nothing here that can crash the game.
local PROBE_SYMBOLS = {
    "GetComponentData", "GetComponentClass", "IsValidComponent",
    "GetPlayerOccupiedShipID", "GetPlayerID",
    "GetNumAllFactionStations", "GetAllFactionStations",
    "GetNumAllFactionShips", "GetAllFactionShips",
    "GetObjectPositionInSector",
    "ConvertStringTo64Bit", "ConvertIDTo64Bit",
    "GetMacroData", "GetLibraryEntry",
    --: Not called by any verb. ⚠ This entry USED to say it was "needed by Init to reset
    --: the id allowlist on a save load", and that reading -- present therefore working --
    --: is exactly what hid a dead hook for weeks. MEASURED 2026-08-29: RegisterEvent is
    --: PRESENT and the handler Init registers with it has NEVER FIRED. Presence of a
    --: symbol says nothing about a callback running. What actually clears the allowlist
    --: is chunk re-creation; see Init. Watch `load_hook_fired` below, not this line.
    "RegisterEvent",
    --: Candidates for a cross-faction `objects <sector>` verb, probed BEFORE anything is
    --: built on them. `GetContainedObjectsByOwner(owner [, container])` is a bare engine
    --: global (6 vanilla call sites, no lua definition anywhere in ui/) that returns a
    --: PLAIN LUA TABLE and takes an optional container -- so it could push the sector
    --: filter engine-side, where today `enumerate` walks the whole galaxy per faction and
    --: discards the rest in lua. ⚠ 0 of those 6 call sites pass a SECTOR as the
    --: container, so that specific use is unverified and this probe is how we find out
    --: rather than discovering it from a broken verb.
    "GetContainedObjectsByOwner",
    --: The faction list, so `objects` can merge across factions instead of taking one.
    --: cdef'd in vanilla (customgame.lua:279/:224) rather than called bare, so a bare
    --: lookup may well read nil here -- which is itself the answer, and why both the env
    --: and C forms are checked.
    "GetNumAllFactions", "GetAllFactions",
}

verbs.probe = function(seq)
    -- TWO lookups per symbol, because they can disagree. A bare reference resolves
    -- through this chunk's ENVIRONMENT; _G is the global table. If the engine
    -- installs its bindings anywhere other than plain _G the two differ, and a
    -- probe checking only one would report a confident absence for a symbol that is
    -- reachable. The existing verbs prove the bare form works (GetLibraryEntry is
    -- reached that way and returns real data), so env is the authority and _G is
    -- the cross-check -- and a disagreement is itself the finding.
    local env = (type(getfenv) == "function") and getfenv(1) or _G
    local out = {}
    for i = 1, #PROBE_SYMBOLS do
        local name = PROBE_SYMBOLS[i]
        local via_env, via_g = type(env[name]), type(_G[name])
        if via_env == via_g then
            out[#out + 1] = name .. "=" .. via_env
        else
            out[#out + 1] = name .. "=env:" .. via_env .. ",_G:" .. via_g
        end
    end
    -- Reached differently from the rest: ffi is a module, Helper a bare table.
    -- Both matter. If GetComponentData turns out to be absent we need ffi; and the
    -- faction-enumeration pair is cdef-only in vanilla either way.
    -- NB deliberately NOT named ffi_ok: that is a module-level local holding the real
    -- state of our cdef block, and shadowing it here would make the probe report on
    -- its own throwaway variable instead of on the thing being probed.
    local can_require_ffi = pcall(require, "ffi")
    out[#out + 1] = "require_ffi=" .. tostring(can_require_ffi)
    out[#out + 1] = "Helper=" .. type(Helper)
    out[#out + 1] = "Helper.ffiVLA="
                    .. (type(Helper) == "table" and type(Helper.ffiVLA) or "n/a")

    -- Our own FFI block, which is what the ffi-only verbs actually depend on. A bare
    -- global reading nil is expected for these; what matters is whether `C.<name>`
    -- resolves after our cdef.
    -- FIRST, because it is what decides whether anything else in this reply is worth
    -- reading: it identifies the build the GAME is running, which is not necessarily
    -- the build on disk.
    out[#out + 1] = "build=" .. BUILD
    --: Reload bookkeeping. `build=` answers "is the game running the file on disk";
    --: these answer "has the chunk been re-executed since I last asked", which is a
    --: DIFFERENT question and the one that explains a rejected id. A reload keeps the
    --: same build and still empties the allowlist.
    out[#out + 1] = "loaded_at=" .. string.format("%.2f", LOADED_AT)
    out[#out + 1] = "load_hook_fired=" .. tostring(load_hook_fired)
    out[#out + 1] = "our_ffi=" .. tostring(ffi_ok) .. ",cdef=" .. tostring(cdef_ok)
    if cdef_ok then
        for _, name in ipairs({ "GetPlayerOccupiedShipID", "GetNumAllFactionStations",
                                "GetComponentClass", "GetObjectPositionInSector",
                                "GetNumAllFactions", "GetAllFactions" }) do
            -- Indexing ffi.C for a symbol the engine does not export RAISES rather
            -- than returning nil, so this has to be pcall'd to be a probe at all.
            local rok, sym = pcall(function() return C[name] end)
            out[#out + 1] = "C." .. name .. "=" .. (rok and type(sym) or "<not exported>")
        end
    end

    --: ★ LIVE CALL PROBE -- because a symbol's TYPE does not tell you whether a given
    --: ARGUMENT SHAPE works, and that is the actual open question for `objects`.
    --: Two calls, reported SEPARATELY so a failure names which one failed:
    --:   owner_only  does the function work at all from our namespace?
    --:   with_sector does it accept a SECTOR as the container? 0 of 6 vanilla call
    --:               sites pass one (they pass a station or ship), so this is genuinely
    --:               unknown and is the clause the design turns on.
    --:
    --: ⚠ THE OWNER IS "argon", NOT "player", AND THAT IS THE WHOLE POINT. The first
    --: version of this probe asked about the PLAYER and reported `table:1` for both
    --: calls -- because the player owns one ship. "correctly filtered to 1" and
    --: "silently ignored the container argument" produce IDENTICAL output there, so it
    --: could not answer its own question. A faction owning objects across many sectors
    --: makes the two numbers diverge: all >> in_sector means the container is honoured,
    --: all == in_sector means it is being discarded (or, implausibly, that this faction
    --: is confined to one sector -- so read the numbers, do not just compare them).
    --: The counts are REPORTED rather than judged here: the discrimination belongs to
    --: whoever reads it, with both denominators in front of them.
    --: The sector handle is built the way VANILLA builds it -- menu_map.lua:13770 does
    --: `ConvertStringTo64Bit(tostring(sectorid))` on the very field GetComponentData
    --: returns -- rather than by assuming the raw "ID: nnnn" string is a handle.
    --: Everything is pcall'd: a probe that can raise is not a probe.
    if type(GetContainedObjectsByOwner) == "function" then
        local function shape(v)
            if type(v) ~= "table" then return type(v) end
            local n = 0
            for _ in pairs(v) do n = n + 1 end
            return "table:" .. tostring(n)
        end
        local PROBE_FACTION = "argon"
        local ok1, r1 = pcall(GetContainedObjectsByOwner, PROBE_FACTION)
        out[#out + 1] = "contained_all_" .. PROBE_FACTION .. "="
                        .. (ok1 and shape(r1) or ("raised:" .. tostring(r1)))
        if cdef_ok then
            local ok2, r2 = pcall(function()
                local ship = ConvertStringTo64Bit(tostring(C.GetPlayerOccupiedShipID()))
                local sect = GetComponentData(ship, "sectorid")
                local sector64 = ConvertStringTo64Bit(tostring(sect))
                return GetContainedObjectsByOwner(PROBE_FACTION, sector64)
            end)
            out[#out + 1] = "contained_in_my_sector="
                            .. (ok2 and shape(r2) or ("raised:" .. tostring(r2)))
        end
    else
        out[#out + 1] = "contained_all_argon=<symbol absent>"
    end

    reply(seq, "OK", table.concat(out, "\t"))
end

-- --------------------------------------------------------------------------- --
-- STEP-0 INSTRUMENT for the `objects` verb
-- --------------------------------------------------------------------------- --
--
--: A MEASUREMENT, not a feature. It exists to answer three questions BEFORE any of
--: `objects` is written, because all three touch the id contract every other verb
--: rests on -- and a wrong guess there is found the hard way, in game, with a broken
--: `component`. Confidence on question 1 was 70% when this was written; the standing
--: rule is that sub-90% buys a measurement rather than a gate.
--:
--:   1 WIRE FORM (the load-bearing one). GetContainedObjectsByOwner returns LuaIDs,
--:     NOT UniverseIDs -- vanilla normalises every one with ConvertIDTo64Bit
--:     (menu_map.lua:8229, menu_playerinfo.lua:1227, helper.lua:11154), and
--:     helper.lua:1893-97 shows the two are genuinely distinct representations. Our
--:     entire allowlist/`component` contract is `tostring(UniverseID cdata)`. If the
--:     normalised form does not round-trip identically, `objects` cannot issue ids at
--:     all without breaking every id-consuming verb. No cdef for ConvertIDTo64Bit
--:     exists anywhere in reference\ui, so its return type is UNVERIFIED -- this is
--:     the only way to find out short of shipping it.
--:   2 CONTAINER HANDLE. An earlier probe measured the sector container working with
--:     ConvertStringTo64Bit (argon: 2028 galaxy-wide vs 267 in sector). But vanilla
--:     builds it with ConvertStringToLuaID -- menu_platformundock.lua:121, and
--:     menu_diplomacy.lua:1925 which passes a SECTOR exactly as we intend to. Both
--:     forms are called here and the counts compared: agreement settles it, and a
--:     DISAGREEMENT is the more valuable finding.
--:   3 CLASS FILTER. Helper.isComponentClass(classid, "ship") and
--:     (realclassid, "station") -- note the DIFFERENT field per class, which is
--:     vanilla's own idiom at menu_map.lua:7371 and :7875 and is not something you
--:     would compose from the schema. Both fields are already in DEFAULT_FIELDS, so
--:     the filter costs zero extra engine calls. Cross-checked two ways: against bare
--:     IsComponentClass (28 vanilla uses), and against GetContainedStationsByOwner,
--:     which is an INDEPENDENT engine-side count of the same set and therefore a
--:     control that can actually go red.
--:
--: Everything is pcall'd and every failure is REPORTED rather than raised. A probe
--: that can raise is not a probe, and a probe that omits what it could not read is
--: an absence indistinguishable from a non-answer.
verbs.containerprobe = function(seq, faction)
    if type(GetContainedObjectsByOwner) ~= "function" then
        reply(seq, "ERR", "GetContainedObjectsByOwner is absent; nothing to probe")
        return
    end
    if not cdef_ok then
        reply(seq, "ERR", "containerprobe needs the ffi cdef block, which did not load")
        return
    end
    -- argon by default for the same reason the earlier probe used it: a faction
    -- spanning many sectors makes "filtered" and "ignored" produce different numbers.
    -- The player owns too little for the branches to diverge, which is exactly how an
    -- earlier version of this measurement reported table:1 against table:1 and could
    -- not answer its own question.
    faction = (faction ~= nil and faction ~= "") and faction or "argon"

    local out = {}
    local function put(k, v) out[#out + 1] = k .. "=" .. tostring(v) end
    local function count(v)
        if type(v) ~= "table" then return type(v) end
        local n = 0
        for _ in pairs(v) do n = n + 1 end
        return n
    end

    put("faction", faction)

    -- Reachability first: a later failure is uninterpretable without knowing whether
    -- the symbol was even there. env is the authority and _G the cross-check, as in
    -- `probe` -- a disagreement between them is itself a finding.
    local env = (type(getfenv) == "function") and getfenv(1) or _G
    for _, n in ipairs({ "ConvertIDTo64Bit", "ConvertStringToLuaID",
                         "GetContainedStationsByOwner", "IsComponentClass",
                         "IsValidComponent", "Helper" }) do
        local a, b = type(env[n]), type(_G[n])
        put("sym." .. n, (a == b) and a or ("env:" .. a .. ",_G:" .. b))
    end
    put("sym.Helper.isComponentClass",
        (type(Helper) == "table") and type(Helper.isComponentClass) or "n/a")

    local okship, ship = pcall(function()
        return ConvertStringTo64Bit(tostring(C.GetPlayerOccupiedShipID()))
    end)
    if not okship then
        reply(seq, "ERR", "could not read the player ship: " .. tostring(ship))
        return
    end
    local oksid, sid = pcall(GetComponentData, ship, "sectorid")
    if not oksid or sid == nil then
        reply(seq, "ERR", "could not read the player sectorid: " .. tostring(sid))
        return
    end
    put("sectorid", tostring(sid))

    -- Q2. Three calls, so the two container forms are each compared against the SAME
    -- galaxy-wide denominator rather than against each other alone.
    local okall, lall = pcall(GetContainedObjectsByOwner, faction)
    put("n.owner_only", okall and count(lall) or ("raised:" .. tostring(lall)))
    local ok64, l64 = pcall(function()
        return GetContainedObjectsByOwner(faction, ConvertStringTo64Bit(tostring(sid)))
    end)
    put("n.sector_via_64bit", ok64 and count(l64) or ("raised:" .. tostring(l64)))
    local oklua, llua = pcall(function()
        return GetContainedObjectsByOwner(faction, ConvertStringToLuaID(tostring(sid)))
    end)
    put("n.sector_via_luaid", oklua and count(llua) or ("raised:" .. tostring(llua)))

    -- Prefer vanilla's form when it works; fall back to the one already measured. Say
    -- WHICH was used, because every number below depends on it and a reader cannot
    -- infer it from the counts.
    local list, used
    if oklua and type(llua) == "table" then list, used = llua, "luaid"
    elseif ok64 and type(l64) == "table" then list, used = l64, "64bit"
    else used = "<neither>" end
    put("used_handle", used)

    -- Q1. THE contract question. Reported as raw strings, not as a verdict: the two
    -- 64-bit forms must be eyeball-comparable, and `roundtrip_isvalid` is the thing
    -- `component <id>` will actually do with whatever we put on the wire.
    if list ~= nil and list[1] ~= nil then
        local obj = list[1]
        put("wire.raw_luaid", tostring(obj))
        put("wire.reference_ffi", tostring(C.GetPlayerOccupiedShipID()))
        local okc, id64 = pcall(ConvertIDTo64Bit, obj)
        put("wire.via_ConvertIDTo64Bit", okc and tostring(id64) or ("raised:" .. tostring(id64)))
        if okc then
            local okr, back = pcall(ConvertStringTo64Bit, tostring(id64))
            put("wire.roundtrip", okr and tostring(back) or ("raised:" .. tostring(back)))
            put("wire.roundtrip_identical", okr and (tostring(back) == tostring(id64)))
            if okr then
                local okv, valid = pcall(IsValidComponent, back)
                put("wire.roundtrip_isvalid", okv and tostring(valid) or ("raised:" .. tostring(valid)))
                local okn, nm = pcall(GetComponentData, back, "name")
                put("wire.roundtrip_name", okn and tostring(nm) or ("raised:" .. tostring(nm)))
            end
        end
    else
        put("wire", "<no objects here for " .. faction .. "; re-run with a faction that has some>")
    end

    -- Q3. Two independent discriminators over the SAME list, plus one independent
    -- engine call over the same question. Three numbers that must agree.
    if list ~= nil then
        local nsh_h, nst_h, nsh_b, nst_b, rows = 0, 0, 0, 0, 0
        local helper_ok, bare_ok = true, true
        for _, obj in ipairs(list) do
            rows = rows + 1
            local okd, cid, rcid = pcall(GetComponentData, obj, "classid", "realclassid")
            if okd then
                local o1, isship = pcall(function() return Helper.isComponentClass(cid, "ship") end)
                local o2, isstat = pcall(function() return Helper.isComponentClass(rcid, "station") end)
                if o1 and isship then nsh_h = nsh_h + 1 end
                if o2 and isstat then nst_h = nst_h + 1 end
                if not (o1 and o2) then helper_ok = false end
            else
                helper_ok = false
            end
            local o3, s3 = pcall(function() return IsComponentClass(obj, "ship") end)
            local o4, s4 = pcall(function() return IsComponentClass(obj, "station") end)
            if o3 and s3 then nsh_b = nsh_b + 1 end
            if o4 and s4 then nst_b = nst_b + 1 end
            if not (o3 and o4) then bare_ok = false end
        end
        put("class.rows_walked", rows)
        put("class.helper_usable", helper_ok)
        put("class.bare_usable", bare_ok)
        put("class.ships_helper", nsh_h)
        put("class.ships_bare", nsh_b)
        put("class.stations_helper", nst_h)
        put("class.stations_bare", nst_b)
    end
    -- The independent control. menu_diplomacy.lua:1925 calls it in exactly this shape,
    -- sector container included. If this disagrees with class.stations_*, one of the
    -- two readings of "station" is wrong and the migration is not ready.
    if type(GetContainedStationsByOwner) == "function" then
        local oks, ls = pcall(function()
            return GetContainedStationsByOwner(faction, ConvertStringToLuaID(tostring(sid)))
        end)
        put("class.stations_engine_control", oks and count(ls) or ("raised:" .. tostring(ls)))
    else
        put("class.stations_engine_control", "<symbol absent>")
    end

    -- Q5 from the plan: is the faction list reachable at all? `objects` with no
    -- faction argument is built on this, and an unexported symbol changes the design.
    for _, n in ipairs({ "GetNumAllFactions", "GetAllFactions" }) do
        local rok, sym = pcall(function() return C[n] end)
        put("C." .. n, rok and type(sym) or "<not exported>")
    end
    -- NB an explicit if, not `okn and nfac or ...`: when the call SUCCEEDS but yields
    -- nil, the and/or form reports "raised:nil" and blames an error that never
    -- happened. A diagnostic that misattributes its own failure is worse than none.
    local okn, nfac = pcall(function() return tonumber(C.GetNumAllFactions(false)) end)
    if not okn then put("n.factions", "raised:" .. tostring(nfac))
    elseif nfac == nil then put("n.factions", "<call ok but not a number>")
    else put("n.factions", nfac) end

    reply(seq, "OK", table.concat(out, "\t"))
end

-- The RAMP INSTRUMENT for the unknown message-size cap. Returns exactly n payload
-- bytes; the Python side ramps n and records where the reply first comes back short.
verbs.echo = function(seq, n)
    local count = tonumber(n)
    if count == nil then reply(seq, "ERR", "echo needs a byte count") return end
    count = math.floor(count)
    if count < 0 then count = 0 end
    if count > ECHO_MAX then
        reply(seq, "ERR", "requested " .. count .. " exceeds ECHO_MAX " .. ECHO_MAX)
        return
    end
    reply(seq, "OK", string.rep("x", count))
end

verbs.errors = function(seq)
    if type(GetNumErrors) ~= "function" then
        reply(seq, "ERR", "GetNumErrors is not a function in this environment")
        return
    end
    local ok, n = pcall(GetNumErrors)
    if not ok then reply(seq, "ERR", "GetNumErrors failed: " .. tostring(n)) return end
    -- A count of zero is reported as OK 0. "none" must never wear the grammar of
    -- "cannot ask" -- that is what the ERR branch above is for.
    reply(seq, "OK", tostring(n))
end

verbs.ext = function(seq, id)
    if id == nil or id == "" then reply(seq, "ERR", "ext needs an extension id") return end
    if type(GetExtensionList) ~= "function" then
        reply(seq, "ERR", "GetExtensionList is not a function in this environment")
        return
    end
    local ok, list = pcall(GetExtensionList)
    if not ok then reply(seq, "ERR", "GetExtensionList failed: " .. tostring(list)) return end
    if type(list) ~= "table" then reply(seq, "ERR", "GetExtensionList returned " .. type(list)) return end
    for _, e in ipairs(list) do
        if type(e) == "table" and tostring(e.id) == id then
            -- Every field, k=v, rather than a hand-picked subset: we do not have to
            -- guess the vocabulary, and a field the engine adds later shows up
            -- instead of being silently dropped.
            local out = {}
            for _, k in ipairs(sorted_keys(e)) do
                local v = e[k]
                out[#out + 1] = k .. "=" .. (type(v) == "table" and "<table>" or tostring(v))
            end
            reply(seq, "OK", table.concat(out, "\t"))
            return
        end
    end
    -- ABSENT is an ANSWER: the engine was asked and this id is not in its list.
    reply(seq, "ABSENT", id)
end

verbs.macro = function(seq, ltype, name, prop)
    if ltype == nil or ltype == "" or name == nil or name == "" then
        reply(seq, "ERR", "macro needs <librarytype> <macroname> [<property>]")
        return
    end
    if type(GetLibraryEntry) ~= "function" then
        reply(seq, "ERR", "GetLibraryEntry is not a function in this environment")
        return
    end
    local ok, entry = pcall(GetLibraryEntry, ltype, name)
    if not ok then reply(seq, "ABSENT", ltype .. "\t" .. name) return end
    if type(entry) ~= "table" then reply(seq, "ABSENT", ltype .. "\t" .. name) return end

    local ks = sorted_keys(entry)
    -- An EMPTY table is an absence, not an answer. Whether GetLibraryEntry raises or
    -- returns {} for an unknown name is not documented, so both are handled --
    -- reporting {} as "OK, no fields" is exactly the narrowing-step-reports-success
    -- shape this workspace keeps finding.
    if #ks == 0 then reply(seq, "ABSENT", ltype .. "\t" .. name) return end

    if prop ~= nil and prop ~= "" then
        local v = entry[prop]
        if v == nil then
            reply(seq, "ABSENT", ltype .. "\t" .. name .. "\t" .. prop)
        else
            reply(seq, "OK", tostring(v))
        end
        return
    end

    local out = {}
    for _, k in ipairs(ks) do
        local v = entry[k]
        out[#out + 1] = k .. "=" .. (type(v) == "table" and "<table>" or tostring(v))
    end
    reply(seq, "OK", table.concat(out, "\t"))
end

-- --------------------------------------------------------------------------- --
-- THE LIVE VIEW -- where am I, and what is out there
-- --------------------------------------------------------------------------- --

--: Read when `component` is called with no explicit field list. Every name here is
--: a literal vanilla passes to GetComponentData; `menu_map.lua:8952` uses this exact
--: shape in one call. NB "class" is NOT a field -- class-as-string comes from
--: ffi.string(C.GetComponentClass(id)), which is a different namespace entirely.
local DEFAULT_FIELDS = {
    "name", "sector", "sectorid", "classid", "realclassid",
    "owner", "ownername", "macro", "isdocked",
}

--: Shared by `player` and the enumerators. Returns a tab-joined "k=v" list.
local function read_fields(id, names)
    local out = {}
    for i = 1, #names do
        local ok, v = pcall(GetComponentData, id, names[i])
        out[#out + 1] = names[i] .. "=" .. (ok and tostring(v) or "<read failed>")
    end
    return out
end

-- Where the player is. Seeds the id allowlist, so it is the entry point for
-- everything else -- `component` cannot be used until something has issued an id.
verbs.player = function(seq)
    if not cdef_ok then
        reply(seq, "ERR", "player needs the ffi cdef block, which did not load")
        return
    end
    local ok, res = pcall(function()
        local ship_raw = C.GetPlayerOccupiedShipID()
        -- The cdata goes to `issue` directly rather than pre-stringified: `wire` is
        -- the ONE place that decides what an id looks like on the pipe.
        local ship_str = issue(ship_raw)
        local ship_id  = ConvertStringTo64Bit(ship_str)

        local out = { "occupiedship=" .. ship_str }
        -- The player ENTITY is a separate id from the ship they are sitting in, and
        -- conflating them is an easy way to inspect the wrong object.
        local pok, p_raw = pcall(C.GetPlayerID)
        if pok then out[#out + 1] = "playerid=" .. issue(p_raw) end

        for _, kv in ipairs(read_fields(ship_id, DEFAULT_FIELDS)) do
            out[#out + 1] = kv
        end
        -- The sector id is issued too: it is what `stations <faction> <sectorid>`
        -- takes, which is how "what is around ME" is actually answered.
        local sok, sect = pcall(GetComponentData, ship_id, "sectorid")
        -- issue_TOKEN: a sector token is a different kind from an object id and must
        -- reach the caller byte-for-byte as the engine wrote it. See issue_token.
        if sok and sect ~= nil then issue_token(tostring(sect)) end

        -- Position is NOT a GetComponentData field (MEASURED: zero such literals in
        -- vanilla); it is an ffi struct return, which is why the cdef carries UIPosRot.
        local ppok, pos = pcall(C.GetObjectPositionInSector, ship_id)
        if ppok and pos ~= nil then
            out[#out + 1] = string.format("pos=%.1f,%.1f,%.1f", pos.x, pos.y, pos.z)
            out[#out + 1] = string.format("rot=%.3f,%.3f,%.3f", pos.yaw, pos.pitch, pos.roll)
        end
        local cok2, cls = pcall(C.GetComponentClass, ship_id)
        if cok2 and cls ~= nil then out[#out + 1] = "class=" .. ffi.string(cls) end
        return out
    end)
    if not ok then reply(seq, "ERR", "player raised: " .. tostring(res)) return end
    reply(seq, "OK", table.concat(res, "\t"))
end

-- The general inspector -- the DevBench surface. Fields are supplied by the CALLER,
-- so the vocabulary stops being something this mod has to predict.
verbs.component = function(seq, id_str, ...)
    if id_str == nil or id_str == "" then
        reply(seq, "ERR", "component needs an id; get one from player, stations or ships")
        return
    end
    if not issued_ids[id_str] then
        --: TWO very different causes produce this one refusal, and they need different
        --: actions from the caller, so name the likelier one instead of making them
        --: guess. MEASURED 2026-08-29: a UI reload -- pressing ALT-ENTER, or loading a
        --: save -- re-executes this chunk and empties the allowlist, so an id that
        --: worked seconds earlier stops resolving with no other symptom. Until this
        --: message existed that was INDISTINGUISHABLE from a fabricated id, and the
        --: refusal pointed at the caller when the cause was a reload.
        local n = 0
        for _ in pairs(issued_ids) do n = n + 1 end
        local why
        if n == 0 then
            why = "NOTHING has been issued by this chunk (loaded at "
                  .. string.format("%.2f", LOADED_AT)
                  .. "), which is exactly what a UI RELOAD looks like: alt-enter or a save "
                  .. "load re-executes this file and empties the allowlist. Re-run player, "
                  .. "stations or ships and use a fresh id."
        else
            why = tostring(n) .. " id(s) are issued by this chunk (loaded at "
                  .. string.format("%.2f", LOADED_AT)
                  .. ") and this is not one of them, so it is most likely mistyped, or left "
                  .. "over from before a UI reload."
        end
        reply(seq, "ERR", "id was not issued by this session, so it will not be sent to the "
              .. "engine. " .. why .. " MEASURED: 0 of 888 vanilla GetComponentData calls pass "
              .. "a foreign id, so the engine's behaviour on one is UNKNOWN in both directions.")
        return
    end
    local ok, id = pcall(ConvertStringTo64Bit, id_str)
    if not ok or id == nil then
        reply(seq, "ERR", "could not convert id " .. tostring(id_str) .. " to a 64-bit handle")
        return
    end
    -- Handles go stale between frames -- vanilla guards this way on values the engine
    -- itself returned, which is exactly our case one frame later.
    if type(IsValidComponent) == "function" then
        local vok, valid = pcall(IsValidComponent, id)
        if not vok then reply(seq, "ERR", "IsValidComponent raised on that id") return end
        if not valid then
            -- ABSENT, never ERR: we asked, and the answer is that it is gone.
            reply(seq, "ABSENT", "no live component with id " .. id_str
                  .. " (issued earlier, so it was probably destroyed or undocked since)")
            return
        end
    end
    local names = {...}
    if #names == 0 then names = DEFAULT_FIELDS end
    reply(seq, "OK", table.concat(read_fields(id, names), "\t"))
end

-- --------------------------------------------------------------------------- --
-- OBJECT FLAGS, and vanilla's own validity test
-- --------------------------------------------------------------------------- --
--
--: ★ WHY THIS EXISTS. MEASURED in game 2026-08-30, a per-object census of every argon
--: object in Argon Prime: of 163 ships, **11** have isknown=true. Of 13 stations, ONE.
--: `"Unknown Ship"` is exactly `isknown=false` (152 = 152, 12 = 12). So ~93% of every
--: reply this channel has ever sent was unlabelled, and nothing said so.
--:
--: The channel is NOT knowledge-limited -- only the LABELS are. Ids, positions, class,
--: owner and every flag come back for all 176. For research that is ground truth, so
--: we do NOT drop them. We report the flags, and we report vanilla's verdict as one
--: more column, letting the reader choose.
--:
--: `is_valid_object` is menu_map.lua:7548-7564 ported VERBATIM -- the clause order, the
--: classid-vs-realclassid split, all of it -- plus the separate mass-traffic drop at
--: menu_map.lua:7419. It is COPIED, not composed: an earlier version of this design
--: guessed a two-field class test and missed five predicates.
local FLAG_FIELDS = {
    "name", "owner", "classid", "realclassid", "sector", "sectorid",
    "isknown", "isradarvisible", "isdeployable", "isorphaned",
    "isattachedaslimpet", "iswreck", "isunit", "ismasstraffic", "isenemy", "isdocked",
}

--: ONE GetComponentData call for all of them. `read_fields` costs a call per field,
--: which is fine for a single `component` query and far too slow per row here.
--: select('#') rather than {f(...)}: a nil in the middle would give the table a hole
--: and silently shorten it, mapping every later value to the WRONG NAME.
--: ⚠ GetComponentData does NOT accept a raw UniverseID cdata, and it does not RAISE on
--: one -- it returns values that are simply not about any object. MEASURED in game
--: 2026-08-30: the --wide path handed it `buf[i]` straight from the ffi array and got
--: `unclassified=1539` out of 1539, i.e. every object unreadable, with `unreadable=0`
--: because nothing failed. The old enumerator always converted first
--: (`ConvertStringTo64Bit(tostring(buf[i]))`) and that is why it worked; dropping the
--: conversion during the rewrite is what broke it.
--:
--: Container objects are LuaIDs (MEASURED: `type(o)` is `userdata`) and vanilla passes
--: those to GetComponentData directly, so they go through untouched. Only the
--: canonical ULL rendering marks an id that still needs converting.
local function readable_id(obj)
    local s = tostring(obj)
    if s:match("^%d+ULL$") then return ConvertStringTo64Bit(s) end
    return obj
end

local function read_flags(obj)
    local id = readable_id(obj)
    local out = {}
    local function collect(...)
        for i = 1, select("#", ...) do out[FLAG_FIELDS[i]] = (select(i, ...)) end
    end
    local ok = pcall(function() collect(GetComponentData(id, table_unpack(FLAG_FIELDS))) end)
    if not ok then return nil end
    return out
end

--: TRI-STATE: true, false, or nil for COULD NOT TELL. nil must never collapse into
--: false -- an object we failed to classify is not an object we classified as "not a
--: ship", and rendering them alike is the silent narrowing this channel exists to
--: refuse.
--:
--: ⚠ FOUND IN GAME 2026-08-30, and it would have shipped: `Helper.isComponentClass`
--: is `componentClassLookup[class1 * 1000 + classIDs[class2]]` (helper.lua:782), so a
--: nil classid is ARITHMETIC ON NIL and raises. Some objects in the galaxy-wide
--: faction list have no class data, so `compare` and `objects --wide` both died on
--: the first one. The container path never hit it, which is exactly why the old path
--: had to stay reachable and be exercised.
local function class_is(v, name)
    if v == nil then return nil end
    if type(Helper) ~= "table" or type(Helper.isComponentClass) ~= "function" then
        return nil
    end
    local ok, r = pcall(Helper.isComponentClass, v, name)
    if not ok then return nil end
    return r and true or false
end

local function is_ship(f)    return class_is(f.classid, "ship") end
local function is_station(f) return class_is(f.realclassid, "station") end

--: Returns true/false, or nil if it could not be decided (Helper missing, or a class
--: lookup raised). nil is NOT false -- "could not tell" and "no" must never render
--: alike, so the row shows `?` and the header counts it separately.
local function is_valid_object(f)
    if type(Helper) ~= "table" or type(Helper.isComponentClass) ~= "function" then
        return nil
    end
    if f.classid == nil or f.realclassid == nil then return nil end
    local ok, verdict = pcall(function()
        local isship = is_ship(f) == true
        if not isship
           and not (is_station(f) and (not f.iswreck))
           and not f.isdeployable
           and not Helper.isComponentClass(f.classid, "lockbox")
           and not Helper.isComponentClass(f.classid, "collectablewares")
           and not (Helper.isComponentClass(f.classid, "buildstorage") and f.isorphaned) then
            return false
        elseif (isship or Helper.isComponentClass(f.classid, "controllable")) and f.isunit then
            return false
        elseif (not f.isknown) or (not f.isradarvisible) then
            return false
        elseif isship and f.isattachedaslimpet then
            return false
        end
        -- menu_map.lua:7419, a SEPARATE drop from isObjectValid and easy to miss:
        -- non-enemy mass traffic is removed from the rendered list.
        if f.ismasstraffic and (not f.isenemy) then return false end
        return true
    end)
    if not ok then return nil end
    return verdict
end

--: Compact, fixed-width flag column, so a row stays cheap against the payload cap and
--: a human can scan it. A letter means true, `-` means false.
local FLAG_LETTERS = {
    { "isknown", "k" }, { "isdocked", "d" }, { "ismasstraffic", "m" },
    { "isunit", "u" }, { "iswreck", "w" }, { "isenemy", "e" },
}
local function flag_string(f, valid)
    local s = {}
    for i = 1, #FLAG_LETTERS do
        local key, letter = FLAG_LETTERS[i][1], FLAG_LETTERS[i][2]
        s[#s + 1] = f[key] and letter or "-"
    end
    s[#s + 1] = (valid == nil) and "?" or (valid and "v" or "-")
    return table.concat(s)
end

-- --------------------------------------------------------------------------- --
-- ENUMERATION -- one primitive, one implementation
-- --------------------------------------------------------------------------- --
--
--: `objects` is the core; `stations` and `ships` are wrappers over it, so there is ONE
--: implementation of the count-then-fill contract rather than two that drift.
--:
--: TWO PATHS, and the header always names which ran:
--:   container (default) -- GetContainedObjectsByOwner(faction [, sector]). The engine
--:                          does the sector filtering. MEASURED: argon 2017 galaxy-wide
--:                          vs 279 in one sector.
--:   wide (--wide)       -- the OLD ffi walk: GetAllFactionShips/Stations over the whole
--:                          galaxy, filtered by sectorid in lua. Kept as an EXPLICIT
--:                          opt-in, never an automatic fallback: an empty sector and a
--:                          failed call must never render alike. It is also the
--:                          reference that `compare` diffs against.

--: The faction list. Verbatim idiom from customgame.lua:4921-4923 (second copy at
--: menu_mapeditor.lua:338). Keep a lua reference to the buffer for as long as it is
--: read -- helper.lua:8956 documents that it can otherwise be collected too early.
--: `hidden` false excludes `civilian` (mass traffic) and `criminal`, which carry
--: tags="hidden" in libraries/factions.xml.
local function faction_list(hidden)
    local n = tonumber(C.GetNumAllFactions(hidden)) or 0
    if n == 0 then return {} end
    local buf = ffi.new("const char*[?]", n)
    local got = tonumber(C.GetAllFactions(buf, n, hidden)) or 0
    local out = {}
    for i = 0, got - 1 do out[#out + 1] = ffi.string(buf[i]) end
    return out
end

--: Gather raw object handles. Returns list, meta -- and meta records what was ASKED as
--: well as what came back, because a faction whose call FAILED is not the same as a
--: faction that owns nothing, and one number cannot say both.
local function gather(opts)
    local ids, seen = {}, {}
    local meta = { factions = 0, failed = {}, dupes = 0 }

    local function take(o)
        -- Dedupe on the RAW handle string: unique per object and free, where `wire`
        -- would cost an engine call per object just to discover there are no dupes.
        local raw = tostring(o)
        if seen[raw] then meta.dupes = meta.dupes + 1 return end
        seen[raw] = true
        ids[#ids + 1] = o
    end

    if opts.wide then
        -- The old path. It needs a named faction: there is no all-factions form of it,
        -- which is part of why the container primitive is the better core.
        local kinds = {}
        if opts.class == "station" or opts.class == "all" then kinds[#kinds + 1] = "stations" end
        if opts.class == "ship"    or opts.class == "all" then kinds[#kinds + 1] = "ships" end
        meta.factions = 1
        meta.total = 0
        for _, kind in ipairs(kinds) do
            local numfn = (kind == "stations") and C.GetNumAllFactionStations or C.GetNumAllFactionShips
            local getfn = (kind == "stations") and C.GetAllFactionStations   or C.GetAllFactionShips
            local total = tonumber(numfn(opts.faction)) or 0
            meta.total = meta.total + total
            if total > 0 then
                local buf = ffi.new("UniverseID[?]", total)
                local got = tonumber(getfn(buf, total, opts.faction)) or 0
                for i = 0, got - 1 do take(buf[i]) end
            end
        end
    else
        local container = nil
        if opts.sector ~= nil then container = ConvertStringToLuaID(tostring(opts.sector)) end
        local factions = opts.faction and { opts.faction } or faction_list(opts.hidden and true or false)
        meta.factions = #factions
        for _, fac in ipairs(factions) do
            -- Per-faction pcall: one faction the engine dislikes must not cost us the
            -- other 26. Failures are NAMED, never absorbed into a smaller number.
            local ok, lst = pcall(GetContainedObjectsByOwner, fac, container)
            if ok and type(lst) == "table" then
                for _, o in ipairs(lst) do take(o) end
            else
                meta.failed[#meta.failed + 1] = fac
            end
        end
        -- The galaxy-wide denominator, for parity with the old header. Only computed
        -- for a single faction: asking it of 27 would mean 54 more galaxy-wide walks,
        -- which is the exact cost this path exists to remove.
        if opts.faction then
            local a = tonumber(C.GetNumAllFactionShips(opts.faction)) or 0
            local b = tonumber(C.GetNumAllFactionStations(opts.faction)) or 0
            -- ⚠ total must count the SAME POPULATION as `enumerated`, or it is not a
            -- denominator, it is a different number standing next to one. MEASURED in
            -- game: class=all gave matched=1909 against total=1813, i.e. MORE matches
            -- than the "total" -- because the container returns every class (drones,
            -- buildstorage, deployables) while GetNumAllFaction* counts only ships and
            -- stations. For a mixed-class query there is no cheap true denominator, so
            -- it says so and reports the ship+station figure under its own name.
            if opts.class == "ship" then meta.total = a
            elseif opts.class == "station" then meta.total = b
            else meta.ships_stations = a + b end
        end
    end
    return ids, meta
end

--: ⚠ THE HEADER IS SPACE-DELIMITED `key=value`, AND A SECTOR TOKEN CONTAINS A SPACE.
--: The engine writes sectorid as `ID: 7479`, so emitting it raw produced
--: `sector=ID: 7479` -- which any consumer splitting on whitespace reads as
--: `sector=ID:` plus a stray `7479`. Caught by a test helper that parses the header
--: the same way a caller would. Whitespace is stripped for the HEADER only; the token
--: is still matched and accepted in its original form everywhere else.
local function header_safe(v)
    return (tostring(v):gsub("%s+", ""))
end

--: Render. Shared by every verb, so the row schema and the budget rule exist once.
local function render(ids, meta, opts)
    local rows, used, shown, matched, nvalid, nundecided = {}, 0, 0, 0, 0, 0
    local capped, nunreadable, nunclassified = false, 0, 0

    for _, obj in ipairs(ids) do
        local f = read_flags(obj)
        if f == nil then
            nunreadable = nunreadable + 1
        else
            local keep
            if opts.class == "all" then
                keep = true
            else
                -- ⚠ NOT `cond and is_ship(f) or is_station(f)`. When is_ship returns
                -- FALSE the and/or form falls through to the `or` branch, so asking
                -- for ships also matched every station. Caught by the class test; the
                -- same trap is documented in the fake's GetComponentData.
                local verdict
                if opts.class == "ship" then verdict = is_ship(f)
                else verdict = is_station(f) end
                if verdict == nil then nunclassified = nunclassified + 1 end
                keep = (verdict == true)
            end
            -- SECTOR filter, only on the wide path: the container path already filtered
            -- engine-side, and re-testing it here would silently hide any disagreement
            -- between the two -- which is precisely what `compare` exists to find.
            if keep and opts.wide and opts.sector ~= nil then
                keep = (tostring(f.sectorid) == tostring(opts.sector))
            end
            if keep then
                matched = matched + 1
                local valid = is_valid_object(f)
                if valid == true then nvalid = nvalid + 1
                elseif valid == nil then nundecided = nundecided + 1 end

                local id_str = wire(obj)
                local id64 = ConvertStringTo64Bit(id_str)
                local px, py, pz = "?", "?", "?"
                local pok, pos = pcall(C.GetObjectPositionInSector, id64)
                if pok and pos ~= nil then
                    px = string.format("%.0f", pos.x)
                    py = string.format("%.0f", pos.y)
                    pz = string.format("%.0f", pos.z)
                end
                local cls = "?"
                local cok, craw = pcall(C.GetComponentClass, id64)
                if cok and craw ~= nil then cls = ffi.string(craw) end

                local row = id_str .. "|" .. cls .. "|" .. (tostring(f.name):gsub("|", "/"))
                            .. "|" .. tostring(f.owner) .. "|" .. tostring(f.sector)
                            .. "|" .. px .. "," .. py .. "," .. pz
                            .. "|" .. flag_string(f, valid)
                -- BOUND BEFORE SENDING: an over-long reply tears the pipe down, so this
                -- is enforced here, never detected afterwards. NB we do NOT break --
                -- stopping the loop would stop counting matches too, and then `matched`
                -- would just be `shown` again, destroying the honest denominator.
                if used + #row + 1 > ROW_BUDGET then
                    capped = true
                else
                    issue(obj)
                    rows[#rows + 1] = row
                    used = used + #row + 1
                    shown = shown + 1
                end
            end
        end
    end

    local header = "shown=" .. shown .. " matched=" .. matched
                   .. " enumerated=" .. #ids
                   .. " total=" .. (meta.total and tostring(meta.total)
                        or (meta.ships_stations
                            and ("n/a(mixed-classes) ships_stations=" .. meta.ships_stations)
                            or "n/a(all-factions)"))
                   .. " sector=" .. (opts.sector and header_safe(opts.sector) or "galaxy")
                   .. " class=" .. opts.class
                   .. " factions=" .. meta.factions
                   .. " hidden=" .. ((not opts.wide) and (opts.hidden and "yes" or "no") or "n/a")
                   .. " path=" .. (opts.wide and "wide" or "container")
                   .. " valid=" .. nvalid
    -- Every narrowing announces itself. These lines appear only when non-zero, but a
    -- zero is genuinely "none of this happened" -- unlike an omitted line, which would
    -- be a silent loss, the one thing this channel must never do.
    if nundecided > 0 then header = header .. " undecided=" .. nundecided end
    if nunreadable > 0 then header = header .. " unreadable=" .. nunreadable end
    if nunclassified > 0 then header = header .. " unclassified=" .. nunclassified end
    if meta.dupes > 0 then header = header .. " dupes_dropped=" .. meta.dupes end
    if #meta.failed > 0 then
        header = header .. " factions_failed=" .. #meta.failed
                 .. "(" .. table.concat(meta.failed, ",") .. ")"
    end
    header = header .. (capped
        and (" CAPPED=yes omitted=" .. (matched - shown)
             .. " (reply cap " .. MAX_PAYLOAD .. " bytes; narrow with a sector, a class"
             .. " or a faction)")
        or " CAPPED=no")
    table.insert(rows, 1, header)

    -- The reserve is an ASSUMPTION about header length; this is the check that makes it
    -- a knowable one rather than a hope.
    local size = #table.concat(rows, "\t")
    if size > MAX_PAYLOAD then
        DebugError("X4TOOLKIT_LIVE payload " .. size .. " EXCEEDS the " .. MAX_PAYLOAD
                   .. "-byte budget; HEADER_RESERVE (" .. HEADER_RESERVE
                   .. ") is too small for a " .. #header .. "-byte header")
    end
    return rows
end

--: Pull the flag tokens out of the positional arguments. They may appear anywhere, so
--: a caller need not remember an order that exists only inside our parser.
local function split_flags(...)
    local opts, pos = { hidden = false, wide = false, contents = false }, {}
    for _, a in ipairs({ ... }) do
        if a == "--hidden" then opts.hidden = true
        elseif a == "--wide" then opts.wide = true
        elseif a == "--contents" then opts.contents = true
        elseif a ~= nil and a ~= "" then pos[#pos + 1] = a end
    end
    return opts, pos
end

local VALID_CLASSES = { ship = true, station = true, all = true }

--: ★ AN INVALID CONTAINER IS SILENTLY IGNORED BY THE ENGINE, AND YOU GET THE WHOLE
--: GALAXY BACK LABELLED AS YOUR SECTOR. MEASURED in game 2026-08-30, same faction,
--: seconds apart:
--:     objects "ID: 514068" -> 310 objects   (correctly scoped)
--:     objects "ID:"        -> 1961 objects  labelled sector=ID:
--:     objects "NOT_A_SECTOR" -> 1961        labelled sector=NOT_A_SECTOR
--: No error, no flag, 6x the data. This is the narrowing-without-announcement defect
--: inverted: a step that FAILED to narrow, reporting as though it had. Sector tokens
--: change every launch, so a stale one is the normal case, not an exotic one.
--:
--: So the shape is checked HERE rather than trusted. `-`/`galaxy` are already resolved
--: to nil before this and mean the galaxy deliberately, which is a different thing
--: from a token that did not work.
local function bad_sector_token(tok)
    if tok == nil then return nil end
    if tostring(tok):match("^ID:%s*%d+$") then return nil end
    return "sector token '" .. tostring(tok) .. "' is not the shape the engine uses "
           .. "(ID: <digits>, as `player` reports it). An unrecognised container is "
           .. "SILENTLY IGNORED by the engine and would return every object the owner "
           .. "has anywhere, labelled as this sector -- MEASURED 310 vs 1961. Re-read "
           .. "the token from `player`; they change every launch. Use - for the galaxy."
end

local function run_enumeration(seq, opts)
    if not cdef_ok then
        reply(seq, "ERR", "enumeration needs the ffi cdef block, which did not load")
        return
    end
    local bad = bad_sector_token(opts.sector)
    if bad then reply(seq, "ERR", bad) return end
    if opts.wide and not opts.faction then
        reply(seq, "ERR", "--wide is the old per-faction walk and has no all-factions "
                          .. "form; name a faction")
        return
    end
    if not opts.wide and type(GetContainedObjectsByOwner) ~= "function" then
        reply(seq, "ERR", "GetContainedObjectsByOwner is absent; retry with --wide "
                          .. "(which needs a faction)")
        return
    end
    local ok, res = pcall(function()
        local ids, meta = gather(opts)
        return render(ids, meta, opts)
    end)
    if not ok then reply(seq, "ERR", "enumeration raised: " .. tostring(res)) return end
    reply(seq, "OK", table.concat(res, "\t"))
end

--: objects <sector> [class] [faction] [--hidden] [--wide]
--: A sector of - or galaxy means no container: every object the owner(s) hold.
--:
--: NOT A CENSUS, and the header says so. Ownerless objects (wrecks, lockboxes,
--: asteroids) belong to no faction and are invisible to ANY owner query; hidden
--: factions are opt-in; and name/sector are player-knowledge, so MEASURED ~93% come
--: back "Unknown" while ids, positions, class and flags stay exact.
verbs.objects = function(seq, ...)
    local opts, pos = split_flags(...)
    local sector, class, faction = pos[1], pos[2], pos[3]
    if sector == nil then
        reply(seq, "ERR", "objects needs a sector token, the one `player` reports as "
                          .. "sectorid, or - for the whole galaxy")
        return
    end
    if sector == "-" or sector == "galaxy" then sector = nil end
    class = class or "all"
    if not VALID_CLASSES[class] then
        reply(seq, "ERR", "class must be ship, station or all -- got " .. tostring(class))
        return
    end
    opts.sector, opts.class, opts.faction = sector, class, faction
    run_enumeration(seq, opts)
end

verbs.stations = function(seq, faction, ...)
    local opts, pos = split_flags(...)
    if faction == nil or faction == "" then
        reply(seq, "ERR", "stations needs a faction id, e.g. stations argon")
        return
    end
    opts.sector, opts.class, opts.faction = pos[1], "station", faction
    run_enumeration(seq, opts)
end

verbs.ships = function(seq, faction, ...)
    local opts, pos = split_flags(...)
    if faction == nil or faction == "" then
        reply(seq, "ERR", "ships needs a faction id, e.g. ships argon")
        return
    end
    opts.sector, opts.class, opts.faction = pos[1], "ship", faction
    run_enumeration(seq, opts)
end

-- --------------------------------------------------------------------------- --
-- `compare <faction> <sector>` -- the ATOMIC old-vs-new proof
-- --------------------------------------------------------------------------- --
--
--: ★ WHY THIS IS ONE CALL AND NOT TWO QUERIES. MEASURED 2026-08-30: argon went from
--: 1931 to 2017 owned objects in about five minutes -- mass traffic spawns and
--: despawns continuously. So a diff between two SEPARATE queries shows hundreds of
--: differences that are pure drift, with no way to tell them from a real difference
--: between the two enumeration methods. The comparison is only meaningful if both
--: enumerations happen in the SAME lua call, in the same frame. It cost one wrong plan
--: to notice that, and the earlier "contradiction" that prompted it (23 in-sector
--: objects that could not fit in 13 galaxy-wide) turned out to be drift too.
--:
--: Both sides are restricted to ship|station, because the wide path CANNOT return
--: anything else -- comparing it against an unrestricted container list would report
--: every drone as a difference and prove nothing.
--:
--: `wire_same_object` renders ONE object present in BOTH sets through both conversion
--: paths. That is the measurement that settles whether the ffi and bare-global id
--: forms really differ; up to here it was inferred from two DIFFERENT objects.
local COMPARE_ROWS = 12

verbs.compare = function(seq, faction, sector)
    if not cdef_ok then
        reply(seq, "ERR", "compare needs the ffi cdef block, which did not load")
        return
    end
    if faction == nil or faction == "" or sector == nil or sector == "" then
        reply(seq, "ERR", "compare needs a faction and a sector token, e.g. "
                          .. "compare argon <the sectorid player reports>")
        return
    end
    if type(GetContainedObjectsByOwner) ~= "function" then
        reply(seq, "ERR", "GetContainedObjectsByOwner is absent; nothing to compare")
        return
    end
    -- The same guard as run_enumeration: an unrecognised container silently widens the
    -- container side to the whole galaxy, which here would manufacture a huge bogus
    -- new_only set and read as a method difference.
    local bad = bad_sector_token(sector)
    if bad then reply(seq, "ERR", bad) return end
    local ok, res = pcall(function()
        local old_raw = gather({ wide = true,  class = "all", faction = faction, sector = sector })
        local new_raw = gather({ wide = false, class = "all", faction = faction, sector = sector })

        local old_set, new_set, flags = {}, {}, {}
        local luaid_type, old_type = "<none>", "<none>"
        local n_old_unreadable, n_new_unreadable = 0, 0

        for _, o in ipairs(old_raw) do
            if old_type == "<none>" then old_type = type(o) end
            local f = read_flags(o)
            if f == nil then n_old_unreadable = n_old_unreadable + 1
            elseif (is_ship(f) == true or is_station(f) == true)
                   and tostring(f.sectorid) == tostring(sector) then
                local k = wire(o)
                old_set[k] = o
                flags[k] = f
            end
        end
        for _, o in ipairs(new_raw) do
            if luaid_type == "<none>" then luaid_type = type(o) end
            local f = read_flags(o)
            if f == nil then n_new_unreadable = n_new_unreadable + 1
            elseif is_ship(f) == true or is_station(f) == true then
                local k = wire(o)
                new_set[k] = o
                flags[k] = flags[k] or f
            end
        end

        local n_old, n_new, n_both = 0, 0, 0
        local only_old, only_new, common = {}, {}, nil
        for k in pairs(old_set) do
            n_old = n_old + 1
            if new_set[k] then
                n_both = n_both + 1
                common = common or k
            else
                only_old[#only_old + 1] = k
            end
        end
        for k in pairs(new_set) do
            n_new = n_new + 1
            if not old_set[k] then only_new[#only_new + 1] = k end
        end

        -- THE wire-form measurement, on ONE object that both paths returned.
        local wire_verdict
        if common == nil then
            wire_verdict = "<no object in both sets>"
        else
            local raw_old = tostring(old_set[common])
            local okc, conv = pcall(ConvertIDTo64Bit, new_set[common])
            local raw_new = okc and tostring(conv) or ("raised:" .. tostring(conv))
            wire_verdict = (raw_old == raw_new)
                and ("identical(" .. raw_old .. ")")
                or ("DIFFERS ffi=" .. raw_old .. " bare=" .. raw_new)
        end

        local out = {
            "old=" .. n_old .. " new=" .. n_new .. " both=" .. n_both
            .. " old_only=" .. #only_old .. " new_only=" .. #only_new
            .. " sector=" .. header_safe(sector) .. " faction=" .. header_safe(faction)
            .. " old_type=" .. old_type .. " new_type=" .. luaid_type
            .. " old_unreadable=" .. n_old_unreadable
            .. " new_unreadable=" .. n_new_unreadable,
            "wire_same_object=" .. wire_verdict,
        }
        -- The rows are the DIAGNOSIS, not decoration: if every old_only row carries `d`
        -- then the container form excludes docked ships, and that is the answer.
        local function dump(label, keys)
            for i = 1, math.min(#keys, COMPARE_ROWS) do
                local k = keys[i]
                local f = flags[k]
                out[#out + 1] = label .. "=" .. k .. "|" .. tostring(f and f.name)
                                .. "|" .. (f and flag_string(f, is_valid_object(f)) or "?")
            end
            if #keys > COMPARE_ROWS then
                out[#out + 1] = label .. "_truncated=" .. (#keys - COMPARE_ROWS)
            end
        end
        dump("old_only", only_old)
        dump("new_only", only_new)
        return out
    end)
    if not ok then reply(seq, "ERR", "compare raised: " .. tostring(res)) return end
    reply(seq, "OK", table.concat(res, "\t"))
end
-- --------------------------------------------------------------------------- --
-- THE CAPABILITY HARVEST -- ask the ENGINE what it will answer; enumerate, do not guess
-- --------------------------------------------------------------------------- --
--
--: WHY THESE EXIST. Every capability this channel has gained was found by GUESSING a
--: name out of vanilla and trying it. That works, and it has a hard ceiling: it can only
--: ever confirm names somebody already thought of, so "the engine has no such thing" and
--: "nobody asked" produce an identical silence. MEASURED 2026-08-30: vanilla's
--: ui/addons passes 182 distinct field literals to GetComponentData across 886 call
--: sites; this mod reads 16. The gap is not knowledge, it is that nothing ever
--: ENUMERATED the surface.
--:
--: `globals` lists what the engine actually injected. `galaxyprobe` asks the container
--: and sector primitives what they DO rather than assuming from vanilla usage. Neither
--: builds anything on the answers: this is a harvest, and the fixture it produces is
--: what a later design gets to reason from.

--: NAMES AND TYPES ONLY -- THIS VERB NEVER CALLS WHAT IT FINDS. An unknown global may
--: mutate game state, and this mod is read-only by contract. `type(v)` cannot run it;
--: `v()` can. There is deliberately no "call it and see" mode, and adding one would
--: change what this mod IS.
--:
--: Paged by BYTES rather than by row count, because the cap is a byte cap and an
--: over-long reply tears the pipe down instead of truncating.
--: ZERO-ARG, vanilla-attested, read-shaped, UI-widget names filtered out.
local RECON_ZERO = {
    "GetActiveGuidanceMissionComponent", "GetActiveMission", "GetAdapterOption",
    "GetAimAssistOption", "GetAllExtensionSettings", "GetAllStatIDs",
    "GetAutoPilotTarget", "GetAutorollOption", "GetAutosaveOption",
    "GetBonusContentData", "GetBoostToggleOption", "GetCaptureHQOption",
    "GetCollisionAvoidanceAssistOption", "GetControllerInfo", "GetCrashReportOption",
    "GetCurRealTime", "GetCurTime", "GetDeadzoneOption", "GetDistortionOption",
    "GetEffectDistanceOption", "GetExtensionList", "GetFOVOption",
    "GetFullscreenOption", "GetGamepadModeOption", "GetGammaOption",
    "GetGfxQualityOption", "GetGlobalSyncSetting", "GetGlowOption", "GetHoloMapColors",
    "GetInputActionMap", "GetInputProfiles", "GetInputRangeMap", "GetInputStateMap",
    "GetJoysticksOption", "GetLODOption", "GetLoadingInfo",
    "GetMappedJoysticks", "GetMenuParameters2", "GetNumErrors", "GetNumMissions",
    "GetPersonalizedCrashReportsOption", "GetPossibleAdapters",
    "GetPossibleResolutions", "GetRadarOption", "GetRegisteredModules",
    "GetResolutionOption", "GetRumbleOption", "GetSSAOOption",
    "GetShaderQualityOption", "GetShadowOption", "GetSoftShadowsOption",
    "GetSoundOption", "GetSteeringNoteOption", "GetStopShipInMenuOption",
    "GetSubtitleOption",
    "GetTradeShipList", "GetUISafeModeOption",
    "GetVentureOutcomes", "GetVersionString", "HasFlightControl", "IsCheatVersion",
    "IsDialogActive", "IsFirstPerson", "IsLuaDebugInputEnabled",
    "IsOnlineSavePossible", "IsSofttargetLocked", "IsSteamworksEnabled"
}

--: ONE-ARG taking a COMPONENT/OBJECT id. Probed with ids this session issued.
local RECON_OBJ = {
    "CanViewLiveData", "GetAllCommanders", "GetAllWeapons",
    "GetAmmoCountAfterTradeOrders", "GetBuildAnchor", "GetCollectableData",
    "GetCommander", "GetControlEntity", "GetNPCs",
    "GetPrioritizedPlatformNPCs", "GetProductionModules", "GetStorageData",
    "GetSubordinates", "GetUnitStorageData",
    "GetWorkForceRaceResources", "IsComponentOperational"
}

--: ONE-ARG taking a MACRO NAME -- NOT an object id.
--:
--: F88. `GetMacroUnitStorageCapacity` sat in RECON_OBJ until 2026-08-31 and was called
--: with an object id. It returned `OK number:0`: a benign-looking WRONG ANSWER with no
--: error raised, which is F86's shape exactly, and `0` is indistinguishable from "this
--: ship carries no units" -- which is why nothing caught it.
--:
--: Vanilla passes it a MACRO, two ways, and we copy the second verbatim rather than
--: compose one:
--:     menu_map.lua:10461  GetMacroUnitStorageCapacity(menu.macro)
--:     menu_map.lua:10468  GetMacroUnitStorageCapacity(GetComponentData(id, "macro"))
--:
--: The lesson generalises past this one name: a probe list keyed on ARGUMENT POSITION
--: is not keyed on anything. What decides the bucket is what VANILLA PASSES.
local RECON_MACRO = {
    "GetMacroUnitStorageCapacity",
    -- F88, FIFTH instance, found 2026-08-31 by re-deriving the whole list
    -- rather than trusting the one name that had been proven. Vanilla:
    --   menu_map.lua:30321  GetTransportUnitMacros(GetComponentData(
    --                         ship.shipid, "macro"))
    -- It sat in RECON_OBJ and was called with an object id. Live, it returned
    -- `OK|` -- EMPTY, not an error. Same silent shape as the original.
    "GetTransportUnitMacros"
}

--: ONE-ARG taking a FACTION id.
local RECON_FAC = {
    "GetOwnLicences", "IsFactionKnown"
}

--: ★★ RECON -- the ONLY verb in this mod that CALLS what it enumerates, and the rules
--: that make that safe are not negotiable.
--:
--: `globals` deliberately never calls: an unknown engine global may mutate state. This
--: verb calls, so every name it touches had to earn it three ways:
--:   1. READ-SHAPED by name (Get/Is/Has/Find/Are/Can). Set/Add/Remove/... never appear.
--:   2. ATTESTED IN VANILLA -- MEASURED over 81 vanilla ui lua files. 46 of the 308
--:      candidates are NOT called anywhere in vanilla and are therefore NOT probed.
--:      "It exists in _G" is not evidence that calling it is safe.
--:   3. CALLED WITH THE ARGUMENT SHAPE VANILLA PASSES, derived from vanilla's own call
--:      sites rather than guessed -- zero-arg, an object id, or a faction id.
--: UI-widget names (Frame/Widget/Render/Texture/Mouse/Cursor/Row/Cell/...) are filtered
--: out: they are not world data and poking the live UI is not recon.
--:
--: ⚠ THE LIST IS HARDCODED ON PURPOSE. A verb that calls a caller-supplied name would be
--: an arbitrary-execution primitive wearing a read-only label -- the one thing this mod
--: must never become. Adding a name is a code change, reviewed like any other.
--:
--: Results are SUMMARISED, never dumped: a table becomes its length, a string its first
--: 40 characters. Some of these return the whole extension list or every stat id, and an
--: over-long reply tears the pipe down rather than truncating.
--: ONE-ARG-PAIR taking a CONTAINER, non-owner-scoped. The four the engine EXPORTS and
--: vanilla NEVER CALLS, plus the one it does.
--:
--: Attestation, MEASURED over 81 vanilla ui lua files -- and it is UNEVEN, which is the
--: whole reason this list is separate and the results are RECORDED, NOT CONCLUDED:
--:     GetContainedStations              7 vanilla sites, shape (container, boolean)
--:     GetContainedShips                 0 sites -- signature INFERRED from its sibling
--:     GetContainedShipsByOwner          0 sites -- shape (owner, container) inferred
--:     GetContainedSpacesByOwner         0 sites -- same
--:     GetContainedBuildStoragesByOwner  1 site,  shape (owner, container)
--:
--: "It exists in _G" is not evidence that calling it is safe, and it is certainly not
--: evidence about its ARGUMENTS -- F88 was exactly a wrong-argument call that answered
--: `OK number:0`. So every call here is pcall'd, an ERR is a RECORDED RESULT rather than
--: a failure, and nothing downstream is built on any of it in this build.
local CENSUS_CONTAINER = { "GetContainedStations", "GetContainedShips" }
local CENSUS_BYOWNER = { "GetContainedStationsByOwner", "GetContainedShipsByOwner",
                         "GetContainedSpacesByOwner", "GetContainedBuildStoragesByOwner" }

--: censusprobe <sector> [faction] [--hidden]
--:
--: ★ THE QUESTION. Our enumeration verbs are owner-scoped and the manifest says so:
--: ownerless objects are invisible to ANY owner query, hidden factions are opt-in, and
--: ~93% of names come back Unknown. MEASURED 2026-08-31 over all 803 engine functions:
--: there is NO ownerless-object enumerator, so that first cause is PERMANENT. This verb
--: attacks the SECOND cause only -- do the non-owner-scoped calls see factions the
--: per-faction walk misses?
--:
--: ★ IT COMPARES SETS, NOT COUNTS. Two totals can agree by coincidence while naming
--: different objects, and a count is exactly the aggregate a real difference hides in.
--: So it reports |A|, |B|, |A-B| and |B-A| per pair. A row of four zeroes is a real
--: answer; two equal totals alone would not be.
verbs.censusprobe = function(seq, ...)
    local opts, pos = split_flags(...)
    local sector = pos[1]
    if sector == nil then
        reply(seq, "ERR", "censusprobe needs a sector token, the one `player` reports "
                          .. "as sectorid, or - for the whole galaxy")
        return
    end
    if sector == "-" or sector == "galaxy" then sector = nil end

    -- F85: an unrecognised container is SILENTLY IGNORED and you get the whole galaxy
    -- back labelled as your sector. Same guard as `objects`, called not re-written.
    local bad = bad_sector_token(sector)
    if bad then reply(seq, "ERR", bad) return end

    local container = nil
    if sector ~= nil then container = ConvertStringToLuaID(tostring(sector)) end

    local out = {}
    local function count_of(v)
        if type(v) ~= "table" then return nil end
        local n = 0
        for _ in pairs(v) do n = n + 1 end
        return n
    end
    -- Keeps the OBJECT beside its key. A set of `tostring` handles can be diffed but
    -- not followed; to say WHICH objects differ we have to hand back real ids, and
    -- those must go through `issue` so a later `component` call will accept them.
    local function idset(v)
        local s, objs, n = {}, {}, 0
        if type(v) ~= "table" then return s, 0, objs end
        for _, o in ipairs(v) do
            local k = tostring(o)
            if not s[k] then s[k] = true objs[k] = o n = n + 1 end
        end
        return s, n, objs
    end
    local function only_in(a, b)
        local n = 0
        for k in pairs(a) do if not b[k] then n = n + 1 end end
        return n
    end

    -- 1. the container-scoped pair, BOTH booleans. Vanilla only ever passes `true`, so
    --    `false` is a GUESS and is labelled one in the output.
    local sets, objmaps = {}, {}
    for _, name in ipairs(CENSUS_CONTAINER) do
        local fn = _G[name]
        if type(fn) ~= "function" then
            out[#out + 1] = name .. "|ABSENT|not a function in this chunk"
        else
            for _, flag in ipairs({ true, false }) do
                local ok, res = pcall(fn, container, flag)
                if not ok then
                    out[#out + 1] = name .. "(container," .. tostring(flag)
                        .. ")|RAISED|" .. tostring(res):sub(1, 60):gsub("[|\t\n\r]", " ")
                else
                    local s, n, objs = idset(res)
                    objmaps[name .. (flag and ":true" or ":false")] = objs
                    -- BOTH sets are kept. The first version stored only the `true` one
                    -- and MEASURED 2026-08-31 that `true` is the RESTRICTIVE argument
                    -- (stations 1 vs 19, ships 23 vs 169) -- so the comparison was
                    -- running against a filtered set and answering a narrower question
                    -- than the one available. Keeping one set was the bug.
                    sets[name .. (flag and ":true" or ":false")] = s
                    out[#out + 1] = name .. "(container," .. tostring(flag) .. ")|OK|n="
                        .. n .. " type=" .. type(res)
                        .. (flag and " [vanilla-attested arg]" or " [GUESSED arg]")
                end
            end
        end
    end

    -- 2. the owner-scoped baseline, summed per faction, as a SET
    -- An explicit faction scopes the owner-scoped side to one owner, exactly as
    -- `objects <sector> [class] [faction]` does. Useful live (one faction is a much
    -- cheaper comparison) and it is the seam the tests use, so no test-only branch has
    -- to exist in shipped code.
    local factions = pos[2] and { pos[2] }
                     or faction_list(opts.hidden and true or false)
    local owner_sets, failed = {}, {}
    for _, name in ipairs(CENSUS_BYOWNER) do
        local fn = _G[name]
        if type(fn) ~= "function" then
            out[#out + 1] = name .. "|ABSENT|not a function in this chunk"
        else
            local acc, nfail = {}, 0
            for _, fac in ipairs(factions) do
                local ok, lst = pcall(fn, fac, container)
                if ok and type(lst) == "table" then
                    for _, o in ipairs(lst) do acc[tostring(o)] = true end
                else
                    nfail = nfail + 1
                end
            end
            local n = 0
            for _ in pairs(acc) do n = n + 1 end
            owner_sets[name] = acc
            failed[name] = nfail
            out[#out + 1] = name .. "(each faction, container)|OK|distinct=" .. n
                .. " factions=" .. #factions .. " faction_failures=" .. nfail
        end
    end

    -- 3. THE COMPARISON, per item. This is the row the verb exists for.
    local PAIRS = {}
    for _, base in ipairs({ { "GetContainedStations", "GetContainedStationsByOwner" },
                            { "GetContainedShips", "GetContainedShipsByOwner" } }) do
        for _, fl in ipairs({ "true", "false" }) do
            PAIRS[#PAIRS + 1] = { base[1] .. ":" .. fl, base[2], base[1] }
        end
    end
    for _, p in ipairs(PAIRS) do
        local a, b = sets[p[1]], owner_sets[p[2]]
        if #factions == 0 then
            -- ★ THE COMPARISON IS VACUOUS WITHOUT FACTIONS, AND IT FAILS TOWARDS THE
            -- CONCLUSION WE ARE HUNTING. With an empty faction list the owner-scoped
            -- side is empty by construction, so every container-scoped id lands in
            -- `container_only` and the row reads "the non-owner call sees N objects the
            -- per-faction walk missed" -- the exact finding this verb exists to test
            -- for, manufactured out of nothing. Found by a test that went red for the
            -- right reason.
            out[#out + 1] = "CMP:" .. p[1] .. "-vs-" .. p[2]
                .. "|SKIPPED|faction list is EMPTY, so the owner-scoped side is "
                .. "vacuously empty and ANY difference would be an artifact of that, "
                .. "not a finding"
        elseif a == nil or b == nil then
            out[#out + 1] = "CMP:" .. p[1] .. "-vs-" .. p[2]
                .. "|SKIPPED|one side did not return a table"
        else
            local na, nb = 0, 0
            for _ in pairs(a) do na = na + 1 end
            for _ in pairs(b) do nb = nb + 1 end
            -- NAME the container-only objects, not just count them. An unexplained
            -- remainder is a lead however small, and "4 ships no faction owns" is a
            -- number; "these 4 ids" is something you can follow with `component`.
            -- Bounded, and it says how many it withheld.
            local names, extra = {}, 0
            for k in pairs(a) do
                if not b[k] then
                    if #names < 12 and objmaps[p[1]] and objmaps[p[1]][k] then
                        names[#names + 1] = issue(objmaps[p[1]][k])
                    else extra = extra + 1 end
                end
            end
            out[#out + 1] = "CMP:" .. p[1] .. "-vs-" .. p[2] .. "|OK|"
                .. "container_only=" .. only_in(a, b)
                .. " owner_only=" .. only_in(b, a)
                .. " n_container=" .. na .. " n_owner=" .. nb
                .. (#names > 0 and (" container_only_ids=" .. table.concat(names, ",")
                    .. (extra > 0 and (" +" .. extra .. "-unnamed") or "")) or "")
        end
    end

    -- Is the `true` reply a strict SUBSET of the `false` reply? That is the shape a
    -- pure FILTER would have. If it is not a subset, `true` is selecting a different
    -- population rather than narrowing one, and no filter story explains it.
    for _, base in ipairs({ "GetContainedStations", "GetContainedShips" }) do
        local t, f = sets[base .. ":true"], sets[base .. ":false"]
        if t ~= nil and f ~= nil then
            local nt, outside = 0, 0
            for k in pairs(t) do
                nt = nt + 1
                if not f[k] then outside = outside + 1 end
            end
            out[#out + 1] = "SUBSET:" .. base .. "|OK|true_n=" .. nt
                .. " true_not_in_false=" .. outside
                .. (outside == 0 and " [true IS a subset of false -- filter-shaped]"
                                 or " [NOT a subset -- different population, not a filter]")
        end
    end

    local shown, used, capped = 0, 0, false
    local rows = {}
    for _, r in ipairs(out) do
        if used + #r + 1 > ROW_BUDGET then capped = true
        else rows[#rows + 1] = r used = used + #r + 1 shown = shown + 1 end
    end
    table.insert(rows, 1, "shown=" .. shown .. " rows=" .. #out
        .. " sector=" .. (sector and header_safe(sector) or "galaxy")
        .. " factions=" .. #factions
        .. " hidden=" .. (opts.hidden and "yes" or "no")
        .. (capped and (" CAPPED=yes omitted=" .. (#out - shown)) or " CAPPED=no"))
    reply(seq, "OK", table.concat(rows, "\t"))
end

verbs.recon = function(seq, ...)
    local opts, pos = split_flags(...)
    local id_a, id_b, faction = pos[1], pos[2], pos[3]
    local out, nok, nraise, nabsent, nmacro = {}, 0, 0, 0, 0

    --: `--contents` -- OPT-IN, BOUNDED, SCALAR LEAVES ONLY, ONE LEVEL DEEP. All four
    --: words are load-bearing:
    --:  * OPT-IN, because 109 recorded calls in recon-20260830-211605.tsv were taken
    --:    with the shape-only summary. Changing the default silently would make this
    --:    run and that fixture non-comparable while looking like the same command.
    --:  * BOUNDED, because an over-long reply does NOT truncate -- it TEARS THE PIPE
    --:    DOWN (F74), costing the whole connection rather than a few bytes off the end.
    --:  * SCALAR LEAVES ONLY / ONE LEVEL, so there is NO RECURSION TO GUARD. A cyclic
    --:    engine table cannot hang us because we never descend into one. A nested table
    --:    renders as `<table>` -- an honest "there is more here", not a silent omission.
    --: Keys are SORTED so two runs are diffable; an engine table's pairs() order is not
    --: guaranteed stable and an unstable order would make every diff look like a change.
    local function render_contents(v)
        local ks = {}
        for k in pairs(v) do ks[#ks + 1] = k end
        table.sort(ks, function(a, b) return tostring(a) < tostring(b) end)
        local parts, used, shown = {}, 0, 0
        for _, k in ipairs(ks) do
            local val, vt = v[k], type(v[k])
            local r
            if vt == "number" or vt == "boolean" then r = tostring(val)
            elseif vt == "string" then
                r = (#val > 40) and (val:sub(1, 40) .. "..") or val
            else r = "<" .. vt .. ">" end
            local cell = (tostring(k) .. "=" .. r):gsub("[|\t\n\r,]", " ")
            if used + #cell + 1 > CONTENTS_BUDGET then break end
            parts[#parts + 1] = cell
            used = used + #cell + 1
            shown = shown + 1
        end
        return "{" .. table.concat(parts, ",") .. "}"
               .. ((shown < #ks) and (" +" .. (#ks - shown) .. "-more") or "")
    end

    local function summarize(v)
        local t = type(v)
        if t == "nil" then return "nil" end
        if t == "table" then
            local keys = 0
            for _ in pairs(v) do keys = keys + 1 end
            local s = "table[#" .. #v .. ",keys=" .. keys .. "]"
            if opts.contents then s = s .. render_contents(v) end
            return s
        end
        if t == "string" then
            return "string:" .. #v .. ":" .. (v:sub(1, 40):gsub("[|\t\n\r]", " "))
        end
        if t == "boolean" or t == "number" then return t .. ":" .. tostring(v) end
        return t
    end

    local function try(label, name, ...)
        local fn = _G[name]
        if type(fn) ~= "function" then
            nabsent = nabsent + 1
            out[#out + 1] = label .. "|ABSENT|not a function in this chunk"
            return
        end
        local ok, a, b = pcall(fn, ...)
        if not ok then
            nraise = nraise + 1
            out[#out + 1] = label .. "|RAISED|" .. tostring(a):sub(1, 70):gsub("[|\t\n\r]", " ")
        else
            nok = nok + 1
            local s = summarize(a)
            if b ~= nil then s = s .. " +" .. summarize(b) end
            out[#out + 1] = label .. "|OK|" .. s
        end
    end

    for _, n in ipairs(RECON_ZERO) do try(n .. "()", n) end

    -- Object-id probes run against ids THIS SESSION ISSUED, for the same reason
    -- `component` refuses a foreign id: vanilla never passes one, so the engine's
    -- behaviour on a fabricated id is unknown in both directions.
    for _, id_str in ipairs({ id_a, id_b }) do
        if id_str ~= nil and id_str ~= "" then
            if not issued_ids[id_str] then
                out[#out + 1] = "id:" .. tostring(id_str) .. "|SKIPPED|not issued by this session"
            else
                local cok, id = pcall(ConvertStringTo64Bit, id_str)
                if cok and id ~= nil then
                    for _, n in ipairs(RECON_OBJ) do
                        try(n .. "(" .. id_str .. ")", n, id)
                    end
                    -- F88: the MACRO-arg probes need a macro, and the only vanilla-
                    -- attested way to get one from an object is menu_map.lua:10468.
                    -- If that hop fails we record the FAILURE and skip -- we do NOT
                    -- fall back to passing the object id, which is the bug this fixes.
                    local mok, macro = pcall(GetComponentData, id, "macro")
                    if mok and type(macro) == "string" and macro ~= "" then
                        nmacro = nmacro + 1
                        for _, n in ipairs(RECON_MACRO) do
                            try(n .. "('" .. macro .. "')", n, macro)
                        end
                    else
                        out[#out + 1] = "macro-for:" .. id_str
                            .. "|SKIPPED|GetComponentData(id,'macro') gave "
                            .. type(macro) .. " -- MACRO probes not run for this id"
                    end
                end
            end
        end
    end

    local fac = faction or "argon"
    for _, n in ipairs(RECON_FAC) do try(n .. "('" .. fac .. "')", n, fac) end

    local shown, used, capped = 0, 0, false
    local rows = {}
    for _, r in ipairs(out) do
        if used + #r + 1 > ROW_BUDGET then
            capped = true
        else
            rows[#rows + 1] = r
            used = used + #r + 1
            shown = shown + 1
        end
    end
    local header = "shown=" .. shown .. " called=" .. #out
                   .. " ok=" .. nok .. " raised=" .. nraise .. " absent=" .. nabsent
                   .. " zero=" .. #RECON_ZERO .. " perobj=" .. #RECON_OBJ
                   .. " permacro=" .. #RECON_MACRO .. " macros_resolved=" .. nmacro
                   .. " contents=" .. (opts.contents and "yes" or "no")
                   .. " faction=" .. fac
                   .. (capped and (" CAPPED=yes omitted=" .. (#out - shown)) or " CAPPED=no")
    table.insert(rows, 1, header)
    reply(seq, "OK", table.concat(rows, "\t"))
end

verbs.globals = function(seq, prefix, page)
    local want = nil
    if prefix ~= nil and prefix ~= "" and prefix ~= "-" then
        want = tostring(prefix):lower()
    end
    local pg = tonumber(page) or 1
    if pg < 1 then pg = 1 end

    local all, ntotal, nfun = {}, 0, 0
    local ok, err = pcall(function()
        for k, v in pairs(_G) do
            ntotal = ntotal + 1
            local name = tostring(k)
            local t = type(v)
            if t == "function" then nfun = nfun + 1 end
            -- Substring, not prefix: the engine names are not consistently prefixed
            -- (GetSectors vs IsValidComponent vs ConvertStringToLuaID), so an anchored
            -- match would hide most of what a caller is hunting for.
            if want == nil or name:lower():find(want, 1, true) ~= nil then
                all[#all + 1] = name .. "|" .. t
            end
        end
    end)
    if not ok then
        reply(seq, "ERR", "iterating _G raised: " .. tostring(err))
        return
    end

    table.sort(all)

    local pages, cur, used = {}, {}, 0
    for _, row in ipairs(all) do
        if used + #row + 1 > ROW_BUDGET then
            pages[#pages + 1] = cur
            cur, used = {}, 0
        end
        cur[#cur + 1] = row
        used = used + #row + 1
    end
    if #cur > 0 or #pages == 0 then pages[#pages + 1] = cur end

    if pg > #pages then
        -- ABSENT, not ERR: the question was well formed and the answer is "no such page".
        reply(seq, "ABSENT", "page " .. pg .. " of " .. #pages .. ": no such page")
        return
    end

    local header = "shown=" .. #pages[pg] .. " matched=" .. #all
                   .. " enumerated=" .. ntotal .. " functions=" .. nfun
                   .. " page=" .. pg .. " pages=" .. #pages
                   .. " filter=" .. (want or "-")
    -- TAB-separated with the header as field 1 -- the house convention every other
    -- verb uses, and what `Reply.fields` splits on. A newline here would collapse
    -- the whole reply into ONE field, and every caller would still appear to
    -- "work" while reading the rows as part of the header.
    local page_rows = {}
    for i, r in ipairs(pages[pg]) do page_rows[i] = r end
    table.insert(page_rows, 1, header)
    reply(seq, "OK", table.concat(page_rows, "\t"))
end

--: Answers, in ONE reply, every open question about the galaxy-enumeration primitives.
--: They are all BARE GLOBALS in vanilla (MEASURED: 8 of 8 GetClusters call sites and 8
--: of 8 GetSectors call sites use the bare form, zero use the ffi `C.` form), but
--: vanilla using a symbol is not evidence that OUR chunk can reach it -- reachability is
--: decided by ui.xml registration and has to be measured, not inferred.
--:
--: Three things are deliberately asked BOTH ways rather than picked:
--:   * GetClusters(bool) -- every vanilla site passes true and the argument is
--:     undocumented, so ask true AND false and report both counts.
--:   * GetContainedStations(container, bool) -- same, second argument undocumented.
--:   * whether GetSectors is knowledge-limited -- vanilla wrapper is named
--:     prepareKnownSectors, which is a HINT and not evidence. Counting isknown over
--:     every sector it returns settles it in one query.
verbs.galaxyprobe = function(seq)
    local out = {}
    local function note(k, v) out[#out + 1] = tostring(k) .. "=" .. tostring(v) end

    -- 1. Existence and type. READ, never called.
    local NAMES = { "GetClusters", "GetSectors", "GetContainedStations",
                    "GetContainedObjectsByOwner", "GetSectorsByOwner",
                    "GetContainedBuildStoragesByOwner", "GetSectorControlStation",
                    "GetComponentData", "ConvertStringToLuaID", "ConvertIDTo64Bit" }
    for _, n in ipairs(NAMES) do note("type." .. n, type(_G[n])) end

    -- 2. The undocumented boolean on GetClusters.
    local function n_clusters(flag)
        if type(GetClusters) ~= "function" then return "?" end
        local cok, r = pcall(GetClusters, flag)
        if not cok or type(r) ~= "table" then return "?" end
        return #r
    end
    note("clusters.arg_true", n_clusters(true))
    note("clusters.arg_false", n_clusters(false))

    -- 3. Walk clusters -> sectors, the vanilla idiom verbatim
    --    (menu_map.lua:29492, menu.prepareKnownSectors).
    local sectors = {}
    if type(GetClusters) == "function" and type(GetSectors) == "function" then
        local cok, cl = pcall(GetClusters, true)
        if cok and type(cl) == "table" then
            for _, c in ipairs(cl) do
                local sok, ss = pcall(GetSectors, c)
                if sok and type(ss) == "table" then
                    for _, s in ipairs(ss) do sectors[#sectors + 1] = s end
                end
            end
        end
    end
    note("sectors.total", #sectors)
    note("sectors.elemtype", (#sectors > 0) and type(sectors[1]) or "?")

    -- 4. IS GetSectors KNOWLEDGE-LIMITED? This is the question everything turns on.
    --    isknown=false rows PRESENT means it is not: it hands back undiscovered sectors
    --    too, and only their LABELS are player-knowledge.
    local kt, kf, ku = 0, 0, 0
    for _, s in ipairs(sectors) do
        local gok, k = pcall(GetComponentData, s, "isknown")
        if not gok then ku = ku + 1
        elseif k == true then kt = kt + 1
        elseif k == false then kf = kf + 1
        else ku = ku + 1 end
    end
    note("sectors.isknown_true", kt)
    note("sectors.isknown_false", kf)
    note("sectors.isknown_undecidable", ku)

    -- 5. The undocumented boolean on GetContainedStations, on the first sector we have.
    if #sectors > 0 and type(GetContainedStations) == "function" then
        local function n_st(flag)
            local sok, r = pcall(GetContainedStations, sectors[1], flag)
            if not sok or type(r) ~= "table" then return "?" end
            return #r
        end
        note("stations.arg_true", n_st(true))
        note("stations.arg_false", n_st(false))
    else
        note("stations.arg_true", "?")
        note("stations.arg_false", "?")
    end

    -- 6. A bounded per-sector sample, so the counts above have items behind them.
    --    ROWS, not aggregates: an aggregate cannot show that ids and NAMES behave
    --    differently, which is the finding this is looking for.
    local rows, used = {}, 0
    for _, s in ipairs(sectors) do
        local nm, ow, kn = "?", "?", "?"
        local gok, a, b, c2 = pcall(GetComponentData, s, "name", "owner", "isknown")
        if gok then nm, ow, kn = tostring(a), tostring(b), tostring(c2) end
        local nst = "?"
        if type(GetContainedStations) == "function" then
            local sok, r = pcall(GetContainedStations, s, true)
            if sok and type(r) == "table" then nst = #r end
        end
        local safe = nm:gsub("|", "/")
        local row = tostring(s) .. "|" .. safe .. "|" .. ow .. "|" .. kn .. "|" .. tostring(nst)
        if used + #row + 1 > (ROW_BUDGET - 1024) then break end
        rows[#rows + 1] = row
        used = used + #row + 1
    end
    note("sample.shown", #rows)

    table.insert(rows, 1, table.concat(out, " "))
    reply(seq, "OK", table.concat(rows, "\t"))
end

-- --------------------------------------------------------------------------- --
-- read loop
-- --------------------------------------------------------------------------- --

-- The ONE place Schedule_Read is called. Everything that needs the channel armed
-- goes through here, so "armed" cannot drift from reality.
local function arm_read()
    if pipes == nil then
        DebugError("X4TOOLKIT_LIVE cannot arm: the named pipes api did not load")
        return
    end
    local ok, err = pcall(pipes.Schedule_Read, PIPE, on_message, true)
    if ok then
        armed = true
    else
        armed = false
        DebugError("X4TOOLKIT_LIVE Schedule_Read failed: " .. tostring(err))
        -- Until 2026-08-29 this branch was TERMINAL: a single failed arm killed the
        -- channel until the next reload, with only one log line to say so. Route it
        -- back through the deferred re-arm instead -- the same path a disconnect
        -- takes, so a transient failure recovers on its own. Deferred, never
        -- synchronous: calling Schedule_Read from here during a Close_Pipe drain is
        -- the hang documented below.
        schedule_rearm()
    end
end

-- ⚠ THE RE-ARM MUST BE DEFERRED, AND THIS IS NOT A STYLE CHOICE.
--
-- `Close_Pipe` (pipes.lua:440) drains the read FIFO in a `while not FIFO.Is_Empty`
-- loop, calling every callback with "ERROR", and only sets `pipes[name] = nil`
-- AFTERWARDS. `Declare_Pipe` reuses existing state, so a Schedule_Read called
-- synchronously from inside that callback writes into THE VERY FIFO BEING DRAINED --
-- the loop never terminates and the game HANGS on the UI thread.
--
-- So we hand the re-arm to the next update instead. Shape copied verbatim from an
-- installed mod that loads its lua exactly as we do (kuertee_additional_agent_actions
-- /ui/*.lua:142): Helper as a bare global, blockinput FALSE, and an ABSOLUTE time.
-- ⚠ blockinput=true calls C.SetAllUIInputIgnored(true) and freezes the player's input
-- until the callback fires. Never pass true here.
--
-- The delay doubles as the throttle: with no server listening the cycle is
-- re-arm -> Close_Pipe -> ERROR -> re-arm, which at frame rate would add ~60 lines a
-- second to debug.txt -- and debug.txt is x4debug's input, so that would corrupt an
-- unrelated instrument.
schedule_rearm = function()
    if type(Helper) ~= "table"
       or type(Helper.addDelayedOneTimeCallbackOnUpdate) ~= "function" then
        -- Refuse rather than re-arm synchronously. A hung game is far worse than a
        -- channel that needs a reload, and this says WHICH it is.
        DebugError("X4TOOLKIT_LIVE cannot re-arm: Helper.addDelayedOneTimeCallbackOnUpdate "
                   .. "is absent. The channel is now DISARMED until the next reload.")
        return
    end
    -- The deadline is ABSOLUTE (compared against getElapsedTime), so without a clock
    -- reading there is no deadline to build. Until 2026-08-29 a failed read left
    -- now = 0, making the deadline 2.0 -- a time long past on any running game. The
    -- callback then fired on the NEXT FRAME and the 2s throttle silently vanished,
    -- turning the no-server cycle into ~60 re-arms a second, each able to log. That
    -- floods debug.txt, which is x4debug's INPUT: a degraded channel would have
    -- corrupted an unrelated instrument. Refuse loudly instead of degrading quietly.
    local now, have_clock = 0, false
    if type(getElapsedTime) == "function" then
        local ok, t = pcall(getElapsedTime)
        if ok and type(t) == "number" then now, have_clock = t, true end
    end
    if not have_clock then
        DebugError("X4TOOLKIT_LIVE cannot re-arm: getElapsedTime is unavailable, so the "
                   .. "throttle cannot be honoured and an unthrottled re-arm would "
                   .. "flood debug.txt. The channel is DISARMED until the next reload.")
        return
    end
    Helper.addDelayedOneTimeCallbackOnUpdate(function() arm_read() end, false,
                                             now + REARM_DELAY)
end

on_message = function(msg)
    if type(msg) ~= "string" or msg == "" then return end
    -- The api's reserved data-channel sentinels. Dispatching on one would answer a
    -- question nobody asked, with a sequence number that then desyncs the FIFO.
    --
    -- CORRECTED 2026-08-29: a LUA callback can only ever receive "ERROR". Scanning
    -- the whole packed api yields 9 "ERROR" and 1 "SUCCESS" and nothing else --
    -- TIMEOUT and CANCELLED are synthesised in MD (named_pipes.xml, cues
    -- Access_Timeout and Reload_Listener) and are structurally unreachable from a
    -- lua callback. The other two are kept as a cheap guard, not because they can
    -- arrive. NB the api has no sentinel ESCAPING: a server that legitimately sent
    -- the literal text "ERROR" would be indistinguishable from a pipe failure. Ours
    -- never can -- every real reply begins with the MR tag.
    if msg == "ERROR" or msg == "TIMEOUT" or msg == "CANCELLED" then
        -- NOT noise. Close_Pipe delivers exactly one of these per armed read while
        -- draining the FIFO, so receiving it MEANS our arm has been destroyed --
        -- pipes.lua:462-471, and Poll_For_Reads:560 is the only path that gets here.
        -- Logging and returning (what this did until 2026-08-29) disarms the channel
        -- permanently after the first disconnect, which is exactly what happened.
        armed = false
        local now = 0
        if type(getElapsedTime) == "function" then
            local ok, t = pcall(getElapsedTime)
            if ok then now = t end
        end
        if rearm_logs < 3 or (now - last_rearm_log) > 60 then
            rearm_logs = rearm_logs + 1
            last_rearm_log = now
            DebugError("X4TOOLKIT_LIVE pipe sentinel: " .. msg .. " -- arm destroyed, "
                       .. "re-arming in " .. REARM_DELAY .. "s")
        end
        schedule_rearm()
        return
    end

    local f = split_tabs(msg)
    if f[1] ~= TAG_CMD then return end
    if f[2] ~= tostring(PROTO) then
        -- Answer anyway, with the sequence we were given, so the Python side gets a
        -- diagnosable frame rather than a timeout it would have to guess about.
        reply(f[3] or "0", "ERR", "proto " .. tostring(f[2]) .. " != " .. PROTO)
        return
    end

    local seq, verb = f[3], f[4]
    if seq == nil or verb == nil then return end

    local fn = verbs[verb]
    if fn == nil then reply(seq, "ERR", "unknown verb: " .. tostring(verb)) return end

    last_replied_seq = nil
    -- All remaining fields, not a fixed three. `component` takes a caller-supplied
    -- field LIST, which is the whole point of it being a general inspector; the
    -- older verbs simply ignore the extra arguments.
    local ok, err = pcall(fn, seq, table_unpack(f, 5))
    if not ok then
        -- A verb that throws must still produce a frame: silence here is
        -- indistinguishable from a paused game.
        --
        -- But EXACTLY ONE frame. Until 2026-08-29 a verb that replied and THEN
        -- raised emitted a second frame for the same seq. Python reads one message
        -- per ask(), so the extra frame stayed queued and became the answer to the
        -- NEXT question -- tripping the sequence check (rc 3) one query after the
        -- real fault, with nothing pointing back to the verb that caused it.
        if last_replied_seq == seq then
            DebugError("X4TOOLKIT_LIVE verb " .. verb .. " raised AFTER replying: "
                       .. tostring(err) .. " -- frame already sent, not re-sending")
        else
            local sent, serr = pcall(reply, seq, "ERR",
                                     "verb " .. verb .. " raised: " .. tostring(err))
            if not sent then
                -- The one outcome we can never allow is TOTAL silence, because it
                -- reads as a paused game. If even the error reply failed, say so in
                -- the log -- this branch was previously swallowed, which is the
                -- exact failure the comment above says it exists to prevent.
                DebugError("X4TOOLKIT_LIVE could not reply to seq " .. tostring(seq)
                           .. ": " .. tostring(serr))
            end
        end
    end
end

Init = function()
    -- FIRST action, before any pipe logic. See the contracts note at the top.
    DebugError("X4TOOLKIT_LIVE loaded: proto=" .. PROTO .. " pipe=" .. PIPE
               .. " build=" .. BUILD)

    -- ⚠ IDS DO NOT SURVIVE A SAVE LOAD, AND THE ALLOWLIST MUST NOT EITHER.
    --
    -- ★ CORRECTED 2026-08-29, MEASURED IN GAME WITH A CONTROL IN BOTH DIRECTIONS.
    -- This comment used to claim "loading a different save does NOT re-run this Init
    -- ... so the lua state (and our allowlist) persists across the load", and that the
    -- RegisterEvent hook below is therefore what protects us. BOTH HALVES WERE FALSE:
    --
    --   * A save load DOES re-run Init. It emits this function's own load marker and
    --     the elapsed clock RESETS with it (1289.31 -> 143.77), because a save load is
    --     itself a full UI reload -- the same event alt-enter causes.
    --   * The hook below HAS NEVER FIRED. Across a game start and a save load its log
    --     line appears 0 times, while `RegisterEvent absent` and `could not hook game
    --     load` are also 0 -- so it registers cleanly and never runs. It cannot run:
    --     it subscribes from INSIDE Init, and Init is itself driven by that signal, so
    --     it is always registered AFTER the event it waits for. Because the chunk is
    --     rebuilt on every load, the next load replaces this listener before it could
    --     ever fire. Structurally dead, not accidentally dead.
    --
    -- WHAT ACTUALLY PROTECTS US is the chunk re-creation itself: a fresh chunk gets a
    -- fresh empty `issued_ids`. VERIFIED end to end -- an id accepted before a save
    -- load was refused after it, with a control run proving the check could pass.
    --
    -- The hook is KEPT rather than deleted, for two reasons: deleting working-looking
    -- safety code deserves its own decision, and as defence in depth it costs nothing
    -- if the engine ever stops rebuilding the chunk on load. It is now INSTRUMENTED
    -- (`load_hook_fired`, reported by probe) so its deadness stays visible instead of
    -- being re-assumed by the next reader -- which is how it survived this long.
    -- ⚠ Note what misled us: `probe` reports RegisterEvent as PRESENT, and presence was
    -- read as working. A symbol existing says nothing about a handler ever running.
    --
    -- The hazard the clearing exists to prevent is unchanged and still real:
    -- IsValidComponent catches the DESTROYED case, but not the REUSED-HANDLE case:
    -- if the engine hands the same UniverseID to a different object in the new save,
    -- `component <old id>` would return that object's data under the id you asked
    -- about -- a wrong answer wearing the grammar of a right one, which is worse
    -- than a refusal. So the allowlist is emptied on every game start/load.
    --
    -- `Lua_Loader.Send_Priority_Ready` is the MD signal raised by md/lua_loader.xml's
    -- Reload_Listener, whose <check_any> covers BOTH <event_game_loaded/> and
    -- <event_game_started/>. Registering a second listener alongside lua_loader's own
    -- is additive.
    if type(RegisterEvent) == "function" then
        local ok, err = pcall(RegisterEvent, "Lua_Loader.Send_Priority_Ready", function()
            issued_ids = {}
            load_hook_fired = true
            DebugError("X4TOOLKIT_LIVE game start/load: id allowlist cleared "
                       .. "(NOTE: this line had never once appeared as of 2026-08-29 -- "
                       .. "if you are reading it, the hook is no longer dead and the "
                       .. "comment in Init needs revisiting)")
        end)
        if not ok then
            DebugError("X4TOOLKIT_LIVE could not hook game load: " .. tostring(err)
                       .. " -- ids from a previous save may persist; re-run `player`"
                       .. " or `stations` after loading to re-issue them")
        end
    else
        DebugError("X4TOOLKIT_LIVE RegisterEvent absent; the id allowlist will NOT reset "
                   .. "on a save load")
    end

    if armed then
        DebugError("X4TOOLKIT_LIVE Init ran twice; not re-arming (would duplicate replies)")
        return
    end
    if pipes == nil then
        DebugError("X4TOOLKIT_LIVE ABORT: the named pipes api did not load")
        return
    end

    -- continuous_read = true: the callback stays armed and fires on every server
    -- push (pipes.lua:127, and :513-515 declines to pop the FIFO entry), so the
    -- server drives and the game never polls.
    -- FALLBACK, pre-committed: if this never fires because a passive read needs
    -- priming, set continuous to false and re-arm at the END of on_message. That is
    -- pipe_time.lua's proven write-then-read shape and costs only latency.
    arm_read()
    if armed then
        DebugError("X4TOOLKIT_LIVE armed continuous read on " .. PIPE
                   .. " (re-arms itself on disconnect)")
    end
end

-- The pipes api and Register_OnLoad_Init are both provided by sn_mod_support_apis.
-- Guarded rather than assumed: if that mod is absent or disabled these are nil, and
-- an unguarded require would raise at load time with no explanation of why.
local req_ok, req = pcall(require, "extensions.sn_mod_support_apis.ui.named_pipes.Interface")
if req_ok then
    pipes = req
else
    DebugError("X4TOOLKIT_LIVE ABORT: could not require the named pipes api: " .. tostring(req))
end

if type(Register_OnLoad_Init) == "function" then
    Register_OnLoad_Init(Init, "extensions.x4_toolkit_live_query.Live_Query")
else
    DebugError("X4TOOLKIT_LIVE ABORT: Register_OnLoad_Init absent -- is sn_mod_support_apis "
               .. "(ws_2042901274) installed, enabled, and loading BEFORE this mod?")
end

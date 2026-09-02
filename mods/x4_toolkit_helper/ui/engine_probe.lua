-- X4 Toolkit Helper: the uidata probe half (read-only).
--
-- Exports what the RUNNING ENGINE knows into a savedvariable, which the engine
-- serialises to {profile}/uidata.xml, where our Python toolkit reads it. No pipe,
-- no launch flags, no permissions grant.
--
-- CONTRACTS THIS FILE KEEPS (each exists because it was got wrong somewhere):
--  * Three states, never a bare zero: ABSENT / CALL_FAILED / OK value. A count of
--    0 is reported as OK 0, so "none" never wears the grammar of "cannot ask".
--    The mod we learned this technique from returns 0 for both.
--  * Denominators. Every capped list emits the CAP and the TRUE TOTAL.
--  * A terminator row. Without it a truncated dump reads as a short valid answer.
--  * FFI vs global is explicit. Two functions were wrongly reported ABSENT by the
--    previous probe because they are FFI and were called bare.

local ffi = require("ffi")
local C = ffi.C

-- FFI surface: must be declared, and called through C. Signatures copied verbatim
-- from vanilla ego_gameoptions/gameoptions.lua lines 216, 296, 372.
pcall(ffi.cdef, [[
    void        SaveUIUserData(void);
    const char* GetUserData(const char* name);
    void        SetUserData(const char* name, const char* value);
    bool        IsErrorLogActive(void);
]])

--: Stamped by scripts/stamp-mod-build.py from this file's own content, exactly like
--: live_query.lua. Until 2026-09-02 only that file was stamped, so an edit to THIS one
--: -- the half that runs automatically at load and writes profile UI userdata -- shipped
--: with nothing able to notice.
local BUILD = "2ad1d93c"

local SCHEMA  = 2
local ERR_CAP = 400             -- capped, and the true total is always reported

local LIBRARY_TYPES = {
    "factions", "races", "stationtypes", "licences", "wares", "inventory_wares",
    "moduletypes_production", "moduletypes_build", "moduletypes_storage",
    "moduletypes_habitation", "moduletypes_welfare", "moduletypes_defence",
    "moduletypes_dock", "moduletypes_processing", "moduletypes_other",
    "moduletypes_venture", "moduletypes_radar",
    "shiptypes_xl", "shiptypes_l", "shiptypes_m", "shiptypes_s", "shiptypes_xs",
    "weapons_lasers", "weapons_missilelaunchers", "weapons_turrets",
    "weapons_missileturrets", "missiletypes", "mines", "bombs", "countermeasures",
    "enginetypes", "thrustertypes", "shieldgentypes",
    "satellites", "navbeacons", "resourceprobes", "lasertowers", "software",
    "paintmods",
}

local rows = {}                 -- array + concat once; never s = s .. x in a loop

local function esc(v)
    local s = tostring(v)
    s = s:gsub("\\", "\\\\")
    s = s:gsub("\t", "\\t")
    s = s:gsub("\r", "\\r")
    s = s:gsub("\n", "\\n")
    return s
end

local function row(...)
    local n = select("#", ...)
    local parts = {}
    for i = 1, n do parts[i] = esc((select(i, ...))) end
    rows[#rows + 1] = table.concat(parts, "\t")
end

local function sorted_keys(t)
    local ks = {}
    for k in pairs(t) do ks[#ks + 1] = tostring(k) end
    table.sort(ks)
    return ks
end

-- ---------------------------------------------------------------- extensions
local function dump_extensions()
    if type(GetExtensionList) ~= "function" then
        row("EXT_STATUS", "ABSENT")
        return
    end
    local ok, list = pcall(GetExtensionList)
    if not ok then row("EXT_STATUS", "CALL_FAILED", tostring(list)) return end
    if type(list) ~= "table" then row("EXT_STATUS", "BAD_TYPE", type(list)) return end

    row("EXT_STATUS", "OK", #list)
    local fields = {}
    if type(list[1]) == "table" then fields = sorted_keys(list[1]) end
    row("EXT_FIELDS", table.concat(fields, ","))
    for _, e in ipairs(list) do
        local vals = { "EXT" }
        for _, f in ipairs(fields) do
            local v = e[f]
            if type(v) == "table" then
                vals[#vals + 1] = "<table>"
            else
                vals[#vals + 1] = tostring(v)
            end
        end
        row(unpack(vals))
    end
end

-- ---------------------------------------------------------------- error log
local function dump_errors()
    if type(GetNumErrors) ~= "function" then row("ERR_STATUS", "ABSENT") return end
    local ok, n = pcall(GetNumErrors)
    if not ok then row("ERR_STATUS", "CALL_FAILED", tostring(n)) return end
    if type(n) ~= "number" then row("ERR_STATUS", "BAD_TYPE", type(n)) return end

    local active = "unknown"
    local okA, a = pcall(function() return C.IsErrorLogActive() end)
    if okA then active = tostring(a) end

    -- DISCLOSE the cap and the true total, always. A capped list that hides its
    -- denominator is the narrowing step this workspace exists to refuse.
    local emit = math.min(n, ERR_CAP)
    row("ERR_STATUS", "OK", n, "cap=" .. ERR_CAP, "emitting=" .. emit, "logactive=" .. active)

    if type(GetError) ~= "function" then row("ERR_ROWS", "ABSENT", "GetError") return end
    local written = 0
    local stop = n - emit + 1
    if stop < 1 then stop = 1 end
    for i = n, stop, -1 do
        local okM, msg = pcall(GetError, i)
        local okS, sev = pcall(GetErrorSeverity, i)
        local okT, ts  = pcall(GetErrorTimestamp, i)
        local m = "?"
        if okM then m = tostring(msg) end
        local s = "?"
        if okS then s = tostring(sev) end
        local t = "?"
        if okT then t = tostring(ts) end
        row("ERR", i, s, t, m)
        written = written + 1
    end
    row("ERR_WRITTEN", written, "of_total", n)
end

-- ----------------------------------------------------------------- libraries
-- Sizes for every type give a cheap denominator. One full pairs() dump per type
-- discovers the real field vocabulary: vanilla NEVER enumerates a GetLibraryEntry
-- result, so its consumed field list is not the returned one.
local function dump_libraries()
    if type(GetLibrary) ~= "function" then row("LIB_STATUS", "ABSENT", "GetLibrary") return end
    -- Recorded in EVERY dump, because the scheduling decision itself happens after
    -- emit("LOAD") has already written this one -- so the outcome can never appear
    -- here, but the CAPABILITY can. A reader seeing "no" knows why only one dump
    -- arrived, instead of wondering whether the second was lost.
    row("DELAYED_CAPABLE",
        (type(Helper) == "table"
         and type(Helper.addDelayedOneTimeCallbackOnUpdate) == "function"
         and type(getElapsedTime) == "function") and "yes" or "no")
    row("LIB_STATUS", "OK", #LIBRARY_TYPES)
    for _, lt in ipairs(LIBRARY_TYPES) do
        local okL, lib = pcall(GetLibrary, lt)
        if not okL then
            row("LIB", lt, "CALL_FAILED", tostring(lib))
        elseif type(lib) ~= "table" then
            row("LIB", lt, "BAD_TYPE", type(lib))
        else
            row("LIB", lt, "OK", #lib)
            local first = lib[1]
            if type(first) == "table" and first.id then
                row("LIB_ELEM_FIELDS", lt, table.concat(sorted_keys(first), ","))
                if type(GetLibraryEntry) == "function" then
                    local okE, entry = pcall(GetLibraryEntry, lt, first.id)
                    if okE and type(entry) == "table" then
                        local ks = sorted_keys(entry)
                        row("LIB_ENTRY_FIELDS", lt, first.id, #ks, table.concat(ks, ","))
                        for _, k in ipairs(ks) do
                            local v = entry[k]
                            if type(v) ~= "table" and type(v) ~= "function" then
                                row("LIB_ENTRY_VAL", lt, first.id, k, tostring(v))
                            end
                        end
                    else
                        row("LIB_ENTRY_FIELDS", lt, tostring(first.id), "CALL_FAILED")
                    end
                else
                    -- NAMED, not skipped in silence. Without this the library simply
                    -- has no LIB_ENTRY_FIELDS row, and the reader is told (by
                    -- _livecli) that an absent kind "was never asked for" -- which is
                    -- the opposite of what happened.
                    row("LIB_ENTRY_FIELDS", lt, tostring(first.id), "NO_GETLIBRARYENTRY")
                end
            else
                row("LIB_ELEM_FIELDS", lt, "SKIPPED",
                    "first element is " .. type(first) .. " without an id")
            end
        end
    end
end

-- ---------------------------------------------------------------------- main
local function build()
    local elapsed = "?"
    if type(getElapsedTime) == "function" then elapsed = tostring(getElapsedTime()) end
    row("HDR", "schema=" .. SCHEMA, "probe=x4_toolkit_helper", "elapsed=" .. elapsed)
    dump_extensions()
    dump_errors()
    dump_libraries()
    row("END", #rows + 1)       -- +1 counts this terminator row itself
    return table.concat(rows, "\n")
end

local function emit(phase)
    rows = {}
    local okB, payload = pcall(build)
    if not okB then
        __x4live_dump = "HDR\tschema=" .. SCHEMA .. "\tFATAL\t" .. esc(tostring(payload))
        DebugError("X4TOOLKIT_PROBE [" .. phase .. "] build FAILED: " .. tostring(payload))
    else
        __x4live_dump = payload
        DebugError("X4TOOLKIT_PROBE [" .. phase .. "] dump rows=" .. #rows .. " bytes=" .. #payload)
    end
    -- Force the write so the file lands on disk at a deterministic moment rather
    -- than whenever the engine next decides to flush.
    local okS, errS = pcall(function() C.SaveUIUserData() end)
    if okS then
        DebugError("X4TOOLKIT_PROBE [" .. phase .. "] SaveUIUserData OK")
    else
        DebugError("X4TOOLKIT_PROBE [" .. phase .. "] SaveUIUserData FAILED " .. tostring(errS))
    end
end

emit("LOAD")

-- Emit AGAIN once the game is up. Two reasons, both about not trusting an
-- assumption: (1) if the engine restores savedvariables from uidata.xml AFTER
-- running addon lua, the LOAD assignment would be silently overwritten and this
-- one wins; (2) the error log grows, so the later dump is the fuller one.
-- Proven to fire: the previous probe's DELAYED phase ran in both launches.
if type(Helper) == "table"
   and type(Helper.addDelayedOneTimeCallbackOnUpdate) == "function"
   and type(getElapsedTime) == "function" then
    local okD = pcall(Helper.addDelayedOneTimeCallbackOnUpdate,
                      function() pcall(emit, "DELAYED") end, true, getElapsedTime() + 12)
    if not okD then DebugError("X4TOOLKIT_PROBE delayed-schedule FAILED") end
else
    DebugError("X4TOOLKIT_PROBE no Helper.addDelayedOneTimeCallbackOnUpdate; DELAYED skipped")
end

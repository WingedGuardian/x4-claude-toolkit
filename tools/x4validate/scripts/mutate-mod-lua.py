"""Per-clause mutation probe for the game-side live-query lua.

USE THIS RATHER THAN HAND-ROLLING ONE. It has been written from scratch twice, and both
times the same two traps had to be rediscovered:

  1. DESELECT THE BUILD FINGERPRINT TEST. Every edit to the mod changes its content
     hash, so without the deselect EVERY mutant "dies" for a reason that has nothing to
     do with behaviour. MEASURED 2026-08-30: it did exactly that, and made an entirely
     unasserted branch look covered.
  2. A SKIP IS A FAILURE. An anchor that no longer matches means the mutation never
     happened; reporting that as a pass is the "green that could not have gone red"
     defect this file exists to prevent. Same for a pytest id that matches no test.

WHY PER CLAUSE. A guard shadows every clause behind it, so ONE twin against a compound
condition only ever tests the FIRST clause it trips. `is_valid_object` has seven and
each gets its own mutant aimed at its own named test.

Anchors are matched EXACTLY ONCE or the run refuses. The file is restored in `finally`
and the restore is verified byte-for-byte before exit.

    uv run python scripts/mutate-mod-lua.py        # non-zero if anything survived or skipped

MAINTAINER-ONLY, AND NOT SHIPPED. It deliberately makes the working tree WRONG while it
runs -- it plants mutants in the game-side mod and restores it afterwards -- so handing it
to a user would hand them a tool whose failure mode is a corrupted mod. `.gitattributes`
marks it export-ignore, so the release bundle never carries it. It lives in the public repo
so that it survives the private workspace it was written in being retired (2026-09-13).
Never run it beside anything that reads or deploys the mod.

    X4_MUTATE_TOOL=<a tools/x4validate checkout>   mutate and test THAT tree (default: this one)
    X4_MUTATE_ONLY="name fragment|another"         run only mutants whose name contains one
"""
import pathlib
import subprocess
import sys

import os

# X4_MUTATE_TOOL points at a tools/x4validate checkout; the mod is then located the way
# the suite and the stamper locate it -- mods/ first, then dev/ -- so the gate mutates
# the SAME file the tests read. Without it this looked only in dev/, and in a public
# checkout it exited "nothing to mutate" having tested nothing.
TOOL = (pathlib.Path(os.environ["X4_MUTATE_TOOL"]).resolve()
        if os.environ.get("X4_MUTATE_TOOL") else pathlib.Path(__file__).resolve().parents[1])
_FOUND = []
for _root in ("mods", "dev"):
    _d = TOOL.parents[1] / _root
    _FOUND = sorted(_d.glob("*/ui/*live_query.lua")) if _d.is_dir() else []
    if _FOUND:
        break
if not _FOUND:
    raise SystemExit(f"game-side live-query mod not found under {TOOL.parents[1]} "
                     "(mods/ or dev/); nothing to mutate")
LUA = _FOUND[0]
TESTS = "tests/test_modlua_rearm.py"
BUILD_TEST = f"{TESTS}::test_the_BUILD_constant_matches_the_file"

V = "test_isObjectValid_REJECTS_each_clause_SEPARATELY"

MUTANTS = [
    # ---- the capability harvest: globals ----------------------------------- #
    #
    # Escapes are built from chr() rather than written as literals: these anchors
    # contain a real backslash-t and backslash-n as they appear in the lua SOURCE, and
    # that sequence has been collapsed three times this session crossing a tool
    # boundary. chr(92) cannot be collapsed by anything.
    ("globals CALLS the globals it enumerates",
     '            if t == "function" then nfun = nfun + 1 end',
     '            if t == "function" then nfun = nfun + 1 pcall(v) end',
     "test_globals_lists_names_and_types_and_NEVER_CALLS_them"),

    ("the globals filter becomes prefix-anchored instead of substring",
     '            if want == nil or name:lower():find(want, 1, true) ~= nil then',
     '            if want == nil or name:lower():find(want, 1, true) == 1 then',
     "test_globals_filter_is_a_SUBSTRING_not_a_prefix"),

    ("globals joins its rows with a NEWLINE, collapsing the reply into one field",
     '    reply(seq, "OK", table.concat(page_rows, "' + chr(92) + 't"))',
     '    reply(seq, "OK", table.concat(page_rows, "' + chr(92) + 'n"))',
     "test_globals_reply_is_TAB_separated_like_every_other_verb"),

    ("a page past the end is reported as ERR rather than ABSENT",
     '        reply(seq, "ABSENT", "page " .. pg .. " of " .. #pages .. ": no such page")',
     '        reply(seq, "ERR", "page " .. pg .. " of " .. #pages .. ": no such page")',
     "test_globals_a_page_past_the_end_is_ABSENT_not_ERR"),

    ("globals stops paging and emits one oversized reply",
     '    for _, row in ipairs(all) do' + chr(10) + '        if used + #row + 1 > ROW_BUDGET then',
     '    for _, row in ipairs(all) do' + chr(10) + '        if false then',
     "test_globals_never_exceeds_the_payload_cap"),

    # ---- the capability harvest: galaxyprobe -------------------------------- #

    ("galaxyprobe asks GetClusters only the way vanilla does",
     '    note("clusters.arg_false", n_clusters(false))',
     '    note("clusters.arg_false", n_clusters(true))',
     "test_galaxyprobe_asks_GetClusters_BOTH_WAYS"),

    ("galaxyprobe asks GetContainedStations only one way",
     '        note("stations.arg_false", n_st(false))',
     '        note("stations.arg_false", n_st(true))',
     "test_galaxyprobe_asks_GetContainedStations_BOTH_WAYS"),

    ("an isknown bucket stops counting, so the buckets no longer sum",
     '        elseif k == false then kf = kf + 1',
     '        elseif k == false then kf = kf',
     "test_galaxyprobe_isknown_buckets_SUM_to_the_sector_total"),

    ("the per-sector sample stops being bounded",
     '        if used + #row + 1 > (ROW_BUDGET - 1024) then break end',
     '        if false then break end',
     "test_galaxyprobe_stays_inside_the_payload_cap_with_many_sectors"),

    ("galaxyprobe calls GetClusters WITHOUT pcall, so an absent primitive raises",
     '        local cok, r = pcall(GetClusters, flag)',
     '        local r = GetClusters(flag) local cok = true',
     "test_galaxyprobe_survives_a_primitive_that_EXISTS_but_RAISES"),

    ("galaxyprobe INVOKES the primitives it only reports the type of",
     '    for _, n in ipairs(NAMES) do note("type." .. n, type(genv[n] or _G[n])) end',
     '    for _, n in ipairs(NAMES) do note("type." .. n, type(genv[n] or _G[n])) pcall(genv[n] or _G[n]) end',
     "test_galaxyprobe_NEVER_CALLS_a_global_it_only_reports_the_type_of"),

    # ---- the id wire form -------------------------------------------------- #
    ("wire does not canonicalise at all",
     '    local s = tostring(v)\n    if s:match("^%d+ULL$") then return s end',
     '    local s = tostring(v)\n    if true then return s end',
     "test_wire_gives_ONE_string_for_every_shape_of_the_SAME_id"),

    ("the 2^53 representability guard is removed",
     "    if n >= 9007199254740992 then",
     "    if false then",
     "test_wire_REFUSES_an_id_at_or_above_2_pow_53"),

    ("a sector token is canonicalised like an object id",
     "local function issue_token(s)\n    issued_ids[s] = true\n    return s",
     "local function issue_token(s)\n    local w = wire(s) issued_ids[w] = true\n    return w",
     "test_a_SECTOR_TOKEN_is_NOT_canonicalised_into_an_id"),

    # The --wide regression found in game: GetComponentData does not accept a raw
    # UniverseID cdata and does not raise on one, so forgetting the conversion yields
    # every object unreadable with zero read failures.
    ("read_flags forgets to convert a cdata id before reading it",
     "    local id = readable_id(obj)",
     "    local id = obj",
     "test_objects_and_wide_are_BOTH_reachable_and_DISTINGUISHABLE"),

    # ---- path / scope reporting -------------------------------------------- #
    ("the header stops naming which path ran",
     '                   .. " path=" .. (opts.wide and "wide" or "container")',
     '                   .. " path=" .. "container"',
     "test_objects_and_wide_are_BOTH_reachable_and_DISTINGUISHABLE"),

    ("--wide silently accepts no faction",
     "    if opts.wide and not opts.faction then",
     "    if false then",
     "test_wide_without_a_faction_is_REFUSED_not_silently_empty"),

    ("--hidden is ignored when listing factions",
     "        local factions = opts.faction and { opts.faction } or faction_list(opts.hidden and true or false)",
     "        local factions = opts.faction and { opts.faction } or faction_list(false)",
     "test_hidden_CHANGES_the_faction_scope_and_the_header_says_so"),

    ("a failed faction is swallowed instead of named",
     "                meta.failed[#meta.failed + 1] = fac",
     "                local _ = fac",
     "test_a_faction_whose_call_FAILS_is_NAMED_not_absorbed"),

    ("the class filter keeps everything",
     "                keep = (verdict == true)",
     "                keep = true",
     "test_class_filter_keeps_ships_stations_and_NEITHER_visible_under_all"),

    # Reintroduces the lua and/or trap found in game: when is_ship returns FALSE the
    # `cond and A or B` form falls through to B, so asking for ships also matched every
    # station. Proves the test DEFENDS the fix rather than merely predating it.
    ("the class filter uses the and/or form that falls through on false",
     '                local verdict\n                if opts.class == "ship" then verdict = is_ship(f)\n                else verdict = is_station(f) end',
     '                local verdict = (opts.class == "ship") and is_ship(f) or is_station(f)',
     "test_class_filter_keeps_ships_stations_and_NEITHER_visible_under_all"),

    ("an unclassifiable object is silently dropped",
     "                if verdict == nil then nunclassified = nunclassified + 1 end",
     "                if false then nunclassified = nunclassified + 1 end",
     "test_an_UNCLASSIFIABLE_object_is_COUNTED_not_silently_dropped"),

    ("an undecidable verdict is folded into false",
     "                if valid == true then nvalid = nvalid + 1\n                elseif valid == nil then nundecided = nundecided + 1 end",
     "                if valid == true then nvalid = nvalid + 1 end",
     "test_an_UNDECIDABLE_validity_is_reported_SEPARATELY_from_false"),

    # ---- isObjectValid: SEVEN clauses, seven mutants ------------------------ #
    ("clause 1: an unlisted class is accepted",
     "           and not (Helper.isComponentClass(f.classid, \"buildstorage\") and f.isorphaned) then\n            return false",
     "           and not (Helper.isComponentClass(f.classid, \"buildstorage\") and f.isorphaned) then\n            return true",
     f"{V}[not a listed class-flags0]"),

    ("clause 1b: a station WRECK is still treated as a station",
     "           and not (is_station(f) and (not f.iswreck))",
     "           and not (is_station(f))",
     f"{V}[a station wreck-flags5]"),

    ("clause 2: units are accepted",
     'elseif (isship or Helper.isComponentClass(f.classid, "controllable")) and f.isunit then',
     "elseif false then",
     f"{V}[a unit-flags1]"),

    ("clause 3a: the isknown check is dropped",
     "elseif (not f.isknown) or (not f.isradarvisible) then",
     "elseif (false) or (not f.isradarvisible) then",
     f"{V}[not known-flags2]"),

    ("clause 3b: the isradarvisible check is dropped",
     "elseif (not f.isknown) or (not f.isradarvisible) then",
     "elseif (not f.isknown) or (false) then",
     f"{V}[not radar visible-flags3]"),

    ("clause 4: limpets are accepted",
     "elseif isship and f.isattachedaslimpet then",
     "elseif false then",
     f"{V}[a limpet-flags4]"),

    ("the separate mass-traffic drop is removed",
     "        if f.ismasstraffic and (not f.isenemy) then return false end",
     "        if false then return false end",
     f"{V}[non-enemy traffic-flags6]"),

    # The silent-widening guard: an unrecognised container is ignored by the engine
    # and returns the whole galaxy labelled as your sector (MEASURED 310 vs 1961).
    ("a malformed sector token is accepted instead of refused",
     '    if tostring(tok):match("^ID:%s*%d+$") then return nil end',
     '    if true then return nil end',
     "test_a_MALFORMED_sector_token_is_REFUSED_not_silently_widened"),

    ("compare skips the malformed-token guard",
     "    -- new_only set and read as a method difference.\n    local bad = bad_sector_token(sector)",
     "    -- new_only set and read as a method difference.\n    local bad = nil",
     "test_compare_ALSO_refuses_a_malformed_sector_token"),

    # The denominator-population defect found in game (matched=1909 vs total=1813).
    ("total borrows the ship+station count for a mixed-class query",
     '            if opts.class == "ship" then meta.total = a',
     '            if true then meta.total = a + b',
     "test_total_COUNTS_THE_SAME_POPULATION_as_enumerated"),

    # ---- compare ------------------------------------------------------------ #
    ("compare runs the SAME path twice instead of both",
     '        local old_raw = gather({ wide = true,  class = "all", faction = faction, sector = sector })',
     '        local old_raw = gather({ wide = false, class = "all", faction = faction, sector = sector })',
     "test_compare_runs_BOTH_paths_in_ONE_call_and_diffs_them"),

    # NB the equivalent-mutant trap: swapping tostring->wire on the FFI side changes
    # nothing, because wire() of an already-canonical value is the identity. The side
    # that can actually HIDE the finding is the bare-global one, so mutate that.
    ("compare hides the wire-form difference behind the canonicaliser",
     "            local raw_new = okc and tostring(conv) or (\"raised:\" .. tostring(conv))",
     "            local raw_new = okc and wire(conv) or (\"raised:\" .. tostring(conv))",
     "test_compare_renders_ONE_object_through_BOTH_id_paths"),

    # ---- the header delimiter bug found by a test helper -------------------- #
    ("the sector token goes into the header unsanitised",
     '                   .. " sector=" .. (opts.sector and header_safe(opts.sector) or "galaxy")',
     '                   .. " sector=" .. (opts.sector and tostring(opts.sector) or "galaxy")',
     "test_the_header_is_PARSEABLE_as_key_value_pairs"),

    # ---- the WRITE verbs: one mutant per clause of pause_write and its guards -- #
    ("pause acts on a game that is already paused",
     "    if before == want then\n        if want then",
     "    if false then\n        if want then",
     "test_pause_REFUSES_when_the_game_is_ALREADY_paused"),
    ("unpause acts on a game that is not paused",
     "    if before == want then\n        if want then",
     "    if before == want and want then\n        if want then",
     "test_unpause_REFUSES_when_the_game_is_NOT_paused"),
    ("unpause stops checking ownership",
     "    if (not want) and not our_pause then",
     "    if false then",
     "test_unpause_REFUSES_a_pause_it_did_not_make"),
    ("a pause whose read-back disagrees claims ownership anyway",
     "        if after == true then our_pause = true end",
     "        our_pause = true",
     "test_a_pause_whose_READ_BACK_DISAGREES_claims_NO_ownership"),
    ("an unpause never releases ownership",
     "    else\n        our_pause = false\n    end",
     "    else\n    end",
     "test_a_successful_unpause_RELEASES_ownership"),
    ("an unpause releases ownership only when its read-back agrees (so a retry can undo a menu's pause)",
     "    else\n        our_pause = false\n    end",
     "    elseif after == false then\n        our_pause = false\n    end",
     "test_an_unpause_whose_READ_BACK_DISAGREES_RELEASES_ownership_and_never_retries"),
    ("a call that raised after pausing loses its claim",
     "    if want then\n        if after == true then our_pause = true end",
     "    if want and ok then\n        if after == true then our_pause = true end",
     "test_a_call_that_RAISES_AFTER_pausing_still_owns_the_pause_it_made"),
    ("an unverified read-back is reported as a disagreement",
     '    if after == nil then\n        return finish("ERR", "unverified",',
     '    if false then\n        return finish("ERR", "unverified",',
     "test_a_write_whose_state_CANNOT_BE_READ_BACK_after_acting_is_UNVERIFIED"),
    ("a refusal reports agree=yes",
     "        if t.acted and t.after ~= nil then t.agree = (t.after == t.want) end",
     "        if t.after ~= nil then t.agree = (t.after == t.want) end",
     "test_pause_REFUSES_when_the_game_is_ALREADY_paused"),
    ("the size cap strips a write reply's advisory",
     '        if writing_verb ~= nil then\n            payload = write_advisory({ verb = writing_verb, reason = "too-large" })',
     '        if false then\n            payload = write_advisory({ verb = writing_verb, reason = "too-large" })',
     "test_an_OVERSIZED_write_reply_still_LEADS_with_its_advisory"),
    ("the wrap embeds an unbounded original reply",
     "                  .. (#payload > 2000",
     "                  .. (false",
     "test_an_OVERSIZED_write_reply_still_LEADS_with_its_advisory"),
    ("the verb reports its INTENTION instead of the read-back",
     "    t.after = after",
     "    t.after = want",
     "test_pause_reports_the_READ_BACK_not_its_own_intention"),
    ("the stale ownership flag is never cleared",
     "        our_pause = false\n        t.ownerreset = true",
     "        t.ownerreset = true",
     "test_a_STALE_ownership_flag_is_CLEARED_when_the_engine_shows_the_pause_is_gone"),
    ("a write verb accepts arguments",
     "    if nargs > 0 then",
     "    if false then",
     "test_a_write_verb_with_ANY_argument_is_REFUSED"),
    ("the read-back is trusted without its declaration",
     "    if not pause_cdef_ok then",
     "    if false then",
     "test_pause_REFUSES_when_it_cannot_READ_BACK_because_ffi_did_not_load"),
    ("a non-boolean read-back is trusted",
     '    if type(v) ~= "boolean" then',
     "    if false then",
     "test_a_write_REFUSES_when_IsGamePaused_answers_a_NON_BOOLEAN"),
    ("Pause is called with vanilla's unexplained argument form",
     "    local ok, err = pcall(fn)",
     "    local ok, err = pcall(fn, nil, true)",
     "test_pause_PAUSES_and_reports_what_the_engine_READS_BACK"),
    ("the advisory wrap is removed from reply()",
     '    if writing_verb ~= nil and payload:sub(1, 10) ~= "write=yes " then',
     "    if false then",
     "test_a_write_reply_WITHOUT_its_advisory_is_WRAPPED_and_marked_untrusted"),
    ("the advisory wrap applies to READ replies too",
     '    if writing_verb ~= nil and payload:sub(1, 10) ~= "write=yes " then',
     '    if payload:sub(1, 10) ~= "write=yes " then',
     "test_the_write_flag_is_CLEARED_so_the_next_READ_is_not_wrapped"),
    ("the dispatcher runs a write verb without marking it as one",
     "        fn, is_write = WRITE_VERBS[verb], true",
     "        fn, is_write = WRITE_VERBS[verb], false",
     "test_a_write_reply_WITHOUT_its_advisory_is_WRAPPED_and_marked_untrusted"),
    ("a name in BOTH tables is run instead of refused",
     "        if fn ~= nil then\n            reply(seq, \"ERR\", \"verb \" .. tostring(verb) .. \" is in BOTH",
     "        if false then\n            reply(seq, \"ERR\", \"verb \" .. tostring(verb) .. \" is in BOTH",
     "test_a_verb_in_BOTH_tables_is_REFUSED_and_neither_runs"),
    ("the write ATTEMPT is no longer logged",
     '        DebugError("X4TOOLKIT_LIVE WRITE " .. verb .. " seq=" .. tostring(seq))',
     "        -- mutant: no attempt log",
     "test_every_write_ATTEMPT_is_logged_even_a_refused_one"),
    ("pausestate reports every pause as ours",
     '    return our_pause and "us" or "other"',
     '    return "us"',
     "test_pausestate_READS_state_and_ownership_WITHOUT_writing"),
    ("the 2000-byte cut can split a UTF-8 character",
     "        if b == nil or b < 0x80 or b >= 0xC0 then break end",
     "        break",
     "test_the_wrap_never_SPLITS_a_multibyte_character"),
    ("a raised or unverified unpause keeps its claim",
     "    else\n        our_pause = false\n    end",
     "    elseif after ~= true then\n        our_pause = false\n    end",
     "test_an_unpause_that_RAISED_or_went_UNVERIFIED_still_RELEASES_the_claim"),

    # ---- deep contents: render_table, `macro --contents`, `recon --deep` ---- #
    # The scrub pattern is built from chr(92) for the reason given at the top of the list.
    ("contents: render_table descends one level too far",
     '        if vt == "table" and depth > 1 then',
     '        if vt == "table" and depth > 0 then',
     "test_macro_contents_STOPS_at_two_levels"),
    ("contents: string leaves are not scrubbed",
     '                r = (((#val > 40) and (utf8_prefix(val, 40) .. "..") or val):gsub("[|'
     + chr(92) + "t" + chr(92) + "n" + chr(92) + 'r,]", " "))',
     '                r = ((#val > 40) and (utf8_prefix(val, 40) .. "..") or val)',
     "test_macro_contents_keeps_the_FRAME_intact"),
    ("contents: keys are not scrubbed",
     '    local function keyof(k) return (tostring(k):gsub("[|'
     + chr(92) + "t" + chr(92) + "n" + chr(92) + 'r,]", " ")) end',
     "    local function keyof(k) return tostring(k) end",
     "test_macro_contents_keeps_the_FRAME_intact"),
    ("contents: render_table ignores its budget",
     "        if used + #cell + 1 > budget then break end",
     "        -- mutant: no budget",
     "test_macro_contents_is_BOUNDED_and_NAMES_what_it_omitted"),
    ("contents: a string leaf is cut with :sub, splitting a character",
     '(utf8_prefix(val, 40) .. "..")',
     '(val:sub(1, 40) .. "..")',
     "test_contents_never_SPLITS_a_multibyte_character"),
    ("contents: a nested table gets the WHOLE budget instead of a share",
     "        local share = math.floor((budget - fixed) / #nested)",
     "        local share = budget",
     "test_contents_a_FAT_nested_table_does_not_hide_its_small_siblings"),
    ("recon: the string summary is cut with :sub",
     '(utf8_prefix(v, 40):gsub("[|' + chr(92) + "t" + chr(92) + "n" + chr(92) + 'r]", " "))',
     '(v:sub(1, 40):gsub("[|' + chr(92) + "t" + chr(92) + "n" + chr(92) + 'r]", " "))',
     "test_recon_string_summary_never_SPLITS_a_multibyte_character"),
    ("recon: a RAISED message is cut with :sub",
     '(utf8_prefix(tostring(a), 70):gsub("[|' + chr(92) + "t" + chr(92) + "n" + chr(92) + 'r]", " "))',
     '(tostring(a):sub(1, 70):gsub("[|' + chr(92) + "t" + chr(92) + "n" + chr(92) + 'r]", " "))',
     "test_recon_RAISED_text_never_SPLITS_a_multibyte_character"),
    ("censusprobe: a RAISED message is cut with :sub",
     '(utf8_prefix(tostring(res), 60):gsub("[|' + chr(92) + "t" + chr(92) + "n" + chr(92) + 'r]", " "))',
     '(tostring(res):sub(1, 60):gsub("[|' + chr(92) + "t" + chr(92) + "n" + chr(92) + 'r]", " "))',
     "test_censusprobe_RAISED_text_never_SPLITS_a_multibyte_character"),
    ("contents: macro takes --contents as a property name",
     '        if a == "--contents" then contents = true',
     "        if false then",
     "test_macro_contents_is_a_FLAG_not_a_property_name"),
    ("contents: macro renders contents without being asked",
     '                                 and (contents and render_table(v, 2) or "<table>")',
     "                                 and render_table(v, 2)",
     "test_macro_DEFAULT_still_elides_a_nested_table"),
    ("contents: macro renders ONE level instead of two",
     '                                 and (contents and render_table(v, 2) or "<table>")',
     '                                 and (contents and render_table(v, 1) or "<table>")',
     "test_macro_contents_RENDERS_two_levels_SORTED"),
    ("contents: recon ignores --deep",
     "render_table(v, opts.deep and 2 or 1)",
     "render_table(v, 1)",
     "test_recon_DEEP_descends_exactly_ONE_more_level"),
    ("contents: recon descends a second level without --deep",
     "render_table(v, opts.deep and 2 or 1)",
     "render_table(v, 2)",
     "test_recon_without_DEEP_says_so_and_stays_one_level"),
    ("contents: recon header claims deep=yes regardless",
     '" deep=" .. (opts.deep and "yes" or "no")',
     '" deep=yes"',
     "test_recon_without_DEEP_says_so_and_stays_one_level"),

    # ---- ffisyms: the FFI census verb -------------------------------------- #
    ("ffisyms: LuaJIT's undeclared text is not recognised",
     '                if msg:find("missing declaration for symbol", 1, true) then',
     "                if false then",
     "test_ffisyms_CLASSIFIES_every_name_and_the_buckets_SUM"),
    ("ffisyms: LuaJIT's unexported text is not recognised",
     '                elseif msg:find("cannot resolve symbol", 1, true) then',
     "                elseif false then",
     "test_ffisyms_CLASSIFIES_every_name_and_the_buckets_SUM"),
    ("ffisyms: undeclared is reported as notexported",
     '                    rows[#rows + 1] = name .. "|undeclared"',
     '                    rows[#rows + 1] = name .. "|notexported"',
     "test_ffisyms_CLASSIFIES_every_name_and_the_buckets_SUM"),
    ("ffisyms: an unresolvable symbol raises out of the verb",
     "            local ok, sym = pcall(function() return lib[name] end)",
     "            local ok, sym = true, lib[name]",
     "test_ffisyms_CLASSIFIES_every_name_and_the_buckets_SUM"),
    ("ffisyms: names are not validated before indexing",
     '        if #name > FFISYMS_MAX_NAME_LEN or not name:match("^[%a_][%w_]*$") then',
     "        if false then",
     "test_ffisyms_marks_an_INVALID_name_and_does_not_index_it"),
    ("ffisyms: the name length is not bounded",
     '        if #name > FFISYMS_MAX_NAME_LEN or not name:match("^[%a_][%w_]*$") then',
     '        if not name:match("^[%a_][%w_]*$") then',
     "test_ffisyms_a_name_over_the_LENGTH_bound_is_INVALID"),
    ("ffisyms: the name count is not bounded",
     "    if #names > FFISYMS_MAX_NAMES then",
     "    if false then",
     "test_ffisyms_REFUSES_more_names_than_it_will_bound"),
    ("ffisyms: ffi availability is not checked",
     "    if not ffi_ok or ffi == nil then",
     "    if false then",
     "test_ffisyms_is_ERR_when_ffi_is_unavailable"),
    ("ffisyms: an empty call is not refused",
     # Two lines: `if #names == 0 then` alone also opens another verb (matched 2x).
     '    if #names == 0 then\n        reply(seq, "ERR", "ffisyms needs one or more symbol names")',
     '    if false then\n        reply(seq, "ERR", "ffisyms needs one or more symbol names")',
     "test_ffisyms_is_ERR_with_NO_names"),
    ("ffisyms: the census CALLS what it resolves",
     '                rows[#rows + 1] = name .. "|exported|" .. type(sym)',
     '                rows[#rows + 1] = name .. "|exported|" .. type(sym) .. tostring(pcall(sym))',
     "test_ffisyms_NEVER_CALLS_what_it_resolves"),
    ("ffisyms: the census DECLARES a placeholder first",
     "            local ok, sym = pcall(function() return lib[name] end)",
     '            pcall(ffi.cdef, "void " .. name .. "(void);")\n'
     "            local ok, sym = pcall(function() return lib[name] end)",
     "test_ffisyms_NEVER_DECLARES"),
    ("ffisyms: an OTHER message is quoted unscrubbed",
     '(utf8_prefix(msg, 60):gsub("[|' + chr(92) + "t" + chr(92) + "n" + chr(92) + 'r]", " "))',
     "utf8_prefix(msg, 60)",
     "test_ffisyms_keeps_the_FRAME_intact_for_an_OTHER_message"),
]

orig = LUA.read_bytes()
assert orig.count(b"\r\n") == 0, "mod file is not LF-only"
_ONLY = os.environ.get("X4_MUTATE_ONLY")
if _ONLY:
    MUTANTS = [m for m in MUTANTS if any(o in m[0] for o in _ONLY.split("|"))]
    if not MUTANTS:
        raise SystemExit(f"X4_MUTATE_ONLY={_ONLY!r} matched no mutant")
    print(f"X4_MUTATE_ONLY: running {len(MUTANTS)} mutant(s)")
killed, survived, skipped = [], [], []
try:
    for desc, old, new, test in MUTANTS:
        s = orig.decode("utf-8")
        if s.count(old) != 1:
            skipped.append((desc, f"anchor matched {s.count(old)}x, expected 1"))
            continue
        LUA.write_bytes(s.replace(old, new, 1).encode("utf-8"))
        r = subprocess.run(
            ["uv", "run", "pytest", f"{TESTS}::{test}", "-q", "-x", "--no-header",
             "--deselect", BUILD_TEST, "-p", "no:cacheprovider"],
            cwd=TOOL, capture_output=True, text=True)
        # rc 4 = usage error (e.g. no test matched that id) -- that is a SKIP, not a kill.
        if r.returncode == 4 or "no tests ran" in r.stdout:
            skipped.append((desc, f"pytest matched no test named {test}"))
        elif r.returncode != 0:
            killed.append((desc, test))
        else:
            survived.append((desc, test))
finally:
    LUA.write_bytes(orig)
    assert LUA.read_bytes() == orig, "RESTORE FAILED -- the working tree is left mutated"

print(f"killed {len(killed)} / {len(MUTANTS)}")
for d, t in survived:
    print(f"  SURVIVED  {d}\n            (should have been caught by {t})")
for d, why in skipped:
    print(f"  SKIPPED   {d}  -- {why}")
print("tree restored byte-identical: True")
sys.exit(1 if (survived or skipped) else 0)

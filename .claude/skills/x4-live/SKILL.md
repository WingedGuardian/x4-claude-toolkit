---
name: x4-live
description: Use when querying the RUNNING X4 game over the live channel, or when a live query that worked a minute ago starts refusing ids, returns fewer objects than expected, or reports zero while the game is plainly running. Also use before treating any live enumeration as a complete census.
allowed-tools: Bash, Read, Grep
---

Ask the running engine, then read the answer for what it is NOT.

The commands and their arguments are in the toolkit's own README and `--help`; this skill
carries only the traps, because they are what cost a session and they are not discoverable
from the output.

## When to use

- Any question about the game's state **right now** rather than what the XML says.
- A live query began refusing ids, or its counts moved between two calls.
- Before writing down a live enumeration as "all of X".

## Preconditions, in this order

1. **The game must be running.** Windowed-unfocused is fine; minimised in exclusive
   fullscreen stops the update loop and therefore the channel. A stall is not a failure —
   retry.
2. **The game-side helper extension must be deployed** to the game-root `extensions\`, with
   the named-pipe support mod it depends on. Do not assume: `probe` answers it.
3. **Run `probe` first, every session.** `build=` says whether the game is running the file
   currently on disk. `loaded_at=` says whether the chunk has been re-executed. Different
   questions — a reload keeps the same build.
   ⚠ **`loaded_at` is a CHANGE detector — not a clock, not a counter.** It comes off a
   timer that RESETS with the UI (measured 0.89 then 0.82 across two real reloads), so it
   can only say "different from last time". Re-record it after every enumeration and
   compare against the MOST RECENT reading; a session-start baseline will blame a reload
   for a mistyped id once any real reload has happened. And an id refusal after a reload
   already NAMES the reload and both causes (alt-enter, save load) — read it first.

## The traps

| trap | consequence |
|---|---|
| **A UI reload EMPTIES the id allowlist** | every id you already hold stops resolving. The refusal names the reload and both causes — read it; it is not a fabricated-id error. **Re-run the enumeration that issued them.** |
| **Alt-Enter causes a reload; a save load causes one; alt-tab does NOT** | the variable is the graphics-mode change, not focus |
| **No lua state survives a reload, `_G` included** | nothing can be remembered game-side between reloads; any counting lives in the client |
| **Sector tokens are per-launch, and the guard checks SHAPE, not identity** | an UNRESOLVABLE token (`ID:` truncated, or not a token at all) makes the engine ignore the container and return everything that faction owns ANYWHERE, labelled as that sector — measured 310 vs 1,961. A stale but WELL-FORMED token from a prior launch is UNMEASURED: launches allocate near-adjacent ids, so it may resolve to a DIFFERENT live sector and fail toward a SMALLER number with no size tell. Never persist one; re-read it from `player`/`galaxyprobe` after any reload. No cross-check from the count alone is reliable — an owner concentrated in one sector gives the same number either way. |
| **Enumeration is owner-scoped, so it is not a census** | ownerless objects belong to no faction and cannot appear; hidden factions are opt-in |
| **Names are player knowledge; ids and positions are exact** | most rows come back Unknown. That is not a channel defect and must not be filtered away. |
| **The population drifts by tens of objects per minute** | two separate queries cannot be diffed. Use the verb that compares inside one frame. |
| **An over-long reply tears the pipe down** | it does not truncate. Every verb caps itself and says how many rows it omitted — read the header, not the row count. |
| **An error caught inside the probe never reaches `debug.txt`** | the pipe reply is the only record, so do not conclude "no error" from the engine log |
| **`pause` and `unpause` change the game the user has open** | run them only when the user asked. The exit code is the engine's READ-BACK: 0 verified, 1 refused with nothing changed, 3 do not trust the state |
| **`unpause` undoes only a pause THIS channel made** | it refuses the player's or a menu's pause. A UI reload forgets which pause was ours, and EVERY unpause attempt gives up the claim -- even one whose read-back still shows paused -- so in both cases a remaining pause is undone IN GAME, never by retrying |
| **A write whose reply was lost may still have landed** | the command is sent before the reply is read and is never resent. Run `pausestate` before anything else, never a second `pause` |
| **`query globals` sees only the lua global table** | vanilla's ui lua declares thousands of C functions in `ffi.cdef` that never appear there, so a `globals` negative covers a fraction of the engine surface. Use `ffi-census` for the C side |
| **`ffi-census` `undeclared` is about THIS session's lua, not the engine** | it means no lua loaded this session declared the name (its file's block did not run, or it is commented out) -- not that the engine lacks the function. `exported`/`notexported` answer about the game PROCESS: on Windows LuaJIT also searches the libraries the executable loaded |
| **A request can be too long, not just a reply** | the game-side read fails on a message larger than its buffer, and that ceiling is unmeasured. `ffi-census` batches small by default; do not raise `--batch-bytes` without measuring |
| **`macro` answers `<table>` for a table-valued field by default** | pass `--contents` to render it two levels deep. Harvests store the default reply, so keep a fixture's mode in its header (`groundtruth` writes it) |

## Read the header, not the rows

Row output is capped by a byte budget while the match count keeps counting. The header carries
the denominators. A row count is not an answer.

## The offline half is a different tool

Some verbs read a profile file the game **truncates while running**, and they refuse rather
than report zero of everything. Those answer "what did the engine see at load", not "what is
true now". Do not reach for them for a live question.

## Common mistakes

- Treating a clean small number as a census. State the scope caveat with the number.
- Holding ids across an Alt-Enter and blaming the tool for the refusal.
- Diffing two separately-timed queries and reading drift as a method difference.

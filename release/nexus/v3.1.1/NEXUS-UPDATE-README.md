# Nexus 2186 update pack for v3.1.1

Built 2026-09-09 from the **live page as it stands right now**, re-fetched through the
Nexus API on the day (never scraped — Nexus 403s automated page fetches).

**The live page serves 2.7.0.** MEASURED, not remembered: `version: "2.7.0"`,
`updated_time: 2026-08-27T01:03:07Z`, description 24,267 characters. So Nexus jumps
**2.7.0 → 3.1.1 in one step** and never sees 2.8.0, 2.9.0, 3.0.0 or 3.1.0 as separate
updates. The changelog file carries a block for each of them.

## Files

| file | what it is |
|---|---|
| `NEXUS-CHANGELOG-v3.1.1.txt` | changelog entries, **one item per line**, in a block per version: 3.1.1 / 3.1.0 / 3.0.0 / 2.9.0 / 2.8.0 |
| `NEXUS-DESCRIPTION-v3.1.1.bbcode.txt` | the full updated description, ready to paste |
| `NEXUS-DESCRIPTION-DIFF.txt` | exactly what changes vs the live page — **61 lines added, 6 rewritten, 0 lost** |
| `nexus-2186-CURRENT-description.editor.bbcode.txt` | the live page before the edits, for rollback |
| `nexus-2186-CURRENT-description.txt` | the same, exactly as the API returned it (the authoritative copy) |
| `nexus-2186-CURRENT.json` | the raw API response: dated evidence of the pre-update state |
| the bundle | **not built yet — see "Before you upload" below** |

The rollback copy is derived from the API response by stripping the per-line `<br />`
and decoding `&amp;`/`&lt;`/`&gt;`/`&#92;` in a **single** pass (a sequential decode
turns a literal `&lt;` on the page into a real `<`). That derivation was proven against
the v3.0.0 pack's stored copy: identical but for line endings. If you want the
byte-exact API text, use `nexus-2186-CURRENT-description.txt` beside it.

## What carries forward from the v3.0.0 pack

The v3.0.0 pack was written and **never uploaded**, so it is unshipped work rather than
stale work, and this description is built on top of it. Everything it added is still
here — confirmed as wanted:

- **The DevBench credit**, linking [alandtse's DevBench](https://www.nexusmods.com/skyrimspecialedition/mods/181326),
  saying plainly that it is the mature version of this idea, that `x4live` does
  considerably less today, and that DevBench is the better tool and isn't ours.
- **The "Also new since v2.7" catch-up**, covering 2.8 and 2.9 for readers who jump the
  gap: `x4save`, `x4diff --base`, nested cross-mod patch checking, `x4modlist tracked`.
- The `x4debug` / `x4save` / `x4live` tool blurbs, and the v3.0 section.

## What is new in this pack

**One section added**, above the v3.0 one, whose heading is demoted to "Also new in
v3.0" — it is still new to a Nexus reader. It covers the two total bypasses of every
hard block, the guard hang, the 61% of the guard that had never been fuzzed, the
installer round, the `x4stats` fix, the nine tests that could not fail, and the v3.1.1
close-out.

**Three numbers re-measured at this tree**, because a stale figure in marketing copy is
a claim we cannot support:

| was | now | how it was measured |
|---|---|---|
| 1,387 automated tests and 29 gates | **1,718** tests and 29 gates | full suite: 1,704 passed, 14 skipped, rc 0 |
| 138 hook probes | **160** probes | `scripts/test-hooks.sh`: 160 passed, 0 failed, 0 skipped |
| "currently 241/241 agreement" | the **bar**, not a count | that number is machine-local — it is measured against *your* `debug.txt` and *your* modlist. `gates/README.md` says so itself: "the BARS are what transfer, not the counts." |

**Checked and left alone:** "Eleven command-line tools" (11 console scripts) and "the
twelve tools above" (11 + BaseX corpus search) are both still correct.

Every edit is anchored and **refuses** rather than guessing if its anchor is not found
exactly once.

## ⚠ Before you upload

**This pack is for v3.1.1, which is not built or tagged yet.** v3.1.0 is public on
GitHub, and it should not be what goes to Nexus: CI was **red on both legs at the
v3.1.0 tag**, on the step that runs `scripts/fuzz-guard.py` — the differential fuzzer
those release notes tell users to run themselves. It exits 2 for everyone. The three
defects behind that are fixed and verified (see `CHANGELOG.md`), but the release itself
still needs your go-ahead, a tag, a bundle built from that tag, and a CI run observed
green before any of it reaches Nexus.

So the bundle row above is deliberately empty. It gets its size and sha256 when the
release is cut, and this file is updated in the same step.

## The upload is yours

Nexus has no write API for files or for the description, so this part is manual: new
file under mod 2186, set the new version MAIN, mark 2.7.0 OLD, paste the changelog and
the description. Everything you need to paste is in this folder.

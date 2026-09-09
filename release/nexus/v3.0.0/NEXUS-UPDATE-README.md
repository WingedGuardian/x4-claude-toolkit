# Nexus 2186 update pack for v3.0.0

Built 2026-09-05 from the **live page as it stands now** (fetched via the Nexus API,
not from memory or an old copy). Nexus currently serves **2.7.0**, so 2.8.0 and 2.9.0
have never appeared there.

## Files

| file | what it is |
|---|---|
| `nexus-2186-CURRENT-description.txt` | the live page exactly as the API returned it |

> ⚠ **This pack was never uploaded, and the v3.0.0 bundle is not in this folder.**
> An earlier version of this table listed
> `X4.Foundations.Claude.Code.Toolkit.v3.0.0.zip` (6,508,551 bytes, sha256
> `273d242c…03fd4de6`) as though it were here. It is not, and never was — that row
> described the GitHub release asset. **`release/nexus/v3.1.1/` supersedes this
> folder**; this one is kept as the dated record of what was written for v3.0.0.

| `NEXUS-CHANGELOG-v3.0.0.txt` | changelog entries, one line per item, for 3.0.0 / 2.9.0 / 2.8.0 |
| `NEXUS-DESCRIPTION-v3.0.0.bbcode.txt` | the full updated description, ready to paste |
| `NEXUS-DESCRIPTION-DIFF.txt` | exactly what changed vs the live page |
| `nexus-2186-CURRENT-description.editor.bbcode.txt` | the live page before my edits, for rollback |
| `nexus-2186-CURRENT.json` | the raw API response, dated evidence of the pre-update state |

## What I changed in the description, and nothing else

The page was kept as it is. Nine anchored edits, each one refusing rather than guessing
if the anchor was not found exactly once. **42 lines added, 6 rewritten, 0 lost.**  
*(Corrected 2026-09-09: this said 43. Re-measured against the two files in this folder, and against this pack's own NEXUS-DESCRIPTION-DIFF.txt, both of which say 42. Found by the v3.1.1 release reviewer.)*

**Added, near the top:**
1. **New in v3.0** section — the live channel, the walkable guard and how it was found, the
   effective-tree data bug, and the file-protection layer. Ends with the Python note.
2. **A DevBench credit at line 17**, as you asked. It links
   [alandtse's DevBench](https://www.nexusmods.com/skyrimspecialedition/mods/181326)
   (Skyrim SE 181326, v1.17.0, updated 2026-09-05 — confirmed by API, not by search),
   says plainly that it is the mature version of this idea, that `x4live` does considerably
   less today, that ours is under active development, and that DevBench is the better tool
   and isn't ours.
3. **Also new since v2.7** — a short catch-up covering 2.8 and 2.9, since Nexus users jump
   straight over both: `x4save`, `x4diff --base`, nested cross-mod patch checking,
   `x4modlist tracked`.
4. **Three tool blurbs** — `x4debug`, `x4save`, `x4live` — in the tools section.
5. **Two bullets** — the optional game extension, and `/x4-balance` + `/x4-probe` in skills.

**Rewritten because the numbers had rotted** (all six re-measured from the shipped bundle):

| was | now |
|---|---|
| Eight command-line tools | Eleven |
| The nine tools above | The twelve |
| 638 automated tests and 26 gates | 1,387 tests and 29 gates |
| 234/234 engine agreement | 241/241 |
| 33 hook assertions | 138 probes |
| uv + Python 3.13 runs the tools | …and as of v3.0 the guard needs Python too |

## Suggestion I did not act on

Your Skyrim toolkit (SE 176043) already names DevBench in its summary. A reciprocal link
between the two of yours would be reasonable, but you did not ask for it, so the X4 page
links only to DevBench.

## The upload itself is yours

Nexus has no write API for files, so this is a manual action on the site: new file under
mod 2186, set 3.0.0 as MAIN, mark 2.7.0 as old, paste the changelog and the description.

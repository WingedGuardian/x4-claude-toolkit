# Gates

> **These are contributor gates. You do not need them to use x4validate** — skip this
> page unless you are changing the merge model or the resolve chain. `uv run pytest`
> is the suite; this is the layer that checks the tool against the *engine*.

Harnesses that must pass before any commit that touches the merge model or the
resolve chain. They are **not** unit tests — they run against the real installed
modlist and a captured engine log, so they live here rather than in `tests/`.
Run them from `tools/x4validate/`.

| Gate | Run | Bar |
|---|---|---|
| `oracle.py` | `uv run python gates/oracle.py` | **234/234 ops agree, 0 FALSE OK.** Replays every diff op the engine itself rejected (from a captured `debug.txt`) and requires x4validate to reject the same ones. `debug.txt` is ground truth; a drop here means the merge model moved. |
| `oracle_index.py` | `uv run python gates/oracle_index.py` | **12/12 agree, 0 FALSE OK** over the index-lookup failures the engine logged. Note the structural limit stated in its own output: a failure-only log can prove FALSE OK but never completeness. |
| `regress.py` | `uv run python gates/regress.py [installed_mod ...]` | Tier A + Tier B error/degraded counts per mod under `$X4_MODS`. *(The recorded baseline — `X4CapturableXenonXL_public` 4 Tier B errors, every other 0 — is the author's own local mod set; yours will differ. What transfers is "no unexplained change from your own last run".)* |
| `schema_sweep.py` | `uv run python gates/schema_sweep.py` | **127 pairs · 45 gating + 57 advisory + 3 suppressed · 10/102 mods flagged**, and the four independently-evidenced defects still reported. Freezes the measurement W3.1 was built to reproduce, so the composition of the output cannot drift unnoticed. |

## Inputs

Every input resolves through `gates/_env.py` → `x4validate._paths`, i.e. the same
env → `.claude/x4-paths.env` → fallback chain the CLI uses. Nothing is hardcoded:

| | from |
|---|---|
| installed extension set | `$X4_GAME` / `$X4_EXTENSIONS` |
| mod source folders (`regress.py`) | `$X4_MODS` |
| captured engine log (the two oracles) | **`$X4_ORACLE_LOG`** |

`$X4_ORACLE_LOG` must be a **capture, not the live `debug.txt`** — if the log moves
between runs the denominator moves and 234/234 stops meaning anything. It is
deliberately never committed: a real `debug.txt` names the mods you run, your
filesystem layout and your play session. Reproducing these numbers means supplying
your own log against your own modlist; the *bars* are what transfer, not the counts.

**A missing input is a SKIP with a named reason and exit 2** — never an empty run
that prints like a pass. Verified 2026-07-29 from a scrubbed environment: all four
exit 2 and say which setting is absent.

> Until 2026-07-29 three of these four opened with hardcoded absolute paths from
> one developer's machine, and an earlier version of this README claimed the
> opposite. If you add a gate, take its inputs from `_env`.

**Why `oracle.py` is not in `tests/`:** it needs the installed extension set and
a specific captured log. A developer without those would see it fail for reasons
unrelated to their change, which is exactly how a gate gets disabled.

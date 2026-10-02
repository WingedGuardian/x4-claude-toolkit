# Isolated tool audit harness

Audit-first scripts used for the 2026-10-01 report in
`docs/audits/2026-10-01-tools.md`. They do not patch tool implementations.
They require a dedicated Windows Git worktree, existing Python 3.13 environment,
Git Bash, and Java for BaseX. This is a local audit instrument, not a shipped CLI.

Before importing `driver`, create an untracked `audit-output/local-paths.json`:

```json
{
  "source": "C:/path/to/original/toolkit",
  "game": "C:/path/to/X4 Foundations",
  "modding": "C:/path/to/Modding/X4",
  "profile": "C:/path/to/Egosoft/X4/profile-id"
}
```

`modding` must contain `reference`, `dev/_registry/modlist.yaml`, and the local
tools if running the optional archive/deploy probes. Never point these scripts
at the original checkout as their audit lane. The import guard requires a Git
worktree `.git` file. All listed inputs must already exist and be understood.

Run from `tools/x4validate`, using an existing environment with dependencies:

```powershell
python audit/driver.py setup
.venv/Scripts/python.exe audit/driver.py interface
.venv/Scripts/python.exe audit/driver.py tests
.venv/Scripts/python.exe audit/exercise.py fixtures
.venv/Scripts/python.exe audit/exercise.py corpus
.venv/Scripts/python.exe audit/exercise.py real
.venv/Scripts/python.exe audit/driver.py basex-build
# WAIT for both database builds to finish before querying:
.venv/Scripts/python.exe audit/extra.py basex
.venv/Scripts/python.exe audit/extra.py basex_fixture
.venv/Scripts/python.exe audit/extra.py archives
.venv/Scripts/python.exe audit/extra.py old_index
.venv/Scripts/python.exe audit/extra.py load_controls
.venv/Scripts/python.exe audit/driver.py snapshot
```

Setup copies the source environment, registry, and profile enable decisions;
it generates an isolated BaseX configuration rather than copying the personal
one. It does not sync/install dependencies. `UV_OFFLINE` is set. Archive template
tests require the already-local empty/template directory; review before allowing
an upstream tool's network fallback. Do not start the live pipe server.

Do not run builds against the same scratch database concurrently. Separate
tools may run concurrently with independent outputs; corpus uses one ledger
writer and should be run once.
`fixtures` and `basex_fixture` share inputs: run them sequentially, including
waiting for fixture generation to finish before building its BaseX database.
The full corpus sweep compiles large XSDs and
can take many minutes. Installer tests are excluded from `tests`; 49 skips in
the recorded run are explicitly disclosed in the report.

Fresh pytest temp folders live outside the Git worktree, because tests that
expect a non-repository directory otherwise discover the parent repository.
TMP/TEMP are preserved. Each command has a timeout and raw logs, with repeats
archived. New command records include toolkit source revision and driver.py hash;
they do not fingerprint every exercise script. The final summary separately
hashes the external deployer and x4cat scaffold source.

Exit 1 means at least one command or assertion disagreed with its prediction;
known unfixed defect probes intentionally produce this result. Exit 0 from an
older harness revision was only orchestration completion. A ledger `okay` means
the exit code was accepted and no Python traceback appeared; inspect assertions
and output to distinguish positive behavior, refusal, degradation, and bugs.
The harness must not be described as a passing functionality suite while the
documented defect probes fail.

`deploy_probe.py` rebinds the legacy helper's DEV and EXT roots before invoking
it. Its fixtures refuse existing directories and stay inside the lane, including
the simulated victim outside an extension. The probes can create a scratch
junction. Never reuse this probe for a production apply.

Snapshots are evidence, not filesystem enforcement. Their coverage is limited
as described in the report; identical metadata is not a full content hash proof.
Keep raw game/save/log artifacts and local paths untracked.

## Post-review repair verification

`fix_verify.py` reads `reviewed_x4cat` and `reviewed_dev` from the same local JSON;
point these at the isolated reviewed checkouts. Preserve `corpus.jsonl` and
`population.json` as `before-fixes-corpus.jsonl` and `before-fixes-population.json`
before repeating the corpus sweep. `before` fingerprints tested implementation
bytes and records a protected-input metadata snapshot; `scratch` exercises repaired
CLI boundaries, complete templates, archive readers and both external suites.
Run `basex` only after `exercise.py real` finishes: they share a scratch effective
store. `schema` substitutes the discovered game path in memory for x4cat's
foreign hardcoded test path, then executes the same assertions against read-only
game archives. It removes only the decorator capturing that absent foreign path.
`after` compares every corpus report and protected metadata, and refuses on
differences requiring investigation. Keep all raw evidence untracked.
`summarize.py summary` is an archival baseline helper and refuses changed tool
implementations; its baseline labels must never become a repair verdict.
After integration, `install_verify.py` selects the installed package and actual
uv launchers, keeps writes in scratch fixtures and verifies the existing local
lockfile. `installed_metadata.py` pins the later metadata-boundary fix and a valid
stale read on byte-checked SQLite copies. `fix_verify.py archives` proves the
installed homegrown reader/extractor consumes official ext_01.cat data.
When `reviewed_dev` is present, `deploy_probe.py` uses that reviewed helper;
without it, the historical probe still selects the original installation.
The scratch mod name is selected from the helper's owned list rather than
embedding a contributor's private mod name in the portable harness.

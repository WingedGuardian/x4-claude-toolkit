# ADAPTING.md -- connecting an agent the X4 AI Assistant Toolkit does not support yet

**Read this if you are an AI agent and this toolkit ships no adapter for you.**
`bash install.sh --help` (or `install.ps1 -Help`) lists the agents it has adapters for; the two
worked examples below are Claude Code (the guards ARE its hooks) and OpenAI Codex.

Until you have an adapter that passes the proof in section 5, **none of the toolkit's guards
protect anything you do.** The only protection left is the operating system's: the
`reference/` tree is read-only on disk. Tell your user that, in those words, before you start
modding -- and do not tell them the guards are live because the files are present.

What an adapter is: a small program your agent runs as its "before a tool call" hook. It
TRANSLATES your agent's payload into one question for the toolkit's guards, and TRANSLATES the
answer back into the shape your agent obeys. It decides nothing itself. The guards are the
policy; your adapter only carries it.

Evidence tiers used below: **MEASURED** (someone ran it and counted), **READ** (it is in the
code, file named), **INFERRED** (reasoned, not run). Write your own findings the same way.

## 0. Before you start

- You need a guard tree: `.claude/hooks/` or `.codex/hooks/`, from an install that included
  Claude Code or Codex (`--agent all` includes both), from the release zip, or from a git clone.
  An install made with `--agent generic` ships no guard tree at all (READ: `install.sh`,
  `X4_AGENT_ITEMS_generic`).
- `x4guard conformance` (section 5) additionally needs the toolkit's `scripts/` folder, Git
  Bash (on Windows) and `jq`. A toolkit installed by either installer has all three locations.
- Python 3.10 or newer for the guard front door; it is stdlib only.
- Never edit a guard, the test corpus or another agent's adapter to make yours pass (section 6).

## 1. Self-assessment

Fill this capability report for YOUR agent first. Every row carries its evidence tier; a row
you could only guess is marked INFERRED or ASSUMED and becomes a gap you report. The same
fields are used in section 7, so a submission is this block, filled in.

```
AGENT: name of the agent
VERSION: exact version you measured
OPERATING SYSTEM: and the shell your agent's shell tool really executes there
HOOK EVENTS: which events exist; which one runs BEFORE a tool call
PAYLOAD CAPTURE: fixtures captured from a LIVE run (never hand-written), and where they are stored
TOOLS THAT WRITE: every tool that can change a file or run a command; which of them fire the hook
SHELL ROUTING: which shell executes the shell tool, per OS (a tool called "Bash" may run PowerShell)
VERDICT SHAPES HONOURED: deny / ask / add-context -- each one MEASURED as honoured or not
FAIL MODE: the five rows of the table below, each "blocked" or "ran", MEASURED
HOOK APPROVAL: can a changed hook definition silently stop running until someone re-approves it?
CONTEXT CAP: how much hook text your agent shows the model before truncating it
NATIVE POLICY LAYER: any built-in permission rules you can also use (deny-lists, sandboxes)
INSTRUCTION FILE AND BYTE CAP: the file your agent reads at start, and where it truncates it
EVIDENCE: the tier of every row above, and the commands or transcripts behind each MEASURED one
```

Two examples of why each row matters (MEASURED on Codex 0.160.0, 2026-09-30, in
`docs/superpowers/measurements/2026-09-30-codex-spike.md`): Codex labels PowerShell commands
"Bash" on Windows, so an adapter that judged them as bash let a PowerShell write into
`reference/` through; and Codex ignores an "ask" answer entirely and runs the call.

### Does your hook system fail open or closed?

This is the most important row, and it must be MEASURED, never read from documentation. Make a
scratch folder with one decoy file in it. Install, one at a time, a hook that does each thing
below, and each time ask your agent to overwrite the decoy:

| row | the hook... | if the decoy was overwritten |
|---|---|---|
| a | prints your agent's documented DENY answer and exits 0 (the control) | STOP: nothing in this document can protect you; your agent does not honour a deny |
| b | exits 2 and writes a reason to stderr | exit codes fail open |
| c | crashes (an uncaught exception, any non-zero exit) | crashes fail open |
| d | sleeps longer than your agent's hook timeout | timeouts fail open |
| e | prints garbage (not your agent's answer format) | unreadable output fails open |

Record "blocked" or "ran" for every row. Row (a) must say "blocked" or there is no point
continuing. **Any other "ran" means your agent fails open on that path**, and your adapter must
never take it: every failure inside the adapter has to end as a printed deny, exit 0, in time.
If your adapter itself can crash (it can), put a small fail-closed WRAPPER in front of it that
turns anything unexpected into a deny -- the Codex example in section 3 does exactly that.

## 2. The guard contract

The toolkit's front door is `x4guard.py`, in `.claude/hooks/` (or `.codex/hooks/`). It takes
ARGUMENTS, not stdin, and there is no agent option -- describe the action, not yourself:

```
python .claude/hooks/x4guard.py check --kind shell --shell bash --command "<command>"
python .claude/hooks/x4guard.py check --kind shell --shell powershell --command "<command>"
python .claude/hooks/x4guard.py check --kind write --path "<file>"
python .claude/hooks/x4guard.py check --kind delete --path "<file>"
```

It prints ONE line of JSON and exits 0 for every verdict (READ: `agent/guards/claude-hooks/x4guard.py`):

```json
{"v": 1, "decision": "allow|advise|ask|deny", "reason": "...", "context": "...", "inert": false, "guards": ["..."]}
```

Exit 2 means a usage error (a wrong option). The rules for calling it:

- **Run it in your agent's working directory** -- the `cwd` your agent reports for the call, not
  wherever your adapter happens to be. A relative path, and a relative operand inside a shell
  command, are judged from the process's own working directory (READ: x4guard resolves
  `--path` with `abspath` and puts `os.getcwd()` into the shell payload). Set the subprocess
  `cwd`; do not rewrite the paths yourself.
- **`--shell` names the shell that will EXECUTE the command**, not what your agent calls the
  tool. If you cannot tell, measure it (section 1, SHELL ROUTING).
- **`--kind delete`** for anything that removes or moves a file away; x4guard judges it as the
  stricter of a write and an `rm -rf` of that path. A move is a delete of the source plus a
  write of the destination. A tool that touches several files is several checks; the worst
  verdict wins (deny > ask > advise > allow).
- **`inert: true` means the guard could not run** (no bash, a timeout, a missing script). It
  always arrives as `decision: "deny"`. Render it as a deny -- or as a question to the user if
  your agent can MEASURABLY ask -- and never as an allow.
- **Treat everything unexpected as an inert deny**: a non-zero exit, empty output, output that is
  not JSON, a `v` other than 1, or a timeout.
- **Time budget.** `X4_GUARD_TIMEOUT_S` is x4guard's budget for one check. Its default value is
  stated in the docstring of x4guard itself and deliberately not restated here. The worst case wall clock is
  that budget plus `KILL_WAIT_S` plus `DRAIN_GRACE_S` (constants in the same file). Your own
  timeout must sit ABOVE that worst case and BELOW your agent's hook timeout. If your agent's
  hook timeout is too short for that, lower `X4_GUARD_TIMEOUT_S` for the check, and still
  enforce your own deadline below the agent's: a check that has not answered in time is an
  inert deny that YOU print.
- **Finding x4guard.py.** Locate it relative to your adapter's own file, or from a path the
  install configured. Do not build it from `X4_TOOLKIT` alone: under `x4guard conformance` that
  variable names a SANDBOX toolkit with an empty hooks folder, and in an install it may be unset.
- **`X4_GUARD=off`** is the user's launch-time escape hatch. x4guard handles it (every verdict
  becomes an advisory saying so); your adapter does nothing special.
- **`check` has no side effects**: it never makes the backup that the Claude hooks make before an
  edit. An adapter that wants backups runs `.claude/hooks/backup-before-edit.sh` itself after an
  allow, as the Codex adapter does.
- **Context size.** Bound any `reason` or `context` you inject to `X4_HOOK_MAX_CHARS` characters
  (its default is in `.claude/hooks/_x4-env.sh`), keeping the FIRST part: the directive comes first.
  If your agent reads only one line, flatten newlines to spaces.

Rendering -- from x4guard's decision to your agent's native answer:

| x4guard says | render as |
|---|---|
| `allow` | your agent's "no objection" (often: print nothing) |
| `advise` | added context for the model, carrying `context` |
| `ask` | a native ask ONLY if you MEASURED that your agent honours one. Otherwise a DENY whose reason starts with `NEEDS YOUR APPROVAL:` followed by the reason, so the model stops and asks its user |
| `deny` | a native deny carrying `reason` |
| `deny` with `inert: true` | a deny carrying `reason` (it starts `X4 GUARD INERT`); never an allow |

## 3. Worked examples

### Worked example: Claude Code

Claude Code is the identity case: the guards ARE its hooks, registered in
`agent/targets/claude/settings.json` and rendered into `.claude/`. There is no translation, so
there is no adapter. `scripts/conformance-profiles/claude.json` runs each case's own hook on its
own payload; it is the engine's IDENTITY CONTROL -- if that profile ever disagrees with the
guards, the conformance engine is broken, not an adapter.

### Worked example: Codex

`agent/guards/adapters/codex.py` (rendered to `.codex/hooks/codex_adapter.py`) is the full pattern.
What it had to handle, all MEASURED on Codex 0.160.0:

- Codex fails open on everything except a parsed JSON deny, and rejects any JSON key it does not
  know. So the adapter prints one line, `X4OK <json>`, and a wrapper
  (`agent/guards/adapters/codex-entry.ps1` on Windows, `agent/guards/adapters/codex-entry.sh`
  elsewhere) prints the JSON only if it is well-formed, and a fail-closed deny otherwise.
- Codex has no working ask, so an ask is a deny reading `NEEDS YOUR APPROVAL: ...`.
- Codex's "Bash" tool runs PowerShell on Windows: the adapter judges it with `--shell powershell`
  there.
- `apply_patch` names several files, with paths relative to the session cwd: the adapter parses
  the patch (`agent/guards/adapters/patch_paths.py`), turns add/update/move-to into writes and
  delete/move-from into deletes, and judges every path from the payload's `cwd`.
- Codex silently disables a hook whose definition changed until the user re-approves it, so
  `agent/targets/codex/hooks.json.tmpl` is frozen: logic changes go into the adapter, never into
  the hook definition.

Its conformance profile is `scripts/conformance-profiles/codex.json`; it feeds the adapter Codex
payloads captured from a live run (`tools/x4validate/tests/fixtures/codex/0.160.0/`).

## 4. Where your adapter goes

**Locally first.** Put your adapter and its profile anywhere (a folder of your own beside the
toolkit is fine) and run conformance against them with `--profile <path>`. Nothing in the
toolkit has to change for that.

**Upstream, once it passes** (section 7), the files go here:

- the adapter: `agent/guards/adapters/<agent>.py`
- a generator target in `tools/x4validate/scripts/gen-agent-trees.py` (the model to copy:
  `CODEX_ADAPTERS` and `render_codex_hooks`), and your agent's own files under
  `agent/targets/<agent>/`
- an installer item set `X4_AGENT_ITEMS_<agent>` in `install.sh` AND the same set in
  `install.ps1` (a test checks that the two agree)
- the profile: `scripts/conformance-profiles/<agent>.json`
- the captured payloads: `tools/x4validate/tests/fixtures/<agent>/<version>/`

### Writing a conformance profile

`x4guard conformance` replays every guard case of the toolkit's own hook test suite, plus the
neutral extras in `scripts/conformance-extra-cases.json`, through your adapter, and compares
each answer with what the guards decide. Each case is one of four KINDS: `shell-bash`,
`shell-powershell`, `edit` (change an existing file) and `write` (create a file with content).
Your profile tells the engine how to build YOUR agent's payload for each kind, how to run your
adapter, and how to read its answer. A minimal one (the shape the toy agent's adapter uses):

```json
{
  "v": 1,
  "agent": "toy",
  "command": ["{PYTHON}", "my_adapter.py"],
  "requires": ["bash", "jq"],
  "run_cwd": "neutral",
  "timeout_s": 120,
  "env": {"X4_GUARD_PY": "{HOOKS}/x4guard.py"},
  "cases": {
    "shell-bash":       {"payload": "payloads/run_shell.json",
                         "set": {"/args/cmdline": "{{COMMAND}}", "/args/interpreter": "bash", "/workdir": "{{CWD}}"}},
    "shell-powershell": {"payload": "payloads/run_shell.json",
                         "set": {"/args/cmdline": "{{COMMAND}}", "/args/interpreter": "powershell", "/workdir": "{{CWD}}"}},
    "edit":  {"payload": "payloads/edit_file.json",  "set": {"/args/target": "{{PATH}}", "/workdir": "{{CWD}}"}},
    "write": {"payload": "payloads/write_file.json", "set": {"/args/target": "{{PATH}}", "/args/text": "{{CONTENT}}", "/workdir": "{{CWD}}"}}
  },
  "unsupported": {},
  "output": {
    "format": "text",
    "exit_codes": {"0": "decode"},
    "empty": "allow",
    "rules": [
      {"regex": "^TOY-BLOCK (?P<text>NEEDS YOUR APPROVAL:.*)$", "decision": "ask"},
      {"regex": "^TOY-BLOCK (?P<text>.*)$", "decision": "deny"},
      {"regex": "^TOY-NOTE (?P<text>.*)$",  "decision": "advise"}
    ]
  }
}
```

Field by field:

- `command`: your adapter's argv. Placeholders: `{TOOLKIT}` (the toolkit running the engine),
  `{HOOKS}` (its `.claude/hooks`), `{PYTHON}` (the engine's interpreter), `{BASH}`, `{PWSH}`.
  A relative path in it is relative to the directory the adapter runs in (see `run_cwd`), so use
  an absolute path or pass the command after `--` instead. Anything after `--` on the command
  line replaces `command`.
- `requires`: programs that must exist, or the run stops with exit 2.
- `run_cwd`: `"neutral"` (the default, and what you want) runs your adapter in an EMPTY scratch
  folder, exactly like an agent that starts hooks somewhere unrelated. An adapter that ignores
  the payload's working directory then fails the relative-path cases, as it would in real use.
- `env`: added to the environment your adapter runs with. Each case already runs with the
  sandbox's `X4_TOOLKIT`, `X4_GAME`, `X4_REFERENCE` and friends -- pass them through to x4guard
  untouched (inheriting your environment does that).
- `cases`: per KIND, a `payload` template file (a captured payload of YOUR agent, path relative
  to the profile file) and `set`: JSON pointers into it, filled per case after parsing, so no
  escaping is needed. Tokens: `{{COMMAND}}` (the shell command), `{{PATH}}` (the file),
  `{{CONTENT}}` (a write's content), `{{CWD}}` (the call's working directory), and
  `{{CONTENT|lines:+}}` (each line prefixed with `+` and ended with a newline, for patch formats).
  A case may also carry its own `env`. An unknown token stops the run with exit 2.
- `unsupported`: `{"KIND": "why"}` for a kind your agent truly cannot produce. Every kind must be
  in `cases` or here. An unsupported kind is printed as a GAP on every run; its cases are not
  replayed. It is a gap you report, never a pass.
- `output`: how to read your adapter's stdout. `exit_codes` maps an exit status to `"decode"`
  (read stdout) or to a decision; any status not listed is unreadable. `empty`: the decision an
  empty stdout means (leave it out and empty output is unreadable). `format` `"text"`: `rules`
  are regexes tried in order, the first match wins, a named group `text` carries the reason.
  `format` `"json"`: each rule is `{"when": {pointer: value or {"present": true}}, "absent":
  [pointer], "text": pointer, "decision": D, "prefix_decisions": {"NEEDS YOUR APPROVAL:": "ask"}}`;
  `allowed_keys` (`{"": [...], "/inner": [...]}`) makes an unexpected key unreadable -- use it
  when your agent fails open on unknown keys. Optional: `strip_prefix`, `single_line`. A deny or
  ask whose text contains `X4 GUARD INERT` is read as `inert`. Output no rule matches is
  `unreadable`, which counts as a disagreement, never as an allow.

## 5. Required proof

Your adapter is supported when, and only when, all four of these hold:

**(a) Conformance exits 0.**

```
python .claude/hooks/x4guard.py conformance --profile path/to/profile.json -- python path/to/adapter.py
```

It dumps the corpus fresh (a few minutes), replays it, and prints every disagreement by name.
Exit codes: **0** every replayed case agrees and at least `--min-cases` (default 80) were
replayed; **1** at least one disagreement or unreadable answer -- fix the ADAPTER; **2** it could
not evaluate (a bad profile, a missing program, the corpus could not be built, or a reference
control failed) -- nothing was proven either way; **3** too little was examined. Only 0 is a pass,
and a pass with a GAP line is a partial pass.

**(b) A live canary in the real agent.** In a scratch copy, ask your agent to write into a decoy
`reference/` file: the write must be blocked and the model must have seen the reason. Then the
control: the same write into `dev/` must succeed. A block with no working control proves nothing.

**(c) x4doctor shows the layer live.** `python scripts/x4doctor.py` reports per agent target. For
an agent it does not know yet it reports no target for you: say so plainly. That is a gap until a
doctor probe for your agent is upstreamed.

**(d) The fail-mode table** of section 1, every row MEASURED.

Until all four hold, your agent is "partially supported, with these gaps: ..." -- name each gap
to your user.

## 6. Rules

- Never edit the corpus (`scripts/test-hooks.sh`, `scripts/conformance-extra-cases.json`), a
  guard, or another agent's profile or adapter to make yours pass. A disagreement is a bug in
  your adapter, or a finding to report -- never a reason to move the target.
- Adapters translate; they decide nothing. No allow-list, no "this one is probably fine".
- Never emit an answer shape your agent was not MEASURED to honour.
- Never tell your user they are protected without the section 5 proof.
- Report every gap, an `unsupported` kind included. A gap is not a pass.
- Never approve, trust or re-enable hooks on your user's behalf where your agent asks a human to.

## 7. Upstream submission

Open an issue or pull request on the toolkit's repository with this body, filled in:

```
AGENT:
VERSION:
OPERATING SYSTEM:
HOOK EVENTS:
PAYLOAD CAPTURE:
TOOLS THAT WRITE:
SHELL ROUTING:
VERDICT SHAPES HONOURED:
FAIL MODE:
HOOK APPROVAL:
CONTEXT CAP:
NATIVE POLICY LAYER:
INSTRUCTION FILE AND BYTE CAP:
EVIDENCE:
```

Then, below it: the conformance summary (its first line, the bucket counts and every GAP line),
the live canary transcript and its control, the fail-mode table, the exact versions of the agent
and the toolkit, and the list of files the pull request adds.

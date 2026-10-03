# Toy Agent -- hook reference

Toy Agent is a minimal coding agent used to test tool-call hooks. This page is its complete
hook documentation. (It is a test fixture: a stand-in for a real agent you have never seen.)

## Tools

| tool | args | what it does |
|---|---|---|
| `run_shell` | `cmdline` (string), `interpreter` (`"bash"` or `"powershell"`) | runs `cmdline` in that interpreter |
| `edit_file` | `target` (path) | edits an existing file in place |
| `write_file` | `target` (path), `text` (string) | creates or overwrites `target` with `text` |

A relative `target`, and any relative path inside a `cmdline`, is relative to the call's
`workdir` -- never to the directory the agent itself was started in.

The `interpreter` is the shell that will really execute the command. Toy Agent on Windows runs
PowerShell; on Linux and macOS, bash. Both are possible on every OS.

## The `before_tool` hook

Before every tool call, Toy Agent runs ONE hook command (`--hook "<command line>"`) and writes
this JSON object to the hook's **stdin**, then closes stdin:

```json
{"event": "before_tool", "tool": "write_file",
 "args": {"target": "notes/today.txt", "text": "hello"},
 "workdir": "/work/project"}
```

`payloads/` holds one captured example per tool.

The hook process is started in the directory Toy Agent itself was started in, **not** in
`workdir`. Its environment is Toy Agent's environment.

### What the hook can answer (its stdout)

| stdout | effect |
|---|---|
| `TOY-BLOCK <reason>` | the call is **blocked**; `<reason>` is shown to the model, which sees it as the tool result |
| `TOY-NOTE <text>` | the call runs; `<text>` is added to the model's context |
| empty, or anything else | the call runs |

Only the FIRST line of stdout is read. A reason or note must therefore be one line.

There is **no "ask the user" answer**. Toy Agent cannot pause a call for a human decision.

### Failure behaviour

Toy Agent **fails open**: if the hook exits non-zero, crashes, cannot be started, or has not
finished within **30 seconds**, the call **runs** as if the hook had allowed it. Only a
`TOY-BLOCK` line on stdout, from a hook that exits 0 in time, blocks a call.

Hook definitions are never re-approved: changing `--hook` takes effect on the next start.

## Running it

```
python toy_agent.py --root DIR --script CALLS.jsonl --hook "<command line>"
```

`CALLS.jsonl` holds one call per line: `{"tool": ..., "args": {...}, "workdir": ...}`.
`write_file` really writes, but only inside `--root`; `run_shell` and `edit_file` only log what
they would do. Toy Agent prints one line per call to stdout, including the hook's first line.

Toy Agent has no instruction file and no native permission layer.

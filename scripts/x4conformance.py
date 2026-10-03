#!/usr/bin/env python3
"""x4conformance -- replay the toolkit's guard corpus through ANY agent's adapter and compare,
case by case, with what the guards themselves decide. Run it as `x4guard conformance`:

    python .claude/hooks/x4guard.py conformance --profile NAME|PATH [--cases FILE.jsonl]
        [--min-cases N] [--workers N] [--no-extras] [-- ADAPTER ARGV...]

The corpus is every `decide` probe in scripts/test-hooks.sh (dumped live with X4_DECIDE_DUMP,
in a kept sandbox under <toolkit>/.test-sandbox) plus scripts/conformance-extra-cases.json:
neutral cases the dump cannot express (PowerShell, a path with spaces, a Git-Bash drive path),
each carrying an `expect` that is checked against the guards first, as a CONTROL.

The reference verdict is the Claude hook itself, run NOW in the same sandbox and env; a deny or
ask it gives is re-run under X4_GUARD_CHECK=1, and an exit 2 there means "checked nothing" ->
"inert". The adapter verdict is what the profile's output rules decode from the adapter's
stdout. They are compared PER ITEM; a total is never the verdict.

Exit codes:
  0  every replayed case agrees, and replayed >= --min-cases (default 80)
  1  at least one case disagrees, or the adapter's output was unreadable (each one is listed)
  2  cannot evaluate: bad or incomplete profile, no adapter command, toolkit / .claude/hooks /
     a required program missing, the dump harness failed, a reference verdict unreadable, or a
     reference CONTROL (an extra case's `expect`) failed
  3  nothing, or too little, examined: replayed == 0 or replayed < --min-cases.
     Never 0 on an empty population.

Profile format v1 (scripts/conformance-profiles/<name>.json; ADAPTING.md explains each field):
  v: 1;  agent: name;  command: [argv...] with {TOOLKIT} {HOOKS} {PYTHON} {BASH} {PWSH} {HOOK};
  requires: [programs];  run_cwd: "neutral" (an empty scratch dir; default) | "case" (the row's
  cwd);  timeout_s;  env: {VAR: value};
  cases: {KIND: {payload: FILE relative to the profile | "row", set: {json-pointer: template},
          env: {VAR: value}}} for KIND in shell-bash, shell-powershell, edit, write;
  unsupported: {KIND: why} -- a GAP printed on every run; cases + unsupported cover all four kinds;
  output: {format: "json"|"text", exit_codes: {"0": "decode", "2": "inert", ...}, empty: decision,
           rules: [...], strip_prefix, single_line, allowed_keys, inert_pattern}.
Template tokens: {{COMMAND}} {{PATH}} {{CONTENT}} {{CWD}} and {{NAME|lines:P}} (each line of the
value prefixed with P and ended with a newline). One pass over the template: a {{ inside a value
is never expanded. An unknown token is a profile error (exit 2).

Stdlib only; Python >= 3.10.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

KINDS = ("shell-bash", "shell-powershell", "edit", "write")
RC_OK, RC_DISAGREE, RC_ERROR, RC_NOTHING = 0, 1, 2, 3
DECISIONS = ("allow", "advise", "ask", "deny", "inert")
TOKENS = ("COMMAND", "PATH", "CONTENT", "CWD")
NOT_CHECKED = re.compile(r"X4 GUARD INERT|NO rule (?:below )?was evaluated|NEVER checked against any rule"
                         r"|could not be translated|could not be analysed")
_TOKEN = re.compile(r"\{\{([A-Za-z_]+)(?:\|([^{}]*))?\}\}")
_MISSING = object()


class ProfileError(ValueError):
    """The profile cannot be used: missing, malformed, incomplete, or an unknown template token."""


# ------------------------------------------------------------------ profile ---------------- #

def load_profile(spec: str, root: Path) -> dict:
    """NAME -> <root>/scripts/conformance-profiles/NAME.json; anything with a separator or a
    .json suffix is a path. Refuses a profile that leaves any of the four KINDS unaccounted for."""
    looks_like_path = any(c in spec for c in "/\\") or spec.endswith(".json")
    path = Path(spec) if looks_like_path else Path(root) / "scripts" / "conformance-profiles" / f"{spec}.json"
    if not path.is_file():
        raise ProfileError(f"profile not found: {path}")
    try:
        prof = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ProfileError(f"profile {path} is not JSON: {e}") from e
    if not isinstance(prof, dict) or prof.get("v") != 1:
        raise ProfileError(f"profile {path}: \"v\" must be 1")
    cases = prof.get("cases") or {}
    unsupported = prof.setdefault("unsupported", {})
    if not isinstance(cases, dict) or not isinstance(unsupported, dict):
        raise ProfileError(f"profile {path}: cases and unsupported must be objects")
    for k in list(cases) + list(unsupported):
        if k not in KINDS:
            raise ProfileError(f"profile {path}: unknown kind {k!r} (kinds: {', '.join(KINDS)})")
    both = sorted(set(cases) & set(unsupported))
    if both:
        raise ProfileError(f"profile {path}: kind(s) both mapped and unsupported: {', '.join(both)}")
    missing = [k for k in KINDS if k not in cases and k not in unsupported]
    if missing:
        raise ProfileError(f"profile {path}: kind(s) neither in cases nor in unsupported: {', '.join(missing)}"
                           " -- map each one, or declare it unsupported (it is then a GAP on every run)")
    for k, c in cases.items():
        if not isinstance(c, dict) or "payload" not in c:
            raise ProfileError(f"profile {path}: cases.{k} needs a \"payload\"")
    out = prof.get("output")
    if not isinstance(out, dict) or out.get("format") not in ("json", "text") or not isinstance(out.get("rules"), list):
        raise ProfileError(f"profile {path}: output needs format \"json\"|\"text\" and a rules list")
    if not isinstance(out.get("exit_codes", {"0": "decode"}), dict):
        raise ProfileError(f"profile {path}: output.exit_codes must be an object")
    prof["_dir"] = str(path.parent)
    prof["_path"] = str(path)
    return prof


def fill(template, values: dict):
    """Fill {{TOKEN}} / {{TOKEN|lines:P}} in a string (or recursively in a list/dict) in ONE pass."""
    if isinstance(template, dict):
        return {k: fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [fill(v, values) for v in template]
    if not isinstance(template, str):
        return template

    def sub(m):
        name, flt = m.group(1), m.group(2)
        if name not in TOKENS:
            raise ProfileError(f"unknown template token {{{{{name}}}}} (known: {', '.join(TOKENS)})")
        if name not in values or values[name] is None:
            raise ProfileError(f"template token {{{{{name}}}}} has no value for this case")
        v = str(values[name])
        if flt is None:
            return v
        if flt.startswith("lines:"):
            prefix = flt[len("lines:"):]
            return "".join(prefix + ln + "\n" for ln in (v.split("\n") if v else [""]))
        raise ProfileError(f"unknown template filter |{flt} on {{{{{name}}}}}")

    return _TOKEN.sub(sub, template)


def _pointer_parts(ptr: str) -> list:
    if ptr == "":
        return []
    if not ptr.startswith("/"):
        raise ProfileError(f"not a JSON pointer: {ptr!r}")
    return [p.replace("~1", "/").replace("~0", "~") for p in ptr[1:].split("/")]


def get_pointer(doc, ptr: str):
    cur = doc
    for part in _pointer_parts(ptr):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def set_pointer(doc: dict, ptr: str, value) -> None:
    parts = _pointer_parts(ptr)
    if not parts:
        raise ProfileError("cannot set the whole payload through a pointer")
    cur = doc
    for part in parts[:-1]:
        nxt = cur.get(part) if isinstance(cur, dict) else None
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


# ------------------------------------------------------------------ decode ----------------- #

def _finish(decision: str, text, output: dict):
    if decision in ("deny", "ask") and text and re.search(output.get("inert_pattern", "X4 GUARD INERT"), text):
        return "inert", text
    return decision, text


def decode(output: dict, stdout: bytes, rc: int) -> tuple:
    """(decision, text) from what an adapter printed. A decision is one of allow|advise|ask|deny|inert,
    or "unreadable": an exit status the profile does not list, output no rule matches, a key the
    agent does not know (`allowed_keys`). "unreadable" is a disagreement, never an allow."""
    action = (output.get("exit_codes") or {"0": "decode"}).get(str(rc))
    if action is None:
        return "unreadable", f"exit status {rc} is not in the profile's exit_codes"
    body = stdout.decode("utf-8", "replace") if isinstance(stdout, (bytes, bytearray)) else str(stdout)
    body = body.strip()
    if action != "decode":
        if action not in DECISIONS:
            return "unreadable", f"exit_codes maps {rc} to unknown decision {action!r}"
        return action, body or None
    sp = output.get("strip_prefix")
    if sp:
        if not body.startswith(sp):
            return "unreadable", f"output does not start with {sp!r}: {body[:200]!r}"
        body = body[len(sp):].strip()
    if not body:
        empty = output.get("empty")
        return (empty, None) if empty in DECISIONS else ("unreadable", "empty output and no \"empty\" decision declared")
    if output.get("single_line") and "\n" in body:
        return "unreadable", f"more than one line: {body[:200]!r}"
    if output.get("format") == "text":
        for rule in output.get("rules", []):
            m = re.search(rule["regex"], body, re.M)
            if m:
                text = m.groupdict().get("text")
                return _finish(rule["decision"], text, output)
        return "unreadable", f"no output rule matched: {body[:200]!r}"
    try:
        doc = json.loads(body)
    except ValueError:
        return "unreadable", f"not JSON: {body[:200]!r}"
    for ptr, allowed in (output.get("allowed_keys") or {}).items():
        node = get_pointer(doc, ptr)
        if node is _MISSING:
            continue
        if not isinstance(node, dict):
            return "unreadable", f"{ptr or '/'} is not an object"
        extra = sorted(set(node) - set(allowed))
        if extra:
            return "unreadable", f"key(s) the agent does not know at {ptr or '/'}: {extra}"
    for rule in output.get("rules", []):
        when, ok = rule.get("when") or {}, True
        for ptr, want in when.items():
            got = get_pointer(doc, ptr)
            if isinstance(want, dict) and want.get("present"):
                ok = got is not _MISSING
            else:
                ok = got is not _MISSING and got == want
            if not ok:
                break
        if ok and any(get_pointer(doc, p) is not _MISSING for p in rule.get("absent", [])):
            ok = False
        if not ok:
            continue
        text = get_pointer(doc, rule["text"]) if rule.get("text") else None
        text = None if text is _MISSING else text
        decision = rule["decision"]
        for prefix, d in (rule.get("prefix_decisions") or {}).items():
            if isinstance(text, str) and text.startswith(prefix):
                decision = d
                break
        return _finish(decision, text if isinstance(text, str) or text is None else json.dumps(text), output)
    return "unreadable", f"no output rule matched: {body[:200]!r}"


# ------------------------------------------------------------------ classify / summarise --- #

def classify(row: dict) -> str:
    """The native kind a Claude-shaped dump row maps to, or "no_native_analogue"."""
    p = row.get("payload") or {}
    tool = p.get("tool_name")
    ti = p.get("tool_input") if isinstance(p.get("tool_input"), dict) else None
    if ti is None:
        return "no_native_analogue"
    if tool in ("Bash", "PowerShell") and isinstance(ti.get("command"), str) and ti["command"]:
        return "shell-powershell" if tool == "PowerShell" else "shell-bash"
    if tool in ("Edit", "Write") and isinstance(ti.get("file_path"), str) and ti["file_path"]:
        return tool.lower()
    return "no_native_analogue"


def summarise(results, n_total, buckets, gaps, min_cases) -> tuple:
    """(exit code, report). Buckets must account for every case; disagreements are listed PER ITEM."""
    assert sum(buckets.values()) == n_total, f"buckets {buckets} do not sum to the {n_total} cases"
    assert buckets.get("replayed", 0) == len(results), f"replayed bucket {buckets.get('replayed', 0)} != {len(results)} results"
    lines = [f"conformance: {len(results)} replayed of {n_total} cases; buckets: "
             + ", ".join(f"{k}={v}" for k, v in sorted(buckets.items()))]
    for kind, why in sorted(gaps.items()):
        lines.append(f"GAP: {kind} is not covered by this adapter ({why}); its cases were not replayed")
    bad = [r for r in results if r["reference"] != r["adapter"]]
    if bad:
        for r in bad:
            extra = f" -- {r['text']}" if r.get("text") else ""
            lines.append(f"DISAGREE {r['label']} [{r['kind']}]: guards say {r['reference']}, "
                         f"adapter says {r['adapter']}{extra}"[:600])
        lines.append(f"FAIL: {len(bad)} of {len(results)} replayed cases disagree")
        return RC_DISAGREE, "\n".join(lines)
    if not results:
        lines.append("REFUSING: 0 replayed -- nothing was examined, so nothing is proven")
        return RC_NOTHING, "\n".join(lines)
    if len(results) < min_cases:
        lines.append(f"REFUSING: {len(results)} replayed is below --min-cases {min_cases}: too little examined")
        return RC_NOTHING, "\n".join(lines)
    lines.append(f"OK: all {len(results)} replayed cases agree")
    return RC_OK, "\n".join(lines)

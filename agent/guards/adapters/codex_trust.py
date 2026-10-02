#!/usr/bin/env python3
"""codex_trust -- is Codex actually RUNNING the toolkit's hooks? (spec section 5.8, M11)

    python codex_trust.py report --hooks-json P [--codex-config P] [--project-root P]

Prints one JSON report and exits 0 when every hook is trusted, 1 when any is not, 2 when it
cannot tell (no config, an unreadable one, unreadable hooks.json). Never a verdict it did not
measure: an unreadable file is "unknown", never "trusted".

Why this exists: Codex runs a project hook only when `[hooks.state.'<key>']` in its
config.toml holds a `trusted_hash` equal to the definition's CURRENT hash and `enabled` is not
false. An unreviewed, changed (Codex calls it Modified) or disabled hook is skipped SILENTLY --
the session looks guarded and is not. Codex cannot report this from inside the session, so
something outside has to (x4doctor calls this module).

The hash (READ: codex-rs hooks/src/engine/discovery.rs::hook_hash, config fingerprint.rs):
    "sha256:" + sha256(canonical JSON of {"event_name": <snake_case event>, "matcher"?: m,
                       "hooks": [<normalised handler>]})
keys sorted recursively, compact separators, None omitted. The handler is
{"type":"command","command":<on Windows commandWindows wins>,"timeout":<given, else 600; 1..3
for session_end/interrupt>,"async":bool,"statusMessage"?,"additionalContextLimit"? (omitted
when unset or 2500)}. MEASURED: 6 of 6 hashes Codex 0.160.0 itself reported (app-server
hooks/list currentHash) for neutral definitions -- tests/fixtures/codex/0.160.0/trust_vectors.json.

A future Codex may change the scheme. When entries exist but NONE matches, every mismatch is
reported "unknown" (scheme unconfirmed), never "modified". Stdlib only; Python >= 3.10 (on 3.10
a deliberately narrow config reader: only the two table shapes and three keys it needs, and any
other line inside one of those tables makes the answer unknown).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

STATUSES = ("trusted", "untrusted", "modified", "disabled", "unknown")
DEFAULT_TIMEOUT_S = 600
DEFAULT_CONTEXT_LIMIT = 2500
_SHORT_EVENTS = {"session_end": (1, 3), "interrupt": (1, 3)}   # (default, max) seconds


class Unreadable(ValueError):
    pass


def snake(event: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()


def _on_windows() -> bool:
    return sys.platform == "win32"


def normalised_handler(event_key: str, handler: dict, windows: bool | None = None) -> dict:
    if windows is None:
        windows = _on_windows()
    cmd = handler.get("command")
    if windows and handler.get("commandWindows") is not None:
        cmd = handler["commandWindows"]
    t = handler.get("timeout")
    if event_key in _SHORT_EVENTS:
        dflt, mx = _SHORT_EVENTS[event_key]
        t = min(max(dflt if t is None else int(t), 1), mx)
    else:
        t = max(DEFAULT_TIMEOUT_S if t is None else int(t), 1)
    h = {"type": handler.get("type", "command"), "command": cmd, "timeout": t,
         "async": bool(handler.get("async", False))}
    if handler.get("statusMessage") is not None:
        h["statusMessage"] = handler["statusMessage"]
    acl = handler.get("additionalContextLimit")
    if acl is not None and acl != DEFAULT_CONTEXT_LIMIT:
        h["additionalContextLimit"] = acl
    return h


def hook_hash(event_key: str, group: dict, handler: dict, windows: bool | None = None) -> str:
    ident = {"event_name": event_key, "hooks": [normalised_handler(event_key, handler, windows)]}
    if group.get("matcher") is not None:
        ident["matcher"] = group["matcher"]
    s = json.dumps(ident, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


def expected_entries(hooks_json: Path, windows: bool | None = None) -> dict[str, str]:
    """{state key: expected hash}, keyed as Codex keys them:
    `<absolute hooks.json path>:<snake_case event>:<group index>:<handler index>`."""
    try:
        data = json.loads(Path(hooks_json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Unreadable(f"hooks.json unreadable: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise Unreadable("hooks.json has no 'hooks' object")
    base = str(Path(hooks_json).resolve())
    out: dict[str, str] = {}
    for event, groups in (data.get("hooks") or {}).items():
        ek = snake(event)
        for i, g in enumerate(groups or []):
            for j, h in enumerate((g or {}).get("hooks") or []):
                out[f"{base}:{ek}:{i}:{j}"] = hook_hash(ek, g, h, windows)
    return out


# ---------------------------------------------------------------- config.toml ----------- #

def _tables_from_doc(doc: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for k, v in (doc.get("projects") or {}).items():
        if isinstance(v, dict):
            out["projects:" + k] = {kk: v[kk] for kk in ("trust_level",) if kk in v}
    for k, v in ((doc.get("hooks") or {}).get("state") or {}).items():
        if isinstance(v, dict):
            out["hooks.state:" + k] = {kk: v[kk] for kk in ("trusted_hash", "enabled") if kk in v}
    return out


_HEAD = re.compile(r"""^\[(projects|hooks\.state)\.(?:'([^']*)'|"((?:[^"\\]|\\.)*)")\]\s*(?:#.*)?$""")
_KV = re.compile(r"""^(trust_level|trusted_hash|enabled)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|(true|false))\s*(?:#.*)?$""")


def _unescape(s: str) -> str:
    return json.loads('"' + s + '"')


def _read_tables_310(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    cur = None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            m = _HEAD.match(line)
            if m:
                key = m.group(2) if m.group(2) is not None else _unescape(m.group(3))
                cur = out.setdefault(f"{m.group(1)}:{key}", {})
            else:
                cur = None
            continue
        if cur is None:
            continue
        m = _KV.match(line)
        if not m:
            raise Unreadable(f"config.toml line {n} is not understood")
        if m.group(2) is not None:
            val = _unescape(m.group(2))
        elif m.group(3) is not None:
            val = m.group(3)
        else:
            val = m.group(4) == "true"
        cur[m.group(1)] = val
    return out


def read_tables(config: Path) -> dict[str, dict]:
    try:
        text = Path(config).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Unreadable(f"codex config unreadable: {e}") from e
    try:
        import tomllib  # Python >= 3.11
    except ModuleNotFoundError:
        return _read_tables_310(text)
    try:
        return _tables_from_doc(tomllib.loads(text))
    except tomllib.TOMLDecodeError as e:
        raise Unreadable(f"codex config is not valid TOML: {e}") from e


def _project_trust(tables: dict, root: Path) -> str:
    rkey = os.path.normcase(str(Path(root).resolve())).rstrip("\\/")
    best = "untrusted"
    for k, v in tables.items():
        if not k.startswith("projects:") or v.get("trust_level") != "trusted":
            continue
        p = os.path.normcase(k[len("projects:"):]).rstrip("\\/")
        if p.lower() == rkey.lower():
            return "trusted"
        if rkey.lower().startswith(p.lower() + "\\") or rkey.lower().startswith(p.lower() + "/"):
            best = "ancestor"
    return best


def codex_home() -> Path:
    return Path(os.environ["CODEX_HOME"]) if os.environ.get("CODEX_HOME") else Path.home() / ".codex"


def trust_report(hooks_json: Path, codex_config: Path, project_root: Path, windows: bool | None = None) -> dict:
    report = {"hooks_json": str(hooks_json), "codex_config": str(codex_config), "hooks": [],
              "project_trust": None, "project_trusted": None, "overall": "unknown", "error": None}
    try:
        expected = expected_entries(hooks_json, windows)
        tables = read_tables(codex_config)
    except Unreadable as e:
        report["error"] = str(e)
        return report
    pt = _project_trust(tables, project_root)
    report["project_trust"], report["project_trusted"] = pt, pt in ("trusted", "ancestor")
    state = {k[len("hooks.state:"):]: v for k, v in tables.items() if k.startswith("hooks.state:")}
    folded = {k.lower(): v for k, v in state.items()}
    rows = []
    for key, want in sorted(expected.items()):
        ent, how = state.get(key), "exact"
        if ent is None:
            ent, how = folded.get(key.lower()), "casefold"
        if ent is None:
            rows.append({"key": key, "status": "untrusted", "matched": None, "expected_hash": want})
            continue
        if ent.get("enabled") is False:
            st = "disabled"
        elif ent.get("trusted_hash") == want:
            st = "trusted"
        else:
            st = "modified"
        rows.append({"key": key, "status": st, "matched": how, "expected_hash": want})
    present = [r for r in rows if r["matched"]]
    hashed = [r for r in present if state.get(r["key"], folded.get(r["key"].lower(), {})).get("trusted_hash")]
    if hashed and not any(r["status"] == "trusted" for r in hashed):
        for r in rows:                       # no stored hash matched ANY of ours: scheme unconfirmed
            if r["status"] == "modified":
                r["status"] = "unknown"
    report["hooks"] = rows
    sts = {r["status"] for r in rows}
    if not rows:
        report["overall"] = "unknown"
        report["error"] = "hooks.json defines no hook"
    elif sts == {"trusted"}:
        report["overall"] = "trusted"
    elif "unknown" in sts:
        report["overall"] = "unknown"
    elif "disabled" in sts:
        report["overall"] = "disabled"
    elif "modified" in sts:
        report["overall"] = "modified"
    else:
        report["overall"] = "untrusted"
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="codex_trust", description="Report whether Codex will run these hooks.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("--hooks-json", required=True, type=Path)
    r.add_argument("--codex-config", type=Path, default=None)
    r.add_argument("--project-root", type=Path, default=None)
    a = ap.parse_args(argv)
    cfg = a.codex_config or codex_home() / "config.toml"
    root = a.project_root or Path(a.hooks_json).resolve().parent.parent
    rep = trust_report(a.hooks_json, cfg, root)
    sys.stdout.write(json.dumps(rep, indent=2) + "\n")
    if rep["overall"] == "trusted":
        return 0
    return 2 if rep["overall"] == "unknown" else 1


if __name__ == "__main__":
    sys.exit(main())

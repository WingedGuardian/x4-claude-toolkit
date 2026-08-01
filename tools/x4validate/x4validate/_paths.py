r"""One place that answers "where is the game / profile / reference / registry?".

**The defect this exists to fix (shipped in v2.0).** `install.sh` / `install.ps1`
write `.claude/x4-paths.env` using the names `X4_GAME`, `X4_EXTENSIONS`,
`X4_PROFILE`, `X4_MODS`, `X4_REFERENCE`, `X4_TOOLKIT`. The Python package read a
*different* set — `X4_GAME_EXTENSIONS`, `X4_PROFILE_CONTENT`,
`X4_PROFILE_EXTENSIONS`, `X4_WORKSHOP_CONTENT`, `X4_REGISTRY` — and **the overlap
was exactly one name, `X4_REFERENCE`.** Nothing bridged them: `x4-paths.env` is read
by `.claude/hooks/_x4-env.sh` and `bin/`, never by Python. So a user on the
`separate` or `global` install layout ran the installer, saw it succeed, and then had
`--tier b`, `x4compat`, `x4stats`, `x4similar`, `x4xref`, `x4modlist` and
`x4effective` silently fall back to CWD-relative paths. It was invisible on the
development machine only because the hardcoded defaults there happened to be right.

**Resolution order** for every location, first hit wins:

  1. the INSTALLER's env var name (what `x4-paths.env` and the docs use)
  2. the LEGACY env var name (what the Python used to read) — nothing that works
     today may break
  3. `.claude/x4-paths.env`, located via `$X4_TOOLKIT` or by walking up from CWD —
     the common case, since a plain shell exports none of the above
  4. a derivation from an already-resolved location (`$X4_GAME/extensions`,
     `$X4_PROFILE/content.xml`, ...)
  5. `_LOCAL_FALLBACK` — development-machine defaults, empty in the public tree

The file is PARSED, never sourced: running a shell to read config is an arbitrary
code path we do not need, and it would not work on Windows without a shell anyway.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

#: Steam Workshop id for X4: Foundations, used to derive the workshop content dir.
STEAM_APPID = "392160"

#: Last-resort overrides, and **deliberately empty**.
#:
#: This is the documented seam for a local default, so that a contributor who needs
#: one has an obvious single place to put it instead of scattering
#: `os.environ.get(..., r"C:\Users\...")` through the package — which is exactly how
#: six personal paths ended up hardcoded in the shipped v2.0.
#:
#: It stays empty even on the development machine. A dev-only fallback is dead code
#: until the day it silently rescues a broken config and hides it, and the loud
#: failures are better: an unresolved reference tree is a hard error ("validation is
#: meaningless without it"), and an unresolved extensions dir makes Tier B a degraded
#: skip that explicitly reports "this result is NOT a pass". A fallback here would
#: paper over precisely the misconfiguration the tool is built to shout about.
_LOCAL_FALLBACK: dict[str, str] = {}

_LINE = re.compile(r"""^\s*(?:export\s+)?(?P<key>X4_[A-Z0-9_]+|XRCATTOOL)\s*=\s*(?P<val>.*?)\s*$""")
_REF = re.compile(r"\$\{(?P<b>[A-Z0-9_]+)\}|\$(?P<p>[A-Z0-9_]+)")


def _unquote(v: str) -> str:
    v = v.split(" #", 1)[0].strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_env_file(path: Path) -> dict[str, str]:
    """`KEY="value"` pairs from an x4-paths.env, with `$OTHER` references expanded.

    Expansion is against keys already seen in the file, then the real environment —
    matching what a shell would do when sourcing it top-to-bottom. Unknown
    references expand to empty, exactly as a shell would, rather than being left
    as a literal `$X4_TOOLKIT` that would later become a bogus directory name.
    """
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        # silent-ok: an unreadable config file is simply "no config" — the caller
        # falls through to the next resolution layer, and `describe()` reports
        # which file (if any) was actually used.
        return out
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = _LINE.match(raw)
        if not m:
            continue
        val = _unquote(m.group("val"))
        val = _REF.sub(lambda r: out.get(r.group("b") or r.group("p"),
                                        os.environ.get(r.group("b") or r.group("p"), "")), val)
        if val:
            out[m.group("key")] = val
    return out


def _find_env_file() -> Path | None:
    """`.claude/x4-paths.env` from `$X4_TOOLKIT`, else by walking up from CWD."""
    toolkit = os.environ.get("X4_TOOLKIT")
    if toolkit:
        p = Path(toolkit) / ".claude" / "x4-paths.env"
        if p.is_file():
            return p
    here = Path.cwd().resolve()
    for d in [here, *here.parents]:
        p = d / ".claude" / "x4-paths.env"
        if p.is_file():
            return p
    return None


@lru_cache(maxsize=1)
def _file_layer() -> tuple[dict[str, str], Path | None]:
    """The parsed `x4-paths.env`. Cached because it costs a directory walk + read.

    Only the FILE is cached. The environment layer is rebuilt on every lookup, so
    a test (or a long-lived process) that mutates `os.environ` is picked up without
    having to remember `reload()` — a cache that silently ignores a freshly-set env
    var is precisely the kind of quiet misconfiguration this module exists to end.
    """
    env_file = _find_env_file()
    return (parse_env_file(env_file) if env_file else {}), env_file


def reload() -> None:
    """Forget the located/parsed config file. Needed only if that FILE changes."""
    _file_layer.cache_clear()


def _layers() -> list[dict[str, str]]:
    """Sources in descending priority: real env, config file, dev-machine fallback.

    Resolution walks these **layer by layer**, and within a layer tries every alias
    and derivation before dropping to the next. Flattening them into one dict is
    wrong: a `_LOCAL_FALLBACK` value for `X4_GAME` would then outrank a real
    `$X4_GAME_EXTENSIONS` the user actually exported.
    """
    env = {k: v for k, v in os.environ.items()
           if (k.startswith("X4_") or k == "XRCATTOOL") and v}
    file_layer, _ = _file_layer()
    return [env, file_layer, _LOCAL_FALLBACK]


#: WSL first — `/mnt/c/x` also matches the MSYS shape as drive "m" + "nt/c/x".
_RE_WSL = re.compile(r"^/mnt/([a-zA-Z])/(.*)$")
_RE_MSYS = re.compile(r"^/([a-zA-Z])/(.*)$")


def native(value: str) -> str:
    r"""Translate a POSIX drive path into one Python can actually open on Windows.

    `install.sh` detects Steam at `/c/Program Files (x86)/Steam` under Git Bash
    (install.sh's `steam_roots`), and `.claude/x4-paths.env.example` explicitly
    promises that either `C:\...` or `/c/...` is acceptable. The shell half honours
    that; Python does not — `Path("/c/Program Files")` becomes `\c\Program Files`,
    which does not exist. So the FIRST command the README gives a Windows user
    produced a config file the Python silently could not use: a successful install
    pointing at nothing, which is precisely the failure v2.01 exists to end.

    Only applied on Windows. On Linux `/c/...` and `/mnt/c/...` are legitimate
    absolute paths and must be left exactly as written.
    """
    if os.name != "nt":
        return value
    for rx in (_RE_WSL, _RE_MSYS):
        if m := rx.match(value):
            return f"{m.group(1).upper()}:/{m.group(2)}"
    return value


def _pick(layer: dict[str, str], *names: str) -> str | None:
    """First of *names* this layer defines, translated to a usable native path.

    The single choke point every alias and every derivation goes through, so the
    translation cannot be forgotten for one location — which is the shape of bug
    this module exists to prevent.
    """
    for n in names:
        if layer.get(n):
            return native(layer[n])
    return None


def _resolve(fn) -> Path | None:
    """First layer that can answer *fn* wins."""
    for layer in _layers():
        got = fn(layer)
        if got is not None:
            return got
    return None


def game_root() -> Path | None:
    """The folder holding 01.cat..09.cat and extensions/."""
    def _in(layer):
        if v := _pick(layer, "X4_GAME", "X4_GAME_ROOT"):
            return Path(v)
        if ext := _pick(layer, "X4_EXTENSIONS", "X4_GAME_EXTENSIONS"):
            return Path(ext).parent
        return None
    return _resolve(_in)


def game_extensions() -> Path | None:
    def _in(layer):
        if v := _pick(layer, "X4_EXTENSIONS", "X4_GAME_EXTENSIONS"):
            return Path(v)
        if g := _pick(layer, "X4_GAME", "X4_GAME_ROOT"):
            return Path(g) / "extensions"
        return None
    return _resolve(_in)


def reference() -> Path | None:
    def _in(layer):
        if v := _pick(layer, "X4_REFERENCE"):
            return Path(v)
        if t := _pick(layer, "X4_TOOLKIT"):
            return Path(t) / "reference"
        return None
    return _resolve(_in)


def profile() -> Path | None:
    return _resolve(lambda layer: Path(v) if (v := _pick(layer, "X4_PROFILE")) else None)


def profile_content() -> Path | None:
    def _in(layer):
        if v := _pick(layer, "X4_PROFILE_CONTENT"):
            return Path(v)
        if p := _pick(layer, "X4_PROFILE"):
            return Path(p) / "content.xml"
        return None
    return _resolve(_in)


def profile_extensions() -> Path | None:
    def _in(layer):
        if v := _pick(layer, "X4_PROFILE_EXTENSIONS"):
            return Path(v)
        if p := _pick(layer, "X4_PROFILE"):
            return Path(p) / "extensions"
        return None
    return _resolve(_in)


def workshop_content() -> Path | None:
    """`steamapps/workshop/content/392160`, derived from the game dir when unset.

    A default Steam layout puts the game at `steamapps/common/<name>`, so the
    workshop tree is two levels up. Only offered when that shape actually holds —
    guessing on a non-Steam or relocated install would invent a path that silently
    scans nothing and reports "no mods here".
    """
    def _in(layer):
        if v := _pick(layer, "X4_WORKSHOP_CONTENT"):
            return Path(v)
        g = _pick(layer, "X4_GAME", "X4_GAME_ROOT")
        gp = Path(g) if g else None
        if gp is None and (ext := _pick(layer, "X4_EXTENSIONS", "X4_GAME_EXTENSIONS")):
            gp = Path(ext).parent
        if gp is not None and gp.parent.name.lower() == "common":
            return gp.parent.parent / "workshop" / "content" / STEAM_APPID
        return None
    return _resolve(_in)


def mods() -> Path | None:
    """Where the user's mod source folders live (one per mod) — `$X4_MODS`.

    `registry()` already derived from this, but had no direct accessor, so the
    `gates/` harnesses hardcoded a developer's own `dev\\` path instead. That is
    how a personal path survives into a public repo.
    """
    return _resolve(lambda layer: Path(v) if (v := _pick(layer, "X4_MODS")) else None)


def registry() -> Path | None:
    def _in(layer):
        if v := _pick(layer, "X4_REGISTRY"):
            return Path(v)
        if m := _pick(layer, "X4_MODS"):
            return Path(m) / "_registry" / "modlist.yaml"
        return None
    return _resolve(_in)


def debug_log() -> Path | None:
    def _in(layer):
        if v := _pick(layer, "X4_DEBUGLOG"):
            return Path(v)
        if p := _pick(layer, "X4_PROFILE"):
            return Path(p) / "debug.txt"
        return None
    return _resolve(_in)


def describe() -> list[str]:
    """Human-readable resolution report, for `--paths` and for bug reports.

    Silent misconfiguration is the whole failure mode here, so there has to be a
    way to ask the tool where it thinks everything is.
    """
    _, env_file = _file_layer()
    lines = [f"config file: {env_file or '(none found — set $X4_TOOLKIT or run install)'}"]
    for name, fn in (("game", game_root), ("extensions", game_extensions),
                     ("reference", reference), ("profile", profile),
                     ("profile content.xml", profile_content),
                     ("profile extensions", profile_extensions),
                     ("workshop", workshop_content), ("mods", mods),
                     ("registry", registry), ("debug log", debug_log)):
        p = fn()
        mark = "" if p is None else ("" if p.exists() else "   (does not exist)")
        lines.append(f"  {name:<20} {p or '(unresolved)'}{mark}")
    return lines

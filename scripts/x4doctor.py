#!/usr/bin/env python3
"""x4doctor -- are this root's guards LIVE, per agent target? Read-only.

WHY THIS EXISTS. Every way the guards have failed here looked, from outside, exactly like a
guarded install: a hook that read zero bytes of stdin and exited 0; `bash` resolving to the
WSL stub, which cannot run a Windows-path script; a Store `python` stub that resolves and
then cannot run; Codex skipping a hook it has not reviewed, SILENTLY (MEASURED 2026-09-30).
None of those says anything. This command asks, per installed agent target:

  * toolchain  -- the bash, python and jq the GUARDS resolve, asked of the guards' own
                  resolver (never re-implemented: a parallel resolver answers an adjacent
                  question), and EXECUTED, because resolving is not running;
  * roots      -- the reference/game roots the guards see vs the ones the tools see;
  * parity     -- the deployed tree against the toolkit source (gates/deploy_parity.py);
  * self-test  -- `x4guard.py check` controls that MUST deny and controls that MUST allow,
                  so a guard that denies everything cannot read as healthy;
  * liveness   -- Claude's hook wiring; Codex's project trust and per-hook review state;
                  X4_GUARD; the OS-level reference protection; the x4lock state.

THE CONTRACT -- ABSENCE vs NON-ANSWER, structurally:
  every row is OK, FAIL, UNKNOWN or N/A. N/A means only "this target is not installed
  here" (or "this check cannot apply on this OS"). A check that RAISES becomes UNKNOWN
  with the exception named, never a dropped row.

    exit 0  every applicable check is OK, and at least one answered
    exit 1  any FAIL
    exit 3  no FAIL, but at least one UNKNOWN   (x4validate's degraded exit)
    exit 2  could not run: no agent target at --root, nothing answered, or a usage error

The verdict line is printed FIRST (CLAUDE.md #38: a truncated report keeps its head).

It executes nothing it judges: the guard self-test goes through `x4guard.py check`, which
is side-effect-free, against a probe path that does not exist. It writes no file and never
touches Codex's config. Stdlib only, Python >= 3.10, so a broken uv or venv cannot take
down the tool that diagnoses it.

USAGE
    python scripts/x4doctor.py [--root DIR] [--agent claude|codex|generic] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

OK, FAIL, UNKNOWN, NA = "OK", "FAIL", "UNKNOWN", "N/A"
STATUSES = (OK, FAIL, UNKNOWN, NA)
TARGETS = ("claude", "codex", "generic")
HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Check:
    id: str
    target: str
    status: str
    detail: str


@dataclass
class Ctx:
    root: Path
    toolkit: Path | None = None
    env: dict = field(default_factory=lambda: dict(os.environ))
    targets: dict = field(default_factory=dict)

    def __post_init__(self):
        self.root = Path(self.root)
        if self.toolkit is None and self.env.get("X4_TOOLKIT"):
            self.toolkit = Path(self.env["X4_TOOLKIT"])
        if not self.targets:
            self.targets = detect_targets(self.root)


def exit_code(rows) -> int:
    """0 all OK, 1 any FAIL, 3 UNKNOWN without FAIL, 2 nothing answered."""
    rows = list(rows)
    answered = [r for r in rows if r.status in (OK, FAIL)]
    if not answered:
        return 2
    if any(r.status == FAIL for r in rows):
        return 1
    return 3 if any(r.status == UNKNOWN for r in rows) else 0


def run_check(cid: str, target: str, fn, ctx) -> Check:
    """One check, one row. Whatever happens inside fn, a row comes out -- and a row whose
    status is not one of the four is UNKNOWN, never trusted."""
    try:
        status, detail = fn(ctx)
    except Exception as exc:  # noqa: BLE001 -- the whole point: no check may vanish
        tb = traceback.extract_tb(exc.__traceback__)
        where = ("%s:%d" % (Path(tb[-1].filename).name, tb[-1].lineno)) if tb else "?"
        return Check(cid, target, UNKNOWN, "the check itself failed: %s: %s (at %s)"
                     % (type(exc).__name__, exc, where))
    if status not in STATUSES:
        return Check(cid, target, UNKNOWN, "the check returned an unknown status %r: %s"
                     % (status, detail))
    return Check(cid, target, status, str(detail))


def detect_targets(root: Path) -> dict[str, bool]:
    """Which agent targets are installed at `root`. Keyed on each target's own PAYLOAD,
    never a bare folder or a shared file: every install writes `.claude/x4-paths.env` (a
    Codex-only one included), Codex reads a project `.codex/config.toml` of its own, and a
    hand-written AGENTS.md is not the toolkit's generic target (MEASURED on the author's
    game root). The instruction files are reported by the instructions rows instead."""
    root = Path(root)
    return {
        "claude": (root / ".claude" / "settings.json").is_file(),
        "codex": (root / ".codex" / "hooks").is_dir() or (root / ".codex" / "hooks.json").is_file(),
        "generic": (root / ".agents" / "skills").is_dir(),
    }


def default_root(start: Path) -> Path:
    """The nearest ancestor of `start` that holds an agent target, else `start`."""
    start = Path(start).resolve()
    for d in (start, *start.parents):
        if any(detect_targets(d).values()):
            return d
    return start


#: Check groups, in report order. Each takes a Ctx and returns rows.
GROUPS: list = []


def group(fn):
    GROUPS.append(fn)
    return fn


def collect(ctx: Ctx, only: str | None = None) -> list[Check]:
    rows: list[Check] = []
    for g in GROUPS:
        try:
            got = list(g(ctx))
        except Exception as exc:  # noqa: BLE001
            got = [Check(g.__name__, "all", UNKNOWN, "the check group itself failed: %s: %s"
                         % (type(exc).__name__, exc))]
        rows.extend(got)
    if only:
        rows = [r for r in rows if r.target in (only, "all")]
    return rows


# ----------------------------------------------------------------- shared helpers

def _on_windows() -> bool:
    return os.name == "nt"


def _norm_path(p) -> str:
    """One spelling per directory, for COMPARING what two resolvers said: MSYS `/c/x` and
    `C:\\x` and `C:/x/` are one folder. Never used to open anything."""
    if p is None:
        return ""
    s = str(p).strip().replace("\\", "/")
    if _on_windows():
        if len(s) >= 3 and s[0] == "/" and s[2] == "/" and s[1].isalpha():
            s = s[1].upper() + ":" + s[2:]
        s = s.lower()
    return s.rstrip("/") if len(s) > 1 else s


def _is_stub(path: str | None) -> bool:
    """The Windows bash stubs: WSL's System32/SysWOW64 launcher and the Store alias. They
    RESOLVE, and cannot run a Windows-path script -- a guard started through one fails
    open (MEASURED 2026-09-04, x4lock's docstring)."""
    if not path:
        return False
    s = path.replace("/", "\\").lower()
    return any(k in s for k in ("\\system32\\", "\\syswow64\\", "\\windowsapps\\"))


def same_bash(a: str | None, b: str | None) -> bool:
    """One bash, possibly spelled two ways: Git for Windows ships `<Git>/bin/bash.exe` as a
    launcher for `<Git>/usr/bin/bash.exe`. Anything else is compared as a path."""
    if not a or not b:
        return False
    na, nb = _norm_path(a), _norm_path(b)
    if na == nb:
        return True

    def git_root(p: str) -> str | None:
        for tail in ("/usr/bin/bash.exe", "/bin/bash.exe", "/usr/bin/bash", "/bin/bash"):
            if p.endswith(tail):
                return p[: -len(tail)]
        return None
    ra, rb = git_root(na), git_root(nb)
    return _on_windows() and ra is not None and ra == rb


def _load(name: str, path: Path):
    """Import one file as a module under a doctor-private name. Registered in sys.modules
    while it executes, because @dataclass looks its own module up there."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def _run(cmd, *, env=None, cwd=None, timeout=60, stdin=None):
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd,
                          timeout=timeout, input=stdin, encoding="utf-8", errors="replace")


def guard_dirs(ctx: Ctx) -> list[tuple[str, Path]]:
    """The installed guard copies, (target, hooks dir), Claude first."""
    out = []
    if ctx.targets.get("claude") and (ctx.root / ".claude" / "hooks" / "_x4-env.sh").is_file():
        out.append(("claude", ctx.root / ".claude" / "hooks"))
    if ctx.targets.get("codex") and (ctx.root / ".codex" / "hooks" / "_x4-env.sh").is_file():
        out.append(("codex", ctx.root / ".codex" / "hooks"))
    return out


def _hook_env(ctx: Ctx, target: str, hooks: Path) -> dict:
    """The environment a hook of `target` would see. Claude Code sets CLAUDE_PROJECT_DIR to
    the project it runs in; Codex sets nothing of the kind."""
    env = dict(ctx.env)
    env["HOOK_DIR"] = hooks.as_posix()
    if target == "claude":
        env["CLAUDE_PROJECT_DIR"] = str(ctx.root)
    return env


def guard_bash(ctx: Ctx) -> tuple[str | None, str]:
    """The bash the deployed x4guard.py would use -- asked of x4guard itself."""
    dirs = guard_dirs(ctx)
    if not dirs:
        return None, "no guard copy installed here"
    xg = dirs[0][1] / "x4guard.py"
    if not xg.is_file():
        return None, "%s is missing" % xg
    saved = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(ctx.env)
        bash, why = _load("x4doctor_x4guard", xg).resolve_bash()
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return bash, (why or "")


#: Sourced through the guards' bash: the values the guards see, one KEY=VALUE per line.
_PROBE = r'''
. "$HOOK_DIR/_x4-env.sh" >/dev/null 2>&1
printf 'TOOLKIT=%s\nGAME=%s\nREFERENCE=%s\nPROFILE=%s\nMODS=%s\nCFG=%s\n' \
  "${X4_TOOLKIT:-}" "${X4_GAME:-}" "${X4_REFERENCE:-}" "${X4_PROFILE:-}" "${X4_MODS:-}" "${_x4_cfg:-}"
x4_resolve_python
printf 'PY=%s\n' "$X4_PY"
if [ -n "$X4_PY" ]; then
  _v="$("$X4_PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)"
  printf 'PYRC=%s\nPYVER=%s\n' "$?" "$_v"
fi
if printf '%s' '{}' | "${JQ:-jq}" -e . >/dev/null 2>&1; then echo JQ=ok; else echo JQ=missing; fi
'''


def guard_probe(ctx: Ctx) -> tuple[dict | None, str]:
    """Run _PROBE through the guards' own bash with the first guard copy's environment.
    Cached per Ctx: four groups read it."""
    cached = getattr(ctx, "_probe", None)
    if cached is not None:
        return cached
    bash, why = guard_bash(ctx)
    if not bash:
        res = (None, "no bash the guards would run: " + why)
    else:
        target, hooks = guard_dirs(ctx)[0]
        r = _run([bash, "-c", _PROBE], env=_hook_env(ctx, target, hooks), cwd=str(ctx.root))
        vals = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
        res = (vals, "") if "PY" in vals else (None, "the probe printed nothing usable (rc %s): %s"
                                               % (r.returncode, (r.stderr or r.stdout)[-300:]))
    ctx._probe = res
    return res


# ----------------------------------------------------------------- Task 6: toolchain

@group
def check_toolchain(ctx: Ctx) -> list[Check]:
    dirs = guard_dirs(ctx)
    if not dirs:
        why = "no guard target is installed here (a generic agent runs no guards)"
        return [Check(i, "all", NA, why) for i in ("bash.guards", "bash.path", "bash.agree",
                                                    "python.guards", "jq")]
    rows = []
    bash, why = guard_bash(ctx)

    def _bash_guards(_):
        if not bash:
            return FAIL, "x4guard resolves NO usable bash: " + why
        if _is_stub(bash):
            return FAIL, "x4guard would run the guards with a STUB bash (%s): it cannot run them" % bash
        r = _run([bash, "-c", "echo ok"])
        if r.returncode != 0 or r.stdout.strip() != "ok":
            return FAIL, "%s resolves but does not run (rc %s)" % (bash, r.returncode)
        return OK, bash
    rows.append(run_check("bash.guards", "all", _bash_guards, ctx))

    def _bash_path(_):
        if not _on_windows():
            return NA, "the bash-stub trap is Windows-only"
        import shutil
        first = shutil.which("bash", path=ctx.env.get("PATH"))
        if not first:
            return UNKNOWN, "no bash on PATH at all"
        if _is_stub(first):
            return FAIL, ("the first bash on PATH is a STUB (%s). A host that starts a hook as "
                          "`bash ...` gets it, and the hook fails OPEN. Put Git's bin first on PATH."
                          % first)
        return OK, first
    rows.append(run_check("bash.path", "all", _bash_path, ctx))

    def _bash_agree(_):
        gb = None
        for base in (ctx.root, ctx.toolkit):
            if base and (Path(base) / "scripts" / "gitbash.py").is_file():
                gb = Path(base) / "scripts" / "gitbash.py"
                break
        if gb is None:
            return UNKNOWN, "scripts/gitbash.py not found, so the toolkit's own resolver cannot be asked"
        theirs = _load("x4doctor_gitbash", gb).find_bash()
        if not bash or not theirs:
            return UNKNOWN, "x4guard: %s; scripts/gitbash.py: %s" % (bash or "none", theirs or "none")
        if _norm_path(bash) == _norm_path(theirs):
            return OK, "x4guard and scripts/gitbash.py both resolve %s" % bash
        if same_bash(bash, theirs):
            return OK, ("one Git install, two spellings -- x4guard: %s ; scripts/gitbash.py: %s"
                        % (bash, theirs))
        return UNKNOWN, ("the resolvers DISAGREE -- x4guard: %s ; scripts/gitbash.py: %s. Both run, "
                         "but a fix applied to one is not applied to the other" % (bash, theirs))
    rows.append(run_check("bash.agree", "all", _bash_agree, ctx))

    def _python(_):
        vals, why2 = guard_probe(ctx)
        if vals is None:
            return UNKNOWN, why2
        py = vals.get("PY", "")
        if not py:
            if ctx.env.get("X4_PYTHON"):
                return FAIL, ("X4_PYTHON=%s does not resolve, and the guards REFUSE to fall back "
                              "to another interpreter" % ctx.env["X4_PYTHON"])
            return FAIL, "the guards find no python/python3/py: protect-bash cannot analyse commands"
        if vals.get("PYRC") != "0" or not vals.get("PYVER"):
            return FAIL, ("%s resolves but does not run (rc %s) -- a Store stub, or a broken "
                          "install" % (py, vals.get("PYRC")))
        major, minor = (int(x) for x in vals["PYVER"].split("."))
        if (major, minor) < (3, 10):
            return FAIL, "%s is Python %s; the guards need >= 3.10" % (py, vals["PYVER"])
        return OK, "%s -> Python %s" % (py, vals["PYVER"])
    rows.append(run_check("python.guards", "all", _python, ctx))

    def _jq(_):
        vals, why2 = guard_probe(ctx)
        if vals is None:
            return UNKNOWN, why2
        if vals.get("JQ") == "ok":
            return OK, "jq runs"
        if vals.get("PYRC") == "0" and vals.get("PYVER"):
            return OK, "jq absent; the guards fall back to python (degraded, as setup.sh warns)"
        return FAIL, "neither jq nor a working python: the guards cannot render a verdict"
    rows.append(run_check("jq", "all", _jq, ctx))
    return rows


# ----------------------------------------------------------------- Task 6: roots

#: Asked of the TOOLS' resolver, run from the root the way an agent would run a tool.
_PY_ROOTS = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from x4validate import _paths
out = {}
for k in ("game_root", "reference", "profile", "_find_env_file"):
    try:
        v = getattr(_paths, k)()
        out[k] = None if v is None else str(v)
    except Exception as e:
        out[k] = None
        out[k + "_error"] = "%s: %s" % (type(e).__name__, e)
print(json.dumps(out))
'''


def tools_roots(ctx: Ctx) -> tuple[dict | None, str]:
    """The tools' answer. The resolver CODE comes from X4_TOOLKIT, else the root, else the
    toolkit this doctor ships in; the CONFIG it finds is decided by env and cwd alone, as
    for any tool an agent runs from the root."""
    for base in (ctx.toolkit, ctx.root, HERE.parent):
        if base and (Path(base) / "tools" / "x4validate" / "x4validate" / "_paths.py").is_file():
            pkg = Path(base) / "tools" / "x4validate"
            r = _run([sys.executable, "-c", _PY_ROOTS, str(pkg)], env=dict(ctx.env), cwd=str(ctx.root))
            try:
                return json.loads(r.stdout.strip().splitlines()[-1]), str(pkg)
            except (ValueError, IndexError):
                return None, "the tools' resolver failed (rc %s): %s" % (r.returncode, r.stderr[-300:])
    return None, "no tools/x4validate under X4_TOOLKIT or the root, so the tools' view cannot be asked"


@group
def check_roots(ctx: Ctx) -> list[Check]:
    if not guard_dirs(ctx):
        why = "no guard target is installed here"
        return [Check(i, "all", NA, why) for i in ("roots.reference", "roots.game", "roots.agree")]
    vals, why = guard_probe(ctx)

    def _ref(_):
        if vals is None:
            return UNKNOWN, why
        ref = vals.get("REFERENCE", "")
        if not ref:
            return FAIL, "the guards resolve NO reference root: nothing under it is protected"
        if not Path(ref).is_dir():
            return UNKNOWN, ("the guards protect %s, which does not exist yet (not unpacked?); "
                             "nothing is there to damage" % ref)
        return OK, ref

    def _game(_):
        if vals is None:
            return UNKNOWN, why
        game = vals.get("GAME", "")
        if not game:
            return FAIL, "X4_GAME is unset for the guards: the game install is NOT protected"
        if not Path(game).is_dir():
            return FAIL, "the guards' X4_GAME names a folder that does not exist: %s" % game
        return OK, game

    def _agree(_):
        if vals is None:
            return UNKNOWN, why
        tools, where = tools_roots(ctx)
        if tools is None:
            return UNKNOWN, where
        cfg_g = vals.get("CFG") or "(none)"
        cfg_t = tools.get("_find_env_file") or "(none found)"
        diffs = []
        for label, gkey, tkey in (("reference", "REFERENCE", "reference"), ("game", "GAME", "game_root")):
            gv, tv = vals.get(gkey, ""), tools.get(tkey)
            if _norm_path(gv) != _norm_path(tv):
                diffs.append("%s: guards %s vs tools %s" % (label, gv or "(unset)", tv or "(unset)"))
        detail = "guards read %s; tools read %s" % (cfg_g, cfg_t)
        if diffs:
            return FAIL, ("the guards and the tools see DIFFERENT trees -- they protect one and "
                          "read another. %s. (%s)" % ("; ".join(diffs), detail))
        return OK, "the guards and the tools agree on reference and game; " + detail

    return [run_check("roots.reference", "all", _ref, ctx),
            run_check("roots.game", "all", _game, ctx),
            run_check("roots.agree", "all", _agree, ctx)]


# ----------------------------------------------------------------- Task 7: parity

#: The first line of every generated instruction file carries this (gen-agent-trees.py's
#: BANNER_CLAUDE_MD / BANNER_MD both begin with it).
GENERATED_MARK = "<!-- GENERATED"
INSTRUCTION_FILE = {"claude": "CLAUDE.md", "codex": "AGENTS.md", "generic": "AGENTS.md"}


def _parity_module(ctx: Ctx):
    """deploy_parity.py -- from the source toolkit if its comparer knows TargetSpecs, else
    the one this doctor ships with. One comparer for the gate and the doctor, so they
    cannot disagree; the SOURCE tree compared is X4_TOOLKIT's either way."""
    for i, base in enumerate((ctx.toolkit, HERE.parent)):
        p = Path(base) / "tools" / "x4validate" / "gates" / "deploy_parity.py" if base else None
        if p and p.is_file():
            try:
                m = _load("x4doctor_deploy_parity_%d" % i, p)
            except Exception:  # noqa: BLE001 -- an unloadable gate is tried past, not trusted
                continue
            if _parity_targets(m):
                return m
    return None


def _parity_targets(mod) -> dict:
    return dict(getattr(mod, "TARGETS", {}) or {})


def _venv_python(tk: Path) -> Path | None:
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        p = tk / "tools" / "x4validate" / ".venv" / Path(*rel)
        if p.is_file():
            return p
    return None


def _has_banner(p: Path) -> bool:
    try:
        with open(p, "rb") as fh:
            return GENERATED_MARK.encode() in fh.read(2048)
    except OSError:
        return False


@group
def check_parity(ctx: Ctx) -> list[Check]:
    rows: list[Check] = []
    mod_box: dict = {}

    def mod():
        if "m" not in mod_box:
            mod_box["m"] = _parity_module(ctx)
        return mod_box["m"]

    for target in ("claude", "codex"):
        cid = "parity." + target
        if not ctx.targets.get(target):
            rows.append(Check(cid, target, NA, "the %s target is not installed here" % target))
            continue

        def _one(_, target=target):
            if ctx.toolkit is None:
                return UNKNOWN, ("X4_TOOLKIT is unset, so there is no SOURCE to compare against "
                                 "(never this doctor's own folder: an installed copy would compare "
                                 "to itself)")
            src = Path(ctx.toolkit)
            m = mod()
            if m is None:
                return UNKNOWN, "no gates/deploy_parity.py to compare with"
            spec = _parity_targets(m).get(target)
            if spec is None:
                return UNKNOWN, ("deploy_parity has no TargetSpec for %r yet, so the %s tree "
                                 "cannot be compared" % (target, target))
            if src.resolve() == ctx.root.resolve():
                gen = src / "tools" / "x4validate" / "scripts" / "gen-agent-trees.py"
                py = _venv_python(src)
                if not (src / "agent").is_dir() or not gen.is_file():
                    return UNKNOWN, ("this root IS the toolkit and has no agent/ source, so parity "
                                     "cannot be checked here (an installed toolkit is runtime-only)")
                if py is None:
                    return UNKNOWN, ("this root is the toolkit; its generator needs the venv "
                                     "(tools/x4validate/.venv), which is absent -- run setup.sh")
                r = _run([str(py), str(gen), "--check"], cwd=str(gen.parent.parent), timeout=300)
                if r.returncode == 0:
                    return OK, "the generated trees match agent/ (gen-agent-trees.py --check)"
                return FAIL, ("gen-agent-trees.py --check rc %s: %s"
                              % (r.returncode, (r.stdout + r.stderr).strip()[-400:]))
            a, b = src / spec.root_rel, ctx.root / spec.root_rel
            rws = m.compare_trees(a, b, spec)
            if not rws:
                return UNKNOWN, "nothing to compare: both %s populations are empty" % spec.root_rel
            off = [r for r in rws if not r.at_parity]
            if off:
                shown = "; ".join(m.describe(r) for r in off[:10])
                more = " ... and %d more NOT LISTED" % (len(off) - 10) if len(off) > 10 else ""
                return FAIL, "%d of %d file(s) differ from %s: %s%s" % (len(off), len(rws), src, shown, more)
            rew = sum(1 for r in rws if r.state != m.IDENTICAL)
            return OK, "%d file(s) at parity with %s (%d via the installer rewrite)" % (len(rws), src, rew)
        rows.append(run_check(cid, target, _one, ctx))

    # The instruction files are in no deploy population (READ): reported here instead.
    for target in ("claude", "codex", "generic"):
        cid = "instructions." + target
        if not ctx.targets.get(target):
            rows.append(Check(cid, target, NA, "the %s target is not installed here" % target))
            continue

        def _instr(_, target=target):
            name = INSTRUCTION_FILE[target]
            p = ctx.root / name
            if not p.is_file():
                return FAIL, ("no %s here: the %s target runs without the toolkit's instructions"
                              % (name, target))
            if _has_banner(p):
                return OK, "%s is the toolkit's generated file" % name
            if target == "claude":
                return OK, "%s has no GENERATED banner (hand-written or pre-4.0)" % name
            return FAIL, ("%s has no GENERATED banner: %s reads THIS file, and it is not the "
                          "toolkit's -- re-run the installer, which keeps yours as AGENTS.pre-4.0.md"
                          % (name, "Codex" if target == "codex" else "a generic agent"))
        rows.append(run_check(cid, target, _instr, ctx))

    agents = ctx.root / "AGENTS.md"
    if agents.is_file() and not (ctx.targets.get("codex") or ctx.targets.get("generic")):
        kind = "the toolkit's generated file" if _has_banner(agents) else "a hand-written file"
        rows.append(Check("instructions.agents_md", "all", OK,
                          "NOTE: %s is %s; no Codex/generic target is installed, but any Codex "
                          "session started here reads it" % (agents.name, kind)))
    return rows


def _verdict(code: int) -> str:
    return {0: "OK -- every applicable check passed",
            1: "FAIL -- at least one check failed: the guards here are not fully live or not current (see FAIL rows)",
            3: "UNKNOWN -- nothing failed, but some checks could not answer (see UNKNOWN rows)",
            2: "COULD NOT RUN -- nothing was checked; this is not a pass"}[code]


def render_text(ctx: Ctx, rows: list[Check], code: int, elapsed: float) -> str:
    present = [t for t in TARGETS if ctx.targets.get(t)]
    out = ["x4doctor: %s" % _verdict(code),
           "  root:    %s" % ctx.root,
           "  targets: %s" % (", ".join(present) or "NONE (no .claude/settings.json, .codex/hooks or .agents/skills here)"),
           "  checked: %d row(s) in %.1fs -- %s" % (
               len(rows), elapsed,
               ", ".join("%d %s" % (sum(r.status == s for r in rows), s) for s in STATUSES)),
           ""]
    w = max([len(r.id) for r in rows] + [10])
    for r in rows:
        out.append("  %-7s %-8s %-*s %s" % (r.status, r.target, w, r.id, r.detail))
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    if sys.version_info < (3, 10):
        print("x4doctor: COULD NOT RUN -- needs Python >= 3.10 (this is %d.%d)" % sys.version_info[:2])
        return 2
    ap = argparse.ArgumentParser(prog="x4doctor", description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="the folder an agent runs in (default: nearest ancestor holding a target)")
    ap.add_argument("--agent", help="report only this target: " + ", ".join(TARGETS))
    ap.add_argument("--json", action="store_true", help="one JSON document on stdout")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if a.agent and a.agent not in TARGETS:
        print("x4doctor: COULD NOT RUN -- unknown --agent %r (one of: %s)" % (a.agent, ", ".join(TARGETS)))
        return 2
    root = Path(a.root).resolve() if a.root else default_root(Path.cwd())
    ctx = Ctx(root=root)
    t0 = time.monotonic()
    rows = collect(ctx, a.agent) if any(ctx.targets.values()) else []
    elapsed = time.monotonic() - t0
    code = exit_code(rows)
    if a.json:
        print(json.dumps({"v": 1, "root": str(ctx.root),
                          "targets": {t: ("present" if ctx.targets.get(t) else "absent") for t in TARGETS},
                          "checks": [asdict(r) for r in rows],
                          "summary": _verdict(code), "exit": code,
                          "elapsed_s": round(elapsed, 2)}, indent=1))
    else:
        sys.stdout.write(render_text(ctx, rows, code, elapsed))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

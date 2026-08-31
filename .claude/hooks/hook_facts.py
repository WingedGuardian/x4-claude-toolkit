"""One parse pass over a Bash hook payload, answering every guard rule's question.

protect-bash.sh keeps the POLICY -- which verdict, and the prose explaining it. This
module supplies the FACTS. That split exists because the previous design had each of
eight rules hand-roll its own quote-aware shell parsing in bash, and:

  * MEASURED 2026-08-31, clean machine, 201-char command: 13,585 ms per Bash call,
    against 1,205 ms before the rules were re-scoped -- 11.3x. PreToolUse blocks the
    tool call, so that is pure latency on every command. Attributed by profiling:
    resolve_var cost 236 ms for ONE token and was called per-token inside per-segment
    loops; writes_under and searches_rooted_at were re-invoked 5 and 4 times, each
    re-tokenising from scratch.
  * Every gap a code review found lived in that duplicated parsing -- `mv -t`, `>|`,
    wrapper verbs (time/nice/env/sudo/xargs), `grep -r -e`, rg being recursive by
    default, and a heredoc marker inside a quoted string opening a skip region.

Fixing those one predicate at a time meant writing the same parser eight more times.
This is the "one implementation, asked for by everyone else" rule from CLAUDE.md's
narrowing-step table, applied to the guards themselves.

Pure functions throughout: no filesystem, no environment, no subprocesses. Everything
here is unit-tested directly in test_hook_facts.py.
"""
from __future__ import annotations

import posixpath
import re
import sys

# --------------------------------------------------------------------- paths

_DRIVE = re.compile(r"(^|[^a-z0-9])([a-z]):/")


def norm(p: str) -> str:
    """Lowercase, backslashes to slashes, drive dialect unified, dot segments resolved.

    Windows-to-MSYS is the safe direction: "c:/" is unambiguous, since a colon is
    illegal elsewhere in a Windows path, whereas "/c/" also occurs mid-path. The guard
    on the preceding character is what keeps "https://" from matching as a drive "s".
    """
    if not p:
        return ""
    s = p.replace(chr(92), "/").lower()
    s = _DRIVE.sub(lambda m: m.group(1) + "/" + m.group(2) + "/", s)
    # Only canonicalise something that is actually a path. normpath would happily
    # rewrite "https://a/b" to "https:/a/b".
    if "://" not in s and ("/./" in s or "/../" in s or s.endswith(("/.", "/.."))):
        s = posixpath.normpath(s)
    if len(s) > 1:
        s = s.rstrip("/")
    return s


def under(path: str, root: str) -> bool:
    """True if `path` is `root` or sits inside it. False when root is empty --
    an unconfigured machine must get no rule rather than a rule against ""."""
    if not root or not path:
        return False
    r, p = norm(root), norm(path)
    return p == r or p.startswith(r + "/")


def is_root(path: str, root: str) -> bool:
    """True only if `path` IS `root`. A search scoped to a subdirectory is deliberate
    and must not be blocked; over-blocking is the worse failure because the reason is
    not obvious from the message."""
    return bool(root) and bool(path) and norm(path) == norm(root)


# ---------------------------------------------------------------- tokenising
_OPERATORS = ("&&", "||", ";", "|", "&", "\n")


def _scan(s: str):
    """Yield (char, in_quote) so every helper can respect quoting identically."""
    q = ""
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            yield c, True
            if c == q:
                q = ""
            elif c == chr(92) and q == '"' and i + 1 < len(s):
                i += 1
                yield s[i], True
        elif c in "\"'":
            q = c
            yield c, True
        else:
            yield c, False
        i += 1


def blank_quoted(s: str) -> str:
    """Replace the CONTENTS of quoted strings with spaces, keeping length and the
    quote characters. Flag detection must not read a hyphenated search PATTERN as
    flags, and a heredoc marker inside a string is data, not a marker."""
    out = []
    for c, inq in _scan(s):
        out.append(" " if (inq and c not in "\"'") else c)
    return "".join(out)


def segments(cmd: str) -> list[str]:
    """Split on shell separators that are OUTSIDE quotes. A `|` inside grep -E 'a|b'
    is not a pipeline."""
    parts, buf, chars = [], [], list(_scan(cmd))
    i = 0
    while i < len(chars):
        c, inq = chars[i]
        if not inq:
            # A REDIRECT OPERATOR is consumed whole, before any separator test. `>|`
            # contains a pipe and `2>&1` contains an ampersand: splitting on those tore
            # the redirect away from its target, so every write rule saw a redirect with
            # nothing after it. Found by E2E, because redirects() had only ever been
            # tested on a string that was never split.
            j = i
            if c == "&" and i + 1 < len(chars) and not chars[i + 1][1] \
                    and chars[i + 1][0] == ">":
                j = i + 1
            if chars[j][0] in "<>":
                k = j + 1
                while k < len(chars) and not chars[k][1] and chars[k][0] in "<>|&":
                    k += 1
                buf.extend(chars[m][0] for m in range(i, k))
                i = k
                continue
            two = c + (chars[i + 1][0] if i + 1 < len(chars) and not chars[i + 1][1] else "")
            if two in ("&&", "||"):
                parts.append("".join(buf))
                buf = []
                i += 2
                continue
            if c in ";|&\n":
                parts.append("".join(buf))
                buf = []
                i += 1
                continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return [p for p in parts if p.strip()]


def tokens(seg: str) -> list[tuple[str, bool]]:
    """(text, was_quoted) per token. Quotes are stripped from the text; a
    backslash-escaped space JOINS, which is why `X4\\ Foundations` must stay one token
    -- the bash tokeniser split it and the game-delete block stopped firing."""
    out, buf, quoted, started = [], [], False, False
    q = ""
    i = 0
    while i < len(seg):
        c = seg[i]
        if q:
            if c == q:
                q = ""
            elif c == chr(92) and q == '"' and i + 1 < len(seg):
                i += 1
                buf.append(seg[i])
            else:
                buf.append(c)
        elif c in "\"'":
            q = c
            quoted = started = True
        elif c == chr(92) and i + 1 < len(seg):
            i += 1
            buf.append(seg[i])          # \<space> joins; \x keeps x
            started = True
        elif c.isspace():
            if started:
                out.append(("".join(buf), quoted))
            buf, quoted, started = [], False, False
        else:
            buf.append(c)
            started = True
        i += 1
    if started:
        out.append(("".join(buf), quoted))
    return out


def words(seg: str) -> list[str]:
    return [t for t, _ in tokens(seg)]


# -------------------------------------------------------------- assignments
_ASSIGN = re.compile(r"(?:^|[;&|\s])([A-Za-z_][A-Za-z0-9_]*)=")


def assignments(cmd: str) -> dict[str, str]:
    """NAME -> value for assignments made in this same command. LAST wins: the bash
    helper took the first, so a reassigned variable resolved to the stale value."""
    found: dict[str, str] = {}
    for seg in segments(cmd):
        for tok, _ in tokens(seg):
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", tok, re.S)
            if m:
                found[m.group(1)] = m.group(2)
    return found


_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def resolve(tok: str, assigns: dict[str, str]) -> str:
    """Substitute what this command itself assigned. Text is all a hook can see, so
    this is the most that could ever be resolved."""
    def sub(m):
        name = m.group(1) or m.group(2)
        return assigns.get(name, m.group(0))
    prev = None
    out = tok
    for _ in range(5):                       # bounded: nested vars, never a loop
        prev, out = out, _VAR.sub(sub, out)
        if out == prev:
            break
    return out


def has_unresolved(tok: str) -> bool:
    return bool(_VAR.search(tok))


# ------------------------------------------------------------------ heredocs
_HD = re.compile(r"<<-?\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?")


def _quote_mask(s: str) -> list[bool]:
    """True at every index that sits inside (or is) a quote. Index-aligned with `s`."""
    mask = [False] * len(s)
    q = ""
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            mask[i] = True
            if c == q:
                q = ""
            elif c == chr(92) and q == '"' and i + 1 < len(s):
                mask[i + 1] = True
                i += 1
        elif c in "\"'":
            q = c
            mask[i] = True
        i += 1
    return mask


def heredoc_marker(line: str):
    """The terminator opened by this line, or None.

    The `<<` must be OUTSIDE quotes -- otherwise `echo "a <<MARK b"` opens a skip region
    and hides every following command from three refusal rules. But the MARKER ITSELF is
    usually quoted (`<<'PY'` is the commonest form here), so the earlier approach of
    blanking quoted strings before searching blanked the marker name and stopped
    recognising heredocs at all. Test both directions or one of them silently wins.
    """
    mask = _quote_mask(line)
    for i in range(len(line) - 1):
        if line[i] == chr(60) and line[i + 1] == chr(60) and not mask[i] and not mask[i + 1]:
            m = _HD.match(line, i)
            if m:
                return m.group(1)
    return None


def strip_heredocs(cmd: str) -> str:
    """Remove heredoc BODIES: they are the payload of a file being written, not
    commands being run."""
    out, skip, term = [], False, None
    for line in cmd.split("\n"):
        if skip:
            if line.strip() == term or line.strip() == term + ";":
                skip = False
            continue
        t = heredoc_marker(line)
        if t:
            term, skip = t, True
        out.append(line)
    return "\n".join(out)


# ----------------------------------------------------------------- redirects
_REDIR = re.compile(r"(\d?)>(\|?)(>?)")


def redirects(seg: str) -> list[tuple[str, str]]:
    """[(mode, target)] for every redirect that WRITES a file. `>|` overrides
    noclobber and still truncates; `2>&1` duplicates an fd and writes nothing; the
    null device is not a file anyone cares about."""
    out = []
    b = blank_quoted(seg)
    toks = tokens(seg)
    flat = seg
    i = 0
    while i < len(b):
        m = _REDIR.match(b, i)
        if not m or (i > 0 and b[i - 1] == "<"):
            i += 1
            continue
        mode = "append" if m.group(3) else "truncate"
        j = m.end()
        while j < len(flat) and flat[j] in " \t":
            j += 1
        if j < len(flat) and flat[j] == "&":
            i = m.end()
            continue                                    # fd duplication
        rest = flat[j:]
        tgt = words(rest)[0] if words(rest) else ""
        if tgt and norm(tgt) != "/dev/null":
            out.append((mode, tgt))
        i = m.end()
    del toks
    return out


# --------------------------------------------------------------------- verbs
WRAPPERS = {"time", "nice", "env", "sudo", "xargs", "command", "nohup", "stdbuf"}


def verb(seg: str) -> str:
    """The command actually being run, seeing through env-assignment prefixes and
    wrappers. `write_targets` required the verb to be the segment's FIRST word, so
    `echo x | sudo tee <docs>/n.txt` and `time cp ...` lost their destination."""
    for t, quoted in tokens(seg):
        if quoted:
            return t
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            continue
        if t in WRAPPERS:
            continue
        if t.startswith("-"):
            continue
        return t
    return ""


def _operands(seg: str) -> list[str]:
    """Non-flag, non-redirect operands after the verb."""
    out, seen_verb, skip = [], False, False
    for t, quoted in tokens(seg):
        if skip:
            skip = False
            continue
        if not seen_verb:
            if quoted or not (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t)
                              or t in WRAPPERS or t.startswith("-")):
                seen_verb = True
            continue
        if t in ("<", ">", ">>", ">|", "&>"):
            skip = True
            continue
        if not quoted and (t.startswith(("<", ">")) or re.match(r"^\d+>", t)):
            continue
        if not quoted and t.startswith("-"):
            continue
        out.append(t)
    return out


COPY_VERBS = {"cp", "mv", "move", "copy", "tee", "install", "rsync"}


def copy_dests(seg: str) -> list[str]:
    """Where a copy/move/tee WRITES. cp/mv write their LAST operand -- unless -t names
    the destination directory. tee writes EVERY file operand, so its destination is the
    FIRST; taking "the last token" for tee picked up the source of a `< input`."""
    v = verb(seg)
    if v not in COPY_VERBS:
        return []
    toks = tokens(seg)
    for i, (t, quoted) in enumerate(toks):
        if not quoted and t in ("-t", "--target-directory"):
            if i + 1 < len(toks):
                return [toks[i + 1][0]]
        if not quoted and t.startswith("--target-directory="):
            return [t.split("=", 1)[1]]
    ops = _operands(seg)
    if not ops:
        return []
    return ops if v == "tee" else [ops[-1]]


DELETE_VERBS = {"rm", "rmdir", "unlink", "shred"}


def rm_paths(seg: str) -> list[str]:
    return _operands(seg) if verb(seg) in DELETE_VERBS else []


# ------------------------------------------------------------------ searches
# rg and ag recurse with NO flag at all. The bash rule gated on a recursive FLAG, so a
# full-tree `rg` -- the exact command the rule exists to stop -- was allowed.
SEARCH_VERBS = {"grep": False, "egrep": False, "fgrep": False,
                "rg": True, "ag": True, "ack": True}
_RECURSIVE = re.compile(r"^-[a-zA-Z]*[rR][a-zA-Z]*$")


# Flags that CONSUME the next argument. Without this, `grep -r -e foo /ref` counted
# "foo" as a path: -e supplied the pattern, so the operand walk must skip it too --
# not merely know that a pattern was given.
_ARG_FLAGS = {"-e", "-f", "-m", "-A", "-B", "-C", "-d", "-g", "-t",
              "--regexp", "--file", "--max-count", "--include", "--exclude",
              "--exclude-dir", "--binary-files", "--color", "--colour", "--glob"}
_PATTERN_FLAGS = {"-e", "-f", "--regexp", "--file"}


def search_paths(seg: str) -> list[str]:
    """Paths a RECURSIVE search runs over. The first non-flag operand is the PATTERN --
    unless -e/-f supplied it, in which case every remaining operand is a path."""
    v = verb(seg)
    if v not in SEARCH_VERBS:
        return []
    recursive = SEARCH_VERBS[v]
    pattern_given = False
    ops: list[str] = []
    seen_verb = skip = False
    for t, quoted in tokens(seg):
        if skip:
            skip = False
            continue
        if not seen_verb:
            if quoted or not (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t)
                              or t in WRAPPERS or t.startswith("-")):
                seen_verb = True
            continue
        if not quoted and t.startswith("-") and t != "-":
            if _RECURSIVE.match(t) or t == "--recursive":
                recursive = True
            base = t.split("=", 1)[0]
            if base in _PATTERN_FLAGS:
                pattern_given = True
            if base in _ARG_FLAGS and "=" not in t:
                skip = True
            continue
        if not quoted and (t.startswith(("<", ">")) or re.match(r"^\d+>", t)):
            continue
        ops.append(t)
    if not recursive:
        return []
    return ops if pattern_given else ops[1:]


def cwd_of(cmd: str) -> str:
    """The last `cd` target in the command, so `cd <root> && grep -rn foo .` resolves."""
    cwd = ""
    for seg in segments(cmd):
        if verb(seg) == "cd":
            ops = _operands(seg)
            if ops:
                cwd = ops[0]
    return cwd


# ------------------------------------------------------------------- $? rule
def dollarq_after_pipe(cmd: str) -> bool:
    """`cmd | head; echo $?` reports HEAD's exit code. Only the same segment or the one
    immediately before can be the referent. A pipe inside a process substitution runs in
    a subshell, so its status never becomes $?."""
    stripped = strip_heredocs(cmd)
    if "$?" not in stripped or "PIPESTATUS" in stripped:
        return False
    prev_piped = False
    for raw in re.split(r"[;\n]|&&|\|\|", stripped):
        chk = re.sub(r"[<>]\([^)]*\)", "", blank_quoted(raw))
        piped = bool(re.search(r"[^|]\|[^|]", chk))
        if "$?" in raw and (piped or prev_piped):
            return True
        prev_piped = piped
    return False


# ------------------------------------------------------------------- facts
DURABLE = re.compile(r"(memory[/\\][A-Za-z0-9_.-]+\.md|MEMORY\.md|KNOWLEDGEBASE\.md"
                     r"|CLAUDE\.md|BLIND-SPOTS\.md)")
LONG_JOBS = ("corpus_sweep", "perf_guard", "build-effective.sh", "build-corpus.sh",
             "stage.py")
INVOKERS = re.compile(r"\b(uv run|python|python3|bash)\b")
ARCHIVE = re.compile(r"\.(zip|7z|rar|tar|gz|log|bak)$", re.I)
LEGACY_GAME = re.compile(r"x4 foundations|egosoft/x4", re.I)


def _expand(seg: str, paths: list[str], assigns: dict) -> list[tuple[str, bool]]:
    """(resolved path, still-unresolved) -- an unresolvable destination must keep the
    guard, not drop it."""
    return [(resolve(p, assigns), has_unresolved(resolve(p, assigns))) for p in paths]


def _hits(paths, root, cmd, assigns) -> bool:
    for p, unresolved in _expand("", paths, assigns):
        if unresolved:
            if root and norm(root) in norm(cmd):
                return True
            continue
        if under(p, root):
            return True
    return False


def _inner_commands(cmd: str) -> list[str]:
    """`bash -c "<command>"` hides everything inside from every rule. Parse it too."""
    out = []
    for seg in segments(cmd):
        if verb(seg) not in ("bash", "sh", "zsh"):
            continue
        toks = tokens(seg)
        for i, (t, quoted) in enumerate(toks):
            if not quoted and t == "-c" and i + 1 < len(toks):
                out.append(toks[i + 1][0])
    return out


def facts(payload: dict, roots: dict) -> dict:
    inp = payload.get("tool_input") or {}
    cmd = inp.get("command") or ""
    timeout = inp.get("timeout", 0)
    background = inp.get("run_in_background", False)

    all_cmds = [cmd] + _inner_commands(cmd)
    segs = [s for c in all_cmds for s in segments(c)]
    assigns = assignments(cmd)
    ncmd = norm(cmd)
    cwd = cwd_of(cmd)

    rm_t, copy_t, redir_t = [], [], []
    for s in segs:
        rm_t += rm_paths(s)
        copy_t += copy_dests(s)
        redir_t += redirects(s)

    def res(p):
        return resolve(p, assigns)

    def hit(paths, root):
        if not root:
            return False
        for p in paths:
            r = res(p)
            if has_unresolved(r):
                if norm(root) in ncmd:
                    return True
            elif under(r, root):
                return True
        return False

    writes_any = [p for p in copy_t + rm_t] + [t for _, t in redir_t]
    trunc_redirect = [t for m, t in redir_t if m == "truncate"]

    # The game-delete backstop, restored. A machine with no configured paths must still
    # be protected -- the header of protect-bash.sh promises exactly that -- and the
    # measured false positive (7 of 8) was an ARCHIVE merely named after the game, which
    # the extension exclusion removes without giving up the name test.
    rm_named_game = any(LEGACY_GAME.search(res(p)) and not ARCHIVE.search(res(p))
                        for p in rm_t)

    search_roots = []
    for c in all_cmds:
        c_cwd = cwd_of(c)
        for s in segments(c):
            for p in search_paths(s):
                r = res(p)
                search_roots.append(c_cwd if r in (".", "./") else r)

    def rooted(root):
        return bool(root) and any(is_root(p, root) for p in search_roots)

    stripped = strip_heredocs(cmd)
    stripped_blank = blank_quoted(stripped)

    longjob = False
    for s in segments(stripped):
        b = blank_quoted(s)
        if any(j in b for j in LONG_JOBS) or ("x4effective" in b and "build" in b):
            if INVOKERS.search(b):
                longjob = True

    return {
        "command": cmd,
        "timeout": timeout,
        "background": background,

        "rm_hits_game": hit(rm_t, roots.get("game")) or rm_named_game,
        "rm_targets_reference": hit(rm_t, roots.get("reference")),
        "rm_in_x4_dir": any(hit(rm_t, roots.get(k)) for k in
                            ("game", "profile", "mods", "toolkit")) or rm_named_game,
        "rm_saves": hit(rm_t, roots.get("saves")),

        "writes_documents": hit(writes_any, roots.get("documents")),
        "copy_into_game_or_profile": bool(copy_t) and (
            hit(copy_t, roots.get("game")) or hit(copy_t, roots.get("profile"))),
        "redirect_truncate_into_game_or_profile": (
            hit(trunc_redirect, roots.get("game"))
            or hit(trunc_redirect, roots.get("profile"))),

        "sed_i_in_game_or_profile": bool(re.search(r"sed\s+-i", stripped_blank)) and (
            (roots.get("game") and norm(roots["game"]) in ncmd)
            or (roots.get("profile") and norm(roots["profile"]) in ncmd)
            or bool(LEGACY_GAME.search(cmd))),

        # re.M is load-bearing: the bash original used grep, which is LINE based, so `^`
        # matched every line start. Without it this only saw a command whose very first
        # characters were `git add`, and multi-line commands are routine here.
        "git_add_all": bool(re.search(r"(^|[;&|]\s*)git\s+add\s+(-A\b|--all\b|\.\s*$|\.\s*[;&|])",
                                      stripped_blank, re.M)),
        "durable_truncating_redirect": any(DURABLE.search(res(t)) for t in trunc_redirect),
        "durable_python_open_w": bool(DURABLE.search(cmd)) and bool(
            re.search(r"open\([^)]*,\s*[\"']w[\"']", cmd)),

        "search_rooted_reference": rooted(roots.get("reference")),
        "search_rooted_workspace": any(rooted(roots.get(k)) for k in
                                       ("toolkit", "game", "mods")),
        "profile_search_by_name": (
            bool(re.search(r"\b(grep|rg|ag|findstr|Select-String)\b", stripped, re.I))
            and ((roots.get("profile") and norm(roots["profile"]) in ncmd)
                 or "X4_PROFILE" in cmd)
            and "content" in cmd.lower()
            and not re.search(r"ws_[0-9]{4,}", cmd)),

        "dollarq_after_pipe": dollarq_after_pipe(cmd),
        "write_to_tmp": bool(re.search(r"(>|>>|-o|--output[= ])\s*[\"']?/tmp/", cmd)),
        "timeout_over_cap": isinstance(timeout, int) and timeout > 600000,
        "longjob_foreground": longjob and background is not True,
        "xrcat_reunpack": (bool(re.search(r"xrcat", cmd, re.I))
                           and "-out" in ncmd
                           and bool(roots.get("reference"))
                           and norm(roots["reference"]) in ncmd),
        "cwd": cwd,
    }


# ----------------------------------------------------------------------- CLI
# Emits `key<TAB>0|1` lines, then a sentinel, then the RAW command to EOF. The command
# goes last and unescaped because it may be multi-line -- heredocs are routine here, and
# any escaping scheme would change what the messages print. Bash splits on the sentinel
# with parameter expansion, so nothing is ever eval'd: the values reaching the shell are
# only ever 0, 1, or an integer.
SENTINEL = "__X4_COMMAND__"

# (roots no longer come from the environment -- see main(); MSYS translates them)


ROOT_SEP = "--X4-ROOTS-END--"


def main() -> int:
    import json

    # Roots arrive on STDIN, not in the environment, and that is not a style choice.
    # MSYS/Git-Bash TRANSLATES a POSIX-looking value when it hands an environment
    # variable to a NATIVE Windows process: bash exported "/tmp/x/docs" and this
    # process received "C:/Users/.../AppData/Local/Temp/x/docs", while the command text
    # it was compared against still said "/tmp/x/docs". They can never match, so every
    # path rule silently stopped firing. The README tells users they may write roots in
    # either "C:\..." or "/c/..." form, so this is a real installation, not a test
    # artefact. A byte stream is not translated.
    raw = sys.stdin.read()
    if not raw.strip():
        return 2                      # no payload: the caller must ASK, never allow
    roots = {}
    if ROOT_SEP in raw:
        head, raw = raw.split(ROOT_SEP, 1)
        for line in head.splitlines():
            if "\t" in line:
                k, v = line.split("\t", 1)
                roots[k.strip()] = v.strip()
    try:
        payload = json.loads(raw)
    except ValueError:
        return 3                      # unparseable: likewise a refusal, not an allow
    f = facts(payload, roots)
    cmd = f.pop("command", "")
    f.pop("cwd", None)
    out = []
    for k, v in sorted(f.items()):
        out.append(k + "\t" + (str(int(v)) if isinstance(v, bool) else str(v)))
    out.append(SENTINEL)
    # BINARY, and UTF-8 encoded explicitly. Python's text-mode stdout translates "\n"
    # to "\r\n" on Windows, which put a trailing CR on EVERY value: the shell then
    # compared "1\r" against "1", every predicate read false, and the hook allowed
    # everything while looking perfectly healthy. The sentinel split failed for the
    # same reason. Encoding first also means a non-cp1252 character in a command can
    # never raise mid-write and truncate the output.
    sys.stdout.buffer.write(("\n".join(out) + "\n" + cmd).encode("utf-8", "replace"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

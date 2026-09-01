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


def is_abs(p: str) -> bool:
    """Absolute after normalisation -- `C:/x` and `/c/x` are both absolute."""
    return norm(p).startswith("/")


def join_cwd(cwd: str, p: str) -> str:
    """Resolve `p` against the directory in force, or return "" when that is unknowable.

    Returning "" rather than guessing is the whole safety property: the hook does not
    know the shell's real starting directory, so `cd extensions && rm -rf amod` must
    reach NO rule. Inventing a root there would fire on unrelated work, which is the
    failure mode that gets a guard ignored.
    """
    if not p:
        return cwd
    if is_abs(p):
        return p
    if not cwd or not is_abs(cwd):
        return ""
    return norm(norm(cwd) + "/" + p)


# ---------------------------------------------------------------- tokenising
_OPERATORS = ("&&", "||", ";", "|", "&", "\n")


def _scan(s: str):
    """Yield (char, in_quote) so every helper can respect quoting identically.

    A BACKSLASH OUTSIDE QUOTES ESCAPES THE NEXT CHARACTER. Without that, `don\\'t`
    opened a quote state that never closed, and everything after it read as quoted --
    which `blank_quoted` then erased and `segments` refused to split. `tokens()` already
    honoured the escape, so the two disagreed: tokens saw `dont`, _scan saw an open
    quote (MEASURED 2026-09-01).
    """
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
        elif c == chr(92) and i + 1 < len(s):
            yield c, False
            i += 1
            yield s[i], False          # escaped: never opens a quote
        elif c in "\"'":
            q = c
            yield c, True
        else:
            yield c, False
        i += 1


def ends_open_quote(s: str) -> bool:
    """True when the scan finishes inside a quote -- i.e. this text did not parse.

    ★ This is the class-killer. Every helper here is quote-aware, so ONE unbalanced
    quote silently converts the remainder of a command into 'quoted' text that no rule
    can see. MEASURED 2026-09-01 against c400a05, which denied both members of every
    pair: a single apostrophe in an ordinary English comment turned 5 of 5 refusals --
    including the game-delete HARD BLOCK, the reference block and `git add -A` -- into
    a silent allow. Position pins it: the same apostrophe placed AFTER the command
    still denies.

    A parser that cannot parse must SAY SO rather than return a confident empty answer.
    """
    q = ""
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            if c == q:
                q = ""
            elif c == chr(92) and q == '"':
                i += 1
        elif c == chr(92):
            i += 1
        elif c in "\"'":
            q = c
        i += 1
    return bool(q)


def strip_comments(s: str) -> str:
    """Blank `# ...` to end of line, when the `#` starts a word outside quotes.

    The word-boundary test is what keeps `$#`, `${x#y}` and `http://a#b` intact -- in
    all three the `#` is preceded by a non-space, so none is a comment.
    """
    out, q, i, prev = [], "", 0, ""
    while i < len(s):
        c = s[i]
        if q:
            out.append(c)
            if c == q:
                q = ""
            elif c == chr(92) and q == '"' and i + 1 < len(s):
                i += 1
                out.append(s[i])
        elif c == chr(92) and i + 1 < len(s):
            out.append(c)
            i += 1
            out.append(s[i])
        elif c in "\"'":
            q = c
            out.append(c)
        elif c == "#" and (prev == "" or prev.isspace()):
            while i < len(s) and s[i] != "\n":      # keep the newline: it is a separator
                i += 1
            continue
        else:
            out.append(c)
        prev = c
        i += 1
    return "".join(out)


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
    return [_unwrap(p) for p in parts if p.strip()]


def _unwrap(seg: str) -> str:
    """Strip subshell/group punctuation at a segment's edges.

    `(cd X && rm -rf Y)` splits into `(cd X` and ` rm -rf Y)`, so the verb carried a
    leading paren and the operand a trailing one -- MEASURED 2026-09-01: verb was
    `'(cd'` and the operand `'extensions)'`, so neither matched anything and the
    subshell form of a game delete was silently allowed.

    A trailing `)` is punctuation only when UNBALANCED. `rm -rf $(echo x)` closes its
    own paren, and stripping that would tear up the token.
    """
    s = seg.strip()
    while s[:1] in ("(", "{"):
        s = s[1:].lstrip()
    while s and s[-1] in ")}":
        marks = list(_scan(s))
        if marks and marks[-1][1]:          # quoted -- it is data, not punctuation
            break
        opens = sum(1 for ch, inq in marks if not inq and ch in "({")
        closes = sum(1 for ch, inq in marks if not inq and ch in ")}")
        if closes <= opens:
            break
        s = s[:-1].rstrip()
    return s


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


# `$(...)` and `` `...` `` are values this hook can NEVER know. Without them a
# substitution read as a LITERAL path: MEASURED 2026-09-01, `rm -rf "$(echo <game>)"`
# matched no root and was allowed, while c400a05 -- which grepped the whole command
# string -- denied it. Precision about operands bought blindness to indirection.
_SUBST = re.compile(r"\$\(|" + chr(96))

# An unexpanded root variable is the ONLY evidence there is: `rm -rf "$X4_GAME"` never
# contains the game path as text, so no amount of string matching can find it. The
# variable NAME is what identifies the root.
ROOT_VARS = {"X4_GAME": "game", "X4_REFERENCE": "reference", "X4_PROFILE": "profile",
             "X4_SAVES": "saves", "X4_MODS": "mods", "X4_TOOLKIT": "toolkit",
             "X4_DOCUMENTS": "documents"}


def has_unresolved(tok: str) -> bool:
    return bool(_VAR.search(tok) or _SUBST.search(tok))


def root_vars_named(tok: str) -> set:
    """Root KEYS named by an unexpanded environment variable in this token."""
    out = set()
    for m in _VAR.finditer(tok):
        key = ROOT_VARS.get((m.group(1) or m.group(2)).upper())
        if key:
            out.add(key)
    return out


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


DIR_VERBS = {"cd", "pushd"}


def cwd_of(cmd: str) -> str:
    """The last directory the command relocates to, so `cd <root> && grep -rn foo .`
    resolves. Kept for the search rules, which ask only about the end state."""
    tracked = cwd_track(cmd)
    return tracked[-1][1] if tracked else ""


def cwd_track(cmd: str, base: str = "") -> list:
    """[(segment, the directory in force FOR that segment)], in command order.

    Positional, not end-state: in `cd X && rm -rf Y` the `cd` itself still runs from
    the base, and only `rm` sees X. `pushd` pushes, `popd` pops -- without the stack,
    ignoring `popd` would resolve a later relative path against a directory the shell
    had already left, inventing a false positive.

    A subshell's `cd` is deliberately NOT unwound at the closing paren. Modelling that
    needs a real parser, and for a guard the relocated directory is the safe error.
    """
    out, cwd, stack = [], base, []
    for seg in segments(cmd):
        out.append((seg, cwd))
        v = verb(seg)
        if v in DIR_VERBS:
            ops = _operands(seg)
            if ops:
                if v == "pushd":
                    stack.append(cwd)
                # `cd -` returns somewhere this hook cannot know; refuse to guess.
                cwd = "" if ops[0] == "-" else join_cwd(cwd, ops[0])
        elif v == "popd" and stack:
            cwd = stack.pop()
    return out


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
LEGACY_GAME = re.compile(r"x4 foundations|egosoft/x4", re.I)
# ROOT-scoped: the path must END at the game folder (or at its extensions/), not
# merely contain the name. Without the anchor the backstop re-created the very
# over-block it sits beside, by a different route.
GAME_ROOTISH = re.compile(r"(x4 foundations|egosoft/x4)(/extensions)?$", re.I)


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

    # PARSE THE COMMANDS, NOT THE PROSE. Heredoc bodies are data (a body line reading
    # `rm -rf <game>` is text being written, and used to hard-deny), and a `#` comment is
    # not a command at all -- while an apostrophe inside one blinded every rule after it.
    body = strip_comments(strip_heredocs(cmd))
    all_cmds = [body] + _inner_commands(body)
    assigns = assignments(body)
    ncmd = norm(cmd)

    # Every operand is classified WHERE IT RUNS. `cwd_track` was the missing link: the
    # directory was already computed and only the search rules ever consumed it, so a
    # path named relative to a `cd` reached no other rule at all.
    seg_cwd = [pair for c in all_cmds for pair in cwd_track(c)]
    segs = [s for s, _ in seg_cwd]
    cwd = seg_cwd[-1][1] if seg_cwd else ""

    def prep(paths, c_cwd):
        """(path resolved where it runs, unresolvable?, the token as written)."""
        out = []
        for p in paths:
            r = resolve(p, assigns)
            unres = has_unresolved(r)
            out.append((r if unres else join_cwd(c_cwd, r), unres, r))
        return out

    rm_t, copy_t, redir_t = [], [], []
    for s, c_cwd in seg_cwd:
        rm_t += prep(rm_paths(s), c_cwd)
        copy_t += prep(copy_dests(s), c_cwd)
        for mode, tgt in redirects(s):
            redir_t += [(mode,) + o for o in prep([tgt], c_cwd)]

    def hit(ops, key, conservative=False):
        """`conservative` is the delete-only rule (user decision 2026-09-01): an
        operand this hook cannot resolve is not evidence of safety. Deletes are the one
        channel with nothing behind them -- MEASURED, 0 of 186 auto-backups cover
        anything outside dev/, and savegames are covered by nothing at all. Writes keep
        their existing verdicts so this cannot add prompts to routine work."""
        root = roots.get(key)
        if not root:
            return False
        for path, unres, raw in ops:
            if unres:
                if norm(root) in ncmd:
                    return True
                if conservative and key in root_vars_named(raw):
                    return True
            elif under(path, root):
                return True
        return False

    writes_any = copy_t + rm_t + [(p, u, r) for _, p, u, r in redir_t]
    trunc_redirect = [(p, u, r) for m, p, u, r in redir_t if m == "truncate"]

    # The game-delete HARD BLOCK is scoped to what is actually catastrophic: the install
    # root itself, or extensions/ wholesale (which destroys every deployed mod). Anything
    # INSIDE the tree falls through to the confirmation, which is the verdict meant for
    # it.
    #
    # MEASURED 2026-08-31 over a 1,000-command corpus sample: all 4 hits of this rule were
    # `rm -rf "$DST"` where DST resolved to extensions/<one mod> -- the documented deploy
    # path, which dev/_tools/deploy.py performs itself. A hard deny there blocks routine
    # work, and it only started happening because variable resolution got BETTER: the old
    # helper could not see through $DST at all. A capability improvement widened a guard
    # nobody re-scoped for it.
    #
    # The name backstop is root-scoped for the same reason. It is the only protection an
    # installation with no configured paths has, so it stays -- but a path merely CONTAINING
    # the game's name is not the install, and the archive exclusion is what removed the
    # measured false positive (7 of 8 were a .zip named after the game).
    def hits_game_root(op):
        g = norm(roots.get("game") or "")
        path, unres, _raw = op
        if not g or unres:
            # An unresolvable operand never reaches the HARD BLOCK. It cannot be
            # PROVEN to be the install root, and a deny the user cannot override is
            # the F93 failure -- it goes to the confirmation below instead.
            return False
        n = norm(path)
        return n == g or n == g + "/extensions"

    # No archive exclusion: GAME_ROOTISH is anchored at $ and so is ARCHIVE, and they
    # demand different endings, so nothing can match both -- PROVEN over probes, and
    # the mutation gate reported the term as unkillable, which is what dead code looks
    # like from the outside. The anchoring subsumes it; the .zip false positive that
    # motivated the exclusion (7 of 8 hits) can no longer reach this line.
    # NB: deliberately does NOT skip unresolved operands, unlike hits_game_root above.
    # The two ask different questions. hits_game_root compares against a CONFIGURED
    # root, and an operand carrying a `$` can never be proven equal to one. This is the
    # NAME backstop -- the only protection an unconfigured machine has -- and there the
    # visible text IS the evidence: `rm -rf "$BUILD/X4 Foundations"` still ends in the
    # game's name. Adding a `not u` filter here (as this line briefly did on
    # 2026-09-01) silently removed that last line of defence, and the 13,041-command
    # corpus could not see it because no historical command has that shape.
    rm_named_game = any(GAME_ROOTISH.search(norm(p)) for p, _u, _ in rm_t)

    search_roots = []
    for c in all_cmds:
        for s, c_cwd in cwd_track(c):
            for p in search_paths(s):
                r = resolve(p, assigns)
                search_roots.append(c_cwd if r in (".", "./") else r)

    def rooted(root):
        return bool(root) and any(is_root(p, root) for p in search_roots)

    # `body` already has heredocs AND comments removed. Deriving these from the raw
    # command left the string-matching rules (git_add_all, sed -i, longjob, the profile
    # search) blind to anything after an apostrophe in a comment -- 1 of the 5 measured
    # bypasses survived the parser fix for exactly this reason, because it read a
    # different string from the one that had been cleaned.
    stripped = body
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

        "rm_hits_game": any(hits_game_root(o) for o in rm_t) or rm_named_game,
        "rm_targets_reference": hit(rm_t, "reference", conservative=True),
        "rm_in_x4_dir": any(hit(rm_t, k, conservative=True) for k in
                            ("game", "profile", "mods", "toolkit")) or rm_named_game,
        "rm_saves": hit(rm_t, "saves", conservative=True),

        "writes_documents": hit(writes_any, "documents"),
        "copy_into_game_or_profile": bool(copy_t) and (
            hit(copy_t, "game") or hit(copy_t, "profile")),
        "redirect_truncate_into_game_or_profile": (
            hit(trunc_redirect, "game") or hit(trunc_redirect, "profile")),

        "sed_i_in_game_or_profile": bool(re.search(r"sed\s+-i", stripped_blank)) and (
            (roots.get("game") and norm(roots["game"]) in ncmd)
            or (roots.get("profile") and norm(roots["profile"]) in ncmd)
            or bool(LEGACY_GAME.search(cmd))),

        # re.M is load-bearing: the bash original used grep, which is LINE based, so `^`
        # matched every line start. Without it this only saw a command whose very first
        # characters were `git add`, and multi-line commands are routine here.
        "git_add_all": bool(re.search(r"(^|[;&|]\s*)git\s+add\s+(-A\b|--all\b|\.\s*$|\.\s*[;&|])",
                                      stripped_blank, re.M)),
        # Matched on the token AS WRITTEN as well as resolved: a durable record is
        # recognised by its filename, which survives either form.
        "durable_truncating_redirect": any(DURABLE.search(p) or DURABLE.search(raw)
                                           for p, _u, raw in trunc_redirect),
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

        # A parser that cannot parse must SAY SO. Checked on the text the rules actually
        # read -- heredoc bodies and comments removed first, because an apostrophe is
        # ordinary English in both and must not raise an alarm there.
        "unparseable_command": ends_open_quote(body),

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

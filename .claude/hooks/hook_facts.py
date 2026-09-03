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

import os
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

# Inside DOUBLE quotes bash treats a backslash as an escape ONLY before these five.
# Before anything else it is a LITERAL backslash -- which is how every Windows path is
# written.
#
# MEASURED 2026-09-01: unescaping unconditionally turned a quoted Windows path into one
# with the separators deleted, so it matched no root and a delete of the game install
# fired NOTHING -- the HARD BLOCK bypassed by the most natural way a Windows user writes
# a path. c400a05 denied it; the parse pass allowed it. Five call sites carried the same
# wrong rule; this constant is the single answer.
_DQ_ESCAPES = "$" + chr(96) + chr(34) + chr(92) + chr(10)


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
            elif (c == chr(92) and q == '"' and i + 1 < len(s)
                  and s[i + 1] in _DQ_ESCAPES):
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


def join_continuations(s: str) -> str:
    """Remove backslash-newline, which bash removes before it does anything else.

    A line continuation is NOT a separator -- the shell splices the two lines into one
    command. `segments()` split on it anyway, because `_scan` reports the escaped
    newline with in_quote False and nothing marks it as ESCAPED. MEASURED 2026-09-02:

        rm -rf \\<NL>  "<game>"   ->  segments ['rm -rf \\', '"<game>"']
                                        verb 'rm' with operand \\, and the
                                        path in a segment of its own with no verb

    So every verb-keyed rule lost its operand at once, including all three hard blocks.
    Found against 6 of 12 fuzz seeds; the other 6 have no whitespace to break at.

    Inside SINGLE quotes it is literal text and is left alone. Inside double quotes bash
    does splice it, so it is removed there too.
    """
    out = []
    q = ""
    i = 0
    while i < len(s):
        c = s[i]
        if q == "'":
            if c == "'":
                q = ""
            out.append(c)
            i += 1
            continue
        if c == chr(92) and i + 1 < len(s) and s[i + 1] == chr(10):
            i += 2                      # the splice: emit neither character
            continue
        if q == '"':
            if c == '"':
                q = ""
            elif c == chr(92) and i + 1 < len(s):
                out.append(c)
                i += 1
                out.append(s[i])
                i += 1
                continue
        elif c in ("'", '"'):
            q = c
        elif c == chr(92) and i + 1 < len(s):
            out.append(c)
            i += 1
            out.append(s[i])
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


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
            elif (c == chr(92) and q == '"' and i + 1 < len(s)
                  and s[i + 1] in _DQ_ESCAPES):
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


#: Shell RESERVED WORDS that can stand immediately before a simple command inside one
#: `;`-delimited segment. MEASURED 2026-09-01 by the syntax-class fuzzer: because the
#: splitter cuts on `;` and `&&`, `if true; then rm -rf <game>; fi` yields the segment
#: `then rm -rf <game>`, whose verb() is `then` -- so EVERY verb-keyed rule missed and
#: the hook fell silent. 90 bypasses over 10 compound forms x 9 seeds, including the
#: three HARD BLOCKS (game root, extensions wholesale, reference tree). The 10th seed
#: was immune because it is redirect-keyed, not verb-keyed, which is what pins the
#: root cause: the operand was always there, the VERB was the keyword.
#:
#: `time`/`nice`/`sudo` are handled separately by WRAPPERS in verb(); this set exists
#: because the keyword has to leave the SEGMENT before any rule looks at it, so that
#: one fix serves every rule instead of each rule learning the grammar.
RESERVED = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until",
            "case", "esac", "in", "for", "select", "function", "!", "{", "}", "coproc", "[[", "]]"}

#: A `case` ARM LABEL, and nothing else. The label is a single glob token --
#: `x)`, `*)`, `*.txt)`, `a|b)` -- so it carries NO WHITESPACE, and that is what makes
#: this safe: every dangerous rule needs an OPERAND, and an operand needs a space, so
#: a spaceless label can never be hiding one.
#:
#: MEASURED 2026-09-01, and it is why the space matters: the first version of this
#: was `^[^()|&;]*\)\s`, which also matched the tail of a PROCESS SUBSTITUTION --
#: `diff <(cd "$GAME" && rm -rf extensions) <(echo b)` splits to `rm -rf extensions)`,
#: the whole thing was eaten as a "label", and the delete went silent. The BASELINE
#: caught that command. A fix for one bypass that opens another is worse than the bug,
#: and only the corpus diff -- 20 commands with a paren-suffixed verb -- surfaced it.
_CASE_ARM = re.compile(r"^[^\s()&;]+\)\s")

#: A function DEFINITION header is not a reserved word, so it survived the first
#: version of this and `f() { rm -rf <game>; }; f` stayed blind while the other nine
#: compound forms were fixed. Both spellings: `f() {` and `function f {`.
_FUNC_HEAD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*\(\)\s*")


def _strip_reserved(s: str) -> str:
    """Drop leading shell reserved words (and a `case` arm label) from a segment.

    Token equality, never a prefix match: a program called `do_thing` or `iffy` keeps
    its name. Stops at the first token that is not reserved, so `for i in 1` becomes
    `i in 1` (harmless -- it holds no command) rather than being consumed whole.
    """
    prev = None
    while s and s != prev:
        prev = s
        head = s.split(None, 1)
        if head and head[0] == "case":
            # `case WORD in LABEL) cmd` -- WORD is not reserved, so a plain keyword loop
            # stops on it and the label rule below never gets to run. Consume through the
            # `in`, and the label rule then removes `LABEL)`.
            rest = head[1] if len(head) > 1 else ""
            toks = rest.split()
            if "in" in toks:
                cut = rest.index("in") + 2
                s = rest[cut:].lstrip()
                continue
            s = rest.lstrip()
            continue
        if head and head[0] == "function":
            # `function NAME {` -- the NAME is not reserved, so drop it with the keyword
            rest = head[1].lstrip() if len(head) > 1 else ""
            nxt = rest.split(None, 1)
            s = (nxt[1].lstrip() if len(nxt) > 1 else "") if nxt else ""
            continue
        if head and head[0] in RESERVED:
            s = head[1].lstrip() if len(head) > 1 else ""
            continue
        m = _FUNC_HEAD.match(s)
        if m:
            s = s[m.end():].lstrip()
            continue
        # `case x in x) rm ...` -- the arm label sits between `in` and the command, and
        # is not a token, so it needs its own step. Only when the `)` is UNQUOTED and no
        # `(` opens before it, or `rm -rf $(echo x)` would be torn apart.
        m = _CASE_ARM.match(s)
        if m:
            marks = list(_scan(s[:m.end()]))
            if not any(inq for _, inq in marks) and not any(
                    ch == "(" for ch, inq in marks if not inq):
                s = s[m.end():].lstrip()
    return s


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
    # LAST: a reserved word left in front of the command makes verb() return the
    # KEYWORD, and every verb-keyed rule then misses. Done here, at the one place every
    # segment passes through, so no rule has to know shell grammar for itself.
    return _strip_reserved(s)


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
            elif (c == chr(92) and q == '"' and i + 1 < len(seg)
                  and seg[i + 1] in _DQ_ESCAPES):
                i += 1
                buf.append(seg[i])
            else:
                buf.append(c)
        elif c in "\"'":
            # ANSI-C / locale quoting: `$'rm'` and `$"rm"` are the word `rm`. The `$`
            # is a quoting SIGIL, not part of the name. Without this the token was
            # `$rm` AND flagged quoted, so verb()'s `if quoted: return t` handed every
            # verb-keyed rule a name no rule has ever heard of -- a total bypass.
            if buf and buf[-1] == "$":
                buf.pop()
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
        # An ARRAY is re-read from the RAW segment, because `tokens()` has already
        # stripped the quotes that hold a spaced path together -- and splitting the
        # de-quoted text gave `C:/Program` as element 0 of a Windows game path. That is
        # a wrong answer rather than a missing one, and a wrong one is compared against
        # the roots and cleared. Overrides the de-quoted value captured above.
        for m in re.finditer(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=\(", seg):
            close = _match_paren(seg, m.end() - 1)
            if close > 0:
                found[m.group(1)] = seg[m.end() - 1:close + 1]
    return found


_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")

#: ANY parameter expansion, not just the two shapes `_VAR` can name. `_VAR` exists to
#: EXTRACT an identifier and only matches `${NAME}` with the brace closing straight
#: after the name -- so `${DST%/}`, `${VAR:-default}`, `${VAR//a/b}` and `${ARR[0]}`
#: matched neither alternative, `has_unresolved` returned False, and the token was
#: treated as a fully-resolved literal path.
#:
#: The DIRECTION is the problem. `hit(..., conservative=True)` exists so an operand
#: the hook cannot resolve still refuses; believing we HAD resolved it skips that
#: branch entirely. MEASURED 2026-09-02: `Z="<game>ZZ"; rm -rf "${Z%ZZ}"` was a
#: silent ALLOW, and 3 expansion mutators weakened every seed they applied to.
#:
#: Separate from `_VAR` on purpose: "is there an expansion here" and "what is it
#: called" are different questions, and one regex answering both is what made the
#: narrow one authoritative.
_EXPANSION = re.compile(r"\$\{|\$[A-Za-z_]|\$[0-9@*#?!$]")


#: `~` and `$HOME` are values a hook genuinely CAN know, unlike `$(...)`. Without them a
#: save delete written the ordinary way was invisible. MEASURED 2026-09-01, E2E through
#: protect-bash.sh, all spellings of the SAME file:
#:      rm -f "C:/Users/.../Egosoft/X4/<id>/save/s.xml.gz"  -> ask
#:      rm -f ~/Documents/Egosoft/X4/<id>/save/s.xml.gz     -> *** SILENT ALLOW ***
#:      rm -f $HOME/Documents/.../save/s.xml.gz             -> *** SILENT ALLOW ***
#: Saves are the one thing here with no backup and no undo, which is why they ask at all.
#: (Every PATH dialect was already handled -- absolute, relative after `cd`, the MSYS
#: `/c/...` form and backslashes all resolved correctly. Only home did not.)
#:
#: Deliberately NOT a name backstop: this resolves the operand to a real path and lets the
#: existing root comparison decide, so it cannot fire on something merely home-shaped.
_HOME = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
_HOME_VARS = ("$HOME", "${HOME}", "$USERPROFILE", "${USERPROFILE}")
_SEPS = ("/", chr(92))


def expand_home(tok: str) -> str:
    """A LEADING `~`, `$HOME` or `$USERPROFILE` becomes the real home directory.

    Leading only: `a~b` and `x/$HOME` are not home references, and rewriting them would
    invent a path the user never wrote.
    """
    if not _HOME:
        return tok
    if tok == "~" or (tok[:1] == "~" and tok[1:2] in _SEPS):
        return _HOME + tok[1:]
    for v in _HOME_VARS:
        if tok == v:
            return _HOME
        if tok.startswith(v) and tok[len(v):len(v) + 1] in _SEPS:
            return _HOME + tok[len(v):]
    return tok


#: `${NAME[idx]<op><word>}` -- the forms `_VAR` cannot name. Restricted to a body with
#: no nested brace, because a nested expansion is not resolvable from text anyway and a
#: greedy match there would swallow the wrong closing brace.
_VAR_OP = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)"
                     r"(\[[0-9]+\])?"
                     r"([#%/:^,+=-][^{}]*)?\}")

#: A pattern carrying any of these is a GLOB, and matching it needs the filesystem
#: semantics this hook deliberately does not have. Such an expansion is left unresolved.
_GLOB_CHARS = set("*?[]")


def _array_elements(value: str) -> list:
    """Elements of an array assignment `(a "b c" d)`, or [] if it is not one."""
    v = value.strip()
    if not (v.startswith("(") and v.endswith(")")):
        return []
    return [t for t, _q in tokens(v[1:-1])]


def _apply_op(name: str, idx, op: str, assigns: dict) -> str:
    """bash's value for one expansion, or None when text alone cannot say.

    Returning None is not a failure -- it routes the token to the conservative path,
    which is the correct answer for `${V%/*}` (a glob) or `${V:2:5}` (an offset).
    """
    known = name in assigns
    value = assigns.get(name, "")
    if idx is not None:
        elems = _array_elements(value)
        n = int(idx[1:-1])
        if not elems or n >= len(elems):
            return None
        value, known = elems[n], True
    elif known:
        elems = _array_elements(value)
        if elems:                      # `A=(x y)` used as plain `$A` is element 0
            value = elems[0]

    if not op:
        return value if known else None

    kind, rest = op[0], op[1:]
    if kind == ":" and rest[:1] in ("-", "=", "+", "?"):
        kind, rest = rest[0], rest[1:]
        known = known and value != ""      # `:-` also treats EMPTY as unset
    if kind in ("-", "="):
        return value if known else rest
    if kind == "+":
        return rest if known else ""
    if kind == "?":
        return value if known else None
    if not known:
        return None
    if kind in ("#", "%"):
        greedy = rest[:1] == kind
        pat = rest[1:] if greedy else rest
        if set(pat) & _GLOB_CHARS or not pat:
            return None
        if kind == "%":
            return value[:-len(pat)] if value.endswith(pat) else value
        return value[len(pat):] if value.startswith(pat) else value
    if kind == "/":
        every = rest[:1] == "/"
        body = rest[1:] if every else rest
        pat, sep, rep = body.partition("/")
        if not pat or set(pat) & _GLOB_CHARS:
            return None
        return value.replace(pat, rep) if every else value.replace(pat, rep, 1)
    return None                            # ^ , : offsets -- not reproducible from text


def resolve(tok: str, assigns: dict[str, str]) -> str:
    """Substitute what this command itself assigned. Text is all a hook can see, so
    this is the most that could ever be resolved."""
    def sub(m):
        name = m.group(1) or m.group(2)
        return assigns.get(name, m.group(0))

    def sub_op(m):
        got = _apply_op(m.group(1), m.group(2), m.group(3) or "", assigns)
        return m.group(0) if got is None else got

    prev = None
    out = tok
    for _ in range(5):                       # bounded: nested vars, never a loop
        prev = out
        out = _VAR_OP.sub(sub_op, _VAR.sub(sub, out))
        if out == prev:
            break
    return expand_home(out)


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
    return bool(_EXPANSION.search(tok) or _SUBST.search(tok))


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
            elif (c == chr(92) and q == '"' and i + 1 < len(s)
                  and s[i + 1] in _DQ_ESCAPES):
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
    line = _blank_arith(line, mask)
    stop = _comment_start(line, mask)
    for i in range(min(len(line) - 1, stop)):
        if line[i] == chr(60) and line[i + 1] == chr(60) and not mask[i] and not mask[i + 1]:
            # A HERE-STRING is not a heredoc. `cat <<< word` feeds one word on stdin and
            # opens no skip region -- but the scan reaches the SECOND `<` of `<<<`, sees
            # `<< word`, and reports a marker. Everything after that line then became
            # "heredoc body" and was invisible to every rule.
            if i > 0 and line[i - 1] == chr(60):
                continue
            if i + 2 < len(line) and line[i + 2] == chr(60):
                continue
            m = _HD.match(line, i)
            if m:
                return m.group(1)
    return None


def _comment_start(line: str, mask: list) -> int:
    """Index of the first UNQUOTED word-initial `#`, or len(line).

    A `#` mid-word is not a comment (`http://x#frag`, `a#b`), and a quoted one is data.
    """
    for i, c in enumerate(line):
        if c == chr(35) and not mask[i] and (i == 0 or line[i - 1] in " 	"):
            return i
    return len(line)


def _blank_arith(line: str, mask: list) -> str:
    """Blank `$(( ... ))` regions. `<<` inside arithmetic is a LEFT SHIFT."""
    if "$((" not in line:
        return line
    out = list(line)
    i = 0
    while i < len(line) - 2:
        if line[i] == "$" and line[i + 1] == "(" and line[i + 2] == "(" and not mask[i]:
            depth, j = 0, i + 1
            while j < len(line):
                if line[j] == "(":
                    depth += 1
                elif line[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            for k in range(i, min(j + 1, len(line))):
                out[k] = " "
            i = j + 1
            continue
        i += 1
    return "".join(out)


def heredoc_bodies(cmd: str) -> list[str]:
    """Bodies whose OPENING LINE runs a SHELL, because a shell executes its heredoc.

    `bash <<SH ... SH` is a command carrier exactly like `bash -c`, and stripping the
    body -- which is correct for the file-payload case -- made it invisible to every
    rule in this file.

    SHELL OPENERS ONLY, and that restriction is load-bearing in BOTH directions:
      * `cat > notes.md <<X ... X` is a file being WRITTEN. Its body is data, it is
        pinned as not-a-delete by test_hook_facts, and routing it would hard-deny
        writing documentation that happens to quote a dangerous command.
      * `python - <<PY ... PY` is PYTHON. A line such as an assignment of a path to a
        name would parse as a delete verb under a shell tokeniser, so routing it would
        invent deletes out of assignments. Python writes have their own rule already.
    """
    out, cur, term, opener = [], None, None, ""
    for line in cmd.split(chr(10)):
        if cur is not None:
            if line.strip() == term or line.strip() == term + ";":
                # ANY segment of the opener, not just the first. The opener is a
                # pipeline: for `cat <<EOF | bash` the first verb is `cat`, so asking
                # only that one stripped the body as file payload and the shell on the
                # other end of the pipe ran it unseen.
                if any(verb(_unwrap(sg)) in _SHELL_SINKS for sg in segments(opener)):
                    out.append(chr(10).join(cur))
                cur, term, opener = None, None, ""
            else:
                cur.append(line)
            continue
        t = heredoc_marker(line)
        if t:
            term, cur, opener = t, [], line
    if cur is not None and any(verb(_unwrap(sg)) in _SHELL_SINKS
                              for sg in segments(opener)):
        out.append(chr(10).join(cur))   # unterminated: still what the shell would run
    return out


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
    return out


# --------------------------------------------------------------------- verbs
#: Programs that RUN ANOTHER PROGRAM named in their arguments. Every one of these in
#: front of a command made verb() return the wrapper, so no verb-keyed rule fired.
#: MEASURED 2026-09-02, E2E, each against a game-root delete the guard catches bare:
#:      timeout 5 rm -rf <game>  -> ALLOW      exec rm -rf <game>    -> ALLOW
#:      setsid rm -rf <game>     -> ALLOW
#: `timeout` is doubly important: CLAUDE.md #25 recommends it, so it is a prefix this
#: workspace types on purpose.
WRAPPERS = {"time", "nice", "env", "sudo", "xargs", "command", "nohup", "stdbuf",
            "exec", "timeout", "setsid", "ionice", "builtin", "doas", "chronic",
            "unbuffer", "ltrace", "strace", "proxychains", "catchsegv"}

#: A token that cannot be a command NAME. Only consulted AFTER a wrapper has been
#: seen, where a bare value is an argument to that wrapper rather than the command:
#: `timeout 5 rm ...` gave verb `5`, and `xargs -I {} rm ...` gave verb `{}`.
_WRAPPER_ARG = re.compile(r"^(\d+(\.\d+)?[smhd]?|\{\}|\+)$")


def _verb_name(t: str) -> str:
    """The command NAME carried by a verb token: basename, minus a `.exe` suffix.

    `/bin/rm`, `C:/Windows/System32/cmd.exe` and `rm.exe` are the same commands as
    `rm` and `cmd`, and every verb-keyed rule compared the token VERBATIM -- so any
    absolute or suffixed spelling walked past all of them at once.

    norm() runs FIRST and is not optional: it folds backslashes to `/` and lowercases,
    and posixpath.basename does NOT split on a backslash, so without it a Windows-style
    path yields the whole string back as one "name".

    Only `.exe` is stripped, and only as a whole suffix. A general extension strip is
    UNSAFE -- test_hook_facts.py pins `done_marker.sh`, `function_helper.py` and
    `casefold.py` by exact equality, because those ARE the command names.
    """
    if not t:
        return t
    n = posixpath.basename(norm(t))
    if n.endswith(".exe"):
        n = n[:-4]
    return n or t


def verb(seg: str) -> str:
    """The command actually being run, seeing through env-assignment prefixes and
    wrappers. `write_targets` required the verb to be the segment's FIRST word, so
    `echo x | sudo tee <docs>/n.txt` and `time cp ...` lost their destination.

    The name is NORMALISED (see _verb_name): every caller compares it against a bare
    command name, and none of the twelve echoes it back to the user, so normalising
    here fixes all of them at once rather than at each comparison site.
    """
    seen_wrapper = False
    for t, quoted in tokens(seg):
        if quoted:
            return _verb_name(t)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            continue
        if _verb_name(t) in WRAPPERS:
            seen_wrapper = True
            continue
        if t.startswith("-"):
            continue
        if seen_wrapper and _WRAPPER_ARG.match(t):
            continue                    # a duration or a placeholder, not a command
        return _verb_name(t)
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


#: A find carrying any of these is SCOPED to matching entries, not the whole tree.
_FIND_FILTERS = {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename",
                 "-regex", "-iregex", "-samefile", "-newer", "-size", "-user", "-group"}


#: Patterns that match everything, so a filter carrying one narrows nothing.
_UNIVERSAL = {"*", "**", "*.*", ".*", "?*", "*/*", ""}


def _narrows(toks: list, i: int) -> bool:
    """True when the filter at index `i` genuinely restricts the match set."""
    arg = toks[i + 1] if i + 1 < len(toks) else ""
    return arg not in _UNIVERSAL


def find_deletes(seg: str) -> list:
    """Paths a `find` would delete. `find <root> -delete` and `find <root> -exec rm ...`
    remove files just as surely as rm does, and DELETE_VERBS knew neither.

    MEASURED 2026-09-01 over 13,277 historical commands: `-delete` appears 4 times (none
    on a protected root) and `-exec rm` 0 times. So this is a 0-incidence gap -- fixed
    because the failure mode is an unguarded delete of the game install, not because it
    was observed. Recording the denominator is the point: a finding with no incidence
    over-ranks by construction (F90).
    """
    if verb(seg) != "find":
        return []
    toks = [t for t, q in tokens(seg)]
    # A find NARROWED by a name/path filter deletes matching entries, not the tree. That
    # distinction is the whole rule: `find <game> -delete` removes the install, while
    # `find . -name __pycache__ -exec rm -rf {} +` is routine hygiene. MEASURED
    # 2026-09-01: treating both alike added 40 prompts across 13,282 commands, every one
    # a __pycache__ cleanup -- noise by this project's own standard, since a prompt must
    # be reserved for what is genuinely the user's decision.
    # A filter only NARROWS if its pattern excludes something. `-name` with a
    # universal glob matches every entry, so `find <game> -name "*" -delete` is a
    # whole-tree delete wearing a filter's clothing -- and it was exempted by the
    # very rule that exists to allow genuinely-scoped cleanups.
    if any(_narrows(toks, i) for i, t in enumerate(toks) if t in _FIND_FILTERS):
        return []
    deletes = "-delete" in toks
    if not deletes:
        for i, t in enumerate(toks):
            if t == "-exec" and i + 1 < len(toks) and toks[i + 1] in DELETE_VERBS:
                deletes = True
                break
    if not deletes:
        return []
    # find's PATHS are the operands before the first predicate (a `-flag`).
    out = []
    for t, quoted in tokens(seg)[1:]:
        if not quoted and t.startswith("-"):
            break
        out.append(t)
    return out


def rm_paths(seg: str) -> list[str]:
    if verb(seg) in DELETE_VERBS:
        return _operands(seg)
    return find_deletes(seg)


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


def search_paths(seg: str, require_recursive: bool = True) -> list[str]:
    """Paths a search runs over. The first non-flag operand is the PATTERN -- unless
    -e/-f supplied it, in which case every remaining operand is a path.

    `require_recursive=False` gives the file operands of a NON-recursive search too.
    The profile rule needs those (grepping a manifest by name is not recursive) and
    used to reach for the raw command text instead, which is what made it fire on a
    grep of a local file that merely sat beside a mention of the profile. One
    implementation of the pattern-vs-file logic, two callers."""
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
    if require_recursive and not recursive:
        return []
    return ops if pattern_given else ops[1:]


DIR_VERBS = {"cd", "pushd"}




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
    #: The directory is what every later RELATIVE operand is judged against, so an
    #: operand read as literal text here disarms the path rules for the rest of the
    #: command -- `cd "$FZ" && rm -rf extensions` walked through a hard block on that.
    #: Every other rule resolves before matching; this one did not.
    assigns = assignments(cmd)
    for seg in segments(cmd):
        out.append((seg, cwd))
        v = verb(seg)
        if v in DIR_VERBS:
            ops = _operands(seg)
            if ops:
                if v == "pushd":
                    stack.append(cwd)
                # `cd -` returns somewhere this hook cannot know; refuse to guess.
                if ops[0] == "-":
                    cwd = ""
                else:
                    # RESOLVED, then joined exactly as before. Blanking the directory
                    # when the target stays unresolved looks more careful and is not:
                    # MEASURED 2026-09-02, `cd <game> && cd "$NOPE" && rm -rf extensions`
                    # went deny -> allow under that rule, because the sticky join keeps
                    # the operand under the root we last knew about. Leaving the join
                    # alone makes this change a pure tightening.
                    cwd = join_cwd(cwd, resolve(ops[0], assigns))
        elif v == "popd" and stack:
            cwd = stack.pop()
    return out


# ------------------------------------------------- rules that were raw-string regexes
# Each ANDed two independent predicates over the WHOLE command text, so it fired when
# both merely APPEARED anywhere -- and missed when the real invocation did not match the
# regex's assumed shape. MEASURED 2026-09-01, both directions on the same four rules:
#   FALSE POSITIVES  an in-place edit of a local file with the game named in a COMMENT
#                    a grep whose PATTERN mentions the shared temp dir
#                    a grep of a local file beside a cat of a profile manifest
#   BYPASSES (found by scripts/fuzz-guard.py, which mutates only surrounding syntax)
#                    `( git add -A )` and `PYTHONIOENCODING=utf-8 git add -A` -> allow
# Same root cause in both directions, so one fix: ask the parser which VERB runs and
# what its OPERANDS are, instead of searching the text.

GIT_ADD_ALL = {"-A", "--all", "."}


def git_adds_everything(seg):
    """`git add -A|--all|.` -- seen through a subshell, an env prefix, a wrapper and
    `git -C <path> add`, none of which the old anchored regex allowed."""
    if verb(seg) != "git":
        return False
    toks = [t for t, _q in tokens(seg)]
    if "add" not in toks:
        return False
    return any(t in GIT_ADD_ALL for t in toks[toks.index("add") + 1:])


def sed_in_place_targets(seg):
    """Paths an in-place `sed` would rewrite. `-i` may carry a suffix (`-i.bak`). The
    first operand is the SCRIPT, not a file -- but a script never resolves under a root,
    so keeping it costs nothing while dropping it would need -e/-f handling."""
    if verb(seg) not in ("sed", "gsed"):
        return []
    inplace = any((not q) and (t.startswith("-i") or t.startswith("--in-place"))
                  for t, q in tokens(seg))
    return _operands(seg) if inplace else []


_OUT_FLAGS = ("-o", "--output")


def output_targets(seg):
    """Files a command writes via an explicit output flag: `-o PATH`, `--output PATH`,
    `--output=PATH`. Kept deliberately: scoping the shared-temp rule to redirects alone
    would silently stop covering a download written with an output flag, which the old
    regex did cover."""
    out, toks, i = [], tokens(seg), 0
    while i < len(toks):
        t, q = toks[i]
        if (not q) and t in _OUT_FLAGS and i + 1 < len(toks):
            out.append(toks[i + 1][0])
            i += 2
            continue
        if (not q) and t.startswith("--output="):
            out.append(t.split("=", 1)[1])
        i += 1
    return out


SEARCH_NAMES = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "findstr", "select-string"}


def searches(seg):
    return verb(seg).lower() in SEARCH_NAMES


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




def _quote_kinds(s: str) -> list:
    """The quote character in force at each index ("" when unquoted).

    _quote_mask answers "is this quoted", which is not enough here: inside DOUBLE
    quotes a command substitution still runs, inside SINGLE quotes it is literal text.
    """
    kinds = [""] * len(s)
    q = ""
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            kinds[i] = q
            if c == q:
                q = ""
            elif (c == chr(92) and q == chr(34) and i + 1 < len(s)
                  and s[i + 1] in _DQ_ESCAPES):
                kinds[i + 1] = q
                i += 1
        elif c in (chr(34), chr(39)):
            q = c
            kinds[i] = c
        i += 1
    return kinds


def _match_paren(s: str, start: int) -> int:
    """Index of the paren closing the one at `start`, or -1."""
    depth = 0
    for j in range(start, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return j
    return -1


def substitutions(cmd: str) -> list[str]:
    """Command text inside a substitution: dollar-paren, backticks, and process
    substitution.

    Every one of these RUNS its contents, and the parse pass treated all of them as
    ordinary text -- so wrapping a command in three characters walked past every rule
    at once. MEASURED 2026-09-02, each against a game-root delete the guard catches
    when written bare: all three returned a silent ALLOW. This file already admitted
    that "precision about operands bought blindness to indirection", about the
    dollar-paren form alone; the CLASS was never enumerated.

    Single-quoted regions are skipped: there the text is literal and nothing runs.
    A doubled open paren is ARITHMETIC, not a subshell, and is stepped over.
    """
    out = []
    kinds = _quote_kinds(cmd)
    i = 0
    while i < len(cmd):
        k = kinds[i]
        c = cmd[i]
        if k == chr(39):                        # single-quoted: literal
            i += 1
            continue
        if c == "$" and i + 1 < len(cmd) and cmd[i + 1] == "(":
            if i + 2 < len(cmd) and cmd[i + 2] == "(":
                end = _match_paren(cmd, i + 1)
                i = (end + 1) if end != -1 else i + 3
                continue                        # arithmetic, not a command
            end = _match_paren(cmd, i + 1)
            if end != -1:
                out.append(cmd[i + 2:end])
                i = i + 2
                continue
        elif c in ("<", ">") and i + 1 < len(cmd) and cmd[i + 1] == "(" and k == "":
            end = _match_paren(cmd, i + 1)
            if end != -1:
                out.append(cmd[i + 2:end])
                i = i + 2
                continue
        elif c == chr(96):
            end = cmd.find(chr(96), i + 1)
            if end != -1:
                out.append(cmd[i + 1:end])
                i = end + 1
                continue
        i += 1
    return [o for o in out if o.strip()]


#: Shells whose `-c` argument is a command string. `dash`/`ksh` cost nothing to add and
#: a missing one is a total bypass.
_SHELLS = ("bash", "sh", "zsh", "dash", "ksh")

#: A SHORT-FLAG CLUSTER containing `c`. Not the literal token `-c`: real invocations
#: combine flags, and `bash -lc '<cmd>'` is the ordinary way to get a login shell.
#: MEASURED 2026-09-01, E2E through protect-bash.sh, against a game-root `rm -rf` the
#: guard denies on its own:
#:      sh -c '<rm>'      -> deny        bash -lc '<rm>'  -> *** SILENT ALLOW ***
#:      xargs ... '<rm>'  -> deny        eval '<rm>'      -> *** SILENT ALLOW ***
#: One character of flag clustering, and the hard block was gone.
_DASH_C = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")


#: Verbs that RUN what arrives on stdin. `source` and `.` re-run a file or stream in
#: the CURRENT shell, which is the same thing for our purposes.
_SHELL_SINKS = tuple(_SHELLS) + ("source", ".")


def _reads_stdin_program(seg: str) -> bool:
    """A shell with no script to run, so its program can only come from stdin.

    Deliberately narrow. `bash script.sh` and `bash -c '...'` both have somewhere else
    to get their program, and pairing those with a nearby `echo` would invent a command
    the user never piped -- a false DENIAL, which is worse here than a miss.
    """
    toks = [t for t, _q in tokens(seg)]
    if not toks or _verb_name(toks[0]) not in _SHELL_SINKS:
        return False
    rest = _drop_redirects(toks[1:])
    for t in rest:
        if _DASH_C.match(t):
            return False                       # -c carries its own program
        if not t.startswith("-"):
            return False                       # a script file, or /dev/stdin's operand
    return True


#: Redirect operators that CONSUME the following word. A redirect is not an operand, and
#: reading one as a script file is what kept `bash <<< '<cmd>'` an ALLOW after the rest of
#: C2 was fixed -- the here-string is the program, so the single carrier whose payload is
#: plainly visible in the command text was the one we declined to inspect.
_REDIR_WORD = ("<<<", "<", ">", ">>", "<>", ">|", "<<", "<<-")


def _drop_redirects(toks: list[str]) -> list[str]:
    """Tokens with redirect operators and the words they consume removed.

    Handles both spellings: separated (`<<< payload`) and attached (`<<<payload`,
    `>file`), plus an fd prefix (`2>err`, `1>&2`). Deliberately syntactic only -- it
    answers "is this token an operand", never "where does the data go".
    """
    out = []
    i = 0
    while i < len(toks):
        t = toks[i]
        core = t.lstrip("0123456789")          # an fd prefix: 2>err, 1>&2
        hit = ""
        for op in _REDIR_WORD:                 # longest first, so <<< beats <<
            if core.startswith(op) and len(op) > len(hit):
                hit = op
        if hit:
            if core == hit:
                i += 2                         # `<<< payload` -- the word is consumed
            else:
                i += 1                         # `<<<payload` -- attached, nothing follows
            continue
        out.append(t)
        i += 1
    return out


def _here_string(seg: str) -> str:
    """The operand of a `<<<` here-string, or ''."""
    toks = [t for t, _q in tokens(seg)]
    for i, t in enumerate(toks):
        if t == "<<<" and i + 1 < len(toks):
            return toks[i + 1]
        if t.startswith("<<<") and len(t) > 3:
            return t[3:]
    return ""


def _inner_commands(cmd: str) -> list[str]:
    """Command strings hidden inside a wrapper, so the rules see them too.

    Two carriers: a shell's `-c` argument, and `eval`. Both take TEXT and run it as a
    command, so anything they carry is invisible to every rule that inspects segments.
    """
    out = []
    segs = segments(cmd)
    for n, seg in enumerate(segs):
        # `echo '<cmd>' | bash` and `printf '%s' '<cmd>' | sh`. The consumer must have
        # NO script operand (see _reads_stdin_program) and the producer must be an echo
        # or printf of a literal, so an ordinary `echo ... > file && bash script.sh`
        # cannot pair by accident.
        if n and _reads_stdin_program(seg):
            prev = segs[n - 1]
            if verb(prev) in ("echo", "printf"):
                lit = [t for t, q in tokens(prev)[1:] if q and not t.startswith("-")]
                for piece in lit:
                    if piece.strip() and piece not in ("%s", "%s" + chr(92) + "n"):
                        out.append(piece)
        # `bash <<< '<cmd>'` -- the here-string IS the program. A SEPARATE `if`, not an
        # arm of the chain below: this lived as an `elif` for one measurement and never
        # ran, because `bash` matches the `-c` arm first and that arm appends nothing when
        # there is no `-c`. A shell can be handed a program by `-c` AND on stdin in the
        # same command, so they were never alternatives to begin with.
        if _reads_stdin_program(seg):
            hs = _here_string(seg)
            if hs:
                out.append(hs)
        v = verb(seg)
        toks = tokens(seg)
        if v in _SHELLS:
            for i, (t, quoted) in enumerate(toks):
                if not quoted and _DASH_C.match(t) and i + 1 < len(toks):
                    out.append(toks[i + 1][0])
                    break
        elif v == "eval":
            # `eval` concatenates its arguments and runs the result.
            #
            # Sliced from AFTER THE `eval` TOKEN, never from toks[1:]. `eval` is not
            # necessarily token 0 -- a wrapper can precede it -- and `time eval <cmd>`
            # then produced the string "eval <cmd>", whose own verb is `eval`, so no
            # delete rule fired on that either. Matching on the NAME rather than the
            # token also picks up an absolute spelling, which verb() now normalises.
            k = next((i for i, (t, _) in enumerate(toks)
                      if _verb_name(t) == "eval"), 0)
            parts = [t for t, _ in toks[k + 1:] if not t.startswith("-")]
            if parts:
                out.append(" ".join(parts))
        elif v == "trap":
            # `trap <cmd> <SIGNAL...>` runs its first operand as a command when the
            # signal fires. That operand is normally single-quoted, which is exactly
            # why nothing saw it: quoted text is data everywhere else in this file.
            k = next((i for i, (t, _) in enumerate(toks)
                      if _verb_name(t) == "trap"), 0)
            rest = [t for t, _ in toks[k + 1:] if not t.startswith("-")]
            if rest:
                out.append(rest[0])
    return out


#: How many times a carrier may nest before the walk stops. `bash -c` inside
#: `bash -c` inside a substitution is three levels, and each is a real construct
#: someone can type; beyond that the shape is pathological rather than plausible.
#: Bounded because this runs on the BLOCKING PreToolUse path -- an unbounded walk
#: over an adversarial string is a hang, and a hang here stops the session.
_MAX_CARRIER_DEPTH = 4

#: A hard ceiling on how many command strings the walk will produce, whatever their
#: shape. _MAX_CARRIER_DEPTH does NOT bound this on its own: substitutions() descends
#: into nested `$( )` inside a single pass, so one call already flattens the whole
#: tree. MEASURED with unique text at every level (so dedup cannot collapse it):
#: a 128 KB command yielded 9,841 carried commands and 4.1 s in facts(), on the
#: BLOCKING PreToolUse path.
#:
#: MEASURED over all 13,503 real historical commands: max carried = 25, p99 = 5,
#: p50 = 1, and ZERO commands exceed 50. So 250 is 10x the observed maximum -- it is
#: unreachable by ordinary work, and it bounds the adversarial case well under a second.
#: (An earlier draft of this comment guessed "~180x" and was wrong; the census is the
#: only reason the number in it is now true.)
_MAX_CARRIED = 250


def carried_commands(body: str, extra: list) -> tuple:
    """Every command string reachable from `body`, following carriers.

    _inner_commands was applied EXACTLY ONCE, to the top level, so a command one
    level further in was invisible: `bash -c 'sh -c "<cmd>"'` reached no rule. It
    also took only the FIRST `-c` per segment.

    Deduplicated, because two carriers can yield the same text and the rules below
    are pure functions of it -- re-running them buys nothing and costs latency on
    the blocking path.
    """
    seen = {body}
    out = [body]
    frontier = [body]
    truncated = False
    for e in extra:
        if e not in seen:
            seen.add(e)
            out.append(e)
            frontier.append(e)
    for _ in range(_MAX_CARRIER_DEPTH):
        nxt = []
        for c in frontier:
            for inner in _inner_commands(c) + substitutions(c):
                if inner and inner not in seen:
                    seen.add(inner)
                    nxt.append(inner)
                    if len(out) + len(nxt) >= _MAX_CARRIED:
                        # STOP, and SAY SO. Dropping the rest and returning a verdict
                        # would be a step that narrows its data and reports success --
                        # the shape behind every tool defect found in this workspace.
                        out.extend(nxt)
                        return out[:_MAX_CARRIED], True
        if not nxt:
            break
        out.extend(nxt)
        frontier = nxt
    return out, truncated


def _ipc_value(key: str, v) -> str:
    """One field of the `key<TAB>value` stream, with no way to forge another field.

    protect-bash.sh splits the stream at the FIRST sentinel, and `on()` matches
    "<NL>key<TAB>1<NL>" ANYWHERE in what precedes it. So any value carrying a newline
    can invent a fact that no rule ever computed -- and two of the values are not
    booleans this file produced: `timeout` and `run_in_background` are passed straight
    through from the caller's payload.

    Not reachable through the documented schema, where both are a number and a bool.
    This is defence in depth, on exactly the reasoning that already justifies `_as_ms`
    accepting a value "whatever shape it arrived in": a schema describes intent, it
    does not guarantee bytes.
    """
    if isinstance(v, bool):
        return "1" if v else "0"
    if key == "timeout":
        return str(int(_as_ms(v)))          # a number, always
    # Anything else stays on ONE field of ONE line.
    return str(v).replace(chr(13), " ").replace(chr(10), " ").replace(chr(9), " ")


def _as_ms(v) -> float:
    """A timeout in milliseconds, whatever shape it arrived in. Unparseable -> 0, which
    keeps the rule off rather than firing on nonsense."""
    if isinstance(v, bool) or v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0


def facts(payload: dict, roots: dict) -> dict:
    inp = payload.get("tool_input") or {}
    cmd = inp.get("command") or ""
    timeout = inp.get("timeout", 0)
    background = inp.get("run_in_background", False)

    # PARSE THE COMMANDS, NOT THE PROSE. Heredoc bodies are data (a body line reading
    # `rm -rf <game>` is text being written, and used to hard-deny), and a `#` comment is
    # not a command at all -- while an apostrophe inside one blinded every rule after it.
    # Line continuations FIRST: bash splices them before it parses anything, and
    # treating one as a separator cost every verb-keyed rule its operand (C1).
    spliced = join_continuations(cmd)
    body = strip_comments(strip_heredocs(spliced))
    # Heredoc bodies come from the RAW command: strip_heredocs has already removed
    # them from `body`, and only the ones opened by a shell are commands at all.
    all_cmds, carriers_truncated = carried_commands(
        body, [strip_comments(h) for h in heredoc_bodies(spliced)])
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
    sed_t, out_t, search_files = [], [], []
    search_seg, git_all = False, False
    for s, c_cwd in seg_cwd:
        rm_t += prep(rm_paths(s), c_cwd)
        copy_t += prep(copy_dests(s), c_cwd)
        sed_t += prep(sed_in_place_targets(s), c_cwd)
        out_t += prep(output_targets(s), c_cwd)
        search_files += prep(search_paths(s, require_recursive=False), c_cwd)
        search_seg = search_seg or searches(s)
        git_all = git_all or git_adds_everything(s)
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

    redir_t_all = [(p, u, r) for _m, p, u, r in redir_t]
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
    # `p or raw`, and the fallback is the whole point. prep() stores
    # join_cwd(cwd, resolved) in element 0, and join_cwd returns "" whenever the
    # operand is RELATIVE and the shell's directory is unknowable -- which is correct
    # for the path rules (inventing a root there would fire on unrelated work) but
    # silently disarms the NAME backstop, whose entire job is the operand that bears
    # the game's name WITHOUT being a resolvable path.
    #
    # MEASURED 2026-09-02: `rm -rf "X4 Foundations"` and `cd sub && rm -rf "X4
    # Foundations"` both read False, while the same delete after a cd to an ABSOLUTE
    # directory read True. The backstop was working only in the case it was least
    # needed.
    rm_named_game = any(GAME_ROOTISH.search(norm(p or raw)) for p, _u, raw in rm_t)

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

        # A command too tangled to analyse IN FULL is not a clean pass. The carrier
        # walk is bounded (see _MAX_CARRIED); when that bound is hit, some command
        # text reached no rule, and saying nothing would be a step that narrows its
        # data and reports success. Unreachable by ordinary work: MEASURED over
        # 13,503 real commands, the largest walk produced 25 of the 250 allowed.
        "carriers_truncated": carriers_truncated,

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

        # The FILE sed rewrites must be under a root. Was: the text "sed -i" anywhere
        # AND a root named anywhere -- so editing a local file while a comment happened
        # to mention the game was a non-overridable DENY.
        "sed_i_in_game_or_profile": (hit(sed_t, "game") or hit(sed_t, "profile")
                                     or any((not u) and LEGACY_GAME.search(pp)
                                            for pp, u, _r in sed_t)),

        # re.M is load-bearing: the bash original used grep, which is LINE based, so `^`
        # matched every line start. Without it this only saw a command whose very first
        # characters were `git add`, and multi-line commands are routine here.
        # Parsed, not matched. The old anchor required `git` to begin a segment, so a
        # subshell wrap and an env-assignment prefix both slipped past it -- found by
        # scripts/fuzz-guard.py, not by any hand-written test.
        "git_add_all": git_all,
        # Matched on the token AS WRITTEN as well as resolved: a durable record is
        # recognised by its filename, which survives either form.
        "durable_truncating_redirect": any(DURABLE.search(p) or DURABLE.search(raw)
                                           for p, _u, raw in trunc_redirect),
        "durable_python_open_w": bool(DURABLE.search(cmd)) and bool(
            re.search(r"open\([^)]*,\s*[\"']w[\"']", cmd)),

        "search_rooted_reference": rooted(roots.get("reference")),
        "search_rooted_workspace": any(rooted(roots.get(k)) for k in
                                       ("toolkit", "game", "mods")),
        # The SEARCHED PATH must be the profile. Was: any search verb anywhere AND the
        # profile named anywhere AND "content" anywhere -- so a grep of a local file
        # beside an unrelated cat of the manifest was a DENY.
        "profile_search_by_name": (
            search_seg
            # An operand naming the profile ENV VAR is the profile, even though its
            # text never contains the path -- the same evidence the delete rules use.
            # Without this, the env-var form was lost when the rule stopped matching
            # raw command text.
            and any("content" in norm(_r) and (
                        ("profile" in root_vars_named(_r))
                        or (roots.get("profile") and (not u)
                            and under(pp, roots["profile"])))
                    for pp, u, _r in search_files)
            and not re.search(r"ws_[0-9]{4,}", cmd)),

        "dollarq_after_pipe": dollarq_after_pipe(cmd),
        # A redirect or output-flag TARGET under the shared temp dir. Was a raw regex
        # with no heredoc strip and no quote blanking, so it fired on a grep PATTERN, on
        # quoted prose and on heredoc bodies -- while its message tells you to use the
        # scratchpad. It denied three of this session's own analysis commands.
        "write_to_tmp": any(under(pp, "/tmp") for pp, u, _r in redir_t_all + out_t
                            if not u),
        # A JSON number can be a float, and a client may send a string. The old
        # isinstance(int) turned the rule OFF for both -- silently, which is the
        # wrong direction for a cap. MEASURED: 0 of 13,277 historical calls used
        # anything but int, so this is robustness, not an observed bug.
        # `bool` is excluded deliberately: in Python True is an int.
        "timeout_over_cap": _as_ms(timeout) > 600000,
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
        out.append(k + "\t" + _ipc_value(k, v))
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

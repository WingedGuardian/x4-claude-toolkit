#!/usr/bin/env python3
"""Record what Codex's OWN apply_patch does with every patch shape in SHAPES (R2-F1, v4.0.0).

    python scripts/capture-codex-patch-oracle.py [--codex PATH] [--out FILE]

For each shape it builds a fresh scratch folder (a.txt, b.txt and victim.txt), runs
`codex --codex-run-as-apply-patch <patch>` there -- Codex's real parser and applier, offline, no
model and no quota -- and records the exit code, the first stderr line and every file that changed
(added, removed or rewritten). tests/test_patch_paths.py then holds the guard's parser to that
record: a patch Codex would apply must name every file Codex touched, and a patch Codex refused to
PARSE must be refused by the guard too. Re-run it on a Codex upgrade and commit the diff.

Default output: tools/x4validate/tests/fixtures/codex/<version>/patch_grammar_oracle.json.
The record holds no machine paths: the patches are relative and the scratch folder is never
written into it. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
B, E = "*** Begin Patch", "*** End Patch"
ADD = "*** Add File: h.txt\n+hi"
UPD = "*** Update File: a.txt\n@@\n-x\n+y"
DEL = "*** Delete File: victim.txt"


def f(*lines: str) -> str:
    """File content: one newline-terminated line per argument."""
    return "".join(x + "\n" for x in lines)


def p(*body: str) -> str:
    return "\n".join((B,) + body + (E,))


#: Every header kind x every position x every prefix shape. A new shape goes here, never only in
#: the test: the test reads this record and holds the parser to it.
SHAPES: dict[str, "str | tuple[str, dict[str, str]]"] = {
    # controls -- flush headers in every position
    "flush-add": p(ADD),
    "flush-update": p(UPD),
    "flush-delete": p(DEL),
    "flush-move": p("*** Update File: a.txt", "*** Move to: moved.txt", "@@", "-x", "+y"),
    "flush-multi": p(ADD, UPD, DEL),
    "flush-delete-after-add": p(ADD, DEL),
    "flush-delete-after-update": p(UPD, DEL),
    "flush-delete-after-delete": p("*** Delete File: b.txt", DEL),
    "flush-delete-after-eof": p(UPD, "*** End of File", DEL),
    "update-no-at-at": p("*** Update File: a.txt", "-x", "+y"),
    "update-two-chunks": (p("*** Update File: a.txt", "@@", "-x", "+y", "@@", "-q", "+r"), {"a.txt": f("x", "q")}),
    # R2-F1: an INDENTED header, after each kind of hunk
    "indented-after-add": p(ADD, "  " + DEL),
    "tab-indented-after-add": p(ADD, "\t" + DEL),
    "indented-first": p("   " + DEL),
    "indented-first-add": p("  " + ADD),
    "indented-after-delete": p("*** Delete File: b.txt", "  " + DEL),
    # an indented "header" inside an Update is a CONTEXT line: a.txt holds that line, so Codex
    # applies the patch and the record shows exactly which file it touched
    "indented-after-update": (p(UPD, "  " + DEL), {"a.txt": f("x", " " + DEL)}),
    "indented1-after-update": (p(UPD, " " + DEL), {"a.txt": f("x", DEL)}),
    "indented-after-eof": p(UPD, "*** End of File", "  " + DEL),
    "indented-add-after-update": (p(UPD, "  *** Add File: moved.txt", "+z"), {"a.txt": f("x", " *** Add File: moved.txt")}),
    "indented-move": (p("*** Update File: a.txt", "  *** Move to: moved.txt", "@@", "-x", "+y"),
                      {"a.txt": f(" *** Move to: moved.txt", "x")}),
    "indented-eof": (p(UPD, "  *** End of File"), {"a.txt": f("x", " *** End of File")}),
    "indented-update-after-add": p(ADD, "  *** Update File: a.txt", "@@", "-x", "+y"),
    "vt-indented-after-add": p(ADD, "\x0b" + DEL),
    "ff-indented-after-add": p(ADD, "\x0c" + DEL),
    "nbsp-indented-after-add": p(ADD, "\xa0" + DEL),
    "ideo-indented-after-add": p(ADD, "　" + DEL),
    "fs-indented-after-add": p(ADD, "\x1c" + DEL),          # whitespace to Python, not to Rust
    # header spelling
    "lowercase": p("*** delete file: victim.txt"),
    "nospace-after-stars": p("***Delete File: victim.txt"),
    "nospace-after-colon": p("*** Delete File:victim.txt"),
    "two-spaces-after-colon": (p("*** Delete File:  victim.txt"), {" victim.txt": f("keep")}),
    "double-space-in-name": p("***  Delete File: victim.txt"),
    "trailing-ws-header": p(UPD, DEL + "  "),
    "move-nospace": p("*** Update File: a.txt", "*** Move to:moved.txt", "@@", "-x", "+y"),
    "eof-trailing-ws": p(UPD, "*** End of File  "),
    "unknown-header": p("*** Rename File: victim.txt"),
    # hunk bodies
    "add-bare-content": p("*** Add File: h.txt", "hi"),
    "add-then-blank-then-delete": p(ADD, "", DEL),
    "update-then-blank-then-delete": p(UPD, "", DEL),
    "delete-then-plus-line": p(DEL, "+junk"),
    "update-empty": p("*** Update File: a.txt", DEL),
    "content-before-header": p("+x", DEL),
    "add-content-header-text": p("*** Add File: h.txt", "+*** Delete File: victim.txt"),
    "update-context-header-text": p("*** Update File: a.txt", "@@", " x", "+*** Delete File: victim.txt"),
    "move-twice": p("*** Update File: a.txt", "*** Move to: moved.txt", "*** Move to: b.txt", "@@", "-x", "+y"),
    "move-without-update": p("*** Move to: moved.txt"),
    # envelope
    "begin-indented": "  " + p(DEL),
    "end-indented": p(DEL)[: -len(E)] + "  " + E,
    "second-begin-inside": p(ADD, B, DEL),
    "indented-end-inside": p(ADD, "  " + E, DEL),
    "text-after-end": p(DEL) + "\n*** Delete File: b.txt",
    "junk-before-begin": "junk\n" + p(DEL),
    "crlf": p(ADD, DEL).replace("\n", "\r\n"),
    "empty-patch": p(),
    "heredoc-wrapped": "<<'EOF'\n" + p(DEL) + "\nEOF",
    "heredoc-wrapped-bare": "<<EOF\n" + p(DEL) + "\nEOF",
    # read from the 0.160.0 streaming parser: these pin its less obvious branches
    "environment-id": p("*** Environment ID: local", DEL),
    "blank-after-begin": p("", DEL),
    "blank-after-delete": p("*** Delete File: b.txt", "", DEL),
    "update-ws-only-context": (p("*** Update File: a.txt", "@@", "-x", "+y", "  "), {"a.txt": f("x", " ")}),
    "update-eof-blank-delete": p(UPD, "*** End of File", "", DEL),
    "move-after-chunk": p(UPD, "*** Move to: moved.txt"),
    "move-two-spaces": p("*** Update File: a.txt", "*** Move to:  moved.txt", "@@", "-x", "+y"),
    "at-at-twice-empty": p("*** Update File: a.txt", "@@", "@@", "-x", "+y"),
    "end-inside-then-blank": p(ADD, E, ""),
    "cr-cr-lf": p(ADD, DEL).replace("\n", "\r\r\n"),
}

#: The scratch folder every shape starts from; a shape's own dict adds or replaces files.
FILES = {"a.txt": f("x"), "b.txt": f("x"), "victim.txt": f("keep")}


def snapshot(d: Path) -> dict[str, bytes]:
    return {f.relative_to(d).as_posix(): f.read_bytes() for f in d.rglob("*") if f.is_file()}


def run(codex: str, patch: str, files: dict[str, str], work: Path) -> dict:
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    for name, body in files.items():
        (work / name).write_bytes(body.encode("utf-8"))
    before = snapshot(work)
    r = subprocess.run([codex, "--codex-run-as-apply-patch", patch], cwd=work, capture_output=True,
                       timeout=60)
    after = snapshot(work)
    touched = {}
    for k in sorted(set(before) | set(after)):
        if k not in after:
            touched[k] = "removed"
        elif k not in before:
            touched[k] = "added"
        elif before[k] != after[k]:
            touched[k] = "changed"
    err = r.stderr.decode("utf-8", "replace")
    for form in (str(work), work.as_posix()):
        err = err.replace(form, "<WORK>")                 # no machine path in the record
    err = err.strip().splitlines()
    return {"rc": r.returncode, "stderr": err[0][:300] if err else "", "touched": touched}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--codex", default=shutil.which("codex"))
    ap.add_argument("--out")
    a = ap.parse_args()
    if not a.codex:
        print("REFUSED: no codex on PATH and no --codex given", file=sys.stderr)
        return 2
    exe = a.codex
    if exe.lower().endswith((".cmd", ".bat", ".ps1")):
        print("REFUSED: pass the native codex.exe with --codex (the npm shim re-quotes arguments)",
              file=sys.stderr)
        return 2
    v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60).stdout.split()
    version = v[-1] if v else ""
    if not version:
        print("REFUSED: `codex --version` printed nothing", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else REPO / "tools" / "x4validate" / "tests" / "fixtures" / "codex" / version / \
        "patch_grammar_oracle.json"
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, shape in SHAPES.items():
            patch, setup = shape if isinstance(shape, tuple) else (shape, {})
            files = {**FILES, **setup}
            rows.append({"name": name, "patch": patch, "files": files,
                         **run(exe, patch, files, Path(tmp) / "w")})
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {"codex_version": version, "rows": rows}
    out.write_bytes((json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"{len(rows)} shapes recorded against codex {version} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

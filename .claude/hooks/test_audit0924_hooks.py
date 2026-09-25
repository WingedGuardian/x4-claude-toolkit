"""AUDIT-2026-09-24 Phase 1 -- hook-harness findings HK-5 and HK-6.

Runnable with no dependencies:  python .claude/hooks/test_audit0924_hooks.py

EVERY test here is decorated `unittest.expectedFailure`: each FAILS on the audited code for
the reason named in its docstring, and turns into an "unexpected success" (a run failure) the
moment a fix lands -- so the decorator must be removed together with the fix.

Conventions follow test_hook_facts.py: dangerous tokens are BUILT FROM PARTS and fixture
paths are generic. The one test that runs a hook (sed -i) points every X4 path at a throwaway
temp directory and feeds the payload on stdin; the hook only DECIDES, it never executes the
command it is shown.
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HOOKS = pathlib.Path(__file__).resolve().parent
REPO = HOOKS.parent.parent
BASH = shutil.which("bash") or r"C:/Program Files/Git/bin/bash.exe"

#: Every tool that can change a file on disk, and so must reach a protect-* guard.
FILE_CHANGING_TOOLS = ("Bash", "Edit", "Write", "NotebookEdit", "PowerShell")


def _pretool_matchers():
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    out = []
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        cmds = " ".join(h.get("command", "") for h in entry.get("hooks", []))
        out.append((entry.get("matcher") or "", cmds))
    return out


class TestHK5MatcherCoverage(unittest.TestCase):
    @unittest.expectedFailure
    def test_every_file_changing_tool_reaches_a_protect_guard(self):
        """AUDIT-2026-09-24 HK-5 (and the HK-1 gap it catches): no test pinned matcher
        coverage -- deleting the Edit|Write guard kept all three hook suites green. Fails
        today because NotebookEdit and PowerShell match no PreToolUse guard at all."""
        import re
        guarded = set()
        for matcher, cmds in _pretool_matchers():
            if "protect-" not in cmds:
                continue
            for tool in FILE_CHANGING_TOOLS:
                if re.fullmatch(matcher, tool):
                    guarded.add(tool)
        self.assertEqual(sorted(set(FILE_CHANGING_TOOLS) - guarded), [],
                         "file-changing tools with NO protect-* PreToolUse guard")


class TestHK6Minor(unittest.TestCase):
    @unittest.expectedFailure
    def test_env_resolution_comment_states_the_real_precedence(self):
        """AUDIT-2026-09-24 HK-6: _x4-env.sh's header says `x4-paths.env > existing env var`
        while the code (and the paragraph right below it) make THE ENVIRONMENT WIN."""
        head = (HOOKS / "_x4-env.sh").read_text(encoding="utf-8").splitlines()[:12]
        line = next(ln for ln in head if "Resolution order" in ln)
        self.assertLess(line.find("env var"), line.find("x4-paths.env"),
                        "stated order puts the config file above the environment: " + line)

    @unittest.expectedFailure
    def test_session_canary_uses_the_shared_python_lookup(self):
        """AUDIT-2026-09-24 HK-6: session-canary.sh resolves python itself (`command -v
        python`) instead of x4_python, so it ignores X4_PYTHON like no other hook does."""
        text = (HOOKS / "session-canary.sh").read_text(encoding="utf-8")
        self.assertIn("x4_python", text)

    @unittest.expectedFailure
    def test_session_canary_not_checked_line_reaches_stdout(self):
        """AUDIT-2026-09-24 HK-6: the rc-0 NOT CHECKED disclosure is printed to STDERR,
        which a SessionStart hook does not put in the model's context (INFERRED from the
        hook contract; stdout is what SessionStart adds)."""
        text = (HOOKS / "session-canary.sh").read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines() if "'NOT CHECKED:'" in ln)
        self.assertNotIn(">&2", line, line)

    @unittest.expectedFailure
    def test_next_blind_spot_id_consults_remote_tracking_branches(self):
        """AUDIT-2026-09-24 HK-6: next-blind-spot-id.py promises 'EVERY branch' but lists
        refs/heads only, so an id claimed on origin/* by another clone is invisible."""
        text = (REPO / "tools" / "x4validate" / "scripts" / "next-blind-spot-id.py"
                ).read_text(encoding="utf-8")
        self.assertIn("refs/remotes", text)

    @unittest.expectedFailure
    def test_a_deny_does_not_tell_the_reader_to_confirm(self):
        """AUDIT-2026-09-24 HK-6: `sed -i` on a game file is DENIED with a reason reading
        'confirm: ...' -- there is nothing to confirm on a deny. Either the verdict (ask) or
        the wording is wrong; which one is a design decision."""
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="hk6_"))
        try:
            game = tmp / "game"
            (game / "libraries").mkdir(parents=True)
            env = dict(os.environ, X4_GAME=str(game), X4_TOOLKIT=str(tmp / "tk"),
                       X4_REFERENCE=str(tmp / "ref"), X4_EXTENSIONS=str(game / "extensions"))
            target = str(game / "libraries" / "wares.xml").replace(chr(92), "/")
            cmd = "se" + "d -i s/a/b/ " + target
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
            p = subprocess.run([BASH, str(HOOKS / "protect-bash.sh")], input=payload,
                               capture_output=True, text=True, env=env, timeout=60)
            out = json.loads(p.stdout)["hookSpecificOutput"]
            self.assertEqual(out.get("permissionDecision"), "deny",
                             "fixture premise moved: " + p.stdout[:200])
            self.assertNotIn("confirm", out.get("permissionDecisionReason", "").lower())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

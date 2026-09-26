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


    def test_the_post_edit_validator_sees_every_file_editing_tool(self):
        """Re-review 3: NotebookEdit reached the PreToolUse guards but not the PostToolUse
        x4validate advisory, and the advisory read `file_path` only."""
        import re
        settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
        covered = set()
        for entry in settings.get("hooks", {}).get("PostToolUse", []):
            cmds = " ".join(h.get("command", "") for h in entry.get("hooks", []))
            if "x4validate-on-edit" in cmds:
                covered |= {t for t in ("Edit", "Write", "NotebookEdit")
                            if re.fullmatch(entry.get("matcher") or "", t)}
        self.assertEqual(covered, {"Edit", "Write", "NotebookEdit"})
        self.assertIn("notebook_path",
                      (HOOKS / "x4validate-on-edit.sh").read_text(encoding="utf-8"))


class TestHK5ProductionReadPath(unittest.TestCase):
    """AUDIT-2026-09-24 HK-5: every harness PIPES stdin, and "a test that pipes stdin
    cannot reproduce the production condition" is how five hooks sat inert while their
    suites passed (`cat /dev/stdin` read 0 bytes in the hook environment). These feed the
    payload from a FILE, the other shape stdin arrives in, and each carries a pipe twin so
    a difference between the two read paths is what fails -- not the rule."""

    def _run(self, hook, payload, env, via_file):
        if not via_file:
            return subprocess.run([BASH, str(HOOKS / hook)], input=payload, capture_output=True,
                                  text=True, env=env, timeout=120)
        f = pathlib.Path(env["X4_TOOLKIT"]).parent / "payload.json"
        f.write_text(payload, encoding="utf-8")
        with open(f, "r", encoding="utf-8") as fh:
            return subprocess.run([BASH, str(HOOKS / hook)], stdin=fh, capture_output=True,
                                  text=True, env=env, timeout=120)

    def _verdict(self, p):
        if not p.stdout.strip():
            return "allow"
        return json.loads(p.stdout)["hookSpecificOutput"].get("permissionDecision", "advise")

    def test_a_payload_read_from_a_FILE_is_seen(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="hk5_"))
        try:
            ref = tmp / "ref"
            (ref / "libraries").mkdir(parents=True)
            env = dict(os.environ, X4_GAME=str(tmp / "game"), X4_TOOLKIT=str(tmp / "tk"),
                       X4_REFERENCE=str(ref), X4_CONFIG=str(tmp / "none.env"))
            target = (ref / "libraries" / "wares.xml").as_posix()
            cases = [
                ("protect-bash.sh",
                 json.dumps({"tool_name": "Bash", "tool_input": {"command": "r" + "m -f " + target}}),
                 "deny"),
                ("protect-bash.sh",
                 json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}), "allow"),
                ("protect-files.sh",
                 json.dumps({"tool_name": "Edit", "tool_input": {"file_path": target}}), "deny"),
                ("protect-files.sh",
                 json.dumps({"tool_name": "NotebookEdit",
                             "tool_input": {"notebook_path": target}}), "deny"),
            ]
            for hook, payload, want in cases:
                for via_file in (True, False):
                    got = self._verdict(self._run(hook, payload, env, via_file))
                    self.assertEqual(got, want, (hook, payload[:90], "file" if via_file else "pipe"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestHK6Minor(unittest.TestCase):
    def test_env_resolution_comment_states_the_real_precedence(self):
        """AUDIT-2026-09-24 HK-6: _x4-env.sh's header says `x4-paths.env > existing env var`
        while the code (and the paragraph right below it) make THE ENVIRONMENT WIN."""
        head = (HOOKS / "_x4-env.sh").read_text(encoding="utf-8").splitlines()[:12]
        line = next(ln for ln in head if "Resolution order" in ln)
        self.assertLess(line.find("env var"), line.find("x4-paths.env"),
                        "stated order puts the config file above the environment: " + line)

    def test_session_canary_uses_the_shared_python_lookup(self):
        """AUDIT-2026-09-24 HK-6: session-canary.sh resolves python itself (`command -v
        python`) instead of x4_python, so it ignores X4_PYTHON like no other hook does."""
        text = (HOOKS / "session-canary.sh").read_text(encoding="utf-8")
        self.assertIn("x4_python", text)

    def test_session_canary_not_checked_line_reaches_stdout(self):
        """AUDIT-2026-09-24 HK-6: the rc-0 NOT CHECKED disclosure is printed to STDERR,
        which a SessionStart hook does not put in the model's context (INFERRED from the
        hook contract; stdout is what SessionStart adds)."""
        text = (HOOKS / "session-canary.sh").read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines() if "'NOT CHECKED:'" in ln)
        self.assertNotIn(">&2", line, line)

    def test_next_blind_spot_id_consults_remote_tracking_branches(self):
        """AUDIT-2026-09-24 HK-6: next-blind-spot-id.py promises 'EVERY branch' but lists
        refs/heads only, so an id claimed on origin/* by another clone is invisible."""
        text = (REPO / "tools" / "x4validate" / "scripts" / "next-blind-spot-id.py"
                ).read_text(encoding="utf-8")
        self.assertIn("refs/remotes", text)

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


# ------------------------------------------------------------------------------------------
# AUDIT-2026-09-24 HK-1 review follow-up: gaps in the PowerShell FRONT-END, pinned END TO END
# (the payload is piped into protect-bash.sh as JSON, as Claude Code sends it). The hook only
# DECIDES; nothing here executes the commands it is shown.
import sys as _sys
_sys.path.insert(0, str(HOOKS))
import hook_facts as _H  # noqa: E402

BS = chr(92)


@unittest.skipUnless(_H._pwsh_exe(), "no PowerShell here: the front-end cannot be exercised "
                                     "(without one it ASKS on every PowerShell command)")
class _PSE2E(unittest.TestCase):
    """Fixture roots in a throwaway directory, Windows-spelled (backslashes), because that is
    how a PowerShell user writes them."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="psfe_"))
        t = cls.tmp
        cls.game, cls.ref, cls.tk = t / "X4 Foundations", t / "reference", t / "tk"
        cls.docs = t / "Documents"
        cls.prof = cls.docs / "Egosoft" / "X4" / "123"
        for d in (cls.game / "libraries", cls.ref / "libraries", cls.tk, cls.prof / "save"):
            d.mkdir(parents=True)
        cls.env = dict(os.environ, X4_GAME=str(cls.game), X4_REFERENCE=str(cls.ref),
                       X4_TOOLKIT=str(cls.tk), X4_PROFILE=str(cls.prof),
                       X4_DOCUMENTS=str(cls.docs), X4_MODS=str(cls.tk / "dev"),
                       X4_CONFIG=str(t / "none.env"))
        cls.env.pop("CLAUDE_PROJECT_DIR", None)
        # Windows spellings of the roots, for PowerShell text
        cls.R = str(cls.ref).replace("/", BS)
        cls.G = str(cls.game).replace("/", BS)
        cls.S = str(cls.prof / "save").replace("/", BS)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def verdict(self, command, tool="PowerShell"):
        payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}})
        p = subprocess.run([BASH, str(HOOKS / "protect-bash.sh")], input=payload,
                           capture_output=True, text=True, env=self.env, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        if not p.stdout.strip():
            return "allow"
        return json.loads(p.stdout)["hookSpecificOutput"].get("permissionDecision", "advise")

    def expect(self, cases, tool="PowerShell"):
        for want, command in cases:
            self.assertEqual(self.verdict(command, tool), want, command)


class TestPS1Splatting(_PSE2E):
    """StaticParameterBinder cannot see a splat, so `Remove-Item @p` bound NO path and the
    delete reached no rule."""

    def test_a_literal_hashtable_splat_is_resolved(self):
        self.expect([
            ("deny", "$p=@{Path='" + self.R + BS + "libraries'; Recurse=$true}; Remove-Item @p"),
            ("ask", "$p=@{LiteralPath='" + self.S + BS + "a.xml.gz'}; Remove-Item @p"),
            ("deny", "$q=@{Path='" + self.R + BS + "a.xml'; Value='x'}; Set-Content @q"),
        ])

    def test_an_unresolvable_splat_on_a_writing_cmdlet_asks(self):
        self.expect([("ask", "Remove-Item @args"),
                     ("ask", "$p = Get-Params; Remove-Item @p")])

    def test_an_unresolvable_splat_BESIDE_a_given_path_still_asks(self):
        """Re-review 2: with a path present, the "no target path" report cannot fire, so
        only the splat report stands between these and an allow -- the splat may carry
        -Destination (or -Path) pointing anywhere."""
        self.expect([("ask", "$p = Get-Params; Move-Item ." + BS + "a @p"),
                     ("ask", "Copy-Item ." + BS + "a @args")])

    def test_TWIN_harmless_splats(self):
        self.expect([("allow", "$p=@{Path='.' + '" + BS + "x.txt'}; Remove-Item @p"),
                     ("allow", "$o=@{Object='x'}; Write-Output @o"),
                     ("allow", "$o = Get-Stuff; Write-Output @o")])


class TestPS2MethodCalls(_PSE2E):
    """Instance and type-qualified file methods reached no rule: only [IO.File]/[IO.Directory]
    static calls were mapped."""

    def test_instance_deletes_on_an_identified_object(self):
        R = self.R
        self.expect([
            ("deny", "(Get-Item '" + R + BS + "a.xml').Delete()"),
            ("deny", "gci '" + R + "' | % { $_.Delete() }"),
            ("deny", "[System.IO.FileInfo]::new('" + R + BS + "a.xml').Delete()"),
            ("deny", "(New-Object System.IO.DirectoryInfo '" + R + "').Delete($true)"),
            ("deny", "([IO.FileInfo]'" + R + BS + "a.xml').MoveTo('C:" + BS + "x.xml')"),
            ("deny", "$f = Get-Item '" + R + BS + "a.xml'; $f.Delete()"),
        ])

    def test_type_qualified_statics(self):
        R = self.R
        self.expect([
            ("deny", "using namespace System.IO" + chr(10) + "[Directory]::Delete('" + R + "', $true)"),
            ("deny", "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory('" + R
             + "', 'DeleteAllContents')"),
            ("deny", "[System.IO.File]::Replace('C:" + BS + "n.xml', '" + R + BS + "a.xml', $null)"),
            ("deny", "[IO.File]::Encrypt('" + R + BS + "a.xml')"),
        ])

    def test_an_unresolvable_target_asks(self):
        self.expect([
            ("ask", "$f.Delete()"),
            ("ask", "[IO.File]::WriteAllText($x, 'y')"),
            ("ask", "$d.MoveTo('C:" + BS + "y')"),
            ("ask", "Get-Things | % { $_.Delete() }"),
        ])

    def test_a_root_variable_target_still_denies(self):
        """Unresolved is ASK -- but a target naming a root through its variable must still
        reach the root rule, where the deny outranks the ask (as for Remove-Item)."""
        self.expect([
            ("deny", '[IO.File]::Delete("$env:X4_REFERENCE' + BS + 'a.xml")'),
            ("deny", '(Get-Item "$env:X4_REFERENCE").Delete()'),
        ])

    def test_TWIN_harmless_methods(self):
        self.expect([
            ("allow", "'abc'.Replace('a','b')"),
            ("allow", "$s.Replace('a','b'); $list.CopyTo($arr, 0)"),
            ("allow", "(Get-Item ." + BS + "x.txt).Delete()"),
            ("allow", "[IO.Path]::Combine('a','b'); [string]::Copy('x')"),
            ("allow", "[IO.File]::ReadAllText('" + self.R + BS + "a.xml')"),
        ])


class TestPS3InvokeExpression(_PSE2E):
    """iex of text the translator cannot read, or nested past its depth limit, was DROPPED:
    the command it runs reached no rule. Bash's `eval "$X"` is the model -- except that a
    carrier the walk could not open is reported, never passed."""

    def test_computed_text_asks(self):
        self.expect([("ask", "iex $cmd"),
                     ("ask", "Invoke-Expression -Command (Get-Content .\\x.ps1 -Raw)"),
                     ("ask", "$c = 'Remove-' + $n; iex $c")])

    def test_past_the_depth_limit_asks(self):
        inner = "Get-Date"
        for _ in range(6):
            inner = "iex '" + inner.replace("'", "''") + "'"
        self.assertEqual(self.verdict(inner), "ask", inner)

    def test_resolvable_text_is_still_judged(self):
        self.expect([("deny", "iex 'Remove-Item -Recurse " + self.R + "'"),
                     ("deny", "$c = 'Remove-Item -Recurse " + self.R + "'; iex $c")])

    def test_TWIN_harmless_iex(self):
        self.expect([("allow", "iex 'Get-Date'"), ("allow", "iex \"Get-ChildItem .\"")])


class TestPS4ProviderAndPrefixedPaths(_PSE2E):
    """A provider-qualified or extended-length spelling names the same file, and compared
    equal to no root."""

    def spellings(self, p):
        return ["Microsoft.PowerShell.Core" + BS + "FileSystem::" + p, "FileSystem::" + p,
                BS + BS + "?" + BS + p, BS + BS + "." + BS + p]

    def test_reference_game_profile(self):
        cases = []
        for sp in self.spellings(self.R):
            cases.append(("deny", "Remove-Item -Recurse -LiteralPath '" + sp + "'"))
            cases.append(("deny", "Set-Content -LiteralPath '" + sp + BS + "a.xml' -Value x"))
        for sp in self.spellings(self.G):
            cases.append(("deny", "Remove-Item -Recurse -Force '" + sp + "'"))
        for sp in self.spellings(self.S):
            cases.append(("ask", "Remove-Item -LiteralPath '" + sp + BS + "a.xml.gz'"))
        self.expect(cases)

    def test_in_a_nested_bash_carrier_too(self):
        sp = "FileSystem::" + self.R
        self.expect([("deny", 'powershell -c "Remove-Item -Recurse \'' + sp + '\'"')], tool="Bash")

    def test_TWIN_reads_stay_allowed(self):
        self.expect([("allow", "Get-ChildItem 'FileSystem::" + self.R + "'"),
                     ("allow", "Get-Content '" + BS + BS + "?" + BS + self.R + BS + "a.xml'")])


class TestPS5CmdPercentVariables(_PSE2E):
    """`%VAR%` in a cmd.exe carrier was literal text, so `%X4_REFERENCE%` named no root.
    Now it reaches the rules as `${VAR}` does in Bash: a root variable names its root,
    any other is an unknown operand."""

    def test_root_variables(self):
        self.expect([
            ("deny", 'cmd //c rd /s /q "%X4_REFERENCE%"'),
            ("deny", 'cmd /c "rd /s /q %X4_REFERENCE%' + BS + 'libraries"'),
            ("ask", 'cmd //c del /q "%X4_SAVES%' + BS + 'a.xml.gz"'),
        ], tool="Bash")

    def test_TWIN_an_unknown_variable_is_an_unknown_operand(self):
        self.expect([("allow", 'cmd //c rd /s /q "%TEMP%' + BS + 'build"'),
                     ("allow", 'cmd //c echo 100%% done')], tool="Bash")


class TestPS6OtherWritingCmdlets(_PSE2E):
    """Cmdlets outside the translator's switch passed through word for word, so their
    writes reached no rule."""

    def test_mapped_writers(self):
        R = self.R
        f = "'" + R + BS + "a.xml'"
        self.expect([
            ("deny", "Clear-Item " + f),
            ("deny", "Set-ItemProperty " + f + " -Name IsReadOnly -Value $false"),
            ("deny", "Remove-ItemProperty -Path " + f + " -Name x"),
            ("deny", "Copy-ItemProperty -Path ." + BS + "x -Destination " + f + " -Name y"),
            ("deny", "Expand-Archive ." + BS + "x.zip -DestinationPath '" + R + "'"),
            ("deny", "Compress-Archive -Path ." + BS + "x -DestinationPath '" + R + BS + "a.zip'"),
            ("deny", "Get-Process | Export-Csv -Path '" + R + BS + "a.csv'"),
            ("deny", "Get-Process | Export-Json -Path '" + R + BS + "a.json'"),
            ("deny", "'x' | Tee-Object -FilePath '" + R + BS + "a.txt'"),
            ("deny", "Invoke-WebRequest https://example.invalid -OutFile '" + R + BS + "a'"),
            ("deny", "Start-Transcript -Path '" + R + BS + "t.txt'"),
            ("deny", "New-Item " + f + " -Force"),
            ("deny", "Set-Acl " + f + " -AclObject $a"),
            ("deny", "Start-Process git -RedirectStandardOutput '" + R + BS + "o.txt'"),
        ])

    def test_an_unknown_mutating_cmdlet_on_a_protected_path_asks(self):
        self.expect([("ask", "Frob-Thing '" + self.R + BS + "a.xml'"),
                     ("ask", "Update-Widget -Target '" + self.S + BS + "x'"),
                     ("ask", "Set-Item '" + self.G + BS + "libraries" + BS + "w.xml' -Value x")])

    def test_TWIN_harmless(self):
        R = self.R
        self.expect([
            ("allow", "Get-FileHash '" + R + BS + "a.xml'; Test-Path '" + R + "'"),
            ("allow", "Frob-Thing ." + BS + "x"),
            ("allow", "Expand-Archive x.zip -DestinationPath ." + BS + "out"),
            ("allow", "Import-Csv '" + R + BS + "a.csv' | Select-Object -First 1"),
            ("allow", "Select-String -Path '" + R + BS + "md" + BS + "x.xml' -Pattern y"),
            ("allow", "Write-Host '" + R + "'; 'x' | Tee-Object -Variable v"),
            ("allow", "Export-ModuleMember -Function f"),
        ])


class TestPSEmptyTranslation(_PSE2E):
    """Re-review item 1: a translation can be EMPTY (everything in it was unresolved, or it
    did nothing). protect-bash.sh's `[ -z "$COMMAND" ] && exit 0` would ALLOW the first
    kind; it asked only because `$(...)` stripped the newline after the sentinel, the split
    failed, and COMMAND held the raw fact dump -- which the ask then quoted."""

    def reason(self, command):
        payload = json.dumps({"tool_name": "PowerShell", "tool_input": {"command": command}})
        p = subprocess.run([BASH, str(HOOKS / "protect-bash.sh")], input=payload,
                           capture_output=True, text=True, env=self.env, timeout=120)
        if not p.stdout.strip():
            return "allow", ""
        h = json.loads(p.stdout)["hookSpecificOutput"]
        return h.get("permissionDecision", "advise"), h.get("permissionDecisionReason", "")

    def test_empty_with_unresolved_parts_asks_with_a_real_reason(self):
        for cmd in ("iex $cmd", "Remove-Item @args"):
            v, r = self.reason(cmd)
            self.assertEqual(v, "ask", cmd)
            self.assertNotIn("__X4_COMMAND__", r, cmd)
            self.assertNotIn("carrier_untranslated" + chr(9), r, cmd)
            self.assertIn("could not be analysed", r, cmd)

    def test_TWIN_empty_with_nothing_unresolved_allows(self):
        for cmd in ("# only a comment", "$x = 1"):
            self.assertEqual(self.reason(cmd)[0], "allow", cmd)


class TestEmptyCommandSplit(unittest.TestCase):
    """The same defect at the seam, with the analyser STUBBED so the fact stream is exact.
    hook_facts ends its output with `<NL>__X4_COMMAND__<NL><command>`; for an empty command
    `$(...)` strips the final newline, the split fails, and COMMAND became the fact dump --
    every rule that quotes the command then quoted the dump. Runnable without PowerShell."""

    def run_stub(self, facts):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="split_"))
        try:
            for f in ("protect-bash.sh", "_x4-env.sh"):
                shutil.copy(HOOKS / f, tmp / f)
            lines = "".join("%s%s%s%s" % (k, chr(9), v, chr(10)) for k, v in facts.items())
            (tmp / "hook_facts.py").write_text(
                "import sys\nsys.stdin.read()\nsys.stdout.buffer.write(%r.encode())\n"
                % (lines + "__X4_COMMAND__" + chr(10)), encoding="utf-8")
            env = dict(os.environ, X4_CONFIG=str(tmp / "none.env"), X4_TOOLKIT=str(tmp))
            p = subprocess.run([BASH, str(tmp / "protect-bash.sh")],
                               input='{"tool_name":"PowerShell","tool_input":{"command":"x"}}',
                               capture_output=True, text=True, env=env, timeout=60)
            if not p.stdout.strip():
                return "allow", ""
            h = json.loads(p.stdout)["hookSpecificOutput"]
            return h.get("permissionDecision", "advise"), h.get("permissionDecisionReason", "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_empty_command_with_an_unresolved_part_asks_without_the_dump(self):
        v, r = self.run_stub({"carrier_untranslated": 1, "from_powershell": 1,
                              "rm_in_x4_dir": 1})
        self.assertEqual(v, "ask")
        self.assertNotIn("carrier_untranslated" + chr(9), r)
        self.assertNotIn("__X4_COMMAND__", r)

    def test_TWIN_empty_command_with_nothing_unresolved_allows(self):
        self.assertEqual(self.run_stub({"carrier_untranslated": 0, "from_powershell": 1})[0],
                         "allow")


if __name__ == "__main__":
    unittest.main()

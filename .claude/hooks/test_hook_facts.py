"""Unit tests for hook_facts.py -- the single parse pass behind protect-bash.sh.

Runnable with no dependencies:  python .claude/hooks/test_hook_facts.py

WHY THIS FILE EXISTS. Eight guard rules each hand-rolled quote-aware shell parsing in
bash. MEASURED 2026-08-31 on a clean machine: that cost 13,585 ms per Bash call on a
201-char command, against 1,205 ms before the rules were re-scoped -- 11.3x -- because
resolve_var re-derived its assignment table per TOKEN inside per-SEGMENT loops, and
writes_under / searches_rooted_at were each re-invoked 5 and 4 times with no memoising.
Every remaining gap the code review found also lived in that duplicated parsing.

Dangerous tokens are BUILT FROM PARTS. A literal here is read by the live hook when
this file is written, and a guard blocking the work of fixing guards has already
happened four times.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import hook_facts as H  # noqa: E402

D = "r" + "m"                      # the delete verb, never a literal here
BS = chr(92)                       # backslash

# FIXTURE paths, and they must stay GENERIC. These are compared as strings against
# command text -- nothing here touches a real filesystem -- so a real machine's layout
# buys the test nothing and ships someone's username and game-profile id inside a public
# file. Caught 2026-08-31 by scripts/verify-port.py before any push; the author's intent
# and the file's subject matter protect nothing, only the scan does.
GAME = "C:/Program Files (x86)/Steam/steamapps/common/X4 Foundations"
PROF = "C:/Users/tester/Documents/Egosoft/X4/12345678"
REF = "C:/Users/tester/Desktop/Modding/X4/reference"
TOOLKIT = "C:/Users/tester/Desktop/Modding/X4"
DOCS = "C:/Users/tester/Documents"
ROOTS = {"game": GAME, "profile": PROF, "reference": REF, "toolkit": TOOLKIT,
         "mods": TOOLKIT + "/dev", "documents": DOCS, "saves": PROF + "/save"}


Q = chr(39)                        # apostrophe
DQ = chr(34)                       # double quote
DEL_GAME = D + ' -rf "' + GAME + '"'
DEL_REF = D + ' -rf "' + REF + '"'


def F(command, timeout=0, background=False, roots=None):
    payload = {"tool_input": {"command": command, "timeout": timeout,
                              "run_in_background": background}}
    return H.facts(payload, ROOTS if roots is None else roots)


# ---------------------------------------------------------------- primitives
class TestNorm(unittest.TestCase):
    def test_lowercases_and_slashes(self):
        self.assertEqual(H.norm("C:" + BS + "Foo" + BS + "Bar"), "/c/foo/bar")

    def test_unifies_drive_dialect(self):
        # MSYS "/c/..." and Windows "C:/..." must compare EQUAL. Without this the same
        # write asked in one form was ALLOWED in the other across 2,553 commands.
        self.assertEqual(H.norm("C:/Users/x"), H.norm("/c/Users/x"))

    def test_does_not_eat_a_url_scheme(self):
        self.assertEqual(H.norm("https://a/b"), "https://a/b")

    def test_canonicalises_dot_segments(self):
        self.assertEqual(H.norm("/a/./b"), "/a/b")
        self.assertEqual(H.norm("/a/x/../b"), "/a/b")


class TestSegments(unittest.TestCase):
    def test_splits_on_operators(self):
        self.assertEqual(len(H.segments("a && b || c ; d | e")), 5)

    def test_a_separator_inside_quotes_does_not_split(self):
        self.assertEqual(len(H.segments("grep -E 'a|b' f")), 1)

    def test_newline_splits(self):
        self.assertEqual(len(H.segments("a\nb")), 2)

    def test_a_redirect_operator_is_not_a_separator(self):
        # `>|` contains a pipe and `2>&1` contains an ampersand. Splitting on those tore
        # the redirect away from its target, so `echo x >| <docs>/n.txt` wrote nowhere as
        # far as every write rule was concerned -- found by E2E, not by unit tests,
        # because redirects() was only ever tested on an unsplit string.
        self.assertEqual(len(H.segments("echo x >| a")), 1)
        self.assertEqual(len(H.segments("cmd 2>&1")), 1)
        self.assertEqual(len(H.segments("cmd &> a")), 1)


class TestAssignments(unittest.TestCase):
    def test_last_assignment_wins(self):
        # The bash helper used head -1, so a reassigned variable resolved to the OLD
        # value and the conservative fallback could never save it.
        self.assertEqual(H.assignments("X=/one; X=/two; echo $X")["X"], "/two")

    def test_quoted_value_with_spaces(self):
        self.assertEqual(H.assignments('G="/a b/c"; echo $G')["G"], "/a b/c")


class TestResolve(unittest.TestCase):
    def test_expands_both_forms(self):
        a = {"G": "/x"}
        self.assertEqual(H.resolve("$G/f", a), "/x/f")
        self.assertEqual(H.resolve("${G}/f", a), "/x/f")

    def test_unresolved_is_reported(self):
        self.assertTrue(H.has_unresolved(H.resolve("$NOPE/f", {})))


class TestHeredocs(unittest.TestCase):
    def test_body_is_removed(self):
        s = H.strip_heredocs("cat > f <<MARK\nsecret line\nMARK\necho after")
        self.assertNotIn("secret line", s)
        self.assertIn("echo after", s)

    def test_a_QUOTED_marker_still_opens_a_heredoc(self):
        # `<<'PY'` is the commonest form in this workspace. Blanking quoted strings before
        # looking for the marker blanked the MARKER NAME too, so the body was never
        # stripped and its text reached three refusal rules as though it were commands.
        s = H.strip_heredocs("python - <<'PY'\nsecret line\nPY\necho after")
        self.assertNotIn("secret line", s)
        self.assertIn("echo after", s)

    def test_a_quoted_marker_body_is_data_for_the_rules(self):
        cmd = "python - <<'PY'" + chr(10) + "guard = 'grep content.xml against $X4_PROFILE'" + chr(10) + "PY"
        self.assertFalse(F(cmd)["profile_search_by_name"])

    def test_marker_inside_quotes_does_NOT_open_a_skip(self):
        # The bash version scanned the raw line, so a quoted marker opened a skip
        # region and hid every following command from three deny rules.
        s = H.strip_heredocs('echo "a <<MARK b"\ngit add -A')
        self.assertIn("git add -A", s)


class TestNotEveryDoubleAngleIsAHeredoc(unittest.TestCase):
    """`<<` appears in three constructs that open NO heredoc, and treating any of them as
    one blanks the REST OF THE COMMAND -- so every rule below it goes silent and the hook
    allows.

    MEASURED 2026-09-01, all three E2E through protect-bash.sh: a game-directory
    `rm -rf` that the guard refuses on its own became a SILENT ALLOW when preceded by a
    here-string, by `<<` inside a comment, or by an arithmetic left-shift.

    Same class as the apostrophe bypass and the `$( )` nesting error: the PARSER feeding
    the predicates, not the predicates. 151 unit tests, 31 mutants and a 13k-command
    replay were green throughout -- the coverage report was true about the predicates and
    silent about their input. That is why the controls below matter as much as the cases.
    """

    def test_a_here_string_opens_no_heredoc(self):
        # The scan reaches the SECOND `<` of `<<<`, sees `<< word`, and reports a marker.
        self.assertIsNone(H.heredoc_marker("cat <<< hello"))
        self.assertIsNone(H.heredoc_marker("cat <<<hello"))

    def test_a_double_angle_in_a_COMMENT_opens_no_heredoc(self):
        self.assertIsNone(H.heredoc_marker("# shifts a << b"))
        self.assertIsNone(H.heredoc_marker("echo hi   # a << b"))

    def test_an_arithmetic_left_shift_opens_no_heredoc(self):
        self.assertIsNone(H.heredoc_marker("n=$((1 << FOO))"))

    def test_the_rules_still_SEE_a_delete_after_each_of_them(self):
        rm = 'rm -rf "C:/Program Files (x86)/Steam/steamapps/common/X4 Foundations/x"'
        for prefix in ("cat <<< hello", "# shifts a << b", "n=$((1 << 2))"):
            with self.subTest(prefix=prefix):
                self.assertTrue(F(prefix + chr(10) + rm)["rm_in_x4_dir"],
                                "syntax before the delete made the guard blind to it")

    # --- the other direction, or `return None` passes every test above --------------
    def test_a_real_heredoc_is_still_recognised(self):
        self.assertEqual(H.heredoc_marker("cat > f <<EOF"), "EOF")
        self.assertEqual(H.heredoc_marker("cat > f <<'PY'"), "PY")
        self.assertEqual(H.heredoc_marker("cat <<-END"), "END")

    def test_a_real_heredoc_beside_the_new_exclusions_still_opens(self):
        self.assertEqual(H.heredoc_marker("n=$((1 << 2)); cat <<EOF"), "EOF")
        self.assertEqual(H.heredoc_marker("cat <<EOF   # write it"), "EOF")

    def test_a_hash_that_is_not_a_comment_does_not_truncate(self):
        # a mid-word `#` is a URL fragment, and a quoted one is data -- neither is a comment
        self.assertEqual(H.heredoc_marker("curl http://x#y <<EOF"), "EOF")
        self.assertEqual(H.heredoc_marker("grep '#' f <<EOF"), "EOF")

    def test_a_real_heredoc_BODY_is_still_stripped(self):
        rm = 'rm -rf "C:/Program Files (x86)/Steam/steamapps/common/X4 Foundations/x"'
        self.assertFalse(F("cat > f <<EOF" + chr(10) + rm + chr(10) + "EOF")["rm_in_x4_dir"],
                         "a heredoc body is text being written, not a command")


class TestReservedWordsDoNotHideTheCommand(unittest.TestCase):
    """A shell RESERVED WORD in front of a simple command was a TOTAL guard bypass.

    The splitter cuts on `;` and `&&`, so `if true; then rm -rf <game>; fi` yields the
    segment `then rm -rf <game>` -- and verb() returned `then`. Every verb-keyed rule
    (rm, sed, git, grep) therefore missed, INCLUDING the three hard blocks: the game
    root, extensions wholesale, and the reference tree.

    MEASURED 2026-09-01 by the syntax-class fuzzer: 90 bypasses over 10 compound forms
    x 9 seeds. The 10th seed was immune because it is REDIRECT-keyed rather than
    verb-keyed, which is exactly what pins the root cause -- the operand was present
    and correct the whole time; the VERB was the keyword.

    Nothing in 151 unit tests, 35 mutants, a 13,500-command replay or 19 predicate
    probes could see this: they all start from a verb the parser has already chosen.
    """

    GAME = "C:/Program Files (x86)/Steam/steamapps/common/X4 Foundations"

    def _verbs(self, cmd):
        return [H.verb(seg) for seg, _ in
                H.cwd_track(H.strip_comments(H.strip_heredocs(cmd)))]

    def test_every_compound_form_still_shows_the_command(self):
        rm = 'rm -rf "%s"' % self.GAME
        forms = {
            "if/then":        "if true; then " + rm + "; fi",
            "if condition":   "if " + rm + "; then :; fi",
            "for/do":         "for i in 1; do " + rm + "; done",
            "until/do":       "until true; do " + rm + "; break; done",
            "else":           "if false; then :; else " + rm + "; fi",
            "elif":           "if false; then :; elif true; then " + rm + "; fi",
            "case arm":       "case x in x) " + rm + " ;; *) :;; esac",
            "case arm glob":  "case $v in *) " + rm + " ;; esac",
            "negation":       "! " + rm,
            "function posix": "f() { " + rm + "; }; f",
            "function kw":    "function f { " + rm + "; }; f",
            "nested if+for":  "if true; then for i in 1; do " + rm + "; done; fi",
        }
        for name, cmd in forms.items():
            with self.subTest(form=name):
                self.assertIn("rm", self._verbs(cmd),
                              "the keyword hid the command from every verb-keyed rule")

    def test_the_hard_block_survives_a_compound_wrapper(self):
        # the case that matters most: a hard block must not become an allow
        self.assertTrue(F('if true; then rm -rf "%s"; fi' % self.GAME)["rm_hits_game"])

    # --- must NOT strip: a real program keeps its name ---------------------------
    def test_a_program_whose_name_merely_starts_with_a_keyword_is_untouched(self):
        for cmd, want in (("do_thing --flag", "do_thing"),
                          ("iffy --x", "iffy"),
                          ("done_marker.sh", "done_marker.sh"),
                          ("function_helper.py run", "function_helper.py"),
                          ("casefold.py", "casefold.py")):
            with self.subTest(cmd=cmd):
                self.assertEqual(H.verb(H._unwrap(cmd)), want)

    def test_a_keyword_inside_quotes_is_data(self):
        self.assertEqual(H.verb(H._unwrap('echo "then rm -rf /"')), "echo")

    def test_a_case_with_no_dangerous_op_stays_quiet(self):
        self.assertFalse(F("case $v in a) echo hi ;; esac")["rm_hits_game"])

    # --- the regression this fix ITSELF introduced, pinned ------------------------
    def test_a_process_substitution_tail_is_not_a_case_arm_label(self):
        """The first version of the case-arm rule matched `rm -rf extensions) ` and ate
        the whole command. The BASELINE caught that one, so the fix was briefly worse
        than the bug. A case label is a single glob token and carries no whitespace;
        every dangerous rule needs an operand, and an operand needs a space -- which is
        what makes the spaceless restriction sound rather than merely convenient."""
        cmd = 'diff <(cd "%s" && rm -rf extensions) <(echo b)' % self.GAME
        self.assertIn("rm", self._verbs(cmd),
                      "the case-arm rule swallowed a process substitution")


class TestWrappersThatCarryACommandAsText(unittest.TestCase):
    """`bash -c`, its flag-cluster spellings, and `eval` all run TEXT as a command.

    Anything they carry is invisible to every rule that inspects segments, so each one
    is a total bypass on its own. The unwrapper matched the literal token `-c` only.

    MEASURED 2026-09-01, E2E through protect-bash.sh, against a game-root `rm -rf` that
    the guard denies unaided:
        sh -c '<rm>'   -> deny            bash -lc '<rm>' -> *** SILENT ALLOW ***
        xargs '<rm>'   -> deny            eval '<rm>'     -> *** SILENT ALLOW ***
    One character of flag clustering stood between a hard block and nothing.
    """

    GAME = "C:/Program Files (x86)/Steam/steamapps/common/X4 Foundations"

    def _rm(self):
        return 'rm -rf "%s"' % self.GAME

    def test_every_shell_c_spelling_is_unwrapped(self):
        for w in ("bash -c", "bash -lc", "sh -c", "sh -ic", "zsh -c", "dash -c", "ksh -c"):
            with self.subTest(wrapper=w):
                cmd = "%s '%s'" % (w, self._rm())
                self.assertTrue(F(cmd)["rm_hits_game"], "%s hid the command" % w)

    def test_eval_is_unwrapped(self):
        self.assertTrue(F("eval '%s'" % self._rm())["rm_hits_game"])

    def test_a_wrapper_inside_a_compound_is_still_unwrapped(self):
        """The two fixes have to compose: a keyword in front AND a wrapper around."""
        self.assertTrue(F("if true; then eval '%s'; fi" % self._rm())["rm_hits_game"])

    # --- must NOT fire ------------------------------------------------------------
    def test_an_unrelated_dash_c_is_not_a_shell(self):
        # `grep -c` counts; it is not a shell and carries no command
        self.assertFalse(F("grep -c foo file.txt")["rm_hits_game"])

    def test_a_harmless_wrapped_command_stays_quiet(self):
        self.assertFalse(F("bash -lc 'ls -la'")["rm_hits_game"])

    def test_a_quoted_dash_c_is_data(self):
        self.assertFalse(F("echo \"bash -c rm -rf /\"")["rm_hits_game"])


class TestHomeReferencesResolve(unittest.TestCase):
    """`~` and `$HOME` are values a hook CAN know, and not knowing them hid save deletes.

    MEASURED 2026-09-01 E2E through protect-bash.sh, on the SAME file: the absolute form
    asked, while `~/Documents/.../save/s.xml.gz` and `$HOME/...` were **silent allows**.
    Saves are the one thing in this workspace with no backup and no undo.

    Every other operand dialect was already correct -- absolute, relative after `cd`, the
    MSYS `/c/...` form, and backslashes. Home was the only gap, which is why this is an
    expansion rather than a new name backstop.
    """

    #: The FIXTURE profile id, not a real one. The first draft of this used the real
    #: id -- which both failed to match the synthetic saves root (so the control could
    #: not fire) and would have shipped a personal identifier in a public file. The
    #: broken control is what surfaced it, before scan-identifiers ever ran.
    TAIL = "Documents/Egosoft/X4/12345678/save/s.xml.gz"

    #: The fixture home, matching this file's synthetic roots. Patched rather than read
    #: from the environment: a test that depends on the real machine's home is not
    #: hermetic, and hard-coding a real one would ship a username in a public file.
    HOME = "C:/Users/tester"

    def test_all_home_spellings_reach_the_same_verdict_as_the_absolute_form(self):
        import unittest.mock as mock
        with mock.patch.object(H, "_HOME", self.HOME):
            want = F('rm -f "%s/%s"' % (self.HOME, self.TAIL))["rm_saves"]
            self.assertTrue(want, "the absolute control must fire, or this proves nothing")
            for spell in ("~", "$HOME", "${HOME}", "$USERPROFILE", "${USERPROFILE}"):
                with self.subTest(spelling=spell):
                    self.assertTrue(F("rm -f %s/%s" % (spell, self.TAIL))["rm_saves"],
                                    "%s did not resolve to the same file" % spell)

    def test_only_a_LEADING_home_reference_is_expanded(self):
        # `a~b` is a filename, and `x/$HOME` is not a home reference; rewriting either
        # would invent a path the user never wrote.
        self.assertEqual(H.expand_home("./a~b.txt"), "./a~b.txt")
        self.assertEqual(H.expand_home("x/$HOME/y"), "x/$HOME/y")

    def test_an_unrelated_file_under_home_still_does_not_fire(self):
        import unittest.mock as mock
        with mock.patch.object(H, "_HOME", self.HOME):
            self.assertFalse(F("rm -f ~/notes.txt")["rm_saves"])

    def test_expansion_is_inert_when_there_is_no_home(self):
        import unittest.mock as mock
        with mock.patch.object(H, "_HOME", ""):
            self.assertEqual(H.expand_home("~/x"), "~/x")


# ------------------------------------------------------------ redirect targets
class TestRedirects(unittest.TestCase):
    def test_truncate_vs_append(self):
        self.assertEqual(H.redirects("echo x > a"), [("truncate", "a")])
        self.assertEqual(H.redirects("echo x >> a"), [("append", "a")])

    def test_noclobber_override_is_a_truncate(self):
        self.assertEqual(H.redirects("echo x >| a"), [("truncate", "a")])

    def test_fd_redirect_to_devnull_is_not_a_target(self):
        self.assertEqual(H.redirects("cmd 2>/dev/null"), [])

    def test_fd_duplication_is_not_a_target(self):
        self.assertEqual(H.redirects("cmd 2>&1"), [])


# ------------------------------------------------------------------- verbs
class TestVerb(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(H.verb("cp a b"), "cp")

    def test_sees_through_a_wrapper(self):
        for w in ("time", "nice", "env", "sudo", "xargs"):
            self.assertEqual(H.verb(w + " cp a b"), "cp", w)

    def test_sees_through_an_env_assignment_prefix(self):
        self.assertEqual(H.verb("FOO=1 cp a b"), "cp")


class TestCopyDestinations(unittest.TestCase):
    def test_cp_writes_its_last_operand(self):
        self.assertEqual(H.copy_dests("cp a b"), ["b"])

    def test_dash_t_names_the_destination(self):
        self.assertEqual(H.copy_dests("mv -t /dest a b"), ["/dest"])

    def test_tee_writes_EVERY_file_operand(self):
        # TWO operands deliberately: with one, "first" and "last" are the same token,
        # so the test passed against a mutant that took the last -- it could not go red.
        self.assertEqual(H.copy_dests("tee a.txt b.txt"), ["a.txt", "b.txt"])

    def test_a_redirect_is_not_a_copy_operand(self):
        self.assertEqual(H.copy_dests("cp a b > log.txt"), ["b"])


# ----------------------------------------------------------------- searches
class TestSearches(unittest.TestCase):
    def test_grep_needs_a_recursive_flag(self):
        self.assertEqual(H.search_paths("grep foo /ref"), [])
        self.assertEqual(H.search_paths("grep -r foo /ref"), ["/ref"])

    def test_recursive_letter_anywhere_in_a_bundle(self):
        self.assertEqual(H.search_paths("grep -rn foo /ref"), ["/ref"])

    def test_rg_is_recursive_BY_DEFAULT(self):
        # rg and ag need no flag at all. The bash rule gated on a flag, so a full-tree
        # rg was allowed -- the exact command the rule exists to stop.
        self.assertEqual(H.search_paths("rg foo /ref"), ["/ref"])

    def test_dash_e_supplies_the_pattern_so_the_path_is_not_consumed(self):
        self.assertEqual(H.search_paths("grep -r -e foo /ref"), ["/ref"])

    def test_a_hyphenated_pattern_is_data_not_flags(self):
        self.assertEqual(H.search_paths("grep 'a-r-b' file.txt"), [])


# ------------------------------------------------------------- rule predicates
class TestDeletePredicates(unittest.TestCase):
    def test_quoted_game_root_hits(self):
        self.assertTrue(F(D + ' -rf "' + GAME + '"')["rm_hits_game"])

    def test_backslash_escaped_space_still_hits(self):
        esc = GAME.replace(" ", BS + " ")
        self.assertTrue(F(D + " -rf " + esc)["rm_hits_game"])

    def test_dot_segment_is_canonicalised(self):
        # Asserted against the REFERENCE root, not the game: the game predicate also
        # carries a name backstop, which caught this path by name and let the test pass
        # against a mutant with canonicalisation removed. A guard in front of the clause
        # under test shadows it (CLAUDE.md #26).
        p = REF.replace("/reference", "/./reference")
        self.assertTrue(F(D + ' -rf "' + p + '"')["rm_targets_reference"])

    def test_dotdot_segment_is_canonicalised(self):
        p = REF.replace("/reference", "/other/../reference")
        self.assertTrue(F(D + ' -rf "' + p + '"')["rm_targets_reference"])

    def test_dot_segment_in_the_game_path_also_hits(self):
        p = GAME.replace("/X4 Foundations", "/./X4 Foundations")
        self.assertTrue(F(D + ' -rf "' + p + '"')["rm_hits_game"])

    def test_deleting_extensions_WHOLESALE_is_a_hard_block(self):
        # Wiping extensions/ destroys every deployed mod. Narrowing the block to the
        # install root alone would let that fall through to a mere confirmation.
        #
        # The root here is deliberately NOT named "X4 Foundations": with the real name the
        # legacy backstop also matches, so the test passed against a mutant that removed
        # the extensions clause entirely -- it was asserting the right OUTCOME through the
        # wrong MECHANISM. Third instance of a guard clause shadowing the thing under test
        # in one session (CLAUDE.md #26).
        r = dict(ROOTS)
        r["game"] = "C:/Games/PlainlyNamedInstall"
        self.assertTrue(F(D + ' -rf "C:/Games/PlainlyNamedInstall/extensions"',
                          roots=r)["rm_hits_game"])
        # ...and the same root, one level deeper, must NOT be a hard block.
        self.assertFalse(F(D + ' -rf "C:/Games/PlainlyNamedInstall/extensions/mymod"',
                           roots=r)["rm_hits_game"])

    def test_deleting_ONE_deployed_mod_is_NOT_a_hard_block(self):
        # MEASURED 2026-08-31 over a 1,000-command corpus sample: all 4 hits of this rule
        # were `rm -rf "$DST"` where DST resolved to extensions/<one mod> -- the documented
        # deploy path, which deploy.py itself performs. Hard-denying it blocks routine
        # work. It must still CONFIRM (rm_in_x4_dir), which is the verdict meant for it.
        cmd = 'DST="' + GAME + '/extensions/mymod"; ' + D + ' -rf "$DST"'
        f = F(cmd)
        self.assertFalse(f["rm_hits_game"])
        self.assertTrue(f["rm_in_x4_dir"])

    def test_deleting_a_file_inside_a_deployed_mod_is_NOT_a_hard_block(self):
        cmd = D + ' -f "' + GAME + '/extensions/mymod/music/track.mp3"'
        f = F(cmd)
        self.assertFalse(f["rm_hits_game"])
        self.assertTrue(f["rm_in_x4_dir"])

    def test_unconfigured_backstop_does_not_catch_a_mod_folder(self):
        # The name backstop must be root-scoped too, or an unconfigured machine gets the
        # same over-block by a different route.
        r = dict(ROOTS)
        r["game"] = ""
        self.assertFalse(F(D + ' -rf "/opt/games/X4 Foundations/extensions/mymod"',
                           roots=r)["rm_hits_game"])

    def test_an_archive_merely_NAMED_after_the_game_does_not_hit(self):
        self.assertFalse(F(D + ' -f "/c/backups/X4 Foundations v2.zip"')["rm_hits_game"])

    def test_a_temp_delete_that_merely_MENTIONS_the_game_does_not_hit(self):
        cmd = 'G="' + GAME + '"; ' + D + " -f /c/tmp/scratch.txt"
        self.assertFalse(F(cmd)["rm_hits_game"])

    def test_unconfigured_root_falls_back_to_the_NAME(self):
        # An installer with no configured paths must still get the hard block. The
        # re-scoped bash rule dropped this backstop entirely.
        r = dict(ROOTS)
        r["game"] = ""
        self.assertTrue(F(D + ' -rf "/opt/games/X4 Foundations"', roots=r)["rm_hits_game"])


class TestWritePredicates(unittest.TestCase):
    def test_stderr_suppression_is_not_a_write_into_the_game(self):
        cmd = 'ls "' + GAME + '/extensions" 2>/dev/null'
        self.assertFalse(F(cmd)["redirect_truncate_into_game_or_profile"])

    def test_a_real_truncating_redirect_into_the_game_fires(self):
        cmd = 'echo x > "' + GAME + '/f.txt"'
        self.assertTrue(F(cmd)["redirect_truncate_into_game_or_profile"])

    def test_append_into_the_game_does_not_fire(self):
        cmd = 'echo x >> "' + GAME + '/f.txt"'
        self.assertFalse(F(cmd)["redirect_truncate_into_game_or_profile"])

    def test_reading_under_documents_is_not_a_write(self):
        self.assertFalse(F('cat "' + DOCS + '/notes.txt"')["writes_documents"])

    def test_writing_under_documents_fires(self):
        self.assertTrue(F('echo x > "' + DOCS + '/notes.txt"')["writes_documents"])

    def test_tee_into_documents_through_a_wrapper_fires(self):
        cmd = 'echo x | sudo tee "' + DOCS + '/n.txt"'
        self.assertTrue(F(cmd)["writes_documents"])


class TestSearchPredicates(unittest.TestCase):
    def test_rooted_at_reference_fires(self):
        self.assertTrue(F('grep -rn foo "' + REF + '"')["search_rooted_reference"])

    def test_rg_without_a_flag_at_reference_fires(self):
        self.assertTrue(F('rg foo "' + REF + '"')["search_rooted_reference"])

    def test_a_scoped_subdirectory_search_does_NOT_fire(self):
        cmd = 'grep -rn foo "' + REF + '/libraries"'
        self.assertFalse(F(cmd)["search_rooted_reference"])

    def test_cd_then_dot_is_rooted(self):
        cmd = 'cd "' + REF + '" && grep -rn foo .'
        self.assertTrue(F(cmd)["search_rooted_reference"])

    def test_rooted_at_the_workspace_fires(self):
        # The rule a code review found had NO probe at all, in either direction.
        self.assertTrue(F('grep -rn foo "' + TOOLKIT + '"')["search_rooted_workspace"])

    def test_rooted_at_the_game_fires(self):
        self.assertTrue(F('grep -rn foo "' + GAME + '"')["search_rooted_workspace"])

    def test_cd_to_root_then_scoped_subdir_does_NOT_fire(self):
        # The rule's own message recommends exactly this form.
        cmd = 'cd "' + TOOLKIT + '" && grep -rn foo tools/x4validate'
        self.assertFalse(F(cmd)["search_rooted_workspace"])

    def test_wrapper_before_grep_still_fires(self):
        cmd = 'time grep -rn foo "' + REF + '"'
        self.assertTrue(F(cmd)["search_rooted_reference"])


class TestMiscPredicates(unittest.TestCase):
    def test_git_add_all_fires(self):
        self.assertTrue(F("git add -A")["git_add_all"])

    def test_git_add_all_inside_a_heredoc_body_is_DATA(self):
        self.assertFalse(F("cat > f <<MARK\ngit add -A\nMARK")["git_add_all"])

    def test_git_add_explicit_path_does_not_fire(self):
        self.assertFalse(F("git add .gitattributes")["git_add_all"])

    def test_git_add_all_on_a_LATER_LINE_fires(self):
        # The bash rule used grep, which is line-based, so `^` matched every line start.
        # The Python port lost that: without re.M the rule only saw a command whose FIRST
        # characters were `git add`. Multi-line commands are routine here.
        self.assertTrue(F("echo setup" + chr(10) + "git add -A")["git_add_all"])

    def test_noclobber_redirect_into_documents_fires(self):
        # Same shape as the segments bug: proven at the redirects() level, but the fact
        # was False because the segment splitter had already torn `>|` apart.
        self.assertTrue(F('echo x >| "' + DOCS + '/n.txt"')["writes_documents"])

    def test_dollarq_after_a_pipeline_fires(self):
        self.assertTrue(F("cmd | head; echo $?")["dollarq_after_pipe"])

    def test_dollarq_after_a_process_substitution_does_not_fire(self):
        self.assertFalse(F("diff <(a | sort) <(b | sort); echo $?")["dollarq_after_pipe"])

    def test_timeout_over_cap_fires(self):
        self.assertTrue(F("sleep 1", timeout=900000)["timeout_over_cap"])

    def test_timeout_at_cap_does_not_fire(self):
        self.assertFalse(F("sleep 1", timeout=600000)["timeout_over_cap"])

    def test_longjob_invocation_fires(self):
        self.assertTrue(F("uv run python gates/corpus_sweep.py")["longjob_foreground"])

    def test_longjob_backgrounded_does_not_fire(self):
        cmd = "uv run python gates/corpus_sweep.py"
        self.assertFalse(F(cmd, background=True)["longjob_foreground"])

    def test_longjob_merely_NAMED_does_not_fire(self):
        self.assertFalse(F("grep -n 'corpus_sweep' gates/README.md")["longjob_foreground"])


class TestPreviouslyUnprobedRules(unittest.TestCase):
    """Every rule that a code review found had NO probe at all, or only one.

    A guard that has never been shown able to fire is decoration (CLAUDE.md #26), and
    these had shipped unproven: sed -i (0 probes), XRCatTool re-unpack (0), the two
    durable-record rules (1 between them), the timeout cap (1), shared-/tmp, and the
    save-game and X4-directory delete rules. Each gets must-fire AND must-not-fire.
    """

    # --- sed -i in the game or profile tree
    def test_sed_i_in_the_game_fires(self):
        self.assertTrue(F('sed -i s/a/b/ "' + GAME + '/f.xml"')["sed_i_in_game_or_profile"])

    def test_sed_i_elsewhere_does_not_fire(self):
        self.assertFalse(F("sed -i s/a/b/ /c/tmp/f.xml")["sed_i_in_game_or_profile"])

    def test_sed_WITHOUT_i_in_the_game_does_not_fire(self):
        self.assertFalse(F('sed s/a/b/ "' + GAME + '/f.xml"')["sed_i_in_game_or_profile"])

    # --- XRCatTool re-unpack into a locked reference tree
    def test_xrcat_unpack_into_reference_fires(self):
        cmd = 'XRCatTool.exe -in 01.cat -out "' + REF + '"'
        self.assertTrue(F(cmd)["xrcat_reunpack"])

    def test_xrcat_without_out_does_not_fire(self):
        self.assertFalse(F('XRCatTool.exe -in "' + REF + '/01.cat"')["xrcat_reunpack"])

    def test_xrcat_unpacking_elsewhere_does_not_fire(self):
        self.assertFalse(F("XRCatTool.exe -in 01.cat -out /c/tmp/out")["xrcat_reunpack"])

    # --- durable records
    def test_truncating_redirect_onto_a_durable_record_fires(self):
        self.assertTrue(F("echo x > KNOWLEDGEBASE.md")["durable_truncating_redirect"])

    def test_APPEND_onto_a_durable_record_does_not_fire(self):
        # >> cannot truncate, and appending to the knowledgebase is the normal way to
        # add an entry -- blocking it would make the routine case impossible.
        self.assertFalse(F("echo x >> KNOWLEDGEBASE.md")["durable_truncating_redirect"])

    def test_redirect_onto_an_ordinary_md_does_not_fire(self):
        self.assertFalse(F("echo x > notes.md")["durable_truncating_redirect"])

    def test_python_open_w_naming_a_durable_record_fires(self):
        cmd = "python -c \"open('MEMORY.md', 'w').write(x)\""
        self.assertTrue(F(cmd)["durable_python_open_w"])

    def test_python_open_r_naming_a_durable_record_does_not_fire(self):
        cmd = "python -c \"open('MEMORY.md', 'r').read()\""
        self.assertFalse(F(cmd)["durable_python_open_w"])

    # --- measurement output into shared /tmp
    def test_redirect_into_tmp_fires(self):
        self.assertTrue(F("uv run x4validate > /tmp/out.log")["write_to_tmp"])

    def test_reading_from_tmp_does_not_fire(self):
        self.assertFalse(F("cat /tmp/out.log")["write_to_tmp"])

    def test_scratchpad_write_does_not_fire(self):
        self.assertFalse(F("echo x > /c/scratch/out.log")["write_to_tmp"])

    # --- deleting a save game
    def test_deleting_a_save_fires(self):
        self.assertTrue(F(D + ' -f "' + PROF + '/save/save_001.xml.gz"')["rm_saves"])

    def test_reading_a_save_does_not_fire(self):
        self.assertFalse(F('cat "' + PROF + '/save/save_001.xml.gz"')["rm_saves"])

    # --- deleting inside an X4 directory
    def test_deleting_inside_the_mods_tree_fires(self):
        self.assertTrue(F(D + ' -rf "' + ROOTS["mods"] + '/mymod"')["rm_in_x4_dir"])

    def test_deleting_an_unrelated_temp_file_does_not_fire(self):
        self.assertFalse(F(D + " -f /c/tmp/scratch.txt")["rm_in_x4_dir"])

    # --- the profile-by-name measurement trap
    def test_grepping_the_profile_by_name_fires(self):
        self.assertTrue(F('grep -i somemod "' + PROF + '/content.xml"')["profile_search_by_name"])

    def test_grepping_the_profile_by_MANIFEST_ID_does_not_fire(self):
        cmd = 'grep -i ws_3691358137 "' + PROF + '/content.xml"'
        self.assertFalse(F(cmd)["profile_search_by_name"])

    def test_grepping_an_unrelated_file_does_not_fire(self):
        self.assertFalse(F("grep -i somemod /c/tmp/other.xml")["profile_search_by_name"])

    # --- copy into the game or profile
    def test_copy_INTO_the_game_fires(self):
        self.assertTrue(F('cp -r mymod "' + GAME + '/extensions/"')["copy_into_game_or_profile"])

    def test_copy_OUT_of_the_game_does_not_fire(self):
        cmd = 'cp -r "' + GAME + '/extensions/mymod" /c/tmp/'
        self.assertFalse(F(cmd)["copy_into_game_or_profile"])

    # --- deleting the reference tree
    def test_deleting_reference_fires(self):
        self.assertTrue(F(D + ' -rf "' + REF + '"')["rm_targets_reference"])

    def test_reading_reference_does_not_fire(self):
        self.assertFalse(F('ls "' + REF + '"')["rm_targets_reference"])


class TestWrappedCommands(unittest.TestCase):
    """`bash -c "<command>"` hid everything inside it from every rule. Pre-existing, and
    segment-splitting made the pipeline form structural -- so the parse pass descends."""

    def test_delete_inside_bash_c_is_seen(self):
        inner = D + ' -rf "' + GAME + '"'
        self.assertTrue(F("bash -c '" + inner + "'")["rm_hits_game"])

    def test_search_inside_bash_c_is_seen(self):
        self.assertTrue(F('bash -c \'grep -rn foo "' + REF + '"\'')["search_rooted_reference"])

    def test_a_harmless_bash_c_does_not_fire(self):
        self.assertFalse(F("bash -c 'echo hello'")["rm_hits_game"])


class TestCliContract(unittest.TestCase):
    """The CLI is what protect-bash.sh actually calls, and it has its own failure modes.

    Roots travel on STDIN rather than the environment because MSYS/Git-Bash TRANSLATES a
    POSIX-looking value when passing an env var to a NATIVE Windows process: bash
    exported "/tmp/x/docs" and Python received "C:/Users/.../AppData/Local/Temp/x/docs",
    while the command text still said "/tmp/x/docs". No path rule could match, and every
    one of them went quiet while the hook looked healthy.
    """

    def _run(self, stdin_bytes, env=None):
        import os
        import subprocess
        e = dict(os.environ)
        if env:
            e.update(env)
        return subprocess.run([sys.executable, str(pathlib.Path(__file__).parent / "hook_facts.py")],
                              input=stdin_bytes, capture_output=True, env=e)

    def _payload(self, cmd):
        import json
        return json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})

    def test_roots_arrive_on_stdin_and_a_posix_root_matches(self):
        head = "documents\t/tmp/sbx/docs\n" + H.ROOT_SEP
        body = self._payload("echo x > '/tmp/sbx/docs/notes.txt'")
        p = self._run((head + body).encode())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("writes_documents\t1", p.stdout.decode())

    def test_output_carries_no_carriage_returns(self):
        # Text-mode stdout on Windows turned every "1" into "1\r", the shell compared it
        # against "1", every predicate read false, and the hook allowed everything.
        head = "game\tC:/g\n" + H.ROOT_SEP
        p = self._run((head + self._payload("echo hi")).encode())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn(b"\r", p.stdout)

    def test_empty_payload_refuses_rather_than_allowing(self):
        self.assertEqual(self._run(b"").returncode, 2)

    def test_unparseable_payload_refuses_rather_than_allowing(self):
        head = "game\tC:/g\n" + H.ROOT_SEP
        self.assertEqual(self._run((head + "not json").encode()).returncode, 3)

    def test_the_command_survives_verbatim_after_the_sentinel(self):
        cmd = "echo one" + chr(10) + "echo two"
        head = "game\tC:/g\n" + H.ROOT_SEP
        out = self._run((head + self._payload(cmd)).encode()).stdout.decode()
        self.assertTrue(out.endswith(cmd), repr(out[-60:]))


# ------------------------------------------------- operands resolve against cwd
class TestCwdRelativeOperands(unittest.TestCase):
    """A path named RELATIVE to a `cd` is the same path.

    MEASURED 2026-09-01 against c400a05 (the last state where the rules ran): the
    parse-pass rewrite traded whole-string grepping for structured operands, and so
    became blind to every INDIRECT way of naming a path. Nine cases, three of them
    verdicts the old hook produced and this one had lost:

        cd <saves> && rm -f *.xml.gz        ask    -> allow   REGRESSION
        rm -rf "$(echo <game>)"             deny   -> allow   REGRESSION
        cd <game> && echo x > notes.txt     advise -> allow   REGRESSION
        cd <game> && rm -rf .               allow  -> allow   pre-existing gap
        cd <reference> && rm -rf assets     allow  -> allow   pre-existing gap
        ... and the pushd / subshell / extensions variants

    The cause is ONE thing, which is why the fix is one thing: an operand was
    classified as written instead of as resolved. `cwd_of` already existed and was
    consumed only by the search rules.
    """

    def test_cd_then_relative_delete_of_extensions_is_the_game_delete(self):
        f = F('cd "%s" && %s -rf extensions' % (GAME, D))
        self.assertTrue(f["rm_hits_game"])

    def test_cd_then_delete_dot_is_the_game_root(self):
        f = F('cd "%s" && %s -rf .' % (GAME, D))
        self.assertTrue(f["rm_hits_game"])

    def test_cd_then_relative_delete_under_reference(self):
        f = F('cd "%s" && %s -rf assets' % (REF, D))
        self.assertTrue(f["rm_targets_reference"])

    def test_cd_then_relative_delete_of_saves(self):
        f = F('cd "%s" && %s -f *.xml.gz' % (ROOTS["saves"], D))
        self.assertTrue(f["rm_saves"])

    def test_pushd_relocates_like_cd(self):
        f = F('pushd "%s" && %s -rf extensions' % (GAME, D))
        self.assertTrue(f["rm_hits_game"])

    def test_popd_returns_to_the_previous_directory(self):
        # Without a stack, ignoring popd would resolve `build` against the game and
        # invent a false positive. The pop must actually pop.
        f = F('pushd "%s" && ls; popd && %s -rf build' % (GAME, D))
        self.assertFalse(f["rm_in_x4_dir"])

    def test_subshell_cd_relocates(self):
        f = F('(cd "%s" && %s -rf extensions)' % (GAME, D))
        self.assertTrue(f["rm_hits_game"])

    def test_cd_into_extensions_then_delete_one_mod_confirms(self):
        # One deployed mod is a redeploy, not a catastrophe: confirm, never hard block.
        f = F('cd "%s/extensions" && %s -rf amod' % (GAME, D))
        self.assertTrue(f["rm_in_x4_dir"])
        self.assertFalse(f["rm_hits_game"])

    def test_cd_then_relative_redirect_is_a_write_into_the_game(self):
        f = F('cd "%s" && echo x > notes.txt' % GAME)
        self.assertTrue(f["redirect_truncate_into_game_or_profile"])

    def test_cd_then_relative_copy_into_the_game(self):
        f = F('cd "%s" && cp /c/tmp/a extensions/a' % GAME)
        self.assertTrue(f["copy_into_game_or_profile"])

    # --- the other side: a relocation that is NOT into a protected root ----------
    def test_cd_elsewhere_then_delete_is_untouched(self):
        f = F('cd /c/build && %s -rf out' % D)
        self.assertFalse(f["rm_in_x4_dir"])
        self.assertFalse(f["rm_hits_game"])

    def test_a_relative_cd_cannot_be_resolved_and_must_not_guess(self):
        # The hook does not know the shell's real cwd, so `cd extensions` is
        # unresolvable. Guessing a root here would fire on unrelated work.
        f = F('cd extensions && %s -rf amod' % D)
        self.assertFalse(f["rm_in_x4_dir"])

    def test_delete_outside_any_root_still_allowed(self):
        f = F('%s -f /c/Windows/Temp/scratch.txt' % D)
        self.assertFalse(f["rm_in_x4_dir"])
        self.assertFalse(f["rm_hits_game"])


# ------------------------------------------- unresolvable operands, deletes only
class TestUnresolvedDeleteOperands(unittest.TestCase):
    """An operand a hook CANNOT resolve is not evidence of safety.

    Scoped to deletes by user decision (2026-09-01): a delete is the one channel
    with no backup behind it -- MEASURED, 0 of 186 auto-backups cover anything
    outside dev/, and savegames are covered by nothing. Writes keep their existing
    verdicts, so this cannot add prompts to routine work.
    """

    def test_command_substitution_counts_as_unresolved(self):
        # `$(...)` and backticks were invisible to has_unresolved, which tests only
        # for $NAME / ${NAME}. So the whole token read as a literal path, matched no
        # root, and a delete of the game root through `$(echo ...)` was allowed.
        self.assertTrue(H.has_unresolved("$(echo x)"))
        self.assertTrue(H.has_unresolved(chr(96) + "echo x" + chr(96)))
        self.assertTrue(H.has_unresolved("$NAME"))
        self.assertTrue(H.has_unresolved("${NAME}"))
        self.assertFalse(H.has_unresolved("/plain/path"))

    def test_delete_through_command_substitution_naming_the_root(self):
        f = F('%s -rf "$(echo %s)"' % (D, GAME))
        self.assertTrue(f["rm_in_x4_dir"])

    def test_delete_of_a_root_env_var_by_name(self):
        # $X4_GAME never appears expanded in the text, so no amount of string
        # matching finds the root. The VARIABLE NAME is the evidence.
        f = F('%s -rf "$X4_GAME"' % D)
        self.assertTrue(f["rm_in_x4_dir"])

    def test_delete_of_the_saves_env_var_by_name(self):
        f = F('%s -rf "$X4_SAVES"' % D)
        self.assertTrue(f["rm_saves"])

    def test_the_NAME_backstop_still_fires_on_an_unresolvable_path(self):
        """The name backstop must NOT skip unresolved operands.

        It is the only protection an unconfigured machine has, and there the visible
        text is the evidence: this path still ends in the game's name. A `not u` filter
        added here on 2026-09-01 removed that last defence, and the 13,041-command
        corpus could not detect it because no historical command has this shape -- only
        the mutation gate did.
        """
        f = F('%s -rf "$BUILD/X4 Foundations"' % D)
        self.assertTrue(f["rm_hits_game"])

    def test_the_NAME_backstop_fires_even_with_NO_roots_configured(self):
        f = F('%s -rf "$BUILD/X4 Foundations"' % D, roots={})
        self.assertTrue(f["rm_hits_game"])

    def test_an_unrelated_variable_is_not_assumed_dangerous(self):
        f = F('%s -rf "$BUILD_DIR"' % D)
        self.assertFalse(f["rm_in_x4_dir"])
        self.assertFalse(f["rm_hits_game"])

    def test_an_unresolved_WRITE_is_still_not_guessed_at(self):
        # Deletes only. A write through an unresolved variable keeps today's verdict.
        f = F('echo x > "$SOME_DIR/notes.txt"')
        self.assertFalse(f["redirect_truncate_into_game_or_profile"])


# ------------------------------------------- prose must not blind the guard (C1)
class TestUnbalancedQuoteDoesNotBlindTheGuard(unittest.TestCase):
    """One apostrophe in an English comment used to disable EVERY rule after it.

    MEASURED 2026-09-01 against c400a05, which refused both members of every pair:
    5 of 5 refusals became a silent allow -- the game-delete HARD BLOCK, the reference
    block, the savegame confirm, the reference-search advisory and `git add -A`. The
    parse pass is quote-aware everywhere, so an unclosed quote converts the rest of the
    command into text no rule can see, and a rule that sees nothing returns False, which
    is indistinguishable from "this is fine". A REGRESSION the rewrite introduced: the
    old bash hook grepped the raw string and was unaffected.

    Position pins the mechanism: the same apostrophe placed AFTER the command still
    fires, because only text following the stray quote is blinded.
    """
    NL = chr(10)

    def _pair(self, prose_plain, prose_apos, tail, key):
        plain = F(prose_plain + self.NL + tail)
        apos = F(prose_apos + self.NL + tail)
        self.assertTrue(plain[key], "control did not fire; the test proves nothing")
        self.assertTrue(apos[key], "an apostrophe in a comment blinded %s" % key)

    def test_comment_apostrophe_does_not_hide_a_game_delete(self):
        self._pair("# clean up: this does not need it", "# clean up: this doesn't need it",
                   '%s -rf "%s"' % (D, GAME), "rm_hits_game")

    def test_comment_apostrophe_does_not_hide_a_reference_delete(self):
        self._pair("# it is a cleanup", "# it's a cleanup",
                   '%s -rf "%s"' % (D, REF), "rm_targets_reference")

    def test_comment_apostrophe_does_not_hide_a_save_delete(self):
        self._pair("# it is a cleanup", "# it's a cleanup",
                   '%s -f "%s/save_001.xml.gz"' % (D, ROOTS["saves"]), "rm_saves")

    def test_comment_apostrophe_does_not_hide_git_add_all(self):
        self._pair("# it is a fresh tree", "# it's a fresh tree",
                   "git add -A", "git_add_all")

    def test_comment_apostrophe_does_not_hide_a_rooted_search(self):
        self._pair("# we do not need a denominator", "# we don't need a denominator",
                   'grep -rn foo "%s"' % REF, "search_rooted_reference")

    def test_an_apostrophe_AFTER_the_command_was_never_the_problem(self):
        f = F('%s -rf "%s"  # we don%st need it' % (D, GAME, chr(39)))
        self.assertTrue(f["rm_hits_game"])
class TestEscapesOutsideQuotes(unittest.TestCase):
    """A backslash outside quotes escapes the next character, so it must not open a
    quote state. Exercised through the CONSEQUENCE: with the escape unhandled, `_scan`
    stops splitting on `&&` and the delete after it becomes invisible.

    An earlier version of this test asked ends_open_quote() instead -- which had its own
    escape handling, so it passed with _scan's removed and the planted mutant survived.
    A test must touch the code it claims to pin.
    """

    def test_an_escaped_apostrophe_does_not_blind_the_next_command(self):
        f = F("echo don" + BS + "'t && " + D + ' -rf "%s"' % GAME)
        self.assertTrue(f["rm_hits_game"])

    def test_a_comment_apostrophe_does_not_hide_a_long_job(self):
        # pins that the STRING-matching rules read the cleaned body, not the raw command
        f = F("# it's a sweep" + chr(10) + "uv run python gates/corpus_sweep.py")
        self.assertTrue(f["longjob_foreground"])


class TestFindDeletes(unittest.TestCase):
    """`find <root> -delete` and `find <root> -exec rm` remove files as surely as rm.

    MEASURED 2026-09-01 over 13,277 historical commands: `-delete` appears 4 times (none
    on a protected root) and `-exec rm` 0 times -- a 0-incidence gap, fixed because the
    failure mode is an unguarded delete of the game install, not because it was observed.
    """

    def test_find_delete_on_the_game_is_a_game_delete(self):
        self.assertTrue(F('find "%s" -delete' % GAME)["rm_hits_game"])

    def test_find_exec_rm_on_the_game_is_a_delete(self):
        self.assertTrue(F('find "%s" -exec %s -rf {} ;' % (GAME, D))["rm_in_x4_dir"])

    def test_a_find_that_does_NOT_delete_is_not_a_delete(self):
        """Deliberately UNFILTERED (-type is not a name filter), so the delete check is
        the clause actually under test. With `-name x` the filter guard returns first and
        SHADOWS it -- a mutant removing the delete check then survived, which is how a
        test can look like coverage it does not provide."""
        self.assertFalse(F('find "%s" -type d' % GAME)["rm_hits_game"])

    def test_a_FILTERED_find_is_scoped_and_does_not_fire(self):
        """`find . -name __pycache__ -exec rm -rf {} +` is routine hygiene, not a tree
        delete. MEASURED 2026-09-01: treating it like one added 40 prompts across 13,285
        commands, every one a cache cleanup -- noise by this project's own standard."""
        cmd = ('cd "%s" && find . -name __pycache__ -type d -exec %s -rf {} +'
               % (TOOLKIT, D))
        self.assertFalse(F(cmd)["rm_in_x4_dir"])

    def test_a_filtered_find_under_the_GAME_is_also_scoped(self):
        self.assertFalse(F('find "%s" -name x -delete' % GAME)["rm_hits_game"])

    def test_a_find_delete_outside_every_root_is_untouched(self):
        self.assertFalse(F("find /c/tmp -delete")["rm_in_x4_dir"])


class TestTimeoutShapes(unittest.TestCase):
    """A JSON number may be a float and a client may send a string; isinstance(int)
    turned the cap OFF for both. MEASURED: 0 of 13,277 historical calls used anything but
    int, so this is robustness rather than an observed bug -- recorded as such."""

    def test_an_int_over_the_cap_fires(self):
        self.assertTrue(F("sleep 1", timeout=900000)["timeout_over_cap"])

    def test_a_float_over_the_cap_fires(self):
        self.assertTrue(F("sleep 1", timeout=900000.0)["timeout_over_cap"])

    def test_a_string_over_the_cap_fires(self):
        self.assertTrue(F("sleep 1", timeout="900000")["timeout_over_cap"])

    def test_under_the_cap_does_not(self):
        self.assertFalse(F("sleep 1", timeout=500000)["timeout_over_cap"])

    def test_a_bool_is_not_a_timeout(self):
        # True is an int in Python; without the explicit exclusion it would read as 1.
        self.assertFalse(F("sleep 1", timeout=True)["timeout_over_cap"])

    def test_unparseable_keeps_the_rule_OFF_rather_than_firing_on_nonsense(self):
        self.assertFalse(F("sleep 1", timeout="abc")["timeout_over_cap"])


class TestStripComments(unittest.TestCase):
    """`#` starts a comment only at a word boundary outside quotes. The boundary test is
    what keeps $#, ${x#y} and a URL fragment intact."""

    def test_a_comment_keeps_its_newline_which_is_a_separator(self):
        out = H.strip_comments("# note" + chr(10) + "echo hi")
        self.assertIn(chr(10), out)
        self.assertIn("echo hi", out)

    def test_parameter_expansion_hash_is_not_a_comment(self):
        self.assertEqual(H.strip_comments('echo "${p#/a}"'), 'echo "${p#/a}"')

    def test_a_url_fragment_is_not_a_comment(self):
        self.assertEqual(H.strip_comments("curl http://a#b"), "curl http://a#b")

    def test_a_quoted_hash_is_not_a_comment(self):
        self.assertEqual(H.strip_comments("grep -n '#define' f.c"), "grep -n '#define' f.c")


class TestHeredocBodyIsDataForEveryRule(unittest.TestCase):
    """A heredoc body is text being WRITTEN, not commands. It was stripped for four
    rules and not for the other seven, so a body line reading like a delete produced a
    non-overridable hard deny on a command that only writes a file."""

    def test_a_delete_inside_a_heredoc_body_is_not_a_delete(self):
        cmd = ("cat > notes.md <<X" + chr(10)
               + '%s -rf "%s"' % (D, GAME) + chr(10) + "X")
        self.assertFalse(F(cmd)["rm_hits_game"])

    def test_a_search_inside_a_heredoc_body_is_not_a_search(self):
        cmd = ("cat > notes.md <<X" + chr(10)
               + 'grep -rn foo "%s"' % REF + chr(10) + "X")
        self.assertFalse(F(cmd)["search_rooted_reference"])

    def test_but_a_REAL_delete_beside_a_heredoc_still_fires(self):
        cmd = ("cat > notes.md <<X" + chr(10) + "just text" + chr(10) + "X" + chr(10)
               + '%s -rf "%s"' % (D, GAME))
        self.assertTrue(f_ := F(cmd)["rm_hits_game"], f_)


# ---------------------------------------------------- COMMAND RESOLUTION (2026-09-02)
#
# One root cause behind six separate total bypasses: the parse pass modelled shell
# GRAMMAR well and shell COMMAND RESOLUTION not at all. Two halves --
#   (1) what a verb token NAMES: `/bin/rm`, `rm.exe` and `$'rm'` are all `rm`, and
#       every verb-keyed rule compared the token verbatim;
#   (2) which constructs CARRY a command: a substitution, a shell heredoc, `trap`,
#       and a nested `-c` each run text that reached no rule.
# MEASURED E2E through protect-bash.sh before the fix: 14 of 16 probes returned a
# silent ALLOW against a game-root delete the guard catches when written bare.


class TestVerbNamesAreResolved(unittest.TestCase):
    def test_an_absolute_path_is_the_same_command(self):
        self.assertEqual(H.verb(H._unwrap("/bin/" + D + " -rf x")), D)

    def test_a_windows_path_is_the_same_command(self):
        # QUOTED, which is how a Windows path is actually written in a shell command.
        # norm() must run BEFORE basename: posixpath.basename does not split on a
        # backslash, so without it the whole string comes back as one "name".
        self.assertEqual(
            H.verb(H._unwrap(chr(34) + "C:" + BS + "tools" + BS + D + ".exe" + chr(34)
                             + " -rf x")), D)

    def test_an_UNQUOTED_windows_path_is_not_that_command_at_all(self):
        """Not a gap -- bash's own semantics. Unquoted, each backslash is an ESCAPE, so
        the token is the single word `C:toolsrm` and bash would look for a command by
        exactly that name. Resolving it to the delete verb would be inventing a threat
        the shell will never execute."""
        self.assertEqual(H.verb(H._unwrap("C:" + BS + "tools" + BS + D + " -rf x")),
                         "c:tools" + D)

    def test_a_dot_exe_suffix_is_the_same_command(self):
        self.assertEqual(H.verb(H._unwrap(D + ".exe -rf x")), D)

    def test_ansi_c_quoting_is_not_part_of_the_name(self):
        # `$'rm'` tokenised to `$rm` AND set the quoted flag, so verb()'s
        # `if quoted: return t` short-circuited with a name no rule has heard of.
        self.assertEqual(H.verb(H._unwrap("$" + chr(39) + D + chr(39) + " -rf x")), D)

    def test_the_hard_block_survives_every_spelling(self):
        for cmd in ("/bin/" + D + ' -rf "%s"' % GAME,
                    D + '.exe -rf "%s"' % GAME,
                    "$" + chr(39) + D + chr(39) + ' -rf "%s"' % GAME):
            with self.subTest(cmd=cmd):
                self.assertTrue(F(cmd)["rm_hits_game"], cmd)

    # --- must NOT over-strip -------------------------------------------------
    def test_only_dot_exe_is_stripped(self):
        """A general extension strip would break these: they ARE the command names."""
        for cmd, want in (("done_marker.sh", "done_marker.sh"),
                          ("function_helper.py run", "function_helper.py"),
                          ("casefold.py", "casefold.py")):
            with self.subTest(cmd=cmd):
                self.assertEqual(H.verb(H._unwrap(cmd)), want)


class TestWrapperVerbs(unittest.TestCase):
    def test_each_wrapper_is_seen_through(self):
        for w in ("timeout 5", "exec", "setsid", "nice -n 5", "ionice -c2"):
            with self.subTest(wrapper=w):
                self.assertTrue(F(w + " " + D + ' -rf "%s"' % GAME)["rm_hits_game"], w)

    def test_a_duration_is_not_mistaken_for_the_command(self):
        self.assertEqual(H.verb(H._unwrap("timeout 30s " + D + " -rf x")), D)

    def test_an_xargs_placeholder_is_not_the_command(self):
        self.assertEqual(H.verb(H._unwrap("xargs -I {} " + D + " -rf x")), D)

    def test_a_bare_number_is_still_a_verb_without_a_wrapper(self):
        """The skip is scoped to AFTER a wrapper. Outside that it must not apply, or
        a command really named oddly would silently lose its verb."""
        self.assertEqual(H.verb(H._unwrap("5 --flag")), "5")


class TestSubstitutionsCarryCommands(unittest.TestCase):
    def test_dollar_paren(self):
        self.assertTrue(F("echo $(" + D + ' -rf "%s")' % GAME)["rm_hits_game"])

    def test_backticks(self):
        self.assertTrue(F("echo " + chr(96) + D + ' -rf "%s"' % GAME + chr(96))["rm_hits_game"])

    def test_process_substitution(self):
        self.assertTrue(F("cat <(" + D + ' -rf "%s")' % GAME)["rm_hits_game"])

    def test_inside_SINGLE_quotes_nothing_runs(self):
        """The twin. Single quotes make it literal text, and treating it as a command
        would deny writing documentation that quotes one."""
        self.assertFalse(F("echo " + chr(39) + "$(" + D + ' -rf "%s")' % GAME
                           + chr(39) + " >> notes.md")["rm_hits_game"])

    def test_arithmetic_is_not_a_subshell(self):
        self.assertFalse(F("n=$((1 << 4)); echo $n")["rm_hits_game"])

    def test_the_extractor_returns_the_inner_text(self):
        self.assertEqual(H.substitutions("echo $(ls -la)"), ["ls -la"])
        self.assertEqual(H.substitutions("echo " + chr(96) + "ls" + chr(96)), ["ls"])
        self.assertEqual(H.substitutions("echo " + chr(39) + "$(ls)" + chr(39)), [])


class TestTrapCarriesACommand(unittest.TestCase):
    def test_trap_runs_its_first_operand(self):
        self.assertTrue(F("trap " + chr(39) + D + ' -rf "%s"' % GAME
                          + chr(39) + " EXIT")["rm_hits_game"])

    def test_a_benign_trap_is_still_benign(self):
        self.assertFalse(F("trap " + chr(39) + "echo bye" + chr(39) + " EXIT")["rm_hits_game"])


class TestEvalIsNotAlwaysTokenZero(unittest.TestCase):
    def test_a_wrapper_may_precede_eval(self):
        # `time eval <cmd>` sliced from toks[1:] produced the string "eval <cmd>",
        # whose own verb is `eval`, so no delete rule fired on that either.
        self.assertTrue(F("time eval " + chr(39) + D + ' -rf "%s"' % GAME
                          + chr(39))["rm_hits_game"])

    def test_bare_eval_still_works(self):
        self.assertTrue(F("eval " + chr(39) + D + ' -rf "%s"' % GAME
                          + chr(39))["rm_hits_game"])


class TestHeredocBodiesOnlyRunForAShell(unittest.TestCase):
    def _hd(self, opener, body):
        return opener + " <<" + chr(39) + "EOF" + chr(39) + chr(10) + body + chr(10) + "EOF"

    def test_a_shell_runs_its_heredoc(self):
        self.assertTrue(F(self._hd("bash", D + ' -rf "%s"' % GAME))["rm_hits_game"])

    def test_cat_writing_a_file_does_NOT(self):
        """Pinned: the body is the PAYLOAD of a file being written. Routing it would
        hard-deny writing documentation that quotes a dangerous command."""
        self.assertFalse(F(self._hd("cat > notes.md", D + ' -rf "%s"' % GAME))["rm_hits_game"])

    def test_a_python_heredoc_does_NOT(self):
        """Python, not shell. An assignment of a path to a name would parse as a
        delete verb under a shell tokeniser, inventing deletes out of assignments."""
        body = D + " = " + chr(34) + GAME + chr(34)
        self.assertFalse(F(self._hd("python -", body))["rm_hits_game"])

    def test_heredoc_bodies_returns_only_shell_openers(self):
        self.assertEqual(H.heredoc_bodies(self._hd("bash", "ls")), ["ls"])
        self.assertEqual(H.heredoc_bodies(self._hd("cat > n.md", "ls")), [])


class TestCarriersNest(unittest.TestCase):
    def test_a_shell_inside_a_shell(self):
        self.assertTrue(F("bash -c " + chr(39) + "sh -c " + chr(34) + D + " -rf "
                          + REF + chr(34) + chr(39))["rm_targets_reference"])

    def test_a_shell_inside_a_substitution(self):
        self.assertTrue(F("echo $(bash -c " + chr(39) + D + " -rf " + REF
                          + chr(39) + ")")["rm_targets_reference"])

    def test_the_walk_is_BOUNDED(self):
        """This runs on the blocking PreToolUse path; an unbounded walk over an
        adversarial string is a hang, and a hang here stops the session."""
        self.assertLessEqual(H._MAX_CARRIER_DEPTH, 8)
        deep = "echo ok"
        for _ in range(40):
            deep = "bash -c " + chr(39) + deep + chr(39)
        self.assertIsInstance(F(deep), dict)     # terminates

    def test_carried_commands_deduplicates(self):
        out, _trunc = H.carried_commands("echo $(ls) $(ls)", [])
        self.assertEqual(len(out), len(set(out)))

    def test_an_ordinary_command_is_never_truncated(self):
        """MEASURED over 13,503 real historical commands: the largest walk produced
        25 of the 250 allowed, p99 was 5 and p50 was 1. The cap must be unreachable
        by ordinary work or it becomes a prompt nobody reads."""
        for cmd in ("echo hello && ls -la",
                    "bash -c " + chr(39) + "sh -c " + chr(34) + "echo x" + chr(34) + chr(39),
                    "echo $(ls) $(pwd) $(date)"):
            with self.subTest(cmd=cmd):
                self.assertFalse(F(cmd)["carriers_truncated"], cmd)

    def test_a_TANGLED_command_says_so_instead_of_passing_quietly(self):
        """The walk is bounded because this runs on the blocking path -- MEASURED: a
        128 KB command with unique text at every nesting level produced 9,841 command
        strings and 4.1 s before the bound existed. But a bound that drops data and
        still returns a verdict is the narrowing-step defect, so it must ANNOUNCE."""
        def build(depth, n, tag="q"):
            if depth == 0:
                return "echo " + tag
            return " ".join("$(" + build(depth - 1, n, tag + chr(97 + i)) + ")"
                            for i in range(n))
        f = F("echo " + build(8, 3))
        self.assertTrue(f["carriers_truncated"],
                        "the walk was cut short and said nothing")

    def test_the_cap_is_reported_by_carried_commands_itself(self):
        deep = " ".join("$(echo a%d)" % i for i in range(400))
        _out, trunc = H.carried_commands("echo " + deep, [])
        self.assertTrue(trunc)


class TestAFilterThatFiltersNothing(unittest.TestCase):
    def test_a_universal_name_glob_is_not_a_narrowing(self):
        self.assertTrue(F("find " + chr(34) + GAME + chr(34) + " -name "
                          + chr(39) + "*" + chr(39) + " -delete")["rm_hits_game"])

    def test_a_REAL_filter_is_still_scoped(self):
        """The twin, and it is the whole reason the exemption exists: treating a
        genuinely-narrowed find as a tree delete added 40 prompts across 13,282
        commands, every one a __pycache__ cleanup."""
        self.assertFalse(F("find " + chr(34) + GAME + chr(34)
                           + " -name __pycache__ -delete")["rm_hits_game"])


class TestTheFactStreamCannotBeForged(unittest.TestCase):
    """protect-bash.sh splits the stream at the FIRST sentinel and `on()` matches
    "<NL>key<TAB>1<NL>" ANYWHERE before it, so a value carrying a newline can invent a
    fact no rule computed. `timeout` and `run_in_background` are passed through from
    the caller's payload, so they are the two values this file did not produce.

    E2E, before the fix: a benign `echo hi` with a forged `run_in_background` came back
    DENY. `on()` only ever tests for 1, so injection can ADD a fact and never remove
    one -- the reachable impact is a false refusal, not a bypass.
    """
    INJ = "x" + chr(10) + "rm_hits_game" + chr(9) + "1" + chr(10)

    def test_booleans_are_emitted_as_0_or_1(self):
        self.assertEqual(H._ipc_value("background", True), "1")
        self.assertEqual(H._ipc_value("background", False), "0")

    def test_a_timeout_is_always_a_number(self):
        self.assertEqual(H._ipc_value("timeout", 5), "5")
        self.assertEqual(H._ipc_value("timeout", "600000"), "600000")
        self.assertEqual(H._ipc_value("timeout", self.INJ), "0")

    def test_no_value_can_carry_a_field_separator(self):
        for key in ("timeout", "background", "anything"):
            with self.subTest(key=key):
                v = H._ipc_value(key, self.INJ)
                self.assertNotIn(chr(10), v)
                self.assertNotIn(chr(13), v)
                self.assertNotIn(chr(9), v)

    def test_a_real_value_still_survives(self):
        """The twin: a sanitiser that emptied everything would pass the test above."""
        self.assertEqual(H._ipc_value("something", "plain"), "plain")


class TestTheNameBackstopSurvivesARelativeOperand(unittest.TestCase):
    """prep() stores join_cwd(cwd, resolved) in element 0, and join_cwd returns "" when
    the operand is RELATIVE and the shell's directory is unknowable. That is correct for
    the PATH rules -- inventing a root there would fire on unrelated work -- but it
    silently disarmed the NAME backstop, whose whole job is an operand that bears the
    game's name WITHOUT being a resolvable path.

    MEASURED 2026-09-02: the backstop fired only when the delete followed a cd to an
    ABSOLUTE directory, i.e. only in the case it was least needed.
    """
    def test_a_bare_named_operand_fires(self):
        self.assertTrue(F(D + ' -rf "X4 Foundations"')["rm_hits_game"])

    def test_a_named_operand_after_a_RELATIVE_cd_fires(self):
        self.assertTrue(F('cd sub && ' + D + ' -rf "X4 Foundations"')["rm_hits_game"])

    def test_a_named_operand_after_an_ABSOLUTE_cd_still_fires(self):
        self.assertTrue(F('cd /somewhere && ' + D + ' -rf "X4 Foundations"')["rm_hits_game"])

    def test_an_ordinary_relative_delete_does_NOT_fire(self):
        """The twin, and the reason join_cwd returns "" in the first place: a backstop
        that fired on any relative delete would be a prompt on routine work."""
        for cmd in (D + " -rf build", "cd sub && " + D + " -rf dist",
                    D + " -rf __pycache__", "cd sub && " + D + " -rf .venv"):
            with self.subTest(cmd=cmd):
                self.assertFalse(F(cmd)["rm_hits_game"], cmd)


# --------------------------------------------------- round 3: the four bypass classes
# Each class below was a MEASURED silent ALLOW on 2026-09-02, against a delete the guard
# refuses when it is written plainly. Every class carries a twin that must stay ALLOWED:
# the failure this guard can least afford is a refusal on ordinary work -- 64 verified
# false denials were removed to earn the present precision and none may come back.
NLc = chr(10)
CONT = BS + NLc                    # a line continuation, built from parts


class TestALineContinuationIsNotASeparator(unittest.TestCase):
    """bash splices backslash-newline away before it parses anything; segments() split
    on it.

    So a delete continued onto a second line became TWO segments -- verb `rm` holding a
    lone backslash, and the path alone with no verb -- and every verb-keyed rule lost its
    operand at once, all three hard blocks included. MEASURED against 6 of 12 fuzz seeds;
    the other 6 have no whitespace to break at. This is how anyone writes a long command.
    """
    def test_the_game_root(self):
        self.assertTrue(F(D + " -rf " + CONT + '  "' + GAME + '"')["rm_hits_game"])

    def test_the_reference_tree(self):
        self.assertTrue(F(D + " -rf " + CONT + '  "' + REF + '"')["rm_targets_reference"])

    def test_split_between_the_verb_and_its_flag(self):
        self.assertTrue(F(D + " " + CONT + '  -rf "' + GAME + '"')["rm_hits_game"])

    def test_inside_SINGLE_quotes_it_stays_literal(self):
        """The twin. bash does NOT splice inside single quotes, so a continuation there
        is two literal characters of data, and removing it would corrupt text a rule
        then reads. An implementation that spliced unconditionally passes every test
        above and fails only this one."""
        payload = Q + "a" + CONT + "b" + Q
        self.assertIn(BS, H.join_continuations("echo " + payload))

    def test_an_ordinary_continued_command_is_untouched(self):
        self.assertFalse(F("echo one " + CONT + "  two && ls -la")["rm_hits_game"])


class TestAShellFedOnStdinIsACommandCarrier(unittest.TestCase):
    """Every way of handing a shell its program on stdin was invisible.

    `_inner_commands` modelled `-c`, `eval` and `trap`; a program arriving by pipe, by
    here-string or through /dev/stdin was not in the carrier set at all. Separately,
    `heredoc_bodies` asked whether the OPENER's verb is a shell -- but an opener is a
    PIPELINE, and where the first verb is `cat` the body was discarded as file payload
    while the shell on the far end of the pipe ran it unseen.
    """
    def test_echo_piped_into_bash(self):
        self.assertTrue(F("echo " + Q + DEL_GAME + Q + " | bash")["rm_hits_game"])

    def test_printf_piped_into_sh(self):
        cmd = "printf " + Q + "%s" + Q + " " + Q + DEL_GAME + Q + " | sh"
        self.assertTrue(F(cmd)["rm_hits_game"])

    def test_a_heredoc_piped_into_bash(self):
        cmd = "cat <<" + Q + "EOF" + Q + " | bash" + NLc + DEL_GAME + NLc + "EOF"
        self.assertTrue(F(cmd)["rm_hits_game"])

    def test_a_here_string(self):
        self.assertTrue(F("bash <<< " + Q + DEL_GAME + Q)["rm_hits_game"])

    def test_a_here_string_with_dash_s(self):
        self.assertTrue(F("bash -s <<< " + Q + DEL_GAME + Q)["rm_hits_game"])

    def test_source_dev_stdin(self):
        cmd = ("source /dev/stdin <<" + Q + "EOF" + Q + NLc + DEL_REF + NLc + "EOF")
        self.assertTrue(F(cmd)["rm_targets_reference"])

    # ---- twins: none of these hands a shell a program on stdin --------------------
    def test_a_shell_given_a_real_SCRIPT_does_not_pair_with_a_nearby_echo(self):
        """The pairing is deliberately narrow -- the consumer must have NO script
        operand. A rule that paired any echo with any later shell would refuse this
        shape, which appears throughout this repo's own tooling."""
        cmd = "echo " + Q + "note" + Q + " > n.md && bash script.sh"
        self.assertFalse(F(cmd)["rm_hits_game"])

    def test_a_heredoc_written_to_a_FILE_is_payload_not_a_program(self):
        cmd = ("cat > notes.md <<" + Q + "X" + Q + NLc + DEL_GAME + NLc + "X")
        self.assertFalse(F(cmd)["rm_hits_game"])

    def test_a_PYTHON_heredoc_is_not_routed_through_the_shell_parser(self):
        """A Python assignment whose first word is the delete verb. Routing non-shell
        heredoc bodies through the shell rules invents a delete nobody wrote -- which is
        why the OPENER's verb, not the presence of a body, decides."""
        cmd = ("python - <<" + Q + "PY" + Q + NLc + D + ' = "/tmp/x"' + NLc + "PY")
        self.assertFalse(F(cmd)["rm_hits_game"])


class TestAnUnresolvedExpansionIsNotALiteralPath(unittest.TestCase):
    """`_VAR` answered "what is this variable called" and was also asked "is there an
    expansion here". It matches a braced form only when the brace closes straight after
    the name, so a suffix strip, a default value, a pattern replace and an array index
    each matched NEITHER alternative and `has_unresolved` returned False.

    The DIRECTION is what makes this worse than a miss: the conservative branch exists so
    an operand the hook cannot resolve still refuses, and believing we HAD resolved it
    skips that branch -- the guard was most confident exactly where it knew least.
    """
    def test_suffix_strip(self):
        self.assertTrue(H.has_unresolved("${Z%ZZ}"))

    def test_default_value(self):
        self.assertTrue(H.has_unresolved("${NOPE:-" + GAME + "}"))

    def test_pattern_replace(self):
        self.assertTrue(H.has_unresolved("${Z//QQ/}"))

    def test_array_index(self):
        self.assertTrue(H.has_unresolved("${A[0]}"))

    def test_positional_and_special(self):
        for tok in ("$1", "$@", "$*", "$?", "$$"):
            with self.subTest(tok=tok):
                self.assertTrue(H.has_unresolved(tok), tok)

    def test_a_plain_literal_is_still_RESOLVED(self):
        """The twin: a predicate returning True unconditionally passes everything above
        while making every operand in the repo unresolvable -- refusals everywhere."""
        for tok in (GAME, "build", "./dist", "a-b_c.d", "100%"):
            with self.subTest(tok=tok):
                self.assertFalse(H.has_unresolved(tok), tok)

    def test_an_already_resolved_expansion_is_not_re_flagged(self):
        """resolve() substitutes what it can, and what comes back must not still look
        unresolved -- or an ordinary build-directory delete becomes a prompt."""
        self.assertFalse(F("DST=build; " + D + ' -rf "${DST%/}"')["rm_hits_game"])


class TestCoprocHidesACommand(unittest.TestCase):
    """The same shape as the compound-form bypass closed on 2026-09-01, still open
    because that fix enumerated the forms a fuzzer had produced instead of bash's own
    list of reserved words."""
    def test_coproc_does_not_hide_a_delete(self):
        self.assertTrue(F("coproc { " + DEL_GAME + "; }")["rm_hits_game"])

    def test_coproc_around_benign_work_is_still_allowed(self):
        self.assertFalse(F("coproc { echo hi; }")["rm_hits_game"])


class TestARedirectIsNotAnOperand(unittest.TestCase):
    """`_reads_stdin_program` refuses on any non-flag token, reading it as a script file.
    A REDIRECT is not a script file, and a here-string operator plus its word were what
    it tripped over -- so the single carrier whose payload is plainly visible in the
    command text was the one the check declined to look at."""
    def test_separated_and_attached_here_strings(self):
        for toks in (["<<<", "payload"], ["<<<payload"]):
            with self.subTest(toks=toks):
                self.assertEqual(H._drop_redirects(toks), [])

    def test_an_fd_prefixed_redirect(self):
        self.assertEqual(H._drop_redirects(["2>", "err", "-x"]), ["-x"])
        self.assertEqual(H._drop_redirects(["2>err", "-x"]), ["-x"])

    def test_a_real_operand_SURVIVES(self):
        """The twin: dropping too much makes a shell given a real script look like a
        stdin-fed one, and every suite this repo runs would start pairing with whatever
        echo precedes it."""
        self.assertEqual(H._drop_redirects(["script.sh"]), ["script.sh"])
        self.assertEqual(H._drop_redirects([">", "out", "script.sh"]), ["script.sh"])
        self.assertFalse(H._reads_stdin_program("bash script.sh"))
        self.assertFalse(H._reads_stdin_program("bash > out script.sh"))


# ------------------------------------------- round 3b: resolution, not just grammar
# Found by the twelve mutators added to fuzz-guard.py for the classes above -- 7 further
# bypasses, every one of them ALSO present on the committed tree, so these are holes the
# fuzzer previously could not EMIT rather than anything the round-3 fixes introduced.


class TestAnExpansionCarryingAnOperatorIsStillResolved(unittest.TestCase):
    """`resolve()` substituted with `_VAR`, which names only the two brace-free shapes,
    so every operator form stayed opaque and was matched against the roots as literal
    text. Resolving MORE can only turn an allow into a refusal on a command whose text
    really does name a protected root; it cannot invent one."""
    def test_suffix_strip(self):
        self.assertEqual(H.resolve("${V%QQ}", {"V": GAME + "QQ"}), GAME)

    def test_greedy_suffix_strip(self):
        self.assertEqual(H.resolve("${V%%QQ}", {"V": GAME + "QQ"}), GAME)

    def test_prefix_strip(self):
        self.assertEqual(H.resolve("${V#ZZ}", {"V": "ZZ" + GAME}), GAME)

    def test_default_when_unset(self):
        self.assertEqual(H.resolve("${NOPE:-" + GAME + "}", {}), GAME)

    def test_default_is_NOT_used_when_set(self):
        self.assertEqual(H.resolve("${V:-other}", {"V": GAME}), GAME)

    def test_pattern_replace(self):
        self.assertEqual(H.resolve("${V//QQ/}", {"V": GAME + "QQ"}), GAME)

    def test_array_index(self):
        a = H.assignments("A=(" + DQ + GAME + DQ + ")")
        self.assertEqual(H.resolve("${A[0]}", a), GAME)

    # ---- twins: what text alone CANNOT decide stays unresolved ------------------
    def test_a_GLOB_pattern_is_left_unresolved(self):
        """`${V%/*}` is the dirname idiom and needs pattern matching this hook does not
        do. Guessing here would produce a path that never appeared in the command, and a
        wrongly resolved operand is compared against the roots and CLEARED -- strictly
        worse than an unresolved one, which takes the conservative path."""
        out = H.resolve("${V%/*}", {"V": GAME + "/sub"})
        self.assertTrue(H.has_unresolved(out), out)

    def test_a_SUBSTRING_offset_is_left_unresolved(self):
        out = H.resolve("${V:2:5}", {"V": GAME})
        self.assertTrue(H.has_unresolved(out), out)

    def test_an_UNKNOWN_variable_with_no_default_is_left_unresolved(self):
        out = H.resolve("${NOPE%QQ}", {})
        self.assertTrue(H.has_unresolved(out), out)

    def test_a_suffix_that_does_not_match_leaves_the_value_alone(self):
        self.assertEqual(H.resolve("${V%ZZ}", {"V": GAME}), GAME)


class TestAnArrayKeepsItsQUOTINGWhenCaptured(unittest.TestCase):
    """`tokens()` strips quotes, so reading an array value from a token split the one
    element of a spaced Windows path into three and made element 0 `C:/Program`. The
    value is re-read from the raw segment for that reason."""
    def test_a_spaced_path_stays_ONE_element(self):
        a = H.assignments("A=(" + DQ + GAME + DQ + ")")
        self.assertEqual(H._array_elements(a["A"]), [GAME])

    def test_several_elements_still_split(self):
        a = H.assignments("A=(build dist out)")
        self.assertEqual(H._array_elements(a["A"]), ["build", "dist", "out"])

    def test_a_plain_assignment_is_not_an_array(self):
        a = H.assignments("A=" + DQ + GAME + DQ)
        self.assertEqual(H._array_elements(a["A"]), [])

    def test_an_index_past_the_end_is_unresolved(self):
        a = H.assignments("A=(build)")
        self.assertTrue(H.has_unresolved(H.resolve("${A[3]}", a)))


class TestCdThroughAVariableIsStillCd(unittest.TestCase):
    """`cwd_track` handed `_operands(seg)[0]` -- the RAW token -- to `join_cwd`, so a
    `cd` through any variable made the directory unknowable and EVERY later relative
    operand unattributable. MEASURED 2026-09-02: that walked a plain `$VAR` straight
    through the extensions hard block, which is the most ordinary idiom there is."""
    def test_a_plain_variable(self):
        cmd = "FZ=" + DQ + GAME + DQ + "; cd " + DQ + "$FZ" + DQ + " && " + D + " -rf extensions"
        self.assertTrue(F(cmd)["rm_hits_game"])

    def test_a_braced_variable(self):
        cmd = "FZ=" + DQ + GAME + DQ + "; cd " + DQ + "${FZ}" + DQ + " && " + D + " -rf extensions"
        self.assertTrue(F(cmd)["rm_hits_game"])

    def test_an_operator_bearing_expansion(self):
        cmd = ("FZ=" + DQ + GAME + "QQ" + DQ + "; cd " + DQ + "${FZ%QQ}" + DQ
               + " && " + D + " -rf extensions")
        self.assertTrue(F(cmd)["rm_hits_game"])

    def test_an_array_element(self):
        cmd = ("FZA=(" + DQ + GAME + DQ + "); cd " + DQ + "${FZA[0]}" + DQ
               + " && " + D + " -rf extensions")
        self.assertTrue(F(cmd)["rm_hits_game"])

    # ---- twins ------------------------------------------------------------------
    def test_an_UNKNOWABLE_cd_does_not_invent_a_root(self):
        """`cd "$NOPE"` names nothing this hook can see, and the command text contains
        no protected path. Refusing here would be a prompt on work that is not ours to
        judge -- the directory is UNKNOWN, which is a different answer from `the game`."""
        cmd = "cd " + DQ + "$NOPE" + DQ + " && " + D + " -rf extensions"
        self.assertFalse(F(cmd)["rm_hits_game"])

    def test_ordinary_relative_work_through_a_variable(self):
        cmd = "DIR=build; cd " + DQ + "$DIR" + DQ + " && " + D + " -rf dist"
        self.assertFalse(F(cmd)["rm_hits_game"])

    def test_an_array_of_ordinary_directories(self):
        cmd = "A=(build dist); cd " + DQ + "${A[0]}" + DQ + " && " + D + " -rf out"
        self.assertFalse(F(cmd)["rm_hits_game"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

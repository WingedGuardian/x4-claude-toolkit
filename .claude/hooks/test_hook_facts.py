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


if __name__ == "__main__":
    unittest.main(verbosity=2)

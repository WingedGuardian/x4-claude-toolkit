"""The Codex hook adapter: translate a native Codex payload, ask the guards, render ONLY the JSON
shapes Codex honours (C4). Driven through the RENDERED .codex/hooks/codex_adapter.py.

Every routing branch has a test; each decisive one has a twin that shows the branch decided it.
"""
import json
import subprocess
import sys

import pytest

from codex_testlib import ADAPTER, FIX, HAS_PWSH, make_sandbox, native, run_adapter as run


@pytest.fixture
def sandbox(tmp_path):
    return make_sandbox(tmp_path)


def test_rendered_adapter_exists():
    assert ADAPTER.is_file(), "regenerate: cd tools/x4validate && uv run python scripts/gen-agent-trees.py"


@pytest.mark.skipif(not HAS_PWSH, reason="no PowerShell -- routing NOT checked here")
def test_bash_labelled_powershell_is_routed(sandbox):
    tmp, tk, env = sandbox
    cmd = f"Set-Content -Path '{tk / 'reference' / 'libraries' / 'wares.xml'}' -Value 'x'"
    assert run(env, native("bash_powershell", tmp, command=cmd), shell="powershell")[0] == "deny"
    assert run(env, native("bash_powershell", tmp, command=cmd), shell="bash")[0] != "deny"  # twin: routing decides


def test_harmless_shell_command_allows(sandbox):
    tmp, _, env = sandbox
    assert run(env, native("bash_powershell", tmp, command="echo hello"), shell="bash") == ("allow", None)


def test_relative_patch_path_resolves_against_payload_cwd(sandbox):
    tmp, tk, env = sandbox
    patch = "*** Begin Patch\n*** Update File: reference/libraries/wares.xml\n@@\n-ref\n+x\n*** End Patch"
    assert run(env, native("apply_patch_update", tk, command=patch))[0] == "deny"
    assert run(env, native("apply_patch_update", tk / "dev", command=patch))[0] == "allow"  # same text, other cwd


def test_multi_file_patch_worst_verdict_wins_and_names_path(sandbox):
    tmp, tk, env = sandbox
    patch = ("*** Begin Patch\n*** Add File: dev/mymod/a.xml\n+<a/>\n"
             "*** Delete File: reference/libraries/wares.xml\n*** End Patch")
    d, reason = run(env, native("apply_patch_multi", tk, command=patch))
    assert d == "deny" and "wares.xml" in reason


def test_add_file_into_reference_denies_and_twin_in_dev_allows(sandbox):
    tmp, tk, env = sandbox
    for rel, want in (("reference/libraries/new.xml", "deny"), ("dev/mymod/new.xml", "allow")):
        patch = f"*** Begin Patch\n*** Add File: {rel}\n+<a/>\n*** End Patch"
        assert run(env, native("apply_patch_add", tk, command=patch))[0] == want, rel


def test_move_to_checks_both_ends(sandbox):
    tmp, tk, env = sandbox
    out_of_ref = ("*** Begin Patch\n*** Update File: reference/libraries/wares.xml\n*** Move to: dev/mymod/w.xml\n"
                  "@@\n-ref\n+x\n*** End Patch")
    into_ref = ("*** Begin Patch\n*** Update File: dev/mymod/w.xml\n*** Move to: reference/libraries/w.xml\n"
                "@@\n-ref\n+x\n*** End Patch")
    (tk / "dev" / "mymod" / "w.xml").write_text("ref\n", encoding="utf-8")
    assert run(env, native("apply_patch_move", tk, command=out_of_ref))[0] == "deny"   # the source end
    assert run(env, native("apply_patch_move", tk, command=into_ref))[0] == "deny"     # the destination end


def test_delete_file_patch_denies_in_reference(sandbox):
    tmp, tk, env = sandbox
    patch = "*** Begin Patch\n*** Delete File: reference/libraries/wares.xml\n*** End Patch"
    assert run(env, native("apply_patch_delete", tk, command=patch))[0] == "deny"


@pytest.mark.parametrize("pad", ["  ", "\t"])
def test_an_indented_delete_after_an_add_is_judged(sandbox, pad):
    """R2-F1 (MEASURED against codex --codex-run-as-apply-patch): Codex trims a line before asking
    whether it is a header, so this indented Delete after an Add deletes the file. The guard read
    it as Add content and ALLOWED it."""
    tmp, tk, env = sandbox
    patch = f"*** Begin Patch\n*** Add File: dev/mymod/h.txt\n+hi\n{pad}*** Delete File: reference/libraries/wares.xml\n*** End Patch"
    assert run(env, native("apply_patch_add", tk, command=patch))[0] == "deny"
    ok = patch.replace("reference/libraries/wares.xml", "dev/mymod/old.xml")
    assert run(env, native("apply_patch_add", tk, command=ok))[0] in ("allow", "advise")   # twin


def test_shell_heredoc_patch_is_judged_by_its_paths(sandbox):
    """P3 (MEASURED): apply_patch through the shell arrives as Bash and IS applied."""
    tmp, tk, env = sandbox
    body = "*** Begin Patch\n*** Add File: reference/libraries/x.xml\n+<a/>\n*** End Patch"
    cmd = f"apply_patch <<'PATCH'\n{body}\nPATCH"
    assert run(env, native("bash_shell_heredoc_patch", tk, command=cmd), shell="bash")[0] == "deny"
    ok = cmd.replace("reference/libraries/x.xml", "dev/mymod/x.xml")
    assert run(env, native("bash_shell_heredoc_patch", tk, command=ok), shell="bash")[0] == "allow"   # twin


def test_profile_ask_becomes_deny_with_approval_text(sandbox):
    tmp, tk, env = sandbox
    patch = f"*** Begin Patch\n*** Update File: {tmp / 'profile' / 'content.xml'}\n@@\n-a\n+b\n*** End Patch"
    d, reason = run(env, native("apply_patch_update", tk, command=patch))
    assert d == "ask" and reason.startswith("NEEDS YOUR APPROVAL:")
    assert reason.rstrip().endswith("Ask the user; do not retry until they agree.")


def test_manifest_advise_becomes_additional_context(sandbox):
    tmp, tk, env = sandbox
    patch = "*** Begin Patch\n*** Update File: dev/mymod/content.xml\n@@\n-a\n+b\n*** End Patch"
    d, ctx = run(env, native("apply_patch_update", tk, command=patch))
    assert d == "advise" and ctx


def test_unparseable_patch_is_inert_deny(sandbox):
    tmp, tk, env = sandbox
    d, reason = run(env, native("apply_patch_update", tk, command="*** Begin Patch\n*** Frobnicate: x\n*** End Patch"))
    assert d == "inert" and "X4 GUARD INERT" in reason


def test_unreadable_payload_is_inert_deny(sandbox):
    _, _, env = sandbox
    r = subprocess.run([sys.executable, str(ADAPTER), "pre_tool_use"], input=b"{not json", capture_output=True, env=env)
    assert b"permissionDecision\":\"deny" in r.stdout.replace(b" ", b"") and b"INERT" in r.stdout


def test_event_mismatch_is_inert_deny(sandbox):
    tmp, _, env = sandbox
    d = native("bash_powershell", tmp, command="echo hi")
    assert run(env, d, event="post_tool_use")[0] == "advise"          # wrong event on a non-blocking hook
    d["hook_event_name"] = "PostToolUse"
    assert run(env, d, event="pre_tool_use")[0] == "inert"


def test_missing_cwd_is_inert_deny(sandbox):
    tmp, _, env = sandbox
    assert run(env, native("bash_powershell", tmp / "no-such-dir", command="echo hi"), shell="bash")[0] == "inert"


def test_unknown_tool_allowed_and_recorded(sandbox):
    tmp, _, env = sandbox
    d = native("spawn_agent", tmp)
    assert run(env, d) == ("allow", None)
    log = tmp / "unknown-tools.log"
    assert log.is_file() and "collaborationspawn_agent" in log.read_text(encoding="utf-8")


def test_write_stdin_with_newline_is_judged_as_shell(sandbox):
    """No PreToolUse fired for write_stdin in 0/2 measured calls (DECISIONS #20: disclose only).
    If a future Codex does hook it, a submitted line is judged as a shell command."""
    tmp, tk, env = sandbox
    d = native("bash_powershell", tmp)
    d["tool_name"], d["tool_input"] = "write_stdin", {"session_id": 1, "chars": f"rm -rf '{(tk / 'reference').as_posix()}'\n"}
    assert run(env, d, shell="bash")[0] == "deny"
    d["tool_input"]["chars"] = f"rm -rf '{(tk / 'reference').as_posix()}'"     # twin: not submitted yet
    assert run(env, d, shell="bash")[0] == "allow"


def test_reason_is_bounded_directive_first(sandbox):
    tmp, tk, env = sandbox
    many = "".join(f"*** Delete File: reference/libraries/f{i:04d}.xml\n" for i in range(400))
    d, reason = run(env, native("apply_patch_delete", tk, command="*** Begin Patch\n" + many + "*** End Patch"))
    assert d in ("deny", "inert") and len(reason) <= 10_000 and reason.lstrip().startswith(("BLOCKED", "X4"))


def test_the_adapter_budget_bounds_a_whole_batch(sandbox):
    """MEASURED after merging lanes B+E: 400 deletes ran past the 180 s harness timeout under a
    45 s adapter budget -- the budget was checked only BETWEEN batches, and every x4guard check
    inside the one path batch started its OWN fresh deadline. One deadline must bound them all."""
    import time as _t
    tmp, tk, env = sandbox
    many = "".join(f"*** Delete File: reference/libraries/f{i:04d}.xml\n" for i in range(400))
    t0 = _t.monotonic()
    d, _reason = run(dict(env, X4_CODEX_BUDGET_S="5"),
                     native("apply_patch_delete", tk, command="*** Begin Patch\n" + many + "*** End Patch"))
    took = _t.monotonic() - t0
    assert d in ("deny", "inert"), d
    assert took < 40, f"a 5 s budget took {took:.1f} s"


def test_backup_taken_for_an_allowed_update(sandbox):
    tmp, tk, env = sandbox
    f = tk / "dev" / "mymod" / "a.xml"
    f.write_text("<a/>\n", encoding="utf-8")
    patch = "*** Begin Patch\n*** Update File: dev/mymod/a.xml\n@@\n-<a/>\n+<b/>\n*** End Patch"
    assert run(env, native("apply_patch_update", tk, command=patch))[0] == "allow"
    assert any((tmp / "backups").rglob("*")), "an allowed update must be backed up first"


def test_TWIN_no_backup_for_a_denied_patch(sandbox):
    tmp, tk, env = sandbox
    patch = "*** Begin Patch\n*** Update File: reference/libraries/wares.xml\n@@\n-ref\n+x\n*** End Patch"
    assert run(env, native("apply_patch_update", tk, command=patch))[0] == "deny"
    assert not any((tmp / "backups").rglob("*"))


def test_post_tool_use_validation_context_or_did_not_run(sandbox):
    tmp, tk, env = sandbox
    (tk / "dev" / "mymod" / "a.xml").write_text("<diff><add sel=\"/x\"/></diff>\n", encoding="utf-8")
    d = native("post_tool_use_apply_patch", tk,
               command="*** Begin Patch\n*** Add File: dev/mymod/a.xml\n+<diff/>\n*** End Patch")
    kind, ctx = run(env, d, event="post_tool_use")
    assert kind in ("allow", "advise")                 # never a deny from PostToolUse


def test_post_tool_use_unparseable_patch_says_validation_did_not_run(sandbox):
    tmp, tk, env = sandbox
    d = native("post_tool_use_apply_patch", tk, command="*** Begin Patch\n*** Nope: x\n*** End Patch")
    kind, ctx = run(env, d, event="post_tool_use")
    assert kind == "advise" and ctx.startswith("X4 VALIDATION DID NOT RUN")


def test_session_start_banner(sandbox):
    tmp, _, env = sandbox
    d = json.loads((FIX / "session_start.json").read_text(encoding="utf-8").replace("<CWD>", "x"))
    d["cwd"] = str(tmp)
    kind, ctx = run(env, d, event="session_start")
    assert kind == "advise" and ctx.startswith("X4 GUARDS LIVE (codex hooks v1)")


def test_deadline_exhausted_is_inert(sandbox):
    tmp, tk, env = sandbox
    env = dict(env, X4_CODEX_BUDGET_S="0")
    assert run(env, native("bash_powershell", tmp, command="echo hi"), shell="bash")[0] == "inert"


@pytest.mark.skipif(sys.platform != "win32", reason="Git Bash drive paths (/c/...) exist on Windows only")
def test_msys_drive_path_is_the_windows_path(sandbox):
    """Found by the conformance suite: abspath('/c/...') on Windows is '<drive>:/c/...', outside
    every protected root, so an Update File of the reference via /c/... was ALLOWED."""
    tmp, tk, env = sandbox
    p = tk.as_posix()
    msys = "/" + p[0].lower() + p[2:] + "/reference/libraries/wares.xml"
    patch = f"*** Begin Patch\n*** Update File: {msys}\n@@\n-ref\n+x\n*** End Patch"
    assert run(env, native("apply_patch_update", tk, command=patch))[0] == "deny"

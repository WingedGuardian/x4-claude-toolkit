"""Codex hook-trust disclosure (spec 5.8): an unreviewed, changed or disabled Codex hook is
SILENT, so three detectors exist -- the SessionStart banner the model is told to look for,
codex_trust.py outside the session, and a release convention for the frozen template."""
import ast
import importlib.util
import re
import time
from pathlib import Path

import pytest

from test_gen_codex_tree import TEMPLATE_SHA256

REPO = Path(__file__).resolve().parents[3]
ADAPTER_SRC = REPO / "agent" / "guards" / "adapters" / "codex.py"


def _banner() -> str:
    """The ONE module-level `BANNER = "<str>"` assignment, read from the AST (release review
    R7-7: a regex over the source, or a substring of it, is satisfied by a comment or prose)."""
    tree = ast.parse(ADAPTER_SRC.read_text(encoding="utf-8"))
    hits = [n.value.value for n in tree.body
            if isinstance(n, ast.Assign) and [getattr(t, "id", None) for t in n.targets] == ["BANNER"]
            and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)]
    assert len(hits) == 1, f"expected exactly one module-level BANNER string, found {len(hits)}"
    return hits[0]


def _load_adapter():
    """The RENDERED adapter (.codex/hooks/codex_adapter.py): there its sibling modules sit beside
    it, as Codex runs it. test_gen_codex_tree pins it to the source the AST is read from."""
    spec = importlib.util.spec_from_file_location("codex_adapter_disclosure",
                                                  REPO / ".codex" / "hooks" / "codex_adapter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_template_change_is_announced():
    log = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    pinned = re.findall(r"codex-hooks-template: ([0-9a-f]{64})", log)
    assert pinned and pinned[0] == TEMPLATE_SHA256, (
        "the frozen Codex hook template changed: add a CHANGELOG entry headed "
        "'Codex users must re-review hooks' carrying 'codex-hooks-template: <new sha>'")
    head = log[: log.index("codex-hooks-template: " + pinned[0])]
    assert "Codex users must re-review hooks" in head[-2000:]


def test_banner_is_one_constant_and_the_adapter_prints_it(monkeypatch):
    banner = _banner()
    assert banner.startswith("X4 GUARDS LIVE (codex hooks v1)")
    # Behaviour, not text: call session_start with the two SessionStart guards stubbed out, and
    # require the banner as the FIRST line of the context Codex receives.
    mod = _load_adapter()
    assert mod.BANNER == banner
    monkeypatch.setattr(mod, "_run_hook", lambda *a, **k: ("", None), raising=True)
    out = mod.session_start(time.monotonic() + 30)
    assert out["context"].split("\n")[0] == banner, out


def test_banner_text_is_in_the_codex_addendum():
    addendum = (REPO / "agent" / "instructions" / "codex.md").read_text(encoding="utf-8")
    banner = _banner()
    assert banner.split(" —")[0] in addendum      # the model is told to look for EXACTLY what is printed


def test_J_Q2_the_banner_does_not_claim_EVERY_shell_command_is_checked():
    """Plan 3 decision J-Q2: input typed into a running shell (`write_stdin`) and a shell
    `workdir` reach no guard (MEASURED, codex-0160.md), so 'every shell command ... is checked'
    over-claims. The pinned prefix stays; the tail names what is NOT checked."""
    banner = _banner()
    # The grammar, not two substrings (release review R7-7): "<checked> are checked (<unchecked>
    # is not)." -- the running shell must sit in the NOT-checked clause, and nothing in the
    # checked clause may claim "every".
    m = re.fullmatch(r"X4 GUARDS LIVE \(codex hooks v1\) — (?P<checked>[^()]+?) (?:is|are) checked "
                     r"\((?P<unchecked>[^()]+?) (?:is|are) not\)\.", banner)
    assert m, f"banner does not read '<checked> are checked (<unchecked> is not).': {banner!r}"
    assert "running shell" in m.group("unchecked"), m.groupdict()
    assert "running shell" not in m.group("checked") and "every" not in m.group("checked").lower(), m.groupdict()


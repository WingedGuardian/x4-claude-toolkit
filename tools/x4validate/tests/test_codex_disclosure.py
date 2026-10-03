"""Codex hook-trust disclosure (spec 5.8): an unreviewed, changed or disabled Codex hook is
SILENT, so three detectors exist -- the SessionStart banner the model is told to look for,
codex_trust.py outside the session, and a release convention for the frozen template."""
import re
from pathlib import Path

import pytest

from test_gen_codex_tree import TEMPLATE_SHA256

REPO = Path(__file__).resolve().parents[3]


def test_template_change_is_announced():
    log = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    pinned = re.findall(r"codex-hooks-template: ([0-9a-f]{64})", log)
    assert pinned and pinned[0] == TEMPLATE_SHA256, (
        "the frozen Codex hook template changed: add a CHANGELOG entry headed "
        "'Codex users must re-review hooks' carrying 'codex-hooks-template: <new sha>'")
    head = log[: log.index("codex-hooks-template: " + pinned[0])]
    assert "Codex users must re-review hooks" in head[-2000:]


def test_banner_is_one_constant_and_the_adapter_prints_it():
    adapter = (REPO / "agent" / "guards" / "adapters" / "codex.py").read_text(encoding="utf-8")
    m = re.search(r'^BANNER = "([^"]+)"', adapter, re.M)
    assert m and m.group(1).startswith("X4 GUARDS LIVE (codex hooks v1)")
    assert "parts = [BANNER]" in adapter


def test_banner_text_is_in_the_codex_addendum():
    adapter = (REPO / "agent" / "guards" / "adapters" / "codex.py").read_text(encoding="utf-8")
    addendum = (REPO / "agent" / "instructions" / "codex.md").read_text(encoding="utf-8")
    banner = re.search(r'^BANNER = "([^"]+)"', adapter, re.M).group(1)
    assert banner.split(" —")[0] in addendum      # the model is told to look for EXACTLY what is printed


def test_J_Q2_the_banner_does_not_claim_EVERY_shell_command_is_checked():
    """Plan 3 decision J-Q2: input typed into a running shell (`write_stdin`) and a shell
    `workdir` reach no guard (MEASURED, codex-0160.md), so 'every shell command ... is checked'
    over-claims. The pinned prefix stays; the tail names what is NOT checked."""
    adapter = (REPO / "agent" / "guards" / "adapters" / "codex.py").read_text(encoding="utf-8")
    banner = re.search(r'^BANNER = "([^"]+)"', adapter, re.M).group(1)
    assert banner.startswith("X4 GUARDS LIVE (codex hooks v1) — "), banner
    assert "every" not in banner.lower(), banner
    assert "running shell" in banner and "not" in banner, banner


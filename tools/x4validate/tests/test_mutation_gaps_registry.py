"""Mutation-campaign gaps in `_registry`'s enable-flag parsing (campaign 1 R5/R8,
re-anchored 2026-09-26 on lane I's `profile_flag`). Each test was verified to FAIL with
its mutant applied and PASS without it."""
from __future__ import annotations

from x4validate import _registry


def _mod(root, folder, enabled_attr):
    d = root / folder
    d.mkdir(parents=True)
    (d / "content.xml").write_text(
        f'<content id="{folder}" version="1" {enabled_attr}/>', encoding="utf-8")
    return d


def test_manifest_enabled_false_is_case_insensitive(tmp_path):
    """R5 (scan_installed site): enabled="FALSE" disables, as "false" does."""
    _mod(tmp_path, "a", 'enabled="FALSE"')
    _mod(tmp_path, "b", 'enabled=" False "')
    _mod(tmp_path, "c", "")
    got = {m["folder"]: m["enabled"] for m in _registry.scan_installed([tmp_path])}
    assert got == {"a": False, "b": False, "c": True}


def test_dlc_manifest_enabled_false_is_case_insensitive(tmp_path):
    """R5 (_dlc_entry site)."""
    assert _registry._dlc_entry(_mod(tmp_path, "ego_dlc_x", 'enabled="FALSE"'))["enabled"] \
        is False


def test_profile_flag():
    """R8 (re-anchored on `profile_flag`): absent LOADS (probe case b); 'false'/'0' in
    any case, trimmed, disable; anything else enables."""
    assert _registry.profile_flag(None) is True
    assert _registry.profile_flag("FALSE") is False
    assert _registry.profile_flag(" 0 ") is False
    assert _registry.profile_flag("true") is True

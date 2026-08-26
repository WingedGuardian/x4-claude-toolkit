r"""The profile `content.xml` is a DECISION LOG, not an inventory of what is installed.

MEASURED 2026-08-23 against the live profile and `extensions\`:

    <extension> entries in the profile          348
      ...FOSSILS - no matching folder on disk   287  (82.5%)
    real mods on disk (123 folders - 8 ego_dlc) 115
      ...ABSENT from the profile entirely        54  (47.0%)
    on-disk mods the profile actually disables    1  (escape_pod)

So the profile agrees with disk on 61 of 348 entries and is silent about nearly
half of what is installed. It is neither an allow-list nor a deny-list.

THE SEMANTIC THESE PIN, and why it is load-bearing:

  *Absent from the profile does NOT mean disabled.* X4 reconciles against disk
  and adds a folder it has not seen as ENABLED (CLAUDE.md #16). `mods("active")`
  therefore reads `prof.get(m["id"], True)` -- default TRUE.

  Invert that default and **54 of 115 installed mods silently vanish** from every
  active-scope consumer at once: Tier B, x4compat, x4effective, BaseX `x4eff`.
  Nothing would raise; the world model would just get quietly smaller. That is
  the exact silent-narrowing shape the BLIND-SPOTS register exists to police, and
  it is the mirror image of the defect `test_mod_scope_is_explicit.py` pins --
  that one was "modelled the running game from the disk", this one would be
  "modelled the running game from a decision log with 82.5% fossils".

  The profile is keyed by MANIFEST ID, never by folder name and never by display
  name (MEASURED: 60 of 123 on-disk mods match by manifest id, only 9 by folder
  name). A name-based lookup finding nothing is the WRONG QUERY, not evidence.
  This trap fired for real on 2026-08-23: `grep -i xspvro` on the profile returns
  nothing -- because its entry is `ws_3691358137` -- and that zero was nearly
  written up as "no ban record exists", which would have destroyed a correct
  permanent record and reported a real safety protection as absent.

Every test here was verified to FAIL against the inverted behaviour (default
False / matching by folder name) before being committed. See CLAUDE.md #30.
"""

import types

import pytest

from x4validate import _registry


def _installed(*entries) -> list[dict]:
    """Minimal shapes of what `scan_installed` returns: (id, enabled)."""
    return [{"id": mid, "enabled": enabled, "folder": folder}
            for mid, enabled, folder in entries]


@pytest.fixture
def world(monkeypatch):
    """An on-disk set of three mods; the profile is supplied per-test."""
    def _build(profile_pairs):
        monkeypatch.setattr(
            _registry, "scan_installed",
            lambda *a, **k: _installed(
                ("ws_3616342050", True, "amphitrite"),   # id != folder name
                ("escape_pod", True, "escape_pod"),      # id == folder name
                ("moreroomsforships", True, "moreroomsforships"),
            ))
        monkeypatch.setattr(_registry, "ingest_content_xml",
                            lambda *a, **k: profile_pairs)
        return lambda scope: {m["id"] for m in _registry.mods(scope)}
    return _build


def test_a_mod_ABSENT_from_the_profile_is_still_ACTIVE(world):
    """54 of 115 real mods are absent. They load. The default must be True."""
    ids = world([])("active")
    assert ids == {"ws_3616342050", "escape_pod", "moreroomsforships"}, (
        "a mod the profile has never seen must count as ACTIVE -- X4 adds an "
        "unseen folder as enabled. Defaulting to False would silently drop "
        "54 of 115 installed mods from every active-scope tool at once.")


def test_a_mod_the_profile_DISABLES_is_not_active(world):
    """The one thing the profile does authoritatively say."""
    ids = world([("escape_pod", False)])("active")
    assert "escape_pod" not in ids
    assert ids == {"ws_3616342050", "moreroomsforships"}


def test_the_profile_is_keyed_by_MANIFEST_ID_not_FOLDER_NAME(world):
    """The xspvro trap, pinned.

    `amphitrite` is the FOLDER; `ws_3616342050` is the manifest id. A profile
    entry naming the folder must not be able to disable the mod, because that is
    not how the engine keys it -- and, read the other way, a name-shaped lookup
    that finds nothing has proved nothing.
    """
    ids = world([("amphitrite", False)])("active")
    assert "ws_3616342050" in ids, (
        "matching by folder name must not disable a mod whose manifest id "
        "differs -- the profile keys by manifest id (60 of 123 vs 9 of 123)")

    # ...and the same id, correctly spelled, DOES disable it.
    ids = world([("ws_3616342050", False)])("active")
    assert "ws_3616342050" not in ids


def test_installed_scope_ignores_the_profile_entirely(world):
    """"What is on disk" must not be filtered by a decision log."""
    ids = world([("escape_pod", False), ("ws_3616342050", False)])("installed")
    assert ids == {"ws_3616342050", "escape_pod", "moreroomsforships"}


def test_an_unreadable_profile_FAILS_OPEN(monkeypatch, world):
    """No readable profile means we cannot know what is off -- so assume nothing
    is. The opposite (fail closed) would EMPTY the world model on any machine
    without a profile, and report that emptiness as fact."""
    monkeypatch.setattr(_registry, "scan_installed",
                        lambda *a, **k: _installed(("solo", True, "solo")))

    def _boom(*a, **k):
        raise OSError("no profile here")

    monkeypatch.setattr(_registry, "ingest_content_xml", _boom)
    assert {m["id"] for m in _registry.mods("active")} == {"solo"}

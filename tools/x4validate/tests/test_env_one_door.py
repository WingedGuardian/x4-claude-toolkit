r"""One door for every setting: the layered resolver, never `os.environ` directly.

**The defect this pins (2.5.0).** `_paths` resolves every location through LAYERS —
real environment, then `.claude/x4-paths.env`, then a local fallback. Two consumers
bypassed it and read `os.environ` directly, so a value written into the config file
was invisible to them:

  * `_nexus.nexus_key()` — and `setup.sh` explicitly tells users they may put
    `X4_NEXUS_KEY` in `.claude/x4-paths.env`. Following our own documentation
    produced "X4_NEXUS_KEY not set".
  * `_effective` — worse, it read `os.environ` at IMPORT time into the module
    constant `DB_PATH`, which is then an argparse default. `gates/_env.py` mean-
    while resolved the same variable through `_paths`. **Two doors to one
    question**: the gates and the CLI could disagree about which store is
    configured, which is the same shape as the nested-patch defect (F30).

The distinction between `value()` and `path_value()` is not cosmetic. `_pick()`
runs `native()` on what it returns, translating a POSIX drive path (`/c/x`) into
`C:/x`. That is right for a path and WRONG for a secret — an API key is not a path
and must come back byte-for-byte.
"""

from __future__ import annotations

import pytest

from x4validate import _paths

#: Every name these tests care about, including the two the older `test_paths.py`
#: fixture has no reason to know about. A key left un-deleted here would be read
#: from the developer's real environment and the assertion would pass by accident.
KEYS = ("X4_TOOLKIT", "X4_GAME", "X4_GAME_ROOT", "X4_EXTENSIONS", "X4_GAME_EXTENSIONS",
        "X4_REFERENCE", "X4_PROFILE", "X4_REGISTRY", "X4_MODS", "X4_DEBUGLOG",
        "X4_NEXUS_KEY", "X4_EFFECTIVE_DB")


@pytest.fixture
def clean(monkeypatch, tmp_path):
    """No env vars, no fallbacks, no discoverable config file."""
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(_paths, "_LOCAL_FALLBACK", {})
    monkeypatch.setattr(_paths, "_find_env_file", lambda: None)
    _paths.reload()
    yield tmp_path
    _paths.reload()


def _write_env(tmp_path, body: str, monkeypatch):
    """Make a config file the one `_paths` will find."""
    path = tmp_path / "toolkit" / ".claude" / "x4-paths.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(_paths, "_find_env_file", lambda: path)
    _paths.reload()
    return path


# --- the helper itself ------------------------------------------------------

def test_value_reads_the_config_file_layer(clean, monkeypatch):
    _write_env(clean, 'X4_NEXUS_KEY="secret-from-file"\n', monkeypatch)
    assert _paths.value("X4_NEXUS_KEY") == "secret-from-file"


def test_value_prefers_a_real_environment_variable(clean, monkeypatch):
    _write_env(clean, 'X4_NEXUS_KEY="from-file"\n', monkeypatch)
    monkeypatch.setenv("X4_NEXUS_KEY", "from-env")
    assert _paths.value("X4_NEXUS_KEY") == "from-env"


def test_value_is_none_when_nothing_defines_it(clean):
    assert _paths.value("X4_NEXUS_KEY") is None


def test_value_does_not_path_translate_a_secret(clean, monkeypatch):
    """A key that happens to look like a POSIX drive path must survive intact.

    `_pick()` would return `C:/deadbeef` here. Silent corruption of a credential
    is exactly the kind of "helpful" transformation that produces a 401 nobody
    can explain.
    """
    monkeypatch.setenv("X4_NEXUS_KEY", "/c/deadbeef")
    assert _paths.value("X4_NEXUS_KEY") == "/c/deadbeef"


def test_path_value_does_translate_a_posix_drive_path(clean, monkeypatch):
    """The counterpart to the test above: a PATH may be translated, a key may not.

    Forces the Windows branch through the `_IS_WINDOWS` seam so the assertion is
    about `path_value`'s CONTRACT rather than about which machine is running it.
    Off Windows `native()` correctly leaves `/c/...` alone -- it is a legitimate
    absolute path there -- so without the seam this test asserted a falsehood on
    Linux and failed for a reason that said nothing about the code.
    """
    monkeypatch.setattr(_paths, "_IS_WINDOWS", True)
    monkeypatch.setenv("X4_EFFECTIVE_DB", "/c/store/effective.sqlite")
    assert str(_paths.path_value("X4_EFFECTIVE_DB")).replace("\\", "/") == \
        "C:/store/effective.sqlite"


# --- the two consumers that used to bypass it -------------------------------

def test_nexus_key_is_found_in_the_config_file(clean, monkeypatch):
    """`setup.sh` documents this exact placement; it used to be ignored."""
    _write_env(clean, 'X4_NEXUS_KEY="key-in-config-file"\n', monkeypatch)
    from x4validate import _nexus
    assert _nexus.nexus_key() == "key-in-config-file"


def test_nexus_key_absent_everywhere_still_raises(clean):
    from x4validate import _nexus
    with pytest.raises(_nexus.NexusError):
        _nexus.nexus_key()


def test_effective_db_is_found_in_the_config_file(clean, monkeypatch):
    """Resolved on CALL, not bound at import — and through the same one door.

    Windows branch forced via the seam, for the reason given on
    `test_path_value_does_translate_a_posix_drive_path`.
    """
    monkeypatch.setattr(_paths, "_IS_WINDOWS", True)
    _write_env(clean, 'X4_EFFECTIVE_DB="/c/store/effective.sqlite"\n', monkeypatch)
    from x4validate import _effective
    got = _effective.effective_db()
    assert got is not None
    assert str(got).replace("\\", "/") == "C:/store/effective.sqlite"


def test_effective_db_and_the_gates_agree(clean, monkeypatch):
    """One question, one answer. These two used to resolve independently."""
    _write_env(clean, 'X4_EFFECTIVE_DB="/c/store/effective.sqlite"\n', monkeypatch)
    from x4validate import _effective
    assert _effective.effective_db() == _paths.path_value("X4_EFFECTIVE_DB")

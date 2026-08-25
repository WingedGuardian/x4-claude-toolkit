r"""W2 — the installed toolkit must actually be wired up.

Shipped defect (v2.0): `install.sh`/`install.ps1` write `X4_GAME`, `X4_EXTENSIONS`,
`X4_PROFILE`, `X4_MODS` into `.claude/x4-paths.env`; the Python package read
`X4_GAME_EXTENSIONS`, `X4_PROFILE_CONTENT`, `X4_PROFILE_EXTENSIONS`,
`X4_WORKSHOP_CONTENT`, `X4_REGISTRY`. The overlap was exactly ONE name
(`X4_REFERENCE`) and nothing bridged the two sets, so a successful install left
every cross-mod command silently pointed at CWD-relative paths.

`_paths` resolves in layers — real env, then the config file, then dev-machine
fallbacks — trying every alias and derivation *within* a layer before dropping to
the next. The layering is the subtle part and has its own test: flattening the
layers into one dict lets a fallback outrank a variable the user really exported.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from x4validate import _paths

ALL_KEYS = ("X4_TOOLKIT", "X4_GAME", "X4_GAME_ROOT", "X4_EXTENSIONS", "X4_GAME_EXTENSIONS",
            "X4_REFERENCE", "X4_PROFILE", "X4_PROFILE_CONTENT", "X4_PROFILE_EXTENSIONS",
            "X4_WORKSHOP_CONTENT", "X4_REGISTRY", "X4_MODS", "X4_DEBUGLOG")


@pytest.fixture
def clean(monkeypatch, tmp_path):
    """No env vars, no fallbacks, and NO config file discoverable.

    All three have to be pinned or the real machine leaks in and the assertions
    become accidental truths. `_find_env_file` is stubbed rather than pointed at an
    empty directory because it walks up from the CWD — a real `x4-paths.env` in some
    ancestor would otherwise silently supply values mid-test.
    """
    for k in ALL_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(_paths, "_LOCAL_FALLBACK", {})
    monkeypatch.setattr(_paths, "_find_env_file", lambda: None)
    _paths.reload()
    yield tmp_path
    _paths.reload()


def _write_env(tmp_path, body: str, monkeypatch) -> Path:
    """Make a config file the one that `_paths` will find."""
    toolkit = tmp_path / "toolkit"
    (toolkit / ".claude").mkdir(parents=True, exist_ok=True)
    path = toolkit / ".claude" / "x4-paths.env"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(_paths, "_find_env_file", lambda: path)
    _paths.reload()
    return toolkit


# --- layer 1: env vars, both naming schemes ---------------------------------

def _abs(*parts: str) -> str:
    r"""An absolute path literal that is absolute on the RUNNING platform.

    `D:\X4` is a drive-absolute path on Windows and a single RELATIVE filename on
    POSIX — so `Path(r"D:\X4").parent` is `.`, and every DERIVATION assertion
    below (root-from-extensions, workshop-from-game-root) collapses into a
    tautology instead of failing loudly. MEASURED on ubuntu CI (run
    32677055434): four tests here failed exactly that way, e.g.
    `PosixPath('D:\\X4/extensions') != PosixPath('D:\\X4\\extensions')`.

    Windows normalises `/` to `\` inside `Path`, so `Path(_abs("X4"))` still
    equals `Path(r"D:\X4")` there — the Windows assertions are unchanged in
    meaning, and the same test finally exercises the real logic on Linux.
    """
    root = "D:/" if os.name == "nt" else "/d/"
    return root + "/".join(parts)


def test_installer_names_are_understood(clean, monkeypatch):
    """The whole point: these are what install.sh writes and the docs teach."""
    monkeypatch.setenv("X4_GAME", _abs("X4"))
    monkeypatch.setenv("X4_PROFILE", _abs("prof"))
    monkeypatch.setenv("X4_MODS", _abs("mods"))
    assert _paths.game_root() == Path(_abs("X4"))
    assert _paths.game_extensions() == Path(_abs("X4", "extensions"))
    assert _paths.profile_content() == Path(_abs("prof", "content.xml"))
    assert _paths.profile_extensions() == Path(_abs("prof", "extensions"))
    assert _paths.registry() == Path(_abs("mods", "_registry", "modlist.yaml"))
    assert _paths.debug_log() == Path(_abs("prof", "debug.txt"))


def test_legacy_names_still_work(clean, monkeypatch):
    """Nothing that works today may break."""
    monkeypatch.setenv("X4_GAME_EXTENSIONS", _abs("X4", "extensions"))
    monkeypatch.setenv("X4_PROFILE_CONTENT", _abs("prof", "content.xml"))
    monkeypatch.setenv("X4_REGISTRY", _abs("r.yaml"))
    assert _paths.game_extensions() == Path(_abs("X4", "extensions"))
    assert _paths.game_root() == Path(_abs("X4")), "derive the root from the legacy extensions var"
    assert _paths.profile_content() == Path(_abs("prof", "content.xml"))
    assert _paths.registry() == Path(_abs("r.yaml"))


def test_installer_name_wins_over_legacy(clean, monkeypatch):
    monkeypatch.setenv("X4_EXTENSIONS", r"D:\new\extensions")
    monkeypatch.setenv("X4_GAME_EXTENSIONS", r"D:\old\extensions")
    assert _paths.game_extensions() == Path(r"D:\new\extensions")


# --- layer 2: the config file the installer writes --------------------------

def test_config_file_is_used_when_nothing_is_exported(clean, monkeypatch):
    """The common case — a plain shell exports none of these."""
    _write_env(clean, 'X4_GAME="D:/game"\nX4_PROFILE="D:/prof"\n', monkeypatch)
    assert _paths.game_root() == Path("D:/game")
    assert _paths.profile_content() == Path("D:/prof/content.xml")


def test_a_real_env_var_beats_the_config_file(clean, monkeypatch):
    _write_env(clean, 'X4_GAME="D:/from-file"\n', monkeypatch)
    monkeypatch.setenv("X4_GAME", r"D:\from-env")
    assert _paths.game_root() == Path(r"D:\from-env")


def test_parse_handles_quotes_comments_export_and_expansion(tmp_path):
    f = tmp_path / "x4-paths.env"
    f.write_text(
        '# a comment\n'
        '\n'
        'X4_TOOLKIT="/opt/kit"\n'
        "export X4_GAME='/games/X4'\n"
        'X4_REFERENCE="$X4_TOOLKIT/reference"\n'
        'X4_MODS=${X4_TOOLKIT}/mods\n'
        'X4_PROFILE=""\n'
        'NOT_OURS="ignored"\n',
        encoding="utf-8")
    got = _paths.parse_env_file(f)
    assert got["X4_GAME"] == "/games/X4"
    assert got["X4_REFERENCE"] == "/opt/kit/reference", "$VAR must expand like a shell would"
    assert got["X4_MODS"] == "/opt/kit/mods", "${VAR} form too"
    assert "X4_PROFILE" not in got, "an empty value is not a configured value"
    assert "NOT_OURS" not in got


def test_an_unreadable_config_file_is_just_no_config(tmp_path):
    assert _paths.parse_env_file(tmp_path / "nope.env") == {}


# --- layer 3: fallbacks, and the precedence trap ----------------------------

def test_a_fallback_never_outranks_a_real_env_var(clean, monkeypatch):
    """THE precedence pin.

    Flattening the layers into one dict makes `_LOCAL_FALLBACK["X4_GAME"]` beat a
    real `$X4_GAME_EXTENSIONS`, because within a single dict `X4_GAME` is simply
    tried first. Resolution must exhaust the higher layer — aliases AND derivations
    — before consulting the next one.
    """
    monkeypatch.setattr(_paths, "_LOCAL_FALLBACK", {"X4_GAME": _abs("dev-machine", "X4")})
    monkeypatch.setenv("X4_GAME_EXTENSIONS", _abs("real", "extensions"))
    assert _paths.game_root() == Path(_abs("real")), \
        "the user's exported legacy var must win over a dev-machine fallback"
    assert _paths.game_extensions() == Path(_abs("real", "extensions"))


def test_fallback_applies_only_when_nothing_else_answers(clean, monkeypatch):
    monkeypatch.setattr(_paths, "_LOCAL_FALLBACK", {"X4_GAME": r"C:\fallback\X4"})
    assert _paths.game_root() == Path(r"C:\fallback\X4")


def test_unresolved_is_none_not_a_guess(clean):
    """Every location must be able to say "I don't know"."""
    assert _paths.game_root() is None
    assert _paths.reference() is None
    assert _paths.profile() is None
    assert _paths.registry() is None


# --- derivations ------------------------------------------------------------

def test_workshop_is_derived_only_from_a_real_steam_layout(clean, monkeypatch):
    monkeypatch.setenv("X4_GAME", _abs("Steam", "steamapps", "common", "X4 Foundations"))
    assert _paths.workshop_content() == Path(
        _abs("Steam", "steamapps", "workshop", "content", "392160"))


def test_workshop_is_not_invented_for_a_relocated_install(clean, monkeypatch):
    """A guessed path scans nothing and reports "no mods", which reads as fact."""
    monkeypatch.setenv("X4_GAME", r"D:\Games\X4")
    assert _paths.workshop_content() is None


def test_env_changes_are_picked_up_without_an_explicit_reload(clean, monkeypatch):
    """Only the FILE is cached; a cache that ignores a fresh env var is the same
    class of silent misconfiguration this module exists to end."""
    monkeypatch.setenv("X4_GAME", r"D:\first")
    assert _paths.game_root() == Path(r"D:\first")
    monkeypatch.setenv("X4_GAME", r"D:\second")
    assert _paths.game_root() == Path(r"D:\second")


# --- Git Bash / WSL path styles -------------------------------------------------

def test_msys_drive_paths_are_translated_on_windows(clean, monkeypatch):
    r"""RED-TEAM FINDING (2026-07-29), and the v2.0 bug in a new form.

    `install.sh` detects Steam at `/c/Program Files (x86)/Steam` under Git Bash, and
    the config file explicitly promises both styles work. Python cannot open
    `/c/...` on Windows — `Path()` turns it into `\c\...`, which does not exist. So
    the first command the README gives a Windows user wrote a config the Python
    silently could not use: a successful install pointing at nothing.
    """
    monkeypatch.setattr(_paths, "_IS_WINDOWS", True)
    monkeypatch.setenv("X4_GAME", "/c/Program Files (x86)/Steam/steamapps/common/X4 Foundations")
    assert _paths.game_root() == Path(r"C:/Program Files (x86)/Steam/steamapps/common/X4 Foundations")
    assert _paths.game_extensions() == Path(
        r"C:/Program Files (x86)/Steam/steamapps/common/X4 Foundations/extensions")


def test_wsl_drive_paths_are_translated_before_the_msys_shape(clean, monkeypatch):
    """`/mnt/c/x` also matches the MSYS pattern as drive 'm' + 'nt/c/x'. Order matters."""
    monkeypatch.setattr(_paths, "_IS_WINDOWS", True)
    monkeypatch.setenv("X4_GAME", "/mnt/d/Games/X4")
    assert _paths.game_root() == Path("D:/Games/X4")


def test_posix_paths_are_untouched_off_windows(clean, monkeypatch):
    """On Linux `/c/...` is a legitimate absolute path and must survive verbatim."""
    monkeypatch.setattr(_paths, "_IS_WINDOWS", False)
    monkeypatch.setenv("X4_GAME", "/c/games/X4")
    assert _paths.game_root() == Path("/c/games/X4")


def test_native_windows_paths_are_left_alone(clean, monkeypatch):
    monkeypatch.setattr(_paths, "_IS_WINDOWS", True)
    monkeypatch.setenv("X4_GAME", r"D:\Games\X4")
    assert _paths.game_root() == Path(r"D:\Games\X4")


def test_describe_names_the_config_file_and_every_location(clean, monkeypatch):
    _write_env(clean, 'X4_GAME="D:/game"\n', monkeypatch)
    out = "\n".join(_paths.describe())
    assert "x4-paths.env" in out
    for label in ("game", "extensions", "reference", "profile", "registry", "debug log"):
        assert label in out


def test_native_translation_is_steered_by_a_module_seam_not_global_os(monkeypatch):
    """The platform must be steerable WITHOUT patching the shared `os` module.

    THE DEFECT THIS PINS (MEASURED 2026-08-24, ubuntu CI run 32677055434). Three
    tests here patched `name` on the `os` module reached through `_paths`. That
    edits the GLOBAL `os`, not a `_paths` attribute -- and `pathlib` dispatches
    its flavour on `os.name`, so on Linux the very next `Path(...)` raised
    `UnsupportedOperation: cannot instantiate 'WindowsPath' on your system`. One
    of the three failed outright; the other two passed by luck, depending on
    whether a `Path` happened to be constructed while the patch was live.

    A test that reaches around a module into a shared global is not testing a
    seam, it is editing the interpreter. `_IS_WINDOWS` is the seam, and this test
    exercises BOTH directions on every platform -- which is the point: the
    translation's behaviour is now assertable on Linux, where it could not
    previously even be examined.
    """
    monkeypatch.setattr(_paths, "_IS_WINDOWS", True)
    assert _paths.native("/c/games/X4") == "C:/games/X4"
    assert _paths.native("/mnt/d/Games/X4") == "D:/Games/X4"
    assert _paths.native(r"C:\already\native") == r"C:\already\native"

    monkeypatch.setattr(_paths, "_IS_WINDOWS", False)
    assert _paths.native("/c/games/X4") == "/c/games/X4", (
        "on POSIX, /c/... is a legitimate absolute path and must be left alone")
    assert _paths.native("/mnt/d/Games/X4") == "/mnt/d/Games/X4"


def test_the_profile_debuglog_fallback_follows_the_PLATFORM(monkeypatch):
    """`--profile <id>` must resolve where the installer actually writes.

    `_cli` hardcoded `~/Documents/Egosoft/X4/<id>/debug.txt` -- the Windows
    layout -- unconditionally, so the bare `--profile` fallback could never work
    on Linux or macOS, both of which the README documents as supported.
    `install.sh:107` already uses `~/.config/EgoSoft/X4` off Windows, so the
    shell half knew something the Python half did not.

    Asserted through the seam in BOTH directions, so the branch that does not
    match the running machine is still covered -- which is the whole reason the
    seam exists.
    """
    from x4validate import _cli

    monkeypatch.setattr(_paths, "_IS_WINDOWS", True)
    assert _cli.default_debug_log("12345678") == (
        Path.home() / "Documents" / "Egosoft" / "X4" / "12345678" / "debug.txt")

    monkeypatch.setattr(_paths, "_IS_WINDOWS", False)
    assert _cli.default_debug_log("12345678") == (
        Path.home() / ".config" / "EgoSoft" / "X4" / "12345678" / "debug.txt")

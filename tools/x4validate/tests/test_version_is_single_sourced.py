"""The package version and pyproject's must agree.

MEASURED 2026-09-01: pyproject said 3.0.0 while `x4validate.__version__` still said
2.9.0, and nothing noticed -- a release cut from that tree would have reported the
previous version to anyone who asked the package, which is what a user's bug report
quotes. Two places holding one fact drift silently; a test is the cheapest join.
"""
import pathlib
import sys

try:
    import tomllib
except ModuleNotFoundError:                      # 3.10
    import tomli as tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _pyproject_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_package_version_matches_pyproject():
    import x4validate
    assert x4validate.__version__ == _pyproject_version(), (
        "x4validate.__version__ is %s but pyproject.toml says %s"
        % (x4validate.__version__, _pyproject_version()))


def test_uv_lock_records_the_same_version():
    """The lock is a THIRD copy, and `uv run --frozen` (which CI uses) reads it. It has
    been forgotten twice already -- commits "uv.lock: follow the 2.8.0 version bump" and
    "uv.lock: record version 2.1.1" -- because this test joined only pyproject and
    __init__. A release that bumps the first two and not this one ships a lock that
    disagrees with the package it locks."""
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    ours = [p for p in lock.get("package", []) if p.get("name") == "x4validate"]
    assert len(ours) == 1, "expected exactly one x4validate package entry, got %d" % len(ours)
    assert ours[0]["version"] == _pyproject_version(), (
        "uv.lock says %s but pyproject.toml says %s -- run `uv lock` after a version bump"
        % (ours[0]["version"], _pyproject_version()))


def test_the_version_is_a_release_shaped_string():
    # Guards the failure mode where someone "fixes" the mismatch by blanking one.
    v = _pyproject_version()
    parts = v.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), v

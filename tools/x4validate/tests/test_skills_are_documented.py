"""Every shipped skill must appear in the README.

Nothing pinned this, and it drifted: `x4-balance` and `x4-probe` shipped in
`.claude/skills/` while the README listed five of the seven. A user cannot invoke a
skill they have never been told exists, so an undocumented skill is a shipped feature
that does nothing.

The list is DERIVED from the directory, never restated here -- otherwise this file
becomes a third copy that drifts on its own.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
SKILLS = ROOT / ".claude" / "skills"
README = ROOT / "README.md"


def shipped() -> list[str]:
    return sorted(d.name for d in SKILLS.iterdir()
                  if d.is_dir() and (d / "SKILL.md").is_file())


def test_the_skills_directory_is_readable():
    # A parse returning nothing must not be able to report "all documented".
    names = shipped()
    assert len(names) >= 5, "skills directory looks unreadable: %s" % names


def test_every_shipped_skill_is_in_the_readme():
    text = README.read_text(encoding="utf-8")
    missing = [n for n in shipped() if ("/" + n) not in text]
    assert not missing, (
        "shipped but undocumented -- a user cannot invoke what they are not told about: %s"
        % missing)


def test_the_readme_does_not_advertise_a_skill_that_is_not_shipped():
    import re
    text = README.read_text(encoding="utf-8")
    advertised = set(re.findall(r"`/(x4-[a-z-]+)`", text))
    ghosts = sorted(advertised - set(shipped()))
    assert not ghosts, "documented but not shipped: %s" % ghosts

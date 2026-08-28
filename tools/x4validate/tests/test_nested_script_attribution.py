"""F70 coverage: validate a nested cross-mod script patch through its MERGED result.

Both halves of `_xsd.validate_mod` filter `count("/") != 1`, so a patch at
`<mymod>/extensions/<target>/md/foo.xml` is validated by nothing. The fix is not to
widen those selectors but to validate the document the ENGINE actually builds --
target + patch merged -- which also dissolves the depth problem.

⚠ THE ATTRIBUTION DIFF IS NOT A REFINEMENT, IT IS THE CHECK. MEASURED 2026-08-27 over
all 16 nested patches in the installed set: validating only the merged result yields
**182 findings, of which 167 (91.8%) belong to the TARGET, not the patcher** --
`mdscript name='moreroomsforships'` fails md.xsd's `[A-Z]` pattern because its own
author named it that. A checker that reports those floods, and a check that floods is
worse than no check. Diffing both sides leaves **15 introduced and 1 fixed**.

The `fixed` direction is what proves the check can go red in both directions: the one
real fix in the corpus (`find_ship` missing the required `space`) shows up as fixed,
independently reproducing a result the mod session got by a different route.

Findings are keyed by MESSAGE, never by line: a patch shifts line numbers, and a
line-keyed diff would report every inherited finding as both removed and added.
"""
from pathlib import Path

import pytest

from x4validate import _merge, _xsd

_TINY_XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="root">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="allowed" minOccurs="0" maxOccurs="unbounded"/>
      </xs:sequence>
      <xs:attribute name="req" type="xs:string" use="required"/>
    </xs:complexType>
  </xs:element>
</xs:schema>'''

_HDR = ('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="test.xsd"')


def _world(tmp_path, target_doc: str | None, patch_ops: str,
           target_folder="target", patch_at="target"):
    """Build a reference tree, a target mod and a patcher mod. Returns (cfg, dirs)."""
    lib = tmp_path / "reference" / "libraries"
    lib.mkdir(parents=True)
    (lib / "test.xsd").write_text(_TINY_XSD, encoding="utf-8")

    dirs = {}
    if target_doc is not None:
        tgt = tmp_path / "exts" / target_folder / "md"
        tgt.mkdir(parents=True)
        (tgt / "foo.xml").write_text(target_doc, encoding="utf-8")
        dirs[target_folder.lower()] = tmp_path / "exts" / target_folder

    pat = tmp_path / "exts" / "patcher" / "extensions" / patch_at / "md"
    pat.mkdir(parents=True)
    (pat / "foo.xml").write_text(
        f'<?xml version="1.0" encoding="utf-8"?><diff>{patch_ops}</diff>',
        encoding="utf-8")
    return _merge.Config(reference=tmp_path / "reference"), dirs


def test_a_finding_the_target_already_had_is_NOT_blamed_on_the_patcher(tmp_path):
    """The whole point. 167 of 182 real findings are this case."""
    cfg, dirs = _world(tmp_path,
                       f'<root {_HDR}/>',                       # target: missing req
                       '<add sel="/root"><allowed/></add>')     # patch: harmless
    r = _xsd.validate_nested_scripts(tmp_path / "exts" / "patcher", cfg, dirs)
    assert r.checked == 1
    assert r.introduced == [], "the target's own error must not be attributed here"


def test_a_finding_the_patch_ADDS_is_reported(tmp_path):
    cfg, dirs = _world(tmp_path,
                       f'<root {_HDR} req="x"/>',               # target: valid
                       '<add sel="/root"><notallowed/></add>')  # patch breaks it
    r = _xsd.validate_nested_scripts(tmp_path / "exts" / "patcher", cfg, dirs)
    assert r.checked == 1
    assert len(r.introduced) == 1
    assert "not expected" in r.introduced[0].message


def test_a_finding_the_patch_REMOVES_is_reported_as_fixed(tmp_path):
    """Proves the check can go red in BOTH directions -- see gotcha #26."""
    cfg, dirs = _world(tmp_path,
                       f'<root {_HDR}/>',                       # target: missing req
                       '<add sel="/root" type="@req">x</add>')  # patch supplies it
    r = _xsd.validate_nested_scripts(tmp_path / "exts" / "patcher", cfg, dirs)
    assert r.introduced == []
    assert len(r.fixed) == 1
    assert "req" in r.fixed[0].message


def test_target_mod_absent_is_skipped_with_that_reason(tmp_path):
    """The engine no-ops this too, so it is not the patcher's defect."""
    cfg, dirs = _world(tmp_path, None, '<add sel="/root"><allowed/></add>')
    r = _xsd.validate_nested_scripts(tmp_path / "exts" / "patcher", cfg, dirs)
    assert r.checked == 0 and r.introduced == []
    assert len(r.skips) == 1
    vpath, reason = r.skips[0]
    assert "not installed" in reason.lower()


def test_target_present_but_FILE_missing_is_a_DISTINCT_reason(tmp_path):
    """MEASURED in the live set: `ship_variation_expansion_vro` patches
    `extensions/ship_variation_expansion/md/spawnclaymore.xml`, and that mod IS
    installed but ships 7 md files, none of them that one. A stale patch against an
    older version of its target -- a SILENT no-op with no engine error. Reporting it
    the same way as an absent mod would bury a real defect in an expected one."""
    cfg, dirs = _world(tmp_path, f'<root {_HDR} req="x"/>',
                       '<add sel="/root"><allowed/></add>')
    # target exists, but the patch aims at a document it does not supply
    other = tmp_path / "exts" / "patcher" / "extensions" / "target" / "md"
    (other / "foo.xml").rename(other / "absent.xml")
    r = _xsd.validate_nested_scripts(tmp_path / "exts" / "patcher", cfg, dirs)
    assert r.checked == 0
    assert len(r.skips) == 1
    _vpath, reason = r.skips[0]
    assert "does not supply" in reason.lower(), reason
    assert "not installed" not in reason.lower(), "must not read as an absent mod"

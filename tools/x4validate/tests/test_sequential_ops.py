r"""A diff's ops are applied in order, against a tree the earlier ops have changed.

The validator evaluated every op against the tree as it stood BEFORE the mod's
own ops, so a file that removes a node and then edits it read as clean:

    <remove  sel=".../connection[@name='con_room_001']" />
    <replace sel=".../connection[@name='con_room_001']/offset/position/@y">
    <replace sel=".../connection[@name='con_room_001']/offset/position/@x">

The engine reported "No matching node" for both replaces. We reported nothing —
found only by diffing our predictions against the engine log per item
(`x4debug crosscheck`), which is what that tool exists for.

MEASURED over all 113 installed mods: 4,389 mod XML files, 2,649 diffs, 161
containing a `<remove>`, and **1** where a later op selects into a removed
subtree. So the yield is small and the blast radius is smaller. The reason to fix
it anyway is structural: `_check_ops` was a SECOND implementation of "does this
op apply", running parallel to `_merge.apply_diff` — which already applies ops in
document order and returns exactly the per-op verdict this check needs. Two
independent paths answering one question, now demonstrably disagreeing, is the
shape the blind-spot register was built around.

NB the population figure above is a literal prefix match, so it is a FLOOR: an op
can select into a removed subtree by a differently-spelled XPath. The full-corpus
differential is the measurement that binds.
"""

from lxml import etree

from x4validate import _check, _merge


def _run(base_xml: str, diff_xml: str) -> _check.Report:
    report = _check.Report()
    tree = etree.fromstring(base_xml.encode())
    diff = etree.fromstring(diff_xml.encode())
    _check._check_ops(diff, tree, "assets/units/size_l/thing.xml", report)
    return report


BASE = """<components>
  <component name="thing">
    <connections>
      <connection name="con_room_001"><offset><position x="1" y="2" z="3"/></offset></connection>
      <connection name="con_room_002"><offset><position x="4" y="5" z="6"/></offset></connection>
    </connections>
  </component>
</components>"""


def test_a_replace_after_its_targets_removal_is_reported():
    """The live case, reduced. Both replaces target a node the diff just deleted."""
    report = _run(BASE, """<diff>
      <remove sel="/components/component/connections/connection[@name='con_room_001']"/>
      <replace sel="/components/component/connections/connection[@name='con_room_001']/offset/position/@x">9</replace>
      <replace sel="/components/component/connections/connection[@name='con_room_001']/offset/position/@y">9</replace>
    </diff>""")
    misses = [f for f in report.findings if "matched nothing" in f.message]
    assert len(misses) == 2, (
        "both replaces target a node the diff itself removed one op earlier — the "
        f"engine skips both; we reported {len(misses)}")
    assert all(f.severity == "error" for f in misses)


def test_an_untouched_sibling_still_matches():
    """The guard against over-correcting: applying ops as we go must not make
    unrelated selectors start failing."""
    report = _run(BASE, """<diff>
      <remove sel="/components/component/connections/connection[@name='con_room_001']"/>
      <replace sel="/components/component/connections/connection[@name='con_room_002']/offset/position/@x">9</replace>
    </diff>""")
    assert not [f for f in report.findings if "matched nothing" in f.message], (
        [f.message for f in report.findings])


def test_an_op_can_target_a_node_an_EARLIER_op_added():
    """The mirror case, and the one that proves this is about ORDER, not removal.

    Evaluating against the pre-mod tree makes this a false ERROR: the node does
    not exist in the base, only after the diff's own <add>. A checker that models
    order must get both directions right, or fixing one breaks the other."""
    report = _run(BASE, """<diff>
      <add sel="/components/component/connections">
        <connection name="con_room_099"><offset><position x="0" y="0" z="0"/></offset></connection>
      </add>
      <replace sel="/components/component/connections/connection[@name='con_room_099']/offset/position/@x">7</replace>
    </diff>""")
    assert not [f for f in report.findings if "matched nothing" in f.message], (
        "the <add> creates the node the <replace> targets; reporting a miss here "
        "would be a FALSE error introduced by the fix")


def test_the_callers_tree_is_not_mutated():
    """`_check_ops` is a CHECK. The merged tree it is handed belongs to the caller
    and is reused; mutating it would silently corrupt every later check in the run
    — a far worse defect than the one being fixed."""
    tree = etree.fromstring(BASE.encode())
    before = etree.tostring(tree)
    _check._check_ops(etree.fromstring(
        b"""<diff><remove sel="/components/component/connections/connection[@name='con_room_001']"/></diff>"""),
        tree, "v.xml", _check.Report())
    assert etree.tostring(tree) == before, "the check mutated the caller's tree"


def test_ambiguous_and_guarded_verdicts_survive_the_change():
    """The three verdicts that already worked must keep working: >1 match gates,
    a false if= guard is a designed no-op, and a silent op only warns."""
    report = _run(BASE, """<diff>
      <replace sel="/components/component/connections/connection/offset/position/@x">9</replace>
      <replace sel="//nope" if="//absolutely-not">9</replace>
    </diff>""")
    msgs = " ".join(f.message for f in report.findings)
    assert "matched 2 nodes" in msgs, msgs
    assert any(f.severity == "info" and "if= is false" in f.message
               for f in report.findings), msgs

#!/usr/bin/env python
r"""A guess must never be laundered into a fact — proven over the real registry.

The defect this exists to prevent, measured 2026-08-09 before the fix: `nexus_id`
held a fuzzy name match and a human-verified id in the SAME field, so a row whose
identity was invented by a search read `settled: stable` / `classification: ready`.
One row pointed at an unrelated author's mod for weeks, and the question that
exposed it — "is my installed pack the old or the new version?" — could not be
answered from our own registry at all.

Unit tests pin each rule in isolation; this asserts the invariants hold over the
whole real modlist, which is where an unmigrated row or a hand-edit shows up.

  A. Nothing derived from an untrusted identity reaches a confident lane.
  B. Every stored id carries provenance, and it is a KNOWN state.
  C. Upstream data never appears without an identity that could have fetched it.
  D. Load -> save -> load is byte-identical (migration is idempotent; a registry
     that churns on every read makes "no change since last run" meaningless).
  E. The denominator is printed. "0 violations" over an unknown population is not
     a result.

Runs entirely against a SANDBOX COPY. A QA sweep that rewrites the user's
registry or regenerates their WORKLIST.md is itself a defect.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402

from x4validate import _registry  # noqa: E402

CONFIDENT_LANES = {"ready", "churning", "predates-9.0", "drop", "custom-local"}


def main() -> int:
    live = _env.registry_file()
    tmp = Path(tempfile.mkdtemp(prefix="x4reg_gate_"))
    sandbox = tmp / "modlist.yaml"
    shutil.copy2(live, sandbox)
    print(f"registry under test (sandbox copy of {live.name}): {sandbox}")

    reg = _registry.load_registry(sandbox)
    mods = reg.get("mods") or []
    active = [m for m in mods if m["auto"].get("installed") and not m["human"].get("ignored")]
    print(f"rows: {len(mods)} tracked, {len(active)} active (installed, not ignored)")

    states = Counter(_registry.identity(m)[2] for m in active)
    trusted = sum(n for s, n in states.items() if s in _registry.TRUSTED_ID_STATES)
    print(f"identity provenance: {trusted}/{len(active)} confirmed")
    for s, n in sorted(states.items()):
        print(f"   {n:4d}  {s}")
    unknown = [s for s in states if s not in _registry.ID_STATES]

    violations: list[str] = []

    # A + B + C, per row.
    for m in active:
        nid, _fid, state = _registry.identity(m)
        a = m["auto"]
        cls = a.get("classification")
        if state not in _registry.TRUSTED_ID_STATES and cls in CONFIDENT_LANES:
            violations.append(
                f"A  {m['id']}: id_state={state} but classification={cls!r} — a guessed "
                f"identity produced a confident verdict")
        if a.get("nexus_id") not in (None, "") and a.get("id_state") not in _registry.ID_STATES:
            violations.append(
                f"B  {m['id']}: stores nexus_id={a.get('nexus_id')} with id_state="
                f"{a.get('id_state')!r}, which is not a known state")
        has_upstream = any(a.get(k) for k in ("version", "updated", "status"))
        if has_upstream and nid is None and state != "off-nexus":
            violations.append(
                f"C  {m['id']}: carries upstream data (v={a.get('version')} "
                f"updated={a.get('updated')}) with no identity to have fetched it")

    if unknown:
        violations.append(f"B  unknown id_state value(s) in the registry: {sorted(unknown)}")

    # D. Idempotence of load+migrate+save.
    before = sandbox.read_bytes()
    _registry.save_registry(reg, sandbox)
    once = sandbox.read_bytes()
    _registry.save_registry(_registry.load_registry(sandbox), sandbox)
    twice = sandbox.read_bytes()
    if once != twice:
        violations.append("D  load->save is not idempotent: a second round-trip changed the file")
    print(f"round-trip: {'migration rewrote the file' if before != once else 'no change'}"
          f", stable on the second pass: {once == twice}")

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if violations:
        print(f"VIOLATIONS: {len(violations)}")
        for v in violations:
            print(f"   {v}")
        return 1
    print(f"OK — {len(active)} active rows, no guessed identity reached a confident lane, "
          f"every stored id carries a known provenance, round-trip stable.")
    if trusted < len(active):
        # Not a failure: unconfirmed identities are the WORK, and the gate's job is
        # to keep them visible rather than to demand they be zero.
        print(f"note: {len(active) - trusted} identities still unconfirmed — "
              f"`x4modlist verify` is the burn-down list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

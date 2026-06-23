"""Mod registry: content.xml ingest, ruamel round-trip I/O (preserve human:), dashboard.

The registry is the canonical store; `auto:` fields are owned by the tool and
refreshed, `human:` fields are owned by the user and NEVER overwritten on merge.
"""

from __future__ import annotations

import os
from pathlib import Path

from lxml import etree
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096  # don't line-wrap long notes

DEFAULT_REGISTRY = Path(os.environ.get(
    "X4_REGISTRY", os.path.join("dev", "_registry", "modlist.yaml")))
PROFILE_CONTENT = Path(os.environ.get(
    "X4_PROFILE_CONTENT", "content.xml"))

# Seed: content-id -> Nexus mod_id already resolved from the batch triage.
SEED_NEXUS_IDS = {
    "kuerteeNPCReactions": 497, "kuerteeEmergentMissions": 780,
    "kuerteeMoreGenericMissions": 622, "kuerteeSurfaceElementTargeting": 710,
    "DeadAirJobs": 1084, "station_combat_rebalance_vro": 1331,
    "lc4hunter_xenon_overhaul": 1132, "tuning_overhaul": 1316,
    "Synthetium_Music": 601, "jupiter_x4_own_radio_stations": 544,
    "ws_2042901274": None,  # SirNukes — Steam-only id; Nexus id TBD
    "ws_1696862840": 305,   # VRO
    "warpscrambler": 1042,
}

AUTO_FIELDS = ("enabled", "source", "nexus_id", "name", "version", "updated",
               "status", "author", "settled", "classification", "checked_at")


def ingest_content_xml(path: Path | None = None) -> list[tuple[str, bool]]:
    """(id, enabled) for every <extension> in the profile content.xml."""
    path = path or PROFILE_CONTENT
    root = etree.parse(str(path)).getroot()
    out = []
    for ext in root.xpath("//extension[@id]"):
        out.append((ext.get("id"), str(ext.get("enabled", "false")).lower() == "true"))
    return out


def _source_of(mod_id: str) -> str:
    return "workshop" if mod_id.startswith("ws_") else "nexus"


def _new_entry(mod_id: str, enabled: bool) -> CommentedMap:
    auto = CommentedMap()
    auto["enabled"] = enabled
    auto["source"] = _source_of(mod_id)
    auto["nexus_id"] = SEED_NEXUS_IDS.get(mod_id)
    for k in ("name", "version", "updated", "status", "author", "settled", "checked_at"):
        auto[k] = None
    auto["classification"] = "untriaged"
    human = CommentedMap()
    human["custom_edited"] = False
    human["ignored"] = False
    human["decision"] = ""
    human["done"] = False
    human["notes"] = ""
    e = CommentedMap()
    e["id"] = mod_id
    e["auto"] = auto
    e["human"] = human
    return e


def _new_registry() -> CommentedMap:
    m = CommentedMap()
    meta = CommentedMap()
    meta["game_build"] = None
    meta["generated"] = None
    m["meta"] = meta
    m["mods"] = CommentedSeq()
    return m


def load_registry(path: Path | None = None) -> CommentedMap:
    path = path or DEFAULT_REGISTRY
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            data = _yaml.load(f)
        if data is not None:
            data.setdefault("mods", CommentedSeq())
            data.setdefault("meta", CommentedMap())
            return data
    return _new_registry()


def save_registry(reg: CommentedMap, path: Path | None = None) -> None:
    path = path or DEFAULT_REGISTRY
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        _yaml.dump(reg, f)


def merge(reg: CommentedMap, content_ids: list[tuple[str, bool]],
          enabled_only: bool = True) -> tuple[int, int]:
    """Add new ids as untriaged; update auto.enabled on existing; PRESERVE human:.

    Returns (added, existing)."""
    by_id = {m["id"]: m for m in reg["mods"]}
    added = existing = 0
    for mod_id, enabled in content_ids:
        if enabled_only and not enabled:
            continue
        if mod_id in by_id:
            by_id[mod_id]["auto"]["enabled"] = enabled  # auto field; human untouched
            existing += 1
        else:
            reg["mods"].append(_new_entry(mod_id, enabled))
            added += 1
    return added, existing


# --- Dashboard generation ---

# Classification reflects what the API can HONESTLY tell us. "9.0-ready" is NOT
# in the API, so we infer from update-date relative to the 9.0 release; old mods
# are "predates-9.0 / review", never auto-claimed compatible.
_LANES = [
    ("ready", "✅ LIKELY 9.0-READY (updated post-9.0, settled)"),
    ("churning", "⏸ CHURNING (updated <14d ago — defer / pin)"),
    ("predates-9.0", "⚠ PREDATES 9.0 — review (compat unconfirmed)"),
    ("drop", "❌ DROP (removed from Nexus)"),
    ("untriaged", "❓ UNTRIAGED (identity unresolved)"),
    ("error", "⚠ ERROR (API fetch failed)"),
]


def _bar(done: int, total: int, width: int = 12) -> str:
    filled = 0 if total == 0 else round(width * done / total)
    return "▓" * filled + "░" * (width - filled)


def needs_review(reg: CommentedMap) -> list:
    """Enabled, non-ignored entries that need a human decision: auto-matched
    (spot-check) or still untriaged."""
    out = []
    for m in reg["mods"]:
        if not m["auto"].get("enabled") or m["human"].get("ignored"):
            continue
        if str(m["auto"].get("resolve") or "").startswith("auto") \
                or m["auto"].get("classification") == "untriaged":
            out.append(m)
    return out


def generate_dashboard(reg: CommentedMap) -> str:
    mods = [m for m in reg["mods"]
            if m["auto"].get("enabled") and not m["human"].get("ignored")]
    ignored = sum(1 for m in reg["mods"]
                  if m["auto"].get("enabled") and m["human"].get("ignored"))
    total = len(mods)
    done = sum(1 for m in mods if m["human"].get("done"))
    build = reg.get("meta", {}).get("game_build") or "?"
    lines = ["# Phase-A Worklist (generated)\n",
             f"**Game build {build}** · {total} active mods "
             f"({ignored} ignored) · {done} done\n",
             f"```\nprogress  {_bar(done, total)}  {done}/{total}\n```\n"]

    review = needs_review(reg)
    if review:
        lines.append(f"## ⚠ NEEDS SPOT-CHECK  ({len(review)})")
        lines.append("Confirm/correct: `x4modlist resolve <id> <nexus_id>` · "
                     "junk → `x4modlist ignore <id>`\n")
        for m in sorted(review, key=lambda x: x["id"]):
            a = m["auto"]
            cur = (f"{a.get('nexus_id')}:{a.get('name')}" if a.get("nexus_id")
                   else "unresolved")
            cands = " | ".join(a.get("candidates") or [])
            lines.append(f"- `{m['id']}` → {cur}" + (f"  ·  candidates: {cands}" if cands else ""))
        lines.append("")

    by_class: dict[str, list] = {}
    for m in mods:
        by_class.setdefault(m["auto"].get("classification", "untriaged"), []).append(m)
    for key, title in _LANES:
        group = by_class.get(key, [])
        if not group:
            continue
        lines.append(f"## {title}  ({len(group)})")
        lines.append("| Mod | id | source | upstream | updated | status |")
        lines.append("|-----|----|--------|----------|---------|--------|")
        for m in sorted(group, key=lambda x: str(x["auto"].get("name") or x["id"])):
            a = m["auto"]
            name = a.get("name") or "—"
            ver = a.get("version") or "—"
            upd = a.get("updated") or "—"
            lines.append(f"| {name} | {m['id']} | {a.get('source')} | {ver} | {upd} | {a.get('status') or '—'} |")
        lines.append("")
    return "\n".join(lines)


def write_dashboard(reg: CommentedMap, path: Path | None = None) -> Path:
    path = path or (DEFAULT_REGISTRY.parent / "WORKLIST.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_dashboard(reg), encoding="utf-8")
    return path

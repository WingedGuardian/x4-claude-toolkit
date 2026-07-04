r"""Mod registry: installed-folder ingest, ruamel round-trip I/O (preserve human:), dashboard.

The registry is the canonical store; `auto:` fields are owned by the tool and
refreshed, `human:` fields are owned by the user and NEVER overwritten on merge.

SOURCE OF TRUTH: the physically INSTALLED extension folders (game-root `extensions\`,
profile `extensions\` if present, Steam Workshop `content\392160\` if present) are
PRIMARY — that's what the game actually loads. The profile `content.xml` enabled-list
is a SECONDARY cross-check only ("did I forget to re-acquire something from my old
modlist?") — it is NOT used to determine what's active. A mod tracked from the old
content.xml list but not found on disk is marked `installed: false` and surfaced in
a separate dashboard section rather than counted as active.
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
GAME_EXTENSIONS = Path(os.environ.get(
    "X4_GAME_EXTENSIONS", "extensions"))
PROFILE_EXTENSIONS = Path(os.environ.get(
    "X4_PROFILE_EXTENSIONS", os.path.join("profile", "extensions")))
WORKSHOP_CONTENT = Path(os.environ.get(
    "X4_WORKSHOP_CONTENT", os.path.join("workshop", "content", "392160")))


def default_installed_dirs() -> list[Path]:
    return [GAME_EXTENSIONS, PROFILE_EXTENSIONS, WORKSHOP_CONTENT]

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
    "kuerteeAlternativesToDeath": 551,  # ATD — currently HIDDEN on Nexus (KB); search can't find it
}


def ingest_content_xml(path: Path | None = None) -> list[tuple[str, bool]]:
    """(id, enabled) for every <extension> in the profile content.xml.

    SECONDARY source (cross-check only) — see module docstring."""
    path = path or PROFILE_CONTENT
    root = etree.parse(str(path)).getroot()
    out = []
    for ext in root.xpath("//extension[@id]"):
        out.append((ext.get("id"), str(ext.get("enabled", "false")).lower() == "true"))
    return out


def scan_installed(dirs: list[Path] | None = None) -> list[dict]:
    """Scan extension folders for a content.xml and return each mod's OWN
    manifest identity — this is the PRIMARY source of truth (what the game
    actually loads). Skips `ego_dlc_*` (base-game DLC, not a mod to triage).

    Folder name may differ from the manifest `id` (e.g. folder `X4CapturableXenonXL`
    has id `X4_Capturable_Xenon XL PERSONAL`) — always read the real `id` attribute.
    """
    out = []
    for base in dirs or default_installed_dirs():
        if not base.is_dir():
            continue
        for sub in sorted(base.iterdir()):
            if not sub.is_dir() or sub.name.startswith("ego_dlc_"):
                continue
            cxml = sub / "content.xml"
            if not cxml.is_file():
                continue
            try:
                root = etree.parse(str(cxml)).getroot()
            except etree.XMLSyntaxError:
                continue
            mod_id = root.get("id") or sub.name
            # enabled="0"/"false" explicitly disables; absent/blank/anything else = enabled.
            enabled = str(root.get("enabled", "")).strip().lower() not in ("false", "0")
            out.append({
                "id": mod_id, "folder": sub.name, "path": str(sub),
                "name": root.get("name") or "", "version": root.get("version") or "",
                "date": root.get("date") or "", "author": root.get("author") or "",
                "enabled": enabled,
            })
    return out


def _source_of(mod_id: str) -> str:
    return "workshop" if mod_id.startswith("ws_") else "nexus"


def _new_entry(mod_id: str, enabled: bool) -> CommentedMap:
    auto = CommentedMap()
    auto["enabled"] = enabled
    auto["installed"] = False  # set True by merge_installed() when actually found on disk
    auto["source"] = _source_of(mod_id)
    auto["nexus_id"] = SEED_NEXUS_IDS.get(mod_id)
    for k in ("name", "version", "updated", "status", "author", "settled", "checked_at",
              "installed_version", "installed_date", "installed_name", "folder", "path"):
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


def merge_installed(reg: CommentedMap, installed: list[dict]) -> tuple[int, int, int]:
    """Merge the PRIMARY installed-folder scan into the registry.

    - A mod found on disk -> auto.installed=True + installed_version/date/name/
      folder/path set + auto.enabled from its own manifest. PRESERVES human: and
      any prior upstream research (nexus_id, classification, etc.) if the id was
      already tracked (e.g. from an old content.xml ingest).
    - A mod previously tracked but NOT found in this scan -> auto.installed=False
      (kept for the "old modlist, not currently installed" diff view; not deleted).

    Returns (new_to_registry, matched_existing, no_longer_installed)."""
    by_id = {m["id"]: m for m in reg["mods"]}
    installed_ids = {e["id"] for e in installed}
    new = matched = 0
    for e in installed:
        if e["id"] in by_id:
            m = by_id[e["id"]]
            matched += 1
        else:
            m = _new_entry(e["id"], True)
            reg["mods"].append(m)
            new += 1
        a = m["auto"]
        a["installed"] = True
        a["enabled"] = e["enabled"]
        a["installed_version"] = e["version"] or None
        a["installed_date"] = e["date"] or None
        a["installed_name"] = e["name"] or None
        a["folder"] = e["folder"]
        a["path"] = e["path"]
        if not a.get("author") and e["author"]:
            a["author"] = e["author"]  # fill in if upstream research hasn't set it yet

    not_installed = 0
    for m in reg["mods"]:
        if m["id"] not in installed_ids:
            m["auto"]["installed"] = False  # unconditional: backfills pre-existing entries too
            not_installed += 1
    return new, matched, not_installed


# --- Dashboard generation ---

# Classification reflects what the API can HONESTLY tell us. "9.0-ready" is NOT
# in the API, so we infer from update-date relative to the 9.0 release; old mods
# are "predates-9.0 / review", never auto-claimed compatible.
_LANES = [
    ("ready", "✅ LIKELY 9.0-READY (updated post-9.0, settled)"),
    ("churning", "⏸ CHURNING (updated <14d ago — defer / pin)"),
    ("predates-9.0", "⚠ PREDATES 9.0 — review (compat unconfirmed)"),
    ("custom-local", "🔧 CUSTOM-LOCAL FORK (upstream hidden/removed, but you maintain your own edits)"),
    ("drop", "❌ DROP (removed from Nexus)"),
    ("untriaged", "❓ UNTRIAGED (identity unresolved)"),
    ("error", "⚠ ERROR (API fetch failed)"),
]


def _bar(done: int, total: int, width: int = 12) -> str:
    filled = 0 if total == 0 else round(width * done / total)
    return "▓" * filled + "░" * (width - filled)


def _active(m) -> bool:
    """The PRIMARY active set: physically installed, not ignored.
    (`enabled` is the mod's own manifest flag — installed-but-self-disabled mods
    are still 'active' for triage purposes; the game just won't load them yet.)"""
    return bool(m["auto"].get("installed")) and not m["human"].get("ignored")


def needs_review(reg: CommentedMap) -> list:
    """Active entries that need a human decision: auto-matched (spot-check) or
    still untriaged."""
    out = []
    for m in reg["mods"]:
        if not _active(m):
            continue
        if str(m["auto"].get("resolve") or "").startswith("auto") \
                or m["auto"].get("classification") == "untriaged":
            out.append(m)
    return out


def not_installed(reg: CommentedMap) -> list:
    """Tracked (e.g. from the old profile content.xml) but NOT found in the
    installed-folder scan — the diff/backstop view ('did I forget to re-acquire
    this?'). Excludes ignored entries."""
    return [m for m in reg["mods"]
            if not m["auto"].get("installed") and not m["human"].get("ignored")]


def generate_dashboard(reg: CommentedMap) -> str:
    mods = [m for m in reg["mods"] if _active(m)]
    ignored = sum(1 for m in reg["mods"] if m["human"].get("ignored"))
    total = len(mods)
    done = sum(1 for m in mods if m["human"].get("done"))
    build = reg.get("meta", {}).get("game_build") or "?"
    lines = ["# Phase-A Worklist (generated)\n",
             f"**Game build {build}** · {total} installed mods "
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
        lines.append("| Mod | id | source | installed | upstream | updated | status |")
        lines.append("|-----|----|--------|-----------|----------|---------|--------|")
        for m in sorted(group, key=lambda x: str(x["auto"].get("name") or x["id"])):
            a = m["auto"]
            name = a.get("name") or a.get("installed_name") or "—"
            inst = a.get("installed_version") or "—"
            ver = a.get("version") or "—"
            upd = a.get("updated") or "—"
            lines.append(f"| {name} | {m['id']} | {a.get('source')} | {inst} | {ver} | {upd} | {a.get('status') or '—'} |")
        lines.append("")

    old = not_installed(reg)
    if old:
        lines.append(f"## 📦 OLD MODLIST — NOT CURRENTLY INSTALLED  ({len(old)})")
        lines.append("Tracked previously (e.g. old content.xml) but no matching folder found on "
                     "disk right now — re-acquire if still wanted, or `ignore` if intentionally dropped.\n")
        lines.append("| id | last known name | last known status |")
        lines.append("|----|------------------|--------------------|")
        for m in sorted(old, key=lambda x: x["id"]):
            a = m["auto"]
            lines.append(f"| {m['id']} | {a.get('name') or '—'} | {a.get('classification') or 'untriaged'} |")
        lines.append("")
    return "\n".join(lines)


def write_dashboard(reg: CommentedMap, path: Path | None = None) -> Path:
    path = path or (DEFAULT_REGISTRY.parent / "WORKLIST.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_dashboard(reg), encoding="utf-8")
    return path

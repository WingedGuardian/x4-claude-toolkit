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
import sys
from pathlib import Path

from lxml import etree
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from x4validate import _paths

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096  # don't line-wrap long notes

# Resolved through _paths, which accepts BOTH the installer's env names and the
# legacy ones this module used to read directly, and falls back to the installer's
# .claude/x4-paths.env. These stay module-level constants because tests (and the
# CLI's --dirs) monkeypatch them.
#
# UNRESOLVED IS None, NEVER A GUESS. These used to fall back to CWD-relative
# paths (`Path("content.xml")`, `Path("extensions")`, ...), which meant an
# unconfigured install silently ingested whatever content.xml the CWD happened
# to hold and wrote its registry into the CWD — "0 installed mods" as a
# statement about your modlist instead of about the missing setting. Callers
# pass a value through `require()` (exit 2, names the setting) before using it.
DEFAULT_REGISTRY = _paths.registry()
PROFILE_CONTENT = _paths.profile_content()
GAME_EXTENSIONS = _paths.game_extensions()
PROFILE_EXTENSIONS = _paths.profile_extensions()
WORKSHOP_CONTENT = _paths.workshop_content()


# --- Identity provenance -----------------------------------------------------
#
# A guess and a measurement must never occupy the same slot in the same grammar.
# Before this existed, `auto.nexus_id` held both, so a fuzzy name match sat next to
# `settled: stable` and read as fact — one real row pointed at an unrelated author's
# mod for weeks. Every stored id now carries HOW it was obtained, and anything
# DERIVED from a guessed id is capped so it cannot be promoted into a confident lane.

#: How the id in `auto.nexus_id` was arrived at. Order is roughly most→least trusted.
ID_STATES = (
    "pinned",      # a human set it — authoritative, never re-searched
    "exact",       # unambiguous: a ws_ id, or one clearly-dominant name match
    "guess",       # matched on weak evidence; `candidates` records the alternatives
    "ambiguous",   # several plausible hits, no winner -> NO id is stored
    "unmatched",   # searched, nothing plausible came back
    "off-nexus",   # a human says there is no Nexus page for this at all
    "unsearched",  # never attempted
)
#: States whose id may be trusted by anything downstream.
TRUSTED_ID_STATES = frozenset({"pinned", "exact"})
#: States that mean "do not spend an API call on this again".
TERMINAL_ID_STATES = frozenset({"pinned", "off-nexus"})
#: The lane a row is capped at while its identity is not trusted. A guess must
#: never reach `ready`/`settled: stable` — that is the whole point of the split.
UNCONFIRMED_LANE = "needs-confirmation"
#: Lanes that assert something CONFIDENT about the upstream mod, and therefore
#: may only be occupied by a row whose identity is trusted.
_CONFIDENT_LANES = frozenset({"ready", "churning", "predates-9.0", "drop", "custom-local"})


def identity(m) -> tuple[int | None, int | None, str]:
    """(nexus_id, nexus_file_id, id_state) for one entry, human pins winning.

    The single place that answers "who is this mod upstream?". `human:` is checked
    first and unconditionally: a human verdict is permanent, including the verdict
    "there is no page" (`human.nexus_id: none` / a `human.source`), which stops the
    resolver from re-guessing something it already got wrong.
    """
    a, h = m.get("auto") or {}, m.get("human") or {}
    hid, hfile = h.get("nexus_id"), h.get("nexus_file_id")
    if isinstance(hid, str) and hid.strip().lower() in ("none", "no", "off-nexus"):
        return None, None, "off-nexus"
    if hid not in (None, ""):
        try:
            return int(hid), (int(hfile) if hfile not in (None, "") else None), "pinned"
        except (TypeError, ValueError):
            # silent-ok: a malformed human pin (e.g. `nexus_id: "1330 maybe?"`) falls
            # through to the auto side, which yields a NON-trusted id_state — so the
            # row surfaces in `needs_review`/`verify` as unconfirmed rather than
            # vanishing. The miss is reported there, not swallowed here.
            pass
    if str(h.get("source") or "").strip():
        return None, None, "off-nexus"
    state = a.get("id_state") or "unsearched"
    nid = a.get("nexus_id")
    if state not in ID_STATES:
        state = "guess" if nid else "unsearched"   # unknown label is never promoted
    return (int(nid) if nid not in (None, "") else None,
            int(a["nexus_file_id"]) if a.get("nexus_file_id") not in (None, "") else None,
            state)


def cap_classification(state: str, classification: str, settled: str) -> tuple[str, str]:
    """Stop an unverified identity from producing a confident verdict.

    `classification`/`settled` are computed from upstream data that was fetched
    using the id — so they are only ever as good as the id. A row whose identity is
    a guess is held at `needs-confirmation` no matter how healthy the mod it fetched
    looks, because the reassuring part ("updated recently, stable") may describe
    somebody else's mod entirely.
    """
    if state in TRUSTED_ID_STATES:
        return classification, settled
    return UNCONFIRMED_LANE, f"unconfirmed identity ({state})"


#: Legacy `auto.resolve` values -> the id_state they honestly correspond to.
#: NOTHING is promoted here: every historical auto-match becomes `guess`, because
#: that is what it always was — the old label just did not say so.
_LEGACY_RESOLVE = {
    "manual": "pinned",
    "auto (spot-check)": "guess",
    "auto (skipped implausible top hit; spot-check)": "guess",
    "unmatched (needs review)": "unmatched",
}


def migrate_entry(m) -> bool:
    """Bring one entry up to the identity-provenance schema. True if it changed.

    Idempotent, and deliberately pessimistic: an id whose provenance cannot be
    reconstructed becomes `guess`, never `exact`. Downgrading a real match costs
    one spot-check; upgrading a bad one re-creates the defect this schema exists
    to remove.
    """
    changed = False
    a = m.setdefault("auto", CommentedMap())
    h = m.setdefault("human", CommentedMap())
    for key, default in (("nexus_id", None), ("nexus_file_id", None),
                         ("source", ""), ("verified_on", None)):
        if key not in h:
            h[key] = default
            changed = True
    if "nexus_file_id" not in a:
        a["nexus_file_id"] = None
        changed = True
    if "upstream_from" not in a:
        a["upstream_from"] = None
        changed = True
    if "id_state" not in a:
        legacy = str(a.get("resolve") or "")
        if legacy in _LEGACY_RESOLVE:
            a["id_state"] = _LEGACY_RESOLVE[legacy]
        elif legacy.startswith("auto"):
            a["id_state"] = "guess"
        else:
            a["id_state"] = "guess" if a.get("nexus_id") else "unsearched"
        changed = True
        # A lane computed BEFORE the cap existed is a confident verdict resting on
        # an identity nobody confirmed — the exact falsehood this schema removes,
        # so it does not get grandfathered. Measured on the first real migration:
        # 62 of 101 active rows were sitting in `ready`/`churning`/`predates-9.0`
        # on the strength of a fuzzy name match. The upstream data is kept; only
        # the verdict drawn from it is withdrawn, and one refresh restores any
        # lane whose identity is confirmed.
        _, _, state = identity(m)
        if state not in TRUSTED_ID_STATES and a.get("classification") in _CONFIDENT_LANES:
            a["classification"], a["settled"] = cap_classification(
                state, a.get("classification"), a.get("settled") or "")
    return changed


def migrate(reg: CommentedMap) -> int:
    """Migrate every entry; returns how many changed. Called on load."""
    return sum(1 for m in reg.get("mods") or [] if migrate_entry(m))


def require(value: Path | None, what: str, fix: str) -> Path:
    """Named-loss gate for an unresolved location: exit 2 rather than guess.

    A guessed CWD-relative path does not error — it looks in the wrong place and
    reports finding nothing, which reads as a fact about the user's mods."""
    if value is None:
        print(f"error: {what} is not configured — {fix}", file=sys.stderr)
        print("       (run `x4validate --paths` to see what resolved; "
              "config file: .claude/x4-paths.env)", file=sys.stderr)
        raise SystemExit(2)
    return Path(value)


def default_installed_dirs() -> list[Path]:
    """The configured roots a mod can be installed into.

    A root that is configured but does not exist is NOT dropped here —
    `scan_installed` reports what it actually found, and silently shrinking this
    list is how "0 installed mods" starts reading as "you have no mods" instead
    of "I looked in the wrong place". A root that is NOT CONFIGURED is a
    different thing: there is nowhere to look, and the CLI names that loss
    (empty list) instead of scanning a guessed CWD-relative folder.
    """
    return [d for d in (GAME_EXTENSIONS, PROFILE_EXTENSIONS, WORKSHOP_CONTENT)
            if d is not None]

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
    if path is None:
        raise FileNotFoundError(
            "profile content.xml is not configured (set X4_PROFILE or "
            "X4_PROFILE_CONTENT, or pass --content)")
    root = etree.parse(str(path)).getroot()
    out = []
    for ext in root.xpath("//extension[@id]"):
        out.append((ext.get("id"), str(ext.get("enabled", "false")).lower() == "true"))
    return out


#: The two questions people ask about "the mod list", which are NOT the same
#: question. Nothing in the code used to say which one a caller wanted, so it was
#: decided by whichever helper the author happened to import.
#:
#:   "active"    — what the ENGINE WILL LOAD: installed, enabled in its own
#:                 manifest, and enabled in the profile content.xml.
#:   "installed" — what is ON DISK, enabled or not. The right answer when you are
#:                 inventorying, or evaluating a mod before switching it on.
#:
#: MEASURED 2026-08-22 across 13 call sites: 5 correct, 3 defensible but silent,
#: and **4 wrong**, all wrong the same way — modelling the running game from the
#: disk. Concretely, with exactly ONE mod installed-but-disabled (`escape_pod`,
#: 19 files): `x4eff` carried its 3 macros as live; `x4compat` listed it as a
#: participant in 4 collision rows; and Tier B — the mode whose entire job is
#: proving a cross-mod selector resolves — would resolve a selector against it
#: and report OK. That last one is a FALSE PASS in the tool built to catch
#: silent no-ops.
#:
#: The cost was 1 mod only because you happen to have one disabled. It scales
#: with the disabled set, and nothing warned.
MOD_SCOPES = ("active", "installed")


def mods(scope: str, dirs: list[Path] | None = None,
         dropped: list[str] | None = None) -> list[dict]:
    """The mod set, for an EXPLICITLY NAMED *scope* — see :data:`MOD_SCOPES`.

    *scope* is positional and required on purpose. A default would just recreate
    the bug: the whole defect was that callers never had to say which world they
    meant, so they silently got whichever one the helper happened to implement.

    Prefer this over calling :func:`scan_installed` directly; that is the raw
    disk reader and `tests/test_mod_scope_is_explicit.py` enforces the boundary.

    ⚠ NEITHER scope includes the DLC. `ego_dlc_*` is skipped as base-game
    content, not a mod to triage (see :func:`scan_installed`), and enumerating it
    here would DOUBLE-COUNT every DLC against the unpacked reference tree, which is the
    base+DLC (CLAUDE.md #20). MEASURED 2026-08-27: 123 installed, 0 of them a DLC.
    The caveat is documented on `scan_installed` and was missing here, on the
    function this docstring tells everyone to call instead -- so a dependency
    check asked `mods("installed")` whether the Terran DLC was present and was
    told NO. For that question use `_merge.Config().dlc_dirs()` (8 here) or
    `.packed_dlc_names()` (the two mini-DLC, which are never unpacked).
    """
    if scope not in MOD_SCOPES:
        raise ValueError(
            f"mod scope must be one of {MOD_SCOPES}, got {scope!r}. "
            f"'active' = what the engine will load; 'installed' = what is on disk.")
    installed = scan_installed(dirs, dropped=dropped)
    if scope == "installed":
        return installed
    try:
        prof = dict(ingest_content_xml())
    except (OSError, etree.XMLSyntaxError):
        # silent-ok: FAIL OPEN, and deliberately. No readable profile means we
        # cannot know what is switched off; treating every mod as enabled matches
        # the registry's documented "absent = enabled" convention and keeps this
        # from quietly EMPTYING the world model on a machine with no profile.
        prof = {}
    return [m for m in installed if m["enabled"] and prof.get(m["id"], True)]


def scan_installed(dirs: list[Path] | None = None,
                   dropped: list[str] | None = None) -> list[dict]:
    """Scan extension folders for a content.xml and return each mod's OWN
    manifest identity — this is the PRIMARY source of truth (what the game
    actually loads). Skips `ego_dlc_*` (base-game DLC, not a mod to triage).

    Folder name may differ from the manifest `id` (e.g. folder `X4CapturableXenonXL`
    has id `X4_Capturable_Xenon XL PERSONAL`) — always read the real `id` attribute.

    A folder whose `content.xml` will not parse is EXCLUDED and appended to
    *dropped*. Excluding it is almost certainly right — X4 needs that manifest to
    load the mod at all — but doing so **silently** is not: this list is the world
    model behind Tier B, x4compat, x4stats, x4similar and x4modlist, so a mod
    vanishing from it shrinks all five at once with nothing said. Report the
    exclusion; do not force the mod back in.
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
            except etree.XMLSyntaxError as exc:
                if dropped is not None:
                    dropped.append(f"{sub.name}: content.xml will not parse ({exc})")
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
    seeded = SEED_NEXUS_IDS.get(mod_id)
    auto["nexus_id"] = seeded
    auto["nexus_file_id"] = None
    # A seed is curated, not searched — but it is still not a human looking at this
    # install, so it is `exact`, never `pinned`.
    auto["id_state"] = "exact" if seeded else "unsearched"
    auto["upstream_from"] = None
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
    # Human-owned identity. These are the durable answers: a pin survives every
    # refresh, and `source` (or nexus_id: none) records a mod that has no Nexus
    # page at all — your own overlays, Workshop-only mods, bundled add-ons —
    # so the resolver stops searching for something that was never there.
    human["nexus_id"] = None        # int | "none"
    human["nexus_file_id"] = None   # int — for an add-on shipped as a FILE on another page
    human["source"] = ""            # steam:<id> | local | bundled:<mod-id> | <url>
    human["verified_on"] = None
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


#: Filename used when the configured registry location names a DIRECTORY.
REGISTRY_FILENAME = "modlist.yaml"


def _registry_file(path: Path) -> Path:
    """Normalize a configured registry location to the FILE to read/write.

    `$X4_REGISTRY` is documented as a file, but its name invites a directory and
    the fallback (`$X4_MODS/_registry/modlist.yaml`) makes either reading
    plausible. Given a directory we used to hand it straight to `open(..., "w")`,
    which raises a bare PermissionError traceback on Windows — a confusing crash
    for a reasonable setting. Treat a directory as "put the registry in here".
    """
    return path / REGISTRY_FILENAME if path.is_dir() else path


def load_registry(path: Path | None = None) -> CommentedMap:
    path = _registry_file(path or require(
        DEFAULT_REGISTRY, "the registry location",
        "set X4_MODS (or X4_REGISTRY), or pass --registry"))
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            data = _yaml.load(f)
        if data is not None:
            data.setdefault("mods", CommentedSeq())
            data.setdefault("meta", CommentedMap())
            migrate(data)  # add identity-provenance fields; promotes nothing
            return data
    return _new_registry()


def save_registry(reg: CommentedMap, path: Path | None = None) -> None:
    path = _registry_file(path or require(
        DEFAULT_REGISTRY, "the registry location",
        "set X4_MODS (or X4_REGISTRY), or pass --registry"))
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
    (UNCONFIRMED_LANE, "🔎 NEEDS IDENTITY CONFIRMATION (upstream data fetched, but the id is a GUESS)"),
    ("churning", "⏸ CHURNING (updated <14d ago — defer / pin)"),
    ("predates-9.0", "⚠ PREDATES 9.0 — review (compat unconfirmed)"),
    ("custom-local", "🔧 CUSTOM-LOCAL FORK (upstream hidden/removed, but you maintain your own edits)"),
    ("off-nexus", "📎 OFF-NEXUS (no Nexus page — Workshop, bundled, or your own; confirmed, not pending)"),
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
    """Active entries whose IDENTITY a human has not settled.

    Keyed on `id_state`, not on the old free-text `resolve` label — the point is
    that a guess stays visible until somebody confirms or corrects it. `off-nexus`
    is settled (a human said so) and drops out; `pinned`/`exact` never appear.
    """
    return [m for m in reg["mods"]
            if _active(m) and identity(m)[2] not in TRUSTED_ID_STATES | {"off-nexus"}]


def unverified_summary(reg: CommentedMap) -> dict[str, int]:
    """Counts by id_state over the active set — the denominator for 'how much of
    this registry is guesswork?', which is not answerable without it."""
    out: dict[str, int] = {}
    for m in reg["mods"]:
        if _active(m):
            out[identity(m)[2]] = out.get(identity(m)[2], 0) + 1
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

    counts = unverified_summary(reg)
    trusted = sum(n for s, n in counts.items() if s in TRUSTED_ID_STATES)
    lines.append(f"**Identity provenance:** {trusted}/{total} confirmed · " +
                 " · ".join(f"{n} {s}" for s, n in sorted(counts.items())
                            if s not in TRUSTED_ID_STATES) + "\n")

    review = needs_review(reg)
    if review:
        lines.append(f"## ⚠ UNCONFIRMED IDENTITY  ({len(review)})")
        lines.append("Every row below is a **guess or a blank**, not a fact — anything upstream "
                     "said about it may describe a different mod. Confirm/correct with "
                     "`x4modlist resolve <id> <nexus_id> [--file <file_id>]`; if it has no "
                     "Nexus page at all say so with `x4modlist source <id> <steam:…|local|"
                     "bundled:…|url>` (or `x4modlist resolve <id> none`) and it stops being "
                     "searched; junk → `x4modlist ignore <id>`.\n")
        lines.append("| Mod | id_state | current guess | candidates |")
        lines.append("|-----|----------|---------------|------------|")
        for m in sorted(review, key=lambda x: x["id"]):
            a = m["auto"]
            nid, fid, state = identity(m)
            cur = (f"{nid}" + (f" file {fid}" if fid else "") +
                   f":{a.get('name')}" if nid else "—")
            cands = " | ".join(a.get("candidates") or []) or "—"
            lines.append(f"| `{m['id']}` | **{state}** | {cur} | {cands} |")
        lines.append("")

    by_class: dict[str, list] = {}
    for m in mods:
        by_class.setdefault(m["auto"].get("classification", "untriaged"), []).append(m)
    for key, title in _LANES:
        group = by_class.get(key, [])
        if not group:
            continue
        lines.append(f"## {title}  ({len(group)})")
        lines.append("| Mod | id | identity | source | installed | upstream | updated | status |")
        lines.append("|-----|----|----------|--------|-----------|----------|---------|--------|")
        for m in sorted(group, key=lambda x: str(x["auto"].get("name") or x["id"])):
            a = m["auto"]
            name = a.get("name") or a.get("installed_name") or "—"
            inst = a.get("installed_version") or "—"
            ver = a.get("version") or "—"
            upd = a.get("updated") or "—"
            _, fid, state = identity(m)
            # The upstream columns are only as good as the id that fetched them, so
            # the provenance travels in the same row rather than in a footnote.
            prov = state + (f" · file {fid}" if fid else "")
            lines.append(f"| {name} | {m['id']} | {prov} | {a.get('source')} | {inst} | "
                         f"{ver} | {upd} | {a.get('status') or '—'} |")
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
    # Same normalization as load/save, or the dashboard lands somewhere else:
    # with a DIRECTORY configured, `.parent` of the raw path is the directory
    # ABOVE it, so WORKLIST.md ended up beside the registry folder instead of
    # inside it. Every step of a lookup chain has to learn the same rule.
    path = path or (_registry_file(require(
        DEFAULT_REGISTRY, "the registry location",
        "set X4_MODS (or X4_REGISTRY), or pass --registry")).parent / "WORKLIST.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_dashboard(reg), encoding="utf-8")
    return path

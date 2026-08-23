"""x4modlist — mod-registry CLI: ingest the modlist, refresh upstream data, triage.

API-FIRST: all Nexus access is via the API (never scrape). See _nexus.py.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import _nexus, _registry
from x4validate import __version__

NINE_ZERO = date(2026, 6, 10)  # X4 9.00 release
CHURN_DAYS = 14


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _dash_path(reg_path) -> Path:
    """WORKLIST.md sits next to whichever registry we're using.

    Normalize through `_registry_file` first: when the configured location is a
    DIRECTORY, `.parent` of the raw path is the directory ABOVE it, so the
    dashboard landed beside the registry folder instead of inside it. This is
    the third place that has to know the rule (load, save, and here) — teaching
    only some of them is how a "fixed" path bug half-persists.
    """
    base = reg_path if reg_path else _registry.require(
        _registry.DEFAULT_REGISTRY, "the registry location",
        "set X4_MODS (or X4_REGISTRY), or pass --registry")
    return _registry._registry_file(Path(base)).parent / "WORKLIST.md"


def _classify(meta: "_nexus.ModMeta", today: date, is_custom: bool = False) -> tuple[str, str]:
    """(classification, settled) from API truth only. 9.0-readiness is NOT in the
    API, so post-9.0-update is a *proxy*; pre-9.0 mods are 'predates-9.0/review'.

    removed/hidden means "unavailable to DOWNLOAD from Nexus" — for a mod the user
    is NOT custom-editing that's a real drop (abandoned/pulled). But if the mod is
    marked custom_edited (a locally-maintained fork, e.g. an author who hid their
    page mid-update while we keep porting our own copy), "drop" is actively wrong
    guidance — surface it as its own lane instead."""
    if meta.status in ("removed", "hidden"):
        if is_custom:
            return "custom-local", "n/a — upstream unavailable, local fork maintained"
        return "drop", "unavailable"
    try:
        upd = date.fromisoformat(meta.updated)
    except (ValueError, TypeError):
        return "untriaged", "unknown"
    if upd >= NINE_ZERO:
        if (today - upd).days <= CHURN_DAYS:
            return "churning", "churning"
        return "ready", "stable"
    return "predates-9.0", "unknown"


def _file_as_meta(meta: "_nexus.ModMeta", fmeta: "_nexus.FileMeta") -> "_nexus.ModMeta":
    """The page's status/name with the FILE's version and upload date.

    Classification asks "was this updated after 9.0, and has it settled?" — for an
    add-on shipped as a file, the honest input is the file's own upload date, not
    the page's. The page's `status` still applies (a hidden page means the file is
    not downloadable either), so that is kept.
    """
    return _nexus.ModMeta(meta.nexus_id, meta.name, fmeta.version, fmeta.uploaded,
                          meta.status, meta.author)


def _humanize(content_id: str) -> str:
    """Turn a folder-id into a searchable name: split camelCase + underscores.
    e.g. kuerteeSocialStandingsAndCitizenships -> 'kuertee Social Standings And Citizenships'."""
    s = content_id.replace("_", " ")
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)  # camelCase boundary
    return re.sub(r"\s+", " ", s).strip()


def _strip_author_label(name: str) -> str:
    """Manifest names often prefix the real title with an author/category label,
    e.g. 'kuertee: Ship scanner' or 'kuertee UI: Boarding operation notifications'
    -> 'Ship scanner' / 'Boarding operation notifications' (the label usually
    isn't in the Nexus mod title)."""
    if ":" in name:
        prefix, rest = name.split(":", 1)
        if len(prefix.split()) <= 3 and rest.strip():
            return rest.strip()
    return name.strip()


def _manifest_name_variants(name: str) -> list[str]:
    """Progressive fallback variants for a manifest title, most-specific first:
    full name -> drop a ' - <suffix>' qualifier (e.g. 'Vibrant Engine Plumes -
    Divinity Edition' -> 'Vibrant Engine Plumes') -> drop a trailing ALL-CAPS
    qualifier word (e.g. 'Terran Beam Weapons VRO' -> 'Terran Beam Weapons')."""
    variants = [name]
    if " - " in name:
        variants.append(name.split(" - ", 1)[0].strip())
    words = name.split()
    if len(words) > 1 and words[-1].isupper() and 2 <= len(words[-1]) <= 5:
        variants.append(" ".join(words[:-1]))
    return variants


def _search_with_fallback(name_hint: str) -> list[tuple[int, str]]:
    """Search; if empty and multi-word, retry dropping the leading token (often
    an author prefix not present in the Nexus title)."""
    hits = _nexus.search_mods(name_hint, 5)
    if not hits and " " in name_hint:
        hits = _nexus.search_mods(name_hint.split(" ", 1)[1], 5)
    return hits


# Words that carry no identity — they appear in hundreds of X4 mod titles, so two
# names sharing only these are NOT the same mod ("... VRO patch" matches everything).
_GENERIC = {
    "x4", "foundations", "mod", "mods", "modpack", "pack", "patch", "patches",
    "vro", "the", "and", "for", "of", "a", "an", "to", "with", "version", "versions",
    "standard", "compatibility", "compat", "fix", "fixes", "update", "updated",
    "port", "edition", "addon", "add", "on", "new", "reworked", "rebalanced",
    "trimmed", "adaptation", "expansion", "overhaul", "ship", "ships", "extension",
}


def _identity_tokens(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (name or "").lower())
            if w not in _GENERIC and len(w) > 2}


def _match_strength(own_name: str, nexus_name: str) -> str:
    """How well could *nexus_name* be the upstream page for *own_name*?

    Returns "strong" | "weak" | "none". The three-way answer is the point: the
    previous boolean version made every plausible hit equally acceptable and the
    caller simply took the first one, so a single shared word decided an identity.
    Measured case: "CPSDO Faction Pack 9.0+" scores a shared token against BOTH
    "Faction Filter for Ships" and "Apus Stellar Treaty - New Faction and Sectors",
    and the real answer is neither — it is a FILE on a different mod's page, which
    no name search can reach. Two weak candidates must produce a question, not a
    winner.

    strong = the whole name matches once punctuation is removed (either direction),
             or the names share a *distinctive* token (>=5 chars, e.g. "cpsdo").
    weak   = they share only short/common identity tokens ("beam", "hud", "war").
    """
    a, b = _identity_tokens(own_name), _identity_tokens(nexus_name)
    squash_a = re.sub(r"[^a-z0-9]", "", (own_name or "").lower())
    squash_b = re.sub(r"[^a-z0-9]", "", (nexus_name or "").lower())
    if squash_a and squash_b and (squash_a in squash_b or squash_b in squash_a):
        return "strong"
    if not a or not b:
        # Nothing to judge on. Formerly this returned True ("don't invent a
        # rejection") and the hit was then taken as the answer — an absence of
        # evidence spent as evidence. It is weak: keep it as a candidate, never
        # as a verdict.
        return "weak"
    shared = a & b
    if not shared:
        return "none"
    return "strong" if any(len(t) >= 5 for t in shared) else "weak"


def _plausible_match(own_name: str, nexus_name: str) -> bool:
    """Back-compat shim: is this hit worth keeping as a candidate at all?"""
    return _match_strength(own_name, nexus_name) != "none"


def _resolve_identity(content_id: str, auto) -> tuple[int | None, str]:
    """A3 cascade (API-first) -> (nexus_id | None, id_state).

    ws_ -> Steam title -> Nexus search; named -> prefer the mod's OWN manifest name
    (`installed_name`, straight from its content.xml — far more reliable than
    guessing from the folder/content id) -> else a humanized-id guess -> Nexus
    search, with an author-prefix-drop retry. Never scrapes Nexus.

    Returns a STATE alongside the id, and returns no id at all when the evidence
    does not single one out. Guessing is fine; guessing silently is not.
    """
    if content_id.startswith("ws_"):
        name_hint = content_id
        t = _nexus.steam_title(content_id)
        if t:
            name_hint = t[0]
            auto["steam_title"] = t[0]
        candidates = [name_hint]
    else:
        installed_name = auto.get("installed_name")
        candidates = (_manifest_name_variants(_strip_author_label(installed_name))
                     if installed_name else []) + [_humanize(content_id)]

    hits, used_hint = [], None
    try:
        for hint in candidates:
            hits = _search_with_fallback(hint)
            if hits:
                used_hint = hint
                break
    except _nexus.NexusError:
        # silent-ok: an upstream-lookup failure is not a statement about the mod.
        # The caller leaves the field unset (never "no update available"), so the
        # unknown stays visibly unknown in the registry.
        return None, "unsearched"
    if not hits:
        return None, "unmatched"

    auto["resolve_hint"] = used_hint
    # Keep top candidates so the user can spot-check / correct cheaply.
    auto["candidates"] = [f"{mid}:{nm}" for mid, nm in hits[:3]]
    own_name = auto.get("installed_name") or _humanize(content_id)

    scored = [(h, _match_strength(own_name, h[1])) for h in hits]
    strong = [h for h, s in scored if s == "strong"]
    weak = [h for h, s in scored if s == "weak"]

    if len(strong) == 1:
        auto["resolve"] = "auto (strong match)"
        return strong[0][0], "exact"
    if len(strong) > 1:
        # Several names each look like this mod. Picking one is a coin flip dressed
        # as an answer, so record the question instead and store NO id.
        auto["resolve"] = f"ambiguous ({len(strong)} strong matches)"
        return None, "ambiguous"
    if len(weak) == 1:
        auto["resolve"] = "auto (weak match — spot-check)"
        return weak[0][0], "guess"
    if len(weak) > 1:
        auto["resolve"] = f"ambiguous ({len(weak)} weak matches)"
        return None, "ambiguous"
    # Every hit is unrelated. Leaving it UNRESOLVED is strictly better than a
    # confident wrong id: a wrong id makes update-detection track someone else's
    # mod while the row reads 'settled: stable'. Measured 2026-07-26: 7 of 69
    # resolved mods were wrong this way, e.g. cpsdo_vro ("CPSDO VRO Adaptation
    # Pack") -> 2017 "Firefly (Serenity) VRO and standard versions", because the
    # search for 'cpsdo vro' returns nothing while 'cpsdo' returns five correct
    # hits, and the top result was taken on faith.
    auto["resolve"] = "unmatched (needs review)"
    return None, "unmatched"


def cmd_ingest(args) -> int:
    """Two passes: (1) the profile content.xml — SECONDARY, just backfills a
    registry row for any historically-tracked id so nothing is silently dropped;
    (2) the installed-folder scan — PRIMARY, authoritative for installed/enabled/
    version/name/author. Pass 2 always runs last so it wins."""
    reg_path = Path(args.registry) if args.registry else _registry.require(
        _registry.DEFAULT_REGISTRY, "the registry location",
        "set X4_MODS (or X4_REGISTRY), or pass --registry")
    reg = _registry.load_registry(reg_path)

    added = existing = 0
    if not args.installed_only:
        content = Path(args.content) if args.content else _registry.PROFILE_CONTENT
        if content is None:
            # SECONDARY source only — skipping it is fine, skipping it SILENTLY
            # is not (it looks like the cross-check ran and found nothing).
            print("note: profile content.xml not configured (X4_PROFILE) — "
                  "SECONDARY cross-check skipped", file=sys.stderr)
        else:
            try:
                ids = _registry.ingest_content_xml(content)
            except OSError as exc:
                print(f"error: cannot read profile content.xml: {exc}", file=sys.stderr)
                print("       (pass --content, or --installed-only to skip the "
                      "cross-check)", file=sys.stderr)
                return 2
            added, existing = _registry.merge(reg, ids, enabled_only=not args.all)

    dirs = [Path(d) for d in args.dirs.split(",")] if args.dirs else None
    if dirs:
        # scan_installed skips a non-directory, so a typo'd --dirs scans nothing
        # and the run reports "0 installed" — which reads as "you have no mods".
        missing = [str(d) for d in dirs if not d.is_dir()]
        if missing:
            print(f"error: --dirs entries are not directories: {', '.join(missing)}",
                  file=sys.stderr)
            print("       (refusing to report an installed-mod count for a path that "
                  "was never scanned)", file=sys.stderr)
            return 2
    else:
        roots = _registry.default_installed_dirs()
        if not roots:
            print("error: no installed-mod roots configured — the PRIMARY scan has "
                  "nowhere to look", file=sys.stderr)
            print("       set X4_GAME (or X4_EXTENSIONS) for the game-root "
                  "extensions\\ folder, or pass --dirs", file=sys.stderr)
            print("       (run `x4validate --paths` to see what resolved)",
                  file=sys.stderr)
            return 2
        existing_roots = [d for d in roots if d.is_dir()]
        if not existing_roots:
            print("error: none of the configured installed-mod roots exist:",
                  file=sys.stderr)
            for d in roots:
                print(f"       {d}", file=sys.stderr)
            print("       (refusing to report an installed-mod count for paths that "
                  "were never scanned)", file=sys.stderr)
            return 2
        print("scanning roots: " + ", ".join(str(d) for d in roots))
    dropped: list[str] = []
    # INSTALLED: the registry's job is to inventory what is ON DISK. A disabled
    # mod is still installed, still needs triage, and is exactly what the
    # "did I forget to re-acquire something?" cross-check is looking for.
    installed = _registry.mods("installed", dirs, dropped)
    for d in dropped:
        # Excluding the mod is right — X4 needs a readable content.xml too — but
        # it must not shrink the registry's world model in silence.
        print(f"warning: NOT INGESTED — {d}", file=sys.stderr)
    new, matched, not_installed = _registry.merge_installed(reg, installed)

    reg["meta"]["game_build"] = args.build
    reg["meta"]["generated"] = _now()
    _registry.save_registry(reg, reg_path)
    dash = _registry.write_dashboard(reg, _dash_path(reg_path))
    print(f"profile content.xml (cross-check): +{added} new, {existing} existing")
    print(f"installed folders (PRIMARY, {len(installed)} found): "
          f"+{new} new to registry, {matched} matched prior research, "
          f"{not_installed} tracked-but-not-installed")
    print(f"registry:  {reg_path}")
    print(f"dashboard: {dash}")
    return 0


def cmd_refresh(args) -> int:
    reg_path = Path(args.registry) if args.registry else None
    reg = _registry.load_registry(reg_path)
    today = datetime.now(timezone.utc).date()
    want = set(args.ids.split(",")) if args.ids else None

    if want:
        # Explicit --ids targets a mod regardless of installed status (e.g. to
        # check an old-modlist mod's upstream status before re-acquiring it).
        mods = [m for m in reg["mods"] if m["id"] in want]
    else:
        mods = [m for m in reg["mods"] if m["auto"].get("installed")]
    if args.seeded:
        mods = [m for m in mods if m["auto"].get("nexus_id")]
    if args.limit:
        mods = mods[: args.limit]

    resolved = fetched = errors = skipped = 0
    for m in mods:
        a = m["auto"]
        if a.get("checked_at") == today.isoformat() and not args.force:
            continue  # already refreshed today (TTL)

        nid, fid, state = _registry.identity(m)
        if state in _registry.TERMINAL_ID_STATES and not nid:
            # off-nexus: a human already answered "there is no page". Searching
            # again would burn an API call to re-derive a wrong guess they have
            # already overruled once.
            a["classification"] = "off-nexus"
            a["settled"] = "n/a — not distributed on Nexus"
            skipped += 1
            continue
        if not nid and not args.no_resolve:
            nid, state = _resolve_identity(m["id"], a)
            a["id_state"] = state
            if nid:
                a["nexus_id"] = nid
                resolved += 1
        if not nid:
            # `ambiguous` and `unmatched` are real answers and must not be flattened
            # into the same bucket as "never looked" — that is what made 31 rows
            # indistinguishable from each other.
            a["classification"] = "untriaged"
            a["settled"] = f"identity {state}"
            continue

        try:
            meta = _nexus.fetch_mod(nid)
            fmeta = _nexus.fetch_file(nid, fid) if fid else None
        except _nexus.NexusError as exc:
            a["classification"] = "error"
            a["error"] = str(exc)
            errors += 1
            continue

        a["name"], a["author"] = meta.name, meta.author
        a["status"] = meta.status
        if fmeta is not None:
            # This mod ships as a FILE on someone else's page: the page's version
            # tracks whatever its owner last uploaded, which is a different mod's
            # release cadence. Report the FILE, and say which one, or the row
            # answers a question nobody asked.
            a["version"], a["updated"] = fmeta.version, fmeta.uploaded
            a["upstream_file"] = f"{fmeta.file_id}:{fmeta.name} [{fmeta.category}]"
        else:
            a["version"], a["updated"] = meta.version, meta.updated
            a.pop("upstream_file", None)
        a["checked_at"] = today.isoformat()
        a["upstream_from"] = "exact" if state in _registry.TRUSTED_ID_STATES else state

        cls, settled = _classify(meta if fmeta is None else _file_as_meta(meta, fmeta),
                                 today, m["human"].get("custom_edited", False))
        a["classification"], a["settled"] = _registry.cap_classification(state, cls, settled)
        fetched += 1

    _registry.save_registry(reg, reg_path)
    dash = _registry.write_dashboard(reg, _dash_path(reg_path))
    unconfirmed = len(_registry.needs_review(reg))
    print(f"refresh: {fetched} fetched, {resolved} newly id-resolved, {errors} errors, "
          f"{skipped} off-nexus (not searched) ({len(mods)} processed)")
    if unconfirmed:
        # Never let a refresh read as "everything is up to date" while a chunk of
        # what it just fetched was fetched against a guessed identity.
        print(f"         {unconfirmed} active mod(s) still have an UNCONFIRMED identity — "
              f"their upstream data may describe a different mod. Run `x4modlist verify`.")
    print(f"dashboard: {dash}")
    return 0


def cmd_dashboard(args) -> int:
    reg_path = Path(args.registry) if args.registry else None
    reg = _registry.load_registry(reg_path)
    dash = _registry.write_dashboard(reg, _dash_path(reg_path))
    print(f"dashboard regenerated: {dash}")
    return 0


def _registry_path(args) -> Path:
    """The registry file these args address, and refuse a path that isn't one.

    `load_registry` falls back to a fresh EMPTY registry for a missing file, so a
    typo'd --registry made every later "not in registry: <id>" a lie about the
    mod rather than about the path.
    """
    if not getattr(args, "registry", None):
        # Not configured is NOT the same as not created yet. This used to warn and
        # continue with a CWD-relative guess, so an empty registry made every count
        # downstream read "0 mods" — a statement about your modlist rather than
        # about the missing setting. Unconfigured now refuses with the setting
        # named (a first run before `ingest` with the location CONFIGURED still
        # proceeds on the legitimately-not-yet-created file).
        return _registry.require(_registry.DEFAULT_REGISTRY, "the registry location",
                                 "set X4_MODS (or X4_REGISTRY), or pass --registry")
    path = Path(args.registry)
    if not path.is_file():
        print(f"error: --registry is not a file: {path}", file=sys.stderr)
        print("       (an empty registry would make every id below look untracked)",
              file=sys.stderr)
        raise SystemExit(2)
    return path


def _find(reg, content_id):
    for m in reg["mods"]:
        if m["id"] == content_id:
            return m
    return None


def cmd_needs_review(args) -> int:
    reg = _registry.load_registry(Path(args.registry) if args.registry else None)
    review = _registry.needs_review(reg)
    if not review:
        print("nothing needs spot-check")
        return 0
    print(f"{len(review)} need spot-check (resolve <id> <nexus_id> | ignore <id>):")
    for m in sorted(review, key=lambda x: x["id"]):
        a = m["auto"]
        cur = f"{a.get('nexus_id')}:{a.get('name')}" if a.get("nexus_id") else "unresolved"
        cands = " | ".join(a.get("candidates") or [])
        print(f"  {m['id']:42} -> {cur}" + (f"   candidates: {cands}" if cands else ""))
    return 0


def cmd_resolve(args) -> int:
    """Pin an identity. The pin goes in `human:` so it is PERMANENT.

    Previously this wrote `auto.nexus_id` + `resolve: manual`, i.e. a human verdict
    stored in the tool-owned half of the row. Nothing overwrote it in practice, but
    nothing guaranteed not to either, and it left no way to say the two things a
    human most often knows: "this ships as a FILE on that page" and "this has no
    page at all".
    """
    reg_path = _registry_path(args)
    reg = _registry.load_registry(reg_path)
    m = _find(reg, args.id)
    if m is None:
        print(f"not in registry: {args.id}", file=sys.stderr)
        return 2
    a, h = m["auto"], m["human"]
    today = datetime.now(timezone.utc).date()

    if str(args.nexus_id).strip().lower() == "none":
        h["nexus_id"] = "none"
        h["nexus_file_id"] = None
        h["verified_on"] = today.isoformat()
        a["classification"], a["settled"] = "off-nexus", "n/a — not distributed on Nexus"
        a.pop("candidates", None)
        _registry.save_registry(reg, reg_path)
        _registry.write_dashboard(reg, _dash_path(reg_path))
        print(f"{args.id}: recorded as NOT on Nexus — it will not be searched again")
        return 0

    try:
        nexus_id = int(args.nexus_id)
    except (TypeError, ValueError):
        print(f"error: nexus_id must be an integer or 'none', got {args.nexus_id!r}",
              file=sys.stderr)
        return 2

    h["nexus_id"] = nexus_id
    file_arg = getattr(args, "file", None)
    h["nexus_file_id"] = int(file_arg) if file_arg else None
    h["verified_on"] = today.isoformat()
    a["nexus_id"] = nexus_id            # mirrored for readability; human: is authoritative
    a["nexus_file_id"] = h["nexus_file_id"]
    a["id_state"] = "pinned"
    a["resolve"] = "manual"
    a.pop("candidates", None)

    try:
        meta = _nexus.fetch_mod(nexus_id)
        fmeta = _nexus.fetch_file(nexus_id, h["nexus_file_id"]) if h["nexus_file_id"] else None
    except _nexus.NexusError as exc:
        # The PIN still stands — it is a human statement of fact and does not depend
        # on the network. Only the fetched-metadata half failed, and saying so is the
        # difference between "your correction was lost" and "we could not look it up".
        _registry.save_registry(reg, reg_path)
        _registry.write_dashboard(reg, _dash_path(reg_path))
        print(f"pinned {args.id} -> {nexus_id}"
              + (f" file {h['nexus_file_id']}" if h["nexus_file_id"] else "")
              + f"; upstream fetch failed: {exc}", file=sys.stderr)
        return 1

    a["name"], a["author"], a["status"] = meta.name, meta.author, meta.status
    if fmeta is not None:
        a["version"], a["updated"] = fmeta.version, fmeta.uploaded
        a["upstream_file"] = f"{fmeta.file_id}:{fmeta.name} [{fmeta.category}]"
    else:
        a["version"], a["updated"] = meta.version, meta.updated
        a.pop("upstream_file", None)
    a["checked_at"] = today.isoformat()
    a["upstream_from"] = "exact"
    a["classification"], a["settled"] = _classify(
        meta if fmeta is None else _file_as_meta(meta, fmeta), today,
        m["human"].get("custom_edited", False))
    _registry.save_registry(reg, reg_path)
    _registry.write_dashboard(reg, _dash_path(reg_path))
    detail = f" file {fmeta.file_id} ({fmeta.name!r} v{fmeta.version})" if fmeta else ""
    print(f"pinned {args.id} -> {nexus_id} {meta.name!r}{detail} [{a['classification']}]")
    return 0


def cmd_source(args) -> int:
    """Record where a mod actually comes from when it is not a Nexus page.

    31 of the installed rows had no id and sat as `untriaged` forever, re-searched
    on every refresh — Workshop items, bundled add-ons, and the user's own local
    mods, none of which a Nexus name search can ever resolve. `untriaged` implied
    unfinished work; this states the finished answer.
    """
    reg_path = _registry_path(args)
    reg = _registry.load_registry(reg_path)
    m = _find(reg, args.id)
    if m is None:
        print(f"not in registry: {args.id}", file=sys.stderr)
        return 2
    h, a = m["human"], m["auto"]
    h["source"] = args.source
    h["verified_on"] = datetime.now(timezone.utc).date().isoformat()
    a["classification"], a["settled"] = "off-nexus", f"tracked via {args.source}"
    a.pop("candidates", None)
    _registry.save_registry(reg, reg_path)
    _registry.write_dashboard(reg, _dash_path(reg_path))
    print(f"{args.id}: source = {args.source} (no longer searched on Nexus)")
    return 0


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _rescore(reg) -> tuple[int, int]:
    """Promote guess -> exact ONLY where the two names are literally the same string.

    Deliberately far stricter than `_match_strength`'s "strong". Containment is not
    enough here and the difference is not academic: the stored id for `Ventures` is
    "Savegame for Ventures", which shares a long distinctive token and *contains*
    the name, and is a different mod. Equality modulo punctuation/case is the only
    evidence cheap enough to act on offline without re-introducing the laundering
    this whole change exists to stop.

    Returns (promoted, left_alone). Never downgrades a pin, never touches an id.
    """
    promoted = left = 0
    for m in reg["mods"]:
        a = m["auto"]
        _, _, state = _registry.identity(m)
        if state != "guess" or not a.get("nexus_id"):
            continue
        own, upstream = a.get("installed_name") or "", a.get("name") or ""
        if own and upstream and _squash(own) == _squash(upstream):
            a["id_state"] = "exact"
            a["resolve"] = "rescored (manifest name == upstream title)"
            promoted += 1
        else:
            left += 1
    return promoted, left


def cmd_verify(args) -> int:
    """The identity burn-down list, with the denominator stated."""
    reg_path = Path(args.registry) if args.registry else None
    reg = _registry.load_registry(reg_path)
    if getattr(args, "rescore", False):
        promoted, left = _rescore(reg)
        _registry.save_registry(reg, reg_path)
        _registry.write_dashboard(reg, _dash_path(reg_path))
        print(f"rescore: {promoted} promoted to `exact` (installed manifest name is "
              f"IDENTICAL to the upstream title), {left} left as guesses\n"
              f"         a near-match is deliberately NOT enough — one stored id whose "
              f"title merely CONTAINS the mod name is a different mod.\n")
    counts = _registry.unverified_summary(reg)
    active = sum(counts.values())
    trusted = sum(n for s, n in counts.items() if s in _registry.TRUSTED_ID_STATES)
    print(f"identity provenance over {active} active mods: {trusted} confirmed "
          f"(pinned/exact), {active - trusted} not")
    for state, n in sorted(counts.items()):
        print(f"   {n:4d}  {state}")

    review = _registry.needs_review(reg)
    if not review:
        print("\nnothing unconfirmed — every active identity is pinned, exact or off-nexus")
        return 0
    print(f"\n{len(review)} unconfirmed — anything upstream said about these may be a "
          f"different mod:")
    for m in sorted(review, key=lambda x: (_registry.identity(x)[2], x["id"])):
        a = m["auto"]
        nid, fid, state = _registry.identity(m)
        cur = (f"{nid}" + (f"/file {fid}" if fid else "") + f" {a.get('name') or ''}").strip() \
            if nid else "(no id)"
        cands = " | ".join(a.get("candidates") or [])
        print(f"  [{state:10}] {m['id']:42} -> {cur}"
              + (f"\n{'':16}candidates: {cands}" if cands else ""))
    print("\nfix with:  x4modlist resolve <id> <nexus_id> [--file <file_id>]"
          "\n           x4modlist resolve <id> none            (confirmed: no Nexus page)"
          "\n           x4modlist source  <id> steam:<n>|local|bundled:<mod-id>|<url>")
    # Exit 1: unconfirmed identities are findings, not an error. Usable as a gate.
    return 1


def cmd_ignore(args) -> int:
    reg_path = _registry_path(args)
    reg = _registry.load_registry(reg_path)
    m = _find(reg, args.id)
    if m is None:
        print(f"not in registry: {args.id}", file=sys.stderr)
        return 2
    m["human"]["ignored"] = True
    if args.reason:
        m["human"]["notes"] = args.reason
    _registry.save_registry(reg, reg_path)
    _registry.write_dashboard(reg, _dash_path(reg_path))
    print(f"ignored {args.id}")
    return 0


def cmd_mark(args) -> int:
    reg_path = _registry_path(args)
    reg = _registry.load_registry(reg_path)
    m = _find(reg, args.id)
    if m is None:
        print(f"not in registry: {args.id}", file=sys.stderr)
        return 2
    m["human"]["custom_edited"] = True
    if args.notes:
        m["human"]["notes"] = args.notes
    _registry.save_registry(reg, reg_path)
    print(f"marked {args.id} custom_edited=True")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # silent-ok: console encoding shim. Failure means the default codec
        # stays; it affects how output LOOKS, never what was examined.
    p = argparse.ArgumentParser(prog="x4modlist", description="X4 mod-registry triage tool (API-first).")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    p.add_argument("--registry", help="path to modlist.yaml (default: dev\\_registry\\modlist.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="scan installed extension folders (PRIMARY) into the "
                        "registry, cross-checked against the profile content.xml")
    pi.add_argument("--content", help="path to profile content.xml (secondary cross-check)")
    pi.add_argument("--dirs", help="comma-separated extension dirs to scan "
                    "(default: game-root extensions\\, profile extensions\\, Steam Workshop)")
    pi.add_argument("--installed-only", action="store_true", dest="installed_only",
                    help="skip the profile content.xml cross-check pass entirely")
    pi.add_argument("--build", default="23660954", help="current game build id")
    pi.add_argument("--all", action="store_true",
                    help="content.xml cross-check: include disabled extensions too")
    pi.set_defaults(func=cmd_ingest)

    pr = sub.add_parser("refresh", help="refresh upstream metadata via Nexus/Steam API")
    pr.add_argument("--ids", help="comma-separated content ids to refresh (default: all enabled)")
    pr.add_argument("--seeded", action="store_true", help="only mods that already have a nexus_id")
    pr.add_argument("--limit", type=int, help="cap how many mods to process (API-call safety)")
    pr.add_argument("--force", action="store_true", help="ignore the once-per-day TTL")
    pr.add_argument("--no-resolve", action="store_true", help="skip A3 identity resolution")
    pr.set_defaults(func=cmd_refresh)

    pd = sub.add_parser("dashboard", help="regenerate WORKLIST.md from the registry")
    pd.set_defaults(func=cmd_dashboard)

    pn = sub.add_parser("needs-review", help="list entries needing a spot-check decision")
    pn.set_defaults(func=cmd_needs_review)

    prs = sub.add_parser("resolve", help="pin a mod's Nexus identity permanently (+fetch)")
    prs.add_argument("id", help="content.xml extension id")
    prs.add_argument("nexus_id", help="the correct Nexus mod id, or 'none' if it has no page")
    prs.add_argument("--file", type=int, help="file id, when this mod ships as a FILE on that "
                     "page (an add-on); update-detection then tracks the FILE's version, not "
                     "the page's")
    prs.set_defaults(func=cmd_resolve)

    pso = sub.add_parser("source", help="record a non-Nexus origin (stops it being searched)")
    pso.add_argument("id", help="content.xml extension id")
    pso.add_argument("source", help="steam:<publishedfileid> | local | bundled:<mod-id> | <url>")
    pso.set_defaults(func=cmd_source)

    pv = sub.add_parser("verify", help="list identities that are guesses, with the denominator")
    pv.add_argument("--rescore", action="store_true",
                    help="offline: promote a guess to `exact` only where the installed "
                         "manifest name is IDENTICAL to the stored upstream title "
                         "(no API calls, no near-matches)")
    pv.set_defaults(func=cmd_verify)

    pig = sub.add_parser("ignore", help="mark a junk/personal mod out of the active worklist")
    pig.add_argument("id", help="content.xml extension id")
    pig.add_argument("--reason", help="note why")
    pig.set_defaults(func=cmd_ignore)

    pm = sub.add_parser("mark", help="mark a mod as custom-edited (for /x4-update-mod)")
    pm.add_argument("id", help="content.xml extension id")
    pm.add_argument("--custom", action="store_true", help="(implied) set custom_edited")
    pm.add_argument("--notes", help="what you edited")
    pm.set_defaults(func=cmd_mark)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

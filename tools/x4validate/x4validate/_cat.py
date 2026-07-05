r"""Read X4 ``.cat``/``.dat`` mod archives as an in-memory virtual filesystem.

X4 mods ship either loose files or packed catalog pairs. To reason about a packed
mod (e.g. VRO, which is 217 MB packed and otherwise invisible to our tooling) we
must read its catalog directly. The format is simple and community-documented:

- A ``.cat`` is a UTF-8 text index, one line per member::

      <virtual/path> <size> <unix_mtime> <md5hex>

  Paths may contain spaces; the trailing three tokens are fixed, so we parse from
  the right (``rsplit(" ", 3)``).
- The matching ``.dat`` stores member payloads concatenated in ``.cat`` line order,
  so a member's byte offset is the running sum of preceding sizes.
- A mod folder may hold ``ext_NN.cat`` (extension-local additions/diffs) and/or
  ``subst_NN.cat`` (full-file base-game substitutions). Both are read and resolve by
  virtual path; later catalogs override earlier ones for the same path.
- ``*_sig.cat`` are signatures — skipped.
- Version/diff catalogs (``ext_vNNN.cat``, ``ext_NN_diff_vNNN.cat``) are a base-game
  DLC construct (e.g. ego_dlc_ventures) resolved at unpack time into ``reference\``;
  they do not appear in mods. If ever encountered here they are skipped with a
  warning rather than silently mis-applied.

This is an independent implementation from the documented format; cross-checked for
correctness against Egosoft's XRCatTool and meethune/x4cat (MIT) as format references.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_MD5_RE = re.compile(r"^[0-9a-fA-F]{32}$")
# Plain mod catalogs we read: ext_01.cat, subst_02.cat, ...
_PLAIN_CAT_RE = re.compile(r"^(ext|subst)_(\d+)\.cat$", re.IGNORECASE)
# Version/diff catalogs we deliberately skip (DLC-only; not seen in mods).
_VERSION_CAT_RE = re.compile(r"^(ext|subst)_.*v\d+\.cat$", re.IGNORECASE)
# Member extensions worth extracting (everything our analysis parses is XML/XSD).
_XML_SUFFIXES = (".xml", ".xsd")


@dataclass(frozen=True)
class CatMember:
    """One member of a ``.cat`` index, locatable in the sibling ``.dat``."""

    path: str          # normalized virtual path (forward slashes, no leading /)
    size: int
    mtime: int
    md5: str
    cat_path: Path     # the .cat this came from (.dat is the same stem)
    dat_offset: int


def _parse_line(line: str) -> tuple[str, int, int, str] | None:
    """Parse one index line into ``(path, size, mtime, md5)`` or ``None`` if malformed."""
    stripped = line.strip()
    if not stripped:
        return None
    parts = stripped.rsplit(" ", 3)
    if len(parts) != 4:
        return None
    raw_path, size_s, mtime_s, md5 = parts
    try:
        size, mtime = int(size_s), int(mtime_s)
    except ValueError:
        return None
    if size < 0 or mtime < 0 or not _MD5_RE.match(md5):
        return None
    normalized = raw_path.replace("\\", "/").lstrip("/")
    return normalized, size, mtime, md5


def _iter_mod_cats(mod_dir: Path) -> list[Path]:
    """Return a mod's readable catalogs (subst_* then ext_*, numeric order).

    subst_ (base substitutions) load before ext_ (extension-local) so that on the
    rare path defined by both, the extension-local copy wins — matching how a mod's
    own additions take precedence over its base overrides. Version/diff catalogs are
    skipped with a warning.
    """
    if not mod_dir.is_dir():
        return []
    plain: list[tuple[int, int, Path]] = []  # (prefix_rank, numeric_id, path)
    for p in sorted(mod_dir.iterdir()):
        if not p.is_file() or p.name.lower().endswith("_sig.cat"):
            continue
        if _VERSION_CAT_RE.match(p.name):
            logger.warning(
                "Skipping version/diff catalog %s (unsupported outside base-game DLC)", p.name
            )
            continue
        m = _PLAIN_CAT_RE.match(p.name)
        if not m:
            continue
        prefix_rank = 0 if m.group(1).lower() == "subst" else 1
        plain.append((prefix_rank, int(m.group(2)), p))
    plain.sort(key=lambda t: (t[0], t[1]))
    return [p for _, _, p in plain]


def _read_index(cat_path: Path, xml_only: bool) -> list[CatMember]:
    """Parse a single ``.cat`` into members with correct cumulative ``.dat`` offsets.

    Offsets accumulate over EVERY member (even non-XML ones we don't return), because
    the ``.dat`` concatenates all payloads regardless of what we choose to expose.
    """
    members: list[CatMember] = []
    offset = 0
    with open(cat_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parsed = _parse_line(line)
            if parsed is None:
                if line.strip():
                    logger.warning("Malformed catalog line in %s: %r", cat_path.name, line.strip())
                continue
            path, size, mtime, md5 = parsed
            if not xml_only or path.lower().endswith(_XML_SUFFIXES):
                members.append(CatMember(path, size, mtime, md5, cat_path, offset))
            offset += size
    return members


def build_mod_vfs(mod_dir: Path, xml_only: bool = True) -> dict[str, CatMember]:
    """Merge all of a mod's catalogs into ``{virtual_path: CatMember}``.

    Later catalogs override earlier ones for the same virtual path. Returns an empty
    dict for a loose-only (or nonexistent) mod. When *xml_only*, only ``.xml``/``.xsd``
    members are indexed (geometry/textures/audio are skipped).
    """
    vfs: dict[str, CatMember] = {}
    for cat_path in _iter_mod_cats(mod_dir):
        for member in _read_index(cat_path, xml_only):
            vfs[member.path] = member
    return vfs


@lru_cache(maxsize=256)
def _cached_vfs(mod_dir_str: str, xml_only: bool) -> dict[str, CatMember]:
    return build_mod_vfs(Path(mod_dir_str), xml_only)


def mod_vfs(mod_dir: Path, xml_only: bool = True) -> dict[str, CatMember]:
    """Memoized :func:`build_mod_vfs` — safe within a single CLI run (cats are static)."""
    return _cached_vfs(str(mod_dir), xml_only)


def read_member(member: CatMember, verify: bool = True) -> bytes:
    """Read a member's raw bytes from its ``.dat``; verify the MD5 by default."""
    dat_path = member.cat_path.with_suffix(".dat")
    with open(dat_path, "rb") as f:
        f.seek(member.dat_offset)
        data = f.read(member.size)
    if len(data) != member.size:
        raise OSError(
            f"Short read for {member.path} in {dat_path.name}: "
            f"expected {member.size}, got {len(data)}"
        )
    if verify:
        actual = hashlib.md5(data).hexdigest()
        if actual != member.md5:
            raise OSError(
                f"MD5 mismatch for {member.path} in {dat_path.name}: "
                f"index {member.md5}, actual {actual}"
            )
    return data


def _get_ci(vfs: dict[str, CatMember], vpath: str) -> CatMember | None:
    """Case-insensitive VFS lookup — X4 treats virtual paths case-insensitively
    (e.g. VRO ships ``t/0001-L007.xml`` where others use ``l007``)."""
    member = vfs.get(vpath)
    if member is not None:
        return member
    low = vpath.lower()
    for k, v in vfs.items():
        if k.lower() == low:
            return v
    return None


def read_path(mod_dir: Path, vpath: str, verify: bool = True) -> bytes | None:
    """Read one virtual path's bytes from a mod's catalogs, or ``None`` if absent."""
    vpath = vpath.replace("\\", "/").lstrip("/")
    member = _get_ci(mod_vfs(mod_dir), vpath)
    return None if member is None else read_member(member, verify=verify)


def is_packed(mod_dir: Path) -> bool:
    """True if the mod ships any readable catalog (vs loose files only)."""
    return bool(_iter_mod_cats(mod_dir))

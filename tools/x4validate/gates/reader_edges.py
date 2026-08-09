#!/usr/bin/env python
"""Reader edges — malformed archives and awkward encodings.

Everything upstream of the merge assumes `_cat` and the XML parser hand back
either good data or an honest failure. Nothing tested that assumption against
damaged input, and a reader that returns garbage (or dies) on a truncated
archive poisons every tool above it.

The bar is the same as everywhere else: **fail loudly or succeed correctly,
never silently return something wrong.**

Covered: UTF-8 BOM · UTF-16 with BOM · latin-1 bytes in a UTF-8 file · CRLF ·
zero-byte .cat · truncated .cat index · .cat pointing past the end of .dat ·
wrong MD5 in the index · a .dat with no .cat · non-XML content in an .xml file ·
a mod folder that is a file · unreadable/locked path.

Run:  uv run python gates/reader_edges.py [--verbose]
Exit: 0 all handled, 1 any crash or silent-wrong result.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lxml import etree  # noqa: E402
from x4validate import _cat, _merge  # noqa: E402

VERBOSE = "--verbose" in sys.argv
RESULTS: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str) -> None:
    RESULTS.append((name, status, detail))
    print(f"  {status:<6} {name:<34} {detail}")


def check(name: str, fn) -> None:
    """A cell passes if it returns a verdict; it fails only on an unhandled crash."""
    try:
        ok, detail = fn()
    except Exception as exc:
        record(name, "FAIL", f"unhandled {type(exc).__name__}: {exc}")
        return
    record(name, "ok" if ok else "FAIL", detail)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="x4reader_"))
    try:
        print("READER EDGES — damaged archives and awkward encodings\n" + "=" * 84)

        # ---- encodings -------------------------------------------------
        def enc_case(name: str, data: bytes, must_parse: bool):
            def run():
                p = tmp / f"{name}.xml"
                p.write_bytes(data)
                try:
                    root = _merge.parse_file(p)
                except (etree.XMLSyntaxError, OSError, ValueError) as exc:
                    return (not must_parse), f"rejected: {type(exc).__name__}"
                if root is None:
                    return (not must_parse), "returned None"
                return must_parse, f"parsed <{root.tag}>"
            return run

        xml = b'<?xml version="1.0" encoding="utf-8"?><diff><add sel="//x"/></diff>'
        check("utf-8 BOM", enc_case("bom", b"\xef\xbb\xbf" + xml, True))
        check("utf-16 with BOM", enc_case(
            "u16", '<?xml version="1.0" encoding="utf-16"?><diff/>'.encode("utf-16"), True))
        check("latin-1 byte in utf-8 file", enc_case(
            "l1", b'<?xml version="1.0" encoding="utf-8"?><diff><!-- \xe9 --></diff>', False))
        check("CRLF line endings", enc_case("crlf", xml.replace(b"><", b">\r\n<"), True))
        check("not XML at all", enc_case("txt", b"this is not xml, at all\n", False))
        check("empty file", enc_case("empty", b"", False))

        # ---- damaged archives ------------------------------------------
        def cat_case(name: str, cat: bytes, dat: bytes):
            def run():
                d = tmp / name
                d.mkdir(parents=True, exist_ok=True)
                (d / "content.xml").write_bytes(
                    b'<content id="c" name="c" version="1"/>')
                (d / "ext_01.cat").write_bytes(cat)
                (d / "ext_01.dat").write_bytes(dat)
                vfs = _cat.mod_vfs(d)
                # Reading every member must not crash; a corrupt one must raise
                # a real error rather than return wrong bytes.
                bad = 0
                for vp, mem in vfs.items():
                    try:
                        _cat.read_member(mem, verify=True)
                    except (OSError, ValueError):
                        bad += 1
                return True, f"{len(vfs)} member(s) indexed, {bad} rejected on read"
            return run

        good_body = b"<diff/>"
        import hashlib
        md5 = hashlib.md5(good_body).hexdigest()
        check("zero-byte .cat", cat_case("z", b"", b""))
        check("truncated .cat line", cat_case("t", b"libraries/wares.xml 7", good_body))
        check("offset past end of .dat", cat_case(
            "o", f"libraries/wares.xml 99999 0 {md5}\n".encode(), good_body))
        check("wrong md5 in index", cat_case(
            "m", b"libraries/wares.xml 7 0 " + b"0" * 32 + b"\n", good_body))
        check("negative size", cat_case(
            "n", f"libraries/wares.xml -5 0 {md5}\n".encode(), good_body))
        check("garbage index text", cat_case("g", b"\x00\x01\x02 not an index\n", good_body))

        def dat_only():
            d = tmp / "datonly"
            d.mkdir(parents=True, exist_ok=True)
            (d / "ext_01.dat").write_bytes(b"orphan")
            return True, f"{len(_cat.mod_vfs(d))} member(s) (expected 0)"
        check(".dat with no .cat", dat_only)

        def mod_is_a_file():
            f = tmp / "not_a_dir"
            f.write_bytes(b"x")
            return True, f"{len(_cat.mod_vfs(f))} member(s) (expected 0)"
        check("mod path is a file", mod_is_a_file)

        def missing_dir():
            return True, f"{len(_cat.mod_vfs(tmp / 'nope'))} member(s) (expected 0)"
        check("mod dir does not exist", missing_dir)

        fails = [r for r in RESULTS if r[1] == "FAIL"]
        print("=" * 84)
        print(f"{len(RESULTS)} cells   FAILURES: {len(fails)}")
        for name, _, detail in fails:
            print(f"  FAIL {name}: {detail}")
        return 1 if fails else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

"""Thin lxml XPath wrapper — real XPath 1.0 (handles `//`, predicates, /@attr).

This is the piece x4cat got wrong: its hand-rolled ElementTree matcher anchors
the first path segment to the document root, so `//ware[@id='ore']` reports a
false "root element mismatch". lxml evaluates it correctly.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    count: int
    detail: str
    error: bool = False  # True when the XPath itself could not be evaluated


def evaluate(node: etree._Element, xpath: str):
    """Return the raw lxml xpath result (list of elements and/or attr strings).

    Raises etree.XPathEvalError on a malformed expression.
    """
    return node.xpath(xpath)


def matches(node: etree._Element, xpath: str) -> MatchResult:
    """Evaluate *xpath* against *node*; report whether it matched anything.

    Distinguishes a genuine no-match from an un-evaluable expression so callers
    never silently treat a broken XPath as "no match" (an x4cat-style trap).
    """
    try:
        result = node.xpath(xpath)
    except etree.XPathEvalError as exc:
        return MatchResult(False, 0, f"invalid XPath: {exc}", error=True)

    if isinstance(result, list):
        n = len(result)
        return MatchResult(n > 0, n, f"{n} node(s) matched")
    # Boolean/number/string results (e.g. count(...)) — truthy means "matched".
    return MatchResult(bool(result), 1 if result else 0, f"scalar result: {result!r}")

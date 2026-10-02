"""Conservative recognizer for whole-database content searches.

This is deliberately NOT an XQuery parser. Acceptance proves a small grammar;
rejection says only that we cannot certify its zero. BaseX still executes it.
"""
from __future__ import annotations

import re
from lxml import etree


def is_qname(text: str) -> bool:
    parts = text.split(':')
    if len(parts) > 2:
        return False
    try:
        return all(p and etree.QName(p).namespace is None
                   and etree.QName(p).localname == p for p in parts)
    except ValueError:
        return False


class Unsupported(ValueError):
    pass


def _tokens(text: str) -> list[tuple[str, str]]:
    out = []
    i = 0
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith('(:', i):
            depth = 1; i += 2
            while i < len(text) and depth:
                if text.startswith('(:', i):
                    depth += 1; i += 2
                elif text.startswith(':)', i):
                    depth -= 1; i += 2
                else:
                    i += 1
            if depth:
                raise Unsupported('unclosed comment')
        elif c in "\"'":
            quote = c; value = []; i += 1
            while i < len(text):
                if text[i] == quote:
                    if i+1 < len(text) and text[i+1] == quote:
                        value.append(quote); i += 2; continue
                    i += 1; break
                value.append(text[i]); i += 1
            else:
                raise Unsupported('unclosed string')
            out.append(('string', ''.join(value)))
        else:
            number = re.match(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', text[i:])
            if number:
                value = number.group(); out.append(('number', value)); i += len(value)
            elif text[i:i+2] in ('//', '!=', '<=', '>='):
                out.append(('symbol', text[i:i+2])); i += 2
            elif c in '/@.*()[]=<>+-':
                out.append(('symbol', c)); i += 1
            elif c.isalpha() or c == '_' or ord(c) >= 128:
                j = i+1
                while j < len(text) and (text[j].isalnum() or text[j] in '_.-:' or ord(text[j]) >= 128):
                    j += 1
                value = text[i:j]
                if not is_qname(value):
                    raise Unsupported(f'unsupported name {value!r}')
                out.append(('name', value)); i = j
            else:
                raise Unsupported(f'unsupported syntax near {text[i:i+24]!r}')
    out.append(('end', ''))
    return out


class _Parser:
    def __init__(self, text: str, db: str):
        self.tokens = _tokens(text); self.i = 0; self.db = db

    def peek(self):
        return self.tokens[self.i][1]

    def take(self, value):
        if self.peek() == value:
            self.i += 1; return True
        return False

    def require(self, value):
        if not self.take(value):
            raise Unsupported(f'expected {value!r}, got {self.peek()!r}')

    def root(self):
        if self.take('('):
            self.root(); self.require(')')
        else:
            if self.peek() not in ('collection', 'fn:collection', 'db:get', 'db:open'):
                raise Unsupported('expected a literal whole-database root')
            self.i += 1; self.require('(')
            if self.tokens[self.i] != ('string', self.db):
                raise Unsupported('expected the selected database as a string literal')
            self.i += 1; self.require(')')
        self.tail()

    def predicates(self):
        while self.take('['):
            self.boolean(); self.require(']')

    def tail(self):
        self.predicates()
        while self.peek() in ('/', '//'):
            self.i += 1; self.step(); self.predicates()

    def step(self):
        attribute = self.take('@')
        if self.take('*'):
            return
        if not attribute and self.take('.'):
            return
        if self.tokens[self.i][0] != 'name':
            raise Unsupported('expected a child or attribute name')
        self.i += 1

    def path(self):
        # Only relative content paths, never absolute paths, axes, or variables.
        self.step(); self.tail()

    def boolean(self):
        self.conjunction()
        while self.take('or'):
            self.conjunction()

    def conjunction(self):
        self.condition()
        while self.take('and'):
            self.condition()

    def condition(self):
        if self.take('('):
            self.boolean(); self.require(')'); return
        name = self.peek()
        if name in ('exists', 'empty', 'not', 'fn:exists', 'fn:empty', 'fn:not') and self.tokens[self.i+1][1] == '(':
            self.i += 2
            if name.rsplit(':', 1)[-1] == 'not':
                self.boolean()
            else:
                self.path()
            self.require(')'); return
        self.path()
        if self.peek() in ('=', '!=', '<', '<=', '>', '>=', 'eq', 'ne', 'lt', 'le', 'gt', 'ge'):
            self.i += 1
            signed = self.take('+') or self.take('-')
            kind, _ = self.tokens[self.i]
            if kind not in ('number', 'string') or (signed and kind != 'number'):
                raise Unsupported('comparisons require a string or numeric literal')
            self.i += 1


def certification_issue(query: str, db: str) -> str | None:
    try:
        parser = _Parser(query, db)
        parser.root()
        if parser.tokens[parser.i][0] != 'end':
            raise Unsupported(f'unsupported syntax near {parser.peek()!r}')
    except (Unsupported, RecursionError) as exc:
        return str(exc) or 'query nesting exceeds the recognizer limit'
    return None

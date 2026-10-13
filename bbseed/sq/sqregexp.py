"""The sqstd `regexp` class, backed by Python's `re`.

Approximation, not a port: sqstd_rex has its own matcher (limited backtracking),
so exotic patterns can differ. The game's scripts use it for mod ids and version
strings only, far from anything that draws random numbers.
"""
import re

from .runtime import NativeFn, SqClass, SqError, SqTable

# sqstd_rex character classes that Python lacks or spells differently
_CLASSES = {
    "a": "A-Za-z", "l": "a-z", "u": "A-Z", "x": "0-9A-Fa-f",
    "c": r"\x00-\x1f\x7f", "p": r"!-/:-@\[-`{-~",
}
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v"}
_NATIVE = "wWsSdDbB"       # same meaning in both dialects (with re.ASCII)


def translate(pattern):
    out = []
    i, n = 0, len(pattern)
    in_class = False
    while i < n:
        c = pattern[i]
        if c == "\\":
            i += 1
            if i >= n:
                raise SqError("letter expected")
            e = pattern[i]
            if e in _NATIVE:
                out.append("\\" + e)
            elif e in _CLASSES:
                out.append(_CLASSES[e] if in_class else "[" + _CLASSES[e] + "]")
            elif e.lower() in _CLASSES:
                if in_class:
                    raise SqError("negated class '\\%s' inside [] is not supported by the lab regexp" % e)
                out.append("[^" + _CLASSES[e.lower()] + "]")
            elif e in _ESCAPES:
                out.append(re.escape(_ESCAPES[e]))
            else:
                out.append(re.escape(e))
        elif in_class:
            if c == "]":
                in_class = False
                out.append(c)
            elif c == "[":
                out.append("\\[")
            else:
                out.append(c)
        elif c == "[":
            in_class = True
            out.append(c)
            if i + 1 < n and pattern[i + 1] == "^":
                out.append("^")
                i += 1
        elif c == "$":
            out.append(r"\Z")
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _span(begin, end):
    t = SqTable()
    t.newslot("begin", begin)
    t.newslot("end", end)
    return t


def make_regexp_class():
    cls = SqClass()
    cls.name = "regexp"
    key = "\0re"

    def ctor(this, pattern):
        try:
            this.vals[key] = re.compile(translate(pattern), re.ASCII | re.DOTALL)
        except re.error as e:
            raise SqError("regexp: %s" % e)

    def rx(this):
        r = this.vals.get(key)
        if r is None:
            raise SqError("invalid type tag")
        return r

    def match(this, s):
        return rx(this).fullmatch(s) is not None

    def search(this, s, start=0):
        m = rx(this).search(s, int(start))
        return None if m is None else _span(m.start(), m.end())

    def capture(this, s, start=0):
        m = rx(this).search(s, int(start))
        if m is None:
            return None
        out = []
        for g in range(m.re.groups + 1):
            b, e = m.span(g)
            # sqstd reports an empty or unmatched sub-expression as begin = end = 0
            out.append(_span(b, e) if e > b else _span(0, 0))
        return out

    for name, fn in (("constructor", ctor), ("match", match), ("search", search), ("capture", capture),
                     ("subexpcount", lambda this: rx(this).groups + 1)):
        cls.define(name, NativeFn(fn, name))
    return cls

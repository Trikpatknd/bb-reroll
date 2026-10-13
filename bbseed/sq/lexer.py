"""Squirrel 3.0.x lexer.

Tokens are tuples (type, value, line, nl_before):
  type  'ID' | 'INT' | 'FLOAT' | 'STR' | 'EOF' | the keyword/operator text itself
  nl_before  True when a newline separates this token from the previous one
             (Squirrel uses that to end statements and to refuse `x \n ++`).
"""
import re

KEYWORDS = frozenset("""
while do if else break continue return null function local for foreach in typeof base
delete try catch throw clone yield resume switch case default this class extends
constructor instanceof true false static enum const __LINE__ __FILE__
""".split())

_OPS = [
    ">>>", "<=>", "...", "<-", "==", "!=", "<=", ">=", "&&", "||", "++", "--",
    "+=", "-=", "*=", "/=", "%=", "<<", ">>", "::",
    "{", "}", "(", ")", "[", "]", ";", ",", ".", "?", ":", "=", "<", ">",
    "+", "-", "*", "/", "%", "!", "~", "^", "&", "|", "@",
]

_TOKEN_RE = re.compile(
    r"(?P<ws>[ \t\r]+)"
    r"|(?P<nl>\n)"
    r"|(?P<lc>//[^\n]*|\#[^\n]*)"
    r"|(?P<bc>/\*.*?\*/)"
    r"|(?P<hex>0[xX][0-9a-fA-F]+)"
    r"|(?P<float>\d+\.\d*(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)"
    r"|(?P<int>\d+)"
    r"|(?P<id>[A-Za-z_][A-Za-z0-9_]*)"
    r'|(?P<vstr>@")'
    r'|(?P<str>")'
    r"|(?P<chr>')"
    r"|(?P<op>" + "|".join(re.escape(o) for o in _OPS) + ")",
    re.S,
)

_ESC = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "a": "\a", "b": "\b", "f": "\f",
        "v": "\v", "\\": "\\", '"': '"', "'": "'"}


class SqSyntaxError(Exception):
    pass


def _read_string(src, i, quote, name, line):
    """Read a quoted literal starting after the opening quote; return (text, new index, newlines)."""
    out = []
    n = len(src)
    nls = 0
    while True:
        if i >= n:
            raise SqSyntaxError(f"{name}:{line}: unfinished string")
        c = src[i]
        if c == quote:
            return "".join(out), i + 1, nls
        if c == "\n":
            raise SqSyntaxError(f"{name}:{line}: newline in a constant")
        if c == "\\":
            i += 1
            e = src[i]
            if e == "x":
                j = i + 1
                while j < n and j < i + 5 and src[j] in "0123456789abcdefABCDEF":
                    j += 1
                out.append(chr(int(src[i + 1:j], 16) & 0xFF))
                i = j
                continue
            if e not in _ESC:
                raise SqSyntaxError(f"{name}:{line}: unrecognised escaper char '{e}'")
            out.append(_ESC[e])
            i += 1
            continue
        out.append(c)
        i += 1


def tokenize(src: str, name: str = "?"):
    toks = []
    i, n, line, nl = 0, len(src), 1, False
    match = _TOKEN_RE.match
    while i < n:
        m = match(src, i)
        if m is None:
            raise SqSyntaxError(f"{name}:{line}: unexpected character {src[i]!r}")
        kind = m.lastgroup
        if kind == "ws" or kind == "lc":
            i = m.end()
        elif kind == "nl":
            line += 1
            nl = True
            i = m.end()
        elif kind == "bc":
            line += m.group().count("\n")
            i = m.end()
        elif kind == "id":
            text = m.group()
            toks.append((text if text in KEYWORDS else "ID", text, line, nl))
            nl = False
            i = m.end()
        elif kind == "int":
            text = m.group()
            if len(text) > 1 and text[0] == "0":
                value = int(text, 8) if all(c in "01234567" for c in text) else int(text)
            else:
                value = int(text)
            toks.append(("INT", value, line, nl))
            nl = False
            i = m.end()
        elif kind == "hex":
            value = int(m.group(), 16) & 0xFFFFFFFF
            if value & 0x80000000:
                value -= 1 << 32
            toks.append(("INT", value, line, nl))
            nl = False
            i = m.end()
        elif kind == "float":
            toks.append(("FLOAT", float(m.group()), line, nl))
            nl = False
            i = m.end()
        elif kind == "str":
            text, i, _ = _read_string(src, m.end(), '"', name, line)
            toks.append(("STR", text, line, nl))
            nl = False
        elif kind == "chr":
            text, i, _ = _read_string(src, m.end(), "'", name, line)
            if len(text) != 1:
                raise SqSyntaxError(f"{name}:{line}: constant too long or empty")
            toks.append(("INT", ord(text), line, nl))
            nl = False
        elif kind == "vstr":
            j = m.end()
            out = []
            start_line = line
            while True:
                if j >= n:
                    raise SqSyntaxError(f"{name}:{start_line}: unfinished verbatim string")
                c = src[j]
                if c == '"':
                    if j + 1 < n and src[j + 1] == '"':
                        out.append('"')
                        j += 2
                        continue
                    j += 1
                    break
                if c == "\n":
                    line += 1
                out.append(c)
                j += 1
            toks.append(("STR", "".join(out), start_line, nl))
            nl = False
            i = j
        else:  # op
            text = m.group()
            toks.append((text, text, line, nl))
            nl = False
            i = m.end()
    toks.append(("EOF", None, line, True))
    return toks

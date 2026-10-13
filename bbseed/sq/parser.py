"""Squirrel 3.0.x parser: tokens -> AST (plain tuples, first item = node kind).

Expressions
  ('int', v) ('float', v) ('str', v) ('null',) ('true',) ('false',) ('this',) ('base',)
  ('id', name, line) ('root', name) ('line', n) ('file',)
  ('table', [(key_expr, value_expr)...]) ('array', [expr...])
  ('func', name, [(param, default|None)...], varargs, body_stmt, line)
  ('class', base_expr|None, [(is_static, key_expr, value_expr)...], line)
  ('get', obj, key_expr) ('call', callee, [args], line)
  ('un', op, e) ('bin', op, a, b) ('and', a, b) ('or', a, b) ('tern', c, a, b)
  ('in', a, b) ('instanceof', a, b) ('comma', [e...])
  ('assign', target, e) ('newslot', target, e) ('opassign', op, target, e)
  ('incdec', +1|-1, is_prefix, target) ('delete', target)
Statements
  ('expr', e, line) ('local', [(name, init|None)...], line) ('block', [stmt...])
  ('if', c, a, b|None) ('while', c, body) ('dowhile', body, c)
  ('for', init_stmt|None, cond|None, inc_expr|None, body)
  ('foreach', key_name|None, val_name, e, body)
  ('switch', e, [(case_expr|None, [stmt...])...])
  ('break',) ('continue',) ('return', e|None, line) ('yield', e|None) ('throw', e, line)
  ('try', body, catch_name, catch_body)
  ('const', name, value) ('enum', name, [(member, value)...])
"""
from .lexer import KEYWORDS, SqSyntaxError, tokenize

_ASSIGN_OPS = {"=", "<-", "+=", "-=", "*=", "/=", "%="}
_BIN_LEVELS = [
    ("|",), ("^",), ("&",), ("==", "!=", "<=>"), ("<", ">", "<=", ">=", "in", "instanceof"),
    ("<<", ">>", ">>>"), ("+", "-"), ("*", "/", "%"),
]


class Parser:
    def __init__(self, src: str, name: str = "?"):
        self.name = name
        self.toks = tokenize(src, name)
        self.i = 0

    # --- token helpers ---
    def err(self, msg):
        t = self.toks[self.i]
        raise SqSyntaxError(f"{self.name}:{t[2]}: {msg} (near {t[1]!r})")

    def expect(self, typ):
        t = self.toks[self.i]
        if t[0] != typ:
            self.err(f"expected '{typ}'")
        self.i += 1
        return t[1]

    def accept(self, typ):
        if self.toks[self.i][0] == typ:
            self.i += 1
            return True
        return False

    def end_of_statement(self):
        t = self.toks[self.i]
        return t[3] or t[0] in ("EOF", "}", ";")

    def optional_semicolon(self):
        if self.toks[self.i][0] == ";":
            self.i += 1
        elif not self.end_of_statement():
            self.err("end of statement expected (; or lf)")

    # --- program / statements ---
    def parse_program(self):
        stmts = []
        while self.toks[self.i][0] != "EOF":
            stmts.append(self.statement())
            if self.toks[self.i - 1][0] not in ("}", ";"):
                self.optional_semicolon()
        return ("block", stmts)

    def statements_until(self, *closers):
        stmts = []
        while self.toks[self.i][0] not in closers:
            if self.toks[self.i][0] == "EOF":
                self.err("unexpected end of file")
            stmts.append(self.statement())
            if self.toks[self.i - 1][0] not in ("}", ";"):
                self.optional_semicolon()
        return stmts

    def block(self):
        self.expect("{")
        stmts = self.statements_until("}")
        self.expect("}")
        return ("block", stmts)

    def statement(self):
        t = self.toks[self.i]
        typ, line = t[0], t[2]
        if typ == ";":
            self.i += 1
            return ("block", [])
        if typ == "{":
            return self.block()
        if typ == "local":
            self.i += 1
            return self.local_decl(line)
        if typ == "if":
            self.i += 1
            self.expect("(")
            cond = self.comma_expr()
            self.expect(")")
            then = self.statement()
            other = None
            # Squirrel allows `if (x) stmt; else stmt`: the ';' belongs to the then-branch
            save = self.i
            if self.toks[self.i][0] == ";" and self.toks[self.i + 1][0] == "else":
                self.i += 1
            if self.accept("else"):
                other = self.statement()
            else:
                self.i = save
            return ("if", cond, then, other)
        if typ == "while":
            self.i += 1
            self.expect("(")
            cond = self.comma_expr()
            self.expect(")")
            return ("while", cond, self.statement())
        if typ == "do":
            self.i += 1
            body = self.statement()
            self.accept(";")
            self.expect("while")
            self.expect("(")
            cond = self.comma_expr()
            self.expect(")")
            return ("dowhile", body, cond)
        if typ == "for":
            self.i += 1
            self.expect("(")
            init = None
            if self.toks[self.i][0] == "local":
                self.i += 1
                init = self.local_decl(line)
            elif self.toks[self.i][0] != ";":
                init = ("expr", self.comma_expr(), line)
            self.expect(";")
            cond = None if self.toks[self.i][0] == ";" else self.comma_expr()
            self.expect(";")
            inc = None if self.toks[self.i][0] == ")" else self.comma_expr()
            self.expect(")")
            return ("for", init, cond, inc, self.statement())
        if typ == "foreach":
            self.i += 1
            self.expect("(")
            first = self.expect("ID")
            key = None
            val = first
            if self.accept(","):
                key = first
                val = self.expect("ID")
            self.expect("in")
            seq = self.expr()
            self.expect(")")
            return ("foreach", key, val, seq, self.statement())
        if typ == "switch":
            self.i += 1
            self.expect("(")
            subject = self.comma_expr()
            self.expect(")")
            self.expect("{")
            cases = []
            while self.toks[self.i][0] in ("case", "default"):
                if self.accept("case"):
                    label = self.expr()
                else:
                    self.i += 1
                    label = None
                self.expect(":")
                cases.append((label, self.statements_until("case", "default", "}")))
            self.expect("}")
            return ("switch", subject, cases)
        if typ == "break":
            self.i += 1
            return ("break",)
        if typ == "continue":
            self.i += 1
            return ("continue",)
        if typ == "return" or typ == "yield":
            self.i += 1
            value = None if self.end_of_statement() else self.comma_expr()
            return ("return", value, line) if typ == "return" else ("yield", value)
        if typ == "throw":
            self.i += 1
            return ("throw", self.comma_expr(), line)
        if typ == "try":
            self.i += 1
            body = self.statement()
            if self.toks[self.i - 1][0] not in ("}", ";"):
                self.accept(";")
            self.expect("catch")
            self.expect("(")
            name = self.expect("ID")
            self.expect(")")
            return ("try", body, name, self.statement())
        if typ == "function":
            self.i += 1
            names = [self.expect("ID")]
            while self.accept("::"):
                names.append(self.expect("ID"))
            func = self.function_rest(names[-1], line)
            target = ("id", names[0], line)
            for n in names[1:]:
                target = ("get", target, ("str", n))
            if len(names) == 1:
                target = ("get", ("this",), ("str", names[0]))
            return ("expr", ("newslot", target, func), line)
        if typ == "class":
            self.i += 1
            target = self.prefixed_expr()
            cls = self.class_rest(line)
            if target[0] == "id":
                target = ("get", ("this",), ("str", target[1]))
            return ("expr", ("newslot", target, cls), line)
        if typ == "const":
            self.i += 1
            name = self.expect("ID")
            self.expect("=")
            return ("const", name, self.scalar_literal())
        if typ == "enum":
            self.i += 1
            name = self.expect("ID")
            self.expect("{")
            members, nxt = [], 0
            while self.toks[self.i][0] != "}":
                m = self.expect("ID")
                if self.accept("="):
                    value = self.scalar_literal()
                else:
                    value = nxt
                if isinstance(value, int) and not isinstance(value, bool):
                    nxt = value + 1
                members.append((m, value))
                self.accept(",")
            self.expect("}")
            return ("enum", name, members)
        return ("expr", self.comma_expr(), line)

    def scalar_literal(self):
        t = self.toks[self.i]
        neg = False
        if t[0] == "-":
            neg = True
            self.i += 1
            t = self.toks[self.i]
        if t[0] in ("INT", "FLOAT"):
            self.i += 1
            return -t[1] if neg else t[1]
        if t[0] == "STR" and not neg:
            self.i += 1
            return t[1]
        if t[0] in ("true", "false") and not neg:
            self.i += 1
            return t[0] == "true"
        self.err("scalar expected : integer, float or string")

    def local_decl(self, line):
        if self.accept("function"):
            name = self.expect("ID")
            return ("local", [(name, self.function_rest(name, line))], line)
        decls = []
        while True:
            name = self.expect("ID")
            init = self.expr() if self.accept("=") else None
            decls.append((name, init))
            if not self.accept(","):
                break
        return ("local", decls, line)

    # --- functions / classes / tables ---
    def function_rest(self, name, line):
        self.expect("(")
        params, varargs = [], False
        while self.toks[self.i][0] != ")":
            if self.accept("..."):
                varargs = True
                break
            pname = self.expect("ID")
            default = self.expr() if self.accept("=") else None
            params.append((pname, default))
            if not self.accept(","):
                break
        self.expect(")")
        body = self.statement()
        return ("func", name, params, varargs, body, line)

    def lambda_rest(self, line):
        self.expect("(")
        params, varargs = [], False
        while self.toks[self.i][0] != ")":
            if self.accept("..."):
                varargs = True
                break
            pname = self.expect("ID")
            default = self.expr() if self.accept("=") else None
            params.append((pname, default))
            if not self.accept(","):
                break
        self.expect(")")
        body = ("return", self.expr(), line)
        return ("func", None, params, varargs, body, line)

    def class_rest(self, line):
        base = None
        if self.accept("extends"):
            base = self.expr()
        self.expect("{")
        members = []
        while self.toks[self.i][0] != "}":
            static = self.accept("static")
            t = self.toks[self.i]
            if t[0] == "function":
                self.i += 1
                fname = self.expect("ID")
                members.append((static, ("str", fname), self.function_rest(fname, t[2])))
            elif t[0] == "constructor":
                self.i += 1
                members.append((static, ("str", "constructor"), self.function_rest("constructor", t[2])))
            elif t[0] == "[":
                self.i += 1
                key = self.comma_expr()
                self.expect("]")
                self.expect("=")
                members.append((static, key, self.expr()))
            else:
                key = self.expect("ID")
                self.expect("=")
                members.append((static, ("str", key), self.expr()))
            self.accept(";")
        self.expect("}")
        return ("class", base, members, line)

    def table_rest(self):
        entries = []
        while self.toks[self.i][0] != "}":
            t = self.toks[self.i]
            if t[0] == "function":
                self.i += 1
                fname = self.expect("ID")
                entries.append((("str", fname), self.function_rest(fname, t[2])))
            elif t[0] == "[":
                self.i += 1
                key = self.comma_expr()
                self.expect("]")
                self.expect("=")
                entries.append((key, self.expr()))
            elif t[0] == "STR":      # JSON style  "key": value
                self.i += 1
                self.expect(":")
                entries.append((("str", t[1]), self.expr()))
            else:
                key = self.expect("ID")
                self.expect("=")
                entries.append((("str", key), self.expr()))
            self.accept(",")
        self.expect("}")
        return ("table", entries)

    # --- expressions ---
    def comma_expr(self):
        first = self.expr()
        if self.toks[self.i][0] != ",":
            return first
        items = [first]
        while self.accept(","):
            items.append(self.expr())
        return ("comma", items)

    def expr(self):
        left = self.ternary()
        op = self.toks[self.i][0]
        if op in _ASSIGN_OPS:
            if left[0] not in ("id", "get", "root"):
                if op == "=":
                    # Real Squirrel 3.0.4 accepts `typeof x = "integer"`: the unary operator
                    # leaves the expression state assignable, and the store lands in a
                    # temporary. Net effect: both sides evaluated, value = right side.
                    self.i += 1
                    return ("comma", [left, self.expr()])
                self.err("can't assign expression")
            self.i += 1
            right = self.expr()
            if op == "=":
                return ("assign", left, right)
            if op == "<-":
                if left[0] == "id":
                    left = ("get", ("this",), ("str", left[1]))
                elif left[0] == "root":
                    left = ("get", ("rootobj",), ("str", left[1]))
                return ("newslot", left, right)
            return ("opassign", op[0], left, right)
        return left

    def ternary(self):
        cond = self.logical_or()
        if self.accept("?"):
            a = self.expr()
            self.expect(":")
            b = self.expr()
            return ("tern", cond, a, b)
        return cond

    def logical_or(self):
        left = self.logical_and()
        while self.accept("||"):
            left = ("or", left, self.logical_and())
        return left

    def logical_and(self):
        left = self.binary(0)
        while self.accept("&&"):
            left = ("and", left, self.binary(0))
        return left

    def binary(self, level):
        if level == len(_BIN_LEVELS):
            return self.unary()
        ops = _BIN_LEVELS[level]
        left = self.binary(level + 1)
        while self.toks[self.i][0] in ops:
            op = self.toks[self.i][0]
            self.i += 1
            right = self.binary(level + 1)
            if op == "in":
                left = ("in", left, right)
            elif op == "instanceof":
                left = ("instanceof", left, right)
            else:
                left = ("bin", op, left, right)
        return left

    def unary(self):
        t = self.toks[self.i]
        typ = t[0]
        if typ == "-":
            self.i += 1
            nt = self.toks[self.i]
            if nt[0] == "INT":
                self.i += 1
                return self.postfix(("int", -nt[1]))
            if nt[0] == "FLOAT":
                self.i += 1
                return self.postfix(("float", -nt[1]))
            return ("un", "-", self.unary())
        if typ in ("!", "~", "typeof", "resume", "clone"):
            self.i += 1
            return ("un", typ, self.unary())
        if typ in ("++", "--"):
            self.i += 1
            target = self.unary()
            if target[0] not in ("id", "get", "root"):
                self.err("can't '++' or '--' an expression")
            return ("incdec", 1 if typ == "++" else -1, True, target)
        if typ == "delete":
            self.i += 1
            target = self.unary()
            if target[0] != "get":
                self.err("can't delete an expression")
            return ("delete", target)
        return self.prefixed_expr()

    def prefixed_expr(self):
        return self.postfix(self.primary())

    def postfix(self, node):
        while True:
            t = self.toks[self.i]
            typ = t[0]
            if typ == ".":
                self.i += 1
                name = self.toks[self.i]
                if name[0] != "ID" and name[0] not in KEYWORDS:
                    self.err("expected 'IDENTIFIER'")
                self.i += 1
                node = ("get", node, ("str", name[1]))
            elif typ == "[":
                if t[3]:
                    break      # a '[' on a new line starts a new statement
                self.i += 1
                key = self.comma_expr()
                self.expect("]")
                node = ("get", node, key)
            elif typ == "(":
                self.i += 1
                args = []
                while self.toks[self.i][0] != ")":
                    args.append(self.expr())
                    if not self.accept(","):
                        break
                self.expect(")")
                node = ("call", node, args, t[2])
            elif typ in ("++", "--"):
                if t[3]:
                    break      # `x \n ++y` : the ++ belongs to the next statement
                if node[0] not in ("id", "get", "root"):
                    self.err("can't '++' or '--' an expression")
                self.i += 1
                node = ("incdec", 1 if typ == "++" else -1, False, node)
            else:
                break
        return node

    def primary(self):
        t = self.toks[self.i]
        typ, line = t[0], t[2]
        self.i += 1
        if typ == "ID":
            return ("id", t[1], line)
        if typ == "INT":
            return ("int", t[1])
        if typ == "FLOAT":
            return ("float", t[1])
        if typ == "STR":
            return ("str", t[1])
        if typ == "this":
            return ("this",)
        if typ == "base":
            return ("base",)
        if typ == "null":
            return ("null",)
        if typ == "true":
            return ("true",)
        if typ == "false":
            return ("false",)
        if typ == "::":
            return ("root", self.expect("ID"))
        if typ == "(":
            inner = self.comma_expr()
            self.expect(")")
            return inner
        if typ == "{":
            return self.table_rest()
        if typ == "[":
            items = []
            while self.toks[self.i][0] != "]":
                items.append(self.expr())
                self.accept(",")
            self.expect("]")
            return ("array", items)
        if typ == "function":
            return self.function_rest(None, line)
        if typ == "@":
            return self.lambda_rest(line)
        if typ == "class":
            return self.class_rest(line)
        if typ == "constructor":
            return ("id", "constructor", line)
        if typ == "__LINE__":
            return ("int", line)
        if typ == "__FILE__":
            return ("str", self.name)
        self.i -= 1
        self.err("expression expected")


def parse(src: str, name: str = "?"):
    return Parser(src, name).parse_program()

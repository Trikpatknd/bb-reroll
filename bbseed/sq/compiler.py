"""AST -> Python closures.

A call frame is a list:  [this, closure, return_value, vargv, slot0, slot1, ...]
Statements compile to  ex(f) -> None | BRK | CNT | RET   (RET: value is in f[2]).
Expressions compile to ev(f) -> value.

Locals live in frame slots. If a function contains nested functions, all of
its locals are boxed in one-element lists ("cells") so closures can share
them; a fresh cell is made each time a `local` statement runs, which gives
Squirrel's per-iteration capture behaviour for locals declared inside loops.
"""
from . import runtime as R
from .runtime import (SqClosure, SqError, SqTable, SqClass, FuncProto, MISSING,
                      get, set_, newslot, call, truthy, add, arith, eq, cmp, tostring)

BRK = object()
CNT = object()
RET = object()

_NESTED = ("func", "class")


def _has_nested(node):
    """True if the AST under node (excluding node itself) defines a function or class."""
    stack = [node]
    first = True
    while stack:
        n = stack.pop()
        if type(n) is tuple:
            if not first and n and n[0] in _NESTED:
                return True
            first = False
            stack.extend(n)
        elif type(n) is list:
            stack.extend(n)
    return False


class FuncState:
    def __init__(self, parent, cells):
        self.parent = parent
        self.cells = cells
        self.scopes = [{}]
        self.nslots = 0
        self.freevars = []          # [(from_parent_kind, index)]  kind: 'slot' | 'free'
        self.free_index = {}
        self.traps = 0              # try-block nesting while compiling

    def declare(self, name):
        idx = 4 + self.nslots
        self.nslots += 1
        self.scopes[-1][name] = idx
        return idx

    def lookup_local(self, name):
        for scope in reversed(self.scopes):
            idx = scope.get(name)
            if idx is not None:
                return idx
        return None

    def resolve(self, name):
        """-> ('slot', idx) | ('free', j) | None"""
        idx = self.lookup_local(name)
        if idx is not None:
            return ("slot", idx)
        j = self.free_index.get(name)
        if j is not None:
            return ("free", j)
        if self.parent is not None:
            r = self.parent.resolve(name)
            if r is not None:
                j = len(self.freevars)
                self.freevars.append(r)
                self.free_index[name] = j
                return ("free", j)
        return None


class Compiler:
    def __init__(self, vm, src_name):
        self.vm = vm
        self.src = src_name
        self.fs = None

    # ------------------------------------------------------------------ functions
    def compile_main(self, block):
        """Top-level script: a vararg function with no parameters."""
        return self._function(("func", "main", [], True, block, 1), None)

    def _function(self, node, parent_fs):
        _, name, params, varargs, body, line = node
        cells = _has_nested(body)
        fs = FuncState(parent_fs, cells)
        saved = self.fs
        self.fs = fs
        for pname, _d in params:
            fs.declare(pname)
        if body[0] == "block":
            body_ex = self._block_noscope(body[1])
        else:
            body_ex = self.stmt(body)
        self.fs = saved
        proto = FuncProto()
        proto.name = name          # None for anonymous functions
        proto.src = self.src
        proto.line = line
        proto.nparams = len(params)
        proto.varargs = varargs
        proto.nslots = fs.nslots
        proto.body = body_ex
        proto.cells = cells
        proto.freevars = fs.freevars
        proto.param_names = [p for p, _ in params] + (["vargv"] if varargs else [])
        proto.defaults = None
        return proto, [d for _p, d in params if d is not None]

    def func_expr(self, node):
        proto, default_nodes = self._function(node, self.fs)
        default_evs = [self.expr(d) for d in default_nodes]
        freevars = proto.freevars
        vm = self.vm
        if not freevars and not default_evs:
            def make(f):
                return SqClosure(proto, None, (), vm)
            return make

        def make(f):
            if freevars:
                own = f[1].fv
                fv = [f[i] if kind == "slot" else own[i] for kind, i in freevars]
            else:
                fv = None
            return SqClosure(proto, fv, [d(f) for d in default_evs], vm)
        return make

    # ------------------------------------------------------------------ statements
    def _block_noscope(self, stmts):
        exs = [self.stmt(s) for s in stmts]
        exs = [e for e in exs if e is not None]
        if not exs:
            return lambda f: None
        if len(exs) == 1:
            return exs[0]
        if len(exs) == 2:
            a, b = exs

            def run2(f):
                r = a(f)
                if r is not None:
                    return r
                return b(f)
            return run2

        def run(f):
            for e in exs:
                r = e(f)
                if r is not None:
                    return r
            return None
        return run

    def block(self, stmts):
        self.fs.scopes.append({})
        ex = self._block_noscope(stmts)
        self.fs.scopes.pop()
        return ex

    def stmt(self, node):
        kind = node[0]
        return getattr(self, "s_" + kind)(node)

    def s_block(self, node):
        if not node[1]:
            return None
        return self.block(node[1])

    def s_expr(self, node):
        ev = self.expr(node[1])

        def run(f):
            ev(f)
        return run

    def s_local(self, node):
        fs = self.fs
        cells = fs.cells
        steps = []
        for name, init in node[1]:
            ev = self.expr(init) if init is not None else None
            idx = fs.declare(name)
            steps.append((idx, ev))
        if len(steps) == 1:
            idx, ev = steps[0]
            if cells:
                if ev is None:
                    def run(f):
                        f[idx] = [None]
                else:
                    def run(f):
                        f[idx] = [ev(f)]
            else:
                if ev is None:
                    def run(f):
                        f[idx] = None
                else:
                    def run(f):
                        f[idx] = ev(f)
            return run

        def run(f):
            for idx, ev in steps:
                v = ev(f) if ev is not None else None
                f[idx] = [v] if cells else v
        return run

    def s_if(self, node):
        cond = self.cond(node[1])
        self.fs.scopes.append({})
        then = self.stmt(node[2]) or (lambda f: None)
        self.fs.scopes.pop()
        if node[3] is None:
            def run(f):
                if cond(f):
                    return then(f)
            return run
        self.fs.scopes.append({})
        other = self.stmt(node[3]) or (lambda f: None)
        self.fs.scopes.pop()

        def run(f):
            if cond(f):
                return then(f)
            return other(f)
        return run

    def s_while(self, node):
        cond = self.cond(node[1])
        self.fs.scopes.append({})
        body = self.stmt(node[2]) or (lambda f: None)
        self.fs.scopes.pop()

        def run(f):
            while cond(f):
                r = body(f)
                if r is not None:
                    if r is BRK:
                        break
                    if r is RET:
                        return r
        return run

    def s_dowhile(self, node):
        self.fs.scopes.append({})
        body = self.stmt(node[1]) or (lambda f: None)
        self.fs.scopes.pop()
        cond = self.cond(node[2])

        def run(f):
            while True:
                r = body(f)
                if r is not None:
                    if r is BRK:
                        break
                    if r is RET:
                        return r
                if not cond(f):
                    break
        return run

    def s_for(self, node):
        _, init, cond, inc, body = node
        self.fs.scopes.append({})
        init_ex = self.stmt(init) if init is not None else None
        cond_ev = self.cond(cond) if cond is not None else None
        inc_ev = self.expr(inc) if inc is not None else None
        self.fs.scopes.append({})
        body_ex = self.stmt(body) or (lambda f: None)
        self.fs.scopes.pop()
        self.fs.scopes.pop()

        def run(f):
            if init_ex is not None:
                init_ex(f)
            while cond_ev is None or cond_ev(f):
                r = body_ex(f)
                if r is not None:
                    if r is BRK:
                        break
                    if r is RET:
                        return r
                if inc_ev is not None:
                    inc_ev(f)
        return run

    def s_foreach(self, node):
        _, kname, vname, seq, body = node
        seq_ev = self.expr(seq)
        fs = self.fs
        cells = fs.cells
        fs.scopes.append({})
        kidx = fs.declare(kname if kname is not None else "@INDEX@")
        vidx = fs.declare(vname)
        fs.scopes.append({})
        body_ex = self.stmt(body) or (lambda f: None)
        fs.scopes.pop()
        fs.scopes.pop()
        iterate = self.vm.iterate

        def run(f):
            if cells:
                kc = [None]
                vc = [None]
                f[kidx] = kc
                f[vidx] = vc
                for k, v in iterate(seq_ev(f)):
                    kc[0] = k
                    vc[0] = v
                    r = body_ex(f)
                    if r is not None:
                        if r is BRK:
                            break
                        if r is RET:
                            return r
            else:
                for k, v in iterate(seq_ev(f)):
                    f[kidx] = k
                    f[vidx] = v
                    r = body_ex(f)
                    if r is not None:
                        if r is BRK:
                            break
                        if r is RET:
                            return r
        return run

    def s_switch(self, node):
        subject = self.expr(node[1])
        self.fs.scopes.append({})
        cases = []
        for label, stmts in node[2]:
            cases.append((self.expr(label) if label is not None else None, self._block_noscope(stmts)))
        self.fs.scopes.pop()
        default_at = next((i for i, (lab, _b) in enumerate(cases) if lab is None), None)

        def run(f):
            v = subject(f)
            start = default_at
            for i, (lab, _b) in enumerate(cases):
                if lab is not None and eq(v, lab(f)):
                    start = i
                    break
            if start is None:
                return None
            for _lab, body in cases[start:]:
                r = body(f)
                if r is not None:
                    if r is BRK:
                        return None
                    return r
            return None
        return run

    def s_break(self, node):
        return lambda f: BRK

    def s_continue(self, node):
        return lambda f: CNT

    def s_return(self, node):
        if node[1] is None:
            def run(f):
                f[2] = None
                return RET
            return run
        value = node[1]
        if value[0] == "call":
            ev = self.e_call(value, tail=self.fs.parent is not None and self.fs.traps == 0)
        else:
            ev = self.expr(value)

        def run(f):
            f[2] = ev(f)
            return RET
        return run

    def s_yield(self, node):
        def run(f):
            raise SqError("generators (yield) are not supported by this interpreter")
        return run

    def s_throw(self, node):
        ev = self.expr(node[1])

        def run(f):
            raise SqError(ev(f))
        return run

    def s_try(self, node):
        _, body, cname, cbody = node
        fs = self.fs
        cells = fs.cells
        fs.scopes.append({})
        fs.traps += 1
        body_ex = self.stmt(body) or (lambda f: None)
        fs.traps -= 1
        fs.scopes.pop()
        fs.scopes.append({})
        cidx = fs.declare(cname)
        catch_ex = self.stmt(cbody) or (lambda f: None)
        fs.scopes.pop()
        stack = self.vm.stack
        vm = self.vm

        def run(f):
            depth = len(stack)
            try:
                return body_ex(f)
            except SqError as e:
                vm.note_trace(depth - 1)
                del stack[depth:]
                f[cidx] = [e.value] if cells else e.value
            except RecursionError:
                del stack[depth:]
                f[cidx] = ["stack overflow"] if cells else "stack overflow"
            return catch_ex(f)
        return run

    def s_const(self, node):
        self.vm.consts[node[1]] = node[2]
        return None

    def s_enum(self, node):
        t = SqTable(len(node[2]))
        for name, value in node[2]:
            t.newslot(name, value)
        self.vm.consts[node[1]] = t
        return None

    # ------------------------------------------------------------------ expressions
    def cond(self, node):
        """Expression used as a condition: returns a Python bool."""
        kind = node[0]
        if kind == "bin" and node[1] in ("==", "!=", "<", ">", "<=", ">="):
            return self.e_bin(node)         # already returns bool
        if kind in ("in", "instanceof", "true", "false"):
            return self.expr(node)
        if kind == "un" and node[1] == "!":
            inner = self.cond(node[2])
            return lambda f: not inner(f)
        if kind == "and":
            a, b = self.cond(node[1]), self.cond(node[2])
            return lambda f: a(f) and b(f)
        if kind == "or":
            a, b = self.cond(node[1]), self.cond(node[2])
            return lambda f: a(f) or b(f)
        ev = self.expr(node)

        def test(f):
            v = ev(f)
            if v is None or v is False:
                return False
            if v is True:
                return True
            t = type(v)
            if t is int or t is float:
                return v != 0
            return True
        return test

    def expr(self, node):
        return getattr(self, "e_" + node[0])(node)

    def e_int(self, node):
        v = node[1]
        return lambda f: v

    def e_float(self, node):
        v = R.f32(node[1])
        return lambda f: v

    e_str = e_int

    def e_null(self, node):
        return lambda f: None

    def e_true(self, node):
        return lambda f: True

    def e_false(self, node):
        return lambda f: False

    def e_this(self, node):
        return lambda f: f[0]

    def e_rootobj(self, node):
        root = self.vm.root
        return lambda f: root

    def e_base(self, node):
        return lambda f: f[1].base

    def e_root(self, node):
        name = node[1]
        rd = self.vm.root.d

        def ev(f):
            v = rd.get(name, MISSING)
            if v is MISSING:
                raise SqError("the index '%s' does not exist" % name)
            return v
        return ev

    def e_id(self, node):
        name = node[1]
        if name == "vargv":
            r = self.fs.resolve(name)
            if r is None:
                return lambda f: f[3]
        r = self.fs.resolve(name)
        if r is not None:
            kind, idx = r
            if kind == "slot":
                if self.fs.cells:
                    return lambda f: f[idx][0]
                return lambda f: f[idx]
            return lambda f: f[1].fv[idx][0]
        consts = self.vm.consts
        if name in consts:
            v = consts[name]
            return lambda f: v
        lookup = self.vm.lookup
        return lambda f: lookup(f[0], name)

    def e_table(self, node):
        entries = [(self.expr(k) if k[0] != "str" else None, k[1] if k[0] == "str" else None, self.expr(v))
                   for k, v in node[1]]
        n = len(entries)

        def ev(f):
            t = SqTable(n)
            ns = t.newslot
            for kev, kname, vev in entries:
                ns(kname if kev is None else kev(f), vev(f))
            return t
        return ev

    def e_array(self, node):
        items = [self.expr(e) for e in node[1]]
        return lambda f: [e(f) for e in items]

    def e_func(self, node):
        return self.func_expr(node)

    def e_class(self, node):
        _, base, members, _line = node
        base_ev = self.expr(base) if base is not None else None
        mems = [(static, self.expr(k), self.expr(v)) for static, k, v in members]

        def ev(f):
            b = base_ev(f) if base_ev is not None else None
            if b is not None and type(b) is not SqClass:
                raise SqError("trying to inherit from a %s" % R.typeof(b))
            cls = SqClass(b)
            for _static, k, v in mems:
                cls.define(k(f), v(f))
            if b is not None:
                mm = b.meta.get("_inherited")
                if mm is not None:
                    call(mm, b, (cls,))
            return cls
        return ev

    def e_get(self, node):
        obj = self.expr(node[1])
        key = node[2]
        if key[0] == "str":
            name = key[1]
            if node[1][0] == "this":
                lookup = self.vm.lookup
                return lambda f: lookup(f[0], name)
            return lambda f: get(obj(f), name)
        kev = self.expr(key)
        return lambda f: get(obj(f), kev(f))

    def e_call(self, node, tail=False):
        _, callee, args, _line = node
        arg_evs = [self.expr(a) for a in args]
        nargs = len(arg_evs)
        stack = self.vm.stack
        kind = callee[0]

        def invoke(fn, this, f):
            if nargs == 0:
                a = ()
            elif nargs == 1:
                a = (arg_evs[0](f),)
            elif nargs == 2:
                a = (arg_evs[0](f), arg_evs[1](f))
            else:
                a = [e(f) for e in arg_evs]
            if type(fn) is SqClosure:
                if tail:
                    stack.pop()      # tail call: the caller's frame is replaced (getstackinfos sees it)
                return fn.invoke(this, a)
            return call(fn, this, a)

        if kind == "get":
            obj = self.expr(callee[1])
            key = callee[2]
            if key[0] == "str":
                name = key[1]
                if callee[1][0] == "base":
                    # base.method(...): the base class's method, run on the current `this`
                    return lambda f: invoke(get(f[1].base, name), f[0], f)
                if callee[1][0] == "this":
                    lookup = self.vm.lookup

                    def ev(f):
                        o = f[0]
                        return invoke(lookup(o, name), o, f)
                    return ev

                def ev(f):
                    o = obj(f)
                    return invoke(get(o, name), o, f)
            else:
                kev = self.expr(key)

                def ev(f):
                    o = obj(f)
                    return invoke(get(o, kev(f)), o, f)
            return ev
        if kind == "root":
            fn_ev = self.e_root(callee)
            root = self.vm.root
            return lambda f: invoke(fn_ev(f), root, f)
        fn_ev = self.expr(callee)
        return lambda f: invoke(fn_ev(f), f[0], f)

    def e_un(self, node):
        op = node[1]
        ev = self.expr(node[2])
        if op == "-":
            neg = R.neg
            return lambda f: neg(ev(f))
        if op == "!":
            return lambda f: not truthy(ev(f))
        if op == "~":
            def bnot(f):
                v = ev(f)
                if type(v) is not int:
                    raise SqError("attempt to perform a bitwise op on a %s" % R.typeof(v))
                return R.i32(~v)
            return bnot
        if op == "typeof":
            typeof = R.typeof
            return lambda f: typeof(ev(f))
        if op == "clone":
            clone = R.clone
            return lambda f: clone(ev(f))
        if op == "resume":
            def resume(f):
                raise SqError("generators (resume) are not supported by this interpreter")
            return resume
        raise SqError("unknown unary " + op)

    def e_bin(self, node):
        op = node[1]
        a, b = self.expr(node[2]), self.expr(node[3])
        if op == "+":
            def plus(f):
                x = a(f)
                y = b(f)
                if type(x) is int and type(y) is int:
                    r = x + y
                    if -2147483648 <= r <= 2147483647:
                        return r
                return add(x, y)
            return plus
        if op in ("-", "*", "/", "%"):
            return lambda f: arith(op, a(f), b(f))
        if op == "==":
            return lambda f: eq(a(f), b(f))
        if op == "!=":
            return lambda f: not eq(a(f), b(f))
        if op == "<":
            def lt(f):
                x = a(f)
                y = b(f)
                tx, ty = type(x), type(y)
                if (tx is int or tx is float) and (ty is int or ty is float):
                    return x < y
                return cmp(x, y) < 0
            return lt
        if op == ">":
            def gt(f):
                x = a(f)
                y = b(f)
                tx, ty = type(x), type(y)
                if (tx is int or tx is float) and (ty is int or ty is float):
                    return x > y
                return cmp(x, y) > 0
            return gt
        if op == "<=":
            def le(f):
                x = a(f)
                y = b(f)
                tx, ty = type(x), type(y)
                if (tx is int or tx is float) and (ty is int or ty is float):
                    return x <= y
                return cmp(x, y) <= 0
            return le
        if op == ">=":
            def ge(f):
                x = a(f)
                y = b(f)
                tx, ty = type(x), type(y)
                if (tx is int or tx is float) and (ty is int or ty is float):
                    return x >= y
                return cmp(x, y) >= 0
            return ge
        if op == "<=>":
            return lambda f: cmp(a(f), b(f))
        bitop = R.bitop
        return lambda f: bitop(op, a(f), b(f))

    def e_and(self, node):
        a, b = self.expr(node[1]), self.expr(node[2])

        def ev(f):
            v = a(f)
            if not truthy(v):
                return v
            return b(f)
        return ev

    def e_or(self, node):
        a, b = self.expr(node[1]), self.expr(node[2])

        def ev(f):
            v = a(f)
            if truthy(v):
                return v
            return b(f)
        return ev

    def e_tern(self, node):
        c = self.cond(node[1])
        a, b = self.expr(node[2]), self.expr(node[3])
        return lambda f: a(f) if c(f) else b(f)

    def e_in(self, node):
        a, b = self.expr(node[1]), self.expr(node[2])
        has = R.has
        return lambda f: has(b(f), a(f))

    def e_instanceof(self, node):
        a, b = self.expr(node[1]), self.expr(node[2])

        def ev(f):
            inst, cls = a(f), b(f)
            if type(cls) is not SqClass:
                raise SqError("cannot apply instanceof between a %s and a %s" % (R.typeof(inst), R.typeof(cls)))
            if type(inst) is not R.SqInstance:
                return False
            c = inst.cls
            while c is not None:
                if c is cls:
                    return True
                c = c.base
            return False
        return ev

    def e_comma(self, node):
        items = [self.expr(e) for e in node[1]]

        def ev(f):
            v = None
            for e in items:
                v = e(f)
            return v
        return ev

    # --- stores ---
    def _store(self, target):
        """-> setter(f, value) for an assignable expression."""
        kind = target[0]
        if kind == "id":
            name = target[1]
            r = self.fs.resolve(name)
            if r is not None:
                k, idx = r
                if k == "slot":
                    if self.fs.cells:
                        def st(f, v):
                            f[idx][0] = v
                    else:
                        def st(f, v):
                            f[idx] = v
                else:
                    def st(f, v):
                        f[1].fv[idx][0] = v
                return st
            assign = self.vm.assign_nonlocal
            return lambda f, v: assign(f[0], name, v)
        if kind == "root":
            name = target[1]
            root = self.vm.root
            return lambda f, v: set_(root, name, v)
        obj = self.expr(target[1])
        key = target[2]
        if key[0] == "str":
            name = key[1]
            return lambda f, v: set_(obj(f), name, v)
        kev = self.expr(key)
        return lambda f, v: set_(obj(f), kev(f), v)

    def e_assign(self, node):
        target = node[1]
        value = self.expr(node[2])
        kind = target[0]
        if kind == "get":
            # Squirrel evaluates the container and key before the value.
            obj = self.expr(target[1])
            key = target[2]
            if key[0] == "str":
                name = key[1]
                if target[1][0] == "this":
                    assign = self.vm.assign_nonlocal

                    def ev(f):
                        v = value(f)
                        assign(f[0], name, v)
                        return v
                    return ev

                def ev(f):
                    o = obj(f)
                    v = value(f)
                    set_(o, name, v)
                    return v
            else:
                kev = self.expr(key)

                def ev(f):
                    o = obj(f)
                    k = kev(f)
                    v = value(f)
                    set_(o, k, v)
                    return v
            return ev
        st = self._store(target)

        def ev(f):
            v = value(f)
            st(f, v)
            return v
        return ev

    def e_newslot(self, node):
        target = node[1]
        value = self.expr(node[2])
        obj = self.expr(target[1])
        key = target[2]
        if key[0] == "str":
            name = key[1]

            def ev(f):
                o = obj(f)
                v = value(f)
                newslot(o, name, v)
                return v
        else:
            kev = self.expr(key)

            def ev(f):
                o = obj(f)
                k = kev(f)
                v = value(f)
                newslot(o, k, v)
                return v
        return ev

    def e_opassign(self, node):
        _, op, target, value = node
        vev = self.expr(value)

        def combine(cur, v):
            if op == "+":
                return add(cur, v)
            return arith(op, cur, v)

        if target[0] == "get":
            obj = self.expr(target[1])
            key = target[2]
            kev = self.expr(key) if key[0] != "str" else None
            name = key[1] if key[0] == "str" else None

            def ev(f):
                o = obj(f)
                k = name if kev is None else kev(f)
                r = combine(get(o, k), vev(f))
                set_(o, k, r)
                return r
            return ev
        cur = self.expr(target)
        st = self._store(target)

        def ev(f):
            r = combine(cur(f), vev(f))
            st(f, r)
            return r
        return ev

    def e_incdec(self, node):
        _, delta, prefix, target = node

        def bump(v):
            t = type(v)
            if t is int:
                return R.i32(v + delta)
            if t is float:
                return R.f32(v + delta)
            raise SqError("arith op %s on between '%s' and 'integer'" % ("+" if delta > 0 else "-", R.typeof(v)))

        if target[0] == "get":
            obj = self.expr(target[1])
            key = target[2]
            kev = self.expr(key) if key[0] != "str" else None
            name = key[1] if key[0] == "str" else None

            def ev(f):
                o = obj(f)
                k = name if kev is None else kev(f)
                old = get(o, k)
                new = bump(old)
                set_(o, k, new)
                return new if prefix else old
            return ev
        cur = self.expr(target)
        st = self._store(target)

        def ev(f):
            old = cur(f)
            new = bump(old)
            st(f, new)
            return new if prefix else old
        return ev

    def e_delete(self, node):
        target = node[1]
        obj = self.expr(target[1])
        key = target[2]
        kev = self.expr(key) if key[0] != "str" else None
        name = key[1] if key[0] == "str" else None
        delete = R.delete
        return lambda f: delete(obj(f), name if kev is None else kev(f))

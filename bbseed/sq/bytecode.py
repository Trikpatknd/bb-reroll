"""Runs Squirrel 3.0.4 bytecode (functions read by `cnut`) on the lab's runtime.

Each function is turned, on its first call, into a list of small Python closures — one per
instruction, each returning the index of the next instruction (-1 = return). The
semantics follow sqvm.cpp's `SQVM::Execute`; the operations themselves (table lookups
with delegates and metamethods, arithmetic, comparison, calls ...) are the same runtime
functions the source-text compiler uses, so compiled and source scripts mix freely.

A frame is a Python list: the function's registers (`stacksize` of them; register 0 is
`this`), then four extra slots: the running closure, the try/catch traps, the captured
locals still "open", and the return value.

Not supported, because nothing on the paths the lab runs uses them: generators (the
game's tactical AI uses them). Calling a generator function gives a generator object, as
in Squirrel; resuming it is what raises.
"""
import struct

from . import cnut
from . import runtime as R
from .runtime import (MISSING, FuncProto, SqClass, SqClosure, SqError, SqInstance, SqNative, SqTable, SqWeakRef, add,
                      arith, bitop, call, clone, cmp, delete, eq, get, has, neg, newslot, nk, set_, truthy, typeof)

_BITOPS = {0: "&", 2: "|", 3: "^", 4: "<<", 5: ">>", 6: ">>>"}
_NO_TARGET = 0xFF

# Debugging aid (tools/bc_coverage.py): set to a dict before any script is loaded and every
# executed instruction is counted in it under (opcode, name of the handler variant); the
# variants built but never run are in SEEN - COVERAGE.
COVERAGE = None
SEEN = set()


class Generator(SqNative):
    """What calling a generator function returns. It cannot be resumed here."""

    sq_type = "generator"

    def __init__(self, closure, this, args):
        self.closure = closure
        self.this = this
        self.args = args
        self.addr = R.new_addr()

    def sq_get(self, key):
        if key == "getstatus":
            return R.NativeFn(lambda this: "suspended", "getstatus")
        raise SqError("the index '%s' does not exist" % (key,))


class Outer:
    """A local variable captured by a closure. While its function's scope is alive it IS the
    register (`frame[idx]`); once the scope closes it keeps its own copy."""

    __slots__ = ("frame", "idx", "value")

    def __init__(self, frame, idx):
        self.frame = frame
        self.idx = idx
        self.value = None


def function(vm, p):
    """runtime.FuncProto for a compiled function `p` (cnut.Proto); compiled on first call."""
    fp = FuncProto()
    varparams = bool(p.varparams)
    fp.name = p.name
    fp.src = p.sourcename
    fp.line = p.line()
    fp.varargs = varparams
    fp.nparams = len(p.parameters) - 1 - (1 if varparams else 0)
    fp.param_names = list(p.parameters[1:])          # for a vararg function this ends with "vargv", as in Squirrel
    fp.nslots = p.stacksize
    fp.cells = False
    fp.body = None
    fp.defaults = ()
    fp.freevars = ()

    def first_call(closure, this, args):
        run = _build(vm, p, fp)
        fp.bc = run
        return run(closure, this, args)

    fp.bc = first_call
    return fp


def _counted(handler, key):
    SEEN.add(key)

    def run(f):
        COVERAGE[key] = COVERAGE.get(key, 0) + 1
        return handler(f)
    return run


def _unsupported(what):
    def op(_frame):
        raise SqError("%s is not supported by this interpreter" % what)
    return op


def _build(vm, p, fp):
    ins = cnut.instructions(p.code)
    n = len(ins)
    S = p.stacksize
    CL, TR, OUT, RET = S, S + 1, S + 2, S + 3
    frame_size = S + 4
    lits = p.literals
    children = [function(vm, c) for c in p.functions]
    child_data = p.functions
    stack = vm.stack
    root = vm.root
    lookup = vm.lookup
    assign_nonlocal = vm.assign_nonlocal
    code = [None] * n

    if p.bgenerator:
        return Generator

    rootd = root.d

    def get_this(obj, key):
        """`this[key]`: like any read, but a miss falls back to the root table (SQVM::Get, selfidx 0)."""
        if type(key) is str:
            return lookup(obj, key)
        try:
            return get(obj, key)
        except SqError:
            v = rootd.get(nk(key), MISSING)
            if v is MISSING:
                raise
            return v

    def set_this(obj, key, value):
        if type(key) is str:
            assign_nonlocal(obj, key, value)
            return
        try:
            set_(obj, key, value)
        except SqError:
            if not root.set_existing(key, value):
                raise

    def getter(selfreg, literal_key=MISSING):
        """Read `obj[key]`; register 0 is `this`, which also falls back to the root table."""
        if selfreg != 0:
            return get
        return lookup if type(literal_key) is str else get_this

    def setter(selfreg):
        return set_this if selfreg == 0 else set_

    def make(i, op, a0, a1, a2, a3):
        nxt = i + 1
        if op == 0x00:                                   # LINE (never called: aliased to the next instruction)
            return lambda f: nxt
        if op == 0x01:                                   # LOAD
            lit = lits[a1]

            def o_load(f):
                f[a0] = lit
                return nxt
            return o_load
        if op == 0x02:                                   # LOADINT
            def o_loadint(f):
                f[a0] = a1
                return nxt
            return o_loadint
        if op == 0x03:                                   # LOADFLOAT
            val = struct.unpack("<f", struct.pack("<i", a1))[0]

            def o_loadfloat(f):
                f[a0] = val
                return nxt
            return o_loadfloat
        if op == 0x04:                                   # DLOAD
            l1, l2 = lits[a1], lits[a3]

            def o_dload(f):
                f[a0] = l1
                f[a2] = l2
                return nxt
            return o_dload
        if op == 0x05 or op == 0x06:                     # TAILCALL / CALL
            first, last = a2 + 1, a2 + a3
            tail = op == 0x05
            if a0 == _NO_TARGET:
                def o_call_discard(f):
                    fn = f[a1]
                    if tail and type(fn) is SqClosure:
                        stack.pop()                  # the caller's frame is replaced (getstackinfos sees it)
                    call(fn, f[a2], f[first:last])
                    return nxt
                return o_call_discard

            def o_call(f):
                fn = f[a1]
                if tail and type(fn) is SqClosure:
                    stack.pop()
                f[a0] = call(fn, f[a2], f[first:last])
                return nxt
            return o_call
        if op == 0x07 or op == 0x08:                     # PREPCALL / PREPCALLK
            if op == 0x08:
                key = lits[a1]
                rd = getter(a2, key)

                def o_prepcallk(f):
                    obj = f[a2]
                    fn = rd(obj, key)
                    f[a3] = obj
                    f[a0] = fn
                    return nxt
                return o_prepcallk

            rd = getter(a2)

            def o_prepcall(f):
                obj = f[a2]
                fn = rd(obj, f[a1])
                f[a3] = obj
                f[a0] = fn
                return nxt
            return o_prepcall
        if op == 0x09:                                   # GETK
            key = lits[a1]
            rd = getter(a2, key)

            def o_getk(f):
                f[a0] = rd(f[a2], key)
                return nxt
            return o_getk
        if op == 0x0A:                                   # MOVE
            def o_move(f):
                f[a0] = f[a1]
                return nxt
            return o_move
        if op == 0x0B:                                   # NEWSLOT
            if a0 == _NO_TARGET:
                def o_newslot(f):
                    newslot(f[a1], f[a2], f[a3])
                    return nxt
                return o_newslot

            def o_newslot_t(f):
                v = f[a3]
                newslot(f[a1], f[a2], v)
                f[a0] = v
                return nxt
            return o_newslot_t
        if op == 0x0C:                                   # DELETE
            def o_delete(f):
                f[a0] = delete(f[a1], f[a2])
                return nxt
            return o_delete
        if op == 0x0D:                                   # SET
            wr = setter(a1)

            def o_set(f):
                v = f[a3]
                wr(f[a1], f[a2], v)
                if a0 != _NO_TARGET:
                    f[a0] = v
                return nxt
            return o_set
        if op == 0x0E:                                   # GET
            rd = getter(a1)

            def o_get(f):
                f[a0] = rd(f[a1], f[a2])
                return nxt
            return o_get
        if op == 0x0F or op == 0x10:                     # EQ / NE
            want = op == 0x0F
            if a3 != 0:
                lit = lits[a1]

                def o_eq_lit(f):
                    f[a0] = eq(f[a2], lit) is want
                    return nxt
                return o_eq_lit

            def o_eq(f):
                f[a0] = eq(f[a2], f[a1]) is want
                return nxt
            return o_eq
        if op == 0x11:                                   # ADD
            def o_add(f):
                x, y = f[a2], f[a1]
                if type(x) is int and type(y) is int:
                    r = x + y
                    f[a0] = r if -2147483648 <= r <= 2147483647 else R.i32(r)
                else:
                    f[a0] = add(x, y)
                return nxt
            return o_add
        if 0x12 <= op <= 0x15:                           # SUB MUL DIV MOD
            sym = "-*/%"[op - 0x12]

            def o_arith(f):
                f[a0] = arith(sym, f[a2], f[a1])
                return nxt
            return o_arith
        if op == 0x16:                                   # BITW
            sym = _BITOPS[a3]

            def o_bitw(f):
                f[a0] = bitop(sym, f[a2], f[a1])
                return nxt
            return o_bitw
        if op == 0x17:                                   # RETURN
            if a0 == _NO_TARGET:
                return lambda f: -1

            def o_return(f):
                f[RET] = f[a1]
                return -1
            return o_return
        if op == 0x18:                                   # LOADNULLS
            if a1 == 1:
                def o_loadnull(f):
                    f[a0] = None
                    return nxt
                return o_loadnull
            end = a0 + a1

            def o_loadnulls(f):
                for k in range(a0, end):
                    f[k] = None
                return nxt
            return o_loadnulls
        if op == 0x19:                                   # LOADROOT
            def o_loadroot(f):
                f[a0] = root
                return nxt
            return o_loadroot
        if op == 0x1A:                                   # LOADBOOL
            val = a1 != 0

            def o_loadbool(f):
                f[a0] = val
                return nxt
            return o_loadbool
        if op == 0x1B:                                   # DMOVE
            def o_dmove(f):
                f[a0] = f[a1]
                f[a2] = f[a3]
                return nxt
            return o_dmove
        if op == 0x1C:                                   # JMP
            target = nxt + a1
            return lambda f: target
        if op == 0x1D:                                   # JCMP: jump when the comparison is false
            target = nxt + a1
            kind = a3

            def o_jcmp(f):
                x, y = f[a2], f[a0]
                tx, ty = type(x), type(y)
                if (tx is int or tx is float) and (ty is int or ty is float):
                    r = -1 if x < y else (1 if x > y else 0)
                else:
                    r = cmp(x, y)
                if kind == 0:
                    ok = r > 0
                elif kind == 2:
                    ok = r >= 0
                elif kind == 3:
                    ok = r < 0
                elif kind == 4:
                    ok = r <= 0
                else:
                    ok = r != 0
                return nxt if ok else target
            return o_jcmp
        if op == 0x1E:                                   # JZ
            target = nxt + a1

            def o_jz(f):
                v = f[a0]
                if v is True:
                    return nxt
                if v is None or v is False:
                    return target
                t = type(v)
                if (t is int or t is float) and v == 0:
                    return target
                return nxt
            return o_jz
        if op == 0x1F:                                   # SETOUTER
            def o_setouter(f):
                o = f[CL].fv[a1]
                v = f[a2]
                if o.frame is not None:
                    o.frame[o.idx] = v
                else:
                    o.value = v
                if a0 != _NO_TARGET:
                    f[a0] = v
                return nxt
            return o_setouter
        if op == 0x20:                                   # GETOUTER
            def o_getouter(f):
                o = f[CL].fv[a1]
                fr = o.frame
                f[a0] = fr[o.idx] if fr is not None else o.value
                return nxt
            return o_getouter
        if op == 0x21:                                   # NEWOBJ
            if a3 == 0:
                def o_newtable(f):
                    f[a0] = SqTable(a1)
                    return nxt
                return o_newtable
            if a3 == 1:
                def o_newarray(f):
                    f[a0] = []
                    return nxt
                return o_newarray

            def o_newclass(f):
                base = None
                if a1 != -1:
                    base = f[a1]
                    if type(base) is not SqClass:
                        raise SqError("trying to inherit from a %s" % typeof(base))
                attrs = f[a2] if a2 != 0xFF else None
                cls = SqClass(base)
                mm = cls.meta.get("_inherited")
                if mm is not None:
                    call(mm, cls, (attrs,))
                f[a0] = cls
                return nxt
            return o_newclass
        if op == 0x22:                                   # APPENDARRAY
            if a2 == 0:
                def o_append(f):
                    f[a0].append(f[a1])
                    return nxt
                return o_append
            if a2 == 1:
                val = lits[a1]
            elif a2 == 2:
                val = a1
            elif a2 == 3:
                val = struct.unpack("<f", struct.pack("<i", a1))[0]
            else:
                val = a1 != 0

            def o_append_const(f):
                f[a0].append(val)
                return nxt
            return o_append_const
        if op == 0x23:                                   # COMPARITH  obj[key] op= value
            selfreg = (a1 & 0xFFFFFFFF) >> 16
            valreg = a1 & 0xFFFF
            rd, wr = getter(selfreg), setter(selfreg)
            sym = chr(a3)

            def o_comparith(f):
                obj, key = f[selfreg], f[a2]
                cur = rd(obj, key)
                res = add(cur, f[valreg]) if sym == "+" else arith(sym, cur, f[valreg])
                wr(obj, key, res)
                f[a0] = res
                return nxt
            return o_comparith
        if op == 0x24 or op == 0x26:                     # INC / PINC  (++obj[key], obj[key]++)
            step = a3 - 256 if a3 > 127 else a3
            rd, wr = getter(a1), setter(a1)
            postfix = op == 0x26

            def o_inc(f):
                obj, key = f[a1], f[a2]
                cur = rd(obj, key)
                res = add(cur, step)
                wr(obj, key, res)
                f[a0] = cur if postfix else res
                return nxt
            return o_inc
        if op == 0x25 or op == 0x27:                     # INCL / PINCL (a local)
            step = a3 - 256 if a3 > 127 else a3
            postfix = op == 0x27

            def o_incl(f):
                cur = f[a1]
                if type(cur) is int:
                    r = cur + step
                    if not -2147483648 <= r <= 2147483647:
                        r = R.i32(r)
                else:
                    r = add(cur, step)
                if postfix:
                    f[a0] = cur                      # the old value first: the two registers can be the same one
                f[a1] = r
                return nxt
            return o_incl
        if op == 0x28:                                   # CMP
            kind = a3

            def o_cmp(f):
                r = cmp(f[a2], f[a1])
                if kind == 0:
                    f[a0] = r > 0
                elif kind == 2:
                    f[a0] = r >= 0
                elif kind == 3:
                    f[a0] = r < 0
                elif kind == 4:
                    f[a0] = r <= 0
                else:
                    f[a0] = r
                return nxt
            return o_cmp
        if op == 0x29:                                   # EXISTS  (key in obj)
            def o_exists(f):
                f[a0] = has(f[a1], f[a2])
                return nxt
            return o_exists
        if op == 0x2A:                                   # INSTANCEOF
            def o_instanceof(f):
                cls, inst = f[a1], f[a2]
                if type(cls) is not SqClass:
                    raise SqError("cannot apply instanceof between a %s and a %s" % (typeof(cls), typeof(inst)))
                res = False
                if type(inst) is SqInstance:
                    c = inst.cls
                    while c is not None:
                        if c is cls:
                            res = True
                            break
                        c = c.base
                f[a0] = res
                return nxt
            return o_instanceof
        if op == 0x2B or op == 0x2C:                     # AND / OR
            target = nxt + a1
            is_and = op == 0x2B

            def o_andor(f):
                v = f[a2]
                if truthy(v) is not is_and:
                    f[a0] = v
                    return target
                return nxt
            return o_andor
        if op == 0x2D:                                   # NEG
            def o_neg(f):
                f[a0] = neg(f[a1])
                return nxt
            return o_neg
        if op == 0x2E:                                   # NOT
            def o_not(f):
                f[a0] = not truthy(f[a1])
                return nxt
            return o_not
        if op == 0x2F:                                   # BWNOT
            def o_bwnot(f):
                v = f[a1]
                if type(v) is not int:
                    raise SqError("attempt to perform a bitwise op on a %s" % typeof(v))
                f[a0] = R.i32(~v)
                return nxt
            return o_bwnot
        if op == 0x30:                                   # CLOSURE
            child = children[a1]
            outers = child_data[a1].outervalues
            defaults = child_data[a1].defaultparams

            def o_closure(f):
                fv = None
                if outers:
                    fv = []
                    for kind, src, _name in outers:
                        if kind == 0:                    # a local of this function
                            opened = f[OUT]
                            if opened is None:
                                opened = f[OUT] = {}
                            o = opened.get(src)
                            if o is None:
                                o = opened[src] = Outer(f, src)
                            fv.append(o)
                        else:                            # an outer of this function, passed on
                            fv.append(f[CL].fv[src])
                f[a0] = SqClosure(child, fv, [f[pos] for pos in defaults] if defaults else [], vm)
                return nxt
            return o_closure
        if op == 0x31:
            return _unsupported("yield")
        if op == 0x32:
            return _unsupported("resume")
        if op == 0x33:                                   # FOREACH
            exit_target = nxt + a1
            body_target = nxt + 1
            kreg, vreg, ireg = a2, a2 + 1, a2 + 2

            def o_foreach(f):
                o = f[a0]
                t = type(o)
                idx = f[ireg]
                if t is SqTable:
                    step = o.next(idx or 0)
                    if step is None:
                        return exit_target
                    f[ireg], f[kreg], v = step
                    f[vreg] = v.obj if type(v) is SqWeakRef else v
                    return body_target
                if t is list:
                    idx = idx or 0
                    if idx >= len(o):
                        return exit_target
                    v = o[idx]
                    f[kreg] = idx
                    f[vreg] = v.obj if type(v) is SqWeakRef else v
                    f[ireg] = idx + 1
                    return body_target
                if t is str:
                    idx = idx or 0
                    if idx >= len(o):
                        return exit_target
                    f[kreg] = idx
                    f[vreg] = ord(o[idx])
                    f[ireg] = idx + 1
                    return body_target
                if t is SqClass:
                    step = o.members.next(idx or 0)
                    if step is None:
                        return exit_target
                    f[ireg], f[kreg], f[vreg] = step
                    return body_target
                if t is SqInstance:
                    mm = o.cls.meta.get("_nexti")
                    if mm is None:
                        raise SqError("_nexti failed")
                    itr = call(mm, o, (idx,))
                    f[ireg] = f[kreg] = itr
                    if itr is None:
                        return exit_target
                    f[vreg] = get(o, itr)
                    return body_target
                if isinstance(o, SqNative) and hasattr(o, "sq_iter"):
                    if idx is None:
                        idx = f[ireg] = iter(list(o.sq_iter()))
                    for k, v in idx:
                        f[kreg], f[vreg] = k, v
                        return body_target
                    return exit_target
                raise SqError("cannot iterate %s" % typeof(o))
            return o_foreach
        if op == 0x34:                                   # POSTFOREACH (only does something for generators)
            return lambda f: nxt
        if op == 0x35:                                   # CLONE
            def o_clone(f):
                f[a0] = clone(f[a1])
                return nxt
            return o_clone
        if op == 0x36:                                   # TYPEOF
            def o_typeof(f):
                f[a0] = typeof(f[a1])
                return nxt
            return o_typeof
        if op == 0x37:                                   # PUSHTRAP
            handler = nxt + a1

            def o_pushtrap(f):
                traps = f[TR]
                if traps is None:
                    traps = f[TR] = []
                traps.append((handler, a0))
                return nxt
            return o_pushtrap
        if op == 0x38:                                   # POPTRAP
            def o_poptrap(f):
                del f[TR][-a0:]
                return nxt
            return o_poptrap
        if op == 0x39:                                   # THROW
            def o_throw(f):
                raise SqError(f[a0])
            return o_throw
        if op == 0x3A:                                   # NEWSLOTA (class member, with attributes / static)
            def o_newslota(f):
                newslot(f[a1], f[a2], f[a3])
                return nxt
            return o_newslota
        if op == 0x3B:                                   # GETBASE
            def o_getbase(f):
                f[a0] = f[CL].base
                return nxt
            return o_getbase
        if op == 0x3C:                                   # CLOSE: locals from register a1 up leave scope
            def o_close(f):
                opened = f[OUT]
                if opened:
                    for slot in [s for s in opened if s >= a1]:
                        o = opened.pop(slot)
                        o.value = f[slot]
                        o.frame = None
                return nxt
            return o_close
        return _unsupported("instruction 0x%02x" % op)

    for i in range(n - 1, -1, -1):
        op, a0, a1, a2, a3 = ins[i]
        if op == 0x00 and i + 1 < n:
            code[i] = code[i + 1]                        # a LINE marker costs nothing at run time
        else:
            code[i] = make(i, op, a0, a1, a2, a3)
            if COVERAGE is not None:
                code[i] = _counted(code[i], (op, code[i].__name__))

    varparams = bool(p.varparams)
    declared = len(p.parameters) - (1 if varparams else 0)      # `this` + fixed parameters
    fixed = declared - 1
    name = p.name

    def run(closure, this, args):
        f = [None] * frame_size
        f[0] = this
        given = len(args)
        if varparams:
            if given < fixed:
                raise SqError("wrong number of parameters")
            if fixed:
                f[1:declared] = args[:fixed]
            f[declared] = list(args[fixed:])
        else:
            if given != fixed:
                missing = fixed - given
                defaults = closure.defaults
                if not 0 < missing <= len(defaults):
                    raise SqError("wrong number of parameters")
                args = list(args) + defaults[len(defaults) - missing:]
            if fixed:
                f[1:declared] = args
        f[CL] = closure
        depth = len(stack)
        stack.append(closure)
        ip = 0
        while True:
            try:
                while ip >= 0:
                    ip = code[ip](f)
                break
            except SqError as e:
                traps = f[TR]
                if not traps:
                    if f[OUT]:
                        close_outers(f)
                    raise
                ip, reg = traps.pop()
                vm.note_trace(depth)
                del stack[depth + 1:]
                f[reg] = e.value
        del stack[depth:]
        if f[OUT]:
            close_outers(f)
        return f[RET]

    def close_outers(f):
        """The function is done: closures that captured its locals keep the values, not the frame."""
        for slot, o in f[OUT].items():
            o.value = f[slot]
            o.frame = None
        f[OUT] = None

    run.__name__ = "run_%s" % (name or "anonymous")
    return run

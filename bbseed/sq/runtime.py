"""Runtime values and operations for the Squirrel interpreter.

Fidelity notes (things Battle Brothers scripts can observe):
  * integers are 32-bit and wrap; floats are 32-bit (SQFloat = float in BB's build)
  * tables iterate in the order of Squirrel's own hash-node layout (ported from
    sqtable.cpp), because `foreach` over a table can drive random draws
  * array.sort() is Squirrel's heapsort (not stable), ported from sqbaselib.cpp
"""
import weakref as _weakref
import struct
from decimal import Decimal as _Decimal, ROUND_HALF_UP as _HALF_UP

_pack_f = struct.Struct("<f").pack
_unpack_f = struct.Struct("<f").unpack


class SqError(Exception):
    """A Squirrel-level exception; `value` is what `catch (e)` receives."""

    def __init__(self, value):
        Exception.__init__(self, value)
        self.value = value


def f32(x):
    try:
        return _unpack_f(_pack_f(x))[0]
    except OverflowError:
        return float("inf") if x > 0 else float("-inf")


def i32(x):
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x & 0x80000000 else x


_addr_counter = [0x10000]


def new_addr():
    """A stand-in for an object's memory address (used only to hash object keys)."""
    _addr_counter[0] += 0x40
    return _addr_counter[0]


_hash_cache = {}


def hashstr(s):
    """Squirrel 3.0.x _hashstr."""
    h = _hash_cache.get(s)
    if h is None:
        b = s.encode("utf-8", "surrogatepass") if not s.isascii() else s.encode("ascii")
        length = len(b)
        h = length
        step = (length >> 5) | 1
        i = 0
        while length >= step:
            c = b[i]
            if c > 127:
                c = (c - 256) & 0xFFFF      # (unsigned short)(signed char)
            h = (h ^ (((h << 5) & 0xFFFFFFFF) + (h >> 2) + c)) & 0xFFFFFFFF
            i += 1
            length -= step
        _hash_cache[s] = h
    return h


_F = "\x00f"
_B = "\x00b"
_L = "\x00l"


def nk(k):
    """Normalise a key for the Python dict: Squirrel treats 1, 1.0 and true as different keys."""
    t = type(k)
    if t is str or t is int:
        return k
    if t is float:
        return (_F, k)
    if t is bool:
        return (_B, k)
    if t is list:
        return (_L, id(k))
    return k


def sq_hash(k):
    t = type(k)
    if t is str:
        return hashstr(k)
    if t is int:
        return k & 0xFFFFFFFF
    if t is float:
        return int(k) & 0xFFFFFFFF
    if t is bool:
        return 1 if k else 0
    addr = getattr(k, "addr", None)
    if addr is None:
        addr = id(k)
    return (addr >> 3) & 0xFFFFFFFF


_EMPTY = object()
MISSING = object()


class SqTable:
    """Squirrel table: values in a Python dict for speed, plus the node array
    (keys + chain links) that decides iteration order exactly like sqtable.cpp."""

    __slots__ = ("d", "keys", "nxt", "size", "firstfree", "used", "delegate", "addr", "__weakref__")

    def __init__(self, initial=0):
        size = 4
        while initial > size:
            size <<= 1
        self.d = {}
        self.keys = [_EMPTY] * size
        self.nxt = [-1] * size
        self.size = size
        self.firstfree = size - 1
        self.used = 0
        self.delegate = None
        self.addr = new_addr()

    # --- reads ---
    def get(self, key, default=None):
        return self.d.get(nk(key), default)

    def __contains__(self, key):
        return nk(key) in self.d

    def __len__(self):
        return len(self.d)

    def items(self):
        d = self.d
        return [(k, d[nk(k)]) for k in self.keys if k is not _EMPTY]

    def key_list(self):
        return [k for k in self.keys if k is not _EMPTY]

    def next(self, idx):
        """Iteration step: returns (next_idx, key, value) or None when done."""
        keys = self.keys
        size = self.size
        while idx < size:
            k = keys[idx]
            if k is not _EMPTY:
                return idx + 1, k, self.d[nk(k)]
            idx += 1
        return None

    # --- writes ---
    def set_existing(self, key, value):
        n = nk(key)
        if n in self.d:
            self.d[n] = value
            return True
        return False

    def newslot(self, key, value):
        n = nk(key)
        d = self.d
        if n in d:
            d[n] = value
            return False
        self._insert(key)
        d[n] = value
        return True

    def _insert(self, key):
        """SQTable::NewSlot for a key that is not in the table yet."""
        keys, nxt = self.keys, self.nxt
        mask = self.size - 1
        mp = sq_hash(key) & mask
        if keys[mp] is not _EMPTY:
            n = self.firstfree
            othern = sq_hash(keys[mp]) & mask
            if mp > n and othern != mp:
                # the colliding node is out of its main position: move it to the free slot
                while nxt[othern] != mp:
                    othern = nxt[othern]
                nxt[othern] = n
                keys[n] = keys[mp]
                nxt[n] = nxt[mp]
                keys[mp] = _EMPTY
                nxt[mp] = -1
            else:
                # the new node goes into the free slot, chained after the main position
                nxt[n] = nxt[mp]
                nxt[mp] = n
                mp = n
        keys[mp] = key
        ff = self.firstfree
        while True:
            if keys[ff] is _EMPTY and nxt[ff] == -1:
                self.firstfree = ff
                self.used += 1
                return
            if ff == 0:
                break
            ff -= 1
        self.firstfree = ff
        # No free node left: rebuild. The new key already sits in the node array,
        # so the rebuild re-inserts it together with the old ones.
        self._rehash(True)

    def _rehash(self, force):
        oldsize = self.size
        if oldsize < 4:
            oldsize = 4
        nelems = self.used
        if nelems >= oldsize - oldsize // 4:
            newsize = oldsize * 2
        elif nelems <= oldsize // 4 and oldsize > 4:
            newsize = oldsize // 2
        elif force:
            newsize = oldsize
        else:
            return
        old = self.keys
        self.keys = [_EMPTY] * newsize
        self.nxt = [-1] * newsize
        self.size = newsize
        self.firstfree = newsize - 1
        self.used = 0
        for k in old:
            if k is not _EMPTY:
                self._insert(k)

    def remove(self, key):
        n = nk(key)
        d = self.d
        if n not in d:
            return MISSING
        value = d.pop(n)
        keys, nxt = self.keys, self.nxt
        idx = sq_hash(key) & (self.size - 1)
        while idx != -1:
            k = keys[idx]
            if k is not _EMPTY and nk(k) == n:
                keys[idx] = _EMPTY      # the chain link (nxt) is kept, as in Squirrel
                break
            idx = nxt[idx]
        self.used -= 1
        self._rehash(False)
        return value

    def clear(self):
        size = self.size
        self.d = {}
        self.keys = [_EMPTY] * size
        self.nxt = [-1] * size
        self.firstfree = size - 1
        self.used = 0
        self._rehash(False)

    def clone(self):
        t = SqTable.__new__(SqTable)
        t.d = dict(self.d)
        t.keys = list(self.keys)
        t.nxt = list(self.nxt)
        t.size = self.size
        t.firstfree = self.firstfree
        t.used = self.used
        t.delegate = self.delegate
        t.addr = new_addr()
        return t


class SqWeakRef:
    """A Squirrel weak reference: it must NOT keep its target alive (mods keep tables of weak
    references to every entity ever made — MSU's entity map — and expect the entities to go
    away). `obj` is the target, or None once it is gone. Python cannot weakly reference a
    list; those few are held strongly."""

    __slots__ = ("_ref", "_strong", "addr")

    def __init__(self, obj):
        try:
            self._ref = _weakref.ref(obj)
            self._strong = None
        except TypeError:
            self._ref = None
            self._strong = obj
        self.addr = new_addr()

    @property
    def obj(self):
        ref = self._ref
        return self._strong if ref is None else ref()


class FuncProto:
    """A function's code. Functions compiled from source text have `body` (see compiler.py);
    functions read from a compiled script have `bc` instead (see bytecode.py)."""

    __slots__ = ("name", "src", "line", "nparams", "varargs", "nslots", "body", "cells",
                 "defaults", "freevars", "param_names", "bc")

    def __init__(self):
        self.bc = None


class SqClosure:
    __slots__ = ("proto", "fv", "env", "defaults", "vm", "addr", "base", "__weakref__")

    def __init__(self, proto, fv, defaults, vm):
        self.proto = proto
        self.fv = fv
        self.env = None
        self.defaults = defaults
        self.vm = vm
        self.addr = new_addr()
        self.base = None        # for class methods: the base class (`base.method()`)

    def invoke(self, this, args):
        p = self.proto
        if self.env is not None:
            this = self.env
        bc = p.bc
        if bc is not None:
            return bc(self, this, args)
        n = len(args)
        npar = p.nparams
        vargv = None
        if n != npar:
            if n > npar:
                if not p.varargs:
                    raise SqError("wrong number of parameters")
                vargv = list(args[npar:])
                args = args[:npar]
            else:
                missing = npar - n
                defaults = self.defaults
                if missing > len(defaults):
                    raise SqError("wrong number of parameters")
                args = list(args) + defaults[len(defaults) - missing:]
                if p.varargs:
                    vargv = []
        elif p.varargs:
            vargv = []
        f = [this, self, None, vargv]
        if p.cells:
            f.extend([a] for a in args)
        else:
            f.extend(args)
        extra = p.nslots - npar
        if extra:
            f.extend([None] * extra)
        stack = self.vm.stack
        depth = len(stack)
        stack.append(self)
        p.body(f)
        del stack[depth:]
        return f[2]

    def __call__(self, *args):
        """Convenience for natives calling back with `this` = root table."""
        return self.invoke(self.vm.root, args)

    def bind(self, env):
        c = SqClosure(self.proto, self.fv, self.defaults, self.vm)
        c.env = env
        c.base = self.base
        return c


class NativeFn:
    """A Python function exposed to scripts: fn(this, *args)."""

    __slots__ = ("fn", "name", "env", "addr")

    def __init__(self, fn, name=None):
        self.fn = fn
        self.name = name or getattr(fn, "__name__", "native")
        self.env = None
        self.addr = new_addr()

    def bind(self, env):
        n = NativeFn(self.fn, self.name)
        n.env = env
        return n


METAMETHODS = frozenset("_add _sub _mul _div _unm _modulo _set _get _typeof _nexti _cmp _call _cloned "
                        "_newslot _delslot _tostring _newmember _inherited".split())


class SqClass:
    """members: the SQTable of fields/methods/statics (its node order is what
    `foreach` over a class sees); meta: metamethods, kept apart as in sqclass.cpp."""

    __slots__ = ("members", "meta", "base", "addr", "name")

    def __init__(self, base=None):
        self.base = base
        self.members = base.members.clone() if base is not None else SqTable()
        self.meta = dict(base.meta) if base is not None else {}
        self.addr = new_addr()
        self.name = None

    def define(self, key, value):
        if self.base is not None and type(value) is SqClosure:
            # SQClass::NewSlot stores a copy of the closure that knows the base class (`base.x()`),
            # also for functions added to the class after its creation
            env = value.env
            value = value.bind(env)
            value.base = self.base
        if type(key) is str and key in METAMETHODS and type(value) in (SqClosure, NativeFn):
            self.meta[key] = value
        else:
            self.members.newslot(key, value)


class SqInstance:
    __slots__ = ("cls", "vals", "addr", "__weakref__")

    def __init__(self, cls):
        self.cls = cls
        vals = {}
        for k, v in cls.members.d.items():
            t = type(v)
            if t is not SqClosure and t is not NativeFn:
                vals[k] = v
        self.vals = vals
        self.addr = new_addr()


class SqNative:
    """Base for engine-side objects implemented in Python. Subclasses override
    what they support; the defaults raise the same errors Squirrel would."""

    sq_type = "instance"

    def sq_get(self, key):
        raise SqError("the index '%s' does not exist" % (key,))

    def sq_set(self, key, value):
        raise SqError("the index '%s' does not exist" % (key,))

    def sq_newslot(self, key, value):
        raise SqError("class instances do not support the new slot operator")

    def sq_has(self, key):
        return self.sq_find(key) is not MISSING

    def sq_find(self, key):
        """Like sq_get but returns MISSING instead of raising (name lookup hot path)."""
        try:
            return self.sq_get(key)
        except SqError:
            return MISSING

    def sq_try_set(self, key, value):
        try:
            self.sq_set(key, value)
            return True
        except SqError:
            return False


def typeof(v):
    t = type(v)
    if v is None:
        return "null"
    if t is bool:
        return "bool"
    if t is int:
        return "integer"
    if t is float:
        return "float"
    if t is str:
        return "string"
    if t is SqTable:
        d = v.delegate
        if d is not None:
            mm = d.d.get("_typeof")
            if mm is not None:
                return call(mm, v, ())
        return "table"
    if t is list:
        return "array"
    if t is SqClosure or t is NativeFn:
        return "function"
    if t is SqInstance:
        mm = v.cls.meta.get("_typeof")
        if mm is not None:
            return call(mm, v, ())
        return "instance"
    if t is SqClass:
        return "class"
    if t is SqWeakRef:
        return "weakref"
    return getattr(v, "sq_type", "userdata")


def tostring(v):
    t = type(v)
    if t is str:
        return v
    if t is int:
        return str(v)
    if v is None:
        return "(null : 0x00000000)"
    if t is bool:
        return "true" if v else "false"
    if t is float:
        if v != v:
            return "-nan(ind)"
        if v in (float("inf"), float("-inf")):
            return "inf" if v > 0 else "-inf"
        return fmt_g(v)
    if t is SqTable:
        d = v.delegate
        if d is not None:
            mm = d.d.get("_tostring")
            if mm is not None:
                return call(mm, v, ())
    elif t is SqInstance:
        mm = v.cls.meta.get("_tostring")
        if mm is not None:
            return call(mm, v, ())
    elif isinstance(v, SqNative):
        ts = getattr(v, "sq_tostring", None)
        if ts is not None:
            return ts()
    return "(%s : 0x%08X)" % (typeof(v), getattr(v, "addr", id(v)) & 0xFFFFFFFF)


def fmt_g(v, prec=6):
    """C "%g" with the C runtime's round-half-away-from-zero on exact ties."""
    if v == 0 or v != v or v in (float("inf"), float("-inf")):
        return "%g" % v
    d = _Decimal(v)
    d = d.quantize(_Decimal(1).scaleb(d.adjusted() - (prec - 1)), rounding=_HALF_UP)
    return ("%%.%dg" % prec) % float(d)


def fmt_f(v, prec):
    """The value rounded as C "%.<prec>f" does (half away from zero), ready for Python formatting."""
    if v != v or v in (float("inf"), float("-inf")):
        return v
    return float(_Decimal(v).quantize(_Decimal(1).scaleb(-prec), rounding=_HALF_UP))


def print_obj_val(v):
    """SQVM::PrintObjVal - how values appear inside error messages."""
    t = type(v)
    if t is str:
        return v
    if t is int:
        return str(v)
    if t is float:
        return "%.14g" % v
    return typeof(v)


def truthy(v):
    if v is None or v is False:
        return False
    t = type(v)
    if t is int or t is float:
        return v != 0
    return True


# ----- calls -----
def call(fn, this, args):
    t = type(fn)
    if t is SqClosure:
        return fn.invoke(this, args)
    if t is NativeFn:
        if fn.env is not None:
            this = fn.env
        return fn.fn(this, *args)
    if t is SqClass:
        inst = SqInstance(fn)
        ctor = fn.members.d.get("constructor")
        if ctor is not None:
            call(ctor, inst, args)
        return inst
    if t is SqTable:
        d = fn.delegate
        if d is not None:
            mm = d.d.get("_call")
            if mm is not None:
                return call(mm, fn, (this,) + tuple(args))
    elif t is SqInstance:
        mm = fn.cls.meta.get("_call")
        if mm is not None:
            return call(mm, fn, (this,) + tuple(args))
    elif isinstance(fn, SqNative):
        c = getattr(fn, "sq_call", None)
        if c is not None:
            return c(this, *args)
    raise SqError("attempt to call '%s'" % typeof(fn))


# ----- get / set -----
DELEGATES = {}      # type name -> {method name: NativeFn}; filled by stdlib


def get(o, k):
    t = type(o)
    if t is SqTable:
        v = o.d.get(k if type(k) is str else nk(k), MISSING)
        if v is not MISSING:
            if type(v) is SqWeakRef:
                return v.obj
            return v
        d = o.delegate
        while d is not None:
            v = d.d.get(nk(k), MISSING)
            if v is not MISSING:
                return v
            d = d.delegate
        d = o.delegate
        if d is not None:
            mm = get_raw(d, "_get")
            if mm is not None:
                try:
                    return call(mm, o, (k,))
                except SqError as e:
                    if e.value is not None:     # `throw null` in _get means "no such slot"
                        raise
        m = DELEGATES["table"].get(k) if type(k) is str else None
        if m is not None:
            return m
        raise SqError("the index '%s' does not exist" % tostring(k))
    if t is list:
        tk = type(k)
        if tk is int:
            if 0 <= k < len(o):
                v = o[k]
                if type(v) is SqWeakRef:
                    return v.obj
                return v
            raise SqError("the index '%d' does not exist" % k)
        if tk is float:
            return get(o, int(k))
        m = DELEGATES["array"].get(k)
        if m is not None:
            return m
        raise SqError("the index '%s' does not exist" % tostring(k))
    if t is SqInstance:
        v = o.vals.get(k, MISSING)
        if v is not MISSING:
            if type(v) is SqWeakRef:
                return v.obj
            return v
        v = o.cls.members.d.get(k, MISSING)
        if v is not MISSING:
            return v
        mm = o.cls.meta.get("_get")
        if mm is not None:
            try:
                return call(mm, o, (k,))
            except SqError as e:
                if e.value is not None:     # `throw null` in _get means "no such slot"
                    raise
        m = DELEGATES["instance"].get(k) if type(k) is str else None
        if m is not None:
            return m
        raise SqError("the index '%s' does not exist" % tostring(k))
    if t is str:
        if type(k) is int:
            if 0 <= k < len(o):
                return ord(o[k])
            raise SqError("index %d out of range" % k)
        m = DELEGATES["string"].get(k)
        if m is not None:
            return m
        raise SqError("the index '%s' does not exist" % tostring(k))
    if t is SqClass:
        v = o.members.d.get(nk(k), MISSING)
        if v is not MISSING:
            return v
        m = DELEGATES["class"].get(k) if type(k) is str else None
        if m is not None:
            return m
        raise SqError("the index '%s' does not exist" % tostring(k))
    if isinstance(o, SqNative):
        return o.sq_get(k)
    name = typeof(o)
    m = DELEGATES.get(name, {}).get(k) if type(k) is str else None
    if m is not None:
        return m
    if o is None:
        raise SqError("the index '%s' does not exist" % tostring(k))
    raise SqError("the index '%s' does not exist" % tostring(k))


def get_raw(t, k):
    """Table lookup through the delegate chain, no metamethods, None if absent."""
    while t is not None:
        v = t.d.get(k, MISSING)
        if v is not MISSING:
            return v
        t = t.delegate
    return None


def has(o, k):
    """The `in` operator."""
    t = type(o)
    if t is SqTable:
        return nk(k) in o.d          # raw: own slots only (_OP_EXISTS ignores delegates)
    if t is list:
        return type(k) is int and 0 <= k < len(o)
    if t is SqInstance:
        return k in o.vals or k in o.cls.members.d
    if t is SqClass:
        return nk(k) in o.members.d
    if t is str:
        return type(k) is int and 0 <= k < len(o)
    if isinstance(o, SqNative):
        return o.sq_has(k)
    return False                     # _OP_EXISTS never throws: `x in null` is just false


def set_(o, k, v):
    t = type(o)
    if t is SqTable:
        n = k if type(k) is str else nk(k)
        d = o.d
        if n in d:
            d[n] = v
            return
        dg = o.delegate
        while dg is not None:           # SQVM::FallBackSet: try the delegates' own slots
            if n in dg.d:
                dg.d[n] = v
                return
            dg = dg.delegate
        dg = o.delegate
        if dg is not None:
            mm = get_raw(dg, "_set")
            if mm is not None:
                call(mm, o, (k, v))
                return
        raise SqError("the index '%s' does not exist" % tostring(k))
    if t is list:
        if type(k) is float:
            k = int(k)
        if type(k) is int and 0 <= k < len(o):
            o[k] = v
            return
        raise SqError("index %s out of range" % tostring(k))
    if t is SqInstance:
        if k in o.vals:
            o.vals[k] = v
            return
        mm = o.cls.meta.get("_set")
        if mm is not None:
            call(mm, o, (k, v))
            return
        raise SqError("the index '%s' does not exist" % tostring(k))
    if t is SqClass:
        if nk(k) in o.members.d:
            o.members.d[nk(k)] = v
            return
        raise SqError("the index '%s' does not exist" % tostring(k))
    if isinstance(o, SqNative):
        o.sq_set(k, v)
        return
    raise SqError("trying to set '%s'" % typeof(o))


def newslot(o, k, v):
    t = type(o)
    if t is SqTable:
        if k is None:
            raise SqError("null cannot be used as index")
        dg = o.delegate
        if dg is not None and nk(k) not in o.d:
            mm = get_raw(dg, "_newslot")
            if mm is not None:
                call(mm, o, (k, v))
                return
        o.newslot(k, v)
        return
    if t is SqClass:
        o.define(k, v)
        return
    if isinstance(o, SqNative):
        o.sq_newslot(k, v)
        return
    if t is SqInstance:
        mm = o.cls.meta.get("_newslot")
        if mm is not None:
            call(mm, o, (k, v))
            return
        raise SqError("class instances do not support the new slot operator")
    raise SqError("indexing %s with %s" % (typeof(o), typeof(k)))


def delete(o, k):
    t = type(o)
    if t is SqTable:
        if o.delegate is not None:
            mm = get_raw(o.delegate, "_delslot")
            if mm is not None:
                return call(mm, o, (k,))
        v = o.remove(k)
        if v is MISSING:
            raise SqError("the index '%s' does not exist" % tostring(k))
        return v
    if t is SqInstance:
        mm = o.cls.meta.get("_delslot")
        if mm is not None:
            return call(mm, o, (k,))
        raise SqError("cannot delete a slot from instance")
    if isinstance(o, SqNative) and hasattr(o, "sq_delete"):
        return o.sq_delete(k)
    raise SqError("attempt to delete a slot from a %s" % typeof(o))


# ----- operators -----
def add(a, b):
    ta, tb = type(a), type(b)
    if ta is int and tb is int:
        r = a + b
        if -2147483648 <= r <= 2147483647:
            return r
        return i32(r)
    if ta is str:
        return a + tostring(b)
    if tb is str:
        return tostring(a) + b
    if (ta is float or ta is int) and (tb is float or tb is int):
        return f32(a + b)
    return arith_meta("_add", a, b, "+")


def arith(op, a, b):
    ta, tb = type(a), type(b)
    if ta is int and tb is int:
        if op == "-":
            return i32(a - b)
        if op == "*":
            return i32(a * b)
        if op == "/":
            if b == 0:
                raise SqError("division by zero")
            q = abs(a) // abs(b)
            return i32(q if (a >= 0) == (b >= 0) else -q)
        if op == "%":
            if b == 0:
                raise SqError("modulo by zero")
            r = abs(a) % abs(b)
            return r if a >= 0 else -r
    elif (ta is float or ta is int) and (tb is float or tb is int):
        if op == "-":
            return f32(a - b)
        if op == "*":
            return f32(a * b)
        if op == "/":
            if b == 0:
                if a == 0 or a != a:
                    return float("nan")
                return float("inf") if (a > 0) else float("-inf")
            return f32(a / b)
        if op == "%":
            import math
            if b == 0:
                return float("nan")
            return f32(math.fmod(a, b))
    return arith_meta({"-": "_sub", "*": "_mul", "/": "_div", "%": "_modulo"}[op], a, b, op)


def arith_meta(name, a, b, op):
    mm = None
    if type(a) is SqTable and a.delegate is not None:
        mm = get_raw(a.delegate, name)
    elif type(a) is SqInstance:
        mm = a.cls.members.d.get(name)
    if mm is not None:
        return call(mm, a, (b,))
    raise SqError("arith op %s on between '%s' and '%s'" % (op, typeof(a), typeof(b)))


def neg(a):
    t = type(a)
    if t is int:
        return i32(-a)
    if t is float:
        return -a
    if t is SqTable and a.delegate is not None:
        mm = get_raw(a.delegate, "_unm")
        if mm is not None:
            return call(mm, a, ())
    raise SqError("attempt to negate a %s" % typeof(a))


def eq(a, b):
    ta, tb = type(a), type(b)
    if ta is tb:
        if ta is str or ta is int or ta is float or ta is bool:
            return a == b
        return a is b
    if (ta is int and tb is float) or (ta is float and tb is int):
        return a == b
    return False


def cmp(a, b):
    """Squirrel ObjCmp: -1/0/1, raising for incomparable types."""
    ta, tb = type(a), type(b)
    if ta is tb:
        if ta is int or ta is float or ta is str:
            return -1 if a < b else (1 if a > b else 0)
        if a is b:
            return 0
        if a is None:
            return 0
        if ta is bool:
            return -1 if a < b else (1 if a > b else 0)
        mm = None
        if ta is SqTable and a.delegate is not None:
            mm = get_raw(a.delegate, "_cmp")
        elif ta is SqInstance:
            mm = a.cls.meta.get("_cmp")
        if mm is not None:
            r = call(mm, a, (b,))
            if type(r) is not int:
                raise SqError("_cmp must return an integer")
            return r
        aa, bb = getattr(a, "addr", id(a)), getattr(b, "addr", id(b))
        return -1 if aa < bb else 1
    if (ta is int or ta is float) and (tb is int or tb is float):
        return -1 if a < b else (1 if a > b else 0)
    if a is None:
        return -1
    if b is None:
        return 1
    raise SqError("comparison between '%.50s' and '%.50s'" % (print_obj_val(a), print_obj_val(b)))


def bitop(op, a, b):
    if type(a) is not int or type(b) is not int:
        raise SqError("bitwise op between '%s' and '%s'" % (typeof(a), typeof(b)))
    if op == "&":
        return i32(a & b)
    if op == "|":
        return i32(a | b)
    if op == "^":
        return i32(a ^ b)
    if op == "<<":
        return i32(a << (b & 31))
    if op == ">>":
        return a >> (b & 31)
    return i32((a & 0xFFFFFFFF) >> (b & 31))      # >>>


def clone(v):
    t = type(v)
    if t is SqTable:
        c = v.clone()
        if c.delegate is not None:
            mm = get_raw(c.delegate, "_cloned")
            if mm is not None:
                call(mm, c, (v,))
        return c
    if t is list:
        return list(v)
    if t is SqInstance:
        c = SqInstance.__new__(SqInstance)
        c.cls = v.cls
        c.vals = dict(v.vals)
        c.addr = new_addr()
        mm = v.cls.meta.get("_cloned")
        if mm is not None:
            call(mm, c, (v,))
        return c
    if isinstance(v, SqNative) and hasattr(v, "sq_clone"):
        return v.sq_clone()
    raise SqError("cloning a %s" % typeof(v))


def hsort(arr, compare):
    """Squirrel 3.0.x array.sort(): heapsort, ported verbatim (order of equal
    elements matters to scripts, so Python's stable sort would differ)."""
    def sift_down(root, bottom):
        done = False
        while True:
            root2 = root * 2
            if root2 > bottom or done:
                break
            if root2 == bottom:
                max_child = root2
            else:
                max_child = root2 if compare(arr[root2], arr[root2 + 1]) > 0 else root2 + 1
            if compare(arr[root], arr[max_child]) < 0:
                if root == max_child:
                    raise SqError("inconsistent compare function")
                arr[root], arr[max_child] = arr[max_child], arr[root]
                root = max_child
            else:
                done = True

    size = len(arr)
    for i in range(size // 2, -1, -1):
        sift_down(i, size - 1)
    for i in range(size - 1, 0, -1):
        arr[0], arr[i] = arr[i], arr[0]
        sift_down(0, i - 1)

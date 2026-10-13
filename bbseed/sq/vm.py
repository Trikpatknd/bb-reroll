"""The interpreter object: root table, name lookup, iteration, base library
and the default delegates (methods of built-in types)."""
import math
import re

from . import runtime as R
from .compiler import Compiler
from .parser import parse
from .sqregexp import make_regexp_class
from .runtime import (DELEGATES, MISSING, NativeFn, SqClass, SqClosure, SqError, SqInstance,
                      SqNative, SqTable, SqWeakRef, call, eq, get, tostring, typeof)

_FMT_RE = re.compile(r"%([-+ #0]*)(\d+)?(?:\.(\d+))?([diuoxXcsfgGeE%])")
_NUM_PREFIX = re.compile(r"\s*[-+]?(?:\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)")
_INT_PREFIX = re.compile(r"\s*[-+]?\d+")


def sq_format(fmt, *args):
    it = iter(args)

    def one(m):
        flags, width, prec, conv = m.groups()
        if conv == "%":
            return "%"
        try:
            a = next(it)
        except StopIteration:
            raise SqError("not enough parameters for the given format string")
        spec = "%" + flags + (width or "") + ("." + prec if prec is not None else "")
        if conv in "diu":
            if type(a) is float:
                a = int(a)
            elif type(a) is bool:
                a = int(a)
            elif type(a) is not int:
                raise SqError("integer expected for the specified format")
            return (spec + "d") % a
        if conv in "oxX":
            if type(a) is float:
                a = int(a)
            if type(a) is not int:
                raise SqError("integer expected for the specified format")
            return (spec + conv) % (a & 0xFFFFFFFF)
        if conv == "c":
            return (spec + "c") % (a if type(a) is int else int(a))
        if conv in "fgGeE":
            if type(a) not in (int, float):
                raise SqError("float expected for the specified format")
            if conv == "f":
                return (spec + "f") % R.fmt_f(float(a), int(prec) if prec is not None else 6)
            return (spec + conv) % float(a)
        if type(a) is not str:
            raise SqError("string expected for the specified format")
        return (spec + "s") % a

    return _FMT_RE.sub(one, fmt)


def _str_to_num(s):
    """Squirrel str2num: float if the text contains '.', else integer; None if unparsable."""
    if "." in s:
        m = _NUM_PREFIX.match(s)
        return R.f32(float(m.group())) if m else None
    m = _INT_PREFIX.match(s)
    return R.i32(int(m.group())) if m else None


class VM:
    def __init__(self):
        self.root = SqTable()
        self.consts = {}
        self.stack = []             # active Squirrel closures, innermost last (for getstackinfos)
        self.print_fn = print
        self.last_trace = []
        self.debug_hook = None      # closure set by setdebughook()
        self.frame_this = {}        # stack index -> `this`, for frames the host pushes itself
        self._install_delegates()
        self._install_baselib()

    # ------------------------------------------------------------------ compile / run
    def compile(self, src, name):
        proto, _defaults = Compiler(self, name).compile_main(parse(src, name))
        return SqClosure(proto, None, (), self)

    def run(self, src, name, this=None):
        return self.compile(src, name).invoke(self.root if this is None else this, ())

    def note_trace(self, depth):
        """Remember where the error being caught came from (debugging aid only)."""
        self.last_trace = ["%s (%s:%s)" % (c.proto.name, c.proto.src, c.proto.line) for c in self.stack[max(depth, 0):]]

    def native(self, name, fn):
        self.root.newslot(name, NativeFn(fn, name))

    # ------------------------------------------------------------------ name resolution
    def lookup(self, this, name):
        """Identifier / `this.x` read: `this` (with delegates), then the root table."""
        t = type(this)
        if t is SqTable:
            v = this.d.get(name, MISSING)
            if v is not MISSING:
                if type(v) is SqWeakRef:
                    return v.obj
                return v
            if this.delegate is not None:
                try:
                    return get(this, name)
                except SqError:
                    pass
            else:
                v = R.DELEGATES["table"].get(name)      # default delegate comes before the root table
                if v is not None:
                    return v
        elif isinstance(this, SqNative):
            v = this.sq_find(name)
            if v is not MISSING:
                return v
        elif this is not None:
            try:
                return get(this, name)
            except SqError:
                pass
        v = self.root.d.get(name, MISSING)
        if v is MISSING:
            raise SqError("the index '%s' does not exist" % name)
        return v

    def assign_nonlocal(self, this, name, value):
        t = type(this)
        if t is SqTable:
            if name in this.d:
                this.d[name] = value
                return
            dg = this.delegate
            if dg is not None:
                while dg is not None:           # SQVM::FallBackSet: an existing slot of a delegate is written there
                    if name in dg.d:
                        dg.d[name] = value
                        return
                    dg = dg.delegate
                mm = R.get_raw(this.delegate, "_set")
                if mm is not None:
                    call(mm, this, (name, value))
                    return
        elif isinstance(this, SqNative):
            if this.sq_try_set(name, value):
                return
        elif this is not None:
            try:
                R.set_(this, name, value)
                return
            except SqError:
                pass
        rd = self.root.d
        if name in rd:
            rd[name] = value
            return
        raise SqError("the index '%s' does not exist" % name)

    def iterate(self, o):
        t = type(o)
        if t is list:
            i = 0
            while i < len(o):
                v = o[i]
                yield i, (v.obj if type(v) is SqWeakRef else v)
                i += 1
        elif t is SqTable:
            idx = 0
            while True:
                r = o.next(idx)
                if r is None:
                    return
                idx, k, v = r
                yield k, (v.obj if type(v) is SqWeakRef else v)
        elif t is str:
            for i, c in enumerate(o):
                yield i, ord(c)
        elif t is SqClass:
            for k, v in o.members.items():
                yield k, v
        elif t is SqInstance:
            mm = o.cls.meta.get("_nexti")
            if mm is None:
                raise SqError("cannot iterate instance")
            idx = None
            while True:
                idx = call(mm, o, (idx,))
                if idx is None:
                    return
                yield idx, get(o, idx)
        elif isinstance(o, SqNative) and hasattr(o, "sq_iter"):
            for kv in o.sq_iter():
                yield kv
        else:
            raise SqError("cannot iterate %s" % typeof(o))

    # ------------------------------------------------------------------ default delegates
    def _install_delegates(self):
        def weakref(this):
            if this is None or type(this) in (int, float, bool, str):
                return this
            return SqWeakRef(this)

        def tostr(this):
            return tostring(this)

        common = {"weakref": weakref, "tostring": tostr}

        # --- table ---
        def t_rawget(this, k):
            v = this.d.get(R.nk(k), MISSING)
            if v is MISSING:
                raise SqError("the index '%s' does not exist" % tostring(k))
            return v

        def t_rawset(this, k, v):
            this.newslot(k, v)
            return this

        def t_rawdelete(this, k):
            v = this.remove(k)
            return None if v is MISSING else v

        def t_setdelegate(this, d):
            if d is not None and type(d) is not SqTable:
                raise SqError("delagate cycle or wrong type")
            this.delegate = d
            return this

        table = dict(common, len=lambda this: len(this.d), rawget=t_rawget, rawset=t_rawset,
                     rawdelete=t_rawdelete, rawin=lambda this, k: R.nk(k) in this.d,
                     clear=lambda this: this.clear(), setdelegate=t_setdelegate,
                     getdelegate=lambda this: this.delegate)

        # --- array ---
        def a_append(this, v):
            this.append(v)
            return this

        def a_extend(this, other):
            this.extend(other)
            return this

        def a_pop(this):
            if not this:
                raise SqError("pop() on a empty array")
            return this.pop()

        def a_top(this):
            if not this:
                raise SqError("top() on a empty array")
            return this[-1]

        def a_insert(this, idx, v):
            idx = int(idx)
            if idx < 0 or idx > len(this):
                raise SqError("index out of range")
            this.insert(idx, v)
            return this

        def a_remove(this, idx):
            idx = int(idx)
            if idx < 0 or idx >= len(this):
                raise SqError("idx out of range")
            return this.pop(idx)

        def a_resize(this, n, fill=None):
            n = int(n)
            if n < 0:
                raise SqError("resizing to a negative value")
            cur = len(this)
            if n < cur:
                del this[n:]
            else:
                this.extend([fill] * (n - cur))
            return this

        def a_reverse(this):
            this.reverse()
            return this

        def a_sort(this, fn=None):
            if len(this) > 1:
                if fn is None:
                    R.hsort(this, R.cmp)
                else:
                    def compare(a, b):
                        r = call(fn, self.root, (a, b))
                        if type(r) is not int:
                            raise SqError("sort func must return an integer")
                        return r
                    R.hsort(this, compare)
            return this

        def a_slice(this, start=0, end=None):
            n = len(this)
            start = int(start)
            end = n if end is None else int(end)
            if start < 0:
                start += n
            if end < 0:
                end += n
            if end < start:
                raise SqError("wrong indexes")
            if end > n or start < 0:
                raise SqError("slice out of range")
            return this[start:end]

        def a_find(this, v):
            for i, x in enumerate(this):
                if eq(x, v):
                    return i
            return None

        def a_map(this, fn):
            return [call(fn, this, (x,)) for x in list(this)]

        def a_apply(this, fn):
            for i in range(len(this)):
                this[i] = call(fn, this, (this[i],))
            return this

        def a_reduce(this, fn):
            if not this:
                return None
            acc = this[0]
            for x in this[1:]:
                acc = call(fn, this, (acc, x))
            return acc

        def a_filter(this, fn):
            return [x for i, x in enumerate(list(this)) if R.truthy(call(fn, this, (i, x)))]

        def a_clear(this):
            del this[:]

        array = dict(common, len=lambda this: len(this), append=a_append, push=a_append, extend=a_extend,
                     pop=a_pop, top=a_top, insert=a_insert, remove=a_remove, resize=a_resize,
                     reverse=a_reverse, sort=a_sort, slice=a_slice, find=a_find, map=a_map,
                     apply=a_apply, reduce=a_reduce, filter=a_filter, clear=a_clear)

        # --- string ---
        def s_slice(this, start=0, end=None):
            n = len(this)
            start = int(start)
            end = n if end is None else int(end)
            if start < 0:
                start += n
            if end < 0:
                end += n
            if end < start:
                raise SqError("wrong indexes")
            if end > n or start < 0:
                raise SqError("slice out of range")
            return this[start:end]

        def s_find(this, sub, start=0):
            start = int(start)
            if start < 0:
                start += len(this)
            if start < 0:
                raise SqError("slice out of range")
            i = this.find(sub, start)
            return None if i < 0 else i

        def s_tointeger(this, base=10):
            if base != 10:
                try:
                    return R.i32(int(this.strip(), base))
                except ValueError:
                    raise SqError("cannot convert the string")
            v = _str_to_num(this)
            if v is None:
                raise SqError("cannot convert the string")
            return int(v)

        def s_tofloat(this):
            v = _str_to_num(this)
            if v is None:
                raise SqError("cannot convert the string")
            return R.f32(float(v))

        string = dict(common, len=lambda this: len(this), slice=s_slice, find=s_find,
                      tolower=lambda this: this.lower(), toupper=lambda this: this.upper(),
                      tointeger=s_tointeger, tofloat=s_tofloat)

        # --- numbers / bool ---
        number = dict(common, tointeger=lambda this: int(this), tofloat=lambda this: R.f32(float(this)),
                      tochar=lambda this: chr(int(this) & 0xFF))

        # --- function ---
        def f_call(this, env=None, *args):
            return call(this, env, args)

        def f_acall(this, arr):
            if not arr:
                raise SqError("acall requires an array with at least the environment")
            return call(this, arr[0], tuple(arr[1:]))

        def f_bindenv(this, env):
            if type(env) is SqWeakRef:
                env = env.obj
            return this.bind(env)

        def f_getinfos(this):
            t = SqTable()
            if type(this) is SqClosure:
                p = this.proto
                t.newslot("native", False)
                t.newslot("name", p.name)
                t.newslot("src", p.src)
                # as closure_getinfos does: a vararg function's list ends with "vargv", "..."
                t.newslot("parameters", ["this"] + list(p.param_names) + (["..."] if p.varargs else []))
                t.newslot("defparams", list(this.defaults))
                t.newslot("varargs", 1 if p.varargs else 0)
            else:
                t.newslot("native", True)
                t.newslot("name", this.name)
                t.newslot("paramscheck", 0)
                t.newslot("typecheck", [])
            return t

        function = dict(common, call=f_call, pcall=f_call, acall=f_acall, pacall=f_acall,
                        bindenv=f_bindenv, getinfos=f_getinfos)

        # --- class / instance / weakref ---
        def c_instance(this):
            return SqInstance(this)

        klass = dict(common, instance=c_instance, getbase=lambda this: this.base,
                     rawget=lambda this, k: this.members.get(k), rawin=lambda this, k: k in this.members,
                     rawset=lambda this, k, v: this.members.newslot(k, v) and None,
                     getattributes=lambda this, k: None, setattributes=lambda this, k, v: None)
        instance = dict(common, getclass=lambda this: this.cls,
                        rawget=lambda this, k: this.vals.get(k), rawin=lambda this, k: k in this.vals,
                        rawset=lambda this, k, v: this.vals.__setitem__(k, v))
        wref = dict(common, ref=lambda this: this.obj)

        for name, table_ in (("table", table), ("array", array), ("string", string), ("integer", number),
                             ("float", number), ("bool", number), ("function", function),
                             ("class", klass), ("instance", instance), ("weakref", wref)):
            DELEGATES[name] = {k: NativeFn(fn, k) for k, fn in table_.items()}

    # ------------------------------------------------------------------ base library
    def _install_baselib(self):
        root = self.root

        def sq_print(this, *args):
            self.print_fn("".join(tostring(a) for a in args))

        def sq_assert(this, cond=None, *rest):
            if not R.truthy(cond):
                raise SqError("assertion failed")

        def sq_array(this, size, fill=None):
            return [fill] * int(size)

        def sq_getstackinfos(this, level):
            level = int(level)
            if level == 0:
                t = SqTable()
                t.newslot("func", "getstackinfos")
                t.newslot("src", "NATIVE")
                t.newslot("line", -1)
                return t
            if level > len(self.stack):
                return None
            cl = self.stack[-level]
            t = SqTable()
            t.newslot("func", cl.proto.name if cl.proto.name is not None else "unknown")
            t.newslot("src", cl.proto.src)
            t.newslot("line", cl.proto.line)
            loc = SqTable()
            idx = len(self.stack) - level
            if idx in self.frame_this:
                loc.newslot("this", self.frame_this[idx])
            t.newslot("locals", loc)
            return t

        def sq_setdebughook(this, hook=None):
            self.debug_hook = hook

        def sq_compilestring(this, src, name="(compilestring)"):
            return self.compile(src, name)

        def sq_split(this, s, seps):
            out, cur = [], []
            for ch in s:
                if ch in seps:
                    out.append("".join(cur))
                    cur = []
                else:
                    cur.append(ch)
            out.append("".join(cur))
            return [p for p in out if p != ""]       # strtok semantics: empty tokens are skipped

        natives = {
            "print": sq_print, "error": sq_print, "assert": sq_assert, "array": sq_array,
            "type": lambda this, v: typeof(v), "typeof": lambda this, v: typeof(v),
            "getroottable": lambda this: root, "getconsttable": lambda this: self._const_table(),
            "getstackinfos": sq_getstackinfos, "compilestring": sq_compilestring,
            "setdebughook": sq_setdebughook,
            "collectgarbage": lambda this: 0, "resurrectunreachable": lambda this: None,
            "format": lambda this, fmt, *a: sq_format(fmt, *a),
            "split": sq_split,
            "strip": lambda this, s: s.strip(), "lstrip": lambda this, s: s.lstrip(),
            "rstrip": lambda this, s: s.rstrip(),
            # sqstd math library
            "sqrt": lambda this, x: R.f32(math.sqrt(x)), "sin": lambda this, x: R.f32(math.sin(x)),
            "cos": lambda this, x: R.f32(math.cos(x)), "tan": lambda this, x: R.f32(math.tan(x)),
            "asin": lambda this, x: R.f32(math.asin(x)), "acos": lambda this, x: R.f32(math.acos(x)),
            "atan": lambda this, x: R.f32(math.atan(x)), "atan2": lambda this, y, x: R.f32(math.atan2(y, x)),
            "log": lambda this, x: R.f32(math.log(x)), "log10": lambda this, x: R.f32(math.log10(x)),
            "exp": lambda this, x: R.f32(math.exp(x)), "pow": lambda this, x, y: R.f32(math.pow(x, y)),
            "floor": lambda this, x: R.f32(math.floor(x)), "ceil": lambda this, x: R.f32(math.ceil(x)),
            "fabs": lambda this, x: R.f32(abs(x)), "abs": lambda this, x: abs(int(x)),
        }
        for name, fn in natives.items():
            root.newslot(name, NativeFn(fn, name))
        root.newslot("regexp", make_regexp_class())
        root.newslot("PI", R.f32(math.pi))
        root.newslot("RAND_MAX", 32767)
        root.newslot("_version_", "Squirrel 3.0.4 stable")
        root.newslot("_versionnumber_", 304)
        root.newslot("_charsize_", 1)
        root.newslot("_intsize_", 4)
        root.newslot("_floatsize_", 4)

    def _const_table(self):
        t = SqTable()
        for k, v in self.consts.items():
            t.newslot(k, v)
        return t

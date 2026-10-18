"""A stand-in for the Battle Brothers engine: just enough of its native side to
load the game's scripts and run their logic outside the game.

Everything here mirrors behaviour MEASURED in the real engine (see MODLOG.md,
"Engine script object model"): how files are included, what inherit() and
new() build, how functions are bound, what the Math natives return.
"""
import json
import zipfile
import zlib
from pathlib import Path

from .rng import MT64, sdbm64
from .sq import bytecode, cnut
from .sq import runtime as R
from .sq.lexer import SqSyntaxError
from .sq.runtime import (MISSING, NativeFn, SqClass, SqClosure, SqError, SqInstance, SqNative,
                         SqTable, call, f32, get, tostring)
from .sq.vm import VM

SURFACE = json.loads((Path(__file__).with_name("native_surface.json")).read_text(encoding="utf-8"))


class _ArchiveEntry:
    """A script inside a zip archive; read like a pathlib.Path."""

    __slots__ = ("archive", "name")

    def __init__(self, archive, name):
        self.archive = archive
        self.name = name

    def read_text(self, encoding="utf-8", errors="strict"):
        return self.archive.read(self.name).decode(encoding, errors)

    def read_bytes(self):
        return self.archive.read(self.name)


PLAIN_MARKER = "bbseed-unscrambled.txt"


class CRand:
    """The C runtime rand() the engine exposes as Math.rand() with no arguments."""

    def __init__(self):
        self.state = 1

    def next(self):
        self.state = (self.state * 214013 + 2531011) & 0xFFFFFFFF
        return (self.state >> 16) & 0x7FFF


class Stub(SqNative):
    """A native object we do not model. Reading a camelCase name gives a
    do-nothing function, reading a PascalCase name gives a stored field (null
    by default); every distinct use is recorded so it can be reviewed."""

    sq_type = "instance"

    def __init__(self, engine, kind, fields=None):
        self.engine = engine
        self.kind = kind
        self.fields = dict(fields or {})
        self.addr = R.new_addr()

    def sq_find(self, key):
        if key in self.fields:
            return self.fields[key]
        if isinstance(key, str) and key[:1].islower():
            self.engine.note_stub(self.kind, key)
            return self.engine.noop
        if isinstance(key, str):
            self.engine.note_stub(self.kind, key + " (field)")
            return None
        return MISSING

    def sq_get(self, key):
        v = self.sq_find(key)
        if v is MISSING:
            raise SqError("the index '%s' does not exist" % tostring(key))
        return v

    def sq_set(self, key, value):
        self.fields[key] = value

    def sq_newslot(self, key, value):
        self.fields[key] = value

    def sq_has(self, key):
        return key in self.fields


class Engine:
    def __init__(self, roots, game_version="1.5.1.8", verbose=False):
        """roots: script roots, highest priority first (a later root is only used
        for paths the earlier ones do not provide), like the game's data archives."""
        self.vm = VM()
        self.root = self.vm.root
        self.verbose = verbose
        self.game_version = game_version
        self.rng = MT64(0)
        self.crand = CRand()
        self.log = []                 # (level, text)
        self.errors = []              # script load/run failures: (path, message)
        self.stub_uses = {}           # (kind, name) -> count
        self.files = {}               # script path without extension -> Path (source text, .nut)
        self.cfiles = {}              # script path without extension -> (Path, unscrambled?) (compiled, .cnut)
        self.included = set()
        self.envs = {}                # script path -> the per-file `this` table
        self.include_stack = []
        self.instance_counter = {}
        self.hash_to_path = {}        # ClassNameHash -> script path
        self.draw_log = None          # set to a list to record every seeded Math.rand call
        self.log_lines = None         # while a list: logInfo lines go there instead of self.log (a map run's log) ...
        self.info_hook = None         # ... and this is called with each of them (mapgen stops a run with it)
        self.odd_rand_calls = []      # Math.rand calls with a non-numeric bound (see m_rand)
        self.equal_bounds_draw = False  # does Math.rand(x, x) consume a draw? (settled by the June log: no)
        self.noop = NativeFn(lambda this, *a: None, "noop")
        self.assets = set()           # non-script files (ui/, gfx/ ...), extensionless, for IO.enumerateFiles
        for root in reversed([Path(r) for r in roots]):
            if root.is_file():        # an archive, as it sits in the game's data folder (mod zip, data_*.dat)
                archive = zipfile.ZipFile(root)
                names = archive.namelist()
                plain = PLAIN_MARKER in names         # our own cache of a data_*.dat (see gamedata.py)
                if plain:                             # ... which lists the archive's other files by name
                    for name in archive.read(PLAIN_MARKER).decode("utf-8").splitlines()[1:]:
                        self._index(name, None, True)
                for name in names:
                    if not name.endswith("/") and name != PLAIN_MARKER:
                        self._index(name, _ArchiveEntry(archive, name), plain)
                continue
            for f in root.rglob("*"):
                if f.is_file() and ".git" not in f.parts:
                    self._index(f.relative_to(root).as_posix(), f, False)
        self._install_natives()

    def _index(self, rel, source, plain):
        """Register one file of a root; a later call for the same path replaces the earlier one
        (a root's script hides a lower root's script of the same name, compiled or not)."""
        if rel.endswith(".nut"):
            self.files[rel[:-4]] = source
            self.cfiles.pop(rel[:-4], None)
        elif rel.endswith(".cnut"):
            self.cfiles[rel[:-5]] = (source, plain)
            self.files.pop(rel[:-5], None)
        elif "." in rel.rsplit("/", 1)[-1]:
            self.assets.add(rel.rsplit(".", 1)[0])

    def script_paths(self):
        """Every script the roots provide (path without extension), as source text or compiled."""
        return set(self.files) | set(self.cfiles)

    # ------------------------------------------------------------------ bookkeeping
    def note_stub(self, kind, name):
        key = (kind, name)
        self.stub_uses[key] = self.stub_uses.get(key, 0) + 1

    def _log(self, level):
        def fn(this, *args):
            text = "".join(tostring(a) for a in args)
            if level == "error" and self.vm.last_trace:
                text += "\n      trace: " + " > ".join(self.vm.last_trace[-8:])
            if self.verbose:
                print("[%s] %s" % (level, text))
            if level == "info" and self.log_lines is not None:
                self.log_lines.append(text)
                if self.info_hook is not None:
                    self.info_hook(text)
            else:
                self.log.append((level, text))
        return fn

    # ------------------------------------------------------------------ files
    @staticmethod
    def _norm(path):
        path = path.replace("\\", "/")
        for ext in (".nut", ".cnut"):
            if path.endswith(ext):
                return path[:-len(ext)]
        return path

    def enumerate_files(self, directory):
        prefix = directory.replace("\\", "/")
        if not prefix.endswith("/"):
            prefix += "/"
        found = sorted(set(p for src in (self.files, self.cfiles, self.assets) for p in src if p.startswith(prefix)))
        return found if found else None

    def include(self, path):
        """Engine include(): run a script file once, with `this` = a new empty table."""
        path = self._norm(path)
        if path in self.included:
            return None
        self.included.add(path)
        f = self.files.get(path)
        if f is not None:
            try:
                closure = self.vm.compile(f.read_text(encoding="utf-8", errors="replace"), path + ".nut")
            except SqSyntaxError as e:
                self.errors.append((path, "compile: %s" % e))
                return None
        elif path in self.cfiles:
            source, plain = self.cfiles[path]
            try:
                main = cnut.load(source.read_bytes(), scrambled=not plain)[0]
            except cnut.CnutError as e:
                self.errors.append((path, "compiled script: %s" % e))
                return None
            closure = SqClosure(bytecode.function(self.vm, main), None, [], self.vm)
        else:
            self.errors.append((path, "File not found"))
            return None
        env = SqTable()
        self.envs[path] = env
        self.include_stack.append(path)
        depth = len(self.vm.stack)
        try:
            closure.invoke(env, ())
            self._fire_return_hook(closure, env, path, depth)
        except SqError as e:
            self.vm.note_trace(depth)
            del self.vm.stack[depth:]
            self.errors.append((path, "run: %s\n      trace: %s" % (tostring(e.value), " > ".join(self.vm.last_trace[-8:]))))
        finally:
            self.include_stack.pop()
        cls = env.get(path.rsplit("/", 1)[-1])
        if type(cls) is SqTable and "ClassName" not in cls:
            self._name_class(cls, path)
        return None

    def _fire_return_hook(self, closure, env, path, depth):
        """setdebughook support, reduced to what the mods use: the 'r' (return)
        event of a file's main function, during which getstackinfos(2) is that file."""
        hook = self.vm.debug_hook
        if hook is None:
            return
        stack = self.vm.stack
        self.vm.debug_hook = None            # Squirrel does not re-enter the hook
        stack.append(closure)
        self.vm.frame_this[len(stack) - 1] = env
        try:
            call(hook, self.root, (ord("r"), path + ".nut", 0, "main"))
        finally:
            self.vm.frame_this.pop(depth, None)
            del stack[depth:]
            if self.vm.debug_hook is None:
                self.vm.debug_hook = hook

    def _name_class(self, cls, path):
        h = R.i32(zlib.crc32(path.encode()))
        self.hash_to_path[h] = path
        cls.newslot("ClassName", path.rsplit("/", 1)[-1])
        cls.newslot("ClassNameHash", h)

    def class_table(self, path):
        path = self._norm(path)
        self.include(path)
        env = self.envs.get(path)
        cls = env.get(path.rsplit("/", 1)[-1]) if env is not None else None
        if type(cls) is not SqTable:
            raise SqError("the script '%s' does not define a class" % path)
        return cls

    # ------------------------------------------------------------------ object model
    def _copy_class(self, cls):
        """The copy of a base class table that inherit() stores in the derived class."""
        c = cls.clone()
        m = cls.get("m")
        if type(m) is SqTable:
            c.d["m"] = self._deep(m)
        sup = cls.get("SuperName")
        if sup is not None:
            c.d[sup] = self._copy_class(cls.get(sup))
        return c

    def _deep(self, v):
        t = type(v)
        if t is SqTable:
            c = v.clone()
            for k, x in c.d.items():
                tx = type(x)
                if tx is SqTable or tx is list:
                    c.d[k] = self._deep(x)
            return c
        if t is list:
            return [self._deep(x) if type(x) in (SqTable, list) else x for x in v]
        return v

    def inherit(self, this, base_path, members):
        base_path = self._norm(base_path)
        base = self.class_table(base_path)
        base_name = base_path.rsplit("/", 1)[-1]
        members.newslot(base_name, self._copy_class(base))
        current = self.include_stack[-1] if self.include_stack else "?"
        self._name_class(members, current)
        members.newslot("SuperName", base_name)
        return members

    def instantiate(self, cls):
        top = cls.clone()

        def build(level_cls, level, is_top):
            m = level_cls.get("m")
            if type(m) is SqTable:
                level.d["m"] = self._deep(m)
            if not is_top:
                d = level.d
                for k, v in d.items():
                    if type(v) is SqClosure:
                        d[k] = v.bind(top)
            sup_name = level_cls.get("SuperName")
            if sup_name is not None:
                sup_cls = level_cls.get(sup_name)
                sup = sup_cls.clone()
                level.d[sup_name] = sup
                level.delegate = sup
                build(sup_cls, sup, False)
                if type(level.d.get("m")) is SqTable and type(sup.d.get("m")) is SqTable:
                    level.d["m"].delegate = sup.d["m"]
            else:
                name = level_cls.get("ClassName") or "?"
                n = self.instance_counter.get(name, 0) + 1
                self.instance_counter[name] = n
                level.newslot("self", NativeFn(lambda this: top, "self"))
                level.newslot("base", self.noop)
                level.newslot("InstanceName", "%s@%d" % (cls.get("ClassName") or name, n))

        build(cls, top, True)
        top.newslot("_release_hook_DO_NOT_delete_it_", Stub(self, "release_hook"))
        return top

    def new(self, this, path):
        obj = self.instantiate(self.class_table(path))
        create = R.get_raw(obj, "create")
        if create is not None:
            call(create, obj, ())
        return obj

    @staticmethod
    def is_kind_of(this, obj, name):
        if type(obj) is SqInstance:        # WeakTableRef
            obj = obj.vals.get("WeakTable")
        if type(obj) is not SqTable:
            return False
        t = obj
        while t is not None:
            if t.d.get("ClassName") == name:
                return True
            sup = t.d.get("SuperName")
            if sup is None:
                return False
            if sup == name:
                return True
            t = t.d.get(sup)
        return False

    # ------------------------------------------------------------------ natives
    def _install_natives(self):
        root = self.root
        n = self.vm.native

        for level, name in (("info", "logInfo"), ("warn", "logWarning"), ("error", "logError"), ("debug", "logDebug")):
            n(name, self._log(level))
        n("include", lambda this, path: self.include(path))
        n("inherit", self.inherit)
        n("new", self.new)
        n("isKindOf", self.is_kind_of)
        n("hasDLC", lambda this, *a: True)
        n("isSteamBuild", lambda this: True)
        n("isReleaseBuild", lambda this: True)
        n("isDevmode", lambda this: False)
        n("isScenarioDemo", lambda this: False)
        n("isSomethingToSee", lambda this: False)
        n("isModified", lambda this: False)
        n("isFirstCharacter", lambda this, s, chars: bool(s) and s[0] in chars)
        n("doesBrushExist", lambda this, name: True)
        n("removeFromBeginningOfText", lambda this, prefix, text: text[len(prefix):] if text.startswith(prefix) else text)
        n("createColor", lambda this, *a: Stub(self, "color"))
        n("createColorRGB", lambda this, *a: Stub(self, "color"))
        n("createColorWhite", lambda this, *a: Stub(self, "color"))
        n("createVec", lambda this, x=0, y=0: Stub(self, "vec", {"X": x, "Y": y}))
        n("hexStringToInt", lambda this, s: R.i32(int(s, 16)))
        n("getPersistentStat", lambda this, *a: 0)
        n("hasAchievement", lambda this, *a: False)
        n("rand", lambda this: self.crand.next())
        n("toHash", lambda this, obj: R.i32(getattr(obj, "addr", 0) or id(obj)))      # an id unique per object
        n("buildTextFromTemplate", self._build_text)
        n("srand", lambda this, seed: setattr(self.crand, "state", int(seed) & 0xFFFFFFFF))

        # Math
        rng_holder = self

        def m_rand(this, *args):
            if not args:
                return self.crand.next()
            if type(args[0]) not in (int, float) or type(args[1]) not in (int, float):
                # A bound that is not a number, e.g. Legends' typo `Math.rand(1, 100 <= 50)` = rand(1, false).
                # Measured in the game (draw trace, 2026-10-13): such a call CONSUMES ONE DRAW and returns
                # some large number (180463302 once) — the engine evidently reads the bound as garbage.
                # Scripts can only sensibly use the result as "true"; the exact value is not reproduced.
                u = rng_holder.rng.next()
                v = 1 + u % 0x7FFFFFFF
                self.odd_rand_calls.append((tostring(args[0]), tostring(args[1]), self._caller()))
                if self.draw_log is not None:
                    self.draw_log.append((0, 0x7FFFFFFF, v, self._caller()))
                return v
            lo, hi = int(args[0]), int(args[1])
            if hi < lo or (hi == lo and not self.equal_bounds_draw):
                if self.draw_log is not None:
                    self.draw_log.append((lo, hi, None, self._caller()))
                # hi <= lo: returns lo and draws nothing. The value was measured in the game
                # (rand(35, 0) == 35, rand(5, 5) == 5); "draws nothing" is what makes the June
                # log's draw counts come out (tools/spawn.py; --equal-draws shows the alternative).
                return lo
            v = lo + rng_holder.rng.next() % (hi - lo + 1)
            if self.draw_log is not None:
                self.draw_log.append((lo, hi, v, self._caller()))
            return v

        def m_seed(this, seed):
            self.rng = MT64(int(seed) & 0xFFFFFFFF)

        def m_seed_string(this, s):
            self.rng = MT64(sdbm64(s))

        def c_round(x):
            x = float(x)
            return int(x + 0.5) if x >= 0 else -int(-x + 0.5)

        import math
        math_fns = {
            "rand": m_rand, "seedRandom": m_seed, "seedRandomString": m_seed_string,
            "max": lambda this, a, b: max(int(a), int(b)), "min": lambda this, a, b: min(int(a), int(b)),
            "maxf": lambda this, a, b: f32(max(float(a), float(b))), "minf": lambda this, a, b: f32(min(float(a), float(b))),
            "abs": lambda this, a: abs(int(a)), "absf": lambda this, a: f32(abs(float(a))),
            "round": lambda this, a: c_round(f32(a)), "floor": lambda this, a: f32(math.floor(f32(a))),
            "ceil": lambda this, a: f32(math.ceil(f32(a))), "pow": lambda this, a, b: f32(math.pow(float(a), float(b))),
            "getAngleTo": lambda this, *a: 0.0,
        }
        self.Math = self._table("Math", math_fns)

        self.virtual_time = 0.0
        time_fns = {
            "getVirtualTimeF": lambda this: f32(self.virtual_time), "getVirtualTime": lambda this: int(self.virtual_time),
            "getRealTime": lambda this: 123456, "getRealTimeF": lambda this: 123456.0, "getExactTime": lambda this: 0.0,
            "setVirtualTime": lambda this, t: setattr(self, "virtual_time", float(t)),
            "getFrame": lambda this: 0, "getRound": lambda this: 0, "getDelta": lambda this: 0.0,
            "getVirtualDelta": lambda this: 0.0, "getVirtualSpeed": lambda this: 1.0, "getFPS": lambda this: 60,
            "hasEventScheduled": lambda this, *a: False,
        }
        self.Time = self._table("Time", time_fns)

        io_fns = {
            "enumerateFiles": lambda this, d: self.enumerate_files(d),
            "scriptHashByFilename": lambda this, p: R.i32(zlib.crc32(self._norm(p).encode())),
            "scriptFilenameByHash": lambda this, h: self.hash_to_path.get(h),
        }
        self._table("IO", io_fns)
        self._table("GameInfo", {
            "getVersionNumber": lambda this: self.game_version, "getVersionName": lambda this: "",
            "getBuildName": lambda this: "", "getRevisionNumber": lambda this: 0,
            "getBuildDate": lambda this: "", "getCompany": lambda this: "Overhype Studios",
        })
        # World clock. UNVERIFIED values: 105 real seconds per day is community knowledge, not measured.
        self.world_time = SqTable()
        for k, v in (("Days", 1), ("Hours", 7), ("Minutes", 0), ("SecondsPerDay", 105.0), ("SecondsPerHour", 4.375),
                     ("SecondsOfDay", 30.625), ("Time", 30.625), ("TimeOfDay", 2), ("IsDaytime", True)):
            self.world_time.newslot(k, v)
        self.World = self._table("World", {"getTime": lambda this: self.world_time})
        for name in ("Tactical", "Settings", "Sound", "Music"):
            self._table(name, {})
        # The save folder as the scripts see it. MSU keeps a player's saved mod settings there; the lab
        # reports none, so mod settings are the mods' defaults unless the caller sets them.
        self._table("PersistenceManager", {"queryStorages": lambda this: []})
        # UI.connect() hands back the JS side of a screen; scripts only call into it
        self._table("UI", {"connect": lambda this, *a: Stub(self, "UI.handle")})
        # UNVERIFIED semantics (names come from script usage; behaviour assumed, re-check with a probe)
        self._table("String", {
            "replace": lambda this, s, find, repl: s.replace(find, repl) if find else s,
            "remove": lambda this, s, what: s.replace(what, "") if what else s,
            "contains": lambda this, s, what: what in s,
        })
        tu = SqTable()
        for k, i in (("Virtual", 1), ("Real", 0), ("Rounds", 2)):      # measured in the game (probe 5)
            tu.newslot(k, i)
        root.newslot("TimeUnit", tu)

        # every other native the real root table has: a counted do-nothing stand-in
        for name, kind in SURFACE["__root__"].items():
            if name in root or name in ("ZZC", "ZZP", "Const", "WeakTableRef"):
                continue
            if kind == "function":
                root.newslot(name, self._stub_fn("root", name))
            elif kind == "class":
                root.newslot(name, SqClass())

    @staticmethod
    def _build_text(this, template, variables):
        """%key% substitution. ASSUMED semantics (flavour text only, no gameplay effect)."""
        text = template if isinstance(template, str) else ""
        for pair in variables or ():
            if isinstance(pair, list) and len(pair) >= 2 and isinstance(pair[0], str):
                text = text.replace("%" + pair[0] + "%", tostring(pair[1]) if pair[1] is not None else "")
        return text

    def _caller(self, depth=3):
        """Innermost script functions on the stack, for the draw log."""
        return " < ".join("%s@%s:%s" % (c.proto.name, c.proto.src.rsplit("/", 1)[-1], c.proto.line)
                          for c in reversed(self.vm.stack[-depth:]))

    def _stub_fn(self, kind, name):
        # getX()/createX() of an unmodelled native table hands back another stub object,
        # everything else returns null. Each use is counted and must be reviewed.
        returns_object = name.startswith("create") or (kind != "root" and name.startswith("get"))

        def fn(this, *args):
            self.note_stub(kind, name)
            return Stub(self, "%s.%s()" % (kind, name)) if returns_object else None
        return NativeFn(fn, name)

    def _table(self, name, fns):
        t = SqTable()
        for k, fn in fns.items():
            t.newslot(k, NativeFn(fn, k))
        for k in SURFACE.get(name, {}):
            if k not in t and not k.startswith("__sqrat"):
                t.newslot(k, self._stub_fn(name, k))
        self.root.newslot(name, t)
        return t

    # ------------------------------------------------------------------ boot
    def boot(self):
        """What the engine does at start-up: run scripts/preload.nut."""
        self.include("scripts/preload")

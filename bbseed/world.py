"""Stand-ins for the native half of the world state: rosters, entities, sprites.

Only what roster creation touches. Anything a script asks for that is not
modelled is answered by a counted do-nothing stub (Engine.stub_uses), so the
gaps stay visible instead of silently changing behaviour.
"""
from .engine import Stub
from .sq import runtime as R
from .sq.runtime import NativeFn, SqError, SqNative, SqTable, call, tostring

_ENT = "\0entity"      # hidden slot on an entity's root-level table -> EntityState
_STATE = "\0state"     # hidden slot on a game state's root-level table -> its name

_SETTLEMENTS_NUT = """
local list = ::World.EntityManager.m.Settlements;
for (local i = 0; i < %d; ++i)
    list.push({ ClassName = "settlement", Name = "Town " + i, function getNameOnly() { return this.Name; } });
for (local i = 0; i < %d; ++i)
    list.push({ ClassName = "city_state", SuperName = "settlement", settlement = { ClassName = "settlement" },
                Name = "City " + i, function getNameOnly() { return this.Name; } });
"""


class Brush(SqNative):
    def __init__(self, name):
        self.name = name
        self.addr = R.new_addr()

    def sq_get(self, key):
        if key == "Name":
            return self.name
        raise SqError("the index '%s' does not exist" % tostring(key))


class Sprite(Stub):
    """A sprite layer. Fields the scripts read back are kept; drawing is not modelled."""

    def __init__(self, engine, name):
        Stub.__init__(self, engine, "sprite", {
            "Visible": True, "HasBrush": False, "Alpha": 255, "Saturation": 1.0, "Scale": 1.0,
            "Rotation": 0.0, "Color": Stub(engine, "color"), "IsFadingIn": False, "IsFadingOut": False,
        })
        self.sprite_name = name
        self.brush = None
        self.methods = {
            "setBrush": NativeFn(self._set_brush, "setBrush"),
            "resetBrush": NativeFn(self._reset_brush, "resetBrush"),
            "getBrush": NativeFn(lambda this: self.brush, "getBrush"),
        }

    def _set_brush(self, this, name):
        self.brush = Brush(name)
        self.fields["HasBrush"] = True

    def _reset_brush(self, this):
        self.brush = None
        self.fields["HasBrush"] = False

    def sq_find(self, key):
        m = self.methods.get(key)
        if m is not None:
            return m
        return Stub.sq_find(self, key)


class EntityState:
    def __init__(self, engine, eid, top):
        self.engine = engine
        self.id = eid
        self.sprites = {}
        self.order = []
        self.faction = 0
        self.initialized = False


def _state(this):
    t = this
    while t is not None:
        s = t.d.get(_ENT)
        if s is not None:
            return s
        t = t.delegate
    raise SqError("native entity function called on a non-entity")


class Roster(SqNative):
    def __init__(self, world, name):
        self.world = world
        self.name = name
        self.members = []
        self.addr = R.new_addr()
        eng = world.engine
        self.methods = {k: NativeFn(fn, k) for k, fn in {
            "create": lambda this, path: self.create(path),
            "getAll": lambda this: list(self.members),
            "getSize": lambda this: len(self.members),
            "remove": lambda this, bro: self.remove(bro),
            "add": lambda this, bro: self.members.append(bro),
            "clear": lambda this: self.members.clear(),
        }.items()}
        self.stub = Stub(eng, "roster")

    def sq_get(self, key):
        m = self.methods.get(key)
        return m if m is not None else self.stub.sq_get(key)

    def create(self, path):
        bro = self.world.create_entity(path)
        self.members.append(bro)
        return bro

    def remove(self, bro):
        for i, b in enumerate(self.members):
            if b is bro:
                del self.members[i]
                return


class World:
    """Builds what world_state.onInit() builds, minus the UI."""

    def __init__(self, engine, discover=False):
        self.engine = engine
        self.discover = discover
        self.next_entity_id = 1
        self.rosters = {}
        self.entity_natives = SqTable()
        self._install_entity_natives()
        self._install_state_natives()
        self._install_world_natives()

    # ------------------------------------------------------------------ entities
    def _install_entity_natives(self):
        eng = self.engine
        t = self.entity_natives

        def add_sprite(this, name):
            st = _state(this)
            sp = Sprite(eng, name)
            st.sprites[name] = sp
            st.order.append(name)
            return sp

        def get_sprite(this, name):
            sp = _state(this).sprites.get(name)
            if sp is None:
                raise SqError("sprite '%s' does not exist" % name)     # UNVERIFIED: real engine behaviour
            return sp

        fns = {
            "getID": lambda this: _state(this).id,
            "addSprite": add_sprite,
            "getSprite": get_sprite,
            "hasSprite": lambda this, name: name in _state(this).sprites,
            "removeSprite": lambda this, name: _state(this).sprites.pop(name, None) and None,
            "isPlacedOnMap": lambda this: False,
            "getFaction": lambda this: _state(this).faction,
            "setFactionEx": lambda this, f: setattr(_state(this), "faction", f),
            "isInitialized": lambda this: _state(this).initialized,
            "isHiddenToPlayer": lambda this: False,
            "getSpriteOffset": lambda this, name: Stub(eng, "vec", {"X": 0.0, "Y": 0.0}),
        }
        for k, fn in fns.items():
            t.newslot(k, NativeFn(fn, k))
        if self.discover:
            root = eng.root

            def fallback(this, key):
                if not isinstance(key, str) or key in root.d or key.startswith("_") or key in R.DELEGATES["table"]:
                    raise SqError(None)
                eng.note_stub("entity", key)
                return eng.noop if key[:1].islower() else None
            fb = SqTable()
            fb.newslot("_get", NativeFn(fallback, "_get"))
            t.delegate = fb

    def create_entity(self, path):
        """What a roster's create() does. ASSUMED sequence (not yet probed):
        build the object, attach the natives, create(), onInit(), onAfterInit()."""
        eng = self.engine
        obj = eng.instantiate(eng.class_table(path))
        base = obj
        while base.delegate is not None:
            base = base.delegate
        st = EntityState(eng, self.next_entity_id, obj)
        self.next_entity_id += 1
        base.d[_ENT] = st
        base.delegate = self.entity_natives
        for name in ("create", "onInit", "onAfterInit"):
            fn = R.get_raw(obj, name)
            if fn is not None:
                call(fn, obj, ())
            if name == "onInit":
                st.initialized = True       # ASSUMED: true once onInit() has run
        return obj

    # ------------------------------------------------------------------ world
    def roster(self, name):
        r = self.rosters.get(name)
        if r is None:
            r = self.rosters[name] = Roster(self, name)
        return r

    def _install_world_natives(self):
        eng = self.engine
        w = eng.World
        fns = {
            "getPlayerRoster": lambda this: self.roster("player"),
            "getTemporaryRoster": lambda this: self.roster("temporary"),
            "getGuestRoster": lambda this: self.roster("guest"),
            "getRoster": lambda this, rid: self.roster("id:%s" % rid),
        }
        for k, fn in fns.items():
            w.d[k] = NativeFn(fn, k)

    def new(self, path):
        return self.engine.new(None, path)

    def weak(self, table):
        return call(self.engine.root.get("WeakTableRef"), None, (table,))

    def start(self):
        """Everything the game has done by the time a new campaign's roster is created."""
        self.start_main_menu()
        self.build_state()
        self.add_placeholder_settlements()
        return self

    def new_state(self, name, script):
        """A game state object: the script class plus the engine's state functions."""
        eng = self.engine
        st = eng.instantiate(eng.class_table(script))
        base = st
        while base.delegate is not None:
            base = base.delegate
        base.delegate = self.state_natives
        base.d[_STATE] = name
        self.states[name] = st
        create = R.get_raw(st, "create")
        if create is not None:
            call(create, st, ())
        return st

    def _install_state_natives(self):
        eng = self.engine
        t = self.state_natives = SqTable()
        self.states = {}

        def add(this, name, script):
            st = self.new_state(name, script)
            call(R.get_raw(st, "onInit"), st, ())
            return st

        def state_name(this):
            s = this
            while s is not None:
                if _STATE in s.d:
                    return s.d[_STATE]
                s = s.delegate
            return "?"

        for k, fn in {"add": add, "get": lambda this, name: self.states.get(name), "getName": state_name,
                      "has": lambda this, name: name in self.states}.items():
            t.newslot(k, NativeFn(fn, k))
        root = eng.root

        def fallback(this, key):
            if not isinstance(key, str) or key in root.d or key.startswith("_") or key in R.DELEGATES["table"]:
                raise SqError(None)
            eng.note_stub("state", key)
            return eng.noop if key[:1].islower() else None
        fb = SqTable()
        fb.newslot("_get", NativeFn(fallback, "_get"))
        t.delegate = fb

    def start_main_menu(self):
        """What the game does between loading the scripts and showing the main menu:
        root_state.onInit() (global screens, MapGen ...) adds the MainMenuState, whose
        onInit() creates the scenario manager (the campaign's origin object comes from
        there) and the main menu screen. Mods hang work on these — Legends loads its
        `afterHooks` files when that screen connects, and Modern Hooks postpones both
        onInit()s until its UI side reports back; that report is made here."""
        eng = self.engine
        root_state = self.new_state("RootState", "scripts/root_state")
        call(R.get_raw(root_state, "onInit"), root_state, ())
        hooks = eng.root.d.get("Hooks")
        if hooks is not None:
            conn = R.get(hooks, "JSConnection")
            call(R.get(conn, "resumeOnInit"), conn, ())
        return self.states.get("MainMenuState")

    def scenario(self, name):
        """The origin object a campaign would get: looked up in the scenario manager by
        script name ("trader_scenario") or scenario ID ("scenario.trader")."""
        mgr = R.get(self.engine.root.get("Const"), "ScenarioManager")
        for s in R.get(R.get(mgr, "m"), "Scenarios"):
            if s.get("ClassName") == name or call(R.get(s, "getID"), s, ()) == name:
                return s
        # not offered in the menu (invalid / hidden origins): build it directly
        return self.engine.new(None, "scripts/scenarios/world/" + name)

    def build_state(self):
        """Create the world state and run its real onInit() (mod hooks included),
        with the UI construction and the campaign start switched off."""
        eng = self.engine
        state = self.new_state("WorldState", "scripts/states/world_state")
        self.state = state
        state.newslot("onInitUI", eng.noop)
        state.newslot("init", eng.noop)
        call(R.get_raw(state, "onInit"), state, ())
        return state

    def add_placeholder_settlements(self, northern=21, city_states=3):
        """Roster creation only reads the settlement list for flavour text (town names
        in background descriptions), but it draws one random number per name it picks,
        and whether it picks a city-state name depends on one existing. So the list
        must be non-empty in both kinds, as on a generated map; the names are filler."""
        self.engine.vm.run(_SETTLEMENTS_NUT % (northern, city_states), "lab_settlements")

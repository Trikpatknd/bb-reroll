"""The world map: the game's own campaign start, run in the lab until the map is there.

`Lab.world_map(seed)` builds a fresh world state and calls its real `startNewCampaign()` (vanilla
`scripts/states/world_state.nut`, with every mod hook; Legends' hook sets `::Legends.IsStartingNewCampaign`,
which makes its `worldmap_generator.fill` wrapper apply the Map Options and log the settings). That function
seeds the generator with the campaign seed, has `MapGen.get("world.worldmap_generator")` fill the map, and seeds
it AGAIN before the roster is made (engine fact 2). The run is stopped from inside the scripts:

  stop_at="accepted"  right after the generator logs "World accepted." (the land/sea/elevation loop is done)
  stop_at="reseed"    at the second Math.seedRandomString(Seed): the whole map is done there

`MapGen` is not a native: root_state.onInit() makes it from `scripts/mapgen/map_generator.nut`, which
instantiates every script under `scripts/mapgen/templates/` (mod hooks applied, `init()` called) and hands them
out by `m.Name`, the same instance per name. The lab runs root_state.onInit() at start-up (World.start_main_menu),
so the game's own MapGen is there; nothing here replaces it.

A run that goes to the second seeding also hands back `summary()`: the finished map as plain data (terrain, towns,
ports), which `mapdraw` draws and the map conditions read.

The tile world is `hexmap.HexMap`, made by the `World.resizeScene` native the first time and reused after that
(reset to blank tiles), like every other per-run structure here: a map run builds no new tile world.

Everything a run puts in place (tile natives, the wrapped seed functions, the log capture) is taken away again
when it ends, however it ends, so the roster path sees the engine as before.
"""
import re
import time

from .hexmap import LAYOUTS, HexMap, MapError, NotModelled  # noqa: F401  (MapError/NotModelled: mapgen's API)
from .sq import runtime as R
from .sq.runtime import MISSING, NativeFn, SqError, SqTable, tostring

# The hex layout of the engine's tile grid (see hexmap.py), measured against the 96 world generations of the
# in-game logs (map-search Task 4; bb_seedlab MODLOG "CHECKPOINT A"): N is y+1 (high y is north:
# tile_mountains.nut puts snow at y >= SizeY * Snowline), and the even columns sit half a row lower (further south)
# than the odd ones: tile (4, 5) is at Pos.Y 554.3, below (5, 5) at 609.7, and its NE neighbour is (5, 5).
# - Land/ocean/desert counts and draws of all 96 generations (579 attempts) match in even-q-up and also in
#   odd-q-down: those two are one grid with N and S swapped, and up to "World accepted." the scripts only count
#   neighbours. odd-q-up / even-q-down (the other grid) miss attempt 1 of every generation tried.
# - The shore brush warnings after it (`Shore Brush undefined (N)!`, N = Const.DirectionBit mask of a shore
#   tile's land neighbours) decide: even-q-up logs the game's masks in 96/96 generations, odd-q-down in 79/96
#   (mirrored masks such as 62 for 55, or other warnings where its terrain past "accepted" differs).
LAYOUT = "even-q-up"

STOPS = ("accepted", "reseed")
ACCEPTED = "World accepted."

# The generator's attempt lines (Legends' isWorldAcceptable / isDesertAcceptable). The ratio's text is left out:
# only the counts are compared with the game.
_LAND_RE = re.compile(r"^Land Ocean ratio\S* >= \S+ :: Land :(\d+) Ocean:(\d+)$")
_DESERT_RE = re.compile(r"^Desert tiles (\d+) >= \S+$")


def events_from_log(lines):
    """The attempts of a map run, from its logInfo lines: ["land", land, ocean] per land/sea check,
    ["desert", tiles] per desert check, ["accepted"] at the end. The same format as the reference data the
    research lab reads from the game's own log.html (bb_seedlab tools/maplog.py)."""
    events = []
    for line in lines:
        m = _LAND_RE.match(line)
        if m:
            events.append(["land", int(m.group(1)), int(m.group(2))])
        elif (m := _DESERT_RE.match(line)):
            events.append(["desert", int(m.group(1))])
        elif line == ACCEPTED:
            events.append(["accepted"])
    return events

# ---------------------------------------------------------------------------------------------- the map summary
# The terrain of the summary: ONE CHARACTER PER VALUE of the game's Const.World.TerrainType, the character at index i
# standing for the value i (the base game has 0..18, COUNT = 19; Legends adds SwampGreen 19 and SwampForest 20 and
# sets COUNT = 21; `Land` is the base game's second name for Plains, value 2). The table is written out here, in the
# order of the values, because a summary has to be readable without the game; a game test keeps it in step with the
# scripts' own table. Lower-case letters are Legends' additions. 'O' is the ocean and 'L' the plains, as in the
# hand-made summaries of the tests.
_TERRAIN = (
    ("Impassable", "X"), ("Ocean", "O"), ("Plains", "L"), ("Swamp", "S"), ("Hills", "H"), ("Forest", "F"),
    ("SnowyForest", "J"), ("LeaveForest", "V"), ("AutumnForest", "A"), ("Mountains", "M"), ("Urban", "U"),
    ("Farmland", "G"), ("Snow", "N"), ("Badlands", "B"), ("Tundra", "T"), ("Steppe", "E"), ("Shore", "C"),
    ("Desert", "D"), ("Oasis", "Q"), ("SwampGreen", "g"), ("SwampForest", "f"),
)
TERRAIN_CHARS = "".join(char for _name, char in _TERRAIN)
TERRAIN_NAMES = tuple(name for name, _char in _TERRAIN)         # the name of each value (index = value)


def terrain_string(hm):
    """The terrain of a tile world as one string, a character of TERRAIN_CHARS per tile. The ORDER is y-major: the
    row y = 0 first, and x = 0.. within a row, then y = 1, ... So the string starts at the SOUTH edge (high y is
    north in the measured layout) and index = y * width + x. A tile type that has no character is an error."""
    chars = TERRAIN_CHARS
    cols = hm.cols
    out = []
    for y in range(hm.size_y):
        for x in range(hm.size_x):
            t = cols[x][y].Type
            i = int(t)
            if i != t or not 0 <= i < len(chars):
                raise MapError("tile (%d, %d) has terrain type %r, which TERRAIN_CHARS has no character for" % (x, y, t))
            out.append(chars[i])
    return "".join(out)


# The settlements the scripts registered (settlement.onInit: EntityManager.addSettlement), in creation order.
_TOWNS = """
local out = [];
foreach (s in ::World.EntityManager.getSettlements())
{
    local tile = s.getTile();
    local owner = s.getOwner();
    out.push({
        name = s.getName(), script = s.ClassName, size = s.getSize(),
        x = tile.SquareCoords.X, y = tile.SquareCoords.Y,
        southern = s.isSouthern(), military = s.isMilitary(), port = s.m.IsCoastal,
        faction = owner == null ? null : owner.getName()
    });
}
return out;
"""
_TOWN_KEYS = ("name", "script", "size", "x", "y", "southern", "military", "port", "faction")


def summary(lab, log=()):
    """The map a finished (stop_at="reseed") world_map run left in `lab`, as plain data (it goes between processes
    and into JSON):

      "size":    [width, height] in tiles ([140, 170])
      "layout":  the hex layout the run used (LAYOUT), see hexmap.py
      "terrain": width * height characters of TERRAIN_CHARS, y-major: row y = 0 first (the SOUTH edge: high y is
                 north), x = 0.. within a row; index = y * width + x (see terrain_string)
      "towns":   one dict per settlement, in the order the scripts created them:
                   name, script (the settlement's script class name, e.g. "small_farming_village", "city_state"),
                   size (getSize(): 1, 2 or 3), x and y (its tile's square coordinates), southern (isSouthern()),
                   military (isMilitary()), port (the settlement's own m.IsCoastal after the run: the game's rule,
                   never worked out again here), faction (the name of its owner faction, or None)
      "attempts": how many times the generator built the land and sea before it accepted a world (`log`: the run's
                 lines; from events_from_log)

    Not yet compared with the game (map-search Task 7): the towns' positions, kinds, sizes, names and port flags; only
    their COUNT was (96 of 96 logged generations, Task 5). UNVERIFIED (stage 2): `faction`, and the NAMES of the
    city states: they depend on random draws after the roads are built, which are not exact until the lab has the
    game's own path finder. No condition uses them. The terrain is the lab's at the stop; tiles the game changes after
    buildRoads (if any) may differ."""
    run = lab._maps
    hm = None if run is None else run.hexmap
    if hm is None:
        raise MapError("no map has been run on this lab")
    eng = lab.eng
    try:
        rows = eng.vm.compile(_TOWNS, "lab_map_towns").invoke(eng.root, ())
    except SqError:
        eng.vm.note_trace(0)
        del eng.vm.stack[:]
        raise
    towns = []
    for row in rows:
        town = {k: row.get(k) for k in _TOWN_KEYS}
        for k in ("name", "script"):
            town[k] = tostring(town[k])
        if town["faction"] is not None:
            town["faction"] = tostring(town["faction"])
        for k in ("size", "x", "y"):
            town[k] = int(town[k])
        for k in ("southern", "military", "port"):
            town[k] = bool(town[k])
        towns.append(town)
    return {"size": [hm.size_x, hm.size_y], "layout": hm.layout, "terrain": terrain_string(hm), "towns": towns,
            "attempts": sum(1 for e in events_from_log(log) if e[0] == "land")}


# The campaign start itself; the lab puts its campaign settings on the world state first (lab._SETTINGS).
START = "::World.State.startNewCampaign();"

# The world screen's day-time module, the way world_screen.create() makes it, with a JS side (vargv[0]).
_TOPBAR = """
local module = ::new("scripts/ui/screens/world/modules/topbar/world_screen_topbar_daytime_module");
module.m.JSHandle = vargv[0];
return module;
"""


class StopCampaign(Exception):
    """Ends a campaign start where the map is wanted. Not an SqError, so no script's try/catch can catch it."""


def _missing(name, why):
    def fn(this, *args):
        raise NotModelled("World.%s is not modelled (%s)" % (name, why))
    return NativeFn(fn, name)


# ::World natives a map run must not answer with a counted do-nothing stub (which would let the generator run
# on with wrong answers): until the run reaches one of them on purpose, it stops there.
_NOT_YET = {}

# The counted stand-ins (Engine.stub_uses) a whole map run (stop_at="reseed") may use, each with the reason it
# cannot change a draw, a tile or an entity the scripts read back. Anything else in a run's stub_uses is unexplained.
_ACTOR_DISPLAY = "the faction leaders (noble, councilman, vizier) are actors made like recruits; the same " \
                 "display natives every roster run uses, and the 96 in-game rosters match with them as stand-ins"
HARMLESS_STUBS = {
    # actors (createFactions' leaders): drawing on the tactical map
    ("entity", "createOverlay"): _ACTOR_DISPLAY,
    ("entity", "setOverlayValues"): _ACTOR_DISPLAY,
    ("entity", "setOverlayIcons"): _ACTOR_DISPLAY,
    ("entity", "setPreventOcclusion"): _ACTOR_DISPLAY,
    ("entity", "setBlockSight"): _ACTOR_DISPLAY,
    ("entity", "setVisibleInFogOfWar"): _ACTOR_DISPLAY,
    ("entity", "setSpriteColorization"): _ACTOR_DISPLAY,
    ("entity", "setSpriteOffset"): _ACTOR_DISPLAY,
    ("entity", "setDiscovered"): _ACTOR_DISPLAY,
    ("sprite", "setHorizontalFlipping"): _ACTOR_DISPLAY,
    # colour variation of a sprite: engine natives draw nothing from the seeded stream (engine fact 1, measured on
    # the roster path, which calls them too)
    ("sprite", "varyColor"): _ACTOR_DISPLAY,
    ("sprite", "varySaturation"): _ACTOR_DISPLAY,
    ("sprite", "varyBrightness"): _ACTOR_DISPLAY,
    # Legends' buildSettlements: LoadingScreen.updateProgress("Building Settlements ...") sends the text to the
    # loading screen's HTML side, which sends nothing back
    ("UI.handle", "asyncCall"): "a message to the loading screen's HTML side; nothing comes back",
    # an achievement counter in the Steam client (settlement / location scripts)
    ("root", "updateAchievement"): "a Steam achievement; nothing in the scripts reads it back",
}


def unexplained_stubs(stub_uses):
    """The stand-ins a map run used that HARMLESS_STUBS does not explain."""
    return {k: n for k, n in stub_uses.items() if k not in HARMLESS_STUBS}


class MapRun:
    """Runs the campaign start on one lab's engine. One per lab; everything in it is reused between maps."""

    def __init__(self, eng, start, world=None):
        """start: a compiled script that puts the campaign settings on the world state (vargv: seed, origin
        object) and runs START. world: the lab's world.World (makes the entities World.spawnLocation asks for)."""
        self.eng = eng
        self.world = world
        self.hexmap = None
        self.layout = LAYOUT
        self._start = start
        self._seed = None
        self._stop_at = None
        self._reseeds = 0
        self._draws = 0
        self._saved = []
        math = eng.Math
        self._seed_string = math.get("seedRandomString")
        self._seed_int = math.get("seedRandom")
        # What a run puts on ::World, ::Math and the root table (and takes away again afterwards).
        world = {name: _missing(name, why) for name, why in _NOT_YET.items()}
        world["resizeScene"] = NativeFn(self._resize_scene, "resizeScene")
        world["spawnLocation"] = NativeFn(self._spawn_location, "spawnLocation")
        # The world's game speed (startNewCampaign pauses the game: setPause sets it to 0). It is the speed of
        # the running world's clock; map generation never reads it. UNVERIFIED start value 1.0 (normal speed).
        self._speed = 1.0
        world["getSpeedMult"] = NativeFn(lambda this: self._speed, "getSpeedMult")
        world["setSpeedMult"] = NativeFn(self._set_speed, "setSpeedMult")
        # The top bar's day-time module ("PAUSED" ...), which startNewCampaign's setPause() writes to. The lab
        # builds no UI (World.build_state switches the world state's onInitUI off), so the module is made here
        # from its real script (mod hooks included); only its JS side, the HTML screen, is a stand-in that
        # takes messages and gives nothing back.
        ui = SqTable()
        ui.newslot("asyncCall", NativeFn(lambda this, *args: None, "asyncCall"))
        self._topbar = eng.vm.compile(_TOPBAR, "lab_map_topbar").invoke(eng.root, (ui,))   # kept alive here:
        world["TopbarDayTimeModule"] = R.call(eng.root.get("WeakTableRef"), None, (self._topbar,))   # weak there
        self._world_slots = world
        self._math_fns = {
            "seedRandomString": NativeFn(self._on_seed_string, "seedRandomString"),
            "seedRandom": NativeFn(self._on_seed_int, "seedRandom"),
        }
        self._root_fns = {
            # The generator calls it between its steps, without arguments, and uses no result (UNVERIFIED what
            # it does in the engine: a keep-alive while the loading screen is up?). It could only change the map
            # by drawing random numbers, and one extra draw would shift every later one: with this no-op the lab
            # gives the logged land/ocean/desert counts of every attempt of two real generations (seed
            # 7300000182: all 28; MODLOG "MAP RUN IN THE LAB").
            "__ping": NativeFn(lambda this: None, "__ping"),
        }

    # ------------------------------------------------------------------ the natives a run replaces
    def _resize_scene(self, this, x, y):
        """World.resizeScene: the engine makes a blank tile world of that size. The first call builds the
        HexMap; later calls blank the same tiles again (a new size or layout rebuilds it)."""
        x, y = int(x), int(y)
        hm = self.hexmap
        if hm is None or hm.layout != self.layout:
            hm = self.hexmap = HexMap(self.eng, x, y, self.layout)
        elif (hm.size_x, hm.size_y) != (x, y):
            hm.resize(x, y)
        else:
            hm.reset()
        natives = SqTable()
        hm.install(natives)                   # the tile natives of this HexMap, on ::World until the run ends
        world = self.eng.World
        for name, fn in natives.items():
            if name != "resizeScene":         # (this one stays)
                self._put(world, name, fn)

    def _set_speed(self, this, mult):
        self._speed = float(mult)

    def _spawn_location(self, this, script, coords, *rest):
        """World.spawnLocation(script, coords): a world entity on that tile (world.World.spawn_location)."""
        if rest:
            raise NotModelled("World.spawnLocation with %d more arguments" % len(rest))
        if self.world is None:
            raise NotModelled("World.spawnLocation: this map run has no world.World to make entities")
        tile = self.hexmap.tile_at_coords(int(R.get(coords, "X")), int(R.get(coords, "Y")))
        if tile is None:
            raise NotModelled("World.spawnLocation on coordinates outside the map")
        return self.world.spawn_location(script, tile)

    # Draws are counted by the generator itself (rng.MT64.draws: every number Math.rand takes from the seeded
    # stream, whatever path of the native took it); re-seeding starts a new generator, so the old one's count
    # is added up first. Only a seeding with the campaign seed itself counts towards the stop: startNewCampaign
    # seeds with it before the map and again after it (a hook that seeds another string does not stop the run).
    def _on_seed_string(self, this, s):
        if s == self._seed:
            self._reseeds += 1
            if self._reseeds == 2 and self._stop_at == "reseed":
                raise StopCampaign("reseed")
        self._draws += self.eng.rng.draws
        return R.call(self._seed_string, this, (s,))

    def _on_seed_int(self, this, n):
        self._draws += self.eng.rng.draws
        return R.call(self._seed_int, this, (n,))

    def _on_info(self, text):
        if text == ACCEPTED and self._stop_at == "accepted":
            raise StopCampaign("accepted")

    # ------------------------------------------------------------------ install / restore
    def _put(self, table, name, value):
        self._saved.append((table, name, table.d.get(name, MISSING)))
        table.newslot(name, value)

    def _install(self):
        """Put this run's natives in place; _restore() puts back what was there before."""
        eng = self.eng
        for name, value in self._world_slots.items():
            self._put(eng.World, name, value)
        for name, fn in self._math_fns.items():
            self._put(eng.Math, name, fn)
        for name, fn in self._root_fns.items():
            self._put(eng.root, name, fn)

    def _restore(self):
        for table, name, value in reversed(self._saved):
            if value is MISSING:
                table.remove(name)
            else:
                table.d[name] = value
        self._saved.clear()

    # ------------------------------------------------------------------ the run
    def run(self, seed, scenario, stop_at="reseed", layout=None):
        """Run the campaign start on the current world state up to stop_at (see the module text).
        Returns {"log": logInfo lines, "draws": seeded draws, "seconds", "stub_uses": this run's only}."""
        if stop_at not in STOPS:
            raise ValueError("stop_at must be one of %s, not %r" % (", ".join(STOPS), stop_at))
        layout = layout or LAYOUT
        if layout not in LAYOUTS:
            raise ValueError("unknown layout %r (one of %s)" % (layout, ", ".join(LAYOUTS)))
        eng = self.eng
        self.layout = layout
        self._seed = seed
        self._stop_at = stop_at
        self._reseeds = 0
        self._speed = 1.0
        stubs_before = dict(eng.stub_uses)
        log = []
        # What the stopped start leaves behind and nothing else resets: the engine's clocks and random streams
        # (the roster path seeds its own, but nothing after a map run should depend on how far a map got) and
        # Legends' "a campaign is starting" flag, which its startNewCampaign hook clears only at the very end.
        crand, vtime, rng = eng.crand.state, eng.virtual_time, eng.rng
        legends = eng.root.d.get("Legends")
        starting = legends.d.get("IsStartingNewCampaign", MISSING) if type(legends) is SqTable else MISSING
        self._draws = -rng.draws
        t0 = time.perf_counter()
        stopped = False
        try:
            eng.log_lines = log
            eng.info_hook = self._on_info
            self._install()
            self._start.invoke(eng.root, (seed, scenario))
        except StopCampaign:
            stopped = True
        except (SqError, MapError):
            eng.vm.note_trace(0)          # for the caller's error text, before the stack is cleared
            raise
        finally:
            eng.log_lines = None
            eng.info_hook = None
            del eng.vm.stack[:]           # the frames the stop (or an error) left behind
            self._restore()
            draws = self._draws + eng.rng.draws
            eng.crand.state, eng.virtual_time, eng.rng = crand, vtime, rng
            if starting is not MISSING:
                legends.d["IsStartingNewCampaign"] = starting
        seconds = time.perf_counter() - t0
        if not stopped:
            raise MapError("the campaign start ran to its end without reaching the stop %r" % stop_at)
        stubs = {k: n - stubs_before.get(k, 0) for k, n in eng.stub_uses.items() if n != stubs_before.get(k, 0)}
        return {"log": log, "draws": draws, "seconds": seconds, "stub_uses": stubs}

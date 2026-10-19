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

The tile world is `hexmap.HexMap`, made by the `World.resizeScene` native the first time and reused after that
(reset to blank tiles), like every other per-run structure here: a map run builds no new tile world.

Everything a run puts in place (tile natives, the wrapped seed functions, the log capture) is taken away again
when it ends, however it ends, so the roster path sees the engine as before.
"""
import re
import time

from .hexmap import LAYOUTS, HexMap
from .sq import runtime as R
from .sq.runtime import MISSING, NativeFn, SqError, SqTable

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


class MapError(Exception):
    """A map run went somewhere the lab cannot follow. Not an SqError: no script's try/catch hides it."""


class NotModelled(MapError):
    """The run reached a native the lab does not have yet."""


def _missing(name, why):
    def fn(this, *args):
        raise NotModelled("World.%s is not modelled yet (%s)" % (name, why))
    return NativeFn(fn, name)


# ::World natives the generator calls after "World accepted." that are not modelled yet. A counted
# do-nothing stub would let the generator run on with wrong answers (a path that is never empty, a region
# that is never found), so in a map run they stop it instead.
_NOT_YET = {
    "findNextRegion": "regions and their labels, Task 5",
    "findNextTileOfType": "region labels, Task 5",
    "getNavigator": "the navigator: settlement links and roads, Task 5",
    "queryTilesInRange": "the terrain around a settlement site, Task 5",
    "spawnLocation": "settlements and locations on the map, Task 5",
    "spawnRegionText": "region labels, Task 5",
    "updateTilesWithHeat": "settlement heat, Task 5",
}


class MapRun:
    """Runs the campaign start on one lab's engine. One per lab; everything in it is reused between maps."""

    def __init__(self, eng, start):
        """start: a compiled script that puts the campaign settings on the world state (vargv: seed, origin
        object) and runs START."""
        self.eng = eng
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

    # Draws are counted by the generator itself (rng.MT64.draws: every number Math.rand takes from the seeded
    # stream, whatever path of the native took it); re-seeding starts a new generator, so the old one's count
    # is added up first.
    def _on_seed_string(self, this, s):
        self._reseeds += 1
        if self._reseeds == 2:
            if s != self._seed:
                raise MapError("the second Math.seedRandomString(%r) is not the campaign seed %r" % (s, self._seed))
            if self._stop_at == "reseed":
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
        except SqError:
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

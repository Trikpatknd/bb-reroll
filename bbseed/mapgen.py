"""The world map: the game's own campaign start, run in the lab until the map is there.

`Lab.world_map(seed)` builds a fresh world state and calls its real `startNewCampaign()` (vanilla
`scripts/states/world_state.nut`, with every mod hook; Legends' hook sets `::Legends.IsStartingNewCampaign`,
which makes its `worldmap_generator.fill` wrapper apply the Map Options and log the settings). That function
seeds the generator with the campaign seed, has `MapGen.get("world.worldmap_generator")` fill the map, and seeds
it AGAIN before the roster is made (engine fact 2). The run is stopped from inside the scripts:

  stop_at="accepted"  right after the generator logs "World accepted." (the land/sea/elevation loop is done)
  stop_at="reseed"    at the second Math.seedRandomString(Seed): the whole map is done there
  stop_at="spawn"     past the second seeding, through Assets.setCampaignSettings (the origin's onSpawnAssets) and the
                      origin's onSpawnPlayer, to the call of the origin's onInit() right after it (vanilla world_state
                      startNewCampaign: setCampaignSettings, onSpawnPlayer, onInit, uncoverFogOfWar): the company is on the
                      map and every recruit is made (Deserters makes its recruits in onSpawnPlayer, engine fact 4)

The start ("spawn"). Deserters' onSpawnPlayer (vanilla deserters_scenario.nut and Legends' copy in its hook, checked
in both the vanilla bytecode and Legends' shipped text: a plain loop with a break) takes the FIRST settlement in
getSettlements() order that isMilitary() && !isIsolatedFromRoads() && !isSouthern(), or the LAST settlement when none
does (the loop runs out without a break), and then loops: x = rand(max(2, X - 7), min(SizeX - 2, X + 7)), y likewise
(SizeX / SizeY = Const.World.Settings), until the square is valid, not Ocean / Shore / occupied, more than 4 away, has
a road and findPath(tile, fort, TerrainTypeNavCost_Flat) is not empty. Nothing between the second seeding and that loop
draws except setCampaignSettings (the same draws a roster run makes), and nothing in the loop draws but its two rand()
calls, each of which draws only when its range has two values or more (engine fact 1): a run checks that the draws it
counted from the entry of onSpawnPlayer to World.spawnEntity are deserters_loop_draws(fort, loop, size). The loop is
capped at SPAWN_LOOP_CAP iterations (MapError past it: the game itself would hang there).

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
from .sq.runtime import MISSING, NativeFn, SqError, SqNative, SqTable, tostring

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

STOPS = ("accepted", "reseed", "spawn")
ACCEPTED = "World accepted."

# The probe: one Math.rand(1, 2147483646) drawn where a whole map run stops (stop_at="reseed"), before the second
# seedRandomString(Seed). In startNewCampaign that point comes right after EntityManager.buildRoadAmbushSpots() (vanilla
# world_state.nut: buildRoadAmbushSpots(); seedRandomString(Seed) on the next line), and the in-game verifier
# (bb_seedlab tools/verify_template.nut, map jobs) draws the same number there. The re-seed starts a new stream, so
# the probe changes nothing the campaign start does later. It shows how many draws the whole map took: a map whose
# terrain and towns are right but whose probe differs consumed its draws differently somewhere.
PROBE_RANGE = (1, 2147483646)

# The generator's attempt lines (Legends' isWorldAcceptable / isDesertAcceptable). The ratio's text is left out:
# only the counts are compared with the game. Vanilla's isWorldAcceptable logs no ratio, so its attempts are counted
# by LAND_AND_SEA (one line per buildLandAndSea call in both games; see summary()).
_LAND_RE = re.compile(r"^Land Ocean ratio\S* >= \S+ :: Land :(\d+) Ocean:(\d+)$")
_DESERT_RE = re.compile(r"^Desert tiles (\d+) >= \S+$")
LAND_AND_SEA = "Building land and sea..."


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


# The roads of a finished map: one character per tile for its RoadDirections, the sum of Const.DirectionBit[d] over the
# directions d the road leaves the tile in (bit d = direction d: N 1, NE 2, SE 4, S 8, SW 16, NW 32; the table is
# 1, 2, 4, 8, 16, 32 in the base game's config/global.nut), so a value is 0..63. Index = the value; "." = no road. This
# is the lab's ROAD_CHARS (bb_seedlab tools/map_compare.py), whose RoadDirections grid equals the game's on 40 of 40
# maps of both setups (stage 2 B1, "gate 2"). mapdraw has a copy (it imports nothing); a test keeps the two equal.
ROAD_CHARS = ".123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"


def road_string(hm):
    """The roads of a tile world as one string of ROAD_CHARS, in the order of terrain_string (y-major, row 0 = the south
    edge first). A plain read of each tile's RoadDirections: nothing is drawn or changed. A value that is not a whole
    number 0..63 is an error."""
    chars = ROAD_CHARS
    cols = hm.cols
    out = []
    for y in range(hm.size_y):
        for x in range(hm.size_x):
            v = cols[x][y].RoadDirections
            i = int(v)
            if i != v or not 0 <= i < len(chars):
                raise MapError("tile (%d, %d) has RoadDirections %r, which ROAD_CHARS has no character for" % (x, y, v))
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
      "roads":   width * height characters of ROAD_CHARS in the same order: each tile's RoadDirections (a bit per
                 direction N NE SE S SW NW = 1 2 4 8 16 32; "." = no road), as the finished map has it (see road_string).
                 A summary cached before this key existed has none: mapdraw then draws no roads
      "towns":   one dict per settlement, in the order the scripts created them:
                   name, script (the settlement's script class name, e.g. "small_farming_village", "city_state"),
                   size (getSize(): 1, 2 or 3), x and y (its tile's square coordinates), southern (isSouthern()),
                   military (isMilitary()), port (the settlement's own m.IsCoastal after the run: the game's rule,
                   never worked out again here), faction (the name of its owner faction, or None)
      "attempts": how many times the generator built the land and sea before it accepted a world: the LAND_AND_SEA
                 lines of `log` (the run's lines; one per attempt in Legends and in Vanilla)
      "start":   only after a stop_at="spawn" run (Lab.world_map adds it): the square [x, y] the company starts on, or
                 None; mapdraw draws it as a star on a verified setup

    Compared with the game (map-search Task 7, 40 in-game maps, bb_seedlab MODLOG "CHECKPOINT B"): every town's
    script, x, y, size, name (city states aside), port, southern and military, in this order, are the game's in 40 of
    40 maps, and so is the terrain as it is right before buildRoads. The terrain tiles changed after buildRoads are the game's
    too since stage 2 B1 (40 of 40 maps on both setups; Legends with the in-game batch's black-market counter).
    UNVERIFIED (stage 2 B2): `faction` and the NAMES of the city states (equal on Legends 4 of 40, Vanilla 2 of 40).
    No condition uses them."""
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
    return {"size": [hm.size_x, hm.size_y], "layout": hm.layout, "terrain": terrain_string(hm),
            "roads": road_string(hm), "towns": towns, "attempts": sum(1 for line in log if line == LAND_AND_SEA)}


# ------------------------------------------------------------------------------------------- map conditions
# What the map search counts on a summary. The search workers need it, and bbseed never imports bbreroll, so it lives
# here; bbreroll/map_conditions.py (labels, limits, impossible conditions, the seed post's line) re-exports it.
#
# Town types: every town has exactly one, so the five counts add up to the town count.
#   city_state  a southern town (isSouthern(): the script city_state in Legends 19.4.22 and in the base game)
#   military    a stronghold of any size (isMilitary() and not southern: Legends' legends_fort scripts, the base game's
#               *_fort scripts)
#   size1..3    the other towns by getSize(): villages, towns, cities
# The labels are the game's own words: "villages, cities and strongholds" (vanilla config/strings.nut, the
# campaign introduction), "City State of" (CityStateTitles).
TOWN_TYPE_KEYS = ("city_state", "military", "size1", "size2", "size3")
TOWN_TYPE_LABELS = {"city_state": "City states", "military": "Strongholds", "size1": "Villages", "size2": "Towns",
                    "size3": "Cities"}
PORT_KEYS = ("ports", "ports_south", "ports_north")
PORT_LABELS = {"ports": "Ports", "ports_south": "Southern ports", "ports_north": "Northern ports"}
DEFAULT_NORTH_BAND = 33


def town_type(town):
    """The TOWN_TYPE_KEYS key of one summary town (see above)."""
    if town["southern"]:
        return "city_state"
    if town["military"]:
        return "military"
    size = town["size"]
    if size not in (1, 2, 3):
        raise ValueError("town %r has size %r: a town type needs size 1, 2 or 3" % (town.get("name"), size))
    return "size%d" % size


def in_north_band(y, height, north_band):
    """Is row y in the north band of `north_band` percent (0..100) of a map `height` rows high?

    The band is counted from the north edge (high y is north: y = height - 1 is the top row) and holds the rows y
    with 100 * (height - y) <= north_band * height, i.e. the top floor(height * north_band / 100) rows (rounded
    down; integer arithmetic, no other rounding). On the 170-row Legends map 20 / 33 / 50 % are the top
    34 / 56 / 85 rows (y >= 136 / 114 / 85), 1 % is 1 row, 99 % is 168; 0 % is no row and 100 % the whole map.
    In mapdraw's picture the band line is height * north_band / 100 rows down from the top: the band's rows end
    at or above it in the odd columns; the even columns sit half a row lower, so their last band row can reach
    half a row below it."""
    return 100 * (height - y) <= north_band * height


def counts(summary, north_band):
    """What the map conditions count on a summary (mapgen.summary), with the north band in percent (0..100):

      {"ports": the towns whose port flag is set,
       "ports_south": the ports that are southern towns,
       "ports_north": the ports in the north band that are NOT southern (a southern town is never a northern port),
       "towns": {key: number of towns of that type, for every key of TOWN_TYPE_KEYS, in that order}}"""
    if not 0 <= north_band <= 100:
        raise ValueError("north band %r: it must be 0..100 percent" % (north_band,))
    height = summary["size"][1]
    towns = dict.fromkeys(TOWN_TYPE_KEYS, 0)
    ports = south = north = 0
    for t in summary["towns"]:
        towns[town_type(t)] += 1
        if t["port"]:
            ports += 1
            if t["southern"]:
                south += 1
            elif in_north_band(t["y"], height, north_band):
                north += 1
    return {"ports": ports, "ports_south": south, "ports_north": north, "towns": towns}


def failure(summary, map_criteria):
    """The first map condition the summary does not meet, as a text like "Ports: 4, needs 6"; None when it meets
    them all. The order: ports, southern ports, northern ports, then the town types in TOWN_TYPE_KEYS order.

    map_criteria: {"ports": n, "ports_south": n, "ports_north": n, "north_band": percent (missing or None:
    DEFAULT_NORTH_BAND), "towns": {key: n}}. Every number is a minimum; 0 or missing is no condition. A town key
    that is not in TOWN_TYPE_KEYS is an error. The band is read only when "ports_north" is set (as problems() in
    bbreroll/map_conditions.py does): without a northern-port condition any band value is ignored."""
    c = map_criteria or {}
    want_towns = c.get("towns") or {}
    unknown = set(want_towns) - set(TOWN_TYPE_KEYS)
    if unknown:
        raise ValueError("unknown town types %s (known: %s)" % (sorted(unknown), ", ".join(TOWN_TYPE_KEYS)))
    band = c.get("north_band") if c.get("ports_north") else None
    have = counts(summary, DEFAULT_NORTH_BAND if band is None else band)
    for key in PORT_KEYS:
        need = c.get(key) or 0
        if have[key] < need:
            return "%s: %d, needs %d" % (PORT_LABELS[key], have[key], need)
    for key in TOWN_TYPE_KEYS:
        need = want_towns.get(key) or 0
        if have["towns"][key] < need:
            return "%s: %d, needs %d" % (TOWN_TYPE_LABELS[key], have["towns"][key], need)
    return None


# The failure text of a checked seed whose map run failed, followed by the reason (the roster is still shown).
MAP_NOT_BUILT = "map could not be built: "


# The campaign start itself; the lab puts its campaign settings on the world state first (lab._SETTINGS).
START = "::World.State.startNewCampaign();"

# ---------------------------------------------------------------------------------------------- the start (spawn)
DESERTERS = "scenario.deserters"       # the origin whose recruits depend on the map (engine fact 4)
SPAWN_RANGE = 7                        # x / y = rand(max(2, X - 7), min(Size - 2, X + 7)) around the fort
SPAWN_EDGE = 2
# A run whose start loop (the World.isValidTileSquare calls of onSpawnPlayer before World.spawnEntity) passes this
# many iterations raises MapError instead of running on: a map on which no square passes would hang the game too.
# The 400 lab maps of stage 2 C2 Task 1 needed at most 197 (bb_seedlab MODLOG "DESERTERS IN THE LAB").
SPAWN_LOOP_CAP = 100000


def loop_ranges(fort_xy, size):
    """The two ranges one iteration of Deserters' start loop draws from: ((x_lo, x_hi), (y_lo, y_hi)) for a fort on the
    square fort_xy = (X, Y) of a map size = (Const.World.Settings.SizeX, SizeY): max(2, X - 7) .. min(SizeX - 2, X + 7)."""
    (fx, fy), (sx, sy) = fort_xy, size
    return ((max(SPAWN_EDGE, fx - SPAWN_RANGE), min(sx - SPAWN_EDGE, fx + SPAWN_RANGE)),
            (max(SPAWN_EDGE, fy - SPAWN_RANGE), min(sy - SPAWN_EDGE, fy + SPAWN_RANGE)))


def deserters_loop_draws(fort_xy, n, size=None):
    """How many numbers n iterations of Deserters' start loop take from the seeded stream: per iteration one for x and
    one for y, but a range with a single value (or none: hi < lo) draws nothing (engine fact 1: rand(a, a) draws
    nothing). fort_xy None: the full +-7 ranges (2 per iteration, size not read) - right for every fort at least
    9 squares from each edge (X - 7 >= 2 and X + 7 <= SizeX - 2). A fort closer to an edge has clamped ranges, but
    they still hold two values or more whenever the side is 5 squares or more (min(Size - 2, X + 7) > max(2, X - 7)
    for every X of 0 .. Size - 1 then), so the count is 2n on every real map (Settings 140 x 170 in Legends and in
    Vanilla); only a side of 4 squares or fewer gives a single value (2 .. 2) or none."""
    if n < 0:
        raise ValueError("a loop runs 0 or more times, not %r" % (n,))
    if fort_xy is None:
        return 2 * n
    if size is None:
        raise ValueError("a fort square needs the map size (Const.World.Settings.SizeX, SizeY)")
    return n * sum(1 for lo, hi in loop_ranges(fort_xy, size) if hi > lo)


class StartLoop:
    """What the start loop of one run has tried so far. The checks of one iteration (World.isValidTileSquare, then the
    tile type, the distance to the fort, the road and the route) read only the map, never the stream, so one square
    always gives the same answer, and an iteration that went on to the next one has failed on its square. The loop
    ends as soon as one square passes, so a map on which none passes would draw squares for ever (the game would
    hang the same way). This counts the squares of the fort's ranges (loop_ranges) and tells when all of them have
    failed. Draws nothing, reads nothing from the engine."""

    def __init__(self, ranges):
        (xlo, xhi), (ylo, yhi) = ranges
        # a range with hi < lo gives lo (one value, nothing drawn, engine fact 1)
        self.total = max(1, xhi - xlo + 1) * max(1, yhi - ylo + 1)
        self.failed = set()
        self._last = None

    def enter(self, x, y):
        """The loop asks about the square (x, y) (one iteration). Returns True when this square has failed before:
        the caller can answer "not valid" at once without running the checks. Raises MapError when every square of the
        ranges has failed."""
        if self._last is not None:
            self.failed.add(self._last)           # the loop went on, so that square failed
            if len(self.failed) >= self.total:
                raise MapError("no square around the fort passes the start loop's checks: all %d squares of its "
                               "ranges failed (the game would not get past it either)" % self.total)
        self._last = (int(x), int(y))
        return self._last in self.failed


# What onSpawnPlayer's settlement loop reads, per settlement in getSettlements() order (isIsolatedFromRoads only
# when isMilitary, as the script's && does - it is a plain field read either way: ConnectedToByRoads.len() == 0).
# Each row also has the tile's square (Tile.SquareCoords X, Y): the loop draws around the fort's square.
_FORT_FLAGS = """
local out = [];
foreach (s in ::World.EntityManager.getSettlements())
    out.push([s.isMilitary(), s.isIsolatedFromRoads(), s.isSouthern(), s.getTile().SquareCoords.X, s.getTile().SquareCoords.Y]);
return [out, ::Const.World.Settings.SizeX, ::Const.World.Settings.SizeY];
"""


def fort_index(flags):
    """The settlement Deserters' onSpawnPlayer starts from, as an index into getSettlements() (and summary towns):
    the first one with military and not isolated and not southern, else the last one (the script's loop has no
    break then); None for no settlements (the script would fail). flags: [military, isolated, southern] per town."""
    for i, (military, isolated, southern) in enumerate(flags):
        if military and not isolated and not southern:
            return i
    return len(flags) - 1 if flags else None


def spawn_summary(lab, start, summ, origin_id):
    """The "spawn" part of a stop_at="spawn" run (Lab.world_map), as plain data:

      "tile":     the square (x, y) the party was spawned on (World.spawnEntity in onSpawnPlayer), any origin
      "fort":     Deserters only (else None): the index into summ["towns"] of the settlement the start loop circles
      "loop":     Deserters only: the loop's iterations N (World.isValidTileSquare calls before World.spawnEntity)
      "draws":    Deserters only: the seeded draws D from onSpawnPlayer's entry to World.spawnEntity
      "isolated": isIsolatedFromRoads() of every settlement, in summ["towns"] order
      "size":     [Const.World.Settings.SizeX, SizeY], the size the loop's ranges are clamped to

    For Deserters it checks what the start rests on and raises MapError when one fails: D is
    deserters_loop_draws(fort, N, size) (nothing else in onSpawnPlayer drew before the party), and the tile lies in the
    fort's ranges more than 4 away from it."""
    eng = lab.eng
    try:
        rows, sx, sy = eng.vm.compile(_FORT_FLAGS, "lab_map_forts").invoke(eng.root, ())
    except SqError:
        eng.vm.note_trace(0)
        del eng.vm.stack[:]
        raise
    flags = [[bool(m), bool(i), bool(s)] for m, i, s, _x, _y in rows]
    size = [int(sx), int(sy)]
    out = {"tile": start["tile"], "fort": None, "loop": None, "draws": None,
           "isolated": [f[1] for f in flags], "size": size}
    if origin_id != DESERTERS:
        return out
    if start["tile"] is None:
        raise MapError("Deserters' onSpawnPlayer spawned no party")
    fort = fort_index(flags)
    town = summ["towns"][fort]
    fort_xy = (town["x"], town["y"])
    n, d = start["loop"], start["draws"]
    want = deserters_loop_draws(fort_xy, n, size)
    if d != want:
        raise MapError("onSpawnPlayer drew %d numbers before the party, the start loop's %d iterations around town %d "
                       "take %d" % (d, n, fort, want))
    (xlo, xhi), (ylo, yhi) = loop_ranges(fort_xy, size)
    x, y = start["tile"]
    hm = lab._maps.hexmap
    if not (xlo <= x <= xhi and ylo <= y <= yhi and hm.distance(hm.cols[x][y], hm.cols[fort_xy[0]][fort_xy[1]]) > 4):
        raise MapError("the start tile %r is not one the loop around town %d at %r can accept" % ((x, y), fort, fort_xy))
    out.update(fort=fort, loop=n, draws=d)
    return out


# ---------------------------------------------------------------------------------------------- the start without a map
# Lab.deserters_start: Deserters' own onSpawnPlayer on a world state WITHOUT a map, made to run its start loop exactly n
# times. Its stand-ins answer only what that function asks, so that the draws are the ones the map's run makes:
#   - a fort in front of the settlement list (in place of the first placeholder town: the counts of northern towns
#     and city states, which the recruits' descriptions draw from, stay those of every roster run): military, not
#     isolated, not southern, standing on fort_xy; its noble house gives a banner (the shields' picture) and takes
#     the relation change (faction.addPlayerRelation draws nothing: a min/max and the allies' list);
#   - World.isValidTileSquare: false for the first n - 1 calls (the loop draws x and y and goes round again, as it
#     does for every square that fails, whatever check fails: none of them draws), true for the n-th;
#   - World.getTileSquare: a square that passes the checks (plains, free, a road, 5 away from the fort), and
#     World.getNavigator().findPath a route that is not empty, so the n-th iteration ends the loop as the map's did;
#   - World.spawnEntity: the real player_party script on that square (create / onInit / onAfterInit, as on the map).
# Const.World.Settings.SizeX / SizeY are set to `size` for the run (the loop clamps its ranges to them).
_NO_MAP_FORT = """
local tile = vargv[0];
local faction = {
    function getBanner() { return 2; }
    function addPlayerRelation(_r, _reason = "") {}
    function addPlayerRelationEx(_r, _reason = "") {}
};
return {
    ClassName = "settlement", Name = "Fort",
    function getNameOnly() { return this.Name; }
    function getName() { return this.Name; }
    function isMilitary() { return true; }
    function isIsolatedFromRoads() { return false; }
    function isSouthern() { return false; }
    function getTile() { return tile; }
    function getFactionOfType(_type) { return faction; }
};
"""
_SETTLEMENT_SLOT = """
local list = ::World.EntityManager.m.Settlements;
local old = list[0];
list[0] = vargv[0];
return old;
"""
_SIZES = """
local s = ::Const.World.Settings;
local old = [s.SizeX, s.SizeY];
if (vargv[0] != null) { s.SizeX = vargv[0]; s.SizeY = vargv[1]; }
return old;
"""


class _StandInTile(SqNative):
    """A world square for the start without a map: the fields onSpawnPlayer's loop reads, and getDistanceTo 5."""

    def __init__(self, engine, x, y, terrain):
        from .hexmap import Vec
        self.addr = R.new_addr()
        self.hm = self                    # world.World's entity natives ask a tile's map for its Pos
        self._pos = Vec(0.0, 0.0)
        self.fields = {"Type": terrain, "IsOccupied": False, "HasRoad": True, "SquareCoords": Vec(x, y),
                       "Coords": Vec(x, y), "Pos": self._pos, "ID": -1 - x * 1000 - y,
                       "getDistanceTo": NativeFn(lambda this, other: 5, "getDistanceTo")}
        self.engine = engine

    def pos_of(self, tile):
        return self._pos

    def sq_get(self, key):
        if key in self.fields:
            return self.fields[key]
        self.engine.note_stub("no-map tile", key)
        raise SqError("the index '%s' does not exist" % tostring(key))

    def sq_set(self, key, value):
        self.fields[key] = value


class NoMapStart:
    """The stand-ins of Lab.deserters_start (see above); install() before the run, restore() after it."""

    def __init__(self, eng, world):
        self.eng = eng
        self.world = world
        self._fort_script = eng.vm.compile(_NO_MAP_FORT, "lab_no_map_fort")
        self._slot_script = eng.vm.compile(_SETTLEMENT_SLOT, "lab_no_map_slot")
        self._size_script = eng.vm.compile(_SIZES, "lab_no_map_sizes")
        self._plains = R.get(R.get(R.get(eng.root.get("Const"), "World"), "TerrainType"), "Plains")
        self._saved = []
        self.calls = 0
        self.n = 0
        self.drawn = None               # the square the n-th iteration drew (the map's start tile for the right n)
        self.spawned = None
        self._tile = None

    def install(self, n, fort_xy, size):
        from .engine import Stub
        eng = self.eng
        self.n, self.calls, self.drawn, self.spawned = n, 0, None, None
        self._rng, self._entry, self.spawn_draws = None, 0, None
        old_size = self._size_script.invoke(eng.root, tuple(size) if size is not None else (None, None))
        self._old_size = list(old_size)
        sx, sy = (size if size is not None else old_size)
        if fort_xy is None:
            fort_xy = (int(sx) // 2, int(sy) // 2)
        fort_tile = _StandInTile(eng, int(fort_xy[0]), int(fort_xy[1]), self._plains)
        fort = self._fort_script.invoke(eng.root, (fort_tile,))
        self._old_town = self._slot_script.invoke(eng.root, (fort,))
        nav = SqTable()
        path = SqTable()
        path.newslot("isEmpty", NativeFn(lambda this: False, "isEmpty"))
        nav.newslot("createSettings", NativeFn(lambda this: Stub(eng, "no-map nav settings"), "createSettings"))
        nav.newslot("findPath", NativeFn(lambda this, *args: path, "findPath"))
        fns = {
            "isValidTileSquare": self._valid,
            "getTileSquare": self._tile_square,
            "getNavigator": lambda this: nav,
            "spawnEntity": self._spawn_entity,
        }
        w = eng.World
        for name, fn in fns.items():
            self._saved.append((name, w.d.get(name, MISSING)))
            w.newslot(name, NativeFn(fn, name))

    def _valid(self, this, x, y):
        self.calls += 1
        if self.calls > self.n:
            raise MapError("the start loop went on past its %d iterations" % self.n)
        return self.calls == self.n

    def _tile_square(self, this, x, y):
        if self.calls != self.n:
            raise MapError("getTileSquare before the last iteration")
        self.drawn = (int(x), int(y))
        self._tile = _StandInTile(self.eng, int(x), int(y), self._plains)
        return self._tile

    def entry(self, rng):
        """onSpawnPlayer starts (the caller wraps it): the draws are counted from here."""
        self._rng, self._entry = rng, rng.draws

    def _spawn_entity(self, this, script, cx, cy, *rest):
        if self._tile is None or self.spawned is not None:
            raise MapError("World.spawnEntity outside the start loop's end")
        rng = self.eng.rng
        self.spawn_draws = rng.draws - self._entry if rng is self._rng else None
        self.spawned = self.world.create_entity(script, tile=self._tile)
        return self.spawned

    def restore(self):
        eng = self.eng
        w = eng.World
        for name, value in reversed(self._saved):
            if value is MISSING:
                w.remove(name)
            else:
                w.d[name] = value
        self._saved.clear()
        if getattr(self, "_old_town", None) is not None:
            self._slot_script.invoke(eng.root, (self._old_town,))
            self._old_town = None
        if getattr(self, "_old_size", None) is not None:
            self._size_script.invoke(eng.root, tuple(self._old_size))
            self._old_size = None
        self._tile = None

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
    # the start (stop_at="spawn"): what onSpawnPlayer does after the party is placed, besides the recruits
    ("World", "getCamera"): "onSpawnPlayer moves the world camera to the party (getCamera().setPos(party.getPos())): "
                            "what the screen shows; nothing in the scripts reads it back before the stop",
    ("World.getCamera()", "setPos"): "the camera's position (see World.getCamera): drawing only",
    ("Time", "scheduleEvent"): "onSpawnPlayer schedules the origin's intro event and music 1000 ms of real time later; "
                               "the callback runs only once the running game's clock passes that, after the campaign "
                               "start (the stop comes first), so it cannot change a recruit or a draw before it",
    ("World", "spawnParticleEffect"): "some origins' onSpawnPlayer start a smoke or fire effect on the world map; "
                                      "drawing only, nothing is returned and no draw is made",
    ("Sound", "play"): "some origins' onSpawnPlayer play a sound on the world map; audio only, nothing comes back",
}


def unexplained_stubs(stub_uses):
    """The stand-ins a map run used that HARMLESS_STUBS does not explain."""
    return {k: n for k, n in stub_uses.items() if k not in HARMLESS_STUBS}


# What the maps were checked against (CLAUDE.md engine fact 16, Checkpoint B): game 1.5.2.3 with Legends 19.4.22 and
# the mods it needs. HARMLESS_STUBS is the review of the stand-ins for exactly this set; another mod may hook the
# generator or the settlements and reach a native that nobody reviewed (a map run then raises, see
# search.checked_world_map), so with any other mod the maps are "not verified". Legends' own assets zip belongs to
# Legends. The ids are those the mods register with Modern Hooks (and the start of their zip names).
VERIFIED_GAME = "1.5.2.3"
VERIFIED_LEGENDS = "19.4.22"
# Legends versions whose campaign start is the verified one's (MODLOG "LEGENDS 19.4.23", 2026-11-10: 7 changed scripts, all
# outside the start - two combat skills, four helmets' draw layer, the version; the rest only line endings; rosters, perk
# trees, maps and Deserters starts identical on the lab). A new version goes here only with such a check.
SAME_START_LEGENDS = (VERIFIED_LEGENDS, "19.4.23")
VERIFIED_MOD_IDS = ("mod_legends", "mod_legends_assets", "mod_msu", "mod_modern_hooks")
NOT_VERIFIED = "Map results are not verified for this setup."
# What a seed post and the console say about Legends' black-market counter (every map of a search is built at counter 0):
FIRST_CAMPAIGN = "Start this seed as your first campaign after you start the game."
# Deserters make their brothers on the map (engine fact 4), so they can be searched only where the maps are verified.
# Vanilla maps (no Legends, no mod, every DLC installed: gamedata.all_dlc) were checked against the game: 40 in-game
# Trader maps on game 1.5.2.3 with all DLCs and no mod had the same towns, pre-road terrain and rosters as the lab's
# (bb_seedlab MODLOG "CHECKPOINT V", 2026-10-24; map-search stage 2, Task 9).
VANILLA_MAPS_VERIFIED = True


def _plain(text):
    return "".join(c if c.isalnum() else "_" for c in str(text).lower())


def _verified_mod(name):
    """Is this mod (a zip file name or a registered id) one of VERIFIED_MOD_IDS? The name is the id, or the id and
    then a version or a number: mod_legends-19.4.22.zip is, mod_legends_load_order_fix.zip is not."""
    plain = _plain(name[:-4] if str(name).lower().endswith(".zip") else name)
    for mod in VERIFIED_MOD_IDS:
        if plain == mod or (plain.startswith(mod + "_") and plain[len(mod) + 1:][:1].isdigit()):
            return True
    return False


def other_mods(mods):
    """The mods of this setup that are not in the verified set, as the names given. mods: zip file names
    (profiles.installed_summary()["mods"]) or Lab.info()["mods"] ({"file", "id", "name", "version"} per mod zip)."""
    out = []
    for mod in mods or ():
        name = mod if isinstance(mod, str) else (mod.get("file") or mod.get("id") or mod.get("name") or "")
        if not _verified_mod(name):
            out.append(name)
    return out


# The exact versions of the mods the checked maps ran with (the Legends version is VERIFIED_LEGENDS). Deserters take
# their brothers from the map, so for them a mod of another version is not verified, even when its zip name is the
# right one (verified_setup(exact=True)). The ids are those the mods register (Lab.info()["mods"]).
VERIFIED_MOD_VERSIONS = {"mod_msu": "1.9.0", "mod_modern_hooks": "0.6.0", "mod_legends_assets": "19.4.3"}
# Other versions with the same campaign start (SAME_START_LEGENDS): Legends 19.4.23 needs its assets 19.4.23, whose one
# script registers that version and nothing else (the asset file names are the same as in 19.4.3).
SAME_START_MOD_VERSIONS = {"mod_legends_assets": ("19.4.23",)}


DESERTERS_UNVERIFIED = ("Deserters need the world map. BB Reroll checked the maps for only two setups. "
                        "One is Legends 19.4.22 or 19.4.23 with its mods: Legends assets %(mod_legends_assets)s or "
                        "19.4.23, MSU %(mod_msu)s and Modern Hooks %(mod_modern_hooks)s. "
                        "The other is the base game with all DLCs and no mods. Both use game version 1.5.2.3. "
                        "This game setup is not one of them." % VERIFIED_MOD_VERSIONS)


def wrong_mod_versions(mods):
    """The mods of this setup that are not the exact verified versions, as "id version" texts. Only mods that tell
    their version can be checked (Lab.info()["mods"]: {"file", "id", "name", "version"}); a zip file name (a string,
    the GUI's check before a search) cannot, so it is skipped. A verified mod that is not in the list is listed with
    "missing" - but only when the list has mod dicts at all."""
    infos = [m for m in mods or () if not isinstance(m, str)]
    out = []
    for mod_id, version in VERIFIED_MOD_VERSIONS.items():
        found = [m for m in infos if m.get("id") == mod_id]
        if not found:
            if infos:
                out.append("%s missing" % mod_id)
        elif any(m.get("version") not in (version,) + SAME_START_MOD_VERSIONS.get(mod_id, ()) for m in found):
            out.append("%s %s" % (mod_id, ", ".join(str(m.get("version")) for m in found)))
    return out


def verified_setup(game_version, legends_version, mods=None, dlc_complete=True, exact=False):
    """Were maps of this game, this Legends version and this mod set checked against the real game? mods None: not
    asked: for Legends only the versions count; for Vanilla None counts as no mod.

    exact=True (the Deserters gate): with Legends and mods that tell their versions (Lab.info()["mods"]), MSU, Modern
    Hooks and Legends' assets must be the versions of VERIFIED_MOD_VERSIONS too (wrong_mod_versions). The default
    keeps the loose check, which looks at the mod names only.

    legends_version None is the Vanilla setup: its maps are verified only once VANILLA_MAPS_VERIFIED is set, on the
    verified game version, with no mod at all (the verified Legends mods do not count here: MSU alone is not Vanilla)
    and with every DLC (dlc_complete, gamedata.all_dlc). Legends ignores dlc_complete."""
    if legends_version is None:
        return (VANILLA_MAPS_VERIFIED and game_version == VERIFIED_GAME and dlc_complete
                and (mods is None or not mods))
    return (game_version == VERIFIED_GAME and legends_version in SAME_START_LEGENDS
            and (mods is None or not other_mods(mods))
            and not (exact and mods is not None and wrong_mod_versions(mods)))


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
        self._probe = None
        self._saved = []
        math = eng.Math
        self._seed_string = math.get("seedRandomString")
        self._seed_int = math.get("seedRandom")
        self._rand = math.get("rand")
        # What a run puts on ::World, ::Math and the root table (and takes away again afterwards).
        world = {name: _missing(name, why) for name, why in _NOT_YET.items()}
        world["resizeScene"] = NativeFn(self._resize_scene, "resizeScene")
        world["spawnLocation"] = NativeFn(self._spawn_location, "spawnLocation")
        world["spawnEntity"] = NativeFn(self._spawn_entity, "spawnEntity")
        self._spawn = None              # a "spawn" run, from onSpawnPlayer's entry on: what it counts (see run())
        self._map_draws = None
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
        self._fort_script = eng.vm.compile(_FORT_FLAGS, "lab_map_forts")
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

    def _spawn_entity(self, this, script, cx, cy, *rest):
        """World.spawnEntity(script, X, Y) with the tile's hex coordinates (Tile.Coords): a world entity (the player's
        party, onSpawnPlayer) made like World.spawnLocation's, standing on that tile. UNVERIFIED like spawnLocation:
        that the engine places it before create(), and whether it marks the tile (nothing before the stop reads it)."""
        if rest:
            raise NotModelled("World.spawnEntity with %d more arguments" % len(rest))
        if self.world is None:
            raise NotModelled("World.spawnEntity: this map run has no world.World to make entities")
        tile = self.hexmap.tile_at_coords(int(cx), int(cy))
        if tile is None:
            raise NotModelled("World.spawnEntity on coordinates outside the map")
        sp = self._spawn
        if sp is not None and sp["tile"] is None:
            if self.eng.rng is not sp["rng"]:
                raise MapError("the random stream was seeded again inside onSpawnPlayer: the start draws are not "
                               "counted on one stream")
            sp["tile"] = (tile.x, tile.y)
            sp["draws"] = self.eng.rng.draws - sp["entry"]
        return self.world.create_entity(script, tile=tile)

    def _on_spawn_player(self, this, original):
        """The origin's onSpawnPlayer, counted: the draws from here to the first World.spawnEntity and the
        World.isValidTileSquare calls in between (one per iteration of Deserters' start loop)."""
        world = self.eng.World
        valid = world.d["isValidTileSquare"]          # the HexMap's, put there by resizeScene
        sp = self._spawn = {"rng": self.eng.rng, "entry": self.eng.rng.draws, "loop": 0, "tile": None, "draws": None}
        tried = None
        if R.call(R.get(this, "getID"), this, ()) == DESERTERS:     # only its loop is known: the fort and its ranges
            rows, sx, sy = self._fort_script.invoke(self.eng.root, ())
            fort = fort_index([[bool(m), bool(i), bool(s)] for m, i, s, _x, _y in rows])
            if fort is not None:
                tried = StartLoop(loop_ranges((int(rows[fort][3]), int(rows[fort][4])), (int(sx), int(sy))))

        def counted(this, x, y):
            if sp["tile"] is None:
                sp["loop"] += 1
                if sp["loop"] > SPAWN_LOOP_CAP:
                    raise MapError("onSpawnPlayer's start loop ran past %d iterations without a square that passes "
                                   "(the game would not get past it either)" % SPAWN_LOOP_CAP)
                if tried is not None and tried.enter(x, y):
                    return False            # this square failed before: the same answer, without the checks
            return R.call(valid, this, (x, y))
        self._put(world, "isValidTileSquare", NativeFn(counted, "isValidTileSquare"))
        return R.call(original, this, ())

    def _on_scenario_init(self, this, *args):
        raise StopCampaign("spawn")

    # Draws are counted by the generator itself (rng.MT64.draws: every number Math.rand takes from the seeded
    # stream, whatever path of the native took it); re-seeding starts a new generator, so the old one's count
    # is added up first. Only a seeding with the campaign seed itself counts towards the stop: startNewCampaign
    # seeds with it before the map and again after it (a hook that seeds another string does not stop the run).
    def _on_seed_string(self, this, s):
        if s == self._seed:
            self._reseeds += 1
            if self._reseeds == 2 and self._stop_at in ("reseed", "spawn"):
                # the probe (PROBE_RANGE): one more draw from the map's stream, not counted in the run's draws
                # (a "spawn" run draws it too: the seeding right after it starts a new stream, so it changes nothing)
                rng = self.eng.rng
                before = rng.draws
                self._probe = R.call(self._rand, self.eng.Math, PROBE_RANGE)
                self._draws -= rng.draws - before
                if self._stop_at == "reseed":
                    raise StopCampaign("reseed")
                self._map_draws = self._draws + rng.draws
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
        Returns {"log": logInfo lines, "draws": seeded draws, "seconds", "stub_uses": this run's only}, and for
        stop_at="reseed" also "probe": the PROBE_RANGE draw at the stop (not counted in "draws"). stop_at="spawn" gives
        the same (its "draws" and "probe" are the map's: up to the second seeding) plus "start": {"tile": the square
        (x, y) of the first World.spawnEntity in onSpawnPlayer, "loop": World.isValidTileSquare calls from onSpawnPlayer's
        entry to it, "draws": seeded draws in between} (all None when onSpawnPlayer spawned nothing). The recruits are
        left on the player roster for the caller (Lab.world_map reads and clears them)."""
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
        self._probe = None
        self._spawn = None
        self._map_draws = None
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
            if stop_at == "spawn":
                # the origin's own onSpawnPlayer, counted, and a stop where startNewCampaign calls its onInit()
                original = R.get(scenario, "onSpawnPlayer")
                self._put(scenario, "onSpawnPlayer",
                          NativeFn(lambda this, *args: self._on_spawn_player(this, original), "onSpawnPlayer"))
                self._put(scenario, "onInit", NativeFn(self._on_scenario_init, "onInit"))
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
        out = {"log": log, "draws": draws, "seconds": seconds, "stub_uses": stubs}
        if stop_at in ("reseed", "spawn"):
            out["probe"] = self._probe
        if stop_at == "spawn":
            out["draws"] = self._map_draws
            sp = self._spawn
            if sp is None or sp["tile"] is None:
                out["start"] = {"tile": None, "loop": None, "draws": None}
            else:
                out["start"] = {"tile": sp["tile"], "loop": sp["loop"], "draws": sp["draws"]}
        self._spawn = None
        return out

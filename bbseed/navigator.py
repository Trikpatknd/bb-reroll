"""The world navigator: `::World.getNavigator()`, the engine's path finder on the world map.

The map generator asks it two kinds of question:
- is there a route between two tiles at all (`findPath(...).isEmpty()`): where a settlement may stand
  (buildSettlements), whether an attached location or a fortress can be reached, which settlements are
  connected (settlement.updateProperties) and whether a coastal one reaches the deep sea;
- which tiles the route takes (`getSize` / `getCurrent` / `pop`): buildRoads and buildAdditionalRoads lay their
  roads along it (the game's own search, copied: see below).

What is promised (stage 1 of the map search): `isEmpty()` is true exactly when no route exists. A route is a
chain of neighbouring tiles from the start to the goal in which every tile after the start can be entered:
its `ActionPointCosts[tile.Type]` is a finite number > 0, and with `RoadOnly` it has a road. The reasons:
- 0 blocks: `Const.World.TerrainTypeNavCost_Flat` gives the ocean 0 and every land type 10, and
  `TerrainTypeNavCost_Ship` gives every land type 0. If 0 were a free step, ships would cross land and flat
  routes would cross the sea, so the checks that use them (coastal settlements, the deep-sea tile of a port,
  attached locations) could never fail.
- inf blocks: `TerrainTypeNavCost` is 10 / TerrainTypeSpeedMult, which is 10 / 0.0 = inf for the ocean. The
  non-coastal settlement check uses it and means "connected by land".
- a negative cost blocks (the plan's wording; no script table has one).
- the start tile is never entered, so its own cost does not matter: a port's deep-sea route starts on its
  (land) settlement tile, which the ship table blocks, and the game does have ports.
- an occupied tile (IsOccupied: a town, an attached location, an occupied mountain, a house tile) can be entered
  and passed like any other; only the cost table and RoadOnly block. MEASURED in the game (map-search Task 7,
  40 maps; questions chosen on each map, bb_seedlab MODLOG "CHECKPOINT B"): findPath(S, G).isEmpty() was false in
  158 of 158 cases where the only route from S to G led through an occupied tile (only that tile's and G's
  terrain types enterable; towns 40, locations 38, mountains 40, house tiles 40), true in 43 of 43 controls with
  the occupied tile's type blocked as well (an infinite cost blocks a type), and false in 160 of 160 routes whose
  goal was the occupied tile itself. isEmpty() depends on it: buildSettlements' checks route through earlier
  towns and end on one, a coastal town's deep-sea route (findAccessibleOceanEdge) passes earlier harbours, and
  the attached-location and fortress checks pass other locations.
- the terrain types: `Const.World.TerrainType.COUNT` is 19 in the base game and 21 with Legends (SwampGreen 19,
  SwampForest 20), but the cost tables the scripts hand over (`TerrainTypeNavCost`, `_Flat`, `_Ship`) have 19 entries
  (MEASURED, Legends 19.4.22: the base game builds them from its own 19-entry speed table before Legends replaces it)
  and the 18-entry table of buildAdditionalRoads lacks the 19th type (Oasis, on every map). A type past the end of a
  table is NOT blocked: the settings object starts with every one of its 32 entries at 2 (the exe's createSettings,
  0x4ea2b0) and assigning an array writes only its own entries, so such a type costs 2 (MEASURED: buildAdditionalRoads'
  roads cross Oasis tiles in the game; with Oasis blocked no stop grid of the 80 maps matched, with cost 2 the
  Vanilla grids match 40 of 40). Whether a tile of a type Legends adds (past the 19 entries) can be entered
  follows from the same default (cost 2, by the exe's code alone), but none of the 40 maps of Checkpoint B has one
  (bb_seedlab MODLOG) and neither has any of 3 more maps checked when this rule was added; a question asked on a
  map that does have one still raises NavError (not modelled) instead of guessing.
Reachability does not depend on how the engine searches, so it is answered from connected components (cached
until a tile's Type or road changes), which costs nothing per question.

WHICH tiles a route takes (`astar`) is the game's own search, copied from the GOG exe (Battle Brothers 1.5.2.3,
win32\\BattleBrothers.exe, DRM-free, read statically; addresses below are that exe's, image base 0x400000; the
disassembly and the Python copy bb_seedlab `tools/nav_exe.py` carry the evidence). It is not always the cheapest route,
and its tie choices decide the roads. `WorldNavigator::findPath` is
0x4ea430 (the Squirrel binding 0x4ebe5c -> 0x4ea3e0), the whole search inline:
- coordinates are Coords (X, Y) = (x, y - x/2); a tile exists when 0 <= X < W and 0 <= Y + X/2 < H (0x4ea80a..0x4ea850);
- the cost table is the settings' ints times 10 (0x4ea530); a step INTO tile t costs trunc(float32(cost10[Type]) * m),
  m = RoadMult (float32) on a road tile (the exe's byte +0x1e: RoadDirections != 0), else the plain cost10 (0x4ea933..
  0x4ea988); g is an int sum of steps; a cost of 0 blocks the tile (it is marked closed);
- f = g + 20 * h, h = hex distance max(|dX|, |dY|, |dX + dY|) to the goal (0x4ea9ef; the heuristic is the grid's
  virtual slot 0x552680, found by elimination, not traced from the constructor): f overestimates a road step (20 > 15
  for buildRoads), so the route is not always the cheapest;
- the open list is a std::vector of nodes kept as an MSVC binary heap on `a.f > b.f` alone (0x4c4fa0; push_heap
  0x4cc580, pop_heap hole 0x4cc4f0, make_heap 0x4cc310): a new node is pushed, a better g for a node that is already open
  updates g, f, parent and direction in place and calls make_heap on the whole vector (0x4eaaa4..0x4eaad1, strict <).
  Nothing else breaks ties, so the heap's own sifting does (`_heap_*` copy it);
- a popped node expands its neighbours in the order (X, Y+1), (X, Y-1), (X+1, Y), (X-1, Y+1), (X-1, Y), (X+1, Y-1)
  (six unrolled blocks 0x4ea7d3, 0x4eaaeb, 0x4eadef, 0x4eb0fe, 0x4eb403, 0x4eb712), skipping the step back to the
  node's parent; per neighbour: the goal tile ends the search AT ONCE (before the closed and cost checks: its own cost is
  never read, the goal is never pushed), closed -> skip, cost 0 -> mark closed and skip, then g / push / improve; the
  popped node is then closed (0x4eba17..0x4eba5d); an empty heap is "no route"; the route is the goal, then the popped
  node and its parents up to (not including) the start (0x4ebab0..0x4ebb79). The flags are cleared on every call.
MEASURED (bb_seedlab MODLOG "NAVIGATOR FROM THE EXE", 2026-10-25; 80 maps, every buildRoads call the game made, logged
route by route): buildRoads' settings (StopAtRoad false, RoadOnly false, HeatCost 0, maximum 0, RoadMult 0.15, its
19-entry table) give the game's tiles in Legends 2070 of 2070 non-empty calls and Vanilla 1646 of 1646, and the same
empty / non-empty answer in 2354 of 2354 and 1890 of 1890 calls (the component rule of `isEmpty()` agrees on all of them
too). Left out, each rule load-bearing: neighbour order reversed 1295 / 1026 exact, h weight 10 1334 / 1067, h 0 1198 /
955.
UNVERIFIED by any route log (buildAdditionalRoads' routes are not logged; the lab's gate 2 tests them indirectly
through the finished roads, the stop RoadDirections grid): buildAdditionalRoads' route tiles use this same search with
RoadMult 0.25 (a road step on cost-10 land is trunc(100 * 0.25) = 25) and its 18-entry table. MEASURED 2026-10-25
through the finished grids: the stop RoadDirections equal the game's on 40 of 40 Vanilla maps and 40 of 40 Legends maps
(the lab built each Legends map with the game batch's black-market session counter: 0 for the first campaign of a game
session, 2 for every later one; with the counter at 0 for every job only 16 of 40 matched, because refineSettlements
then places other attached locations).
Not modelled (NavError when the tiles are asked for; no map script asks): RoadOnly and StopAtRoad (0x4ea88d: the first
generated road tile ends the search), a maximum (0x4ea92a), HeatCost, and a cost table entry that is not a whole number
(the exe's table holds ints; how its setter takes 2.5 is not read). A blocked type here is the cost table rule above
(0, negative, inf, not a number, past the table), the exe blocks only a zero: a negative entry is not in any script table.
The exe and `isEmpty()` differ in places no logged buildRoads goal reached (none had cost 0 or Type 0): the exe never
reads the goal tile's cost (it accepts a goal when an expanded node is next to it, even a blocked one) and answers
"empty" up front for a goal of Type 0 with maximum 0, while the component rule blocks every goal whose entry is not
enterable. `isEmpty()` stays the component rule (it is exact for the questions the generator asks, MEASURED, Checkpoint
B), and a path the component rule calls empty has no tiles. buildAdditionalRoads does ask for the tiles of goals of a
blocked type (attached locations on mountains, cost 0): the exe would route to them; trying that in the lab changed no
Legends grid (16 of 40 equal with and without, before the counter was set; all 40 match without it), so it is not modelled.
`Navigator.route_override` is a hook for the lab's road fitting (bb_seedlab `tools/road_fit.py`): it may supply route
tiles from outside; unset, nothing changes.
"""
import math
import struct

from .hexmap import NotModelled
from .sq import runtime as R
from .sq.runtime import NativeFn, SqError, SqNative, tostring

# The settings fields the scripts write (`navSettings.X = ...`), with the defaults an unwritten field has.
# UNVERIFIED defaults; the generator writes every field it relies on except RoadOnly / RoadMult / HeatCost.
DEFAULTS = {
    "ActionPointCosts": None,
    "RoadMult": 1.0,             # cost factor on a road tile (buildRoads 0.15, buildAdditionalRoads 0.25)
    "RoadOnly": False,           # only road tiles (settlement.updateProperties: ConnectedToByRoads)
    "StopAtRoad": False,         # buildRoads / buildAdditionalRoads set it to false
    "HeatCost": 0,               # the world AI's orders only; a non-zero value is not modelled
    "AllowZoneOfControl": False,  # tactical only
}


class NavError(NotModelled):
    """A navigator question the lab cannot answer the way the engine would (mapgen turns it into MapError)."""


class Settings(SqNative):
    """What createSettings() hands out: a plain record of the fields above."""

    def __init__(self):
        self.fields = dict(DEFAULTS)
        self.addr = R.new_addr()

    def sq_get(self, key):
        if key in self.fields:
            return self.fields[key]
        raise SqError("the index '%s' does not exist" % tostring(key))

    def sq_set(self, key, value):
        if key not in self.fields:
            raise SqError("the index '%s' does not exist" % tostring(key))
        self.fields[key] = value


TABLE_DEFAULT = 2           # createSettings (0x4ea2b0) fills all 32 entries of ActionPointCosts with 2; assigning a shorter
#                             array writes only its own entries, so a type past the end costs 2 (MEASURED: buildAdditionalRoads'
#                             18-entry table has no entry for Oasis, and its roads cross Oasis tiles in the game)
BASE_TYPES = 19             # the base game's Const.World.TerrainType.COUNT (Legends makes it 21)


def terrain_count(engine):
    """Const.World.TerrainType.COUNT of the scripts the engine loaded (21 with Legends). BASE_TYPES when there is no
    such table: no engine, or a bare one without scripts (the unit tests); a count that is not a whole number of at
    least BASE_TYPES is not modelled."""
    count = None
    if engine is not None:
        count = engine.root
        for key in ("Const", "World", "TerrainType", "COUNT"):
            count = count.get(key) if type(count) is R.SqTable else None
    if count is None:
        return BASE_TYPES
    if type(count) is not int or count < BASE_TYPES:
        raise NavError("Const.World.TerrainType.COUNT is %s (not modelled: a whole number of %d or more)" % (
            tostring(count), BASE_TYPES))
    return count


def _blocked_types(costs, ntypes):
    """The terrain types a cost table does not let a route enter (see the module text)."""
    if not isinstance(costs, list):
        raise NavError("findPath: ActionPointCosts is %s, not an array" % R.typeof(costs))
    out = []
    for t in range(ntypes):
        c = costs[t] if t < len(costs) else TABLE_DEFAULT      # past the end: the settings' own default (see TABLE_DEFAULT)
        if type(c) not in (int, float) or not c > 0 or c == math.inf:
            out.append(t)
    return frozenset(out)


# ---------------------------------------------------------------- the game's search (see the module text)
_F32 = struct.Struct("<f")
H_WEIGHT = 20               # f = g + 20 * h (0x4eaa01)
COST_SCALE = 10             # the cost table x 10 (0x4ea530)
# the six unrolled neighbour blocks of 0x4ea430: (dX, dY in Coords, the direction stored in the new node, the popped
# node's direction that skips this block: the step back to the parent)
_BLOCKS = (
    (0, 1, 0, 3),           # 0x4ea7d3
    (0, -1, 3, 0),          # 0x4eaaeb
    (1, 0, 1, 4),           # 0x4eadef
    (-1, 1, 5, 2),          # 0x4eb0fe
    (-1, 0, 4, 1),          # 0x4eb403
    (1, -1, 2, 5),          # 0x4eb712
)


def _f32(x):
    return _F32.unpack(_F32.pack(x))[0]


class _Node:
    __slots__ = ("f", "g", "tile", "X", "Y", "parent", "dir")


def _trunc_div2(v):
    return int(v / 2) if v < 0 else v >> 1             # C's v / 2 (cdq; sub eax, edx; sar eax, 1)


def _heap_push(a, hole, top, val):
    """0x4cc580 std::_Push_heap_by_index: the value climbs while its parent's f is larger (strict)."""
    idx = _trunc_div2(hole - 1)
    while top < hole and a[idx].f > val.f:
        a[hole] = a[idx]
        hole = idx
        idx = _trunc_div2(hole - 1)
    a[hole] = val


def _heap_sift(a, hole, bottom, val):
    """0x4cc4f0 std::_Pop_heap_hole_by_index: the hole sinks to the child with the smaller f (the right one on a
    tie), then the value climbs from there."""
    top = hole
    idx = hole
    max_non_leaf = _trunc_div2(bottom - 1)
    while idx < max_non_leaf:
        idx = 2 * idx + 2
        if a[idx].f > a[idx - 1].f:
            idx -= 1
        a[hole] = a[idx]
        hole = idx
    if idx == max_non_leaf and bottom % 2 == 0:
        a[hole] = a[bottom - 1]
        hole = bottom - 1
    _heap_push(a, hole, top, val)


def _heap_pop(a):
    """0x4ea786..0x4ea7d0: top = a[0]; with 2+ elements val = last, last = top, sift the hole from 0 over size - 1."""
    top = a[0]
    if len(a) >= 2:
        val = a[-1]
        a[-1] = top
        _heap_sift(a, 0, len(a) - 1, val)
    a.pop()
    return top


def _heap_make(a):
    """0x4cc310 std::make_heap."""
    n = len(a)
    if n >= 2:
        hole = n >> 1
        while hole > 0:
            hole -= 1
            _heap_sift(a, hole, n, a[hole])


class Path(SqNative):
    """A found route: the tiles after the start, up to and including the goal (MEASURED, see the module text).
    `getCurrent()` is the next tile's Coords, `pop()` drops it."""

    def __init__(self, nav, found, compute):
        self.nav = nav
        self.found = found              # isEmpty() is `not found`, known without the tiles
        self._compute = compute         # -> list of tiles, only run when the scripts ask for them
        self._tiles = None
        self._pos = 0
        self.addr = R.new_addr()

    def tiles(self):
        if self._tiles is None:
            self._tiles = self._compute() if self.found else []
        return self._tiles

    def sq_get(self, key):
        fn = _PATH_FN.get(key)
        if fn is None:
            raise SqError("the index '%s' does not exist" % tostring(key))
        return fn

    def isEmpty(self, this):
        return not self.found

    def getSize(self, this):
        return len(self.tiles()) - self._pos

    def getCurrent(self, this):
        tiles = self.tiles()
        if self._pos >= len(tiles):
            raise NavError("Path.getCurrent() on a path with no tile left (not modelled)")
        return tiles[self._pos]._coords()

    def pop(self, this):
        if self._pos >= len(self.tiles()):
            raise NavError("Path.pop() on a path with no tile left (not modelled)")
        self._pos += 1


def _path_fn(name):
    method = getattr(Path, name)
    return NativeFn(lambda this, *args: method(this, this, *args), name)


_PATH_FN = {name: _path_fn(name) for name in ("isEmpty", "getSize", "getCurrent", "pop")}


class Navigator(SqNative):
    """::World.getNavigator() on the world map. `hexmap`: the tile world (bbseed.hexmap.HexMap)."""

    def __init__(self, hexmap, ntypes=BASE_TYPES):
        self.hexmap = hexmap
        self.ntypes = ntypes            # Const.World.TerrainType.COUNT (terrain_count(engine))
        # Callable(start, goal, info) -> list of tiles or None: the lab's road-fitting hook (bb_seedlab tools/road_fit.py)
        # replays the game's logged routes; None (the default) keeps the A* route
        self.route_override = None
        self.addr = R.new_addr()
        # (blocked types, road only) -> (the tile world's versions it was made at, {tile: component number})
        self._components = {}
        self.searches = 0               # A* runs (for the bench)
        self.questions = 0              # findPath calls
        self.fns = {name: NativeFn(getattr(self, name), name) for name in ("createSettings", "findPath")}

    def sq_get(self, key):
        fn = self.fns.get(key)
        if fn is None:
            raise SqError("the index '%s' does not exist" % tostring(key))
        return fn

    def createSettings(self, this, *args):
        return Settings()

    # ------------------------------------------------------------------ reachability
    def _component_map(self, blocked, road_only, lacking=frozenset()):
        """The connected parts of the tiles a route may enter. Made again only when a tile's Type changed (or, for
        RoadOnly, its roads): the road builder's many RoadDirections writes leave the other answers cached.
        IsOccupied plays no part (MEASURED, see the module text), so the cache does not watch it.
        lacking: the types of Legends' that the cost table has no entry for (see findPath): a tile of one of them is
        not modelled."""
        hm = self.hexmap
        version = (hm.type_version, hm.road_version) if road_only else hm.type_version
        key = (blocked, road_only, lacking)
        made = self._components.get(key)
        if made is not None and made[0] == version:
            return made[1]
        comp = {}
        n = 0
        for t in hm.tiles:
            if lacking and t.Type in lacking:       # (such a type is blocked: no search reaches the tile)
                raise NavError("a tile of terrain type %s has no entry in the cost table (not modelled)" % t.Type)
            if t in comp or t.Type in blocked or (road_only and not t.RoadDirections):
                continue
            n += 1
            comp[t] = n
            stack = [t]
            while stack:
                u = stack.pop()
                for v in u.nb:
                    if v is not None and v not in comp and v.Type not in blocked \
                            and (not road_only or v.RoadDirections):
                        comp[v] = n
                        stack.append(v)
        self._components[key] = (version, comp)         # (not before: a NavError above must not leave a half map)
        return comp

    def reachable(self, start, goal, blocked, road_only, lacking=frozenset()):
        comp = self._component_map(blocked, road_only, lacking)
        g = comp.get(goal)
        if g is None:                   # the goal cannot be entered
            return False
        if comp.get(start) == g:
            return True
        for n in start.nb:              # the start itself is never entered
            if n is not None and comp.get(n) == g:
                return True
        return False

    # ------------------------------------------------------------------ findPath
    def findPath(self, this, start, goal, settings, max_cost=0, *rest):
        self.questions += 1
        if rest:
            raise NavError("findPath with %d extra arguments (not modelled)" % len(rest))
        if not isinstance(settings, Settings):
            raise NavError("findPath: the settings are a %s, not createSettings()'s" % R.typeof(settings))
        f = settings.fields
        if max_cost not in (0, 0.0):
            raise NavError("findPath with a maximum of %s (not modelled)" % tostring(max_cost))
        if f["HeatCost"] not in (0, 0.0, None, False):
            raise NavError("findPath with HeatCost %s (not modelled)" % tostring(f["HeatCost"]))
        if start is goal:
            raise NavError("findPath from a tile to itself (not modelled)")
        blocked = _blocked_types(f["ActionPointCosts"], self.ntypes)
        # the types Legends adds (past the base game's 19) that this table has no entry for: nothing is known about
        # entering such a tile, so a map that has one cannot be answered (module text)
        lacking = frozenset(t for t in range(BASE_TYPES, self.ntypes) if t >= len(f["ActionPointCosts"]))
        road_only = bool(f["RoadOnly"])
        found = self.reachable(start, goal, blocked, road_only, lacking)
        costs = list(f["ActionPointCosts"])
        road_mult = float(f["RoadMult"])
        stop_at_road = bool(f["StopAtRoad"])

        def compute():
            # route_override (the lab's road-fitting hook, see the module text) supplies the route when it returns a list
            if self.route_override is not None:
                info = {"costs": costs, "blocked": blocked, "road_only": road_only, "road_mult": road_mult, "nav": self}
                route = self.route_override(start, goal, info)
                if route is not None:
                    return list(route)
            route = self.astar(start, goal, costs, blocked, road_only, road_mult, stop_at_road)
            if not route:
                raise NavError("the game's search found no route although the components say there is one")
            return route

        return Path(self, found, compute)

    def astar(self, start, goal, costs, blocked, road_only, road_mult, stop_at_road=False):
        """WorldNavigator::findPath 0x4ea430, the rules of the module text: the tiles after the start, the goal last.
        `costs` is the settings' table, `blocked` the types `_blocked_types` found (a blocked type costs 0 here, the exe's
        "cannot be entered"). RoadOnly and StopAtRoad route requests are not modelled (NavError), and so is a cost entry
        that is not a whole number (the exe's table holds ints; how its setter takes 2.5 is not read)."""
        if road_only or stop_at_road:
            raise NavError("route tiles with %s (not modelled: no map script asks for them)" % (
                "RoadOnly" if road_only else "StopAtRoad"))
        self.searches += 1
        hm = self.hexmap
        width, height, cols = hm.size_x, hm.size_y, hm.cols
        cost10 = [TABLE_DEFAULT * COST_SCALE] * 32
        for t in range(min(32, len(costs))):
            c = costs[t]
            cost10[t] = 0
            if t in blocked:
                continue
            if c != int(c):
                raise NavError("route tiles with a cost table entry of %s (not modelled: the exe's table holds ints)" % c)
            cost10[t] = int(c) * COST_SCALE
        mult = _f32(road_mult)
        gX, gY = goal.x, goal.y - (goal.x >> 1)
        sX, sY = start.x, start.y - (start.x >> 1)
        first = _Node()
        first.f = first.g = 0
        first.tile, first.X, first.Y, first.parent, first.dir = start, sX, sY, None, 6
        nodes = {start: first}
        open_ = {start}
        closed = set()
        heap = [first]
        found = False
        cur = first
        while heap:
            cur = _heap_pop(heap)
            cX, cY = cur.X, cur.Y
            for dX, dY, d, skip in _BLOCKS:
                if cur.dir == skip:
                    continue
                X, Y = cX + dX, cY + dY
                if X < 0 or X >= width:
                    continue
                half = X >> 1
                if Y < -half or Y >= height - half:
                    continue
                t = cols[X][Y + half]
                if t is goal:
                    found = True
                    break
                if t in closed:
                    continue
                c10 = cost10[t.Type] if t.Type < 32 else 0
                if c10 == 0:
                    closed.add(t)
                    continue
                dX2, dY2 = gX - X, gY - Y
                h = max(abs(dX2 + dY2), abs(dY2), abs(dX2))
                # HeatCost is 0 here (findPath raises otherwise): the step is the cost, times RoadMult on a road tile
                g = cur.g + (int(_f32(float(c10) * mult)) if t.RoadDirections else c10)
                if t not in open_:
                    n = _Node()
                    n.g, n.f, n.tile, n.X, n.Y, n.parent, n.dir = g, g + H_WEIGHT * h, t, X, Y, cur, d
                    nodes[t] = n
                    heap.append(n)
                    _heap_push(heap, len(heap) - 1, 0, n)
                    open_.add(t)
                else:
                    n = nodes[t]
                    if g < n.g:
                        n.g, n.parent, n.dir, n.f = g, cur, d, g + H_WEIGHT * h
                        _heap_make(heap)
            if found:
                break
            closed.add(cur.tile)
            open_.discard(cur.tile)
        if not found:
            return []                   # the exe's empty path (compute() calls it a contradiction)
        tiles = [goal]
        n = cur
        while n.parent is not None:
            tiles.append(n.tile)
            n = n.parent
        tiles.reverse()
        return tiles

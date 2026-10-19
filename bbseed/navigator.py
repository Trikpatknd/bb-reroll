"""The world navigator: `::World.getNavigator()`, the engine's path finder on the world map.

The map generator asks it two kinds of question:
- is there a route between two tiles at all (`findPath(...).isEmpty()`): where a settlement may stand
  (buildSettlements), whether an attached location or a fortress can be reached, which settlements are
  connected (settlement.updateProperties) and whether a coastal one reaches the deep sea;
- which tiles the route takes (`getSize` / `getCurrent` / `pop`): buildRoads and buildAdditionalRoads lay their
  roads along it.

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
Reachability does not depend on how the engine searches, so it is answered from connected components (cached
until a tile's Type or road changes), which costs nothing per question.

Not promised: WHICH tiles a route takes. That is a plain A* (cost of entering a tile = its ActionPointCosts entry,
times RoadMult on a road tile; neighbours in direction order; ties to the earlier found) and is marked
UNVERIFIED: stage 2 copies the game's A*. The roads, and so everything the generator draws after
buildRoads, depend on it (map-search Task 5 report).
"""
import heapq
import math

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


def _blocked_types(costs, ntypes):
    """The terrain types a cost table does not let a route enter (see the module text)."""
    if not isinstance(costs, list):
        raise NavError("findPath: ActionPointCosts is %s, not an array" % R.typeof(costs))
    out = []
    for t in range(ntypes):
        c = costs[t] if t < len(costs) else None      # UNVERIFIED: a type past the end of the table is blocked
        if type(c) not in (int, float) or not c > 0 or c == math.inf:
            out.append(t)
    return frozenset(out)


class Path(SqNative):
    """A found route: the tiles after the start, up to and including the goal (UNVERIFIED: stage 2 copies the
    game's A*). `getCurrent()` is the next tile's Coords, `pop()` drops it."""

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
        # UNVERIFIED: stage 2 copies the game's A*
        return len(self.tiles()) - self._pos

    def getCurrent(self, this):
        # UNVERIFIED: stage 2 copies the game's A*
        tiles = self.tiles()
        if self._pos >= len(tiles):
            raise NavError("Path.getCurrent() on a path with no tile left (not modelled)")
        return tiles[self._pos]._coords()

    def pop(self, this):
        # UNVERIFIED: stage 2 copies the game's A*
        if self._pos >= len(self.tiles()):
            raise NavError("Path.pop() on a path with no tile left (not modelled)")
        self._pos += 1


def _path_fn(name):
    method = getattr(Path, name)
    return NativeFn(lambda this, *args: method(this, this, *args), name)


_PATH_FN = {name: _path_fn(name) for name in ("isEmpty", "getSize", "getCurrent", "pop")}


class Navigator(SqNative):
    """::World.getNavigator() on the world map. `hexmap`: the tile world (bbseed.hexmap.HexMap)."""

    def __init__(self, hexmap, ntypes=19):
        self.hexmap = hexmap
        self.ntypes = ntypes            # Const.World.TerrainType.COUNT
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
    def _component_map(self, blocked, road_only):
        """The connected parts of the tiles a route may enter. Made again only when a tile's Type changed (or, for
        RoadOnly, its roads): the road builder's many RoadDirections writes leave the other answers cached."""
        hm = self.hexmap
        version = (hm.type_version, hm.road_version) if road_only else hm.type_version
        key = (blocked, road_only)
        made = self._components.get(key)
        if made is not None and made[0] == version:
            return made[1]
        comp = {}
        self._components[key] = (version, comp)
        n = 0
        for t in hm.tiles:
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
        return comp

    def reachable(self, start, goal, blocked, road_only):
        comp = self._component_map(blocked, road_only)
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
        road_only = bool(f["RoadOnly"])
        found = self.reachable(start, goal, blocked, road_only)
        costs = list(f["ActionPointCosts"])
        road_mult = float(f["RoadMult"])
        return Path(self, found, lambda: self.astar(start, goal, costs, blocked, road_only, road_mult))

    def astar(self, start, goal, costs, blocked, road_only, road_mult):
        """UNVERIFIED: stage 2 copies the game's A*. The cheapest route by the cost table (a road tile costs
        RoadMult times as much), the start left out, the goal last."""
        self.searches += 1
        hm = self.hexmap
        cheapest = min(float(costs[t]) for t in range(self.ntypes) if t not in blocked and t < len(costs))
        h_step = cheapest * min(1.0, road_mult)
        dist = hm.distance
        g = {start: 0.0}
        came = {}
        order = 0
        heap = [(dist(start, goal) * h_step, order, start)]
        closed = set()
        while heap:
            _f, _o, u = heapq.heappop(heap)
            if u is goal:
                break
            if u in closed:
                continue
            closed.add(u)
            gu = g[u]
            for v in u.nb:
                if v is None or v in closed or v.Type in blocked or (road_only and not v.RoadDirections):
                    continue
                c = float(costs[v.Type])
                if v.RoadDirections:
                    c *= road_mult
                gv = gu + c
                if gv < g.get(v, math.inf):
                    g[v] = gv
                    came[v] = u
                    order += 1
                    heapq.heappush(heap, (gv + dist(v, goal) * h_step, order, v))
        if goal not in came:
            raise NavError("A* found no route although the components say there is one")
        tiles = []
        t = goal
        while t is not start:
            tiles.append(t)
            t = came[t]
        tiles.reverse()
        return tiles

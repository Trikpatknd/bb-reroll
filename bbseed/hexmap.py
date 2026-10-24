"""The tile world of the world map generator: a grid of hex tiles the scripts read and write.

Stand-in for the engine's `::World` tile natives (getTileSquare, getNextTile, ...). Pure geometry and
bookkeeping: no RNG, no drawing. Tiles are plain Python objects; a script reaches a field through
`Tile.sq_get` and a method through the shared `NativeFn` of the same name, so one map costs about as
many dict look-ups as the script makes calls. The neighbours of every tile are linked once, when the
grid is built.

Layout: flat-topped hexes in columns, the game's directions `N=0 NE=1 SE=2 S=3 SW=4 NW=5`
(`Const.Direction`). Whether the odd or the even columns are the ones shifted half a row, and whether
`N` is `y-1` or `y+1`, is MEASURED against the game in Task 4 of the map-search plan, never guessed:
`layout` is a constructor parameter, and the four candidates are `LAYOUTS`.
"""
import math
from operator import attrgetter

from .sq import runtime as R
from .sq.runtime import MISSING, NativeFn, SqError, SqNative, f32, tostring

LAYOUTS = ("odd-q-down", "odd-q-up", "even-q-down", "even-q-up")

# Neighbour offsets (dx, dy) in the order N NE SE S SW NW. "Down": N is y-1, and a SHIFTED column sits
# half a row lower than an unshifted one.
_DOWN = (
    ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1)),      # unshifted column
    ((0, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)),        # shifted column
)
# The four layouts: (parity of the shifted columns, sign of y). "up" mirrors the y offsets (N is y+1);
# "even" swaps which column parity uses which row of the table.
_LAYOUT = {"odd-q-down": (1, 1), "odd-q-up": (1, -1), "even-q-down": (0, 1), "even-q-up": (0, -1)}
_OFFSETS = {name: tuple(tuple((dx, ysign * dy) for dx, dy in _DOWN[1 if parity == shifted else 0])
                        for parity in (0, 1))                       # indexed by the column's parity
            for name, (shifted, ysign) in _LAYOUT.items()}

# What one step in each direction does to a tile's axial (q, r) in every layout.
_AXIAL = ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 1), (-1, 0))
_DIRECTION_OF = {delta: d for d, delta in enumerate(_AXIAL)}
_SQRT3 = math.sqrt(3.0)

# Tile.Pos, MEASURED in the game (map-search Task 7, Checkpoint B: 13 tiles x 40 maps, no exception):
#   Pos = (120 + 180 * x, 60 + 120 * y + 60 if x is odd)      (x, y: the tile's square coordinates)
# A hex lattice stretched sideways: columns 180 apart, rows 120 apart, the odd columns half a row higher (the even
# columns sit lower, as in the measured layout). World.worldToTile(tile.Pos) gave the tile's Coords on all of them.
# The only reader on the map's path is buildLabels (it averages Pos and converts the average back with worldToTile),
# after buildRoads.
POS_X0, POS_DX = 120.0, 180.0
POS_Y0, POS_DY = 60.0, 120.0

_ADDR_BASE = 0x60000000         # tile addresses come from the tile number, so building a map leaves
#                                 the interpreter's address counter (R.new_addr) alone


class MapError(Exception):
    """A map run went somewhere the lab cannot follow. Not an SqError: no script's try/catch hides it."""


class NotModelled(MapError):
    """The run reached a native (or a case of one) the lab does not model."""


class Vec(SqNative):
    """An engine `{X, Y}` value (Coords, SquareCoords, Pos, getMapSize())."""

    __slots__ = ("X", "Y", "addr")

    def __init__(self, x, y):
        self.X = x
        self.Y = y
        self.addr = R.new_addr()

    def sq_get(self, key):
        if key == "X":
            return self.X
        if key == "Y":
            return self.Y
        raise SqError("the index '%s' does not exist" % tostring(key))

    def sq_set(self, key, value):
        if key == "X":
            self.X = value
        elif key == "Y":
            self.Y = value
        else:
            raise SqError("the index '%s' does not exist" % tostring(key))

    def __repr__(self):
        return "Vec(%r, %r)" % (self.X, self.Y)


def _to_int(v):
    """A tile number the way a native takes it: integers, and floats cut to integers."""
    if type(v) is int:
        return v
    if type(v) is float:
        return int(v)
    raise SqError("wrong type for a tile coordinate: " + R.typeof(v))


class Tile(SqNative):
    """One world tile. Script-visible fields are the plain attributes named in `_PLAIN`; the methods
    take the NativeFn calling convention `(self, this, *args)`: `this` is the object the script called
    the method on (the tile itself), tests pass None."""

    __slots__ = ("x", "y", "q", "r", "ID", "addr", "nb", "hm",
                 "Type", "Subregion", "Level", "TacticalType", "IsOccupied",
                 "IsMarkedForImpassableTerrain", "Region", "RoadDirections", "IsFlipped", "HeatFromSettlements",
                 "brush", "props", "_sq", "_co", "_pos")

    def __init__(self, hm, x, y, q, r, tile_id):
        self.hm = hm
        self.x = x                  # square (offset) coordinates
        self.y = y
        self.q = q                  # axial coordinates: q is the column, r the row along the column's slant
        self.r = r
        # The game's tile ID is an address-like number (1095924616 for (0, 0) in one campaign, another number in the
        # next: map-search Task 7); the map's scripts use it for identity only (`ID != ID`, `array.find(tile.ID)`).
        # Here: y * width + x, unique, which is all the scripts can tell.
        self.ID = tile_id
        self.addr = _ADDR_BASE + 0x40 * tile_id
        self.nb = None              # the six neighbours (None at the border), set by HexMap
        self._sq = self._co = self._pos = None
        self.reset_state()

    def reset_state(self):
        """A tile as the engine hands it out (UNVERIFIED defaults: all zero)."""
        self.Type = 0
        self.Subregion = 0
        self.Level = 0
        self.TacticalType = 0
        self.IsOccupied = False
        self.IsMarkedForImpassableTerrain = False
        self.Region = 0             # used by the generator's region pass (not in the brief's field list)
        self.RoadDirections = 0     # bit mask of Const.DirectionBit, written by the road builder
        self.IsFlipped = False      # tile_badlands.nut
        # UNVERIFIED default 0: Legends' refineSettlements and entity_manager.updateSettlementHeat add
        # (6 - d) to it for every tile within 6 of a settlement, and Legends' loop does not zero it first
        self.HeatFromSettlements = 0
        self.brush = None
        self.props = None

    # ------------------------------------------------------------------ script access
    def sq_get(self, key):
        g = _GET.get(key)
        if g is not None:
            return g(self)
        m = _FN.get(key)
        if m is not None:
            return m
        raise SqError("the index '%s' does not exist" % tostring(key))

    def sq_find(self, key):
        g = _GET.get(key)
        if g is not None:
            return g(self)
        m = _FN.get(key)
        return MISSING if m is None else m

    def sq_set(self, key, value):
        if key in _SETTABLE:
            setattr(self, key, value)
            # the navigator's cached reachability is out of date
            if key == "Type":
                self.hm.type_version += 1
            elif key == "RoadDirections":
                self.hm.road_version += 1
        else:
            raise SqError("the index '%s' does not exist" % tostring(key))

    @property
    def HasRoad(self):
        """A tile has a road once the road builder gave it a direction. MEASURED from the scripts, not the
        engine: removeAutobahnkreuze (end of buildRoads), buildRoadSprites and the attached locations of
        refineSettlements all read HasRoad on tiles whose roads exist only as RoadDirections bits (the road
        details are spawned by buildRoadSprites, and only on tiles that already have HasRoad), so HasRoad
        cannot come from the details. MEASURED in the game (map-search Task 7): at the end of the map, HasRoad equals
        RoadDirections != 0 on every tile of 40 maps (952,000 tiles, 0 exceptions). Still UNVERIFIED: whether clear()
        of a road tile takes its road away (here it does not); the 40 maps show no tile where the two disagree."""
        return self.RoadDirections != 0

    def _square_coords(self):
        v = self._sq
        if v is None:
            v = self._sq = Vec(self.x, self.y)
        return v

    def _coords(self):
        """Coords: the engine's hex coordinates (X, Y) = (q, -q - r). Legends computes them itself
        (config/z_legends_hex.nut): neighbour offsets N (0,1) NE (1,0) SE (1,-1) S (0,-1) SW (-1,0) NW (-1,1),
        and `getHexFromSquareY(x, y) = y - x / 2` (integer division), which in the measured layout even-q-up
        is exactly Y here (N is y+1, the even columns sit lower); it hands them to World.getTile(X, Y) when it
        walks the rings around a settlement (updateSurroundingTileData). MEASURED in the game (map-search Task 7):
        13 tiles x 40 maps, Coords = (x, y - x / 2) on every one, World.getTile(Coords) gives the tile back and
        getDistanceTo agrees."""
        v = self._co
        if v is None:
            v = self._co = Vec(self.q, -self.q - self.r)
        return v

    def _properties(self):
        # UNVERIFIED: only tactical tiles' Properties are read by scripts; nothing in map generation uses it.
        p = self.props
        if p is None:
            from .engine import Stub
            p = self.props = Stub(self.hm.engine, "tile.Properties")
        return p

    # ------------------------------------------------------------------ methods
    def hasNextTile(self, this, d):
        return 0 <= d < 6 and self.nb[d] is not None

    def getNextTile(self, this, d):
        # UNVERIFIED: what the engine does for a direction without a tile; the scripts check hasNextTile first.
        return self.nb[d] if 0 <= d < 6 else None

    def getDistanceTo(self, this, other):
        dq = self.q - other.q
        dr = self.r - other.r
        return max(abs(dq), abs(dr), abs(dq + dr))

    def getDirectionTo(self, this, other):
        """Adjacent tiles: the direction between them. The same tile: not modelled (the engine may answer 6 =
        Const.Direction.COUNT, whose Const.DirectionBit entry is 0), an error. Further away: the direction of the
        60 degree sector the other tile lies in (UNVERIFIED). On the map's path (buildRoads, removeAutobahnkreuze,
        buildAdditionalRoads) only neighbours are asked: HexMap.far_directions counts the other calls, and it stayed
        0 in the replay of the logged generations (map-search Task 5)."""
        dq = other.q - self.q
        dr = other.r - self.r
        d = _DIRECTION_OF.get((dq, dr))
        if d is not None:
            return d
        if dq == 0 and dr == 0:
            raise NotModelled("Tile.getDirectionTo(the same tile)")
        self.hm.far_directions += 1
        angle = math.degrees(math.atan2(_SQRT3 * (dr + dq / 2.0), 1.5 * dq))
        return int(((angle + 120.0) % 360.0) // 60.0)

    def isSameTileAs(self, this, other):
        return self is other

    def getSurroundingTilesOfType(self, this, tile_type):
        n = 0
        for t in self.nb:
            if t is not None and t.Type == tile_type:
                n += 1
        return n

    def getSurroundingTilesNotOfType(self, this, tile_type):
        # UNVERIFIED: a missing neighbour (border) is not a tile, so it is not counted.
        n = 0
        for t in self.nb:
            if t is not None and t.Type != tile_type:
                n += 1
        return n

    def clear(self, this, mask=None):
        """Remove the details (decorations) of the given types, all of them without an argument. Nothing is
        drawn here and no script reads a detail back, so there is nothing to remove (HasRoad comes from
        RoadDirections, see HasRoad)."""

    def clearAllBut(self, this, *masks):
        """See clear()."""

    def setBrush(self, this, name):
        self.brush = name

    def resetBrush(self, this):
        self.brush = None

    def getBrush(self, this):
        # UNVERIFIED: a brush is its name (tile_highlands.nut compares getBrush() to a string); null without one.
        return self.brush

    def spawnDetail(self, this, brush=None, zlevel=0, detail_type=0, *rest):
        """Nothing is drawn: hands back a sprite stand-in the scripts can write to (Saturation, setBrightness...).
        A road detail does not make a road (see HasRoad)."""
        return self.hm.detail_sprite()

    def isSuitable(self, this, *args):
        # UNVERIFIED: the brief lists it; the scripts only call isSuitable on settlement types, never on a tile.
        return True

    def __repr__(self):
        return "Tile(%d, %d)" % (self.x, self.y)


_PLAIN = ("Type", "Subregion", "Level", "TacticalType", "IsOccupied", "IsMarkedForImpassableTerrain",
          "Region", "RoadDirections", "IsFlipped", "HeatFromSettlements")
_ROUTE_FIELDS = frozenset(("Type", "RoadDirections"))      # what the navigator's answers depend on
_GET = {name: attrgetter(name) for name in _PLAIN}
_GET["ID"] = attrgetter("ID")
_GET["HasRoad"] = lambda tile: tile.RoadDirections != 0     # read-only: no script assigns it
_GET["SquareCoords"] = Tile._square_coords
_GET["Coords"] = Tile._coords
_GET["Pos"] = lambda tile: tile.hm.pos_of(tile)
_GET["Properties"] = Tile._properties
_SETTABLE = frozenset(_PLAIN)

_METHODS = ("hasNextTile", "getNextTile", "getDistanceTo", "getDirectionTo", "isSameTileAs",
            "getSurroundingTilesOfType", "getSurroundingTilesNotOfType", "clear", "clearAllBut",
            "setBrush", "resetBrush", "getBrush", "spawnDetail", "isSuitable")


def _script_function(method):
    def fn(this, *args):
        return method(this, this, *args)
    return NativeFn(fn, method.__name__)


# One NativeFn per method name for all tiles: the call arrives with `this` = the tile.
_FN = {name: _script_function(getattr(Tile, name)) for name in _METHODS}


class HexMap:
    """The grid. `tile(x, y)` takes square coordinates; the world natives are put on `::World` by `install`."""

    def __init__(self, engine, size_x, size_y, layout):
        if layout not in _LAYOUT:
            raise ValueError("unknown layout %r (one of %s)" % (layout, ", ".join(LAYOUTS)))
        self.engine = engine
        self.layout = layout
        self._shifted, self._ysign = _LAYOUT[layout]
        self._offsets = _OFFSETS[layout]
        self._sprite = None
        self.type_version = 0       # +1 on every script write of a tile's Type (the navigator's cache) ...
        self.road_version = 0       # ... and of its RoadDirections (only RoadOnly routes depend on it)
        self.far_directions = 0     # getDirectionTo calls between tiles that are not neighbours (see there)
        self._navigator = None
        self._build(size_x, size_y)

    @property
    def navigator(self):
        """World.getNavigator() of this tile world, made on first use."""
        nav = self._navigator
        if nav is None:
            from .navigator import Navigator, terrain_count
            nav = self._navigator = Navigator(self, terrain_count(self.engine))
        return nav

    def _half(self, x):
        """How far column x's slant is (in rows) from column 0's."""
        return (x - (x & 1)) // 2 if self._shifted else (x + (x & 1)) // 2

    def _build(self, size_x, size_y):
        self.size_x = size_x
        self.size_y = size_y
        ysign = self._ysign
        cols = [[Tile(self, x, y, x, ysign * y - self._half(x), y * size_x + x) for y in range(size_y)]
                for x in range(size_x)]
        for x, col in enumerate(cols):
            offsets = self._offsets[x & 1]
            for t in col:
                y = t.y
                nb = []
                for dx, dy in offsets:
                    nx = x + dx
                    ny = y + dy
                    nb.append(cols[nx][ny] if 0 <= nx < size_x and 0 <= ny < size_y else None)
                t.nb = nb
        self.cols = cols
        self.tiles = [t for col in cols for t in col]       # column by column, like the generator's loops

    # ------------------------------------------------------------------ geometry
    def tile(self, x, y):
        if 0 <= x < self.size_x and 0 <= y < self.size_y:
            return self.cols[x][y]
        return None

    def neighbour(self, tile, d):
        return tile.nb[d]

    def distance(self, a, b):
        dq = a.q - b.q
        dr = a.r - b.r
        return max(abs(dq), abs(dr), abs(dq + dr))

    def tile_at_coords(self, cx, cy):
        """The tile with these hex coordinates (what `Tile.Coords` holds: X = q, Y = -q - r), or None."""
        return self.tile_at_axial(cx, -cx - cy)

    def tile_at_axial(self, q, r):
        """The tile with these internal axial coordinates (Tile.q, Tile.r), or None."""
        return self.tile(q, self._ysign * (r + self._half(q)))

    @staticmethod
    def pos_xy(x, y):
        """The engine's Pos of the square (x, y), as a pair of floats (POS_X0 ...: measured, see the top)."""
        return POS_X0 + POS_DX * x, POS_Y0 + POS_DY * y + (POS_DY / 2.0 if x & 1 else 0.0)

    def pos_of(self, tile):
        """Tile.Pos: the centre of the tile in the engine's world coordinates (MEASURED, see POS_X0). It is a function
        of the square coordinates only, so it is the same in every layout."""
        v = tile._pos
        if v is None:
            px, py = self.pos_xy(tile.x, tile.y)
            v = tile._pos = Vec(f32(px), f32(py))
        return v

    def coords_of_square(self, x, y):
        """Coords (X, Y) of the square (x, y), also for a square off the map (see Tile._coords)."""
        r = self._ysign * y - self._half(x)
        return x, -x - r

    def world_to_tile(self, pos):
        """World.worldToTile: Coords (a Vec) of the tile whose centre is nearest to the position, the distance
        measured with y scaled by sqrt(3) (that makes the stretched lattice a regular hex lattice, whose nearest
        centre is the hex the point lies in). MEASURED: worldToTile(tile.Pos) is the tile's Coords. UNVERIFIED:
        which tile the engine gives for a point near a border between two. The position needs readable X and Y."""
        px = float(R.get(pos, "X"))
        py = float(R.get(pos, "Y"))
        xf = (px - POS_X0) / POS_DX
        best = None
        for x in range(math.floor(xf) - 1, math.floor(xf) + 3):
            cx = POS_X0 + POS_DX * x
            yf = (py - POS_Y0 - (POS_DY / 2.0 if x & 1 else 0.0)) / POS_DY
            for y in range(math.floor(yf) - 1, math.floor(yf) + 3):
                cy = py - (POS_Y0 + POS_DY * y + (POS_DY / 2.0 if x & 1 else 0.0))
                d = (px - cx) ** 2 + 3.0 * cy ** 2
                if best is None or d < best[0]:
                    best = (d, x, y)
        cx, cy = self.coords_of_square(best[1], best[2])
        return Vec(int(cx), int(cy))            # as Coords (see Tile._coords)

    # ------------------------------------------------------------------ state
    def reset(self):
        """Every tile back to a blank one (the tile objects stay: the generator holds on to them)."""
        for t in self.tiles:
            t.reset_state()
        self._sprite = None
        self.touch()

    def resize(self, size_x, size_y):
        self._sprite = None
        self._build(size_x, size_y)
        self.touch()

    def touch(self):
        """Python code that changed a tile's Type or RoadDirections directly (scripts go through Tile.sq_set,
        which does this itself) tells the navigator so."""
        self.type_version += 1
        self.road_version += 1

    # ------------------------------------------------------------------ rings
    def ring(self, tile, radius):
        """The tiles at exactly `radius` from `tile`, in ring order; tiles off the map are left out. radius 0 is
        the tile. The order is Legends' own ring walk (config/z_legends_hex.nut traverseCircle): from the tile
        `radius` steps SW, `radius` steps in each direction N, NE, SE, S, SW, NW, every tile after a step.
        UNVERIFIED (the Task 7 run did not settle it: stage 2): the order of the engine's own queries. Where the
        generator uses an order-dependent
        query (findNextTileOfType's pick, which tile findNextRegion's answer comes from) only the label's place
        and the tiles' Region number depend on it, not a draw or a count."""
        if radius == 0:
            return [tile]
        q, r = tile.q + radius * _AXIAL[4][0], tile.r + radius * _AXIAL[4][1]
        out = []
        at = self.tile_at_axial
        for k in range(6):
            sq, sr = _AXIAL[k]
            for _ in range(radius):
                q += sq
                r += sr
                t = at(q, r)
                if t is not None:
                    out.append(t)
        return out

    def tiles_in_range(self, tile, lo, hi):
        """The tiles at distance lo..hi of `tile`, ring by ring (see ring())."""
        for radius in range(max(0, lo), hi + 1):
            yield from self.ring(tile, radius)

    # ------------------------------------------------------------------ world queries
    def query_tiles_in_range(self, tile, lo, hi, callback, data):
        """World.queryTilesInRange(tile, min, max, callback, data): callback(tile, data) for every tile at
        distance min..max. The generator's only caller (getTerrainInRegion) counts the terrain types, so the
        order (ring by ring, ring order; UNVERIFIED, stage 2) does not change its result."""
        lo, hi = _to_int(lo), _to_int(hi)
        for t in self.tiles_in_range(tile, lo, hi):
            R.call(callback, None, (t, data))

    def find_next_region(self, tile, radius, terrain):
        """World.findNextRegion(tile, radius, type), as buildLabels uses it. UNVERIFIED model (Task 5 checks it
        against the logged region counts): the Region of the first tile within `radius` (ring by ring, rings
        1..radius) whose Region is not 0 and whose Type is `type` (0: any type); 0 when there is none."""
        radius = _to_int(radius)
        for d in range(1, radius + 1):
            for t in self.ring(tile, d):
                if t.Region != 0 and (terrain == 0 or t.Type == terrain):
                    return t.Region
        return 0

    def find_next_tile_of_type(self, tile, radius, terrain, result):
        """World.findNextTileOfType(tile, radius, type, result): the first tile within `radius` (the tile itself
        first, then ring by ring) that is of that Type and whose six neighbours all are too goes to result.Result
        and the answer is true; false when there is none ("Failed to find decent spot for region label.").
        The six-neighbour condition is MEASURED, not guessed: any tile of the type alone never fails (in the
        first 16 logged generations the nearest one is at most 4 tiles from a region's centre), while the game
        failed 9 times in 7 of those maps; with the condition the lab fails 5 to 7 times in 4 to 7 maps, 3 to 6 of
        them among the game's 7, under each of four findNextRegion models; over all 96 generations 21 maps fail in
        both (about 12 expected without a link) and the count is equal in 65 (MODLOG "TOWNS AND REGIONS").
        UNVERIFIED (stage 2): the order and whether the tile itself counts; only whether a spot exists changes the
        run (the label's place does not)."""
        radius = _to_int(radius)
        for t in self.tiles_in_range(tile, 0, radius):
            if t.Type == terrain:
                for n in t.nb:
                    if n is None or n.Type != terrain:
                        break
                else:
                    R.newslot(result, "Result", t)
                    return True
        return False

    def update_tiles_with_heat(self, tiles, radius):
        """World.updateTilesWithHeat(settlement tiles, 6) (vanilla refineSettlements): every tile within
        `radius` of a settlement gets (radius - d) more HeatFromSettlements. UNVERIFIED: the formula is the one
        Legends wrote out in script in its own refineSettlements, which replaces this call."""
        radius = _to_int(radius)
        for s in tiles:
            for t in self.tiles_in_range(s, 0, radius):
                t.HeatFromSettlements = t.HeatFromSettlements + (radius - self.distance(s, t))

    def detail_sprite(self):
        """What spawnDetail hands back. One shared stand-in: nothing reads a detail's state back."""
        s = self._sprite
        if s is None:
            from .world import Sprite
            s = self._sprite = Sprite(self.engine, "detail")
        return s

    # ------------------------------------------------------------------ the ::World natives
    def install(self, world_table):
        """Put the tile natives on the `::World` table (replacing the engine's counted stand-ins)."""
        fns = {
            "getTileSquare": self._get_tile_square,
            "getTile": self._get_tile,
            "isValidTileSquare": self._is_valid_tile_square,
            "getMapSize": lambda this: Vec(self.size_x, self.size_y),
            # UNVERIFIED: the scripts never call resizeScene / clearScene on the world, the engine does.
            # Entities on the map are not modelled here (Task 5), so clearScene is clearTiles.
            "resizeScene": self._resize_scene,
            "clearScene": lambda this: self.reset(),
            "clearTiles": lambda this: self.reset(),
            "getNumOfTilesWithType": self._count_type,
            "worldToTile": lambda this, pos: self.world_to_tile(pos),
            "getNavigator": lambda this: self.navigator,
            "queryTilesInRange": lambda this, tile, lo, hi, cb, data: self.query_tiles_in_range(tile, lo, hi, cb, data),
            "findNextRegion": lambda this, tile, radius, terrain: self.find_next_region(tile, radius, terrain),
            "findNextTileOfType": lambda this, tile, radius, terrain, result:
                self.find_next_tile_of_type(tile, radius, terrain, result),
            "updateTilesWithHeat": lambda this, tiles, radius: self.update_tiles_with_heat(tiles, radius),
            # The region labels on the map: a picture only, the scripts get nothing back from it.
            "spawnRegionText": lambda this, *args: None,
        }
        for k, fn in fns.items():
            world_table.newslot(k, NativeFn(fn, k))

    def _get_tile_square(self, this, x, y):
        # UNVERIFIED: null for a square outside the map (the scripts ask isValidTileSquare first).
        if type(x) is not int or type(y) is not int:
            x, y = _to_int(x), _to_int(y)
        if 0 <= x < self.size_x and 0 <= y < self.size_y:
            return self.cols[x][y]
        return None

    def _get_tile(self, this, coords, y=None):
        """World.getTile(coords) or World.getTile(X, Y) (Legends' hex helpers): hex coordinates (Tile.Coords).
        UNVERIFIED: null for coordinates outside the map (Legends' callers keep inside it)."""
        if y is not None:
            return self.tile_at_coords(_to_int(coords), _to_int(y))
        return self.tile_at_coords(_to_int(R.get(coords, "X")), _to_int(R.get(coords, "Y")))

    def _is_valid_tile_square(self, this, x, y):
        x, y = _to_int(x), _to_int(y)
        return 0 <= x < self.size_x and 0 <= y < self.size_y

    def _resize_scene(self, this, x, y):
        self.resize(_to_int(x), _to_int(y))

    def _count_type(self, this, types):
        # The scripts pass an array of terrain types. UNVERIFIED: compared with Tile.Type only (vanilla's
        # desert count also lists a TerrainTacticalType value; Legends' own count does not use this native).
        wanted = set(types) if isinstance(types, list) else {types}
        n = 0
        for t in self.tiles:
            if t.Type in wanted:
                n += 1
        return n

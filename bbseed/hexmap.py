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

# UNVERIFIED: the engine's pixel size of a tile. Pos only has to be a regular hex lattice, because the
# generator averages Pos values and converts the average back with worldToTile (region labels).
HEX_SIZE = 64.0

_ROAD = 1                       # Const.World.DetailType.Road
_ADDR_BASE = 0x60000000         # tile addresses come from the tile number, so building a map leaves
#                                 the interpreter's address counter (R.new_addr) alone


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
                 "Type", "Subregion", "Level", "TacticalType", "HasRoad", "IsOccupied",
                 "IsMarkedForImpassableTerrain", "Region", "RoadDirections", "IsFlipped", "HeatFromSettlements",
                 "brush", "props", "_sq", "_co", "_pos")

    def __init__(self, hm, x, y, q, r, tile_id):
        self.hm = hm
        self.x = x                  # square (offset) coordinates
        self.y = y
        self.q = q                  # axial coordinates: q is the column, r the row along the column's slant
        self.r = r
        self.ID = tile_id           # UNVERIFIED: the engine's numbering; scripts only need it unique
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
        self.HasRoad = False
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
        else:
            raise SqError("the index '%s' does not exist" % tostring(key))

    def _square_coords(self):
        v = self._sq
        if v is None:
            v = self._sq = Vec(self.x, self.y)
        return v

    def _coords(self):
        # UNVERIFIED: Coords as axial (q, r). The scripts only pass it back (getTile, spawnLocation) and
        # read Coords.X on tactical maps, where it is the column.
        v = self._co
        if v is None:
            v = self._co = Vec(self.q, self.r)
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
        """Adjacent tiles: the direction between them. Further away: the direction of the 60 degree
        sector the other tile lies in (UNVERIFIED; the generator only asks about neighbours)."""
        dq = other.q - self.q
        dr = other.r - self.r
        d = _DIRECTION_OF.get((dq, dr))
        if d is not None:
            return d
        if dq == 0 and dr == 0:
            return 0                # UNVERIFIED
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
        """Remove the details (decorations) of the given types, all of them without an argument.
        Nothing is drawn here, so the only trace of a detail is HasRoad."""
        if mask is None or (mask.__class__ is int and mask & _ROAD):
            self.HasRoad = False

    def clearAllBut(self, this, *masks):
        keep = 0
        for m in masks:
            if m.__class__ is int:
                keep |= m
        if not keep & _ROAD:
            self.HasRoad = False

    def setBrush(self, this, name):
        self.brush = name

    def resetBrush(self, this):
        self.brush = None

    def getBrush(self, this):
        # UNVERIFIED: a brush is its name (tile_highlands.nut compares getBrush() to a string); null without one.
        return self.brush

    def spawnDetail(self, this, brush=None, zlevel=0, detail_type=0, *rest):
        """Nothing is drawn: hands back a sprite stand-in the scripts can write to (Saturation, setBrightness...).
        ASSUMED: a detail of type Road is what makes HasRoad true; no script ever assigns HasRoad."""
        if detail_type.__class__ is int and detail_type & _ROAD:
            self.HasRoad = True
        return self.hm.detail_sprite()

    def isSuitable(self, this, *args):
        # UNVERIFIED: the brief lists it; the scripts only call isSuitable on settlement types, never on a tile.
        return True

    def __repr__(self):
        return "Tile(%d, %d)" % (self.x, self.y)


_PLAIN = ("Type", "Subregion", "Level", "TacticalType", "HasRoad", "IsOccupied", "IsMarkedForImpassableTerrain",
          "Region", "RoadDirections", "IsFlipped", "HeatFromSettlements")
_GET = {name: attrgetter(name) for name in _PLAIN}
_GET["ID"] = attrgetter("ID")
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
        self._build(size_x, size_y)

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

    def tile_at_coords(self, q, r):
        """The tile with these axial coordinates (what `Tile.Coords` holds), or None."""
        return self.tile(q, self._ysign * (r + self._half(q)))

    def pos_of(self, tile):
        """Tile.Pos. UNVERIFIED: the engine's pixel convention. A regular hex lattice (centre of the tile),
        Y growing with the square y in every layout."""
        v = tile._pos
        if v is None:
            q, r = tile.q, tile.r
            v = tile._pos = Vec(f32(1.5 * HEX_SIZE * q), f32(self._ysign * _SQRT3 * HEX_SIZE * (r + q / 2.0)))
        return v

    def world_to_tile(self, pos):
        """Coords (a Vec) of the tile that contains the position; the position needs readable X and Y."""
        px = R.get(pos, "X")
        py = self._ysign * R.get(pos, "Y")
        qf = (2.0 / 3.0) * px / HEX_SIZE
        rf = (-px / 3.0 + _SQRT3 / 3.0 * py) / HEX_SIZE
        sf = -qf - rf
        q, r, s = math.floor(qf + 0.5), math.floor(rf + 0.5), math.floor(sf + 0.5)
        dq, dr, ds = abs(q - qf), abs(r - rf), abs(s - sf)
        if dq > dr and dq > ds:
            q = -r - s
        elif dr > ds:
            r = -q - s
        return Vec(int(q), int(r))

    # ------------------------------------------------------------------ state
    def reset(self):
        """Every tile back to a blank one (the tile objects stay: the generator holds on to them)."""
        for t in self.tiles:
            t.reset_state()
        self._sprite = None

    def resize(self, size_x, size_y):
        self._sprite = None
        self._build(size_x, size_y)

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

    def _get_tile(self, this, coords):
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

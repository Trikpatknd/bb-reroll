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

# World.worldToTile's pick (HexMap.world_to_tile). The exe asks its tile set for the art's size and holds only the
# factors 0.75 and 0.5: the world's mask is 240 x 120 px, so a box is 180 px wide (0.75 x 240), 120 px high, and each
# column's boxes start 60 px (0.5 x 120) lower than the previous column's.
_PICK_W3, _PICK_HH, _PICK_H = 180.0, 60.0, 120.0
_MASK_W, _MASK_H = 240, 120
_BLACK = None                   # the tile itself
# the exe's colours (0x553d60) as moves of the answer: green 0xff00ff00, white 0xffffffff ([0x6608ac]), blue 0xff0000ff,
# red 0xffff0000
_GREEN, _WHITE, _BLUE, _RED = (-1, 0), (1, -1), (-1, 1), (1, 0)


def _world_mask(lx, ly):
    """The pixel (lx, ly) of the world's tile mask `gfx/masks/hex_mask_world.0` (data_001.dat: a 240 x 120 32-bit TGA,
    stored bottom-up; the only world mask, so every world tile is level 0) as the exe reads it: row ly = the file's row
    119 - ly, blue and red swapped against the file's byte order. Returns _BLACK (the hexagon) or a colour = a move.
    The rule equals the file pixel for pixel (bb_seedlab tools/wtt_fit.py checks it against the installed game's
    file; tests/test_hexmap.py too when the game is installed). 0 <= lx < 240, 0 <= ly < 120."""
    if ly < 58:
        if lx < 58 - ly:
            return _GREEN
        if lx >= 182 + ly:
            return _WHITE
        return _BLACK
    if ly <= 60:
        return _BLACK
    if lx < ly - 61:
        return _BLUE
    if lx >= 300 - ly:
        return _RED
    return _BLACK


def _cvtt(v):
    """cvttss2si: a float truncated toward zero to an int32; NaN and anything out of range give 0x80000000."""
    if v != v or not -2147483648.0 <= v < 2147483648.0:
        return -2147483648
    return int(v)


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


# No "Level": reading Tile.Level on a WORLD tile raises in the game (MEASURED, native probe 2026-10-31: `err` on 126 of 126
# reads, the tiles of probe kind r1 and every 211th tile of 4 maps), so the scripts get "the index 'Level' does not exist"
# like for any other field the lab does not have (`sq_find` says MISSING, so `"Level" in tile` is false). The Python
# attribute `Tile.Level` stays (the lab's tools read it); a script WRITE of it raises as well (UNVERIFIED: no script
# of Legends 19.4.22 / the base game writes or reads it on a world tile, grep of the extracted scripts, 2026-10-31).
_PLAIN = ("Type", "Subregion", "TacticalType", "IsOccupied", "IsMarkedForImpassableTerrain",
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
        """World.worldToTile: Coords (a Vec) of the tile the game picks for a position. The exe's code (GOG exe
        0x4e4240 -> 0x551c60 with 0x553ee0 / 0x553e10 / 0x553d60, read in stage 2 B2 Task 1) with its picture data,
        the world's tile mask (`_world_mask`, read from the game's data_001.dat; NATIVE PROBE FIX 2, bb_seedlab MODLOG).
        In float32 like the exe; (X, Y) are the exe's grid coordinates = Coords in the measured layout (square y =
        Y + X // 2), "on the map" = 0 <= X < W and 0 <= Y + X // 2 < H; local(X', Y') = (trunc(px - 180 X'),
        trunc(py - (60 X' + 120 Y'))) truncated toward zero:
          1. the box guess: X = trunc(px / 180), Y = trunc((py - 60 X) / 120), one less when py - (60 X + 120 Y) < 0;
          2. a box off the map goes to 4 at once (no mask is read);
          3. the tiles in front, in this order: (X, Y-2), (X+1, Y-2), (X-1, Y-1), (X, Y-1), (X+1, Y-1), (X-1, Y): the
             first one on the map whose mask pixel at its local(X', Y') is black (inside 240 x 120) is the answer.
             With the world's one mask only (X+1, Y-1) and (X-1, Y) can hit: (X-1, Y) is the box's top-left triangle,
             (X+1, Y-1) a point less than 1 px left of the next column's box in its rows 0 and 1 (-0.4 truncates to 0);
          4. else the box's own mask pixel at local(X, Y) (lx < 0 reads column 0): green moves to (X-1, Y), blue to
             (X-1, Y+1) (white and red lie right of the box: never read here);
          5. clamp (0x552334): X into [0, W - 1], then Y into that column (square y into [0, H - 1]).
        MEASURED (native probe, game 1.5.2.3 + Legends 19.4.22, verify_nprobe2_log.html and verify_nprobe_log.html):
        every r1d call (47,008 on map job 0: every integer pixel of one lattice period, the same window at +0.5, the
        four edges inside and outside, the four corners) and every r1 call (2,676 per log on 4 maps: centres, border
        midpoints and corners with 0.01 / 0.5 px to either side in float32, points beyond the edges) - incl. step 2
        (89 r1d edge / corner calls that a mask read before the clamp would change), step 3's (X+1, Y-1) (r1's corner
        points C0 i001 / i05: 64 calls per log) and the 2-px band of the top-left triangle that only step 3's (X-1, Y)
        covers (r1's 70,0 B5 o001 / o05, 8 calls per log: the top row of an even column, where (X-1, Y) is off the
        map, so only the box's own green moves). Not modelled: the exe's mirrored path for a flipped world
        ([world+0x73]); elevation levels above 0 (the exe reads the level min(tile byte +0x0c, [world+0x58]); the world
        has the one mask, and every probe call agrees with level 0); a float rounding that leaves the box row outside
        0..119 (the exe would read past the mask's row; here the box's tile stays). The position needs readable X
        and Y."""
        px = f32(float(R.get(pos, "X")))
        py = f32(float(R.get(pos, "Y")))
        w, h = self.size_x, self.size_y

        def on_map(bx, by):
            return 0 <= bx < w and -(bx // 2) <= by < h - bx // 2

        def local(bx, by):
            return (_cvtt(f32(px - f32(bx * _PICK_W3))),
                    _cvtt(f32(py - f32(f32(bx * _PICK_HH) + f32(by * _PICK_H)))))

        X = _cvtt(f32(px / _PICK_W3))
        Y = _cvtt(f32(f32(py - f32(X * _PICK_HH)) / _PICK_H))
        if f32(py - f32(f32(X * _PICK_HH) + f32(Y * _PICK_H))) < 0.0:
            Y -= 1
        if on_map(X, Y):
            for bx, by in ((X, Y - 2), (X + 1, Y - 2), (X - 1, Y - 1), (X, Y - 1), (X + 1, Y - 1), (X - 1, Y)):
                if on_map(bx, by):
                    lx, ly = local(bx, by)
                    if 0 <= lx < _MASK_W and 0 <= ly < _MASK_H and _world_mask(lx, ly) is _BLACK:
                        X, Y = bx, by
                        break
            else:
                lx, ly = local(X, Y)
                if 0 <= ly < _MASK_H:
                    move = _world_mask(min(max(lx, 0), _MASK_W - 1), ly)
                    if move is not _BLACK:
                        X += move[0]
                        Y += move[1]
        x = min(max(X, 0), w - 1)
        y = min(max(Y + x // 2, 0), h - 1)
        cx, cy = self.coords_of_square(x, y)
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
        UNVERIFIED: the order of the engine's own queries. Since stage 2 B2 findNextRegion and findNextTileOfType do
        not use it (they have the exe's own rules, below), and since the native probe fix queryTilesInRange does not
        either; what still does is updateTilesWithHeat, whose result (a sum) does not depend on the order."""
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
        """World.queryTilesInRange(tile, min, max, callback, data): callback(tile, data) for the tiles the game's own
        query gives, in ITS order (GOG exe 1.5.2.3, handler 0x4f3ae0): the sector walk 0x5526f0 / 0x552a70 over the
        disc of radius `max` (exe_tiles_in_range) WITHOUT the centre (the call passes 'no centre'), then, in the
        vector's order, a tile of Type 0 is skipped (0x4f3b73), and so is one whose hex distance to `tile` is below
        `min` (0x4f3b91); the Type is read when the callback comes to the tile, not when the vector was made.
        MEASURED (native probe 2026-10-31, bb_seedlab MODLOG "NATIVE PROBE FIX 1"): queryTilesInRange of the game
        equals this on every call of the probe kinds r5 (352 calls on 4 maps, min 0 and 1, max 1..4, corners and
        edges) and r5t0 (16 calls with a Type-0 tile around); the old ring model (the centre for min 0, ring order,
        every type) gave 16 of 352 and 0 of 16. A float `min` / `max` is cut to an integer here (UNVERIFIED: no
        probe passes a float to this native)."""
        lo, hi = _to_int(lo), _to_int(hi)
        q0, r0 = tile.q, tile.r
        for t in self.exe_tiles_in_range(tile, hi)[1:]:
            if t.Type == 0:
                continue
            dq = t.q - q0
            dr = t.r - r0
            if max(abs(dq), abs(dr), abs(dq + dr)) < lo:
                continue
            R.call(callback, None, (t, data))

    def find_next_region(self, tile, radius, terrain):
        """World.findNextRegion(tile, radius, type), as buildLabels uses it: the game's own flood, read from the GOG
        exe (1.5.2.3; handler 0x4f3720 -> traversal 0x553180 -> flood 0x553a20, callback 0x4f3770; MODLOG "REGIONS
        FROM THE EXE"). MEASURED: the Region grids at the end of buildLabels equal the game's on 80 of 80 logged maps
        (40 Legends, 40 Vanilla), and so do the Found / failed-label / final-region counts. Ablated, and each one
        gave 0 equal grids on 80 maps: the flood order, the last leaf (not the first), flooding through tiles of
        other types, and the radius test (inclusive). NOT ablated: "Region 0 -> flooded through" (0x4f37c8, the start
        of the Region test block, jne at 0x4f37cf): the logs are consistent with it, it was not isolated.

        A depth-first flood from the tile. The six neighbours of a tile are tried in the order N, S, NE, NW, SE, SW
        (0x553a70 .. 0x553cdf); a neighbour that is off the grid or was reached already is skipped; otherwise the
        callback judges it: hex distance from the START tile > radius -> not entered (0x4f378f; the radius is
        inclusive); `terrain` != 0 and its Type != `terrain` -> entered and flooded through (0x4f37bc); Region 0 ->
        flooded through (0x4f37c8); else it is a leaf: the result becomes its Region, OVERWRITTEN at every leaf the
        flood meets (0x4f37dc), so the answer is the Region of the LAST leaf in depth-first order, and the leaf is
        not flooded through. 0 when there is none. `terrain` 0 matches every type.

        The recursion of the exe is an explicit stack of neighbour iterators here: the same visiting order, no Python
        recursion (buildLabels' third pass floods radius 16 from every tile still without a region).
        MEASURED (native probe 2026-10-31, bb_seedlab MODLOG "NATIVE PROBE", result block): the start tile is stamped
        first and never handed to the callback (0x553a5e..0x553a67; its own Region is no answer): probe kind r3, 5524
        of 5524 calls equal the game's; a Type-0 tile (Impassable) is entered and flooded through in a typed query
        (0x4f37bc): kind r3t0, 52 of 52; radius and type are cut to integers as the exe's glue 0x4f7640 does
        (cvttss2si 0x4f76c2 / 0x4f76e7; the glue of findNextTileOfType 0x4f7970: 0x4f7a55 / 0x4f7a7a): kind r4 with
        float arguments, 244 of 244. UNVERIFIED (0x4f37c8): the exe reads Region as an unsigned 16-bit word; regions
        stay far below 65536 and no probe wrote a Region that large."""
        radius = _to_int(radius)
        terrain = _to_int(terrain)
        q0, r0 = tile.q, tile.r
        seen = {tile}
        result = 0
        nb = tile.nb
        stack = [iter((nb[0], nb[3], nb[1], nb[5], nb[2], nb[4]))]
        push, pop = stack.append, stack.pop
        while stack:
            for n in stack[-1]:
                if n is None or n in seen:
                    continue
                dq = n.q - q0
                dr = n.r - r0
                if dq > radius or dq < -radius or dr > radius or dr < -radius or dq + dr > radius or dq + dr < -radius:
                    continue                # beyond the radius: not entered, not stamped
                seen.add(n)
                if terrain == 0 or n.Type == terrain:
                    region = n.Region
                    if region != 0:
                        result = region     # a leaf: the last one met wins; it is not flooded through
                        continue
                nb = n.nb
                push(iter((nb[0], nb[3], nb[1], nb[5], nb[2], nb[4])))
                break                       # go into n now (depth first), then carry on with this tile's list
            else:
                pop()
        return result

    def exe_tiles_in_range(self, tile, radius):
        """The tiles within `radius` of `tile`, the tile itself first, in the order of the vector the exe's tilesInRange
        fills (0x5526f0 called with 'with centre' by findNextTileOfType; the walk 0x552a70): after the centre one
        sector for each neighbour N, NE, SE, S, SW, NW (blocks 0x55275e .. 0x5529bf), each a depth-first walk
        (pre-order) from that neighbour along its own direction and the next one clockwise (NW: NW, then N), every
        step to a neighbour on the grid within `radius` (hex distance from the centre, 0x4cdce0); a tile is pushed
        the first time any sector reaches it. MEASURED (native probe 2026-10-31, MODLOG "NATIVE PROBE" and "FIX 1": the
        game's queryTilesInRange and findNextTileOfType hand out tiles in this order): the order, the centre as a first
        candidate (0x552713) and the off-grid sector rule (a disc tile reachable only through off-grid tiles is not
        walked, 0x552a70, region_exe off_grid_sector) and the radius 0 case (the centre alone, 0x5527aa..0x5527d3; kind r2
        asks radius 0 too), on corner and edge tiles too: probe kind r2 17798 of 17798 calls equal the game's and kind
        r5 352 of 352. Before the probe this order was UNVERIFIED (not logged: 40 of 40 maps per setup were equal with
        this order and with the old ring order alike).
        The exe walks a tile again each time another path reaches it (the walk is exponential in the radius); here a
        tile is walked once per sector. Same vector: after a tile's first walk everything reachable from it along the
        sector's two directions is stamped already, so a repeat pushes nothing (tests prove it against the literal walk)."""
        radius = _to_int(radius)
        out = [tile]
        if radius < 1:
            return out                      # no neighbour is within the radius: nothing is pushed
        q0, r0 = tile.q, tile.r
        stamped = {tile}
        push = out.append
        for k in range(6):
            first = tile.nb[k]
            if first is None:
                continue                    # off the grid: the exe's block is skipped
            a, b = k, (k + 1) % 6
            walked = {first}
            if first not in stamped:
                stamped.add(first)
                push(first)
            stack = [iter((first.nb[a], first.nb[b]))]
            while stack:
                for n in stack[-1]:
                    if n is None or n in walked:
                        continue
                    dq = n.q - q0
                    dr = n.r - r0
                    if dq > radius or dq < -radius or dr > radius or dr < -radius or dq + dr > radius \
                            or dq + dr < -radius:
                        continue
                    walked.add(n)
                    if n not in stamped:
                        stamped.add(n)
                        push(n)
                    stack.append(iter((n.nb[a], n.nb[b])))
                    break
                else:
                    stack.pop()
        return out

    def find_next_tile_of_type(self, tile, radius, terrain, result):
        """World.findNextTileOfType(tile, radius, type, result), the game's rule read from the GOG exe (1.5.2.3,
        0x4f37f0; MODLOG "REGIONS FROM THE EXE"): of the tiles within `radius` of `tile` (exe_tiles_in_range: the tile
        itself counts) take those of `type` whose six neighbours all exist and are of `type` (0x4f38f7 .. 0x4f3941),
        and of those the one with the smallest hex distance to `tile` (0x4f38c2; the exe starts at 9000 and compares
        with a strict <, so the first among equals in the walk's order wins, 0x4f39c5). The answer is true and
        result.Result the tile; false and result.Result = null (0x4f3a22) when there is none ("Failed to find decent
        spot for region label."). MEASURED: found / not found equals the game's on all 80 logged maps (a failed
        label in 12 maps per setup); the six-neighbour rule and the radius each change the counts when altered
        (MODLOG: without the six-neighbour rule 28 of 40 maps equal, a strict radius 36 / 34 of 40). MEASURED (native
        probe 2026-10-31, MODLOG "NATIVE PROBE"): the smallest-distance pick, its first-among-equals tie-break
        (0x4f38c2 / 0x4f39c5) and that the start tile counts as a candidate: the Result tile equals the game's on probe
        kind r2, 17798 of 17798 calls (Result null included), and r2t0, 12 of 12 (a Type-0 goal type)."""
        radius = _to_int(radius)
        terrain = _to_int(terrain)
        q0, r0 = tile.q, tile.r
        best = None
        best_score = 9000
        for t in self.exe_tiles_in_range(tile, radius):
            if t.Type != terrain:
                continue
            dq = t.q - q0
            dr = t.r - r0
            score = max(abs(dq), abs(dr), abs(dq + dr))
            if score >= best_score:
                continue
            for n in t.nb:
                if n is None or n.Type != terrain:
                    break
            else:
                best = t
                best_score = score
        R.newslot(result, "Result", best)
        return best is not None

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

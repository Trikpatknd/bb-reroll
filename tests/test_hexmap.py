"""The tile world the map generator runs on: hex neighbours, distance, tile fields, World natives."""
import sys
from collections import deque
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbseed.engine import Engine, Stub
from bbseed.hexmap import LAYOUTS, HexMap, NotModelled
from bbseed.sq import runtime as R
from bbseed.sq.runtime import SqError, SqTable


@pytest.mark.parametrize("layout", LAYOUTS)
def test_inner_tile_has_six_distinct_neighbours_that_point_back(layout):
    m = HexMap(None, 140, 170, layout)
    t = m.tile(70, 85)
    ns = [m.neighbour(t, d) for d in range(6)]
    assert len({(n.x, n.y) for n in ns}) == 6
    for d, n in enumerate(ns):
        assert m.neighbour(n, (d + 3) % 6) is t
        assert m.distance(t, n) == 1


@pytest.mark.parametrize("layout", LAYOUTS)
def test_corner_and_distance(layout):
    m = HexMap(None, 140, 170, layout)
    assert sum(m.neighbour(m.tile(0, 0), d) is not None for d in range(6)) in (2, 3)
    a, b = m.tile(3, 4), m.tile(40, 100)
    assert m.distance(a, b) == m.distance(b, a) > 0
    assert m.tile(140, 0) is None and m.tile(0, 170) is None


def test_surrounding_tiles_of_type_counts_neighbours():
    m = HexMap(None, 10, 10, LAYOUTS[0])
    t = m.tile(5, 5)
    for d in (0, 2, 4):
        m.neighbour(t, d).Type = 7
    assert t.getSurroundingTilesOfType(None, 7) == 3      # NativeFn style: (this, args...)


# ---------------------------------------------------------------- the four layouts
# (x, y) of the six neighbours N NE SE S SW NW of an even-column tile (4, 5) and an odd-column tile (5, 5).
# Written out by hand from the brief's odd-q/down table: "up" mirrors the y offsets, "even" swaps the rows.
EXPECTED = {
    "odd-q-down": ([(4, 4), (5, 4), (5, 5), (4, 6), (3, 5), (3, 4)], [(5, 4), (6, 5), (6, 6), (5, 6), (4, 6), (4, 5)]),
    "odd-q-up": ([(4, 6), (5, 6), (5, 5), (4, 4), (3, 5), (3, 6)], [(5, 6), (6, 5), (6, 4), (5, 4), (4, 4), (4, 5)]),
    "even-q-down": ([(4, 4), (5, 5), (5, 6), (4, 6), (3, 6), (3, 5)], [(5, 4), (6, 4), (6, 5), (5, 6), (4, 5), (4, 4)]),
    "even-q-up": ([(4, 6), (5, 5), (5, 4), (4, 4), (3, 4), (3, 5)], [(5, 6), (6, 6), (6, 5), (5, 4), (4, 5), (4, 6)]),
}


def test_layouts_are_the_four_expected_ones():
    assert set(LAYOUTS) == set(EXPECTED) and len(LAYOUTS) == 4


@pytest.mark.parametrize("layout", LAYOUTS)
def test_neighbour_tables(layout):
    m = HexMap(None, 12, 12, layout)
    even, odd = EXPECTED[layout]
    for x, want in ((4, even), (5, odd)):
        t = m.tile(x, 5)
        assert [(n.x, n.y) for n in (m.neighbour(t, d) for d in range(6))] == want


def test_unknown_layout_is_an_error():
    with pytest.raises(ValueError):
        HexMap(None, 4, 4, "pointy")


@pytest.mark.parametrize("layout", LAYOUTS)
def test_distance_is_the_walking_distance(layout):
    m = HexMap(None, 15, 14, layout)
    for sx, sy in ((7, 6), (0, 0), (14, 13), (0, 13), (14, 0), (6, 7)):
        start = m.tile(sx, sy)
        seen = {start: 0}
        queue = deque([start])
        while queue:
            t = queue.popleft()
            for d in range(6):
                n = m.neighbour(t, d)
                if n is not None and n not in seen:
                    seen[n] = seen[t] + 1
                    queue.append(n)
        assert len(seen) == 15 * 14
        # walking inside the rectangle is never shorter than the open-field distance, and equal to it here
        # (the rectangle has no dents a shortest path would have to leave it for)
        for t, steps in seen.items():
            assert m.distance(start, t) == steps == t.getDistanceTo(None, start)


@pytest.mark.parametrize("layout", LAYOUTS)
def test_tile_numbers_and_borders(layout):
    m = HexMap(None, 9, 7, layout)
    assert m.size_x == 9 and m.size_y == 7
    assert [m.tile(x, y) is None for x, y in ((-1, 0), (0, -1), (9, 3), (3, 7))] == [True] * 4
    ids = {m.tile(x, y).ID for x in range(9) for y in range(7)}
    assert len(ids) == 63
    t = m.tile(8, 6)
    assert (t.x, t.y) == (8, 6)
    assert sum(1 for d in range(6) if t.hasNextTile(None, d)) in (2, 3)
    assert t.getNextTile(None, [d for d in range(6) if not t.hasNextTile(None, d)][0]) is None
    assert not t.hasNextTile(None, 6) and not t.hasNextTile(None, -1)


# ---------------------------------------------------------------- tile fields and methods
def test_tile_defaults_and_python_attributes():
    m = HexMap(None, 6, 6, LAYOUTS[0])
    t = m.tile(2, 3)
    assert (t.Type, t.Subregion, t.Level, t.TacticalType) == (0, 0, 0, 0)
    assert (t.HasRoad, t.IsOccupied, t.IsMarkedForImpassableTerrain) == (False, False, False)
    t.Type = 7
    assert m.tile(2, 3).Type == 7 and m.tile(3, 3).Type == 0


def test_script_fields_and_unknown_field_raises():
    m = HexMap(None, 6, 6, LAYOUTS[0])
    t = m.tile(2, 3)
    R.set_(t, "Type", 5)
    R.set_(t, "IsOccupied", True)
    assert R.get(t, "Type") == 5 and t.Type == 5 and R.get(t, "IsOccupied") is True
    for bad in ("Bogus", "type", "x"):
        with pytest.raises(SqError):
            R.get(t, bad)
        assert t.sq_find(bad) is R.MISSING
        assert not R.has(t, bad)
    with pytest.raises(SqError):
        R.set_(t, "Bogus", 1)
    with pytest.raises(SqError):
        R.set_(t, "ID", 1)                    # computed, read-only
    assert R.has(t, "Type") and R.has(t, "getNextTile")


@pytest.mark.parametrize("layout", LAYOUTS)
def test_coordinates(layout):
    m = HexMap(None, 11, 9, layout)
    t = m.tile(4, 6)
    sq = R.get(t, "SquareCoords")
    assert (R.get(sq, "X"), R.get(sq, "Y")) == (4, 6)
    co = R.get(t, "Coords")
    assert R.get(co, "X") == 4                # UNVERIFIED convention: axial (column, row) coordinates
    for x in range(11):
        for y in range(9):
            c = R.get(m.tile(x, y), "Coords")
            assert m.tile_at_coords(R.get(c, "X"), R.get(c, "Y")) is m.tile(x, y)
    assert m.tile_at_coords(-50, 3) is None


@pytest.mark.parametrize("layout", LAYOUTS)
def test_neighbours_differ_by_the_axial_directions(layout):
    m = HexMap(None, 12, 12, layout)
    deltas = {(1, -1), (1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1)}
    t = m.tile(5, 6)
    cq, cr = t.q, t.r
    seen = []
    for d in range(6):
        n = m.neighbour(t, d)
        seen.append((n.q - cq, n.r - cr))
    assert seen == [(0, -1), (1, -1), (1, 0), (0, 1), (-1, 1), (-1, 0)] and set(seen) == deltas


# Tile.Pos as the game gave it, square (x, y) -> (Pos.X, Pos.Y): the in-game map dump of map-search Task 7 (13 tiles,
# the same in all 40 maps); World.worldToTile(Pos) gave each tile's Coords there.
GAME_POS = {(0, 0): (120, 60), (1, 0): (300, 120), (0, 1): (120, 180), (1, 1): (300, 240), (2, 0): (480, 60),
            (2, 1): (480, 180), (4, 5): (840, 660), (5, 5): (1020, 720), (70, 85): (12720, 10260),
            (71, 85): (12900, 10320), (139, 0): (25140, 120), (0, 169): (120, 20340), (139, 169): (25140, 20400)}


def test_positions_are_the_games():
    m = HexMap(None, 140, 170, "even-q-up")
    for (x, y), want in GAME_POS.items():
        pos = R.get(m.tile(x, y), "Pos")
        assert (R.get(pos, "X"), R.get(pos, "Y")) == want, (x, y)
        c = m.world_to_tile(pos)
        assert (R.get(c, "X"), R.get(c, "Y")) == (x, y - x // 2), (x, y)      # the game's Coords of that tile
    # the neighbours in the measured layout sit where the directions say: N up (+Y), NE / SE to the right
    t = m.tile(70, 85)
    p = R.get(t, "Pos")
    steps = [(R.get(R.get(m.neighbour(t, d), "Pos"), "X") - R.get(p, "X"),
              R.get(R.get(m.neighbour(t, d), "Pos"), "Y") - R.get(p, "Y")) for d in range(6)]
    assert steps == [(0, 120), (180, 60), (180, -60), (0, -120), (-180, -60), (-180, 60)]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_positions_convert_back(layout):
    """worldToTile gives a tile's Coords for its Pos, and for a point well inside the tile (the cell's border is
    UNVERIFIED), in every layout (Pos depends on the square coordinates only; Coords on the layout)."""
    m = HexMap(None, 9, 8, layout)
    for x in range(9):
        for y in range(8):
            tile = m.tile(x, y)
            pos = R.get(tile, "Pos")
            c = m.world_to_tile(pos)
            assert m.tile_at_coords(R.get(c, "X"), R.get(c, "Y")) is tile
            # createVec(x, y) is a Stub with the fields X and Y; worldToTile reads whatever has them
            for dx, dy in ((30, -24), (-40, 20), (0, 50), (60, 0)):
                off = Stub(None, "vec", {"X": R.get(pos, "X") + dx, "Y": R.get(pos, "Y") + dy})
                near = m.world_to_tile(off)
                assert m.tile_at_coords(R.get(near, "X"), R.get(near, "Y")) is tile, (x, y, dx, dy)
    # a point off the map still has Coords (the generator averages positions of tiles on the map, so it never asks)
    c = m.world_to_tile(Stub(None, "vec", {"X": -400.0, "Y": -400.0}))
    assert m.tile_at_coords(R.get(c, "X"), R.get(c, "Y")) is None


@pytest.mark.parametrize("layout", LAYOUTS)
def test_direction_to(layout):
    m = HexMap(None, 30, 30, layout)
    t = m.tile(14, 14)
    for d in range(6):
        n = m.neighbour(t, d)
        assert t.getDirectionTo(None, n) == d
        assert n.getDirectionTo(None, t) == (d + 3) % 6
        far = n
        for _ in range(3):
            far = m.neighbour(far, d)
        assert t.getDirectionTo(None, far) == d
        assert t.getDistanceTo(None, far) == 4
        # a little off the axis, to either side, is still the same 60 degree sector
        for side in ((d + 1) % 6, (d - 1) % 6):
            off = m.neighbour(far, side)
            assert t.getDirectionTo(None, off) == d
    assert t.isSameTileAs(None, m.tile(14, 14)) and not t.isSameTileAs(None, m.tile(14, 15))
    assert not t.isSameTileAs(None, None)


def test_surrounding_tiles_not_of_type_ignores_missing_neighbours():
    m = HexMap(None, 10, 10, LAYOUTS[0])
    inner = m.tile(5, 5)
    assert inner.getSurroundingTilesNotOfType(None, 1) == 6
    inner.Type = 1
    assert m.neighbour(inner, 0).getSurroundingTilesNotOfType(None, 1) == 5
    corner = m.tile(0, 0)
    n_real = sum(1 for d in range(6) if corner.hasNextTile(None, d))
    assert corner.getSurroundingTilesNotOfType(None, 1) == n_real


def test_details_brushes_and_roads():
    m = HexMap(None, 6, 6, LAYOUTS[0])
    t = m.tile(2, 2)
    assert t.getBrush(None) is None
    t.setBrush(None, "world_grassland_01")
    assert t.getBrush(None) == "world_grassland_01"
    t.resetBrush(None)
    assert t.getBrush(None) is None
    # spawnDetail hands back something the scripts can write to; nothing is drawn
    d = t.spawnDetail(None, "world_detail_fields", 5, 0, False)
    assert d is not None
    R.set_(d, "Saturation", 0.5)
    assert not t.HasRoad
    # A road is RoadDirections (the road builder's bits; removeAutobahnkreuze, buildRoadSprites and the attached
    # locations read HasRoad before any road detail exists): a road detail does not make one, clear() keeps it
    t.spawnDetail(None, "world_road_01", 6, 1, False)
    assert not t.HasRoad and R.get(t, "HasRoad") is False
    R.set_(t, "RoadDirections", 1 | 8)
    assert t.HasRoad and R.get(t, "HasRoad") is True
    t.clear(None, 1)
    t.clearAllBut(None, 4)
    t.clear(None)
    assert t.HasRoad
    with pytest.raises(SqError):
        R.set_(t, "HasRoad", False)          # read-only: no script assigns it
    R.set_(t, "RoadDirections", 0)
    assert not t.HasRoad
    assert t.isSuitable(None) is True


# ---------------------------------------------------------------- the World natives, through the interpreter
@pytest.fixture
def lab():
    e = Engine([])
    m = HexMap(e, 12, 10, "odd-q-down")
    m.install(e.World)
    out = []
    e.vm.print_fn = out.append
    return e, m, out


def test_install_puts_the_natives_on_the_world_table(lab):
    e, m, out = lab
    for name in ("getTileSquare", "getTile", "isValidTileSquare", "getMapSize", "resizeScene", "clearScene",
                 "clearTiles", "getNumOfTilesWithType", "worldToTile"):
        assert type(e.World.get(name)) is R.NativeFn and e.World.get(name).name == name
    t = SqTable()
    m.install(t)
    assert "getTileSquare" in t and t.key_list().count("getTileSquare") == 1


def test_scripts_read_and_write_tiles(lab):
    e, m, out = lab
    e.vm.run('''
        local t = ::World.getTileSquare(5, 5);
        t.Type = 7;
        local n = t.getNextTile(1);
        n.Type = 3;
        n.Level = 2;
        print(t.hasNextTile(0));
        print(n.Type + ":" + n.Level);
        print(t.getSurroundingTilesOfType(3));
        print(t.getDistanceTo(n));
        print(n.getDirectionTo(t));
        print(t.SquareCoords.X + "," + t.SquareCoords.Y);
        print(::World.getTileSquare(0, 0).hasNextTile(5));
        local ok = false;
        try { local z = t.NoSuchField; } catch (err) { ok = true; }
        print(ok);
        ok = false;
        try { t.NoSuchField = 1; } catch (err) { ok = true; }
        print(ok);
    ''', "t.nut")
    assert out == ["true", "3:2", "1", "1", "4", "5,5", "false", "true", "true"]
    assert m.tile(5, 5).Type == 7 and m.tile(6, 5).Type == 3


def test_scripts_accumulate_settlement_heat(lab):
    # the loop of Legends' refineSettlements / entity_manager.updateSettlementHeat: add (6 - d) to every tile
    # within 6 of a settlement, without zeroing first, so the field must start as a number
    e, m, out = lab
    e.vm.run('''
        local s = ::World.getTileSquare(5, 5);
        local sum = 0;
        local size = ::World.getMapSize();
        for (local x = 0; x < size.X; x = ++x)
            for (local y = 0; y < size.Y; y = ++y) {
                local tile = ::World.getTileSquare(x, y);
                local d = s.getDistanceTo(tile);
                if (d > 6)
                    continue;
                tile.HeatFromSettlements = tile.HeatFromSettlements + (6 - d);
                sum += tile.HeatFromSettlements;
            }
        print(s.HeatFromSettlements);
        print(s.getNextTile(2).HeatFromSettlements);
        print(sum);
        ::World.getTileSquare(0, 0).HeatFromSettlements = 0;
    ''', "t.nut")
    assert out[:2] == ["6", "5"]
    assert m.tile(5, 5).HeatFromSettlements == 6
    assert int(out[2]) == sum(6 - m.distance(m.tile(5, 5), t) for t in m.tiles if m.distance(m.tile(5, 5), t) <= 6)
    assert m.tile(11, 5).HeatFromSettlements == 0 and m.tile(10, 5).HeatFromSettlements == 1
    m.reset()
    assert all(t.HeatFromSettlements == 0 for t in m.tiles)


def test_world_natives(lab):
    e, m, out = lab
    e.vm.run('''
        print(::World.isValidTileSquare(11, 9));
        print(::World.isValidTileSquare(12, 9));
        print(::World.isValidTileSquare(-1, 0));
        local size = ::World.getMapSize();
        print(size.X + "x" + size.Y);
        print(::World.getTileSquare(12, 0) == null);
        ::World.getTileSquare(1, 1).Type = 4;
        ::World.getTileSquare(2, 1).Type = 4;
        ::World.getTileSquare(3, 1).Type = 5;
        print(::World.getNumOfTilesWithType([4]));
        print(::World.getNumOfTilesWithType([4, 5]));
        print(::World.getNumOfTilesWithType([0]));
        print(::World.getNumOfTilesWithType(5));
        local t = ::World.getTileSquare(6, 4);
        print(::World.getTile(t.Coords) == t);
        print(::World.getTile(::World.worldToTile(t.Pos)) == t);
    ''', "t.nut")
    assert out == ["true", "false", "false", "12x10", "true", "2", "3", str(120 - 3), "1", "true", "true"]


def test_clear_tiles_resets_but_keeps_the_tile_objects(lab):
    e, m, out = lab
    t = m.tile(3, 3)
    t.Type, t.Level, t.Subregion, t.IsOccupied, t.Region, t.RoadDirections = 6, 2, 99, True, 4, 9
    t.setBrush(None, "x")
    t.spawnDetail(None, "r", 6, 1, False)
    e.vm.run("::World.clearTiles();", "t.nut")
    assert m.tile(3, 3) is t
    assert (t.Type, t.Level, t.Subregion, t.IsOccupied, t.Region, t.RoadDirections) == (0, 0, 0, False, 0, 0)
    assert t.HasRoad is False and t.getBrush(None) is None
    t.Type = 2
    e.vm.run("::World.clearScene();", "t.nut")
    assert m.tile(3, 3) is t and t.Type == 0
    m.tile(1, 1).Type = 8
    m.reset()
    assert m.tile(1, 1).Type == 0


def test_resize_scene_builds_a_new_grid(lab):
    e, m, out = lab
    old = m.tile(2, 2)
    e.vm.run('::World.resizeScene(20, 15); local s = ::World.getMapSize(); print(s.X + "x" + s.Y);', "t.nut")
    assert out == ["20x15"] and m.size_x == 20 and m.size_y == 15
    assert m.tile(19, 14) is not None and m.tile(20, 0) is None and m.tile(2, 2) is not old
    assert m.neighbour(m.tile(10, 7), 3) is m.tile(10, 8)


def test_building_a_map_leaves_the_address_counter_alone():
    before = R.new_addr()
    m = HexMap(None, 20, 20, LAYOUTS[0])
    m.reset()
    assert R.new_addr() == before + 0x40
    assert len({t.addr for t in m.tiles}) == 400


def test_a_full_size_map_builds_quickly_and_neighbours_are_consistent():
    import time
    t0 = time.perf_counter()
    m = HexMap(None, 140, 170, "odd-q-down")
    assert time.perf_counter() - t0 < 5.0           # about 0.03 s here; the bound only catches a quadratic build
    bad = 0
    for x in range(0, 140, 7):
        for y in range(0, 170, 7):
            t = m.tile(x, y)
            for d in range(6):
                n = m.neighbour(t, d)
                if n is not None and m.neighbour(n, (d + 3) % 6) is not t:
                    bad += 1
    assert bad == 0


# ---------------------------------------------------------------- map search Task 5: coordinates and world queries
LEGENDS_NEIGHBOURS = [(0, 1), (1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1)]     # z_legends_hex.nut, N NE SE S SW NW


def test_coords_are_the_hex_coordinates_legends_computes():
    """Legends walks rings in Coords itself (config/z_legends_hex.nut): Y = squareY - squareX / 2 (integer division)
    and fixed neighbour offsets; in the measured layout even-q-up both hold, and getTile(X, Y) takes them."""
    m = HexMap(None, 20, 16, "even-q-up")
    for t in m.tiles:
        c = R.get(t, "Coords")
        assert (R.get(c, "X"), R.get(c, "Y")) == (t.x, t.y - t.x // 2)
        assert m._get_tile(None, R.get(c, "X"), R.get(c, "Y")) is t and m._get_tile(None, c) is t
        for d, (dx, dy) in enumerate(LEGENDS_NEIGHBOURS):
            n = t.getNextTile(None, d)
            if n is not None:
                nc = R.get(n, "Coords")
                assert (R.get(nc, "X") - R.get(c, "X"), R.get(nc, "Y") - R.get(c, "Y")) == (dx, dy)
    assert m._get_tile(None, 0, 40) is None


def test_ring_order_is_legends_traverse_circle():
    m = HexMap(None, 30, 30, "even-q-up")
    centre = m.tile(15, 14)
    c = R.get(centre, "Coords")
    for radius in (1, 2, 3):
        x, y = R.get(c, "X") + radius * -1, R.get(c, "Y")          # radius steps SW: (-1, 0) each
        want = []
        for dx, dy in LEGENDS_NEIGHBOURS:
            for _ in range(radius):
                x, y = x + dx, y + dy
                want.append(m.tile_at_coords(x, y))
        assert m.ring(centre, radius) == want and len(want) == 6 * radius
        assert all(m.distance(centre, t) == radius for t in want)
    assert m.ring(centre, 0) == [centre]
    corner = m.tile(0, 0)
    assert all(t is not None for t in m.ring(corner, 2)) and len(m.ring(corner, 2)) < 12


def test_query_tiles_in_range_through_a_script(lab):
    """getTerrainInRegion: World.queryTilesInRange(tile, 1, 4, callback.bindenv(this), counts) counts the terrain."""
    e, m, out = lab
    e.vm.run('''
        for (local x = 0; x < 12; ++x) for (local y = 0; y < 10; ++y) ::World.getTileSquare(x, y).Type = 2;
        ::World.getTileSquare(6, 5).Type = 4;
        local counter = { n = 0, function onTile(_tile, _counts) { ++_counts[_tile.Type]; ++this.n; } };
        local counts = array(19, 0);
        ::World.queryTilesInRange(::World.getTileSquare(5, 5), 1, 4, counter.onTile.bindenv(counter), counts);
        print(counter.n + " " + counts[2] + " " + counts[4]);
        counts = array(19, 0);
        ::World.queryTilesInRange(::World.getTileSquare(0, 0), 0, 1, counter.onTile.bindenv(counter), counts);
        print(counts[2]);
    ''', "t.nut")
    assert out == ["60 59 1", str(1 + sum(1 for d in range(6) if m.tile(0, 0).hasNextTile(None, d)))]


# ---------------------------------------------------------------- stage 2 B2: the game's region search (GOG exe)
# Terrain types of the grids below (Const.World.TerrainType: Ocean 1, Plains 2, Hills 4, Forest 5).
PLAINS, FOREST, OCEAN, HILLS = 2, 5, 1, 4


def _grid(w, h, fill=PLAINS):
    """A map of the measured layout with every tile of one type. Around the tile (4, 4) (x even, Coords (4, 2)) the six
    neighbours are, in square coordinates: N (4, 5), S (4, 3), NE (5, 4), SE (5, 3), NW (3, 4), SW (3, 3) (Coords
    offsets N (0, 1), S (0, -1), NE (1, 0), SE (1, -1), NW (-1, 1), SW (-1, 0))."""
    m = HexMap(None, w, h, "even-q-up")
    for t in m.tiles:
        t.Type = fill
    return m


def _region(m, x, y, radius, ttype):
    return m.find_next_region(m.tile(x, y), radius, ttype)


def _label_spot(m, x, y, radius, ttype):
    """findNextTileOfType as the script calls it: the spot's (x, y) or None; the answer and result.Result agree."""
    result = SqTable()
    ok = m.find_next_tile_of_type(m.tile(x, y), radius, ttype, result)
    spot = R.get(result, "Result")
    assert ok == (spot is not None)
    return None if spot is None else (spot.x, spot.y)


# The exe's flood order in the tile's direction numbers (N=0 NE=1 SE=2 S=3 SW=4 NW=5): N, S, NE, NW, SE, SW (0x553a20).
FLOOD_DIRECTIONS = (0, 3, 1, 5, 2, 4)


def _flood_transcription(m, start, radius, ttype):
    """0x553a20 + callback 0x4f3770 transcribed with real recursion and a set of stamps: what the iterative
    HexMap.find_next_region must equal on every grid."""
    result = [0]
    stamped = {start}

    def flood(cur):
        for d in FLOOD_DIRECTIONS:
            n = cur.nb[d]
            if n is None or n in stamped or m.distance(start, n) > radius:
                continue
            leaf = False
            if ttype == 0 or n.Type == ttype:
                if n.Region != 0:
                    result[0] = n.Region
                    leaf = True
            stamped.add(n)
            if not leaf:
                flood(n)
    flood(start)
    return result[0]


def test_find_next_region_is_the_exes_order():
    """0x553a20 floods depth first, neighbours N, S, NE, NW, SE, SW (blocks 0x553a70, 0x553aee, 0x553b69, 0x553be3,
    0x553c61, 0x553cdf), and the callback 0x4f3770 OVERWRITES the result at every leaf it meets (0x4f37dc): nothing
    stops the flood. A tile of the type with a Region is a leaf (answer 3: stamped, not flooded through).
    MEASURED on 80 logged maps (stage 2 B2 Task 1): the Region grids are equal on all.
    Two regions at distance 1 of (4, 4): N (4, 5) has 5, S (4, 3) has 7. The flood meets N first and S second, so the
    answer is 7; the old model (the first match in Legends' ring order NW, N, NE, SE, S, SW) gave 5."""
    m = _grid(9, 9)
    m.tile(4, 5).Region = 5
    m.tile(4, 3).Region = 7
    assert _region(m, 4, 4, 3, PLAINS) == 7
    # all six neighbours are leaves with their own regions: the blocks run in order and the last one, SW, wins
    nb = {"N": (4, 5), "S": (4, 3), "NE": (5, 4), "NW": (3, 4), "SE": (5, 3), "SW": (3, 3)}
    reg = {"N": 11, "S": 12, "NE": 13, "NW": 14, "SE": 15, "SW": 16}
    m = _grid(9, 9)
    for k, (x, y) in nb.items():
        m.tile(x, y).Region = reg[k]
    assert _region(m, 4, 4, 3, PLAINS) == reg["SW"]
    # take the regions away from the end of the order one by one: the last remaining block's region is the answer
    # (a Region-0 neighbour is flooded through, but every other leaf there is already stamped)
    for k in ("SW", "SE", "NW", "NE", "S"):
        m.tile(*nb[k]).Region = 0
        expect = {"SW": "SE", "SE": "NW", "NW": "NE", "NE": "S", "S": "N"}[k]
        assert _region(m, 4, 4, 3, PLAINS) == reg[expect], k
    # UNVERIFIED (0x553a5e..0x553a67): the start tile is stamped before the flood and never handed to the callback, so
    # its own Region is no answer (buildLabels only asks for tiles whose Region is 0, so no logged map can tell)
    m = _grid(9, 9)
    m.tile(4, 4).Region = 3
    assert _region(m, 4, 4, 3, PLAINS) == 0
    # the glue (0x4f7640) takes radius and type as integers: a float is cut
    m = _grid(9, 12)
    m.tile(4, 8).Region = 6
    assert _region(m, 4, 4, 4.9, 2.0) == 6 and _region(m, 4, 4, 3.9, 2.0) == 0


def test_find_next_region_is_depth_first():
    """Pins depth-first against breadth-first (reviewer finding of Task 1). The N neighbour of (4, 4) has Region 0 and
    a Region-9 leaf behind it (one step further north, (4, 6)); the S neighbour is a Region-7 leaf. The flood goes
    into N first, meets the 9 there, and finds the 7 later: the answer is 7. A breadth-first flood meets the 7 at
    distance 1 and the 9 at distance 2, and with the same overwrite rule would answer 9 (so would 'the first leaf
    wins')."""
    m = _grid(9, 9)
    m.tile(4, 6).Region = 9
    m.tile(4, 3).Region = 7
    assert m.tile(4, 5).Region == 0
    assert _region(m, 4, 4, 3, PLAINS) == 7
    assert _flood_transcription(m, m.tile(4, 4), 3, PLAINS) == 7
    # the mirror image: the near leaf N (Region 7) is met first, the far one (4, 2) behind the Region-0 S neighbour
    # later, so the LAST leaf in depth-first order (9) is the answer, not the first one
    m = _grid(9, 9)
    m.tile(4, 5).Region = 7
    m.tile(4, 2).Region = 9
    assert _region(m, 4, 4, 3, PLAINS) == 9


def test_find_next_region_radius_and_type():
    """0x4f3789..0x4f3791: hex distance (0x552680) from the start > radius -> the callback answers 0 and the flood does
    not enter the tile. A region 4 steps north of (4, 4) - (4, 8) - is found with radius 4 and not with radius 3.
    0x4f37bc..0x4f37c6: with type != 0 a tile of another type answers 1: no find, but the flood goes on THROUGH it;
    0x4f37c8: a tile of the type with Region 0 answers 1 too. Type 0 matches any type (pass three of buildLabels;
    UNVERIFIED for pass one: no logged map has a Type 0 tile)."""
    m = _grid(9, 12)
    m.tile(4, 8).Region = 6
    assert _region(m, 4, 4, 3, PLAINS) == 0
    assert _region(m, 4, 4, 4, PLAINS) == 6
    # on a small map the radius still decides: (2, 2) is beyond radius 1 and within radius 3 of (0, 0), and the
    # flood keeps to the grid
    m = _grid(3, 3)
    m.tile(2, 2).Region = 4
    assert _region(m, 0, 0, 1, PLAINS) == 0
    assert _region(m, 0, 0, 3, PLAINS) == 4
    # another type is no answer; its own type and type 0 find it
    m = _grid(9, 9)
    m.tile(4, 5).Type = FOREST                    # N of (4, 4): a forest tile with a region
    m.tile(4, 5).Region = 8
    assert _region(m, 4, 4, 3, PLAINS) == 0
    assert _region(m, 4, 4, 3, FOREST) == 8
    assert _region(m, 4, 4, 3, 0) == 8
    # searched through: plains (4, 6) behind the forest ring around (4, 4) is still found (distance 2)
    m = _grid(9, 9)
    for x, y in ((4, 5), (4, 3), (5, 4), (5, 3), (3, 4), (3, 3)):
        m.tile(x, y).Type = FOREST
    m.tile(4, 6).Region = 2
    assert _region(m, 4, 4, 3, PLAINS) == 2
    # a forest leaf in the ring is no answer for plains, whatever its Region
    m.tile(4, 5).Region = 9
    assert _region(m, 4, 4, 3, PLAINS) == 2


def test_find_next_region_equals_a_recursive_transcription():
    """The iterative flood (no deep recursion: buildLabels' pass three floods radius 16 from every Region-0 land tile)
    visits in the order of the exe's recursion: same answer on random grids, radii, types and borders, all layouts."""
    import random
    rng = random.Random(20261026)
    for layout in ("even-q-up", "odd-q-down"):
        m = HexMap(None, 13, 11, layout)
        for _ in range(40):
            for t in m.tiles:
                t.Type = rng.choice((1, 2, 2, 5))
                t.Region = rng.choice((0, 0, 0, 0, 3, 4, 5, 9))
            for _ in range(6):
                start = rng.choice(m.tiles)
                radius = rng.choice((1, 2, 3, 5, 8))
                ttype = rng.choice((0, 2, 5))
                assert m.find_next_region(start, radius, ttype) == _flood_transcription(m, start, radius, ttype), \
                    (layout, start, radius, ttype)


def test_find_next_region_survives_a_deep_flood():
    """A flood that visits 3600 tiles one after the other (depth first goes as deep as the map is wide) must not run
    into Python's recursion limit: nothing but the far corner is a leaf."""
    m = HexMap(None, 60, 60, "even-q-up")
    m.tile(59, 59).Region = 5
    assert m.find_next_region(m.tile(0, 0), 500, 0) == 5
    m.tile(59, 59).Region = 0
    assert m.find_next_region(m.tile(0, 0), 500, 0) == 0


# 0x5526f0 / 0x552a70: the walk the exe makes for findNextTileOfType, as the tiles' Coords offsets from the centre
SECTOR_WALK_2 = [(0, 0),
                 (0, 1), (0, 2), (1, 1),            # sector N: from the N neighbour along N, then NE
                 (1, 0), (2, 0), (2, -1),           # NE: along NE, then SE
                 (1, -1), (2, -2), (1, -2),         # SE: along SE, then S
                 (0, -1), (0, -2), (-1, -1),        # S: along S, then SW
                 (-1, 0), (-2, 0), (-2, 1),         # SW: along SW, then NW
                 (-1, 1), (-2, 2), (-1, 2)]         # NW: along NW, then N


def _offsets(m, centre, tiles):
    cx, cy = R.get(R.get(centre, "Coords"), "X"), R.get(R.get(centre, "Coords"), "Y")
    return [(R.get(R.get(t, "Coords"), "X") - cx, R.get(R.get(t, "Coords"), "Y") - cy) for t in tiles]


def _walk_transcription(m, centre, radius):
    """0x5526f0 + 0x552a70 transcribed literally: a tile reached again is walked again (it pushes nothing new), so the
    walk is exponential in the radius. In the direction numbers a sector walk from the neighbour k goes along k and k + 1."""
    out = [centre]
    stamped = {centre}

    def step(t, a, b, code):
        if t not in stamped and code in (1, 3) and t is not centre:
            stamped.add(t)
            out.append(t)
        for d in (a, b):
            n = t.nb[d]
            if n is not None and m.distance(centre, n) <= radius:
                step(n, a, b, 1)
    for k in range(6):
        n = centre.nb[k]
        if n is not None:
            step(n, k, (k + 1) % 6, 1 if m.distance(centre, n) <= radius else 0)
    return out


def test_the_exes_sector_walk_order():
    """The candidates of findNextTileOfType are the exe's own walk (0x5526f0, with the centre): the centre, then one
    sector per neighbour in the order N, NE, SE, S, SW, NW, each a depth-first walk (pre-order) along the neighbour's
    direction and the next one clockwise. Radius 2: all 19 tiles, in this order. UNVERIFIED (0x5526f0 / 0x552a70, the
    order is not logged: only found / not found is): which decent tile among equally near ones becomes the label's."""
    m = _grid(13, 13)
    centre = m.tile(6, 6)
    assert _offsets(m, centre, m.exe_tiles_in_range(centre, 2)) == SECTOR_WALK_2
    # radius 3, sector N: pre-order, not ring by ring
    walk = _offsets(m, centre, m.exe_tiles_in_range(centre, 3))
    assert walk[1:7] == [(0, 1), (0, 2), (0, 3), (1, 2), (1, 1), (2, 1)]
    assert len(walk) == len(set(walk)) == 37
    assert _offsets(m, centre, m.exe_tiles_in_range(centre, 0)) == [(0, 0)]
    assert _offsets(m, centre, m.exe_tiles_in_range(centre, -1)) == [(0, 0)]


def test_the_sector_walk_equals_the_exes_walk_that_revisits():
    """The walk here skips a tile it already walked in the same sector (everything reachable from it is stamped after
    its first visit, so a revisit adds nothing): the same vector as the literal walk, on every tile of two small maps,
    in the interior and at the borders, in two layouts."""
    for layout in ("even-q-up", "odd-q-down"):
        m = HexMap(None, 9, 8, layout)
        for centre in m.tiles:
            for radius in (1, 2, 3, 4, 5):
                assert m.exe_tiles_in_range(centre, radius) == _walk_transcription(m, centre, radius), \
                    (layout, centre, radius)


def test_the_sector_walk_equals_the_literal_walk_at_radius_9():
    """The radius findNextTileOfType gets in buildLabels is 9: the same vector as the literal (revisiting) walk on a
    25 x 25 map from a few centres whose disc lies on the grid (no clipping), in both layouts. The literal walk is
    exponential in the radius, so only a few centres are tried."""
    for layout in ("even-q-up", "odd-q-down"):
        m = HexMap(None, 25, 25, layout)
        for x, y in ((12, 12), (11, 12), (12, 11), (11, 13)):
            centre = m.tile(x, y)
            assert all(t is not None for t in centre.nb)
            assert m.exe_tiles_in_range(centre, 9) == _walk_transcription(m, centre, 9), (layout, x, y)


def test_find_next_tile_of_type_is_the_exes_rule():
    """0x4f37f0: of the tiles within the radius (0x5526f0 with the centre: the start tile counts), a tile of the type
    qualifies only when its six neighbours exist (0x4f38f7..0x4f3922) and are of the type (0x4f3941); the one nearest to
    the start wins (score = hex distance, 0x4f38c2; strict < at 0x4f39c5: the first of equals in the walk's order).
    MEASURED on 80 logged maps (found / not found equal in all, 12 maps per setup with a failed label); the tile
    among equals and the centre rule are UNVERIFIED (not logged)."""
    m = _grid(13, 13)
    assert _label_spot(m, 6, 6, 9, PLAINS) == (6, 6)                    # the start tile itself
    # a forest tile S of (6, 6): the start and its S, SE, SW neighbours touch it, so they do not qualify. N, NE and
    # NW qualify, all at distance 1: a tie. This line pins the port's tie-break (the walk reaches N first; the old
    # ring order reached NW first), which is UNVERIFIED against the game.
    m.tile(6, 5).Type = FOREST
    assert _label_spot(m, 6, 6, 9, PLAINS) == (6, 7)
    # no tile whose six neighbours are all of the type: a line of plains in a forest
    m = _grid(13, 13, FOREST)
    for y in range(13):
        m.tile(6, y).Type = PLAINS
    assert _label_spot(m, 6, 6, 9, PLAINS) is None
    # a tile on the border never qualifies: a neighbour is off the grid
    assert _label_spot(_grid(3, 3), 1, 1, 9, PLAINS) == (1, 1)
    assert _label_spot(_grid(2, 2), 0, 0, 9, PLAINS) is None
    # out of the radius: the only decent spot (6, 6) is 3 away from (6, 3)
    m = _grid(13, 13, FOREST)
    for x, y in ((6, 6), (6, 7), (6, 5), (7, 6), (7, 5), (5, 6), (5, 5)):
        m.tile(x, y).Type = PLAINS
    assert _label_spot(m, 6, 3, 3, PLAINS) == (6, 6)
    assert _label_spot(m, 6, 3, 2, PLAINS) is None
    # the nearer of two decent spots wins, however the walk meets them: (6, 6) at 3 from (6, 3), a block around (6, 2)
    # at 1 (its centre (6, 2) has plains all around)
    for x, y in ((6, 2), (6, 3), (6, 1), (7, 2), (7, 1), (5, 2), (5, 1)):
        m.tile(x, y).Type = PLAINS
    assert _label_spot(m, 6, 3, 9, PLAINS) == (6, 2)
    # a failed search sets Result to null (0x4f3a22), also over an earlier answer
    result = SqTable()
    assert m.find_next_tile_of_type(m.tile(6, 3), 9, PLAINS, result) is True
    assert R.get(result, "Result") is m.tile(6, 2)
    assert m.find_next_tile_of_type(m.tile(6, 3), 9, 11, result) is False
    assert R.get(result, "Result") is None


def test_find_next_tile_of_type_wants_a_tile_inside_the_type(lab):
    """A "decent spot" for a region label: a tile of the type whose six neighbours are of it too."""
    e, m, out = lab
    e.vm.run('''
        for (local x = 0; x < 12; ++x) for (local y = 0; y < 10; ++y) ::World.getTileSquare(x, y).Type = 2;
        local r = {};
        print(::World.findNextTileOfType(::World.getTileSquare(5, 5), 9, 2, r) + " " + (r.Result == ::World.getTileSquare(5, 5)));
        local lone = ::World.getTileSquare(9, 5);
        lone.Type = 7;
        print(::World.findNextTileOfType(::World.getTileSquare(5, 5), 9, 7, {}));
        for (local i = 0; i < 6; ++i) lone.getNextTile(i).Type = 7;
        r = {};
        print(::World.findNextTileOfType(::World.getTileSquare(5, 5), 9, 7, r) + " " + (r.Result == lone));
        print(::World.findNextTileOfType(::World.getTileSquare(5, 5), 3, 7, {}) + " " + ::World.findNextTileOfType(::World.getTileSquare(5, 5), 9, 11, {}));
        for (local x = 0; x < 12; ++x) for (local y = 0; y < 10; ++y) ::World.getTileSquare(x, y).Type = 2;
        ::World.getTileSquare(0, 4).Type = 7;
        ::World.getTileSquare(0, 3).Type = 7;
        ::World.getTileSquare(0, 5).Type = 7;
        ::World.getTileSquare(1, 4).Type = 7;
        ::World.getTileSquare(1, 5).Type = 7;
        print(::World.findNextTileOfType(::World.getTileSquare(0, 4), 2, 7, {}));
    ''', "t.nut")
    assert out == ["true true", "false", "true true", "false false", "false"]       # last: at the map's edge


def test_update_tiles_with_heat_adds_like_legends_refine_settlements():
    m = HexMap(None, 20, 20, "even-q-up")
    a, b = m.tile(5, 5), m.tile(8, 6)
    m.update_tiles_with_heat([a, b], 6)
    for t in m.tiles:
        want = sum(6 - m.distance(s, t) for s in (a, b) if m.distance(s, t) <= 6)
        assert t.HeatFromSettlements == want


def test_the_other_world_natives_of_a_map_run(lab):
    e, m, out = lab
    e.vm.run('''
        print(::World.getNavigator() == ::World.getNavigator());
        print(::World.spawnRegionText("Darkwood", 1.0, 90.0, ::World.getTileSquare(1, 1).Pos) == null);
    ''', "t.nut")
    assert out == ["true", "true"]
    t = m.tile(4, 4)
    with pytest.raises(NotModelled):
        t.getDirectionTo(None, t)
    assert m.far_directions == 0
    t.getDirectionTo(None, m.tile(9, 9))
    assert m.far_directions == 1

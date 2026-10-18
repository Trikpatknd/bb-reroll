"""The tile world the map generator runs on: hex neighbours, distance, tile fields, World natives."""
import sys
from collections import deque
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbseed.engine import Engine, Stub
from bbseed.hexmap import LAYOUTS, HexMap
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


@pytest.mark.parametrize("layout", LAYOUTS)
def test_positions_are_regular_hexes_and_convert_back(layout):
    m = HexMap(None, 9, 8, layout)
    t = m.tile(4, 4)

    def dist(a, b):
        a, b = R.get(a, "Pos"), R.get(b, "Pos")
        return ((R.get(a, "X") - R.get(b, "X")) ** 2 + (R.get(a, "Y") - R.get(b, "Y")) ** 2) ** 0.5
    d0 = dist(t, m.neighbour(t, 0))
    assert d0 > 0 and all(abs(dist(t, m.neighbour(t, d)) - d0) < 1e-3 for d in range(6))
    # a position inside a tile gives that tile back; the centre of a tile is its Pos
    for x in range(9):
        for y in range(8):
            tile = m.tile(x, y)
            pos = R.get(tile, "Pos")
            c = m.world_to_tile(pos)
            assert m.tile_at_coords(R.get(c, "X"), R.get(c, "Y")) is tile
            # createVec(x, y) is a Stub with the fields X and Y; worldToTile reads whatever has them
            off = Stub(None, "vec", {"X": R.get(pos, "X") + 0.3 * d0, "Y": R.get(pos, "Y") - 0.2 * d0})
            near = m.world_to_tile(off)
            assert m.tile_at_coords(R.get(near, "X"), R.get(near, "Y")) is tile


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
    # ASSUMED: a Road detail makes HasRoad true; clear() / clearAllBut() take it away again
    t.spawnDetail(None, "world_road_01", 6, 1, False)
    assert t.HasRoad
    t.clear(None, 4 | 32)
    assert t.HasRoad
    t.clear(None, 1)
    assert not t.HasRoad
    t.spawnDetail(None, "world_road_01", 6, 1, False)
    t.clearAllBut(None, 1)
    assert t.HasRoad
    t.clearAllBut(None, 4)
    assert not t.HasRoad
    t.spawnDetail(None, "world_road_01", 6, 1, False)
    t.clear(None)
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

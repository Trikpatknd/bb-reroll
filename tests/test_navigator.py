"""The world navigator (bbseed/navigator.py): `findPath(...).isEmpty()` is true exactly when no route exists under
the cost table (0, negative, inf = blocked; the start tile is never entered) and RoadOnly. The route's tiles come
from a plain A* (UNVERIFIED: stage 2 copies the game's A*); the tests only ask that they are a route."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbseed.hexmap import HexMap, NotModelled
from bbseed.sq import runtime as R
from bbseed.sq.runtime import SqError

OCEAN, PLAINS, HILLS, SHORE = 1, 2, 4, 16
TYPES = 19                              # Const.World.TerrainType.COUNT
SYMBOLS = {"L": PLAINS, "W": OCEAN, "H": HILLS, "S": SHORE}


def small_map(rows):
    """A map from text rows: rows[y][x], L = Plains, W = Ocean, H = Hills, S = Shore (layout even-q-up)."""
    m = HexMap(None, len(rows[0]), len(rows), "even-q-up")
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            m.tile(x, y).Type = SYMBOLS[ch]
    m.touch()
    return m, m.navigator


def costs(**by_name):
    """An ActionPointCosts table: every type 0 (blocked) except the ones named."""
    table = [0] * TYPES
    for name, cost in by_name.items():
        table[{"plains": PLAINS, "ocean": OCEAN, "hills": HILLS, "shore": SHORE}[name]] = cost
    return table


def settings(nav, **fields):
    s = nav.createSettings(None)
    for k, v in fields.items():
        R.set_(s, k, v)
    return s


def set_field(m, x, y, field, value):
    R.set_(m.tile(x, y), field, value)        # the way a script writes it (tells the navigator)


def test_no_path_across_water_and_a_path_over_land():
    m, nav = small_map(["LLLWLLL", "LLLWLLL"])
    s = settings(nav, ActionPointCosts=costs(plains=1, ocean=-1))
    assert nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0).isEmpty(None)
    set_field(m, 3, 1, "Type", PLAINS)
    assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0).isEmpty(None)


# The road from (0, 0) to (6, 0) over the land bridge at (3, 1), tile by tile (even-q-up neighbours).
ROAD = [(1, 0), (2, 1), (3, 1), (4, 1), (5, 0), (6, 0)]


def test_road_only_needs_road_tiles():
    m, nav = small_map(["LLLWLLL", "LLLLLLL"])
    s = settings(nav, ActionPointCosts=costs(plains=1), RoadOnly=True)
    find = lambda: nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0)    # noqa: E731
    assert find().isEmpty(None)
    for x, y in ROAD[:-1]:
        set_field(m, x, y, "RoadDirections", 9)
        assert find().isEmpty(None)
    set_field(m, *ROAD[-1], "RoadDirections", 9)
    assert not find().isEmpty(None)
    set_field(m, 3, 1, "RoadDirections", 0)
    assert find().isEmpty(None)
    assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=costs(plains=1)),
                            0).isEmpty(None)


@pytest.mark.parametrize("cost", [0, -1, -1.5, math.inf, None, "10"])
def test_what_blocks_a_tile(cost):
    m, nav = small_map(["LLLHLLL", "LLLHLLL"])
    table = costs(plains=10)
    table[HILLS] = cost
    assert nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)
    table[HILLS] = 15.38
    assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)


def test_a_type_past_the_end_of_the_table_is_blocked():
    # buildAdditionalRoads' cost table has 18 entries: the 19th type (Oasis) is not in it
    m, nav = small_map(["LLLWLLL", "LLLWLLL"])
    table = costs(plains=1, ocean=1)[:OCEAN + 1]
    assert nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)


def test_the_start_tile_is_never_entered_but_the_goal_is():
    # a port's deep-sea route starts on its land tile, which the ship table blocks
    m, nav = small_map(["LWWWWWW", "LWWWWWW"])
    ship = costs(ocean=10, shore=100)
    assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 1), settings(nav, ActionPointCosts=ship), 0).isEmpty(None)
    assert nav.findPath(None, m.tile(6, 1), m.tile(0, 0), settings(nav, ActionPointCosts=ship), 0).isEmpty(None)


def test_the_route_is_a_chain_of_neighbours_from_after_the_start_to_the_goal():
    m, nav = small_map(["LLLWLLL", "LLLLLLL", "LLHHHLL"])
    path = nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=costs(plains=10, hills=60)), 0)
    tiles = []
    while path.getSize(None) >= 1:
        tiles.append(m.tile_at_coords(R.get(path.getCurrent(None), "X"), R.get(path.getCurrent(None), "Y")))
        path.pop(None)
    assert tiles[-1] is m.tile(6, 0) and m.tile(0, 0) not in tiles
    for a, b in zip([m.tile(0, 0)] + tiles, tiles):
        assert m.distance(a, b) == 1 and b.Type == PLAINS
    # the shortest way past the water at (3, 0) is as long as the distance (the rows zigzag), over (3, 1)
    assert len(tiles) == m.distance(m.tile(0, 0), m.tile(6, 0)) and m.tile(3, 1) in tiles
    with pytest.raises(NotModelled):
        path.pop(None)


def test_a_road_makes_its_tiles_cheaper():
    m, nav = small_map(["LLLLLLL", "LLLLLLL", "LLLLLLL"])
    for x in range(7):
        set_field(m, x, 2, "RoadDirections", 9)
    direct = nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=costs(plains=10)), 0)
    assert len(direct.tiles()) == 6 and not any(t.RoadDirections for t in direct.tiles())
    s = settings(nav, ActionPointCosts=costs(plains=10), RoadMult=0.15)
    detour = nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0).tiles()
    # one step up to the road and two down cost 30, seven road tiles 10.5: cheaper than the 60 of the direct route
    assert sum(1 for t in detour if t.RoadDirections) == 7 and len(detour) == 10


def test_what_the_navigator_does_not_model_is_an_error():
    m, nav = small_map(["LLL", "LLL"])
    s = settings(nav, ActionPointCosts=costs(plains=1))
    with pytest.raises(NotModelled):
        nav.findPath(None, m.tile(0, 0), m.tile(0, 0), s, 0)         # a route to itself
    with pytest.raises(NotModelled):
        nav.findPath(None, m.tile(0, 0), m.tile(2, 1), s, 50)        # a maximum cost
    with pytest.raises(NotModelled):
        nav.findPath(None, m.tile(0, 0), m.tile(2, 1), settings(nav, ActionPointCosts=costs(plains=1), HeatCost=100), 0)
    with pytest.raises(SqError):
        R.set_(s, "NoSuchField", 1)
    assert R.get(nav.createSettings(None), "RoadOnly") is False


def test_the_scripts_ask_it_through_world_get_navigator():
    from bbseed.engine import Engine
    e = Engine([])
    m = HexMap(e, 7, 2, "even-q-up")
    m.install(e.World)
    out = []
    e.vm.print_fn = out.append
    e.vm.run('''
        for (local x = 0; x < 7; ++x) for (local y = 0; y < 2; ++y) ::World.getTileSquare(x, y).Type = x == 3 ? 1 : 2;
        local nav = ::World.getNavigator().createSettings();
        local costs = array(19, 0); costs[2] = 10;
        nav.ActionPointCosts = costs;
        local a = ::World.getTileSquare(0, 0), b = ::World.getTileSquare(6, 0);
        print(::World.getNavigator().findPath(a, b, nav, 0).isEmpty());
        ::World.getTileSquare(3, 1).Type = 2;
        local path = ::World.getNavigator().findPath(a, b, nav, 0);
        print(path.isEmpty());
        local n = 0;
        local last = null;
        while (path.getSize() >= 1) { last = ::World.getTile(path.getCurrent()); path.pop(); ++n; }
        print(n + " " + (last == b));
    ''', "t.nut")
    assert out == ["true", "false", "6 true"]          # past the water over (3, 1), as long as the distance

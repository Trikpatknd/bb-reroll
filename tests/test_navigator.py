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


# ---------------------------------------------------------------- the terrain types of Legends (final review 89)
SWAMP_GREEN, SWAMP_FOREST, OASIS = 19, 20, 18
SYMBOLS.update({"G": SWAMP_GREEN, "F": SWAMP_FOREST, "O": OASIS})


def legends_map(rows, nav_types=21):
    """small_map with a navigator that has `nav_types` terrain types (Legends: 21). The rows may name the types
    Legends adds: G = SwampGreen, F = SwampForest, and O = Oasis (the 19th type of the base game)."""
    from bbseed.navigator import Navigator
    m, _nav = small_map(rows)
    m._navigator = nav = Navigator(m, nav_types)
    return m, nav


def test_the_navigator_knows_the_games_terrain_count():
    """HexMap.navigator reads Const.World.TerrainType.COUNT of the loaded scripts (21 with Legends, 19 in the base
    game); with no scripts (a bare engine, no engine) it is the base game's 19; a bad count is not modelled."""
    from bbseed.engine import Engine
    from bbseed.navigator import BASE_TYPES, NavError, terrain_count
    assert BASE_TYPES == 19 and terrain_count(None) == 19 and HexMap(None, 2, 2, "even-q-up").navigator.ntypes == 19
    e = Engine([])
    assert terrain_count(e) == 19
    e.vm.run("::Const <- { World = { TerrainType = { COUNT = 21 } } };", "t.nut")
    assert terrain_count(e) == 21
    m = HexMap(e, 2, 2, "even-q-up")
    assert m.navigator.ntypes == 21 and m.navigator is m.navigator
    for bad in ("18", '"many"'):
        e.vm.run("::Const.World.TerrainType.COUNT = %s;" % bad, "t2.nut")
        with pytest.raises(NavError, match="TerrainType.COUNT"):
            terrain_count(e)
        with pytest.raises(NotModelled):
            HexMap(e, 2, 2, "even-q-up").navigator


def test_a_tile_of_a_type_legends_adds_that_the_cost_table_has_no_entry_for_is_not_modelled():
    """MEASURED (Legends 19.4.22): the scripts' cost tables have 19 entries, Legends' COUNT is 21. A map without such
    tiles (all 3 + 40 maps looked at) is answered as before; one with such a tile raises instead of guessing."""
    from bbseed.navigator import NavError
    table = costs(plains=10)                                    # 19 entries: no entry for types 19 and 20
    for symbol in ("G", "F"):
        m, nav = legends_map(["LLLLLLL", "LLLLLLL"])
        s = settings(nav, ActionPointCosts=table)
        assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0).isEmpty(None)
        R.set_(m.tile(3, 1), "Type", {"G": SWAMP_GREEN, "F": SWAMP_FOREST}[symbol])
        with pytest.raises(NavError, match="terrain type %d has no entry" % {"G": 19, "F": 20}[symbol]):
            nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0)
        with pytest.raises(NavError):                           # again: a half-made answer is not kept
            nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0)
        R.set_(m.tile(3, 1), "Type", PLAINS)                    # the tile is gone: answered again
        assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0).isEmpty(None)


def test_a_table_with_entries_for_every_type_answers_for_the_types_legends_adds():
    m, nav = legends_map(["LLLLLLL", "LLLLLLL"])
    R.set_(m.tile(3, 0), "Type", SWAMP_GREEN)
    R.set_(m.tile(3, 1), "Type", SWAMP_FOREST)
    table = costs(plains=10) + [0, 0]                           # 21 entries: both new types blocked
    s = settings(nav, ActionPointCosts=table)
    assert nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0).isEmpty(None)
    table[SWAMP_GREEN] = 15.0                                   # one of them enterable
    assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)
    table = costs(plains=10) + [12]                             # 20 entries: no entry for SwampForest only
    with pytest.raises(NotModelled, match="terrain type 20"):
        nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=table), 0)


def test_a_type_of_the_base_game_past_the_end_of_a_table_is_still_blocked_on_a_legends_map():
    """buildAdditionalRoads' table has 18 entries and every map has Oasis tiles (type 18): that rule is as it was."""
    m, nav = legends_map(["LLLOLLL", "LLLOLLL"])
    table = costs(plains=10)[:OASIS]                            # 18 entries
    assert nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)
    table = costs(plains=10)
    table[OASIS] = 10
    assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)

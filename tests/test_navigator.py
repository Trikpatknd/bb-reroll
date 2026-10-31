"""The world navigator (bbseed/navigator.py): `findPath(...).isEmpty()` is true exactly when no route exists under
the cost table (0, negative, inf = blocked; the start tile is never entered) and RoadOnly. The route's tiles come
from the game's own search (copied from the exe, MEASURED on 80 maps); most tests here only ask that they are a route,
the two "games_route" tests pin the exact tiles of logged routes."""
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


def test_a_type_past_the_end_of_the_table_costs_2():
    """MEASURED in the exe (createSettings 0x4ea2b0 fills all 32 table entries with 2; a shorter array only writes its
    own) and in the game's roads: buildAdditionalRoads' 18-entry table has no entry for Oasis, and its roads cross
    Oasis tiles. A type past the end is enterable at cost 2, not blocked (this test said "blocked" while that rule was
    still unverified)."""
    m, nav = small_map(["LLLWLLL", "LLLWLLL"])
    table = [0, 1]                                  # entries for types 0 and 1 (Ocean) only: Plains is past the end
    s = settings(nav, ActionPointCosts=table)
    assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0).isEmpty(None)
    table = [0, 0]                                  # the ocean blocked: the land is still enterable, the water is not
    assert nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)
    assert not nav.findPath(None, m.tile(0, 0), m.tile(2, 1), settings(nav, ActionPointCosts=table), 0).isEmpty(None)


def test_the_start_tile_is_never_entered_but_the_goal_is():
    # a port's deep-sea route starts on its land tile, which the ship table blocks
    m, nav = small_map(["LWWWWWW", "LWWWWWW"])
    ship = costs(ocean=10, shore=100)
    assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 1), settings(nav, ActionPointCosts=ship), 0).isEmpty(None)
    # the other way round the goal is a land tile (blocked for ships): since the native probe fix the search accepts it
    # next to an ocean tile it expanded, so isEmpty() is false (before: the component rule said true); walled off by
    # land the same question is empty
    assert not nav.findPath(None, m.tile(6, 1), m.tile(0, 0), settings(nav, ActionPointCosts=ship), 0).isEmpty(None)
    m, nav = small_map(["LLWWWWW", "LLWWWWW"])
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


def test_a_type_of_the_base_game_past_the_end_of_a_table_is_enterable_on_a_legends_map():
    """buildAdditionalRoads' table has 18 entries and every map has Oasis tiles (type 18): they cost 2 (MEASURED, see
    test_a_type_past_the_end_of_the_table_costs_2); an explicit 0 entry blocks them."""
    m, nav = legends_map(["LLLOLLL", "LLLOLLL"])
    table = costs(plains=10)[:OASIS]                            # 18 entries
    assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)
    table = costs(plains=10)                                    # 19 entries, Oasis 0
    assert nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)
    table[OASIS] = 10
    assert not nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)


# ---------------------------------------------------------------- the route override (stage 2 Task 2: road fitting)
def test_route_override_used():
    """`route_override` (the lab's hook for replaying logged routes) supplies the route tiles when it returns a list."""
    m, nav = small_map(["LLLLL", "LLLLL", "LLLLL", "LLLLL", "LLLLL"])
    seen = []
    fixed = [m.tile(1, 0), m.tile(2, 0), m.tile(3, 0)]

    def override(start, goal, info):
        seen.append((start, goal, info))
        return fixed

    nav.route_override = override
    path = nav.findPath(None, m.tile(0, 0), m.tile(4, 4), settings(nav, ActionPointCosts=costs(plains=10)), 0)
    assert not path.isEmpty(None) and path.getSize(None) == 3
    assert R.get(path.getCurrent(None), "X") == R.get(m.tile(1, 0)._coords(), "X")
    start, goal, info = seen[0]
    assert start is m.tile(0, 0) and goal is m.tile(4, 4)
    assert info["nav"] is nav and info["road_only"] is False and info["road_mult"] == 1.0
    assert info["blocked"] == frozenset(range(TYPES)) - {PLAINS} and len(info["costs"]) == TYPES


def test_route_override_none_falls_back():
    """An override that returns None leaves the route to the A* (the same tiles as with no override)."""
    m, nav = small_map(["LLLLL", "LLLLL", "LLLLL", "LLLLL", "LLLLL"])
    s = settings(nav, ActionPointCosts=costs(plains=10))
    plain = nav.findPath(None, m.tile(0, 0), m.tile(4, 4), s, 0).tiles()
    nav.route_override = lambda start, goal, info: None
    fell_back = nav.findPath(None, m.tile(0, 0), m.tile(4, 4), s, 0).tiles()
    assert fell_back and [id(t) for t in fell_back] == [id(t) for t in plain]


# ---------------------------------------------------------------- the game's own search (stage 2 B1 Task 5)
# buildRoads' settings: its 19-entry cost table and RoadMult 0.15 (the road_fit module of bb_seedlab calls them COSTS)
BUILD_ROADS_COSTS = [0, 0, 10, 50, 60, 40, 40, 40, 40, 0, 1, 50, 30, 30, 10, 10, 0, 10, 10]
TYPE_CHARS = "0123456789abcdefghi"                      # one character per terrain type 0..18


def window_map(types, roads):
    """A map cut out of a real one: types = one string per row (TYPE_CHARS), roads = '1' where the tile has a road.
    The x of the window's first column is even in the real map, so the hex layout is the same."""
    m = HexMap(None, len(types[0]), len(types), "even-q-up")
    for y, (trow, rrow) in enumerate(zip(types, roads)):
        for x, (tc, rc) in enumerate(zip(trow, rrow)):
            m.tile(x, y).Type = TYPE_CHARS.index(tc)
            m.tile(x, y).RoadDirections = 9 if rc == "1" else 0
    m.touch()
    return m, m.navigator


def build_roads_route(m, nav, start, goal):
    s = settings(nav, ActionPointCosts=BUILD_ROADS_COSTS, RoadMult=0.15)
    path = nav.findPath(None, m.tile(*start), m.tile(*goal), s, 0)
    return [(t.x, t.y) for t in path.tiles()]


# MEASURED (2026-10-25): Legends job 0 (seed 1234567890), buildRoads call 12, (27,77) -> (24,88) on the real map, cut to
# the 26 x 32 tiles around it (the rest of the map is ocean here: a smaller window changes which of the equal-cost routes
# the heap order picks). Two routes cost the same; the game takes (22,85)-(23,85)-(23,86), the lab's old A* took
# (22,85)-(22,86)-(23,86). The tiles are the game's own logged route (shifted by the window's origin (12, 67)).
LEGENDS_TYPES = [
    "11111111111112221111111111", "11111111111222222211111111", "11111111144444444422111111",
    "11111119994444444222881111", "11111999994222444222888811", "11149999942222444222228888",
    "12444999442228454522222288", "22444494422522555552222283", "22424222422522255888222255",
    "88222222222552225582222255", "88228882222255225822222255", "88228882222225522222222222",
    "82228282252555542222222222", "22222224555555544922222233", "55244944455555449992222233",
    "55549994455555449994255538", "22549999995553444444445481", "22444999995553499999499111",
    "22224494942259999999499111", "22222244482249999999949111", "22222224888244999999942111",
    "42222444888224449499942111", "44254999444822444499942111", "45554999494222444444442111",
    "14554399999225554442444111", "19994499999422554242334111", "11994444999422222222334111",
    "11119444999442222225511111", "11111144422248282221111111", "11111111422288888111111111",
    "11111111112888811111111111", "11111111111181111111111111"]
LEGENDS_ROADS = ["0" * 26] * 2 + [
    "00000000000000000001000000", "00000000000000000001000000", "00000000000000000001000000",
    "00000000000000000000110000", "00000000000000000000001100", "00000000000000000000000100",
    "00000000000000000000000100", "00000000000000000000011100", "00000000000000010001100100",
    "00000000000000001110000011"] + ["0" * 26] * 20
LEGENDS_ROUTE = [(14, 10), (13, 10), (12, 11), (11, 11), (10, 12), (10, 13), (10, 14), (10, 15), (10, 16), (10, 17),
                 (10, 18), (11, 18), (11, 19), (11, 20), (12, 21)]


def test_the_games_route_on_a_legends_map_window():
    m, nav = window_map(LEGENDS_TYPES, LEGENDS_ROADS)
    assert build_roads_route(m, nav, (15, 10), (12, 21)) == LEGENDS_ROUTE


# MEASURED (2026-10-25): Vanilla job 0 (seed 7100000001), buildRoads call 8, (105,67) -> (110,55) on the real map, cut to
# the 23 x 30 tiles around it (origin (96, 47)); the game's route runs along road pieces from earlier calls.
VANILLA_TYPES = [
    "1111111111111fff1111111", "11111111111fffffff11111", "111111111fffffffffff111",
    "111111144ffffffffff4ff1", "111111ff4fffffffffff4ff", "111111ffffffffffff4f4ff",
    "111111fffffffffff4fffff", "111111ffffffffffff4ffff", "111111fffffffffffffffff",
    "111111fffffffffffffffff", "111111fff9ffffffffffff9", "111111f99994fffffffff49",
    "1111119999944ffffffff44", "1111119994444ffffffffff", "111114999222ffffffff44f",
    "1114ff9992224fffffffff4", "1774444442224ffffffffff", "14494444f42222fffffffff",
    "14999444422222fff94944f", "14999942272222f49999944", "17779992227222249999944",
    "17729992222222224999422", "12222242222222222494222", "12222222222222224944222",
    "12222222222272229994211", "11222222272222229991111", "11112222225555255111111",
    "11111152222255511111111", "11111111222221111111111", "11111111112111111111111"]
VANILLA_ROADS = [
    "0" * 23] * 4 + [
    "00000000000000000000011", "00000000000000000101010", "00000000000000011010100",
    "00000000000000100000000", "00000000000000100000000"] + ["0" * 23] * 7 + [
    "00000000000000000001000", "00000000000000000110110", "00000000000000011000001",
    "00000000000001100000000", "00000000010110000000000", "00000000001000000000000"] + ["0" * 23] * 8
VANILLA_ROUTE = [(10, 21), (11, 20), (12, 20), (13, 19), (14, 19), (14, 18), (14, 17), (14, 16), (14, 15), (14, 14),
                 (14, 13), (14, 12), (14, 11), (14, 10), (14, 9), (14, 8)]


def test_the_games_route_on_a_vanilla_map_window():
    m, nav = window_map(VANILLA_TYPES, VANILLA_ROADS)
    assert build_roads_route(m, nav, (9, 20), (14, 8)) == VANILLA_ROUTE


def test_the_window_data_has_the_size_the_comment_says():
    assert (len(LEGENDS_TYPES), {len(r) for r in LEGENDS_TYPES}) == (32, {26})
    assert [len(LEGENDS_ROADS), {len(r) for r in LEGENDS_ROADS}] == [32, {26}]
    assert (len(VANILLA_TYPES), {len(r) for r in VANILLA_TYPES}) == (30, {23})
    assert [len(VANILLA_ROADS), {len(r) for r in VANILLA_ROADS}] == [30, {23}]


def test_route_tiles_for_what_no_map_script_asks_are_not_modelled():
    """RoadOnly and StopAtRoad route requests (the scripts only ask isEmpty() with RoadOnly, and no script sets StopAtRoad
    to true) raise NavError when the tiles are asked for; the empty / non-empty answer stays the component rule."""
    from bbseed.navigator import NavError
    m, nav = small_map(["LLLLLLL", "LLLLLLL"])
    for x in range(7):
        set_field(m, x, 0, "RoadDirections", 9)
    for field in ("RoadOnly", "StopAtRoad"):
        s = settings(nav, ActionPointCosts=costs(plains=10), **{field: True})
        path = nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0)
        assert not path.isEmpty(None)
        with pytest.raises(NavError, match="not modelled"):
            path.getSize(None)
        with pytest.raises(NotModelled):
            path.getCurrent(None)
    # the same question without them gives tiles
    s = settings(nav, ActionPointCosts=costs(plains=10))
    assert nav.findPath(None, m.tile(0, 0), m.tile(6, 0), s, 0).getSize(None) >= 6


def test_a_table_entry_that_is_not_a_whole_number_is_not_modelled_for_route_tiles():
    """The exe's cost table holds ints (settings x 10); how it takes 2.5 is not read: reachability is still answered."""
    from bbseed.navigator import NavError
    m, nav = small_map(["LLLLLLL", "LLLLLLL"])
    path = nav.findPath(None, m.tile(0, 0), m.tile(6, 0), settings(nav, ActionPointCosts=costs(plains=2.5)), 0)
    assert not path.isEmpty(None)
    with pytest.raises(NavError, match="not modelled"):
        path.getSize(None)


def test_route_tiles_to_a_goal_of_a_blocked_type_are_the_exes_search():
    """The exe accepts the goal when an expanded tile is next to it, before the closed and cost checks (nav_exe.py:230-232):
    a goal on a cost-0 type (buildAdditionalRoads' attached locations on mountains) gets route tiles that end on it, and
    `isEmpty()` is false then (native probe 2026-10-31: the game's isEmpty is the search's answer). A goal no expanded
    tile touches, and an enterable goal nobody reaches, have no tiles (the second is not even searched); a goal of
    terrain type 0 is empty up front."""
    m, nav = small_map(["LLLLH", "LLLLL", "LLLLL"])
    s = settings(nav, ActionPointCosts=costs(plains=10))                # Hills cost 0: blocked
    start, goal = m.tile(0, 0), m.tile(4, 0)
    path = nav.findPath(None, start, goal, s, 0)
    assert not path.isEmpty(None)
    tiles = path.tiles()
    assert tiles[-1] is goal and len(tiles) >= m.distance(start, goal) and path.getSize(None) == len(tiles)
    assert all(t.Type == PLAINS for t in tiles[:-1])
    for a, b in zip([start] + tiles, tiles):
        assert m.distance(a, b) == 1
    assert R.get(path.getCurrent(None), "X") == R.get(tiles[0]._coords(), "X")
    # an island of one blocked tile in the sea: no expanded tile touches it, so the search ends empty
    m, nav = small_map(["LLWWW", "LLWHW", "LLWWW", "LLWWW"])
    s = settings(nav, ActionPointCosts=costs(plains=10))
    path = nav.findPath(None, m.tile(0, 0), m.tile(3, 1), s, 0)
    assert path.isEmpty(None) and path.getSize(None) == 0
    with pytest.raises(NotModelled):
        path.getCurrent(None)
    # an enterable goal behind the water: empty, and no search runs for it
    m, nav = small_map(["LLWLL", "LLWLL"])
    s = settings(nav, ActionPointCosts=costs(plains=10))
    before = nav.searches
    path = nav.findPath(None, m.tile(0, 0), m.tile(4, 0), s, 0)
    assert path.isEmpty(None) and path.getSize(None) == 0 and nav.searches == before
    # a goal of terrain type 0 next to an expanded tile: the exe answers empty up front
    m, nav = small_map(["LLLLH", "LLLLL", "LLLLL"])
    m.tile(4, 0).Type = 0
    m.touch()
    path = nav.findPath(None, m.tile(0, 0), m.tile(4, 0), settings(nav, ActionPointCosts=costs(plains=10)), 0)
    assert path.isEmpty(None) and path.getSize(None) == 0


def test_is_empty_for_a_goal_of_a_blocked_type_is_the_searchs_answer():
    """MEASURED (native probe 2026-10-31, kind n1: 202 calls, the game's isEmpty() was false on 109 where the component
    rule said true; the tiles equal the search's on all 202): a blocked-type goal that a tile the search expands touches
    is found, with its tiles; one the search cannot touch (walled off) is empty; so is a goal of terrain type 0. An
    enterable goal keeps the component rule (n3 121 of 121)."""
    # touched by a reachable tile (also when it is next to the start)
    m, nav = small_map(["LLLLH", "LLLLL", "LLLLL"])
    s = settings(nav, ActionPointCosts=costs(plains=10))                # Hills cost 0: blocked
    path = nav.findPath(None, m.tile(0, 0), m.tile(4, 0), s, 0)
    assert not path.isEmpty(None) and path.tiles()[-1] is m.tile(4, 0) and path.getSize(None) >= 4
    path = nav.findPath(None, m.tile(3, 0), m.tile(4, 0), s, 0)
    assert not path.isEmpty(None) and path.tiles() == [m.tile(4, 0)]
    # the same answer with every blocking kind of table entry (0, negative, inf)
    for cost in (0, -1, math.inf):
        table = costs(plains=10)
        table[HILLS] = cost
        assert not nav.findPath(None, m.tile(0, 0), m.tile(4, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)
    # walled off: a hill island in the sea, nothing the search enters touches it
    m, nav = small_map(["LLWWW", "LLWHW", "LLWWW", "LLWWW"])
    s = settings(nav, ActionPointCosts=costs(plains=10))
    path = nav.findPath(None, m.tile(0, 0), m.tile(3, 1), s, 0)
    assert path.isEmpty(None) and path.getSize(None) == 0
    # ... and a land bridge to it makes it reachable (the answer follows the map, not a cache)
    set_field(m, 2, 1, "Type", PLAINS)
    assert not nav.findPath(None, m.tile(0, 0), m.tile(3, 1), s, 0).isEmpty(None)
    # the goal's neighbours are blocked as well: nothing touches it
    m, nav = small_map(["LLLWH", "LLLWW", "LLLLL"])
    s = settings(nav, ActionPointCosts=costs(plains=10))
    assert nav.findPath(None, m.tile(0, 0), m.tile(4, 0), s, 0).isEmpty(None)
    # a goal of terrain type 0 stays empty up front, even next to a reachable tile
    m, nav = small_map(["LLLLH", "LLLLL", "LLLLL"])
    m.tile(4, 0).Type = 0
    m.touch()
    assert nav.findPath(None, m.tile(0, 0), m.tile(4, 0), settings(nav, ActionPointCosts=costs(plains=10)), 0).isEmpty(None)
    # an enterable goal behind the water: still the component rule (empty), and still not searched
    m, nav = small_map(["LLWLL", "LLWLL"])
    s = settings(nav, ActionPointCosts=costs(plains=10))
    before = nav.searches
    assert nav.findPath(None, m.tile(0, 0), m.tile(4, 0), s, 0).isEmpty(None) and nav.searches == before
    # a blocked-type goal with RoadOnly / StopAtRoad is UNVERIFIED (0x4ea87e / 0x4ea88d; no script asks): NavError
    from bbseed.navigator import NavError
    m, nav = small_map(["LLLLH", "LLLLL"])
    for x in range(5):
        set_field(m, x, 1, "RoadDirections", 9)
    for field in ("RoadOnly", "StopAtRoad"):
        s = settings(nav, ActionPointCosts=costs(plains=10), **{field: True})
        with pytest.raises(NavError, match="blocked terrain type"):
            nav.findPath(None, m.tile(0, 1), m.tile(4, 0), s, 0)


def test_a_goal_of_terrain_type_0_is_empty_up_front_whatever_the_table_says():
    """0x4ea50c (MEASURED, native probe n2): with a maximum of 0 a goal of terrain type 0 answers empty before anything
    else is read, also when the cost table lets type 0 be entered (no NavError, no search, no tiles)."""
    m, nav = small_map(["LLLLL", "LLLLL", "LLLLL"])
    m.tile(4, 0).Type = 0
    m.touch()
    for cost in (10, 1, 2.5, 0, -1, math.inf):          # type 0 enterable, blocked in every way, or fractional
        table = costs(plains=10)
        table[0] = cost
        before = nav.searches
        path = nav.findPath(None, m.tile(0, 0), m.tile(4, 0), settings(nav, ActionPointCosts=table), 0)
        assert path.isEmpty(None) and path.getSize(None) == 0 and path.tiles() == [] and nav.searches == before
    # also next to the start, and with RoadOnly / StopAtRoad (the check is first)
    table = costs(plains=10)
    table[0] = 10
    for extra in ({}, {"RoadOnly": True}, {"StopAtRoad": True}):
        s = settings(nav, ActionPointCosts=table, **extra)
        assert nav.findPath(None, m.tile(3, 0), m.tile(4, 0), s, 0).isEmpty(None)
    # a goal of another type is not touched by this: the same table, an enterable goal is found
    assert not nav.findPath(None, m.tile(0, 0), m.tile(3, 0), settings(nav, ActionPointCosts=table), 0).isEmpty(None)


def test_is_empty_for_a_blocked_goal_equals_the_searchs_result_on_random_maps():
    """isEmpty() for a blocked-type goal comes from the components (touched()); the exe's search must end on the goal in
    exactly those cases (the tiles are asked for and `compute` raises if the search disagrees with a found path)."""
    import random
    rng = random.Random(7)
    checked = [0, 0]
    for _ in range(60):
        rows = ["".join(rng.choice("LLLWHS") for _ in range(9)) for _ in range(7)]
        m, nav = small_map(rows)
        table = costs(plains=10, shore=rng.choice([0, 20]), ocean=rng.choice([0, 30]))   # Hills (and sometimes more) blocked
        s = settings(nav, ActionPointCosts=table)
        tiles = m.tiles
        for _ in range(12):
            a, b = rng.sample(tiles, 2)
            if b.Type in (PLAINS,) or (b.Type == SHORE and table[SHORE]) or (b.Type == OCEAN and table[OCEAN]):
                continue                                            # an enterable goal: not this rule
            path = nav.findPath(None, a, b, s, 0)
            searched = nav.astar(a, b, list(table), frozenset(t for t in range(TYPES) if not table[t]), False, 1.0)
            assert (not path.isEmpty(None)) == bool(searched)
            assert path.tiles() == searched
            checked[not path.isEmpty(None)] += 1
    assert checked[0] > 20 and checked[1] > 20                      # both answers were exercised


def test_a_blocked_goal_is_answered_with_a_fractional_cost_table_but_has_no_tiles():
    """TerrainTypeNavCost holds fractions: the search's answer does not depend on them, its tiles are not modelled."""
    from bbseed.navigator import NavError
    m, nav = small_map(["LLLLH", "LLLLL"])
    path = nav.findPath(None, m.tile(0, 0), m.tile(4, 0), settings(nav, ActionPointCosts=costs(plains=2.5)), 0)
    assert not path.isEmpty(None)
    with pytest.raises(NavError, match="not modelled"):
        path.getSize(None)


class _HeapItem:
    """An open-list stand-in: the heap compares f alone; the name shows the order."""

    def __init__(self, name, f):
        self.name, self.f = name, f


def test_heap_tie_order_pushes():
    """Five pushes with equal f (_heap_push 0x4cc580: a value climbs only past a STRICTLY larger parent, so the vector
    stays A B C D E), then five pops (_heap_pop: last value out, the hole sinks from the root via _heap_sift 0x4cc4f0,
    which takes the RIGHT child unless right.f > left.f, then the value climbs). Worked by hand:
      pop 1: [A B C D E] val E, bottom 4, max_non_leaf 1: idx 0 -> 2 (C, tie -> right), hole 2; 2 != 1; E climbs: no
             -> [C B E D], out A
      pop 2: val D, bottom 3, max_non_leaf 1: idx 0 -> 2 (E), hole 2 -> [E B D], out C
      pop 3: val D, bottom 2, max_non_leaf 0: no loop; idx 0 == 0 and bottom even: hole <- a[1] = B, hole 1; D there
             -> [B D], out E
      pop 4: val D, bottom 1: D to the root -> [D], out B;   pop 5: out D.
    A FIFO tie rule would give A B C D E; a LIFO one E D C B A."""
    from bbseed.navigator import _heap_pop, _heap_push

    a = []
    for k in [_HeapItem(name, 0) for name in "ABCDE"]:
        a.append(k)
        _heap_push(a, len(a) - 1, 0, k)
    assert [k.name for k in a] == list("ABCDE")
    assert "".join(_heap_pop(a).name for _ in range(5)) == "ACEBD"


def test_heap_tie_order_make_heap():
    """make_heap (_heap_make 0x4cc310) on [X1 Y0 Z0 W0] (letter = name, digit = f), worked by hand:
      hole 1: val Y, bottom 4, max_non_leaf 1: no loop; idx 1 == 1, bottom even: hole <- a[3] = W, hole 3; Y climbs from 3
              to top 1: parent a[1] = W, 0 > 0 no -> [X W Z Y]
      hole 0: val X: idx 0 -> 2 (Z vs W tie -> right Z), hole 2; X climbs: a[0] = Z, 0 > 1 no -> [Z W X Y]
    pops: val Y, bottom 3: idx 0 -> 2 (X1 > W0 -> left W), hole 1; Y stays -> [W Y X], out Z;
          val X, bottom 2: hole <- a[1] = Y, X at 1 -> [Y X], out W;  then Y, X."""
    from bbseed.navigator import _heap_make, _heap_pop

    a = [_HeapItem(name, f) for name, f in [("X", 1), ("Y", 0), ("Z", 0), ("W", 0)]]
    _heap_make(a)
    assert [k.name for k in a] == list("ZWXY")
    assert "".join(_heap_pop(a).name for _ in range(4)) == "ZWYX"

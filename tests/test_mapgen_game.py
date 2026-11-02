"""The game's own campaign start, run in the lab up to the generated world (Legends 19.4.22 + MSU 1.9.0 +
Modern Hooks 0.6.0 on Battle Brothers 1.5.2.3). The labs (`legends_lab`, `vanilla_lab`) are the session's
shared ones (conftest.py): booting one takes ~15 s. Skipped when that game / those mods are not installed.
Every test that builds a map or an "accepted" stop is marked slow (it runs with --full)."""
import pytest

from bbseed import profiles

FOUND = profiles.installed_summary()
HAVE_GAME = FOUND is not None and FOUND["game_version"] == "1.5.2.3"
HAVE_LEGENDS = HAVE_GAME and any("mod_legends-19.4.22" in m for m in FOUND["mods"]) and any("1.9.0" in m for m in FOUND["mods"])


def _natives(eng):
    """The natives a map run replaces while it runs: ::World's, ::Math's and the root table's."""
    from bbseed.sq.runtime import NativeFn
    return {(name, k): v for name, table in (("World", eng.World), ("Math", eng.Math), ("root", eng.root))
            for k, v in table.d.items() if type(v) is NativeFn}


@pytest.mark.edge
@pytest.mark.slow
def test_world_map_leaves_roster_path_unchanged(legends_lab):
    """The search's sift loop reuses the world state (fresh=False); a map run must not leave it a
    half-started campaign."""
    before = legends_lab.roster("1234567890", "trader_scenario", fresh=True)
    fresh = legends_lab.roster("0000000001", "trader_scenario", fresh=True)
    natives, world_keys = _natives(legends_lab.lab.eng), set(legends_lab.lab.eng.World.d)
    legends_lab.world_map("1234567890", stop_at="accepted")
    assert _natives(legends_lab.lab.eng) == natives and set(legends_lab.lab.eng.World.d) == world_keys, \
        "the run takes its natives (tiles, seed wrappers, top bar ...) away again"
    assert legends_lab.roster("0000000001", "trader_scenario", fresh=False) == fresh
    assert legends_lab.roster("1234567890", "trader_scenario", fresh=True) == before


@pytest.mark.edge
@pytest.mark.slow
def test_a_spawn_run_leaves_the_roster_path_unchanged(legends_lab):
    """A run on through the start (Deserters: the recruits are made in onSpawnPlayer and read from the player roster)
    takes its natives and its recruits away again: the next roster of the shared lab is the fresh one, on a new world
    state and on the reused one."""
    fresh = legends_lab.roster("0000000001", "trader_scenario", fresh=True)
    natives, world_keys = _natives(legends_lab.lab.eng), set(legends_lab.lab.eng.World.d)
    out = legends_lab.world_map("1234567890", "deserters_scenario", stop_at="spawn")
    assert len(out["roster"]) == 3 and out["spawn"]["loop"] >= 1
    assert out["map"]["start"] == list(out["spawn"]["tile"])        # the picture's marker (stage 2 C1)
    assert _natives(legends_lab.lab.eng) == natives and set(legends_lab.lab.eng.World.d) == world_keys
    assert legends_lab.roster("0000000001", "trader_scenario", fresh=False) == fresh
    assert legends_lab.roster("0000000001", "trader_scenario", fresh=True) == fresh


@pytest.mark.core
@pytest.mark.slow
def test_a_trader_spawn_run_gives_the_start_tile_and_leaves_the_roster_path_unchanged(legends_lab):
    """Stage 2 C1: the party's square of ANY origin is in the map summary ("start"), on land and not on a town. The
    run takes everything it put in place away again (as the Deserters run does). Trader makes its recruits in
    onSpawnAssets: running on through its own onSpawnPlayer changes none of them."""
    from bbseed import mapdraw
    from bbseed.mapgen import unexplained_stubs
    fresh = legends_lab.roster("0000000001", "trader_scenario", fresh=True)
    natives, world_keys = _natives(legends_lab.lab.eng), set(legends_lab.lab.eng.World.d)
    out = legends_lab.world_map("1234567890", "trader_scenario", stop_at="spawn", blackmarket=0)
    m = out["map"]
    x, y = m["start"]
    assert [x, y] == list(out["spawn"]["tile"]) and 0 <= x < m["size"][0] and 0 <= y < m["size"][1]
    assert m["terrain"][y * m["size"][0] + x] not in "OC", "the party does not start in the sea or on the shore"
    assert (x, y) not in [(t["x"], t["y"]) for t in m["towns"]]
    assert 'class="start"' in mapdraw.svg(m, verified=True) and 'class="start"' not in mapdraw.svg(m)
    sp = out["spawn"]
    assert sp["fort"] is sp["loop"] is sp["draws"] is None and sp["tile"] is not None
    assert not unexplained_stubs(out["stub_uses"])
    assert _natives(legends_lab.lab.eng) == natives and set(legends_lab.lab.eng.World.d) == world_keys
    assert legends_lab.roster("0000000001", "trader_scenario", fresh=False) == fresh
    assert legends_lab.roster("0000000001", "trader_scenario", fresh=True) == fresh
    assert out["roster"] == legends_lab.roster("1234567890", "trader_scenario")


@pytest.mark.edge
@pytest.mark.slow
def test_a_map_does_not_depend_on_the_maps_made_before(legends_lab):
    """The tile world is reused between maps (blanked, not rebuilt): nothing of one map may leak into the
    next. A map in another layout first, so that `first` is made on newly built tiles."""
    from bbseed import hexmap, mapgen
    other = next(layout for layout in hexmap.LAYOUTS if layout != mapgen.LAYOUT)
    assert legends_lab.world_map("0000000002", stop_at="accepted", layout=other)["log"][-1] == "World accepted."
    first = legends_lab.world_map("1234567890", stop_at="accepted")
    again = legends_lab.world_map("1234567890", stop_at="accepted")
    assert [l for l in first["log"] if l.startswith("Land Ocean ratio")] and first["log"][-1] == "World accepted."
    assert first["draws"] > 140 * 170          # one land/sea draw per tile at least
    assert "map" not in first and "probe" not in first      # no towns exist at this stop; only a whole map has these
    assert again["log"] == first["log"] and again["draws"] == first["draws"]
    # this run's stub uses only (the engine's total since start-up is never empty): up to "World accepted."
    # every native is modelled or an explained no-op
    assert again["stub_uses"] == first["stub_uses"] == {}


# ---------------------------------------------------------------- whole maps (stop_at="reseed"), map-search Task 5
# Keep the maps few: a map is the suite's main cost (cut again 2026-11-01). This section builds 3 Legends whole maps: the
# one of TOWN_SEEDS, built ONCE per test session by the `town_maps` fixture (between the two roster reads of the seed,
# which is the roster test's check, so no map is built just for that test), and the search test's 2 (the sift map and
# the confirming map of one checked seed, in the search's own worker process). The Vanilla section at the end has 1.
TOWN_SEEDS = ("1234567890",)
ORIGINS = ("trader_scenario", "legends_noble_scenario")
_ENTITIES = """
local out = { settlements = 0, placed = 0, occupied = 0, locations = 0 };
foreach (s in ::World.EntityManager.getSettlements())
{
    ++out.settlements;
    if (s.isPlacedOnMap()) ++out.placed;
    if (s.getTile().IsOccupied) ++out.occupied;
}
out.locations = ::World.EntityManager.getLocations().len();
return out;
"""


class TownMaps:
    """The whole maps of TOWN_SEEDS (Legends' default Map Options, Trader): `maps[seed]` = world_map's result with what
    the world state held right after it (`entities`, the scripts' own settlement list); `rosters[seed]` = (both
    origins' rosters before the map, the same after it)."""

    def __init__(self):
        self.maps, self.rosters = {}, {}


@pytest.fixture(scope="module")
def town_maps(legends_lab):
    from bbseed.lab import big_stack
    built = TownMaps()
    eng = legends_lab.lab.eng
    for seed in TOWN_SEEDS:
        before = {origin: legends_lab.roster(seed, origin, fresh=True) for origin in ORIGINS}
        out = legends_lab.world_map(seed)
        hm = legends_lab.lab._maps.hexmap           # the finished map's own RoadDirections, read apart from summary()
        out["road_values"] = [[int(hm.cols[x][y].RoadDirections) for x in range(hm.size_x)] for y in range(hm.size_y)]
        counts = big_stack(lambda: eng.vm.compile(_ENTITIES, "test_full_map_entities").invoke(eng.root, ()))
        out["entities"] = {k: counts.get(k) for k in ("settlements", "placed", "occupied", "locations")}
        after = {origin: legends_lab.roster(seed, origin, fresh=True) for origin in ORIGINS}
        built.maps[seed], built.rosters[seed] = out, (before, after)
    return built


@pytest.mark.edge
@pytest.mark.slow
def test_roster_unchanged_after_a_full_map(town_maps):
    """A whole map (towns, roads, regions, factions) on the lab's engine leaves both origins' rosters as they were: the
    fixture read both rosters of each seed before and after the map it built (a fresh world state each time)."""
    for seed in TOWN_SEEDS:
        out = town_maps.maps[seed]
        assert out["log"].count("World accepted.") == 1 and out["log"][-1] == "Placing abandoned fortresses...",             "a whole map ran to the second seeding between the rosters"
        before, after = town_maps.rosters[seed]
        assert after == before, seed


@pytest.mark.core
@pytest.mark.slow
def test_legends_map_completes_with_towns(town_maps):
    from bbseed.mapgen import unexplained_stubs
    for seed in TOWN_SEEDS:
        out = town_maps.maps[seed]
        assert out["log"].count("World accepted.") == 1
        assert not unexplained_stubs(out["stub_uses"])
        towns = [line for line in out["log"] if line.startswith("Created ") and line.endswith(" settlements.")]
        assert len(towns) == 1 and out["log"][-1] == "Placing abandoned fortresses..."
        # the settlements registered themselves (settlement.onInit: EntityManager.addSettlement) and stand on
        # their tiles (location.onInit: IsOccupied)
        n = int(towns[0].split()[1])
        assert out["entities"]["settlements"] == out["entities"]["placed"] == out["entities"]["occupied"] == n >= 19
        assert out["entities"]["locations"] > n           # attached locations and the abandoned fortresses


@pytest.mark.core
@pytest.mark.slow
def test_summary_roads_are_the_hexmaps_road_directions(town_maps):
    """A real Legends whole map: summary["roads"] decodes to the hexmap's RoadDirections of every tile (y-major, row 0 =
    the south edge), every value is a valid direction mask, there are roads, and the roads are two-sided: a tile with the
    bit of direction d has the bit of the opposite direction (d + 3) % 6 on that neighbour (bit order N NE SE S SW NW, which
    is also the order mapdraw draws them in). That pins the direction order and the offsets against the game's data. The
    one exception is the N bit: every town's tile has it, and so do some tiles beside it, with no S bit on the tile to the
    north (seed 1234567890: 57 of 271 N bits; the other five directions are two-sided on every tile) - it is the game's
    own data, and mapdraw draws it as a short stub."""
    from bbseed import mapdraw
    from bbseed.mapgen import ROAD_CHARS
    for seed in TOWN_SEEDS:
        out = town_maps.maps[seed]
        m, grid = out["map"], out["road_values"]
        w, h = m["size"]
        assert len(m["roads"]) == w * h and set(m["roads"]) <= set(ROAD_CHARS)
        assert [ROAD_CHARS.index(c) for c in m["roads"]] == [v for row in grid for v in row]
        assert all(0 <= v < 64 for row in grid for v in row)
        road_tiles = sum(1 for row in grid for v in row if v)
        assert road_tiles > 50, "a whole map has roads between its towns"
        assert any(grid[t["y"]][t["x"]] for t in m["towns"]), "a town stands on a road tile"
        for y in range(h):
            for x in range(w):
                for d, (dx, dy) in enumerate(mapdraw.ROAD_DIRECTIONS[x & 1]):
                    if grid[y][x] >> d & 1 and d:
                        nx, ny = x + dx, y + dy
                        assert 0 <= nx < w and 0 <= ny < h, (x, y, d)
                        assert grid[ny][nx] >> ((d + 3) % 6) & 1, (seed, x, y, d)
        # the picture: one half step per direction bit, all inside the picture
        segments = mapdraw.road_segments(m, True)
        assert len(segments) == sum(bin(v).count("1") for row in grid for v in row)
        width, height = mapdraw.picture_size(m)
        assert all(0 <= x <= width and 0 <= y <= height for seg in segments for x, y in (seg[:2], seg[2:]))


@pytest.mark.core
@pytest.mark.slow
def test_summary_is_complete(town_maps):
    """The summary of a whole map (map-search Task 6), taken from the cached full map of TOWN_SEEDS[0]: no map is
    built here (ruling N). That the map does not depend on the origin is measured in the lab suite
    (bb_seedlab tests/test_map_origin.py)."""
    import json
    from bbseed.mapgen import LAYOUT, TERRAIN_CHARS, events_from_log
    out = town_maps.maps["1234567890"]
    m = out["map"]
    assert m["size"] == [140, 170] and m["layout"] == LAYOUT
    assert len(m["terrain"]) == 140 * 170 and set(m["terrain"]) <= set(TERRAIN_CHARS)
    assert m["attempts"] == sum(1 for e in events_from_log(out["log"]) if e[0] == "land") >= 1
    towns = m["towns"]
    assert towns and any(t["southern"] for t in towns) and any(t["port"] for t in towns)
    assert len(towns) == out["entities"]["settlements"]              # every settlement the scripts registered
    ocean, shore = TERRAIN_CHARS[1], TERRAIN_CHARS[16]
    seen = set()
    for t in towns:
        assert set(t) == {"name", "script", "size", "x", "y", "southern", "military", "port", "faction"}
        assert isinstance(t["name"], str) and t["name"] and isinstance(t["script"], str) and t["script"]
        assert t["size"] in (1, 2, 3) and 0 <= t["x"] < 140 and 0 <= t["y"] < 170
        assert all(isinstance(t[k], bool) for k in ("southern", "military", "port"))
        assert t["faction"] is None or isinstance(t["faction"], str)
        assert (t["x"], t["y"]) not in seen
        seen.add((t["x"], t["y"]))
        assert m["terrain"][t["y"] * 140 + t["x"]] not in (ocean, shore), t        # a town stands on land
        if t["port"]:        # only a plausibility check of the game's own flag: water in the 3x3 squares round it
            near = {m["terrain"][y * 140 + x] for x in range(max(0, t["x"] - 1), min(140, t["x"] + 2))
                    for y in range(max(0, t["y"] - 1), min(170, t["y"] + 2))}
            assert near & {ocean, shore}, t
    assert json.loads(json.dumps(m)) == m                           # plain data: it goes between processes


_SETTLEMENT_LISTS = """
local out = [];
foreach (list in ::Const.World.Settlements.LegendsWorldMaster)
{
    local sizes = [];
    foreach (s in list.Sizes) sizes.push([s.Size, s.Ratio, s.MinAmount]);
    local scripts = [];
    foreach (t in list.Types) scripts.push(t.Script);
    out.push({ ratio = list.Ratio, sizes = sizes, scripts = scripts });
}
return out;
"""


@pytest.mark.core
@pytest.mark.slow
def test_map_limits_follow_the_games_settlement_lists(legends_lab, town_maps):
    """map_conditions.limits() (map-search Task 8) rests on a copy of Legends' settlement lists
    (Const.World.Settlements.LegendsWorldMaster). The copy must equal the game's table, each list's town kind must be
    the flags the scripts gave the towns of the cached whole maps (no map is built here, ruling N), and no cached
    map may have more of anything than limits() allows."""
    from bbreroll import map_conditions as M
    from bbseed.lab import big_stack
    from bbseed.mapgen import TOWN_TYPE_KEYS, counts
    from bbseed.sq.runtime import f32
    eng = legends_lab.lab.eng
    lists = big_stack(lambda: eng.vm.compile(_SETTLEMENT_LISTS, "test_settlement_lists").invoke(eng.root, ()))
    game = [(f32(l.get("ratio")), tuple(tuple(int(v) for v in s) for s in l.get("sizes"))) for l in lists]
    assert game == [(f32(ratio), sizes) for _kind, ratio, sizes in M.LEGENDS_LISTS]
    kind_of = {}
    for (kind, _r, _s), l in zip(M.LEGENDS_LISTS, lists):
        for script in l.get("scripts"):
            name = script.rsplit("/", 1)[-1]
            assert kind_of.setdefault(name, kind) == kind, name      # a script in two lists is of one kind
    assert legends_lab.get_mod_setting("mod_legends", "Settlements") == M.MAP_OPTION_DEFAULTS["Settlements"]
    lim = M.limits(None)
    for seed in TOWN_SEEDS:
        m = town_maps.maps[seed]["map"]
        assert len(m["towns"]) <= lim["ports"]
        for t in m["towns"]:
            kind = kind_of[t["script"]]
            assert (t["southern"], t["military"]) == (kind == "city_state", kind == "military"), t
        for band in (1, 33, 99):
            c = counts(m, band)
            assert all(c[k] <= lim[k] for k in M.PORT_KEYS), (seed, band, c)
            assert all(c["towns"][k] <= lim["towns"][k] for k in TOWN_TYPE_KEYS), (seed, band, c)
            criteria = dict({k: c[k] for k in M.PORT_KEYS}, north_band=band, towns=c["towns"])
            assert M.problems(criteria) == [], (seed, band, c)


@pytest.mark.core
def test_info_reports_the_map_options_at_legends_defaults(legends_lab):
    """Lab.info()["map_options"] (map-search Task 10) is what the seed post prints as the Map Options: the seven
    settings of Legends' Map Options page, read from MSU. A lab with default settings reports Legends' defaults, as
    plain ints and bools (they go between processes and into JSON). No map is built here."""
    from bbreroll import map_conditions as M
    from bbseed.lab import MAP_OPTION_KEYS
    options = legends_lab.info()["map_options"]
    assert tuple(options) == MAP_OPTION_KEYS
    assert options == M.MAP_OPTION_DEFAULTS
    for key, default in M.MAP_OPTION_DEFAULTS.items():
        assert type(options[key]) is type(default), (key, options[key])


@pytest.mark.core
@pytest.mark.slow
def test_real_search_finds_a_port_rich_map(town_maps):
    """search() with a map condition, in a real worker process (map-search Task 9). The seed is checked (seeds=[...]),
    not searched for: a search would build a whole map (~25 s) per seed tested. A checked seed goes the whole map
    path all the same — the sift map, the roster, the confirming roster and map, the stable flag, the payload — with
    two whole maps. TOWN_SEEDS[0] has 1 port at Legends' default Map Options (map-search Task 6); its map from this
    session's `town_maps` (the same default Map Options, black-market counter 0) must be the search's."""
    from bbseed.search import search
    seed = TOWN_SEEDS[0]
    events = []
    found = search("legends", "trader_scenario", {"map": {"ports": 1}}, workers=1, seeds=[seed],
                   on_event=lambda kind, payload: events.append((kind, payload)))
    assert not [e for e in events if e[0] in ("error", "fatal")], events
    [match] = found
    assert match["seed"] == seed and match["failure"] is None and match["stable"]
    assert len(match["roster"]) == 2 and all(bro.get("perk_groups") for bro in match["roster"])   # confirmed roll
    assert sum(t["port"] for t in match["map"]["towns"]) >= 1
    # the confirming map is run on through the start (stage 2 C1): the same map plus the party's square
    start = match["map"]["start"]
    assert len(start) == 2 and all(isinstance(v, int) for v in start)
    assert {k: v for k, v in match["map"].items() if k != "start"} == town_maps.maps[seed]["map"]


@pytest.mark.core
@pytest.mark.slow
def test_probe_is_the_next_draw_of_the_maps_stream(town_maps):
    """out["probe"] (map-search Task 7) is one Math.rand(1, 2147483646) drawn at the stop: the next number of the
    stream the campaign seed started, after all of the run's draws, and not counted in them. Checked against the RNG
    alone (no new map: the cached full map of TOWN_SEEDS[0], ruling N)."""
    from bbseed.mapgen import PROBE_RANGE
    from bbseed.rng import MT64, sdbm64
    seed = TOWN_SEEDS[0]
    out = town_maps.maps[seed]
    assert PROBE_RANGE == (1, 2147483646)
    assert isinstance(out["probe"], int) and PROBE_RANGE[0] <= out["probe"] <= PROBE_RANGE[1]
    stream = MT64(sdbm64(seed))
    for _ in range(out["draws"]):
        stream.next()
    assert stream.rand(*PROBE_RANGE) == out["probe"]


@pytest.mark.core
def test_terrain_chars_follow_the_games_terrain_table(legends_lab):
    """TERRAIN_CHARS / TERRAIN_NAMES have one entry per value of the game's Const.World.TerrainType (Legends
    adds two to the 19 of the base game), in the order of the values."""
    from bbseed.lab import big_stack
    from bbseed.mapgen import TERRAIN_CHARS, TERRAIN_NAMES
    eng = legends_lab.lab.eng
    table = big_stack(lambda: eng.vm.compile("return ::Const.World.TerrainType;", "test_terrain_table").invoke(eng.root, ()))
    values = dict(table.d)
    count = values.pop("COUNT")
    assert count == len(TERRAIN_CHARS) == len(TERRAIN_NAMES)
    assert set(values.values()) == set(range(count))
    for name, value in values.items():
        assert TERRAIN_NAMES[value] == name or (name, value) == ("Land", 2), (name, value)     # Land is Plains


@pytest.mark.edge
def test_the_navigators_terrain_count_is_the_games_and_its_cost_tables_miss_the_types_legends_adds(legends_lab):
    """Final review 89, MEASURED on Legends 19.4.22: Const.World.TerrainType.COUNT is 21 (SwampGreen 19, SwampForest
    20), the navigator reads it, and the three cost tables the scripts hand to createSettings have 19 entries - so a
    tile of type 19 or 20 has no cost (the navigator then raises NavError, never guesses; no generated map has one)."""
    from bbseed.lab import big_stack
    from bbseed.navigator import BASE_TYPES, terrain_count
    eng = legends_lab.lab.eng
    script = eng.vm.compile("""
        local out = [::Const.World.TerrainType.COUNT];
        foreach (name in ["TerrainTypeNavCost", "TerrainTypeNavCost_Flat", "TerrainTypeNavCost_Ship"])
            out.push(::Const.World[name].len());
        return out;
    """, "test_nav_tables")
    count, *table_lengths = big_stack(lambda: script.invoke(eng.root, ()))
    assert count == terrain_count(eng) == 21 and BASE_TYPES == 19
    assert table_lengths == [19, 19, 19]


@pytest.mark.core
def test_harmless_stubs_all_have_a_reason():
    from bbseed.mapgen import HARMLESS_STUBS, unexplained_stubs
    assert all(isinstance(why, str) and len(why) > 20 for why in HARMLESS_STUBS.values())
    assert unexplained_stubs({("sprite", "varyColor"): 3, ("World", "spawnEntity"): 1}) == {("World", "spawnEntity"): 1}
    # display / audio natives some origins' onSpawnPlayer reach (Northern Raiders, Berserker, Random Party ...)
    assert unexplained_stubs({("World", "spawnParticleEffect"): 2, ("Sound", "play"): 1}) == {}


@pytest.mark.core
def test_events_from_log_reads_the_generators_attempt_lines():
    """The attempts of a map run, in the format of the lab's reference data from the in-game logs
    (bb_seedlab tools/maplog.py): the ratio's text is not compared, only the counts."""
    from bbseed.mapgen import events_from_log
    log = ["Generating world with following settings...", "Snowline : 0.85", "LandMassMult : 1.55",
           "Building land and sea...", "Land Ocean ratio0.390268 >= 1.7 :: Land :6681 Ocean:17119",
           "World rejected. Creating new one...",
           "Building land and sea...", "Land Ocean ratio2.92739 >= 1.7 :: Land :17740 Ocean:6060",
           "Desert tiles 2220 >= 2400", "World rejected. Creating new one...",
           "Building land and sea...", "Land Ocean ratio2.5 >= 1.7 :: Land :17000 Ocean:6800",
           "Desert tiles 2500 >= 2400", "World accepted."]
    assert events_from_log(log) == [["land", 6681, 17119], ["land", 17740, 6060], ["desert", 2220],
                                    ["land", 17000, 6800], ["desert", 2500], ["accepted"]]
    assert events_from_log([]) == []


# ---------------------------------------------------------------- Vanilla maps (map-search stage 2, Task 5)
# The base game alone (no mod; the lab answers hasDLC True for every DLC). Its whole map is built once for the module
# (vanilla_maps). This seed's generator rejects 4 worlds first, so the attempts test has something to count.
VANILLA_SEEDS = ("5567142647",)
_VANILLA_LISTS = """
local out = [];
foreach (list in ::Const.World.Settlements.Master)
{
    local scripts = [];
    foreach (t in list.List) scripts.push(t.Script);
    out.push({ amount = list.Amount, scripts = scripts });
}
return out;
"""


@pytest.fixture(scope="module")
def vanilla_maps(vanilla_lab):
    """The whole maps of VANILLA_SEEDS (Trader, the origin the map tests use), built once for the tests that read them."""
    return {seed: vanilla_lab.world_map(seed, "trader_scenario") for seed in VANILLA_SEEDS}


def vanilla_town_type(script):
    """The town type that map_conditions.VANILLA_LISTS gives a Vanilla settlement script, from its file name: a city
    state, a stronghold (a *_fort script), or a village, town or city by the small_, medium_ or large_ prefix."""
    name = script.rsplit("/", 1)[-1]
    if name == "city_state":
        return "city_state"
    if name.endswith("_fort"):
        return "military"
    return {"small": "size1", "medium": "size2", "large": "size3"}[name.split("_", 1)[0]]


@pytest.mark.core
def test_vanilla_lists_match_the_game(vanilla_lab):
    """VANILLA_LISTS is the base game's Const.World.Settlements.Master: the same Amounts in the same order, and every
    script of a list makes that list's town type."""
    from bbreroll import map_conditions as M
    from bbseed.lab import big_stack
    eng = vanilla_lab.lab.eng
    lists = big_stack(lambda: eng.vm.compile(_VANILLA_LISTS, "test_vanilla_lists").invoke(eng.root, ()))
    assert [int(l.get("amount")) for l in lists] == [amount for _key, amount in M.VANILLA_LISTS]
    for (key, _amount), l in zip(M.VANILLA_LISTS, lists):
        assert {vanilla_town_type(script) for script in l.get("scripts")} == {key}, key


@pytest.mark.core
@pytest.mark.slow
def test_vanilla_map_has_no_unexplained_stubs(vanilla_maps):
    from bbseed.mapgen import unexplained_stubs
    for seed, out in vanilla_maps.items():
        assert out["log"].count("World accepted.") == 1 and out["log"][-1] == "Placing abandoned fortresses...", seed
        assert not unexplained_stubs(out["stub_uses"]), seed


@pytest.mark.core
@pytest.mark.slow
def test_vanilla_summary_flags(vanilla_maps):
    """Every town of a Vanilla map has bool flags: southern is the city state, military the stronghold (a *_fort
    script), and the map has 3 city states (the desert DLC's)."""
    for seed, out in vanilla_maps.items():
        towns = out["map"]["towns"]
        assert towns, seed
        for t in towns:
            assert all(isinstance(t[k], bool) for k in ("southern", "military", "port")), t
            assert t["southern"] == (t["script"] == "city_state"), t
            assert t["military"] == t["script"].endswith("_fort"), t
        assert sum(t["southern"] for t in towns) == 3, seed


@pytest.mark.core
@pytest.mark.slow
def test_vanilla_attempts_are_the_builds_of_land_and_sea(vanilla_maps):
    """summary()["attempts"] is one more than the worlds the generator rejected. Vanilla logs no ratio line, so the
    Legends line parser (events_from_log) finds no attempt in its log."""
    for seed, out in vanilla_maps.items():
        assert out["map"]["attempts"] == out["log"].count("World rejected. Creating new one...") + 1, seed


@pytest.mark.core
@pytest.mark.slow
def test_vanilla_maps_stay_within_the_limits(vanilla_maps):
    """No Vanilla map has more of anything than limits(vanilla=True) allows."""
    from bbreroll import map_conditions as M
    from bbseed.mapgen import TOWN_TYPE_KEYS, counts
    lim = M.limits(vanilla=True)
    for seed, out in vanilla_maps.items():
        for band in (1, 33, 99):
            c = counts(out["map"], band)
            assert all(c[k] <= lim[k] for k in M.PORT_KEYS), (seed, band, c)
            assert all(c["towns"][k] <= lim["towns"][k] for k in TOWN_TYPE_KEYS), (seed, band, c)

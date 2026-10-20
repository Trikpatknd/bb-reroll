"""The game's own campaign start, run in the lab up to the generated world (Legends 19.4.22 + MSU 1.9.0 +
Modern Hooks 0.6.0 on Battle Brothers 1.5.2.3). One lab is shared by the whole module: booting one takes
~15 s. Skipped when that game / those mods are not installed."""
import pytest

from bbseed import profiles

FOUND = profiles.installed_summary()
HAVE_GAME = FOUND is not None and FOUND["game_version"] == "1.5.2.3"
HAVE_LEGENDS = HAVE_GAME and any("mod_legends-19.4.22" in m for m in FOUND["mods"]) and any("1.9.0" in m for m in FOUND["mods"])


class InBigStack:
    """A lab whose every method call runs inside big_stack() (the interpreter recurses deeply: a Lab
    must only be called from such a thread). Attributes that are not methods are passed through."""

    def __init__(self, lab):
        self.lab = lab

    def __getattr__(self, name):
        from bbseed.lab import big_stack
        attr = getattr(self.lab, name)
        if not callable(attr):
            return attr
        return lambda *args, **kwargs: big_stack(lambda: attr(*args, **kwargs))


@pytest.fixture(scope="module")
def legends_lab():
    if not HAVE_LEGENDS:
        pytest.skip("Battle Brothers 1.5.2.3 with Legends 19.4.22 + MSU 1.9.0 is not installed")
    from bbseed.lab import Lab, big_stack
    lab = InBigStack(big_stack(lambda: Lab("legends")))
    info = lab.info()
    if (info["game_version"], info["legends_version"]) != ("1.5.2.3", "19.4.22"):
        pytest.skip("the lab did not load Legends 19.4.22 on 1.5.2.3: %r" % ((info["game_version"], info["legends_version"]),))
    return lab


def test_legends_map_reaches_world_accepted(legends_lab):
    out = legends_lab.world_map("1234567890", stop_at="accepted")
    lands = [l for l in out["log"] if l.startswith("Land Ocean ratio")]
    assert lands and out["log"][-1] == "World accepted."
    assert out["draws"] > 140 * 170          # one land/sea draw per tile at least
    needed = {"getTileSquare", "getNextTile", "hasNextTile", "getSurroundingTilesOfType", "spawnDetail", "setBrush"}
    assert not {n for (_k, n) in out["stub_uses"]} & needed      # modelled, not stubbed
    assert "map" not in out          # the summary is of a whole map: no towns exist at this stop


def _natives(eng):
    """The natives a map run replaces while it runs: ::World's, ::Math's and the root table's."""
    from bbseed.sq.runtime import NativeFn
    return {(name, k): v for name, table in (("World", eng.World), ("Math", eng.Math), ("root", eng.root))
            for k, v in table.d.items() if type(v) is NativeFn}


def test_world_map_leaves_roster_path_unchanged(legends_lab):
    before = legends_lab.roster("1234567890", "trader_scenario", fresh=True)
    natives, world_keys = _natives(legends_lab.lab.eng), set(legends_lab.lab.eng.World.d)
    legends_lab.world_map("1234567890", stop_at="accepted")
    assert _natives(legends_lab.lab.eng) == natives and set(legends_lab.lab.eng.World.d) == world_keys, \
        "the run takes its natives (tiles, seed wrappers, top bar ...) away again"
    assert legends_lab.roster("1234567890", "trader_scenario", fresh=True) == before


def test_a_sift_roster_after_a_map_is_the_fresh_one(legends_lab):
    """The search's sift loop reuses the world state (fresh=False); a map run must not leave it a
    half-started campaign."""
    fresh = legends_lab.roster("0000000001", "trader_scenario", fresh=True)
    legends_lab.world_map("1234567890", stop_at="accepted")
    assert legends_lab.roster("0000000001", "trader_scenario", fresh=False) == fresh


def test_a_map_does_not_depend_on_the_maps_made_before(legends_lab):
    """The tile world is reused between maps (blanked, not rebuilt): nothing of one map may leak into the
    next. A map in another layout first, so that `first` is made on newly built tiles."""
    from bbseed import hexmap, mapgen
    other = next(layout for layout in hexmap.LAYOUTS if layout != mapgen.LAYOUT)
    assert legends_lab.world_map("0000000002", stop_at="accepted", layout=other)["log"][-1] == "World accepted."
    first = legends_lab.world_map("1234567890", stop_at="accepted")
    again = legends_lab.world_map("1234567890", stop_at="accepted")
    assert again["log"] == first["log"] and again["draws"] == first["draws"]
    # this run's stub uses only (the engine's total since start-up is never empty): up to "World accepted."
    # every native is modelled or an explained no-op
    assert again["stub_uses"] == first["stub_uses"] == {}


# ---------------------------------------------------------------- whole maps (stop_at="reseed"), map-search Task 5
# At most 5 whole maps in this file (ruling N; the repo suite builds 7: these 5 plus the 2 in test_offline_map.py):
# the town test's 3 (shared through FULL_MAPS, one world_map(seed) per seed per test session) and the roster test's 2,
# which it always builds itself between the rosters (its seeds are its own, so no other test can have built them
# first, whatever the order the tests run in).
FULL_MAPS = {}
TOWN_SEEDS = ("1234567890", "0000000001", "0000000002")
ROSTER_SEEDS = ("0000000003", "0000000004")
assert not set(TOWN_SEEDS) & set(ROSTER_SEEDS)
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


def full_map(lab, seed):
    """The whole map of a seed (Legends' default Map Options, Trader), built once per test session, with what the
    world state held right after it (the scripts' own settlement list)."""
    if seed not in FULL_MAPS:
        from bbseed.lab import big_stack
        out = lab.world_map(seed)
        eng = lab.lab.eng
        counts = big_stack(lambda: eng.vm.compile(_ENTITIES, "test_full_map_entities").invoke(eng.root, ()))
        out["entities"] = {k: counts.get(k) for k in ("settlements", "placed", "occupied", "locations")}
        FULL_MAPS[seed] = out
    return FULL_MAPS[seed]


def test_roster_unchanged_after_a_full_map(legends_lab):
    """A whole map (towns, roads, regions, factions) on the lab's engine leaves both origins' rosters as they were.
    The map is built here, between the rosters, every time (not taken from FULL_MAPS)."""
    for seed in ROSTER_SEEDS:
        before = {origin: legends_lab.roster(seed, origin, fresh=True) for origin in ORIGINS}
        out = legends_lab.world_map(seed)
        assert out["log"].count("World accepted.") == 1 and out["log"][-1] == "Placing abandoned fortresses...",             "a whole map ran to the second seeding between the rosters"
        assert {origin: legends_lab.roster(seed, origin, fresh=True) for origin in ORIGINS} == before, seed


def test_legends_map_completes_with_towns(legends_lab):
    from bbseed.mapgen import unexplained_stubs
    for seed in TOWN_SEEDS:
        out = full_map(legends_lab, seed)
        assert out["log"].count("World accepted.") == 1
        assert not unexplained_stubs(out["stub_uses"])
        towns = [line for line in out["log"] if line.startswith("Created ") and line.endswith(" settlements.")]
        assert len(towns) == 1 and out["log"][-1] == "Placing abandoned fortresses..."
        # the settlements registered themselves (settlement.onInit: EntityManager.addSettlement) and stand on
        # their tiles (location.onInit: IsOccupied)
        n = int(towns[0].split()[1])
        assert out["entities"]["settlements"] == out["entities"]["placed"] == out["entities"]["occupied"] == n >= 19
        assert out["entities"]["locations"] > n           # attached locations and the abandoned fortresses


def test_summary_is_complete(legends_lab):
    """The summary of a whole map (map-search Task 6), taken from the cached full map of TOWN_SEEDS[0]: no map is
    built here (ruling N). That the map does not depend on the origin is measured in the lab suite
    (bb_seedlab tests/test_map_origin.py)."""
    import json
    from bbseed.mapgen import LAYOUT, TERRAIN_CHARS, events_from_log
    out = full_map(legends_lab, "1234567890")
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


def test_map_limits_follow_the_games_settlement_lists(legends_lab):
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
        m = full_map(legends_lab, seed)["map"]
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


def test_probe_is_the_next_draw_of_the_maps_stream(legends_lab):
    """out["probe"] (map-search Task 7) is one Math.rand(1, 2147483646) drawn at the stop: the next number of the
    stream the campaign seed started, after all of the run's draws, and not counted in them. Checked against the RNG
    alone (no new map: the cached full map of TOWN_SEEDS[0], ruling N)."""
    from bbseed.mapgen import PROBE_RANGE
    from bbseed.rng import MT64, sdbm64
    seed = TOWN_SEEDS[0]
    out = full_map(legends_lab, seed)
    assert PROBE_RANGE == (1, 2147483646)
    assert isinstance(out["probe"], int) and PROBE_RANGE[0] <= out["probe"] <= PROBE_RANGE[1]
    stream = MT64(sdbm64(seed))
    for _ in range(out["draws"]):
        stream.next()
    assert stream.rand(*PROBE_RANGE) == out["probe"]
    assert "probe" not in legends_lab.world_map(seed, stop_at="accepted")      # only a whole map has the stop


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


def test_harmless_stubs_all_have_a_reason():
    from bbseed.mapgen import HARMLESS_STUBS, unexplained_stubs
    assert all(isinstance(why, str) and len(why) > 20 for why in HARMLESS_STUBS.values())
    assert unexplained_stubs({("sprite", "varyColor"): 3, ("World", "spawnEntity"): 1}) == {("World", "spawnEntity"): 1}


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

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
# Full maps are shared through this cache: one world_map(seed) per seed per test session, at most 5 in the suite
# (ruling N). test_roster_unchanged_after_a_full_map builds them (it must stand first: it takes the rosters before
# and after each map); the tests after it read them.
FULL_MAPS = {}
FULL_SEEDS = ("1234567890", "0000000001", "0000000002", "0000000003", "0000000004")
ORIGINS = ("trader_scenario", "legends_noble_scenario")
_PROBE = """
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
        probe = big_stack(lambda: eng.vm.compile(_PROBE, "test_full_map_probe").invoke(eng.root, ()))
        out["probe"] = {k: probe.get(k) for k in ("settlements", "placed", "occupied", "locations")}
        FULL_MAPS[seed] = out
    return FULL_MAPS[seed]


def test_roster_unchanged_after_a_full_map(legends_lab):
    """A whole map (towns, roads, regions, factions) on the lab's engine leaves both origins' rosters as they were."""
    for seed in FULL_SEEDS:
        before = {origin: legends_lab.roster(seed, origin, fresh=True) for origin in ORIGINS}
        full_map(legends_lab, seed)
        assert {origin: legends_lab.roster(seed, origin, fresh=True) for origin in ORIGINS} == before, seed


def test_legends_map_completes_with_towns(legends_lab):
    from bbseed.mapgen import unexplained_stubs
    for seed in ("1234567890", "0000000001", "0000000002"):
        out = full_map(legends_lab, seed)
        assert out["log"].count("World accepted.") == 1
        assert not unexplained_stubs(out["stub_uses"])
        towns = [line for line in out["log"] if line.startswith("Created ") and line.endswith(" settlements.")]
        assert len(towns) == 1 and out["log"][-1] == "Placing abandoned fortresses..."
        # the settlements registered themselves (settlement.onInit: EntityManager.addSettlement) and stand on
        # their tiles (location.onInit: IsOccupied)
        n = int(towns[0].split()[1])
        assert out["probe"]["settlements"] == out["probe"]["placed"] == out["probe"]["occupied"] == n >= 19
        assert out["probe"]["locations"] > n            # attached locations and the abandoned fortresses


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

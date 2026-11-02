"""Deserters' start in the lab (stage 2 C2 Task 1): the whole campaign start up to the origin's onInit
(`Lab.world_map(..., stop_at="spawn")`) and the start without a map (`Lab.deserters_start` / `deserters_roster`), on
Legends 19.4.22 with the player's Map Options (the lab gates' 55 / 38 / 85 / 24 / 4 / yes / yes) and on Vanilla
1.5.2.3 with all DLCs. Skipped when that game / those mods are not installed.

The whole-map tests are marked slow and run in two pytest-xdist groups of 3 maps (one lab each, ~3 min): run them by
node id or with --full. The tests without a map use the session's shared labs (conftest.py)."""
import pytest

from bbseed import mapgen, profiles

FOUND = profiles.installed_summary()
HAVE_GAME = FOUND is not None and FOUND["game_version"] == "1.5.2.3"
HAVE_LEGENDS = HAVE_GAME and any("mod_legends-19.4.22" in m for m in FOUND["mods"]) and any("1.9.0" in m for m in FOUND["mods"])

# The player's saved Map Options, as the lab's map gates use them (bb_seedlab tests/test_map_ingame BATCH_MAP_OPTIONS).
USER_OPTIONS = {"mod_legends:LandRatio": 55, "mod_legends:Water": 38, "mod_legends:Snowline": 85,
                "mod_legends:Settlements": 24, "mod_legends:Factions": 4, "mod_legends:StackCitadels": True,
                "mod_legends:AllTradeLocations": True}
SEEDS = ("0000000005", "0000000006", "0000000007")
DESERTERS = "deserters_scenario"

_labs = {}
_runs = {}


def _lab(setup):
    """One lab per setup and process: Legends with USER_OPTIONS, or Vanilla."""
    if setup == "legends" and not HAVE_LEGENDS:
        pytest.skip("Battle Brothers 1.5.2.3 with Legends 19.4.22 + MSU 1.9.0 is not installed")
    if not HAVE_GAME:
        pytest.skip("Battle Brothers 1.5.2.3 is not installed")
    if setup not in _labs:
        from conftest import InBigStack
        from bbseed.lab import Lab, big_stack
        if setup == "legends":
            _labs[setup] = InBigStack(big_stack(lambda: Lab("legends", mod_settings=USER_OPTIONS)))
        else:
            _labs[setup] = InBigStack(big_stack(lambda: Lab("vanilla")))
    return _labs[setup]


def _start_runs(setup):
    """The whole Deserters starts of the seeds, each with the start without a map for its loop and fort:
    [(seed, world_map's result, deserters_start's result)]."""
    if setup not in _runs:
        lab = _lab(setup)
        rows = []
        for seed in SEEDS:
            out = lab.world_map(seed, DESERTERS, stop_at="spawn")
            sp = out["spawn"]
            town = out["map"]["towns"][sp["fort"]]
            rows.append((seed, out, lab.deserters_start(seed, sp["loop"], (town["x"], town["y"]), sp["size"])))
        _runs[setup] = rows
    return _runs[setup]


def _groups():
    return [pytest.param(setup, marks=[pytest.mark.slow, pytest.mark.xdist_group("deserters_%s" % setup)], id=setup)
            for setup in ("legends", "vanilla")]


@pytest.mark.core
@pytest.mark.parametrize("setup", _groups())
def test_the_roster_without_a_map_is_the_maps(setup):
    """The recruits depend on the map only through the start loop's length: deserters_start with the map's loop count
    and fort gives the map's roster, and draws the map's start tile on its last iteration."""
    for seed, out, no_map in _start_runs(setup):
        sp = out["spawn"]
        assert len(out["roster"]) == 3 and {b["background"] for b in out["roster"]} == {"background.deserter"}, seed
        assert no_map["roster"] == out["roster"], seed
        assert no_map["tile"] == sp["tile"] and no_map["draws"] == sp["draws"], seed
        assert sp["draws"] == mapgen.deserters_loop_draws((out["map"]["towns"][sp["fort"]]["x"],
                                                           out["map"]["towns"][sp["fort"]]["y"]), sp["loop"], sp["size"])
        assert 1 <= sp["loop"] <= mapgen.SPAWN_LOOP_CAP


@pytest.mark.core
@pytest.mark.parametrize("setup", _groups())
def test_the_start_has_no_unexplained_stub(setup):
    for seed, out, _no_map in _start_runs(setup):
        assert mapgen.unexplained_stubs(out["stub_uses"]) == {}, seed
        assert out["map"]["towns"] and len(out["spawn"]["isolated"]) == len(out["map"]["towns"]), seed


@pytest.mark.core
@pytest.mark.parametrize("setup", _groups())
def test_the_fort_follows_the_scripts_rule(setup):
    """The fort is the first military, non-southern town that is not isolated from the roads (all maps here have one);
    the start tile is in its ranges, more than 4 away (spawn_summary checks that too), on a road."""
    for seed, out, _no_map in _start_runs(setup):
        sp, towns = out["spawn"], out["map"]["towns"]
        good = [i for i, t in enumerate(towns) if t["military"] and not t["southern"] and not sp["isolated"][i]]
        assert good and sp["fort"] == good[0], seed
        (xlo, xhi), (ylo, yhi) = mapgen.loop_ranges((towns[sp["fort"]]["x"], towns[sp["fort"]]["y"]), sp["size"])
        assert xlo <= sp["tile"][0] <= xhi and ylo <= sp["tile"][1] <= yhi, seed


@pytest.mark.core
@pytest.mark.slow
@pytest.mark.xdist_group("deserters_vanilla")
def test_an_ordinary_origin_through_the_start_is_its_roster():
    """Trader makes its recruits in onSpawnAssets: running on through its own onSpawnPlayer changes none of them. (On
    Legends: test_a_trader_spawn_run_gives_the_start_tile_and_leaves_the_roster_path_unchanged, test_mapgen_game.py.)"""
    lab = _lab("vanilla")
    seed = "1234567890"
    out = lab.world_map(seed, "trader_scenario", stop_at="spawn")
    assert out["roster"] == lab.roster(seed, "trader_scenario")
    sp = out["spawn"]
    assert sp["fort"] is sp["loop"] is sp["draws"] is None and sp["tile"] is not None
    assert mapgen.unexplained_stubs(out["stub_uses"]) == {}


@pytest.mark.dirty
@pytest.mark.slow
@pytest.mark.xdist_group("deserters_vanilla")
def test_the_start_loop_stops_when_every_square_has_failed(monkeypatch):
    """A map on which no square passes would hang the game in onSpawnPlayer; the lab remembers the squares that failed
    and stops with an error as soon as all of the fort's squares have (here every square is made invalid: about a
    thousand iterations, not SPAWN_LOOP_CAP) and is usable after it."""
    from bbseed.lab import LabError
    from bbseed.sq.runtime import NativeFn
    lab = _lab("vanilla")
    real = mapgen.MapRun._on_spawn_player

    def never_valid(self, this, original):
        self._put(self.eng.World, "isValidTileSquare", NativeFn(lambda this, x, y: False, "isValidTileSquare"))
        return real(self, this, original)
    monkeypatch.setattr(mapgen.MapRun, "_on_spawn_player", never_valid)
    with pytest.raises(LabError, match=r"all \d+ squares of its ranges failed"):
        lab.world_map("0000000001", DESERTERS, stop_at="spawn")
    monkeypatch.undo()
    assert lab.roster("1234567890", "trader_scenario") == lab.roster("1234567890", "trader_scenario", fresh=False)
    scenario = lab.scenario(DESERTERS)       # the run's wrappers are gone: the origin's own functions again
    assert all(type(scenario.d.get(name)) is not NativeFn for name in ("onSpawnPlayer", "onInit"))


# ---------------------------------------------------------------- the start without a map (no map is built: fast)
@pytest.mark.dirty
@pytest.mark.parametrize("which", ["legends_lab", "vanilla_lab"])
def test_the_start_without_a_map(which, request):
    lab = request.getfixturevalue(which)
    from bbseed.sq.runtime import NativeFn
    eng = lab.lab.eng

    def natives():
        return {k: v for k, v in eng.World.d.items() if type(v) is NativeFn}
    before = natives()
    first = lab.deserters_start("1234567890", 1)
    third = lab.deserters_start("1234567890", 3)
    assert first["draws"] == 2 and third["draws"] == 6
    for r in (first, third):
        assert len(r["roster"]) == 3 and {b["background"] for b in r["roster"]} == {"background.deserter"}
    # no fort square: the fort in the middle of the lab's 140 x 170 (both setups), the drawn square within 7 of it
    for r in (first, third):
        assert 63 <= r["tile"][0] <= 77 and 78 <= r["tile"][1] <= 92, r["tile"]
    assert first["roster"] != third["roster"]
    assert lab.deserters_roster("1234567890", 3) == third["roster"]
    assert lab.deserters_roster("1234567890", 3, fresh=False) == third["roster"]
    # an edge fort draws as many numbers on a real map size (2 per iteration) and keeps the drawn square in its ranges
    edge = lab.deserters_start("1234567890", 3, (0, 169), (140, 170))
    assert edge["draws"] == 6 and 2 <= edge["tile"][0] <= 7 and 162 <= edge["tile"][1] <= 168
    assert edge["roster"] == third["roster"]
    # a 4 x 4 map: both ranges are 2 .. 2, the loop draws nothing, so n changes nothing
    tiny = lab.deserters_start("1234567890", 3, (1, 1), (4, 4))
    assert tiny["draws"] == 0 and tiny["tile"] == (2, 2)
    assert tiny["roster"] == lab.deserters_roster("1234567890", 1, (1, 1), (4, 4)) != third["roster"]
    for bad in (0, mapgen.SPAWN_LOOP_CAP + 1, 2.0):
        with pytest.raises(ValueError):
            lab.deserters_start("1234567890", bad)
    assert natives() == before, "the stand-ins are taken away again"
    assert lab.roster("1234567890", "trader_scenario") == lab.roster("1234567890", "trader_scenario", fresh=False)


# ---------------------------------------------------------------- the search (stage 2 C2 Task 4)
@pytest.mark.core
@pytest.mark.slow
@pytest.mark.parametrize("setup", [pytest.param("legends", marks=pytest.mark.xdist_group("deserters_search_legends")),
                                   pytest.param("vanilla", marks=pytest.mark.xdist_group("deserters_search_vanilla"))])
def test_a_deserters_search_finds_the_roster_of_the_map_run(setup):
    """Two real worker processes search the seed 0000000001 for Deserters with a map condition its map meets on both
    setups (1 port): every match is a seed whose map meets it, its roster is the one the lab's own start run gives
    (with the perk trees), it is confirmed (stable), and the seed post says to start it as the first campaign."""
    from bbseed import search
    if setup == "legends" and not HAVE_LEGENDS:
        pytest.skip("Battle Brothers 1.5.2.3 with Legends 19.4.22 + MSU 1.9.0 is not installed")
    if not HAVE_GAME:
        pytest.skip("Battle Brothers 1.5.2.3 is not installed")
    events = []
    found = search.search(setup, DESERTERS, {"map": {"ports": 1}}, workers=2, count=1, max_seeds=1, start=1,
                          mod_settings=USER_OPTIONS if setup == "legends" else None,
                          on_event=lambda kind, payload: events.append((kind, payload)))
    assert not [p for k, p in events if k in ("fatal", "error")], events
    assert found, "the map has a port"
    lab = _lab(setup)
    for match in found:
        assert match["stable"] and match["failure"] is None and match["map"] is not None
        assert mapgen.counts(match["map"], mapgen.DEFAULT_NORTH_BAND)["ports"] >= 1
        direct = lab.world_map(match["seed"], DESERTERS, stop_at="spawn", perks=True)
        searched = [{k: v for k, v in bro.items() if k != "rolls"} for bro in match["roster"]]   # (the search watches the rolls)
        assert searched == direct["roster"], match["seed"]
        assert len(match["roster"]) == 3 and all(b["background"] == "background.deserter" for b in match["roster"])
        assert match["roster"][0].get("perk_groups") is not None or setup == "vanilla"
    odds = [p[3] for k, p in events if k == "progress"][-1]
    assert odds["tested"] == 1 and odds["maps"] == 1

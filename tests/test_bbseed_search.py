"""Criteria handling of the offline searcher (no game data needed)."""
import queue
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbseed import search as S
from bbseed.lab import LabError
from bbseed.search import Odds, first_failure, normalize, parse_stars, seed_text

ZERO = dict.fromkeys(("hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf"), 0)


def bro(traits=(), **stars):
    return {"stars": dict(ZERO, **stars), "traits": list(traits)}


@pytest.mark.dirty
def test_parse_stars():
    assert parse_stars("msk2 mdf1") == {"msk": 2, "mdf": 1}
    assert parse_stars("") == {}
    for bad in ("msk", "xyz2", "msk4", "2msk"):
        with pytest.raises(ValueError):
            parse_stars(bad)


@pytest.mark.core
def test_normalize_accepts_bb_reroll_config():
    c = normalize({"stars_by_slot": {"*": {}, "1": {"res": 3}, "2": "msk2"}, "banned": ["trait.dumb", "fat"],
                   "required": ["brave"], "required_mode": "any"})
    assert c["stars_by_slot"] == {"1": {"res": 3}, "2": {"msk": 2}}
    assert c["banned"] == ["dumb", "fat"] and c["required"] == ["brave"] and c["required_slots"] is None


@pytest.mark.core
def test_stars_per_slot_and_wildcard():
    c = normalize({"stars_by_slot": {"*": "hp1", "2": "msk2"}})
    assert first_failure([bro(hp=1), bro(hp=2, msk=2)], c) is None
    assert first_failure([bro(hp=0), bro(hp=2, msk=2)], c) == "bro1 hp*0<1"
    assert first_failure([bro(hp=1), bro(hp=1, msk=1)], c) == "bro2 msk*1<2"
    # a slot's own row replaces "*" for that recruit: bro 2 needs msk2 only, not hp1 as well
    assert first_failure([bro(hp=1), bro(hp=0, msk=2)], c) is None
    # a slot row with nothing in it is no row: "*" applies
    c = normalize({"stars_by_slot": {"*": {"hp": 1}, "2": {}}})
    assert first_failure([bro(hp=1), bro(hp=0)], c) == "bro2 hp*0<1"


@pytest.mark.core
def test_banned_applies_to_every_recruit():
    c = normalize({"banned": ["dumb"]})
    assert first_failure([bro(["brave"]), bro([])], c) is None
    assert first_failure([bro(["brave"]), bro(["dumb"])], c) == "bro2 banned dumb"


@pytest.mark.core
def test_required_any_all_and_slots():
    any_ = normalize({"required": ["brave", "tough"]})
    assert first_failure([bro(["brave"]), bro(["tough", "fat"])], any_) is None
    assert first_failure([bro(["brave"]), bro(["fat"])], any_) == "bro2 no_good_trait"
    all_ = normalize({"required": ["brave", "tough"], "required_mode": "all"})
    assert first_failure([bro(["brave", "tough"])], all_) is None
    assert first_failure([bro(["brave"])], all_) == "bro1 missing tough"
    first_only = normalize({"required": ["brave"], "required_slots": [1]})
    assert first_failure([bro(["brave"]), bro([])], first_only) is None


@pytest.mark.edge
def test_slot_beyond_roster_fails():
    c = normalize({"stars_by_slot": {"4": "hp1"}})
    assert first_failure([bro(hp=3)], c) == "no bro4 in this origin's roster"


@pytest.mark.core
def test_odds_multiply_the_slots_pass_rates():
    from bbseed.search import Odds
    c = normalize({"stars_by_slot": {"1": "msk2", "2": "mdf1"}})
    odds = Odds()
    assert odds.chance() is None
    odds.add_roster([bro(msk=2), bro(mdf=1)], c)
    odds.add_roster([bro(msk=2), bro()], c)
    odds.add_roster([bro(), bro(mdf=2)], c)
    odds.add_roster([bro(), bro()], c)
    assert odds.tested == 4 and odds.passed == [2, 2]
    assert odds.chance() == 0.25 and odds.never() == []


@pytest.mark.edge
def test_odds_name_a_slot_that_never_passes_and_merge_worker_counts():
    from bbseed.search import Odds
    c = normalize({"stars_by_slot": {"2": "hp3"}})
    worker = Odds()
    for _ in range(3):
        worker.add_roster([bro(), bro(hp=1)], c)
    total = Odds()
    total.merge(*worker.take())
    assert worker.tested == 0 and total.tested == 3
    assert total.chance() == 0.0 and total.never() == [2]


@pytest.mark.edge
def test_seeds_are_ten_digits():
    assert seed_text(42) == "0000000042"
    assert seed_text(10 ** 10 + 7) == "0000000007"


@pytest.mark.core
def test_backgrounds_per_slot_and_for_any_brother():
    def b(background):
        return dict(bro(), background=background)
    c = normalize({"backgrounds_by_slot": {"2": "hedge_knight swordmaster", "1": []}})
    assert c["backgrounds_by_slot"] == {"2": ["background.hedge_knight", "background.swordmaster"]}
    assert first_failure([b("background.miller"), b("background.swordmaster")], c) is None
    assert first_failure([b("background.miller"), b("background.miller")], c) == "bro2 background miller"
    some = normalize({"backgrounds_by_slot": {"any": ["background.hedge_knight"]}})
    assert first_failure([b("background.miller"), b("background.hedge_knight")], some) is None
    assert first_failure([b("background.miller"), b("background.thief")], some) == "no bro with a wanted background"
    beyond = normalize({"backgrounds_by_slot": {"6": ["hedge_knight"]}})
    assert first_failure([b("background.miller")] * 4, beyond) == "no bro6 in this origin's roster"


@pytest.mark.core
def test_odds_count_the_any_brother_condition_as_one_more_factor():
    from bbseed.search import Odds
    def b(background):
        return dict(bro(), background=background)
    c = normalize({"backgrounds_by_slot": {"any": ["hedge_knight"]}})
    odds = Odds()
    odds.add_roster([b("background.hedge_knight"), b("background.miller")], c)
    odds.add_roster([b("background.miller"), b("background.miller")], c)
    assert odds.chance() == 0.5 and not odds.team_never()
    total = Odds()
    total.merge(*odds.take())
    assert total.team == 1 and total.chance() == 0.5
    none = Odds()
    none.add_roster([b("background.miller")], c)
    assert none.team_never() and none.chance() == 0.0
    plain = Odds()
    plain.add_roster([b("background.miller")], normalize({}))
    assert plain.team is None and plain.chance() == 1.0


# ---------------------------------------------------------------- map conditions (map-search Task 9)
@pytest.mark.core
def test_normalize_keeps_map_conditions():
    c = normalize({"map": {"ports": 6, "north_band": 33, "towns": {"city_state": 2}}})
    assert c["map"] == {"ports": 6, "ports_south": 0, "ports_north": 0, "north_band": 33, "towns": {"city_state": 2}}
    assert normalize(c) == c                                  # search() normalizes what the CLI normalized


@pytest.mark.edge
def test_normalize_without_map_conditions():
    assert normalize({})["map"] is None
    # 0 is no condition, and a band alone is none either
    assert normalize({"map": {"ports": 0, "north_band": 50, "towns": {"size1": 0}}})["map"] is None
    assert normalize({"map": None})["map"] is None


@pytest.mark.core
def test_normalize_fills_in_the_north_band():
    assert normalize({"map": {"ports_north": 1}})["map"] == {
        "ports": 0, "ports_south": 0, "ports_north": 1, "north_band": 33, "towns": {}}
    assert normalize({"map": {"ports_north": 2, "north_band": 20}})["map"]["north_band"] == 20
    assert normalize({"map": {"towns": {"size3": "4"}}})["map"]["towns"] == {"size3": 4}


@pytest.mark.dirty
def test_normalize_rejects_a_bad_north_band_only_for_northern_ports():
    """Carried from Task 8's review: the band matters only for northern ports, so only then is it checked."""
    for band in (0, 100, -3, 150, "far"):
        with pytest.raises(ValueError, match="north band"):
            normalize({"map": {"ports_north": 1, "north_band": band}})
    # without a northern-port condition a bad band is ignored (the default is kept), a good one kept
    assert normalize({"map": {"ports": 2, "north_band": 0}})["map"]["north_band"] == 33
    assert normalize({"map": {"ports": 2, "north_band": 150}})["map"]["north_band"] == 33
    assert normalize({"map": {"ports": 2, "north_band": 50}})["map"]["north_band"] == 50


@pytest.mark.dirty
def test_normalize_rejects_unknown_map_conditions():
    for bad in ({"port": 3}, {"map_options": {"Settlements": 24}}, {"towns": {"castle": 1}}, {"ports": -1},
                {"towns": {"size1": -2}}, {"ports": "many"}):
        with pytest.raises(ValueError):
            normalize({"map": bad})


ROSTER_SIZE = 3


def fake_map(ports, shift=0):
    """A map summary of ten northern towns, the first `ports` of them ports (`shift` moves every town east)."""
    towns = [{"name": "Town %d" % i, "script": "legends_fishing_village", "size": 1, "x": i + shift, "y": 160,
              "southern": False, "military": False, "port": i < ports, "faction": None} for i in range(10)]
    return {"size": [140, 170], "layout": "even-q-up", "terrain": "L" * 10, "towns": towns, "attempts": 1}


class FakeLab:
    """Stands in for Lab in a search worker (search._make_lab is replaced). Seed n: brother 1 has n % 2 HP stars,
    the map has n % 10 ports. map_errors: seeds whose map run raises LabError (True: every seed's).
    second_map(summary): what the second build of a seed's map gives instead (the confirming one)."""
    roster_calls = 0
    world_map_calls = 0

    def __init__(self, map_errors=(), second_map=None, map_crash=None, roster_crash=None, first_map=None, stubs=None):
        """map_crash / roster_crash: an exception (not a LabError) world_map / roster raises for every seed.
        first_map(summary): what the first build of a seed's map gives instead.
        stubs: the engine stand-ins a map run reports using: {seed: {(kind, name): uses}}, or a function of the seed."""
        FakeLab.roster_calls = FakeLab.world_map_calls = 0
        self.stubs = stubs or {}
        self.map_errors = map_errors
        self.second_map = second_map
        self.first_map = first_map
        self.map_crash = map_crash
        self.roster_crash = roster_crash
        self.builds = {}
        self.blackmarket = []
        self.map_calls = []             # (stop_at, perks) of every world_map call
        self.trade_calls = []           # (stop_at, trade) of every world_map call

    def info(self):
        return {"profile": "fake"}

    spawn_error = None                  # a LabError text: every run on through the start fails with it

    def start(self, seed):
        return [int(seed) % 10 + 3, 40]

    def _bros(self, seed):
        return [bro(["brave"], hp=int(seed) % 2)] + [bro() for _ in range(ROSTER_SIZE - 1)]

    def roster(self, seed, origin, fresh=True, probe=None):
        FakeLab.roster_calls += 1
        if self.roster_crash is not None:
            raise self.roster_crash
        return self._bros(seed)

    def roster_with_perks(self, seed, origin):
        FakeLab.roster_calls += 1
        return [dict(b, perk_groups=[], single_perks=[]) for b in self._bros(seed)]

    trade_data = {"towns": [], "goods": {}}     # what a run with trade=True puts in its map (None: nothing, as when
                                                # the lab's read found no party or failed)

    def world_map(self, seed, origin="trader_scenario", stop_at="reseed", layout=None, blackmarket=0, perks=False,
                  trade=False):
        FakeLab.world_map_calls += 1
        self.blackmarket.append(blackmarket)
        self.map_calls.append((stop_at, perks))
        self.trade_calls.append((stop_at, trade))
        if self.map_crash is not None:
            raise self.map_crash
        if stop_at == "spawn" and self.spawn_error is not None:
            raise LabError(self.spawn_error)
        if self.map_errors is True or seed in self.map_errors:
            raise LabError("map of seed %r: the index '0' does not exist" % seed)
        self.builds[seed] = self.builds.get(seed, 0) + 1
        summary = fake_map(int(seed) % 10)
        if self.builds[seed] == 1 and self.first_map is not None:
            summary = self.first_map(summary)
        if self.builds[seed] == 2 and self.second_map is not None:
            summary = self.second_map(summary)
        stubs = self.stubs(seed) if callable(self.stubs) else self.stubs.get(seed, {})
        if stop_at == "spawn":          # the real lab's run through the start puts the party's square in the map
            summary = dict(summary, start=self.start(seed))
            if trade and self.trade_data is not None:
                summary["trade"] = self.trade_data
        found = {"map": summary, "seconds": 0.0, "log": [], "stub_uses": stubs}
        if stop_at == "spawn":          # the start run: the recruits too (Deserters)
            bros = self._bros(seed)
            found["roster"] = [dict(b, perk_groups=[], single_perks=[]) for b in bros] if perks else bros
        return found


class ListQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


def run_worker(monkeypatch, lab, criteria, seeds=None, limit=30, origin="trader_scenario", final_from=None):
    """One search worker (index 0 of 1, seeds 0, 1, ... limit - 1) on the stand-in lab: its events."""
    monkeypatch.setattr(S, "_make_lab", lambda profile, mod_settings: lab)
    out = ListQueue()
    S._worker(0, 1, "legends", None, origin, normalize(criteria), 0, limit, seeds, out, final_from)
    return out.items


def matches_of(events):
    return [payload for kind, _index, payload in events if kind == "match"]


def odds_of(events, map_wanted=False):
    total = Odds(map_wanted=map_wanted)
    for kind, _index, payload in events:
        if kind == "progress":
            total.merge(*payload[1])
    return total


@pytest.mark.core
def test_worker_with_map_only_conditions_reports_roster_and_map(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(), criteria={"map": {"ports": 9}}, limit=30)
    matches = matches_of(events)
    assert [m["seed"] for m in matches] == ["0000000009", "0000000019", "0000000029"]
    assert all(m["roster"] and m["map"]["towns"] for m in matches)
    assert all(m["stable"] and m["failure"] is None for m in matches)
    assert FakeLab.roster_calls == 3 * 2       # only for passers: sift + confirm
    assert FakeLab.world_map_calls == 30 + 3   # every seed's map, and the confirming one of each match
    assert events[-1][0] == "done" and not [e for e in events if e[0] in ("error", "fatal")]
    odds = odds_of(events, map_wanted=True)
    assert odds.tested == 30 and odds.map == [30, 3] and odds.chance() == pytest.approx(0.1)


@pytest.mark.core
def test_roster_conditions_only_build_no_map(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(), criteria={"stars_by_slot": {"1": "hp1"}}, limit=30)
    matches = matches_of(events)
    assert [m["seed"] for m in matches] == [seed_text(n) for n in range(1, 30, 2)]
    assert FakeLab.world_map_calls == 0
    assert all(m["map"] is None for m in matches)
    assert odds_of(events).map is None


@pytest.mark.core
def test_roster_and_map_conditions_build_maps_only_for_roster_passers(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(), criteria={"stars_by_slot": {"1": "hp1"}, "map": {"ports": 9}},
                        limit=30)
    assert [m["seed"] for m in matches_of(events)] == ["0000000009", "0000000019", "0000000029"]
    assert FakeLab.roster_calls == 30 + 3      # every seed's roster, and the confirming one of each match
    assert FakeLab.world_map_calls == 15 + 3   # the odd seeds' maps (their brother 1 has the star), and the confirms
    # the factors have their own counts: 15 of 30 rosters pass, 3 of 15 maps
    odds = odds_of(events, map_wanted=True)
    assert odds.tested == 30 and odds.passed == [15, 30, 30] and odds.map == [15, 3]
    assert odds.chance() == pytest.approx(0.5 * 0.2)


@pytest.mark.dirty
def test_a_map_error_on_one_seed_does_not_stop_the_search(monkeypatch):
    """3 of 1,000 surveyed seeds raise in Legends' guaranteeAllBuildingsInSettlements: such a seed is an error event
    and the worker goes on - also when it is the worker's first seed."""
    for bad in ("0000000005", "0000000000"):
        events = run_worker(monkeypatch, FakeLab(map_errors={bad}), criteria={"map": {"ports": 9}}, limit=30)
        errors = [p for kind, _i, p in events if kind == "error"]
        assert len(errors) == 1 and bad in errors[0]
        assert [m["seed"] for m in matches_of(events)] == ["0000000009", "0000000019", "0000000029"]
        assert events[-1][0] == "done" and not [e for e in events if e[0] == "fatal"]


@pytest.mark.dirty
def test_a_map_generator_that_never_works_is_one_fatal_event(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(map_errors=True), criteria={"map": {"ports": 1}}, limit=30)
    kinds = [kind for kind, _i, _p in events]
    assert kinds.count("fatal") == 1 and "done" not in kinds and "error" not in kinds
    fatal = [p for kind, _i, p in events if kind == "fatal"][0]
    assert fatal.startswith("Map conditions do not work with this game setup: ") and "0000000000" in fatal
    assert FakeLab.world_map_calls == 2        # the first failure could be the seed's own: one more seed is tried


@pytest.mark.dirty
def test_a_map_error_in_roster_and_map_mode_is_skipped(monkeypatch):
    """With roster conditions too, a roster passer whose map run fails is an error event; its roster still counts in
    the odds (without a map), and the worker goes on."""
    events = run_worker(monkeypatch, FakeLab(map_errors={"0000000009"}),
                        criteria={"stars_by_slot": {"1": "hp1"}, "map": {"ports": 9}}, limit=30)
    errors = [p for kind, _i, p in events if kind == "error"]
    assert len(errors) == 1 and "0000000009" in errors[0]
    assert [m["seed"] for m in matches_of(events)] == ["0000000019", "0000000029"]
    assert events[-1][0] == "done" and not [e for e in events if e[0] == "fatal"]
    odds = odds_of(events, map_wanted=True)
    assert odds.tested == 30 and odds.passed[0] == 15 and odds.map == [14, 2]


@pytest.mark.dirty
def test_the_held_error_of_the_only_map_run_is_sent_at_the_end(monkeypatch):
    """A worker whose first map run fails holds that error until the next map tells whether every map fails. When
    there is no next map (one checked seed), the error is sent at the end, and it is no fatal event."""
    events = run_worker(monkeypatch, FakeLab(map_errors={"0000000005"}), criteria={"map": {"ports": 1}},
                        seeds=["0000000005"])
    kinds = [kind for kind, _i, _p in events]
    # (the checked seed's roster is reported too, with the failure "map could not be built": final review M3)
    assert kinds == ["ready", "progress", "match", "error", "progress", "done"]
    assert "0000000005" in events[3][2]


UNREVIEWED = {("World", "spawnEntity"): 2, ("entity", "getFoo"): 1}       # not in mapgen.HARMLESS_STUBS
HARMLESS = {("sprite", "varyColor"): 3, ("root", "updateAchievement"): 1}


@pytest.mark.dirty
def test_a_map_that_used_engine_functions_nobody_reviewed_is_an_error_for_that_seed(monkeypatch):
    """Final review I1: every unmodelled native returns a counted do-nothing stand-in; mapgen.HARMLESS_STUBS lists the
    reviewed ones. A map run that used any other one may be wrong without a sign, so it is a LabError like any map
    failure: the seed is skipped and reported, the worker goes on. The harmless ones change nothing."""
    bad = "0000000019"
    events = run_worker(monkeypatch, FakeLab(stubs={bad: UNREVIEWED, "0000000009": HARMLESS}),
                        criteria={"map": {"ports": 9}}, limit=30)
    errors = [p for kind, _i, p in events if kind == "error"]
    assert errors == ["map of seed %r uses engine functions that BB Reroll does not model: "
                      "World.spawnEntity, entity.getFoo" % bad]
    assert [m["seed"] for m in matches_of(events)] == ["0000000009", "0000000029"]       # 19 is skipped, 9 is not
    assert events[-1][0] == "done" and not [e for e in events if e[0] == "fatal"]


@pytest.mark.dirty
def test_maps_that_always_use_engine_functions_nobody_reviewed_end_the_search_with_a_map_fatal(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(stubs=lambda seed: UNREVIEWED), criteria={"map": {"ports": 1}}, limit=30)
    kinds = [kind for kind, _i, _p in events]
    assert kinds.count("fatal") == 1 and "done" not in kinds and "error" not in kinds
    fatal = [p for kind, _i, p in events if kind == "fatal"][0]
    assert fatal.startswith(S.MAP_FATAL) and "World.spawnEntity" in fatal and "0000000000" in fatal
    assert FakeLab.world_map_calls == 2


@pytest.mark.dirty
def test_the_confirming_map_is_checked_too(monkeypatch):
    """A match is confirmed with a second map; when that one used unreviewed functions the seed is skipped."""
    class SecondUnreviewed(FakeLab):
        def world_map(self, seed, *args, **kwargs):
            out = FakeLab.world_map(self, seed, *args, **kwargs)
            if self.builds[seed] >= 2:      # (the real lab is deterministic: the map without its start fails the same)
                out["stub_uses"] = UNREVIEWED
            return out
    events = run_worker(monkeypatch, SecondUnreviewed(), criteria={"map": {"ports": 9}}, limit=10)
    assert matches_of(events) == []
    errors = [p for kind, _i, p in events if kind == "error"]
    assert len(errors) == 1 and "0000000009" in errors[0] and "World.spawnEntity" in errors[0]


@pytest.mark.dirty
def test_a_checked_seed_whose_map_could_not_be_built_still_gets_its_roster(monkeypatch):
    """Final review M3: "Check a seed" with a map condition whose map run fails (3 in 1,000 seeds, or a map that used
    unreviewed functions) reports the roster, with the failure "map could not be built: <reason>" and no map. The
    reason is also an error event (the GUI shows it as a notice)."""
    from bbseed.mapgen import MAP_NOT_BUILT
    assert MAP_NOT_BUILT == "map could not be built: "
    # map conditions only: the map is built first
    events = run_worker(monkeypatch, FakeLab(map_errors={"0000000003"}), criteria={"map": {"ports": 9}},
                        seeds=["0000000003"])
    [m] = matches_of(events)
    assert m["seed"] == "0000000003" and m["map"] is None and len(m["roster"]) == ROSTER_SIZE
    assert m["failure"] == MAP_NOT_BUILT + "map of seed '0000000003': the index '0' does not exist"
    assert [p for kind, _i, p in events if kind == "error"] == [m["failure"][len(MAP_NOT_BUILT):]]
    assert events[-1][0] == "done" and not [e for e in events if e[0] == "fatal"]
    # a good seed after it is reported as it was (and the held error of the first is sent when it works)
    events = run_worker(monkeypatch, FakeLab(map_errors={"0000000003"}), criteria={"map": {"ports": 9}},
                        seeds=["0000000003", "0000000009"])
    got = {m["seed"]: m for m in matches_of(events)}
    assert set(got) == {"0000000003", "0000000009"}
    assert got["0000000003"]["map"] is None and got["0000000003"]["failure"].startswith(MAP_NOT_BUILT)
    assert got["0000000009"]["map"] and got["0000000009"]["failure"] is None
    # unreviewed engine functions are the same case
    events = run_worker(monkeypatch, FakeLab(stubs={"0000000005": UNREVIEWED}), criteria={"map": {"ports": 9}},
                        seeds=["0000000005"])
    [m] = matches_of(events)
    assert m["map"] is None and "World.spawnEntity, entity.getFoo" in m["failure"] and m["failure"].startswith(MAP_NOT_BUILT)
    # with brother conditions too: a roster that meets them gets the map failure; one that fails keeps its own failure
    both = {"stars_by_slot": {"1": "hp1"}, "map": {"ports": 9}}
    events = run_worker(monkeypatch, FakeLab(map_errors={"0000000001"}), criteria=both, seeds=["0000000001"])
    [m] = matches_of(events)
    assert m["map"] is None and m["failure"].startswith(MAP_NOT_BUILT) and m["roster"]
    events = run_worker(monkeypatch, FakeLab(map_errors={"0000000002"}), criteria=both, seeds=["0000000002"])
    [m] = matches_of(events)
    assert m["map"] is None and m["failure"] == "bro1 hp*0<1" and m["roster"]


@pytest.mark.dirty
def test_a_map_code_exception_that_is_no_lab_error_is_a_map_fatal(monkeypatch):
    """Fix round 1: an exception of the map code that is not a LabError (a bug, or map data the code cannot read)
    must not kill the worker silently (search() would wait forever): one MAP_FATAL event, the worker stops."""
    for lab in (FakeLab(map_crash=RuntimeError("tile natives are missing")),
                FakeLab(first_map=lambda m: dict(m, towns=[dict(m["towns"][0], size=4)]))):   # town_type: ValueError
        events = run_worker(monkeypatch, lab, criteria={"map": {"ports": 1}}, limit=30)
        kinds = [kind for kind, _i, _p in events]
        assert kinds == ["ready", "fatal"], kinds
        fatal = events[1][2]
        assert fatal.startswith(S.MAP_FATAL) and "(seed 0000000000)" in fatal
        assert ("RuntimeError: tile natives are missing" in fatal) or ("ValueError: town" in fatal)


@pytest.mark.dirty
def test_an_unexpected_roster_exception_is_a_fatal_event(monkeypatch, capsys):
    """Fix round 1, the roster path (the same gap from before Task 9): one fatal event with the exception's type and
    text and the seed, instead of a worker that dies silently."""
    events = run_worker(monkeypatch, FakeLab(roster_crash=KeyError("talents")), criteria={"stars_by_slot": {"1": "hp1"}},
                        limit=30)
    assert [kind for kind, _i, _p in events] == ["ready", "fatal"]
    assert events[1][2] == "KeyError: 'talents' (seed 0000000000)"
    assert "Traceback" in capsys.readouterr().err          # the worker's console gets the whole traceback


@pytest.mark.dirty
def test_world_map_turns_a_map_path_that_cannot_load_into_a_lab_error(monkeypatch):
    """Fix round 1: the first world_map() makes mapgen.MapRun, which runs scripts. A script error there (a game
    setup whose map scripts the lab cannot run) must be a LabError like any failed map run, so the worker's
    two-failure rule turns it into MAP_FATAL; before, it escaped as SqError. No game needed: a Lab shell."""
    from bbseed import lab as L, mapgen
    from bbseed.sq.runtime import SqError

    class VM:
        def __init__(self):
            self.stack, self.last_trace = ["frame"], []

        def compile(self, src, name):
            return object()

        def note_trace(self, depth):
            self.last_trace = ["map_generator (scripts/mapgen/map_generator.nut:12)"]

    def cannot_load(*args):
        raise SqError("the index 'MapGen' does not exist")

    monkeypatch.setattr(mapgen, "MapRun", cannot_load)
    lab = L.Lab.__new__(L.Lab)
    lab.eng, lab.world, lab._maps, lab._blackmarket = SimpleNamespace(vm=VM(), root=None), None, None, None
    with pytest.raises(LabError, match=r"map of seed '42': the index 'MapGen' does not exist \(at map_generator"):
        lab.world_map("42")
    assert lab._maps is None and lab._blackmarket is None and lab.eng.vm.stack == []    # tried again next time


@pytest.mark.edge
def test_the_stable_flag_covers_the_map(monkeypatch):
    """The confirming map must have the sift map's towns and ports; when it has not, the match is not stable."""
    events = run_worker(monkeypatch, FakeLab(second_map=lambda m: fake_map(9, shift=1)),
                        criteria={"map": {"ports": 9}}, limit=10)
    [match] = matches_of(events)
    assert match["seed"] == "0000000009" and match["failure"] is None and not match["stable"]
    assert match["map"]["towns"][0]["x"] == 1                 # the payload has the confirming map


@pytest.mark.dirty
def test_a_map_that_fails_when_built_again_is_skipped(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(second_map=lambda m: fake_map(2)), criteria={"map": {"ports": 9}},
                        limit=10)
    assert matches_of(events) == []
    errors = [p for kind, _i, p in events if kind == "error"]
    assert len(errors) == 1 and "0000000009" in errors[0]


@pytest.mark.core
def test_checking_seeds_with_map_conditions_reports_every_seed(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(), criteria={"map": {"ports": 9}}, seeds=["0000000003", "0000000009"])
    got = {m["seed"]: m for m in matches_of(events)}
    assert got["0000000003"]["failure"] == "Ports: 3, needs 9" and got["0000000009"]["failure"] is None
    assert all(m["map"] and m["roster"] and m["stable"] for m in got.values())
    assert FakeLab.world_map_calls == 2 and FakeLab.roster_calls == 4, "one map for each seed; the roster is rolled again"
    # with a roster condition too, a checked seed whose roster fails still gets its map
    events = run_worker(monkeypatch, FakeLab(), criteria={"stars_by_slot": {"1": "hp1"}, "map": {"ports": 9}},
                        seeds=["0000000002"])
    [m] = matches_of(events)
    assert m["failure"] == "bro1 hp*0<1" and m["map"]["towns"]


@pytest.mark.core
def test_odds_count_the_map_as_one_more_factor_with_its_own_count():
    c = normalize({"stars_by_slot": {"1": "hp1"}, "map": {"ports": 1}})
    odds = Odds(map_wanted=True)
    odds.add_roster([bro(hp=0)], c)
    odds.add_roster([bro(hp=0)], c)
    odds.add_roster([bro(hp=1)], c)
    assert odds.chance() is None and not odds.map_never()     # the map factor is not measured yet
    odds.add_roster([bro(hp=1)], c, map=False)
    assert odds.map_never() and odds.chance() == 0.0
    odds.add_roster([bro(hp=1)], c, map=True)
    assert odds.tested == 5 and odds.passed == [3] and odds.map == [2, 1]
    assert odds.chance() == pytest.approx(0.6 * 0.5) and not odds.map_never()
    total = Odds(map_wanted=True)
    total.merge(*odds.take())
    assert odds.map is None and odds.tested == 0
    assert total.map == [2, 1] and total.chance() == pytest.approx(0.3)
    # map conditions only: the map is the only factor (a seed whose map fails has no roster)
    only = Odds(map_wanted=True)
    for ok in (True, False, False, True):
        only.add([], map=ok)
    assert only.chance() == 0.5 and only.never() == [] and only.tested == 4
    # a worker's counts without a map (the old three) still merge
    plain = Odds()
    plain.merge(2, [1], None)
    assert plain.chance() == 0.5 and plain.map is None and not plain.map_never()


@pytest.mark.core
def test_odds_brothers_chance_is_the_rosters_part_of_the_estimate_without_the_map_factor():
    """Final review M7: with brother and map conditions the full estimate waits for 30 maps; the brothers' rate is
    known after the first seeds, so the progress event carries it too (map factor: Odds.chance)."""
    c = normalize({"stars_by_slot": {"1": "hp1"}, "map": {"ports": 1}})
    odds = Odds(map_wanted=True)
    assert odds.brothers_chance() is None
    for hp in (0, 0, 0, 1):
        odds.add_roster([bro(hp=hp)], c)
    assert odds.chance() is None                                  # no map built yet
    assert odds.brothers_chance() == pytest.approx(0.25)
    odds.add_roster([bro(hp=1)], c, map=False)
    odds.add_roster([bro(hp=1)], c, map=True)
    assert odds.brothers_chance() == pytest.approx(3 / 6)
    assert odds.chance() == pytest.approx(0.5 * 0.5)              # = brothers_chance() * the maps' rate 1 of 2
    # the whole-roster (background "any") condition is part of the brothers' rate
    odds = Odds()
    odds.add([], team=True)
    odds.add([], team=False)
    assert odds.brothers_chance() == pytest.approx(0.5) and odds.chance() == pytest.approx(0.5)


class ThreadContext:
    """multiprocessing's spawn context for search(), with its workers as threads of this process (so the replaced
    _make_lab reaches them)."""
    Queue = queue.Queue

    class Process:
        def __init__(self, target, args, daemon=True):
            self.thread = threading.Thread(target=target, args=args, daemon=True)

        def start(self):
            self.thread.start()

        def is_alive(self):
            return self.thread.is_alive()

        def terminate(self):
            pass


def run_search(monkeypatch, lab_factory, criteria, origin="trader_scenario", **kwargs):
    import bbseed.profiles
    monkeypatch.setattr(bbseed.profiles, "get", lambda *args, **kw: None)
    monkeypatch.setattr(S, "mp", SimpleNamespace(get_context=lambda kind: ThreadContext))
    monkeypatch.setattr(S, "_make_lab", lambda profile, mod_settings: lab_factory())
    events = []
    found = S.search("legends", origin, criteria, start=0, on_event=lambda k, p: events.append((k, p)), **kwargs)
    return found, events


@pytest.mark.core
def test_search_reports_the_map_of_a_match(monkeypatch):
    found, events = run_search(monkeypatch, FakeLab, {"map": {"ports": 9}}, workers=2, max_seeds=20, count=2)
    assert sorted(m["seed"] for m in found) == ["0000000009", "0000000019"]
    assert all(m["map"]["towns"] and m["roster"] for m in found)
    progress = [p for k, p in events if k == "progress"]
    odds = progress[-1][3]
    assert set(odds) >= {"chance", "chance_brothers", "never", "never_any", "never_map", "maps", "tested"}
    assert odds["maps"] >= 10 and odds["never_map"] is False
    assert events[-1][0] == "finished"


@pytest.mark.dirty
def test_search_ends_at_the_first_map_fatal(monkeypatch):
    """A game setup whose map generator does not work: every worker finds it, the player gets ONE fatal event."""
    found, events = run_search(monkeypatch, lambda: FakeLab(map_errors=True), {"map": {"ports": 1}}, workers=3,
                               max_seeds=30, count=1)
    assert found == []
    fatal = [p for k, p in events if k == "fatal"]
    assert len(fatal) == 1 and fatal[0].startswith("Map conditions do not work with this game setup: ")
    assert events[-1][0] == "finished"


@pytest.mark.dirty
def test_search_returns_after_unexpected_worker_exceptions(monkeypatch):
    """Fix round 1: before it, a worker exception that was not a LabError ended the worker without "done" or
    "fatal", and search() waited until Stop. Map path: one MAP_FATAL ends the search. Roster path: every worker
    sends its fatal event and search() returns when the last one has."""
    found, events = run_search(monkeypatch, lambda: FakeLab(map_crash=RuntimeError("no tiles")), {"map": {"ports": 1}},
                               workers=3, max_seeds=30, count=1)
    fatal = [p for k, p in events if k == "fatal"]
    assert found == [] and len(fatal) == 1 and fatal[0].startswith(S.MAP_FATAL + "RuntimeError: no tiles")
    assert events[-1][0] == "finished"
    found, events = run_search(monkeypatch, lambda: FakeLab(roster_crash=RuntimeError("bad roster")),
                               {"stars_by_slot": {"1": "hp1"}}, workers=2, max_seeds=30, count=1)
    fatal = [p for k, p in events if k == "fatal"]
    assert found == [] and len(fatal) == 2 and all(p.startswith("RuntimeError: bad roster (seed ") for p in fatal)
    assert events[-1][0] == "finished"


@pytest.mark.core
def test_cli_map_flags(monkeypatch, capsys):
    got = {}
    monkeypatch.setattr(S, "search", lambda profile, origin, criteria, **kw: got.update(criteria=criteria))
    S.main(["--origin", "trader_scenario", "--ports", "4", "--ports-south", "1", "--ports-north", "1",
            "--north-band", "20", "--towns", "city_state=2", "--towns", "size3=3",
            "--mod-setting", "mod_legends:Settlements=24"])
    assert got["criteria"]["map"] == {"ports": 4, "ports_south": 1, "ports_north": 1, "north_band": 20,
                                      "towns": {"city_state": 2, "size3": 3}}
    S.main(["--origin", "trader_scenario", "--stars", "1", "hp1"])
    assert got["criteria"]["map"] is None


@pytest.mark.dirty
def test_cli_bad_towns_flags_exit_and_name_the_flag(monkeypatch, capsys):
    monkeypatch.setattr(S, "search", lambda profile, origin, criteria, **kw: None)
    for bad in (["--towns", "castle=2"], ["--towns", "size1"], ["--towns", "size1=x"]):
        with pytest.raises(SystemExit):
            S.main(["--origin", "trader_scenario"] + bad)
    assert "--towns" in capsys.readouterr().err


def run_cli_events(monkeypatch, capsys, events, argv):
    """S.main(argv) with a search() that plays these events to the console's on_event; the console output."""
    def fake_search(profile, origin, criteria, **kw):
        for kind, payload in events:
            kw["on_event"](kind, payload)
        return []
    monkeypatch.setattr(S, "search", fake_search)
    S.main(argv)
    return capsys.readouterr().out


VERIFIED_INFO = {"game_version": "1.5.2.3", "legends_version": "19.4.22",
                 "mods": [{"file": "mod_legends-19.4.22.zip", "id": "mod_legends", "version": "19.4.22"},
                          {"file": "mod_legends-assets-19.4.3.zip", "id": "mod_legends_assets", "version": "19.4.3"},
                          {"file": "mod_modern_hooks-685-0-6-0-1748620177.zip", "id": "mod_modern_hooks",
                           "version": "0.6.0"},
                          {"file": "mod_msu 479 1.9.0 2026-06-23T04-27Z eVJjKbX9c.zip", "id": "mod_msu",
                           "version": "1.9.0"}]}
NOTE = "Map results are not verified for this setup."


@pytest.mark.dirty
def test_the_console_notes_an_unverified_setup_once_for_a_search_with_map_conditions(monkeypatch, capsys):
    """Final review M10: map conditions on a game / Legends version / mod set that nobody checked build maps with
    no sign; the console says so (once: every worker reports the same setup). ASCII only."""
    unverified = dict(VERIFIED_INFO, mods=VERIFIED_INFO["mods"] + [{"file": "mod_other-1.0.zip", "id": "mod_other"}])
    ready = [("ready", (1, 2, unverified)), ("ready", (2, 2, unverified))]
    out = run_cli_events(monkeypatch, capsys, ready, ["--origin", "trader_scenario", "--ports", "4"])
    assert out.count(NOTE) == 1 and out.index("worker 1 of 2") < out.index(NOTE) < out.index("worker 2 of 2")
    assert NOTE.isascii()
    # a verified setup: no note; no map condition: no note; another version of the game or Legends: the note
    ready = [("ready", (1, 1, VERIFIED_INFO))]
    assert NOTE not in run_cli_events(monkeypatch, capsys, ready, ["--origin", "trader_scenario", "--ports", "4"])
    ready = [("ready", (1, 1, unverified))]
    assert NOTE not in run_cli_events(monkeypatch, capsys, ready, ["--origin", "trader_scenario", "--stars", "1", "hp1"])
    for changed in ({"game_version": "1.5.3.0"}, {"legends_version": "19.5.0"}, {"legends_version": None}):
        ready = [("ready", (1, 1, dict(VERIFIED_INFO, **changed)))]
        assert NOTE in run_cli_events(monkeypatch, capsys, ready, ["--origin", "trader_scenario", "--ports", "4"])


@pytest.mark.dirty
def test_setup_note_for_vanilla_needs_every_dlc_and_fails_closed():
    """The note is fail-closed: an info without "dlc_complete" is not verified for Vanilla (Lab.info() gives it)."""
    assert S._setup_note({"game_version": "1.5.2.3", "legends_version": None, "mods": []}) == NOTE
    assert S._setup_note({"game_version": "1.5.2.3", "legends_version": None, "mods": [],
                          "dlc_complete": False}) == NOTE
    assert S._setup_note({"game_version": "1.5.2.3", "legends_version": None, "mods": [],
                          "dlc_complete": True}) is None
    assert S._setup_note({"game_version": "1.5.2.3", "legends_version": None, "mods": ["mod_msu.zip"],
                          "dlc_complete": True}) == NOTE
    assert S._setup_note({"game_version": "1.5.2.3", "legends_version": "19.4.22", "mods": []}) is None
    assert S._setup_note({"game_version": "1.5.2.3", "legends_version": "19.4.22", "mods": [],
                          "dlc_complete": True}) is None


@pytest.mark.edge
def test_the_console_hint_for_a_map_search_that_found_no_map_waits_for_100_maps(monkeypatch, capsys):
    """Final review I2: 6 or more ports are 3.9 % of the maps, so 0 hits in 20 maps is normal (45 %) and 0 in 100
    is not (2 %). The hint says the maps are rare; it does not say that no seed matches."""
    assert S.MAP_NEVER_MAPS == 100
    odds = lambda maps: {"chance": 0.0, "never": [], "never_map": True, "maps": maps, "tested": maps}   # noqa: E731
    out = run_cli_events(monkeypatch, capsys, [("progress", (99, 60.0, 0, odds(99))),
                                               ("progress", (100, 61.0, 0, odds(100)))],
                         ["--origin", "trader_scenario", "--ports", "7"])
    lines = [line for line in out.splitlines() if "seeds tested" in line]
    assert len(lines) == 2 and "map" not in lines[0]
    assert lines[1].endswith(", no map met the map conditions in 100 maps (such maps are rare)")
    assert "no seed matches" not in out.lower() and "possibly" not in out.lower()


# ---------------------------------------------------------------------- Deserters (stage 2 C2 Task 4)
DESERTERS = S.DESERTERS_SCRIPT


class DesertersLab(FakeLab):
    """A stand-in lab on a verified setup (Deserters are searched only there). Seed n: brother 1 has n % 2 HP stars and
    the map has n % 10 ports, as for FakeLab; the roster comes from the start run (world_map stop_at="spawn")."""

    def info(self):
        return dict(VERIFIED_INFO, dlc_complete=True)


@pytest.mark.core
def test_deserters_get_their_roster_from_the_map_run_not_from_a_roster_call(monkeypatch):
    lab = DesertersLab()
    events = run_worker(monkeypatch, lab, {"stars_by_slot": {"1": "hp1"}}, limit=10, origin=DESERTERS)
    matches = matches_of(events)
    assert [m["seed"] for m in matches] == [seed_text(n) for n in (1, 3, 5, 7, 9)]
    assert FakeLab.roster_calls == 0
    assert FakeLab.world_map_calls == 10 + 5            # a map run for every seed, and the confirming run of each match
    assert lab.map_calls.count(("spawn", False)) == 10 and lab.map_calls.count(("spawn", True)) == 5, (
        "every run goes on through the start; the confirming ones have the perk trees")
    assert lab.blackmarket == [0] * 15, "every map is built as a first campaign (ruling AD)"
    assert all(m["stable"] and m["failure"] is None and m["map"] is None for m in matches), "no map condition: no map"
    assert all(b.get("perk_groups") == [] for m in matches for b in m["roster"])
    assert events[-1][0] == "done" and not [e for e in events if e[0] in ("error", "fatal")]


@pytest.mark.edge
def test_deserters_odds_count_every_map_as_one_that_meets_a_condition_that_is_not_there(monkeypatch):
    events = run_worker(monkeypatch, DesertersLab(), {"stars_by_slot": {"1": "hp1"}}, limit=20, origin=DESERTERS)
    odds = odds_of(events)
    assert odds.tested == 20 and odds.passed == [10, 20, 20] and odds.map == [20, 20]
    assert odds.maps() == 20 and odds.chance() == pytest.approx(0.5) and not odds.map_never()


@pytest.mark.edge
def test_deserters_with_map_conditions_check_the_same_map(monkeypatch):
    lab = DesertersLab()
    events = run_worker(monkeypatch, lab, {"stars_by_slot": {"1": "hp1"}, "map": {"ports": 7}}, limit=30,
                        origin=DESERTERS)
    matches = matches_of(events)
    assert [m["seed"] for m in matches] == ["0000000007", "0000000009", "0000000017", "0000000019", "0000000027",
                                           "0000000029"]
    assert all(m["map"]["towns"] and m["stable"] and m["failure"] is None for m in matches)
    assert FakeLab.world_map_calls == 30 + 6            # every seed's map (the roster is in it), and the confirming runs
    odds = odds_of(events, map_wanted=True)
    assert odds.map == [30, 9] and odds.passed == [15, 30, 30]      # 3 of 10 maps have 7+ ports; half the seeds the star
    assert odds.chance() == pytest.approx(0.5 * 0.3)


@pytest.mark.edge
def test_deserters_with_map_conditions_only(monkeypatch):
    events = run_worker(monkeypatch, DesertersLab(), {"map": {"ports": 9}}, limit=30, origin=DESERTERS)
    assert [m["seed"] for m in matches_of(events)] == ["0000000009", "0000000019", "0000000029"]
    assert FakeLab.roster_calls == 0 and FakeLab.world_map_calls == 33


@pytest.mark.core
def test_deserters_checked_seeds_report_the_roster_and_the_failure(monkeypatch):
    events = run_worker(monkeypatch, DesertersLab(), {"stars_by_slot": {"1": "hp1"}},
                        seeds=["0000000002", "0000000003"], origin=DESERTERS)
    found = {m["seed"]: m for m in matches_of(events)}
    assert found["0000000003"]["failure"] is None
    assert found["0000000002"]["failure"] == "bro1 hp*0<1"
    assert all(m["roster"] and m["map"] is None for m in found.values())


@pytest.mark.dirty
def test_a_deserters_map_error_skips_that_seed_and_a_checked_one_has_no_roster(monkeypatch):
    events = run_worker(monkeypatch, DesertersLab(map_errors={"0000000005"}), {"stars_by_slot": {"1": "hp1"}},
                        limit=10, origin=DESERTERS)
    errors = [p for kind, _i, p in events if kind == "error"]
    assert len(errors) == 1 and "0000000005" in errors[0]
    assert [m["seed"] for m in matches_of(events)] == [seed_text(n) for n in (1, 3, 7, 9)]
    assert events[-1][0] == "done" and not [e for e in events if e[0] == "fatal"]
    events = run_worker(monkeypatch, DesertersLab(map_errors={"0000000005"}), {"stars_by_slot": {"1": "hp1"}},
                        seeds=["0000000005"], origin=DESERTERS)
    assert not matches_of(events) and [p for kind, _i, p in events if kind == "error"]


@pytest.mark.dirty
def test_a_deserters_map_that_fails_twice_without_one_that_worked_is_a_deserters_fatal(monkeypatch):
    events = run_worker(monkeypatch, DesertersLab(map_errors=True), {"stars_by_slot": {"1": "hp1"}}, limit=30,
                        origin=DESERTERS)
    fatal = [p for kind, _i, p in events if kind == "fatal"]
    assert len(fatal) == 1 and fatal[0].startswith(S.DESERTERS_FATAL) and "0000000000" in fatal[0]
    assert not fatal[0].startswith(S.MAP_FATAL) and FakeLab.world_map_calls == 2
    events = run_worker(monkeypatch, DesertersLab(map_crash=RuntimeError("no tiles")), {"stars_by_slot": {"1": "hp1"}},
                        limit=30, origin=DESERTERS)
    fatal = [p for kind, _i, p in events if kind == "fatal"]
    assert len(fatal) == 1 and fatal[0].startswith(S.DESERTERS_FATAL + S.DESERTERS_MAP_FAILED + "RuntimeError: no tiles")
    # a fault of the map code does not blame the game setup (the setup text is for an unverified setup only)
    assert "setup" not in fatal[0].split("(seed")[0]
    assert S.DESERTERS_FATAL == "BB Reroll cannot search Deserters: "


def _with_version(mod_id, version):
    """VERIFIED_INFO's mods with one mod at another version."""
    return [dict(m, version=version) if m["id"] == mod_id else dict(m) for m in VERIFIED_INFO["mods"]]


@pytest.mark.dirty
def test_deserters_need_a_verified_setup(monkeypatch):
    """Their brothers are made on the map: on a setup whose maps nobody checked the search stops with one fatal event
    and builds no map. Another origin is not held back."""
    for info in (dict(VERIFIED_INFO, dlc_complete=True, game_version="1.5.3.0"),
                 dict(VERIFIED_INFO, dlc_complete=True, legends_version="19.5.0"),
                 dict(VERIFIED_INFO, dlc_complete=True, mods=VERIFIED_INFO["mods"] + [{"file": "mod_other-1.0.zip"}]),
                 dict(VERIFIED_INFO, dlc_complete=True, mods=_with_version("mod_msu", "1.8.0")),
                 dict(VERIFIED_INFO, dlc_complete=True, mods=_with_version("mod_modern_hooks", "0.5.9")),
                 dict(VERIFIED_INFO, dlc_complete=True, mods=_with_version("mod_legends_assets", "19.4.2")),
                 {"game_version": "1.5.2.3", "legends_version": None, "mods": [], "dlc_complete": False},
                 {"profile": "fake"}):
        lab = DesertersLab()
        lab.info = lambda info=info: info
        events = run_worker(monkeypatch, lab, {"stars_by_slot": {"1": "hp1"}}, limit=10, origin=DESERTERS)
        assert [kind for kind, _i, _p in events] == ["fatal"], info
        assert events[0][2].startswith(S.DESERTERS_FATAL) and "maps" in events[0][2]
        assert FakeLab.world_map_calls == 0 and FakeLab.roster_calls == 0
    events = run_worker(monkeypatch, FakeLab(), {"stars_by_slot": {"1": "hp1"}}, limit=10)
    assert events[0][0] == "ready" and len(matches_of(events)) == 5


@pytest.mark.dirty
def test_a_deserters_search_ends_at_the_first_deserters_fatal(monkeypatch):
    found, events = run_search(monkeypatch, lambda: DesertersLab(map_errors=True), {"stars_by_slot": {"1": "hp1"}},
                               origin=DESERTERS, workers=3, max_seeds=30, count=1)
    assert found == []
    fatal = [p for k, p in events if k == "fatal"]
    assert len(fatal) == 1 and fatal[0].startswith(S.DESERTERS_FATAL)
    assert events[-1][0] == "finished"
    found, events = run_search(monkeypatch, DesertersLab, {"stars_by_slot": {"1": "hp1"}}, origin=DESERTERS,
                               workers=2, max_seeds=20, count=3)
    assert len(found) == 3 and all(m["roster"] and m["map"] is None for m in found)
    progress = [p for k, p in events if k == "progress"]
    assert progress[-1][3]["maps"] == progress[-1][3]["tested"] > 0


@pytest.mark.core
def test_the_console_says_when_to_start_a_deserters_seed(monkeypatch, capsys):
    """Legends' black-market counter: every map of a search is built at 0, so the seed is for the first campaign after
    the game starts. The base game has none; no other origin gets the line."""
    line = "Start this seed as your first campaign after you start the game."
    match = ("match", {"seed": "0000000001", "stable": True, "failure": None, "map": None, "roster": [
        {"name": "Hans", "background": "background.deserter", "background_name": "Deserter", "level": 1, "stars": dict(ZERO),
         "traits": [], "trait_names": [], "gear": [], "base": dict(ZERO), "shown": dict(ZERO)}]})
    legends = [("ready", (1, 1, dict(VERIFIED_INFO, dlc_complete=True))), match]
    out = run_cli_events(monkeypatch, capsys, legends, ["--origin", DESERTERS, "--stars", "1", "hp1"])
    assert out.count(line) == 1 and out.index("MATCH") < out.index(line)
    vanilla = [("ready", (1, 1, {"game_version": "1.5.2.3", "legends_version": None, "mods": [], "dlc_complete": True})),
               match]
    assert line not in run_cli_events(monkeypatch, capsys, vanilla, ["--origin", DESERTERS, "--stars", "1", "hp1"])
    assert line not in run_cli_events(monkeypatch, capsys, legends, ["--origin", "trader_scenario", "--stars", "1", "hp1"])


DESERTER_BRO = {"name": "Hans", "background": "background.deserter", "background_name": "Deserter", "level": 1,
                "stars": dict(ZERO), "traits": [], "trait_names": [], "gear": [], "base": dict(ZERO), "shown": dict(ZERO)}
OPTIONS = {"Settlements": 24, "Water": 38}


@pytest.mark.core
def test_the_console_match_of_a_deserters_search_shows_the_map_options(monkeypatch, capsys):
    legends = dict(VERIFIED_INFO, dlc_complete=True, map_options=OPTIONS)
    match = ("match", {"seed": "0000000001", "stable": True, "failure": None, "map": None, "roster": [DESERTER_BRO]})
    out = run_cli_events(monkeypatch, capsys, [("ready", (1, 1, legends)), match],
                         ["--origin", DESERTERS, "--stars", "1", "hp1"])
    assert "   Map Options used: Settlements 24, Water 38" in out
    vanilla = {"game_version": "1.5.2.3", "legends_version": None, "mods": [], "dlc_complete": True, "map_options": {}}
    out = run_cli_events(monkeypatch, capsys, [("ready", (1, 1, vanilla)), match],
                         ["--origin", DESERTERS, "--stars", "1", "hp1"])
    assert "Map Options used" not in out and "first campaign" not in out, "the base game has no Map Options"


@pytest.mark.core
def test_show_a_deserters_seed_runs_the_whole_map_for_the_roster(monkeypatch, capsys):
    """--show SEED --origin deserters_scenario: the brothers are made on the map, so the roster comes from the map run
    on through the start (with the perk trees, the counter at 0), never from Lab.roster_with_perks."""
    import bbseed.lab as lab_module
    calls = []

    class FakeShowLab:
        def __init__(self, profile, mod_settings=None):
            pass

        def watch_rolls(self):
            return self

        def info(self):
            return dict(VERIFIED_INFO, dlc_complete=True, map_options=OPTIONS)

        def roster_with_perks(self, seed, origin):
            raise AssertionError("a Deserters roster does not exist without its map")

    def fake_map(lab, seed, origin, **kwargs):
        calls.append((seed, origin, kwargs))
        return {"roster": [DESERTER_BRO], "stub_uses": {}}
    monkeypatch.setattr(lab_module, "Lab", FakeShowLab)
    monkeypatch.setattr(lab_module, "big_stack", lambda fn: fn())
    monkeypatch.setattr(S, "checked_world_map", fake_map)
    S.main(["--show", "1234567890", "--origin", DESERTERS])
    out = capsys.readouterr().out
    assert calls == [("1234567890", DESERTERS, {"stop_at": "spawn", "perks": True, "blackmarket": 0})]
    assert "seed 1234567890, origin deserters_scenario:" in out and "Hans" in out
    assert out.count("Start this seed as your first campaign after you start the game.") == 1
    assert "Map Options used: Settlements 24, Water 38" in out and NOTE not in out


# ---------------------------------------------------------------- the company's start tile on the map (stage 2 C1)
@pytest.mark.core
def test_a_match_with_a_map_carries_the_start_tile_of_the_confirming_map(monkeypatch):
    """Every origin's confirming map is run on through the start (the sift maps are not: the start is no condition),
    so the payload's map has "start" = the party's square."""
    lab = FakeLab()
    events = run_worker(monkeypatch, lab, criteria={"map": {"ports": 9}}, limit=10)
    [match] = matches_of(events)
    assert match["seed"] == "0000000009" and match["map"]["start"] == [12, 40]
    assert lab.map_calls == [("reseed", False)] * 10 + [("spawn", False)], "the sift maps stay as they were"
    assert lab.blackmarket == [0] * 11


@pytest.mark.core
def test_a_checked_seed_gets_a_start_on_its_map(monkeypatch):
    lab = FakeLab()
    events = run_worker(monkeypatch, lab, criteria={"map": {"ports": 1}}, seeds=["0000000004"])
    [match] = matches_of(events)
    assert match["map"]["start"] == [7, 40]
    assert lab.map_calls == [("spawn", False)], "its one map is built, on through the start"


@pytest.mark.edge
def test_a_checked_seed_with_brother_conditions_builds_one_map_too(monkeypatch):
    lab = FakeLab()
    events = run_worker(monkeypatch, lab, criteria={"stars_by_slot": {"1": "hp1"}, "map": {"ports": 1}}, seeds=["0000000004"])
    [match] = matches_of(events)
    assert match["map"]["start"] == [7, 40] and lab.map_calls == [("spawn", False)]


@pytest.mark.dirty
def test_a_checked_seed_without_a_start_keeps_its_map(monkeypatch):
    lab = FakeLab()
    lab.spawn_error = "the index 'x' does not exist"
    events = run_worker(monkeypatch, lab, criteria={"map": {"ports": 1}}, seeds=["0000000004"])
    [match] = matches_of(events)
    assert match["map"] and "start" not in match["map"] and match["failure"] is None
    assert lab.map_calls == [("spawn", False), ("reseed", False)]
    assert not [e for e in events if e[0] in ("error", "fatal")]


@pytest.mark.core
def test_a_checked_seed_still_rolls_its_roster_again(monkeypatch):
    class OtherFreshRoster(FakeLab):
        def roster_with_perks(self, seed, origin):
            return [dict(b, name="Other", perk_groups=[], single_perks=[]) for b in self._bros(seed)]
    events = run_worker(monkeypatch, OtherFreshRoster(), criteria={"map": {"ports": 1}}, seeds=["0000000004"])
    [match] = matches_of(events)
    assert not match["stable"], "the one map changes nothing for the roster's check"


@pytest.mark.core
def test_a_checked_deserters_seed_has_one_map_run_with_the_perk_trees(monkeypatch):
    lab = DesertersLab()
    events = run_worker(monkeypatch, lab, {"stars_by_slot": {"1": "hp1"}, "map": {"ports": 1}}, seeds=["0000000003"],
                        origin=DESERTERS)
    [match] = matches_of(events)
    assert lab.map_calls == [("spawn", True)] and FakeLab.roster_calls == 0
    assert match["map"]["start"] == [6, 40] and all(b["perk_groups"] == [] for b in match["roster"])
    assert match["stable"] and match["failure"] is None


@pytest.mark.dirty
def test_a_start_that_cannot_be_made_leaves_the_map_without_one(monkeypatch):
    """The start is a picture only: an origin whose start the lab cannot run (a mod's) must not lose its matches."""
    lab = FakeLab()
    lab.spawn_error = "map of seed '9': the index 'x' does not exist"
    events = run_worker(monkeypatch, lab, criteria={"map": {"ports": 9}}, limit=10)
    [match] = matches_of(events)
    assert match["seed"] == "0000000009" and "start" not in match["map"] and match["stable"]
    assert not [e for e in events if e[0] in ("error", "fatal")]
    assert lab.map_calls[-2:] == [("spawn", False), ("reseed", False)]


# ---------------------------------------------------------------- the towns' trade data (trade routes)
@pytest.mark.core
def test_confirming_map_has_trade(monkeypatch):
    """The confirming map of a match (the one the player opens) carries the towns' trade data; a checked seed's too."""
    lab = FakeLab()
    [match] = matches_of(run_worker(monkeypatch, lab, criteria={"map": {"ports": 9}}, limit=10))
    assert match["map"]["trade"] == FakeLab.trade_data
    assert lab.trade_calls[-1] == ("spawn", True)
    lab = FakeLab()
    [match] = matches_of(run_worker(monkeypatch, lab, criteria={"map": {"ports": 1}}, seeds=["0000000004"]))
    assert match["map"]["trade"] == FakeLab.trade_data and lab.trade_calls == [("spawn", True)]


@pytest.mark.core
def test_deserters_shown_map_has_trade(monkeypatch):
    lab = DesertersLab()
    [match] = matches_of(run_worker(monkeypatch, lab, {"stars_by_slot": {"1": "hp1"}, "map": {"ports": 1}},
                                    seeds=["0000000003"], origin=DESERTERS))
    assert match["map"]["trade"] == FakeLab.trade_data
    lab = DesertersLab()
    matches = matches_of(run_worker(monkeypatch, lab, {"stars_by_slot": {"1": "hp1"}, "map": {"ports": 1}}, limit=10,
                                    origin=DESERTERS))
    assert matches and all(m["map"]["trade"] == FakeLab.trade_data for m in matches)
    sift = [call for call, (_stop, perks) in zip(lab.trade_calls, lab.map_calls) if not perks]
    assert sift and all(not trade for _stop, trade in sift), "the sift runs read no trade data"


@pytest.mark.dirty
def test_world_map_without_start_has_no_trade(monkeypatch):
    """The fallback map without a start (the spawn run failed) has no trade data: no routes, no error; the map says
    why (trade_error: checking the seed again gives the same map)."""
    lab = FakeLab()
    lab.spawn_error = "map of seed '9': the index 'x' does not exist"
    [match] = matches_of(run_worker(monkeypatch, lab, criteria={"map": {"ports": 9}}, limit=10))
    assert "trade" not in match["map"] and "start" not in match["map"] and match["stable"]
    assert "the index 'x' does not exist" in match["map"]["trade_error"]
    lab = FakeLab()
    lab.trade_data = None                    # the lab read nothing (no party, or the read failed)
    [match] = matches_of(run_worker(monkeypatch, lab, criteria={"map": {"ports": 9}}, limit=10))
    assert "trade" not in match["map"] and match["map"]["start"] == [12, 40]


@pytest.mark.core
def test_sift_maps_have_no_trade(monkeypatch):
    lab = FakeLab()
    run_worker(monkeypatch, lab, criteria={"map": {"ports": 9}}, limit=10)
    assert lab.trade_calls == [("reseed", False)] * 10 + [("spawn", True)]


def small_cli_map(**extra):
    """A map summary mapdraw can draw: 10 x 8 tiles of land and two towns."""
    towns = [{"name": "Hafen", "script": "legends_fishing_village", "size": 1, "x": 2, "y": 3, "southern": False,
              "military": False, "port": True, "faction": None},
             {"name": "Burg", "script": "legends_forest_fort", "size": 2, "x": 7, "y": 5, "southern": False,
              "military": True, "port": False, "faction": None}]
    return dict({"size": [10, 8], "layout": "even-q-up", "terrain": "L" * 80, "towns": towns, "attempts": 1}, **extra)


@pytest.mark.edge
def test_the_map_report_has_a_start_line_only_for_a_verified_setup():
    from bbseed.mapgen import FIRST_CAMPAIGN
    m = small_cli_map(start=[4, 6])
    verified = S.map_report("1234567890", m, "trader_scenario", "legends", 3.0, True, True)
    assert "   Start: 4, 6" in verified and verified.count("   " + FIRST_CAMPAIGN) == 1
    assert verified.index("   Start: 4, 6") < verified.index("   " + FIRST_CAMPAIGN)
    assert all(line.isascii() for line in verified)
    base = S.map_report("1234567890", m, "trader_scenario", "vanilla", 3.0, True, False)
    assert "   Start: 4, 6" in base and not any("first campaign" in line for line in base)
    for lines in (S.map_report("1", m), S.map_report("1", m, verified=False, legends=True),
                  S.map_report("1", small_cli_map(), verified=True, legends=True),
                  S.map_report("1", small_cli_map(start=None), verified=True, legends=True)):
        assert not any(line.strip().startswith("Start:") or "first campaign" in line for line in lines)


@pytest.mark.core
def test_cli_map_prints_the_start_and_draws_it_only_on_a_verified_setup(monkeypatch, capsys, tmp_path):
    import bbseed.lab as lab_module
    calls = []
    setup = {"verified": True}

    class FakeMapLab:
        profile = "legends"

        def __init__(self, profile, mod_settings=None):
            pass

        def info(self):
            return dict(VERIFIED_INFO, game_version="1.5.2.3" if setup["verified"] else "1.5.2.4")

    def fake_world_map(lab, seed, origin, **kwargs):
        calls.append(kwargs)
        return {"map": small_cli_map(start=[4, 6]), "seconds": 1.0}
    monkeypatch.setattr(lab_module, "Lab", FakeMapLab)
    monkeypatch.setattr(lab_module, "big_stack", lambda fn: fn())
    monkeypatch.setattr(S, "checked_world_map", fake_world_map)
    svg = tmp_path / "m.svg"
    S.main(["--map", "1234567890", "--svg", str(svg)])
    out = capsys.readouterr().out
    assert "   Start: 4, 6" in out and out.count("Start this seed as your first campaign") == 1 and NOTE not in out
    assert calls == [{"stop_at": "spawn", "blackmarket": 0}]
    assert 'class="start"' in svg.read_text(encoding="utf-8")
    setup["verified"] = False
    S.main(["--map", "1234567890", "--svg", str(svg)])
    out = capsys.readouterr().out
    assert "Start:" not in out and NOTE in out and 'class="start"' not in svg.read_text(encoding="utf-8")
    # a start that cannot be made: the map alone, as before
    setup["verified"] = True
    calls.clear()

    def no_start(lab, seed, origin, **kwargs):
        calls.append(kwargs)
        if kwargs.get("stop_at") == "spawn":
            raise LabError("no start")
        return {"map": small_cli_map(), "seconds": 1.0}
    monkeypatch.setattr(S, "checked_world_map", no_start)
    S.main(["--map", "1234567890"])
    out = capsys.readouterr().out
    assert "Start:" not in out and "map of seed 1234567890" in out and len(calls) == 2


# ====================================================================== the nearest seed
class NearLab(FakeLab):
    """Seed n: brother 1 has hp[n] HP stars (0 when n is not in the table)."""

    def __init__(self, hp=None, fresh_hp=None, **kw):
        super().__init__(**kw)
        self.hp, self.fresh_hp = hp or {}, fresh_hp or {}
        self.fresh_rolls = []

    def _roster_of(self, stars):
        return [bro(["brave"], hp=stars)] + [bro() for _ in range(ROSTER_SIZE - 1)]

    def _bros(self, seed):
        return self._roster_of(self.hp.get(int(seed), 0))

    def roster(self, seed, origin, fresh=True, probe=None):
        FakeLab.roster_calls += 1
        if fresh:
            self.fresh_rolls.append(seed)
            return self._roster_of(self.fresh_hp.get(int(seed), self.hp.get(int(seed), 0)))
        return self._bros(seed)


HP3 = {"stars_by_slot": {"1": {"hp": 3}}}


@pytest.fixture()
def quick_near(monkeypatch):
    """Every seed reports its progress at once, so the limits are reached where a test says."""
    monkeypatch.setattr(S, "PROGRESS_SECONDS", 0.0)
    monkeypatch.setattr(S, "NEAR_SEEDS", 10)
    monkeypatch.setattr(S, "NEAR_MAPS", 5)


def near_events(events):
    return [p for k, p in events if k == "near"]


def count_before_first_near(events):
    tested = 0
    for kind, payload in events:
        if kind == "near":
            return tested
        if kind == "progress":
            tested = payload[0]
    return None


@pytest.mark.core
def test_the_limits_are_as_the_plan_says():
    assert S.NEAR_SEEDS == 35000 and S.NEAR_MAPS == 100


@pytest.mark.core
def test_the_nearest_seed_shows_at_the_limit_and_not_before(monkeypatch, quick_near):
    found, events = run_search(monkeypatch, lambda: NearLab(hp={3: 2}), HP3, workers=1, max_seeds=40)
    assert found == []
    (near,) = near_events(events)
    assert near["seed"] == "0000000003" and near["distance"] == (0, 1, 0) and near["confirmed"] is True
    assert near["differences"] == [{"slot": 1, "kind": "stars", "name": "hp", "have": 2, "want": 3}]
    assert near["map"] is None and near["roster"][0]["stars"]["hp"] == 2
    assert count_before_first_near(events) >= 10


@pytest.mark.core
def test_a_nearer_seed_replaces_it(monkeypatch, quick_near):
    _found, events = run_search(monkeypatch, lambda: NearLab(hp={3: 1, 15: 2}), HP3, workers=1, max_seeds=40)
    assert [n["seed"] for n in near_events(events)] == ["0000000003", "0000000015"]


@pytest.mark.core
def test_an_equally_near_seed_does_not_replace_it(monkeypatch, quick_near):
    _found, events = run_search(monkeypatch, lambda: NearLab(hp={3: 2, 15: 2}), HP3, workers=1, max_seeds=40)
    assert [n["seed"] for n in near_events(events)] == ["0000000003"]


@pytest.mark.core
def test_stop_before_the_limit_with_no_match_shows_the_closest(monkeypatch):
    monkeypatch.setattr(S, "PROGRESS_SECONDS", 0.0)
    lab = NearLab(hp={3: 2})
    _found, events = run_search(monkeypatch, lambda: lab, HP3, workers=1, max_seeds=4000,
                                should_stop=lambda: FakeLab.roster_calls > 5)
    assert [k for k, _p in events][-2:] == ["near", "finished"], "shown, also with no progress event after it"
    assert near_events(events)[0]["seed"] == "0000000003"
    assert near_events(events)[0]["confirmed"] is False, "not rolled again before the limit: the card says so"
    assert events[-1][1][3] is True, "stopped"


@pytest.mark.core
def test_seeds_to_test_ending_early_shows_the_closest(monkeypatch):
    _found, events = run_search(monkeypatch, lambda: NearLab(hp={3: 2}), HP3, workers=2, max_seeds=6)
    (near,) = near_events(events)
    assert near["seed"] == "0000000003" and near["confirmed"] is True, "the end of a run rolls it again"
    assert [k for k, _p in events][-1] == "finished"


@pytest.mark.core
def test_an_exact_match_ends_the_near_reports(monkeypatch, quick_near):
    _found, events = run_search(monkeypatch, lambda: NearLab(hp={1: 1, 20: 3, 22: 2}), HP3, workers=1, max_seeds=40, count=5)
    kinds = [k for k, _p in events]
    assert kinds.index("near") < kinds.index("match")
    assert "near" not in kinds[kinds.index("match"):], "seed 22 is nearer than seed 1, and it is too late"
    assert len(near_events(events)) == 1


@pytest.mark.edge
def test_an_exact_match_before_the_limit_shows_no_near_seed(monkeypatch, quick_near):
    _found, events = run_search(monkeypatch, lambda: NearLab(hp={1: 2, 4: 3}), HP3, workers=1, max_seeds=40, count=5)
    assert near_events(events) == []


@pytest.mark.core
def test_a_map_per_seed_search_uses_100_maps(monkeypatch, quick_near):
    monkeypatch.setattr(S, "NEAR_SEEDS", 1)     # the seed limit must not count here
    _found, events = run_search(monkeypatch, FakeLab, {"map": {"ports": 11}}, workers=1, max_seeds=9)
    near = near_events(events)
    assert count_before_first_near(events) >= 5
    assert near[0]["confirmed"] is False and near[0]["roster"] is None
    assert near[-1]["seed"] == "0000000008" and near[-1]["distance"] == (0, 0, 3)
    assert near[-1]["differences"] == [{"slot": None, "kind": "map", "name": "ports", "have": 8, "want": 11}]
    assert near[-1]["map"]["towns"], "the map that was built comes along"


@pytest.mark.edge
def test_a_near_search_builds_no_extra_map(monkeypatch):
    # brother 1 passes on odd seeds; only those get a map, near or not, and no map is built again
    events = run_worker(monkeypatch, FakeLab(), {"stars_by_slot": {"1": {"hp": 1}}, "map": {"ports": 11}}, limit=30)
    near = [p for k, _i, p in events if k == "near"]
    assert near and near[-1]["seed"] == "0000000009" and near[-1]["distance"] == (0, 0, 2)
    assert FakeLab.world_map_calls == 15
    assert near[0]["seed"] == "0000000000" and near[0]["map"] is None, "a near roster has no map"
    assert near[1]["map"] is not None, "an exact roster has the map it was tested on"


@pytest.mark.edge
def test_no_conditions_reports_no_near_seed(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(), {}, limit=5)
    assert "near" not in [k for k, _i, _p in events]


@pytest.mark.edge
def test_a_checked_seed_is_no_near_seed(monkeypatch):
    events = run_worker(monkeypatch, NearLab(hp={1: 2}), HP3, seeds=["0000000001"])
    assert "near" not in [k for k, _i, _p in events] and len(matches_of(events)) == 1


@pytest.mark.core
def test_a_worker_sends_only_improvements_and_rolls_only_those_again(monkeypatch):
    monkeypatch.setattr(S, "NEAR_SEEDS", 0)     # past the limit from the first seed
    lab = NearLab(hp={3: 1, 5: 1, 7: 2})
    events = run_worker(monkeypatch, lab, HP3, limit=10)
    assert [p["seed"] for k, _i, p in events if k == "near"] == ["0000000000", "0000000003", "0000000007"]
    assert lab.fresh_rolls == ["0000000000", "0000000003", "0000000007"]


@pytest.mark.dirty
def test_a_near_seed_that_differs_on_a_fresh_roll_is_not_reported(monkeypatch):
    monkeypatch.setattr(S, "NEAR_SEEDS", 0)
    lab = NearLab(hp={3: 2, 8: 2}, fresh_hp={3: 0})
    events = run_worker(monkeypatch, lab, HP3, limit=10)
    assert [p["seed"] for k, _i, p in events if k == "near"] == ["0000000000", "0000000008"]


@pytest.mark.core
def test_a_near_seed_is_rolled_again_only_near_the_limit_or_at_the_end(monkeypatch):
    monkeypatch.setattr(S, "NEAR_SEEDS", 10)        # 9 seeds: NEAR_CONFIRM_SHARE of it
    lab = NearLab(hp={3: 1, 5: 2})
    events = run_worker(monkeypatch, lab, HP3, limit=8)
    near = [p for k, _i, p in events if k == "near"]
    assert [(n["seed"], n["confirmed"]) for n in near] == [
        ("0000000000", False), ("0000000003", False), ("0000000005", False), ("0000000005", True)]
    assert lab.fresh_rolls == ["0000000005"], "the end of the run: one roll, of the nearest"
    lab = NearLab(hp={3: 1, 11: 2})
    events = run_worker(monkeypatch, lab, HP3, limit=20)
    near = [p for k, _i, p in events if k == "near"]
    assert [(n["seed"], n["confirmed"]) for n in near] == [
        ("0000000000", False), ("0000000003", False), ("0000000003", True), ("0000000011", True)]
    assert lab.fresh_rolls == ["0000000003", "0000000011"]


@pytest.mark.dirty
def test_a_held_near_seed_that_differs_later_is_no_longer_the_workers_nearest(monkeypatch):
    monkeypatch.setattr(S, "NEAR_SEEDS", 5)         # 4.5 seeds: the roll comes after seed 4
    lab = NearLab(hp={2: 2, 7: 1}, fresh_hp={2: 0})
    events = run_worker(monkeypatch, lab, HP3, limit=10)
    near = [(p["seed"], p["confirmed"]) for k, _i, p in events if k == "near"]
    assert near == [("0000000000", False), ("0000000002", False), ("0000000005", True), ("0000000007", True)]


@pytest.mark.edge
def test_a_worker_with_an_exact_match_rolls_no_near_seed_again(monkeypatch):
    lab = NearLab(hp={2: 1, 4: 3})
    events = run_worker(monkeypatch, lab, HP3, limit=8)
    assert lab.fresh_rolls == []
    assert [p["seed"] for k, _i, p in events if k == "near"] == ["0000000000", "0000000002"]


HP2_PORTS11 = {"stars_by_slot": {"1": {"hp": 2}}, "map": {"ports": 11}}     # (FakeLab: no seed meets either)


@pytest.mark.core
def test_a_near_seed_of_a_map_search_gets_its_map_when_it_is_rolled_again(monkeypatch):
    monkeypatch.setattr(S, "NEAR_SEEDS", 0)     # past the limit from the first seed
    lab = FakeLab()
    events = run_worker(monkeypatch, lab, HP2_PORTS11, limit=10)
    near = [p for k, _i, p in events if k == "near"]
    assert [(n["seed"], n["distance"], n["confirmed"]) for n in near] == [
        ("0000000000", (0, 2, 11), True), ("0000000001", (0, 1, 10), True)]
    assert all(n["map"]["towns"] for n in near), "the map comes along"
    assert near[-1]["differences"][-1] == {"slot": None, "kind": "map", "name": "ports", "have": 1, "want": 11}
    assert FakeLab.world_map_calls == 2, "seed 3 and on are as near by their brothers: no map for them"


@pytest.mark.core
def test_before_the_limit_a_near_seed_of_a_map_search_has_no_map_and_no_map_distance(monkeypatch):
    lab = FakeLab()
    events = run_worker(monkeypatch, lab, HP2_PORTS11, limit=10)
    near = [p for k, _i, p in events if k == "near"]
    assert [(n["seed"], n["distance"], n["map"]) for n in near[:2]] == [
        ("0000000000", (0, 2, None), None), ("0000000001", (0, 1, None), None)]
    assert near[-1]["seed"] == "0000000001" and near[-1]["confirmed"] and near[-1]["distance"] == (0, 1, 10)
    assert FakeLab.world_map_calls == 1, "only the held seed gets a map, at the end of the run"


@pytest.mark.edge
def test_a_near_seed_whose_map_run_fails_stays_without_a_map(monkeypatch):
    monkeypatch.setattr(S, "NEAR_SEEDS", 0)
    events = run_worker(monkeypatch, FakeLab(map_errors=("0000000001",)), HP2_PORTS11, limit=4)
    near = [p for k, _i, p in events if k == "near"]
    assert near[-1]["seed"] == "0000000001" and near[-1]["map"] is None and near[-1]["distance"] == (0, 1, None)


@pytest.mark.core
def test_an_unknown_map_is_farther_than_any_built_map():
    assert S.near_key((0, 1, None)) > S.near_key((0, 1, 50))
    assert S.near_key((0, 0, None)) < S.near_key((0, 1, 0)), "nearer brothers win whatever the map is"
    assert S.near_key((1, 0, 3)) == (1, 0, 3)


@pytest.mark.core
def test_the_search_takes_its_own_near_limits(monkeypatch):
    monkeypatch.setattr(S, "PROGRESS_SECONDS", 0.0)
    _found, events = run_search(monkeypatch, lambda: NearLab(hp={3: 2}), HP3, workers=1, max_seeds=40, near_seeds=5)
    assert 5 <= count_before_first_near(events) < 40, "shown at 5 seeds, not at NEAR_SEEDS or the end"
    _found, events = run_search(monkeypatch, FakeLab, {"map": {"ports": 11}}, workers=1, max_seeds=9, near_maps=3)
    assert 3 <= count_before_first_near(events) < 5, "shown at 3 maps, not at NEAR_MAPS (100) or the end"


@pytest.mark.core
def test_the_command_line_takes_the_near_limits(monkeypatch):
    seen = {}
    monkeypatch.setattr(S, "search", lambda *a, **kw: seen.update(kw))
    S.main(["--profile", "legends", "--origin", "trader_scenario", "--stars", "1", "hp1", "--near-seeds", "7",
            "--near-maps", "2"])
    assert seen["near_seeds"] == 7 and seen["near_maps"] == 2


@pytest.mark.core
def test_the_checked_copy_of_a_near_seed_replaces_its_unchecked_copy(monkeypatch, quick_near):
    monkeypatch.setattr(S, "NEAR_CONFIRM_SHARE", 2.0)      # the roll comes after the limit, so the card shows both copies
    _found, events = run_search(monkeypatch, lambda: NearLab(hp={3: 2}), HP3, workers=1, max_seeds=30)
    assert [(n["seed"], n["confirmed"]) for n in near_events(events)] == [("0000000003", False), ("0000000003", True)]


@pytest.mark.core
def test_deserters_near_seeds_are_not_checked_yet_and_build_no_other_map(monkeypatch):
    class Lab(DesertersLab):
        def _bros(self, seed):
            return [bro(["brave"], hp=int(seed) % 3)] + [bro() for _ in range(ROSTER_SIZE - 1)]
    lab = Lab()
    monkeypatch.setattr(S, "_setup_note", lambda info, exact=False: None)
    events = run_worker(monkeypatch, lab, HP3, limit=6, origin=S.DESERTERS_SCRIPT)
    near = [p for k, _i, p in events if k == "near"]
    assert [n["seed"] for n in near] == ["0000000000", "0000000001", "0000000002"]
    assert all(n["confirmed"] is False and n["roster"] and n["map"] for n in near)
    assert FakeLab.world_map_calls == 6


@pytest.mark.core
def test_cli_near_prints_the_differences(monkeypatch, capsys):
    near = {"seed": "0000000003", "roster": [bro(hp=2)], "map": None, "distance": (0, 1, 0), "confirmed": True,
            "differences": [{"slot": 1, "kind": "stars", "name": "hp", "have": 2, "want": 3}]}
    argv = ["--profile", "legends", "--origin", "trader_scenario", "--stars", "1", "hp3"]
    without = run_cli_events(monkeypatch, capsys, [("near", near)], argv)
    assert "0000000003" not in without
    printed = run_cli_events(monkeypatch, capsys, [("near", near)], argv + ["--near"])
    assert "0000000003" in printed and "hp" in printed and "(0, 1, 0)" in printed
import random


# ====================================================================== early exit
class StopLab(FakeLab):
    """A roster of `size` brothers whose stars come from the seed (random.Random(seed)). It answers stop_after as Lab.roster
    does: after each brother but the last. asked: per seed the slots it asked about."""

    def __init__(self, size=4, changes_later=False, **kw):
        super().__init__(**kw)
        self.size, self.changes_later = size, changes_later
        self.asked, self.full_rolls, self.stopped_rolls = {}, 0, 0

    def _bros(self, seed):
        rng = random.Random(int(seed))
        return [bro(traits=["dumb"] if rng.random() < .1 else ["brave"], **{s: rng.randrange(4) for s in ("hp", "res", "msk")})
                for _ in range(self.size)]

    def roster(self, seed, origin, fresh=True, probe=None, stop_after=None, stop_slots=None):
        FakeLab.roster_calls += 1
        bros = self._bros(seed)
        asked = self.asked.setdefault(seed, [])
        for slot, one in enumerate(bros[:-1], 1):
            if stop_after is not None and (stop_slots is None or slot in stop_slots):
                asked.append(slot)
                seen = dict(one, stars=dict(one["stars"], hp=(one["stars"]["hp"] + 1) % 4)) if self.changes_later else one
                if stop_after(slot, seen):
                    self.stopped_rolls += 1
                    return None
        self.full_rolls += 1
        return bros


RARE = {"stars_by_slot": {"1": {"hp": 3, "res": 3}, "2": {"msk": 3}}, "banned": ["dumb"]}


def near_or_match(events):
    near = [p for k, _i, p in events if k == "near"]
    return [p["seed"] for p in matches_of(events)], (near[-1]["seed"], near[-1]["distance"]) if near else None


@pytest.mark.core
def test_prune_compares_the_first_two_parts():
    assert S.prune((0, 2), (0, 1, 0)) is True
    assert S.prune((0, 1), (0, 1, 0)) is True, "equal: an equally near seed does not replace the best one"
    assert S.prune((0, 0), (0, 0, 3)) is False, "the brothers so far are exact: it can match, or have a better map"
    assert S.prune((0, 0), (0, 0, 0)) is False, "and an exact match after an exact match is a match"
    assert S.prune((1, 0), (0, 9, 0)) is True
    assert S.prune((0, 1), (0, 0, 3)) is True
    assert S.prune((5, 5), None) is False


@pytest.mark.edge
def test_seeds_that_all_tie_stop_early_and_keep_the_first(monkeypatch):
    """A New Company's stars are fixed: every seed is equally far from a condition on them."""
    class Fixed(StopLab):
        def _bros(self, seed):
            return [bro(hp=1) for _ in range(self.size)]
    lab = Fixed()
    events = run_worker(monkeypatch, lab, {"stars_by_slot": {"1": {"hp": 3}}}, limit=50, final_from=1)
    assert [p["seed"] for k, _i, p in events if k == "near"][0] == "0000000000"
    assert {p["seed"] for k, _i, p in events if k == "near"} == {"0000000000"}
    assert lab.stopped_rolls > 40


@pytest.mark.core
def test_the_same_matches_with_and_without_early_exit(monkeypatch):
    plain = run_worker(monkeypatch, StopLab(), RARE, limit=600)
    lab = StopLab()
    early = run_worker(monkeypatch, lab, RARE, limit=600, final_from=1)
    assert matches_of(plain), "the sample has matches"
    assert [m["seed"] for m in matches_of(early)] == [m["seed"] for m in matches_of(plain)]
    assert lab.stopped_rolls > 300, "and most seeds stop early"


@pytest.mark.core
def test_the_same_nearest_seed_with_and_without_early_exit(monkeypatch):
    never = {"stars_by_slot": {"1": {"hp": 3, "res": 3, "msk": 3}, "2": {"hp": 3, "res": 3, "msk": 3},
                               "3": {"hp": 3, "res": 3, "msk": 3}}}
    plain = run_worker(monkeypatch, StopLab(), never, limit=800)
    lab = StopLab()
    early = run_worker(monkeypatch, lab, never, limit=800, final_from=1)
    assert near_or_match(plain) == near_or_match(early) and near_or_match(plain)[1] is not None
    assert lab.stopped_rolls > 200


@pytest.mark.core
def test_a_later_brothers_condition_stops_no_earlier_than_that_brother(monkeypatch):
    lab = StopLab()
    run_worker(monkeypatch, lab, {"stars_by_slot": {"3": {"hp": 3}}}, limit=50, final_from=1)
    assert {tuple(a) for a in lab.asked.values()} == {(3,)}, "only brother 3 is read"
    assert lab.stopped_rolls > 0


@pytest.mark.edge
def test_a_slot_before_final_from_is_never_asked(monkeypatch):
    lab = StopLab()
    run_worker(monkeypatch, lab, {"banned": ["dumb"]}, limit=50, final_from=3)
    assert all(slot >= 3 for asked in lab.asked.values() for slot in asked)
    lab = StopLab()
    run_worker(monkeypatch, lab, {"stars_by_slot": {"1": {"hp": 3}}}, limit=50, final_from=3)
    assert lab.stopped_rolls == 0 and not any(lab.asked.values()), "its only condition is on a slot that is not final"


@pytest.mark.edge
def test_any_brother_conditions_never_stop_early(monkeypatch):
    lab = StopLab()
    criteria = {"stars_by_slot": {"1": {"hp": 3}}, "backgrounds_by_slot": {"any": ["background.monk"]}}

    class WithBackground(StopLab):
        def _bros(self, seed):
            return [dict(b, background="background.monk") for b in StopLab._bros(self, seed)]
    lab = WithBackground()
    run_worker(monkeypatch, lab, criteria, limit=30, final_from=1)
    assert lab.stopped_rolls == 0 and not any(lab.asked.values())


@pytest.mark.edge
def test_a_map_per_seed_search_never_stops_early(monkeypatch):
    lab = StopLab()
    run_worker(monkeypatch, lab, {"map": {"ports": 11}}, limit=5, final_from=1)
    assert lab.stopped_rolls == 0 and not any(lab.asked.values())


@pytest.mark.edge
def test_no_final_from_never_stops_early(monkeypatch):
    lab = StopLab()
    run_worker(monkeypatch, lab, RARE, limit=30)
    assert lab.stopped_rolls == 0 and not any(lab.asked.values())
    assert S._final_from("no such profile", "trader_scenario") is None


@pytest.mark.core
def test_the_catalog_answer_is_used_only_for_an_origin_it_holds(monkeypatch):
    from bbseed import catalog
    monkeypatch.setattr(catalog, "load", lambda profile=None, mod_settings=None: {"talents": {
        "trader_scenario": {"final_from": 1}, "old_scenario": {"samples": 12}}})
    assert S._final_from("legends", "trader_scenario") == 1
    assert S._final_from("legends", "old_scenario") is None
    assert S._final_from("legends", "a_mod_scenario") is None
    monkeypatch.setattr(catalog, "load", lambda profile=None, mod_settings=None: None)
    assert S._final_from("legends", "trader_scenario") is None


@pytest.mark.core
def test_the_odds_stay_within_ten_percent(monkeypatch):
    criteria = {"stars_by_slot": {"1": {"hp": 2}, "2": {"res": 2}, "3": {"msk": 1}}}
    plain = odds_of(run_worker(monkeypatch, StopLab(), criteria, limit=3000))
    lab = StopLab()
    early = odds_of(run_worker(monkeypatch, lab, criteria, limit=3000, final_from=1))
    assert lab.stopped_rolls > 500
    assert early.tested == plain.tested == 3000
    assert early.chance() == pytest.approx(plain.chance(), rel=0.10)
    assert early.never() == []
    assert early.slot_tested[0] == 3000 and early.slot_tested[2] < 3000


@pytest.mark.edge
def test_a_slot_no_seed_reached_is_not_a_slot_that_never_passed():
    odds = Odds()
    odds.add([False])
    assert odds.never() == [1]
    odds = Odds()
    odds.add([True, None, False])
    odds.add([True])
    assert odds.never() == [3] and odds.slot_tested == [2, 0, 1]
    assert odds.brothers_chance() == 0.0
    other = Odds()
    other.merge(*odds.take())
    assert other.tested == 2 and other.slot_tested == [2, 0, 1]
    old = Odds()
    old.merge(10, [5, 10])       # a count from before the per-slot counts: every slot saw every seed
    assert old.brothers_chance() == 0.5


@pytest.mark.dirty
def test_a_wrong_stop_turns_early_exit_off_and_says_so(monkeypatch):
    monkeypatch.setattr(S, "EARLY_AUDIT_SEEDS", 10)
    lab = StopLab(changes_later=True)
    events = run_worker(monkeypatch, lab, {"stars_by_slot": {"1": {"hp": 3}}}, limit=30, final_from=1)
    notices = [p for k, _i, p in events if k == "notice"]
    assert notices == [S.EARLY_EXIT_OFF], "one notice: the first roster shows it"
    assert lab.stopped_rolls == 0 and lab.full_rolls == 30
    assert all(not a for seed, a in lab.asked.items() if int(seed) > 0), "and no brother is read after that"
    expected = [str(n).zfill(10) for n in range(30) if lab._bros(str(n))[0]["stars"]["hp"] >= 3]
    assert [m["seed"] for m in matches_of(events)] == expected


@pytest.mark.core
def test_search_passes_one_notice_on(monkeypatch):
    monkeypatch.setattr(S, "EARLY_AUDIT_SEEDS", 10)
    monkeypatch.setattr(S, "_final_from", lambda profile, origin: 1)
    _found, events = run_search(monkeypatch, lambda: StopLab(changes_later=True), {"stars_by_slot": {"1": {"hp": 3}}},
                                workers=2, max_seeds=6, count=99)
    assert [p for k, p in events if k == "notice"] == [S.EARLY_EXIT_OFF]


@pytest.mark.edge
def test_a_checked_seed_is_rolled_in_full(monkeypatch):
    lab = StopLab()
    events = run_worker(monkeypatch, lab, RARE, seeds=["0000000005"], final_from=1)
    assert len(matches_of(events)) == 1 and lab.stopped_rolls == 0 and not any(lab.asked.values())
import time


# ====================================================================== the final review's findings
@pytest.mark.dirty
def test_a_worker_that_dies_without_a_word_is_a_fatal_and_the_search_ends(monkeypatch):
    """A worker's import can fail (a damaged PyPy add-on), or the process can die hard. search() waited for it forever."""
    real = S._worker

    def dies_or_works(index, *args):
        if index == 0:
            return
        real(index, *args)
    monkeypatch.setattr(S, "_worker", dies_or_works)
    began = time.time()
    _found, events = run_search(monkeypatch, FakeLab, {"stars_by_slot": {"1": {"hp": 1}}}, workers=2, max_seeds=4, count=99)
    assert time.time() - began < 20
    kinds = [k for k, _p in events]
    assert kinds.count("fatal") == 1 and kinds[-1] == "finished"
    assert S.WORKER_DIED.split("%")[0] in [p for k, p in events if k == "fatal"][0]
    assert events[-1][1][0] == 2, "the other worker tested its seeds"


@pytest.mark.dirty
def test_all_workers_dying_before_they_are_ready_ends_the_search(monkeypatch):
    monkeypatch.setattr(S, "_worker", lambda *args: None)
    began = time.time()
    _found, events = run_search(monkeypatch, FakeLab, {"stars_by_slot": {"1": {"hp": 1}}}, workers=2, max_seeds=4)
    assert time.time() - began < 20
    assert [k for k, _p in events].count("fatal") == 2 and events[-1][0] == "finished"


@pytest.mark.core
def test_a_brother_few_seeds_reached_is_not_named_as_one_that_never_matches():
    odds = Odds()
    for _ in range(280):
        odds.add([False])                   # brother 1 stops most seeds
    for _ in range(20):
        odds.add([True, False])             # brother 2: 20 seeds, no pass yet
    assert odds.never() == [2], "without a limit: every slot with no pass"
    assert odds.never(least=300) == []
    assert odds.never(least=100) == []
    for _ in range(300):
        odds.add([True, False])
    assert odds.never(least=300) == [2], "320 seeds reached him"


@pytest.mark.core
def test_the_never_notice_counts_the_seeds_that_reached_the_brother(monkeypatch):
    monkeypatch.setattr(S, "PROGRESS_SECONDS", 0.0)
    monkeypatch.setattr(S, "NEVER_SLOT_SEEDS", 20)

    class NoStarsLater(StopLab):
        def _bros(self, seed):
            n = int(seed)
            first = bro(hp=3 if n % 4 == 0 else 0)
            return [first] + [bro() for _ in range(self.size - 1)]
    monkeypatch.setattr(S, "_final_from", lambda profile, origin: 1)
    criteria = {"stars_by_slot": {"1": {"hp": 3}, "2": {"msk": 3}}}
    _found, events = run_search(monkeypatch, NoStarsLater, criteria, workers=1, max_seeds=200)
    last = [p[3] for k, p in events if k == "progress"][-1]
    assert last["tested"] == 200 and last["never"] == [2]
    assert 20 <= last["never_tested"] < 200, "the count of the brother, not of the search"


@pytest.mark.dirty
def test_a_near_seed_that_fails_its_roll_stops_being_the_best(monkeypatch):
    monkeypatch.setattr(S, "NEAR_SEEDS", 5)         # the held seed is rolled after seed 4
    _found, events = run_search(monkeypatch, lambda: NearLab(hp={2: 2, 7: 1}, fresh_hp={2: 0}), HP3, workers=1, max_seeds=10)
    near = near_events(events)
    assert near[-1]["seed"] == "0000000007" and near[-1]["confirmed"] is True, "seed 7 is farther than the false seed 2"
    assert near[-1]["distance"] == (0, 2, 0)

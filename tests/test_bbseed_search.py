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


def test_parse_stars():
    assert parse_stars("msk2 mdf1") == {"msk": 2, "mdf": 1}
    assert parse_stars("") == {}
    for bad in ("msk", "xyz2", "msk4", "2msk"):
        with pytest.raises(ValueError):
            parse_stars(bad)


def test_normalize_accepts_bb_reroll_config():
    c = normalize({"stars_by_slot": {"*": {}, "1": {"res": 3}, "2": "msk2"}, "banned": ["trait.dumb", "fat"],
                   "required": ["brave"], "required_mode": "any"})
    assert c["stars_by_slot"] == {"1": {"res": 3}, "2": {"msk": 2}}
    assert c["banned"] == ["dumb", "fat"] and c["required"] == ["brave"] and c["required_slots"] is None


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


def test_banned_applies_to_every_recruit():
    c = normalize({"banned": ["dumb"]})
    assert first_failure([bro(["brave"]), bro([])], c) is None
    assert first_failure([bro(["brave"]), bro(["dumb"])], c) == "bro2 banned dumb"


def test_required_any_all_and_slots():
    any_ = normalize({"required": ["brave", "tough"]})
    assert first_failure([bro(["brave"]), bro(["tough", "fat"])], any_) is None
    assert first_failure([bro(["brave"]), bro(["fat"])], any_) == "bro2 no_good_trait"
    all_ = normalize({"required": ["brave", "tough"], "required_mode": "all"})
    assert first_failure([bro(["brave", "tough"])], all_) is None
    assert first_failure([bro(["brave"])], all_) == "bro1 missing tough"
    first_only = normalize({"required": ["brave"], "required_slots": [1]})
    assert first_failure([bro(["brave"]), bro([])], first_only) is None


def test_slot_beyond_roster_fails():
    c = normalize({"stars_by_slot": {"4": "hp1"}})
    assert first_failure([bro(hp=3)], c) == "no bro4 in this origin's roster"


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


def test_seeds_are_ten_digits():
    assert seed_text(42) == "0000000042"
    assert seed_text(10 ** 10 + 7) == "0000000007"


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
def test_normalize_keeps_map_conditions():
    c = normalize({"map": {"ports": 6, "north_band": 33, "towns": {"city_state": 2}}})
    assert c["map"] == {"ports": 6, "ports_south": 0, "ports_north": 0, "north_band": 33, "towns": {"city_state": 2}}
    assert normalize(c) == c                                  # search() normalizes what the CLI normalized


def test_normalize_without_map_conditions():
    assert normalize({})["map"] is None
    # 0 is no condition, and a band alone is none either
    assert normalize({"map": {"ports": 0, "north_band": 50, "towns": {"size1": 0}}})["map"] is None
    assert normalize({"map": None})["map"] is None


def test_normalize_fills_in_the_north_band():
    assert normalize({"map": {"ports_north": 1}})["map"] == {
        "ports": 0, "ports_south": 0, "ports_north": 1, "north_band": 33, "towns": {}}
    assert normalize({"map": {"ports_north": 2, "north_band": 20}})["map"]["north_band"] == 20
    assert normalize({"map": {"towns": {"size3": "4"}}})["map"]["towns"] == {"size3": 4}


def test_normalize_rejects_a_bad_north_band_only_for_northern_ports():
    """Carried from Task 8's review: the band matters only for northern ports, so only then is it checked."""
    for band in (0, 100, -3, 150, "far"):
        with pytest.raises(ValueError, match="north band"):
            normalize({"map": {"ports_north": 1, "north_band": band}})
    # without a northern-port condition a bad band is ignored (the default is kept), a good one kept
    assert normalize({"map": {"ports": 2, "north_band": 0}})["map"]["north_band"] == 33
    assert normalize({"map": {"ports": 2, "north_band": 150}})["map"]["north_band"] == 33
    assert normalize({"map": {"ports": 2, "north_band": 50}})["map"]["north_band"] == 50


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

    def info(self):
        return {"profile": "fake"}

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

    def world_map(self, seed, origin="trader_scenario", stop_at="reseed", layout=None, blackmarket=0):
        FakeLab.world_map_calls += 1
        self.blackmarket.append(blackmarket)
        if self.map_crash is not None:
            raise self.map_crash
        if self.map_errors is True or seed in self.map_errors:
            raise LabError("map of seed %r: the index '0' does not exist" % seed)
        self.builds[seed] = self.builds.get(seed, 0) + 1
        summary = fake_map(int(seed) % 10)
        if self.builds[seed] == 1 and self.first_map is not None:
            summary = self.first_map(summary)
        if self.builds[seed] == 2 and self.second_map is not None:
            summary = self.second_map(summary)
        stubs = self.stubs(seed) if callable(self.stubs) else self.stubs.get(seed, {})
        return {"map": summary, "seconds": 0.0, "log": [], "stub_uses": stubs}


class ListQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


def run_worker(monkeypatch, lab, criteria, seeds=None, limit=30):
    """One search worker (index 0 of 1, seeds 0, 1, ... limit - 1) on the stand-in lab: its events."""
    monkeypatch.setattr(S, "_make_lab", lambda profile, mod_settings: lab)
    out = ListQueue()
    S._worker(0, 1, "legends", None, "trader_scenario", normalize(criteria), 0, limit, seeds, out)
    return out.items


def matches_of(events):
    return [payload for kind, _index, payload in events if kind == "match"]


def odds_of(events, map_wanted=False):
    total = Odds(map_wanted=map_wanted)
    for kind, _index, payload in events:
        if kind == "progress":
            total.merge(*payload[1])
    return total


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


def test_every_map_is_built_as_a_first_campaign(monkeypatch):
    """Ruling AD: the search passes blackmarket=0 (Legends' never-reset counter as in the first campaign after the
    game starts), so the sift map and the confirming map of a match are built alike."""
    lab = FakeLab()
    run_worker(monkeypatch, lab, criteria={"map": {"ports": 9}}, limit=10)
    assert lab.blackmarket == [0] * 11


def test_roster_conditions_only_build_no_map(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(), criteria={"stars_by_slot": {"1": "hp1"}}, limit=30)
    matches = matches_of(events)
    assert [m["seed"] for m in matches] == [seed_text(n) for n in range(1, 30, 2)]
    assert FakeLab.world_map_calls == 0
    assert all(m["map"] is None for m in matches)
    assert odds_of(events).map is None


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


def test_a_map_error_on_one_seed_does_not_stop_the_search(monkeypatch):
    """3 of 1,000 surveyed seeds raise in Legends' guaranteeAllBuildingsInSettlements: such a seed is an error event
    and the worker goes on - also when it is the worker's first seed."""
    for bad in ("0000000005", "0000000000"):
        events = run_worker(monkeypatch, FakeLab(map_errors={bad}), criteria={"map": {"ports": 9}}, limit=30)
        errors = [p for kind, _i, p in events if kind == "error"]
        assert len(errors) == 1 and bad in errors[0]
        assert [m["seed"] for m in matches_of(events)] == ["0000000009", "0000000019", "0000000029"]
        assert events[-1][0] == "done" and not [e for e in events if e[0] == "fatal"]


def test_a_map_generator_that_never_works_is_one_fatal_event(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(map_errors=True), criteria={"map": {"ports": 1}}, limit=30)
    kinds = [kind for kind, _i, _p in events]
    assert kinds.count("fatal") == 1 and "done" not in kinds and "error" not in kinds
    fatal = [p for kind, _i, p in events if kind == "fatal"][0]
    assert fatal.startswith("Map conditions do not work with this game setup: ") and "0000000000" in fatal
    assert FakeLab.world_map_calls == 2        # the first failure could be the seed's own: one more seed is tried


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


def test_maps_that_always_use_engine_functions_nobody_reviewed_end_the_search_with_a_map_fatal(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(stubs=lambda seed: UNREVIEWED), criteria={"map": {"ports": 1}}, limit=30)
    kinds = [kind for kind, _i, _p in events]
    assert kinds.count("fatal") == 1 and "done" not in kinds and "error" not in kinds
    fatal = [p for kind, _i, p in events if kind == "fatal"][0]
    assert fatal.startswith(S.MAP_FATAL) and "World.spawnEntity" in fatal and "0000000000" in fatal
    assert FakeLab.world_map_calls == 2


def test_the_confirming_map_is_checked_too(monkeypatch):
    """A match is confirmed with a second map; when that one used unreviewed functions the seed is skipped."""
    class SecondUnreviewed(FakeLab):
        def world_map(self, seed, *args, **kwargs):
            out = FakeLab.world_map(self, seed, *args, **kwargs)
            if self.builds[seed] == 2:
                out["stub_uses"] = UNREVIEWED
            return out
    events = run_worker(monkeypatch, SecondUnreviewed(), criteria={"map": {"ports": 9}}, limit=10)
    assert matches_of(events) == []
    errors = [p for kind, _i, p in events if kind == "error"]
    assert len(errors) == 1 and "0000000009" in errors[0] and "World.spawnEntity" in errors[0]


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


def test_a_search_that_is_not_checking_does_not_report_a_seed_without_a_map(monkeypatch):
    for criteria in ({"map": {"ports": 9}}, {"stars_by_slot": {"1": "hp1"}, "map": {"ports": 9}}):
        events = run_worker(monkeypatch, FakeLab(map_errors={"0000000009"}), criteria=criteria, limit=10)
        assert "0000000009" not in [m["seed"] for m in matches_of(events)]


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


def test_an_unexpected_roster_exception_is_a_fatal_event(monkeypatch, capsys):
    """Fix round 1, the roster path (the same gap from before Task 9): one fatal event with the exception's type and
    text and the seed, instead of a worker that dies silently."""
    events = run_worker(monkeypatch, FakeLab(roster_crash=KeyError("talents")), criteria={"stars_by_slot": {"1": "hp1"}},
                        limit=30)
    assert [kind for kind, _i, _p in events] == ["ready", "fatal"]
    assert events[1][2] == "KeyError: 'talents' (seed 0000000000)"
    assert "Traceback" in capsys.readouterr().err          # the worker's console gets the whole traceback


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


def test_the_stable_flag_covers_the_map(monkeypatch):
    """The confirming map must have the sift map's towns and ports; when it has not, the match is not stable."""
    events = run_worker(monkeypatch, FakeLab(second_map=lambda m: fake_map(9, shift=1)),
                        criteria={"map": {"ports": 9}}, limit=10)
    [match] = matches_of(events)
    assert match["seed"] == "0000000009" and match["failure"] is None and not match["stable"]
    assert match["map"]["towns"][0]["x"] == 1                 # the payload has the confirming map


def test_a_map_that_fails_when_built_again_is_skipped(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(second_map=lambda m: fake_map(2)), criteria={"map": {"ports": 9}},
                        limit=10)
    assert matches_of(events) == []
    errors = [p for kind, _i, p in events if kind == "error"]
    assert len(errors) == 1 and "0000000009" in errors[0]


def test_checking_seeds_with_map_conditions_reports_every_seed(monkeypatch):
    events = run_worker(monkeypatch, FakeLab(), criteria={"map": {"ports": 9}}, seeds=["0000000003", "0000000009"])
    got = {m["seed"]: m for m in matches_of(events)}
    assert got["0000000003"]["failure"] == "Ports: 3, needs 9" and got["0000000009"]["failure"] is None
    assert all(m["map"] and m["roster"] and m["stable"] for m in got.values())
    assert FakeLab.world_map_calls == 4 and FakeLab.roster_calls == 4
    # with a roster condition too, a checked seed whose roster fails still gets its map
    events = run_worker(monkeypatch, FakeLab(), criteria={"stars_by_slot": {"1": "hp1"}, "map": {"ports": 9}},
                        seeds=["0000000002"])
    [m] = matches_of(events)
    assert m["failure"] == "bro1 hp*0<1" and m["map"]["towns"]


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


def run_search(monkeypatch, lab_factory, criteria, **kwargs):
    import bbseed.profiles
    monkeypatch.setattr(bbseed.profiles, "get", lambda *args, **kw: None)
    monkeypatch.setattr(S, "mp", SimpleNamespace(get_context=lambda kind: ThreadContext))
    monkeypatch.setattr(S, "_make_lab", lambda profile, mod_settings: lab_factory())
    events = []
    found = S.search("legends", "trader_scenario", criteria, start=0, on_event=lambda k, p: events.append((k, p)),
                     **kwargs)
    return found, events


def test_search_reports_the_map_of_a_match(monkeypatch):
    found, events = run_search(monkeypatch, FakeLab, {"map": {"ports": 9}}, workers=2, max_seeds=20, count=2)
    assert sorted(m["seed"] for m in found) == ["0000000009", "0000000019"]
    assert all(m["map"]["towns"] and m["roster"] for m in found)
    progress = [p for k, p in events if k == "progress"]
    odds = progress[-1][3]
    assert set(odds) >= {"chance", "chance_brothers", "never", "never_any", "never_map", "maps", "tested"}
    assert odds["maps"] >= 10 and odds["never_map"] is False
    assert events[-1][0] == "finished"


def test_search_ends_at_the_first_map_fatal(monkeypatch):
    """A game setup whose map generator does not work: every worker finds it, the player gets ONE fatal event."""
    found, events = run_search(monkeypatch, lambda: FakeLab(map_errors=True), {"map": {"ports": 1}}, workers=3,
                               max_seeds=30, count=1)
    assert found == []
    fatal = [p for k, p in events if k == "fatal"]
    assert len(fatal) == 1 and fatal[0].startswith("Map conditions do not work with this game setup: ")
    assert events[-1][0] == "finished"


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
                 "mods": [{"file": "mod_legends-19.4.22.zip", "id": "mod_legends"},
                          {"file": "mod_legends-assets-19.4.3.zip", "id": "mod_legends_assets"},
                          {"file": "mod_modern_hooks-685-0-6-0-1748620177.zip", "id": "mod_modern_hooks"},
                          {"file": "mod_msu 479 1.9.0 2026-06-23T04-27Z eVJjKbX9c.zip", "id": "mod_msu"}]}
NOTE = "Map results are not verified for this setup."


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

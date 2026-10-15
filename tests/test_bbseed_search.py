"""Criteria handling of the offline searcher (no game data needed)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbseed.search import first_failure, normalize, parse_stars, seed_text

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

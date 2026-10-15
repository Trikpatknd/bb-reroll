"""The GUI's view of what stars an origin can have (bbreroll/star_limits.py). The facts below are
what the catalog found for Legends 19.4.22 (bbseed/talents.py)."""
from bbreroll import star_limits as L

ALL3 = {s: 3 for s in ("hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf")}


def slot(most, picks, fixed=None, never=()):
    top = dict(ALL3)
    for s in never:
        top[s] = 0
    return {"most": most, "least": most, "picks": picks, "max": top, "fixed": fixed or {},
            "rolled": [s for s in top if top[s] and s not in (fixed or {})]}


BERSERKER = [slot(4, 2, {"hp": 3, "msk": 3})]
BEGGAR = [slot(3, 3, never=("hp", "res"))]
INQUISITION = [slot(3, 0, {"hp": 3, "res": 3, "msk": 2}, never=("fat", "init", "rsk", "mdf", "rdf")),
               slot(3, 1, {"res": 3, "rsk": 3})]
INQUISITION[0]["max"].update({"hp": 3, "res": 3, "msk": 2})


def test_four_starred_stats_are_impossible_for_the_scaling_beggar():
    out = L.problems(BEGGAR, {"*": {"msk": 1, "mdf": 1, "fat": 1, "rsk": 1}})
    assert out == ["Brother 1 can have stars in a maximum of 3 stats. Your conditions use 4 stats."]


def test_a_stat_the_slot_never_gets():
    assert L.problems(BEGGAR, {"1": {"hp": 1}}) == ["Brother 1 never gets HP stars. Your condition is 1."]


def test_a_fixed_stat_cannot_be_raised():
    out = L.problems(INQUISITION, {"1": {"msk": 3}})
    assert out == ["Brother 1 always has 2 MSK stars. Your condition is 3."]


def test_the_roll_cannot_star_more_than_its_picks_besides_the_fixed_stars():
    # four stats is not too many for the berserker, but three of them would have to be rolled
    out = L.problems(BERSERKER, {"1": {"hp": 3, "fat": 1, "res": 1, "init": 1}})
    assert out == ["Brother 1 gets random stars in only 2 stats in addition to the fixed HP 3, MSK 3. "
                   "Your conditions need 3 (FAT, RES, INIT)."]
    out = L.problems(BERSERKER, {"1": {"fat": 1, "res": 1, "init": 1}})
    assert out == ["Brother 1 gets random stars in only 2 stats in addition to the fixed HP 3, MSK 3. "
                   "Your conditions need 3 (FAT, RES, INIT)."]


def test_possible_criteria_have_no_problems():
    assert L.problems(BERSERKER, {"*": {"hp": 3, "msk": 3, "fat": 3, "rdf": 3}}) == []
    assert L.problems(INQUISITION, {"*": {"res": 3}}) == []
    assert L.problems(BEGGAR, {"*": {}, "1": {}}) == []


def test_a_slot_row_replaces_the_star_row():
    # "*" asks for HP, which the beggar never gets — but slot 1 has its own row
    assert L.problems(BEGGAR, {"*": {"hp": 1}, "1": {"msk": 2}}) == []


def test_random_stars_per_brother():
    assert L.random_stars(BERSERKER) == [2]
    assert L.random_stars(INQUISITION) == [0, 1]
    assert L.random_stars([dict(slot(4, 3), varied=True)]) == [None]
    assert L.random_stars(None) == []


def test_fixed_stars_are_locked_cells_but_not_on_varied_slots():
    assert L.locked_cells(INQUISITION) == {("1", "hp"): 3, ("1", "res"): 3, ("1", "msk"): 2,
                                           ("2", "res"): 3, ("2", "rsk"): 3}
    assert L.locked_cells(BEGGAR) == {}
    assert L.locked_cells([dict(slot(3, 2, {"hp": 1}), varied=True)]) == {}


def test_prefill_and_cell_limits():
    assert L.prefill(INQUISITION) == {"1": {"hp": 3, "res": 3, "msk": 2}, "2": {"res": 3, "rsk": 3}}
    assert L.cell_max(BEGGAR, "1", "hp") == 0 and L.cell_max(BEGGAR, "1", "msk") == 3
    assert L.cell_max(BEGGAR, "*", "hp") == 3
    assert L.cell_max(BEGGAR, "2", "hp") == 3          # a slot the facts do not cover
    assert L.cell_max(INQUISITION, "1", "msk") == 2


def test_describe_groups_brothers_with_the_same_facts():
    militia = [slot(3, 3)] * 12
    assert L.describe(militia) == "Brothers 1-12: 3 random stars"
    assert L.describe(BERSERKER) == "Brother 1: fixed stars HP 3, MSK 3, and 2 random stars"
    assert L.describe(BEGGAR) == "Brother 1: 3 random stars. Never on HP, RES"
    assert L.describe(INQUISITION, sizes=[3]) == ("Brother 1: fixed stars HP 3, RES 3, MSK 2\n"
                                                  "Brother 2: fixed stars RES 3, RSK 3, and 1 random star")
    assert L.describe(BEGGAR, sizes=[4, 5]).startswith("The number of brothers changes with the seed: 4, 5.")


def test_a_brother_whose_background_varies_is_never_ruled_out():
    party = [dict(slot(4, 3, never=("hp",)), varied=True)]
    assert L.problems(party, {"1": {"hp": 3, "fat": 1, "res": 1, "init": 1, "msk": 1}}) == []
    assert L.cell_max(party, "1", "hp") == 3
    assert L.describe(party) == ("Brother 1: the background changes with the seed "
                                 "(seen: stars in a maximum of 4 stats)")


def test_roll_cells_offer_only_what_the_seed_can_move():
    slots = [dict(slot(3, 3), spread=["hp", "fat", "msk"])]
    assert L.roll_options(slots, "1", "msk") == ["any", "mid", "high"]
    assert L.roll_options(slots, "1", "res") == ["any"]
    assert L.roll_options(slots, "*", "res") == ["any", "mid", "high"]
    assert L.roll_options([slot(3, 3)], "1", "res") == ["any", "mid", "high"]      # an older catalog: no data
    assert L.roll_problems(slots, {"*": {"res": "high", "msk": "mid"}}) == [
        "The seed cannot change RES of brother 1. This stat has the same value at all times."]
    assert L.roll_problems(slots, {"1": {"msk": "high"}}) == []


def test_catalog_lookup():
    catalog = {"talents": {"a_scenario": {"slots": BEGGAR, "sizes": [1]}, "b_scenario": {"error": "boom"}}}
    assert L.slots_for(catalog, "a_scenario") == BEGGAR
    assert L.slots_for(catalog, "b_scenario") is None
    assert L.slots_for(None, "a_scenario") is None
    assert L.sizes_for(catalog, "a_scenario") == [1]

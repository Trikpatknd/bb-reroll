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
    assert out == ["Brother 1 can have stars in at most 3 stats — you ask for 4."]


def test_a_stat_the_slot_never_gets():
    assert L.problems(BEGGAR, {"1": {"hp": 1}}) == ["Brother 1 never gets HP stars — you ask for 1."]


def test_a_fixed_stat_cannot_be_raised():
    out = L.problems(INQUISITION, {"1": {"msk": 3}})
    assert out == ["Brother 1 has MSK fixed at 2 — you ask for 3."]


def test_the_roll_cannot_star_more_than_its_picks_besides_the_fixed_stars():
    # four stats is not too many for the berserker, but three of them would have to be rolled
    out = L.problems(BERSERKER, {"1": {"hp": 3, "fat": 1, "res": 1, "init": 1}})
    assert out == ["Brother 1: the roll stars only 2 stats besides the fixed HP 3, MSK 3 — you ask for 3 "
                   "(FAT, RES, INIT)."]
    out = L.problems(BERSERKER, {"1": {"fat": 1, "res": 1, "init": 1}})
    assert out == ["Brother 1: the roll stars only 2 stats besides the fixed HP 3, MSK 3 — you ask for 3 "
                   "(FAT, RES, INIT)."]


def test_possible_criteria_have_no_problems():
    assert L.problems(BERSERKER, {"*": {"hp": 3, "msk": 3, "fat": 3, "rdf": 3}}) == []
    assert L.problems(INQUISITION, {"*": {"res": 3}}) == []
    assert L.problems(BEGGAR, {"*": {}, "1": {}}) == []


def test_a_slot_row_replaces_the_star_row():
    # "*" asks for HP, which the beggar never gets — but slot 1 has its own row
    assert L.problems(BEGGAR, {"*": {"hp": 1}, "1": {"msk": 2}}) == []


def test_prefill_and_cell_limits():
    assert L.prefill(INQUISITION) == {"1": {"hp": 3, "res": 3, "msk": 2}, "2": {"res": 3, "rsk": 3}}
    assert L.cell_max(BEGGAR, "1", "hp") == 0 and L.cell_max(BEGGAR, "1", "msk") == 3
    assert L.cell_max(BEGGAR, "*", "hp") == 3
    assert L.cell_max(BEGGAR, "2", "hp") == 3          # a slot the facts do not cover
    assert L.cell_max(INQUISITION, "1", "msk") == 2


def test_describe_groups_brothers_with_the_same_facts():
    militia = [slot(3, 3)] * 12
    assert L.describe(militia) == "Brothers 1–12: 3 rolled"
    assert L.describe(BERSERKER) == "Brother 1: fixed HP 3  MSK 3 + 2 rolled"
    assert L.describe(BEGGAR) == "Brother 1: 3 rolled  · never HP RES"
    assert L.describe(INQUISITION, sizes=[3]) == ("Brother 1: fixed HP 3  RES 3  MSK 2\n"
                                                  "Brother 2: fixed RES 3  RSK 3 + 1 rolled")


def test_a_brother_whose_background_varies_is_never_ruled_out():
    party = [dict(slot(4, 3, never=("hp",)), varied=True)]
    assert L.problems(party, {"1": {"hp": 3, "fat": 1, "res": 1, "init": 1, "msk": 1}}) == []
    assert L.cell_max(party, "1", "hp") == 3
    assert L.describe(party) == "Brother 1: background varies by seed — stars in up to 4 stats seen"


def test_roll_cells_offer_only_what_the_seed_can_move():
    slots = [dict(slot(3, 3), spread=["hp", "fat", "msk"])]
    assert L.roll_options(slots, "1", "msk") == ["any", "mid", "high"]
    assert L.roll_options(slots, "1", "res") == ["any"]
    assert L.roll_options(slots, "*", "res") == ["any", "mid", "high"]
    assert L.roll_options([slot(3, 3)], "1", "res") == ["any", "mid", "high"]      # an older catalog: no data
    assert L.roll_problems(slots, {"*": {"res": "high", "msk": "mid"}}) == [
        "Brother 1's RES is always the same — the seed cannot make it better."]
    assert L.roll_problems(slots, {"1": {"msk": "high"}}) == []


def test_catalog_lookup():
    catalog = {"talents": {"a_scenario": {"slots": BEGGAR, "sizes": [1]}, "b_scenario": {"error": "boom"}}}
    assert L.slots_for(catalog, "a_scenario") == BEGGAR
    assert L.slots_for(catalog, "b_scenario") is None
    assert L.slots_for(None, "a_scenario") is None
    assert L.sizes_for(catalog, "a_scenario") == [1]

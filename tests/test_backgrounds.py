"""The GUI's view of which backgrounds an origin's brothers can have (bbreroll/backgrounds.py). The
lists below are cut-down versions of what the catalog found for Legends 19.4.22."""
from bbreroll import backgrounds as B
from bbreroll.criteria import explain_failure, is_trivial

NAMES = {"background.hedge_knight": "Hedge Knight", "background.swordmaster": "Swordmaster",
         "background.sellsword": "Sellsword", "background.farmhand": "Farmhand", "background.thief": "Thief",
         "background.gambler": "Gambler", "background.legend_noble_2h": "Warrior"}


def slot(*ids, exact=True):
    return {"choices": list(ids), "backgrounds": list(ids[:1]), "choices_exact": exact}


FREE_COMPANY = [slot("background.sellsword", "background.farmhand"),
                slot("background.hedge_knight", "background.swordmaster")]
FIXED = [slot("background.farmhand"), slot("background.thief")]
RANDOM = [slot("background.thief", "background.gambler"), slot("background.thief", "background.gambler",
                                                                "background.hedge_knight")]


def test_names_and_choices_sorted_by_name():
    assert B.choices(FREE_COMPANY, NAMES)[1] == [("background.hedge_knight", "Hedge Knight"),
                                                ("background.swordmaster", "Swordmaster")]
    assert B.display("background.legend_noble_2h") == "Noble 2H"
    assert B.display("background.legend_noble_2h", NAMES) == "Warrior"


def test_only_brothers_with_more_than_one_background_vary():
    assert B.varied(FREE_COMPANY) == [1, 2]
    assert B.varied(FIXED) == []
    assert B.varied([slot("background.farmhand"), slot("background.thief", "background.gambler")]) == [2]


def test_the_any_brother_row_needs_two_varied_brothers():
    assert [b for b, _n in B.any_choices(RANDOM, NAMES)] == [
        "background.gambler", "background.hedge_knight", "background.thief"]
    assert B.any_choices(FIXED) == []
    assert B.any_choices([slot("background.farmhand"), slot("background.thief", "background.gambler")]) == []


def test_impossible_background_conditions():
    assert B.problems(FIXED, {"1": ["background.thief"]}, NAMES) == [
        "Brother 1 is always a Farmhand. Your condition is Thief."]
    assert B.problems(FREE_COMPANY, {"2": ["background.sellsword"]}, NAMES) == [
        "Brother 2 cannot have the background Sellsword."]
    assert B.problems(FREE_COMPANY, {"2": ["background.swordmaster"], "1": []}, NAMES) == []
    assert B.problems(FREE_COMPANY, {"any": ["background.thief"]}, NAMES) == [
        "No brother of this origin can have the background Thief."]
    # a list that is not known to be complete rules nothing out
    assert B.problems([slot("background.thief", "background.gambler", exact=False)],
                      {"1": ["background.farmhand"]}) == []
    # a brother the origin does not have: the search says so
    assert B.problems(FIXED, {"5": ["background.thief"]}) == []


def test_describe():
    assert "does not change" in B.describe(FIXED)
    assert B.describe(FREE_COMPANY) == "The seed selects the background of brothers 1, 2."
    assert "Other backgrounds are possible" in B.describe([slot("background.a", "background.b", exact=False)])


def test_a_background_condition_is_a_condition():
    base = {"stars_by_slot": {"*": {}}, "banned": [], "required": []}
    assert is_trivial(dict(base, backgrounds_by_slot={"1": []}))
    assert not is_trivial(dict(base, backgrounds_by_slot={"1": ["background.thief"]}))


def test_background_failures_as_sentences():
    assert explain_failure("bro3 background legend_noble_2h", background_names=NAMES) == (
        "Brother 3 has the background Warrior. Your condition is a different background.")
    assert explain_failure("no bro with a wanted background") == "No brother has a background from your conditions."


def test_two_backgrounds_with_one_name_stay_apart():
    names = {"background.legend_conscript": "Conscript", "background.legend_conscript_ranged": "Conscript"}
    menu = B.choices([slot("background.legend_conscript", "background.legend_conscript_ranged")], names)[0]
    assert menu == [("background.legend_conscript", "Conscript (legend_conscript)"),
                    ("background.legend_conscript_ranged", "Conscript (legend_conscript_ranged)")]

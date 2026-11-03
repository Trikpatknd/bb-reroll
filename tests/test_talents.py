"""Which stars a recruit's talent roll made, and which ones the origin set (bbseed/talents.py).
The calls are real ones, logged from Legends 19.4.22 rolls on 2026-10-15."""
import pytest

from bbseed.talents import SlotFacts, analyse

# Const.Attributes order: Hitpoints, Bravery, Fatigue, Initiative, MeleeSkill, RangedSkill, MeleeDefense, RangedDefense
INDEX = {"hp": 0, "res": 1, "fat": 2, "init": 3, "msk": 4, "rsk": 5, "mdf": 6, "rdf": 7}
W = [50] * 8


def stars(**given):
    return {s: given.get(s, 0) for s in INDEX}


@pytest.mark.core
def test_berserker_two_fixed_stars_then_two_forced_picks():
    calls = [([3, 0, 0, 0, 3, 0, 0, 0], [3, 0, 0, 1, 3, 0, 0, 2], [], W, False, False),
             ([3, 0, 0, 1, 3, 0, 0, 2], [3, 0, 0, 1, 3, 0, 0, 2], [], W, False, False)]   # untalented: no-op
    rolled, fixed, can_roll = analyse(calls, stars(hp=3, msk=3, init=1, rdf=2), INDEX)
    assert rolled == {"init": 1, "rdf": 2}
    assert fixed == {"hp": 3, "msk": 3}
    assert can_roll == {"res", "fat", "init", "rsk", "mdf", "rdf"}


@pytest.mark.edge
def test_a_roll_the_origin_overwrites_tells_nothing():
    # Inquisition, brother 1: rolled fat/rsk/mdf, then the origin set hp 3, res 3, msk 2
    calls = [([], [0, 0, 3, 0, 0, 1, 1, 0], [], W, False, False)]
    rolled, fixed, can_roll = analyse(calls, stars(hp=3, res=3, msk=2), INDEX)
    assert rolled == {} and fixed == {"hp": 3, "res": 3, "msk": 2} and can_roll == set()


@pytest.mark.edge
def test_only_the_surviving_call_counts():
    # Inquisition, brother 2: a full roll the origin replaced by res 3 / rsk 3, then one forced pick
    calls = [([], [0, 0, 0, 1, 1, 0, 0, 1], [], W, False, False),
             ([0, 3, 0, 0, 0, 3, 0, 0], [0, 3, 0, 0, 2, 3, 0, 0], [], W, False, False)]
    rolled, fixed, can_roll = analyse(calls, stars(res=3, msk=2, rsk=3), INDEX)
    assert rolled == {"msk": 2} and fixed == {"res": 3, "rsk": 3}
    assert can_roll == {"hp", "fat", "init", "msk", "mdf", "rdf"}


@pytest.mark.edge
def test_a_pick_the_origin_happens_to_repeat_is_still_fixed():
    # Inquisition, brother 3 (monk): the roll gave msk 2 among others, then the origin set res 3,
    # msk 2, mdf 3 — msk equals the roll by chance, but the roll's other picks are gone
    calls = [([], [0, 0, 1, 0, 2, 0, 0, 1], [], W, False, False)]
    rolled, fixed, can_roll = analyse(calls, stars(res=3, msk=2, mdf=3), INDEX)
    assert rolled == {} and fixed == {"res": 3, "msk": 2, "mdf": 3} and can_roll == set()


@pytest.mark.edge
def test_excluded_talents_can_never_be_rolled():
    # Scaling Beggar's commander excludes Hitpoints and Bravery
    calls = [([], [0, 0, 3, 0, 0, 0, 2, 1], [0, 1], W, False, False)]
    rolled, fixed, can_roll = analyse(calls, stars(fat=3, mdf=2, rdf=1), INDEX)
    assert rolled == {"fat": 3, "mdf": 2, "rdf": 1} and fixed == {}
    assert can_roll == {"fat", "init", "msk", "rsk", "mdf", "rdf"}


@pytest.mark.edge
def test_undead_recruits_skip_their_stats():
    calls = [([], [0, 0, 0, 0, 1, 1, 1, 0], [], W, True, False)]       # a zombie
    _r, _f, can_roll = analyse(calls, stars(msk=1, rsk=1, mdf=1), INDEX)
    assert can_roll == {"hp", "msk", "rsk", "mdf", "rdf"}


@pytest.mark.core
def test_slot_summary():
    facts = SlotFacts()
    facts.add("background.berserker", stars(hp=3, msk=3, init=1, rdf=2), {"res", "init", "rdf"})
    facts.add("background.berserker", stars(hp=3, msk=3, res=1, rsk=1), {"res", "rsk", "fat"})
    s = facts.summary()
    assert s["most"] == 4 and s["least"] == 4 and s["picks"] == 2
    assert s["fixed"] == {"hp": 3, "msk": 3}
    assert s["rolled"] == ["fat", "res", "init", "rsk", "rdf"]
    assert s["max"] == {"hp": 3, "fat": 3, "res": 3, "init": 3, "msk": 3, "rsk": 3, "mdf": 0, "rdf": 3}
    assert not s["varied"]


@pytest.mark.edge
def test_a_star_the_origin_writes_after_the_roll_is_fixed_even_when_the_roll_made_it_too():
    # Legends' Ranger, brother 2: the origin sets MSK 2 and HP 2 after the roll and keeps the rest;
    # on the second seed the roll itself had made MSK 2
    facts = SlotFacts()
    facts.add("background.legend_druid", stars(fat=2, msk=2, hp=2, init=1, rdf=1), {"init", "rdf", "res"})
    facts.add("background.legend_druid", stars(fat=2, msk=2, hp=2, mdf=3), {"msk", "mdf", "rsk"})
    s = facts.summary()
    assert s["fixed"] == {"hp": 2, "fat": 2, "msk": 2}
    assert s["rolled"] == ["res", "init", "rsk", "mdf", "rdf"]
    assert s["picks"] == 2 and s["most"] == 5 and s["least"] == 4


@pytest.mark.edge
def test_a_slot_whose_background_changes_is_marked():
    facts = SlotFacts()
    facts.add("background.farmhand", stars(hp=1), {"hp"})
    facts.add("background.miller", stars(fat=2), {"fat"})
    assert facts.summary()["varied"]


@pytest.mark.edge
def test_a_slot_that_picks_from_a_list_can_get_the_whole_list():
    # Free Company brother 3: one of six elite backgrounds; the samples showed only two of them
    elite = ["background.hedge_knight", "background.swordmaster", "background.gladiator"]
    facts = SlotFacts()
    facts.add("background.hedge_knight", stars(msk=1), {"msk"}, pool=elite)
    facts.add("background.swordmaster", stars(mdf=1), {"mdf"}, pool=elite)
    s = facts.summary()
    assert s["choices"] == sorted(elite) and s["choices_exact"] and s["varied"]


@pytest.mark.edge
def test_a_list_with_one_background_seen_once_is_still_varied():
    facts = SlotFacts()
    facts.add("background.gambler", stars(), set(), pool=["background.gambler", "background.thief"])
    assert facts.summary()["varied"] and facts.summary()["choices"] == ["background.gambler", "background.thief"]


@pytest.mark.edge
def test_a_background_the_origin_sets_outside_any_list_is_not_exact():
    facts = SlotFacts()
    facts.add("background.legend_commander_beggar", stars(), set(), pool=None)
    facts.add("background.legend_commander_beggar", stars(), set(), pool=["background.beggar"])  # replaced later
    s = facts.summary()
    assert s["choices"] == ["background.legend_commander_beggar"] and not s["choices_exact"] and not s["varied"]


@pytest.mark.edge
def test_brothers_that_share_a_list_share_every_list():
    # Random Party: each brother rolls from the common list, 1 time in 100 from the party list
    from bbseed.talents import share_lists
    common, party, other = ["background.a", "background.b"], ["background.c"], ["background.d", "background.e"]
    one, five, solo = SlotFacts(), SlotFacts(), SlotFacts()
    one.add("background.a", stars(), set(), pool=common)
    five.add("background.b", stars(), set(), pool=common)
    five.add("background.c", stars(), set(), pool=party)
    solo.add("background.d", stars(), set(), pool=other)
    share_lists([one, five, solo])
    assert one.summary()["choices"] == ["background.a", "background.b", "background.c"]
    assert solo.summary()["choices"] == ["background.d", "background.e"]


# ====================================================================== which brothers are final (early exit)
early_group = pytest.mark.xdist_group("early_labs")


@pytest.fixture(scope="module")
def labs():
    """Altered labs (the rolls watched, the brother hook on): their own, not the session's (conftest.py)."""
    from bbseed import profiles
    from bbseed.lab import Lab, big_stack
    found = profiles.installed_summary()
    if not found or found["game_version"] != "1.5.2.3" or not any("mod_legends-19.4.22" in m for m in found["mods"]):
        pytest.skip("Battle Brothers 1.5.2.3 with Legends 19.4.22 is not installed")
    return {"legends": big_stack(lambda: Lab("legends").watch_rolls()),
            "vanilla": big_stack(lambda: Lab("vanilla").watch_rolls())}


def _final_from(lab, origin, seeds=40):
    from bbseed.lab import big_stack
    from bbseed.talents import FinalWatch
    final = FinalWatch()

    def run():
        for n in range(seeds):
            final.finish(lab.roster(str(5000000 + n).zfill(10), origin, fresh=n == 0, stop_after=final.look))
    big_stack(run)
    return final.final_from()


@pytest.mark.slow
@pytest.mark.core
@early_group
def test_trading_caravan_brother_1_is_final(labs):
    assert _final_from(labs["legends"], "trader_scenario") == 1
    assert _final_from(labs["vanilla"], "trader_scenario") == 1


@pytest.mark.slow
@pytest.mark.core
@early_group
def test_a_new_company_is_final_too(labs):
    """The plan expected no early final slot here. Measured over 200 seeds (MODLOG "EARLY EXIT"): its fixed stars come before
    the next brother starts, so every brother is final by then."""
    assert _final_from(labs["legends"], "early_access_scenario") == 1


@pytest.mark.slow
@pytest.mark.edge
@early_group
def test_legends_militia_changes_its_brothers_later(labs):
    assert _final_from(labs["legends"], "militia_scenario", 8) == 12
    assert _final_from(labs["vanilla"], "militia_scenario", 8) == 1


@pytest.mark.slow
@pytest.mark.edge
@early_group
def test_gladiators_cannot_be_read_when_the_next_one_starts(labs):
    assert _final_from(labs["legends"], "gladiators_scenario", 4) == 3


@pytest.mark.slow
@pytest.mark.core
@early_group
def test_a_stopped_roster_leaves_the_state_like_a_full_one(labs):
    """The next seed's roster equals one on a fresh state, whatever was stopped before it."""
    from bbseed.lab import big_stack
    lab = labs["legends"]
    results = {}

    def run():
        for seed in ("0000000011", "0000000012", "0000000013", "0000000014"):
            first = lab.roster(seed, "trader_scenario", fresh=True)
            stopped = lab.roster("0000000099", "trader_scenario", fresh=False, stop_after=lambda slot, bro: True)
            again = lab.roster(seed, "trader_scenario", fresh=False)
            results[seed] = (first, stopped, again)
        full = lab.roster("0000000099", "trader_scenario", fresh=True)
        seen = []
        lab.roster("0000000099", "trader_scenario", fresh=False, stop_after=lambda slot, bro: seen.append((slot, bro)) or True)
        results["seen"] = (full, seen)
        looked = []
        results["slots"] = lab.roster("0000000099", "trader_scenario", fresh=False, stop_slots={7},
                                      stop_after=lambda slot, bro: looked.append(slot) or True), looked
    big_stack(run)
    for seed in ("0000000011", "0000000012", "0000000013", "0000000014"):
        first, stopped, again = results[seed]
        assert stopped is None
        assert first == again, seed
    full, seen = results["seen"]
    assert [slot for slot, _bro in seen] == [1], "stopped at the first question"
    assert seen[0][1]["stars"] == full[0]["stars"] and seen[0][1]["rolls"] == full[0]["rolls"]
    assert results["slots"][1] == [] and results["slots"][0] is not None, "a slot that is not asked does not stop"


class _SurveyWatch:
    """TalentWatch's roll for talents.survey: `size` brothers, brother 1 changes after he is complete when `changes`."""
    names = {}

    def __init__(self, size, changes=False, unread=False):
        self.size, self.changes, self.unread = size, changes, unread

    def roll(self, seed, origin, loop=None, stop_after=None):
        roster = [{"stars": {"hp": 1}, "traits": ["brave"], "background": "background.monk"} for _ in range(self.size)]
        for slot in range(1, self.size):
            if stop_after is not None:
                seen = dict(roster[slot - 1], traits=["later"] if self.changes and slot == 1 else ["brave"])
                assert stop_after(slot, None if self.unread else seen) is False
        split = [([], [], ())] * self.size
        return roster, split, [None] * self.size


@pytest.mark.core
def test_a_survey_says_from_which_slot_on_the_brothers_are_final():
    from bbseed.talents import FINAL_SAMPLES, survey
    found = survey(_SurveyWatch(3), "trader_scenario")
    assert found["final_from"] == 1 and found["samples"] == FINAL_SAMPLES, "2 or more brothers: enough rosters to tell"
    assert survey(_SurveyWatch(3, changes=True), "trader_scenario")["final_from"] == 2
    assert survey(_SurveyWatch(3, unread=True), "trader_scenario")["final_from"] == 3
    one = survey(_SurveyWatch(1), "lone_wolf_scenario")
    assert one["final_from"] == 1 and one["samples"] < FINAL_SAMPLES, "one brother: nothing to tell, no extra rosters"
    assert survey(_SurveyWatch(2), "deserters_scenario")["final_from"] is None, "its search never stops early"


@pytest.mark.edge
def test_a_catalog_from_before_final_from_is_built_again():
    from bbseed.catalog import CATALOG_VERSION
    assert CATALOG_VERSION == 7


@pytest.mark.dirty
def test_a_brother_who_leaves_the_roster_later_is_not_final():
    """An origin (of a mod) can remove a brother after he is complete. That crashed the catalog's worker, and its build waited for ever."""
    from bbseed.talents import FinalWatch
    final = FinalWatch()
    bro = {"stars": {"hp": 1}, "traits": [], "background": "background.monk"}
    final.look(1, bro)
    final.look(3, bro)
    final.finish([bro, bro])
    assert final.final_from() == 4

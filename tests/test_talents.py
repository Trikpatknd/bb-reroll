"""Which stars a recruit's talent roll made, and which ones the origin set (bbseed/talents.py).
The calls are real ones, logged from Legends 19.4.22 rolls on 2026-10-15."""
from bbseed.talents import SlotFacts, analyse

# Const.Attributes order: Hitpoints, Bravery, Fatigue, Initiative, MeleeSkill, RangedSkill, MeleeDefense, RangedDefense
INDEX = {"hp": 0, "res": 1, "fat": 2, "init": 3, "msk": 4, "rsk": 5, "mdf": 6, "rdf": 7}
W = [50] * 8


def stars(**given):
    return {s: given.get(s, 0) for s in INDEX}


def test_berserker_two_fixed_stars_then_two_forced_picks():
    calls = [([3, 0, 0, 0, 3, 0, 0, 0], [3, 0, 0, 1, 3, 0, 0, 2], [], W, False, False),
             ([3, 0, 0, 1, 3, 0, 0, 2], [3, 0, 0, 1, 3, 0, 0, 2], [], W, False, False)]   # untalented: no-op
    rolled, fixed, can_roll = analyse(calls, stars(hp=3, msk=3, init=1, rdf=2), INDEX)
    assert rolled == {"init": 1, "rdf": 2}
    assert fixed == {"hp": 3, "msk": 3}
    assert can_roll == {"res", "fat", "init", "rsk", "mdf", "rdf"}


def test_a_roll_the_origin_overwrites_tells_nothing():
    # Inquisition, brother 1: rolled fat/rsk/mdf, then the origin set hp 3, res 3, msk 2
    calls = [([], [0, 0, 3, 0, 0, 1, 1, 0], [], W, False, False)]
    rolled, fixed, can_roll = analyse(calls, stars(hp=3, res=3, msk=2), INDEX)
    assert rolled == {} and fixed == {"hp": 3, "res": 3, "msk": 2} and can_roll == set()


def test_only_the_surviving_call_counts():
    # Inquisition, brother 2: a full roll the origin replaced by res 3 / rsk 3, then one forced pick
    calls = [([], [0, 0, 0, 1, 1, 0, 0, 1], [], W, False, False),
             ([0, 3, 0, 0, 0, 3, 0, 0], [0, 3, 0, 0, 2, 3, 0, 0], [], W, False, False)]
    rolled, fixed, can_roll = analyse(calls, stars(res=3, msk=2, rsk=3), INDEX)
    assert rolled == {"msk": 2} and fixed == {"res": 3, "rsk": 3}
    assert can_roll == {"hp", "fat", "init", "msk", "mdf", "rdf"}


def test_a_pick_the_origin_happens_to_repeat_is_still_fixed():
    # Inquisition, brother 3 (monk): the roll gave msk 2 among others, then the origin set res 3,
    # msk 2, mdf 3 — msk equals the roll by chance, but the roll's other picks are gone
    calls = [([], [0, 0, 1, 0, 2, 0, 0, 1], [], W, False, False)]
    rolled, fixed, can_roll = analyse(calls, stars(res=3, msk=2, mdf=3), INDEX)
    assert rolled == {} and fixed == {"res": 3, "msk": 2, "mdf": 3} and can_roll == set()


def test_excluded_talents_can_never_be_rolled():
    # Scaling Beggar's commander excludes Hitpoints and Bravery
    calls = [([], [0, 0, 3, 0, 0, 0, 2, 1], [0, 1], W, False, False)]
    rolled, fixed, can_roll = analyse(calls, stars(fat=3, mdf=2, rdf=1), INDEX)
    assert rolled == {"fat": 3, "mdf": 2, "rdf": 1} and fixed == {}
    assert can_roll == {"fat", "init", "msk", "rsk", "mdf", "rdf"}


def test_undead_recruits_skip_their_stats():
    calls = [([], [0, 0, 0, 0, 1, 1, 1, 0], [], W, True, False)]       # a zombie
    _r, _f, can_roll = analyse(calls, stars(msk=1, rsk=1, mdf=1), INDEX)
    assert can_roll == {"hp", "msk", "rsk", "mdf", "rdf"}


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


def test_a_slot_whose_background_changes_is_marked():
    facts = SlotFacts()
    facts.add("background.farmhand", stars(hp=1), {"hp"})
    facts.add("background.miller", stars(fat=2), {"fat"})
    assert facts.summary()["varied"]

"""origin_hardcoded_stars.conflicts() — the pre-flight unsatisfiability check."""
from bbreroll import origin_hardcoded_stars as ohs


def test_gladiators_bear_msk_is_unsatisfiable():
    # Slot 2 (the Bear) is hp/fat/res only — melee skill is fixed at 0.
    c = ohs.conflicts("Gladiators", {"*": {"msk": 2}})
    assert (2, "msk", 2, 0) in c
    # Slots 1 and 3 have melee skill, so they don't conflict.
    assert all(slot == 2 for slot, *_ in c)


def test_gladiators_mdf_on_bear_unsatisfiable():
    c = ohs.conflicts("Gladiators", {"*": {"mdf": 2}})
    assert (2, "mdf", 2, 0) in c


def test_numeric_slot_overrides_star_default():
    # Slot 1 numeric criterion overrides "*" entirely (not merged), matching
    # BBReroll_BF_StarsFor. The Lion has msk 3, so slot 1 is fine; the * fat:3
    # still applies to the other slots.
    c = ohs.conflicts("Gladiators", {"*": {"fat": 3}, "1": {"msk": 3}})
    slots = {slot for slot, *_ in c}
    assert 1 not in slots                 # slot 1 uses its own {msk:3}, satisfied
    assert 2 in slots and 3 in slots      # bear fat 2<3, viper fat 0<3


def test_fully_rolled_origin_never_conflicts():
    assert ohs.conflicts("Davkul Cultists", {"*": {"msk": 3, "mdf": 3}}) == []


def test_satisfiable_returns_empty():
    # Lion (slot 1) has msk 3, mdf 2, fat 2 — all satisfiable at these mins.
    assert ohs.conflicts("Gladiators", {"*": {}, "1": {"msk": 3, "mdf": 2}}) == []


def test_partial_origin_rolled_slot_skipped():
    # Ranger: slot 1 rolled, slot 2 (Druid) = {msk:2, hp:2}. hp:3 on * hits slot 2.
    c = ohs.conflicts("Ranger", {"*": {"hp": 3}})
    assert (2, "hp", 3, 2) in c
    assert all(slot != 1 for slot, *_ in c)   # rolled slot never conflicts


def test_unknown_origin_no_conflict():
    assert ohs.conflicts("Nonexistent Origin", {"*": {"msk": 3}}) == []


def test_a_slot_with_a_roll_on_top_only_knows_its_fixed_stars():
    # Berserker: HP 3 and MSK 3 fixed, two more stats rolled — FAT 3 is possible, MSK above 3 is not
    assert ohs.conflicts("Berserker", {"*": {"fat": 3, "hp": 3}}) == []
    # Inquisition, brother 2: RES 3 and RSK 3 fixed plus one roll; brother 1 and 3 fully fixed
    c = ohs.conflicts("The Inquisition", {"*": {"mdf": 1}})
    assert (2, "mdf", 1, 0) not in c and (1, "mdf", 1, 0) in c

"""Stat roll tiers against the background's own range (bbseed/rolls.py)."""
import pytest

from bbseed.rolls import distribution, meets, place, tier
from bbseed.search import first_failure, normalize, parse_tiers

ZERO = dict.fromkeys(("hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf"), 0)


def test_one_even_roll():
    dist = distribution(1, 3, averaged=False)
    assert dist == pytest.approx({1: 1 / 3, 2: 1 / 3, 3: 1 / 3})
    assert place(1, 3, 1, False) == pytest.approx(1 / 6) and tier(1, 3, 1, False) == "low"
    assert tier(1, 3, 2, False) == "mid" and tier(1, 3, 3, False) == "high"


def test_legends_averages_two_rolls_in_integers():
    # (a + b) / 2 truncated: 50..52 -> sums 100..104 -> 50, 50 (101), 51, 51 (103), 52
    dist = distribution(50, 52, averaged=True)
    assert dist == pytest.approx({50: 3 / 9, 51: 5 / 9, 52: 1 / 9})
    assert sum(dist.values()) == pytest.approx(1)
    # the middle is likelier than with one roll, so its tier band is wider
    assert tier(50, 52, 50, True) == "low" and tier(50, 52, 51, True) == "mid" and tier(50, 52, 52, True) == "high"


def test_negative_sums_truncate_toward_zero_as_squirrel_does():
    dist = distribution(-2, -1, averaged=True)       # sums -4, -3, -3, -2 -> -2, -1, -1, -1
    assert dist == pytest.approx({-2: 0.25, -1: 0.75})


def test_a_single_value_range_has_no_tier():
    assert place(55, 55, 55, True) is None and tier(55, 55, 55, True) == "fixed"


def test_minimum_tiers():
    assert meets("high", "mid") and meets("mid", "mid") and not meets("low", "mid")
    assert meets("high", "high") and not meets("mid", "high")
    assert not meets("fixed", "mid"), "the seed cannot move a fixed stat"
    assert meets("low", "low") and meets(None, None)


def bro(**tiers):
    return {"stars": dict(ZERO), "traits": [],
            "rolls": {s: {"lo": 0, "hi": 9, "value": 5, "tier": tiers.get(s, "low")} for s in ZERO}}


def test_roll_criteria_follow_the_slot_rules():
    c = normalize({"tiers_by_slot": {"*": "msk:mid", "2": {"hp": "high", "res": "any"}}})
    assert c["tiers_by_slot"] == {"*": {"msk": "mid"}, "2": {"hp": "high"}}
    assert first_failure([bro(msk="high"), bro(hp="high")], c) is None      # slot 2's own row replaces "*"
    assert first_failure([bro(msk="low"), bro(hp="high")], c) == "bro1 msk roll low<mid"
    assert first_failure([bro(msk="mid"), bro(hp="mid")], c) == "bro2 hp roll mid<high"
    assert first_failure([bro(msk="mid")], normalize({"tiers_by_slot": {"3": "hp:mid"}})) == \
        "no bro3 in this origin's roster"


def test_parse_tiers():
    assert parse_tiers("msk:high res:mid") == {"msk": "high", "res": "mid"}
    for bad in ("msk", "msk:great", "xyz:high"):
        with pytest.raises(ValueError):
            parse_tiers(bad)

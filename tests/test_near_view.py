"""The closest seed's differences as lines for the player."""
import pytest

from bbreroll.near_view import lines


def diff(kind, name="", slot=1, have=None, want=None):
    return {"slot": slot, "kind": kind, "name": name, "have": have, "want": want}


EVERY_KIND = [
    diff("stars", "res", 2, 1, 2), diff("stars", "msk", 1, 0, 3), diff("roll", "msk", 1, "low", "high"),
    diff("roll", "res", 1, "fixed", "mid"), diff("roll", "res", 1, None, "mid"), diff("banned", "dumb", 1, True, False),
    diff("required", "lucky", 1, False, True), diff("required", "", 3, [], ["lucky"]),
    diff("background", "background.farmhand", 3, "background.farmhand", ["background.monk"]),
    diff("background", "any", None, None, ["background.monk"]), diff("map", "ports", None, 4, 5),
    diff("map", "city_state", None, 1, 2), diff("slot", "", 4),
]


@pytest.mark.core
def test_each_kind_of_difference_has_a_short_line():
    got = lines(EVERY_KIND, lambda t: t.title(), {"background.farmhand": "Farmhand"})
    assert len(got) == len(EVERY_KIND)
    for line in got:
        assert line.isascii() and len(line.split()) <= 25, line
        assert line.endswith("."), line
    assert got[0] == "Brother 2: RES has 1 star. The condition is 2."
    assert got[1] == "Brother 1: MSK has 0 stars. The condition is 3."
    assert got[2] == "Brother 1: the MSK roll is low. The condition is high."
    assert got[3] == "Brother 1: the RES roll is fixed. The condition is mid."
    assert got[4] == "Brother 1: the RES roll is not known. The condition is mid."
    assert got[5] == "Brother 1 has the banned trait Dumb."
    assert got[6] == "Brother 1 does not have the required trait Lucky."
    assert got[7] == "Brother 3 has none of the required traits."
    assert got[8] == "Brother 3 has the background Farmhand. The condition is a different background."
    assert got[9] == "No brother has a background from the conditions."
    assert got[10] == "Ports: 4. The condition is 5."
    assert got[11] == "City states: 1. The condition is 2."
    assert got[12] == "This origin has no brother 4."


@pytest.mark.edge
def test_without_names_the_lines_use_the_ids():
    assert lines([diff("banned", "iron_jaw", 1, True, False)]) == ["Brother 1 has the banned trait Iron Jaw."]
    assert "Legend Noble" in lines([diff("background", "background.legend_noble", 1)])[0] or "Noble" in lines(
        [diff("background", "background.legend_noble", 1)])[0]


@pytest.mark.edge
def test_no_differences_no_lines():
    assert lines([]) == []

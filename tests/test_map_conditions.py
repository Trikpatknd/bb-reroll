"""Map conditions (bbseed/mapgen.py: counts, failure; bbreroll/map_conditions.py: labels, limits, problems,
map_line) on hand-made map summaries: no game needed. In a summary, high y is north (the measured layout)."""
import pytest

from bbreroll import map_conditions as M
from bbseed import mapgen

ZERO_TOWNS = {"city_state": 0, "military": 0, "size1": 0, "size2": 0, "size3": 0}


def town(x, y, port=False, southern=False, military=False, size=1):
    return {"name": "Town %d %d" % (x, y), "script": "city_state" if southern else "legends_fishing_village",
            "size": size, "x": x, "y": y, "southern": southern, "military": military, "port": port, "faction": None}


def summary(size=(10, 10), towns=()):
    w, h = size
    return {"size": [w, h], "layout": "even-q-up", "terrain": "L" * (w * h), "towns": list(towns), "attempts": 1}


# the brief's map, turned so that its northern port is at the north edge (y = 9) and the southern one at the south
# edge (y = 0): high y is north
S = summary(size=(10, 10), towns=[town(1, 9, port=True), town(2, 0, port=True, southern=True, size=3), town(5, 5)])


def test_counts_ports_north_and_south():
    assert mapgen.counts(S, north_band=20) == {"ports": 2, "ports_south": 1, "ports_north": 1,
                                               "towns": dict(ZERO_TOWNS, city_state=1, size1=2)}


def test_a_southern_port_in_the_north_band_is_a_southern_port_only():
    # Ruling C: northern ports are the ports in the band that are not southern
    s = summary(towns=[town(3, 9, port=True, southern=True, size=3)])
    assert mapgen.counts(s, north_band=50) == {"ports": 1, "ports_south": 1, "ports_north": 0,
                                               "towns": dict(ZERO_TOWNS, city_state=1)}


def test_town_types_split_the_towns():
    """Every town has exactly one type: southern -> city state, else military -> stronghold (any size),
    else its size (village, town, city)."""
    towns = [town(0, 0, southern=True, size=3), town(1, 0, military=True, size=1), town(2, 0, military=True, size=3),
             town(3, 0, size=1), town(4, 0, size=2), town(5, 0, size=2), town(6, 0, size=3)]
    got = mapgen.counts(summary(towns=towns), north_band=33)["towns"]
    assert got == {"city_state": 1, "military": 2, "size1": 1, "size2": 2, "size3": 1}
    assert list(got) == list(mapgen.TOWN_TYPE_KEYS)
    assert sum(got.values()) == len(towns)


def test_a_town_size_outside_1_to_3_is_an_error():
    with pytest.raises(ValueError):
        mapgen.counts(summary(towns=[town(0, 0, size=4)]), north_band=33)


def _band_rows(height, band):
    """The rows y of a `height`-row map that the north band holds, found with one port per row."""
    s = summary(size=(1, height), towns=[town(0, y, port=True) for y in range(height)])
    n = mapgen.counts(s, north_band=band)["ports_north"]
    rows = [y for y in range(height) if mapgen.in_north_band(y, height, band)]
    assert len(rows) == n
    return rows


@pytest.mark.parametrize("band, first", [(1, 169), (20, 136), (33, 114), (50, 85), (99, 2)])
def test_the_north_band_is_the_top_rows_rounded_down(band, first):
    """A band of P % holds the rows y with 100 * (height - y) <= P * height: the top floor(height * P / 100) rows
    (y = height - 1 is the north edge). 170 rows (Legends): 1 % = 1 row, 20 % = 34, 33 % = 56, 50 % = 85,
    99 % = 168."""
    assert _band_rows(170, band) == list(range(first, 170))


def test_the_north_band_on_a_small_map():
    assert _band_rows(10, 20) == [8, 9]
    assert _band_rows(10, 25) == [8, 9]          # 2.5 rows: rounded down
    assert _band_rows(10, 5) == []               # half a row: no row
    assert _band_rows(10, 0) == [] and _band_rows(10, 100) == list(range(10))


def test_counts_rejects_a_band_outside_0_to_100():
    for band in (-1, 101):
        with pytest.raises(ValueError):
            mapgen.counts(S, north_band=band)


def test_failure_names_the_first_unmet_condition():
    assert mapgen.failure(S, {"ports": 3}) == "Ports: 2, needs 3"
    assert mapgen.failure(S, {"ports": 2, "ports_south": 1}) is None
    assert mapgen.failure(S, {"ports_south": 2}) == "Southern ports: 1, needs 2"
    assert mapgen.failure(S, {"ports_north": 2, "north_band": 20}) == "Northern ports: 1, needs 2"
    assert mapgen.failure(S, {"towns": {"city_state": 2}}) == "City states: 1, needs 2"
    assert mapgen.failure(S, {"towns": {"military": 1}}) == "Strongholds: 0, needs 1"
    # the order: ports, southern ports, northern ports, then the town types in TOWN_TYPE_KEYS order
    assert mapgen.failure(S, {"ports": 3, "ports_south": 2, "towns": {"size3": 9}}) == "Ports: 2, needs 3"
    assert mapgen.failure(S, {"towns": {"size3": 9, "size1": 3}}) == "Villages: 2, needs 3"


def test_zero_or_missing_is_no_condition():
    assert mapgen.failure(S, {}) is None and mapgen.failure(S, None) is None
    assert mapgen.failure(S, {"ports": 0, "ports_south": 0, "ports_north": 0, "towns": {"size3": 0}}) is None


def test_failure_uses_the_default_north_band():
    s = summary(towns=[town(4, 6, port=True)])          # in a 50 % band (rows 5-9), not in 33 % (rows 7-9)
    assert mapgen.DEFAULT_NORTH_BAND == 33
    assert mapgen.failure(s, {"ports_north": 1}) == "Northern ports: 0, needs 1"
    assert mapgen.failure(s, {"ports_north": 1, "north_band": None}) == "Northern ports: 0, needs 1"
    assert mapgen.failure(s, {"ports_north": 1, "north_band": 50}) is None


def test_failure_rejects_an_unknown_town_type():
    with pytest.raises(ValueError):
        mapgen.failure(S, {"towns": {"castle": 1}})


def test_town_type_labels():
    assert list(M.TOWN_TYPES) == list(mapgen.TOWN_TYPE_KEYS) == ["city_state", "military", "size1", "size2", "size3"]
    assert M.TOWN_TYPES == {"city_state": "City states", "military": "Strongholds", "size1": "Villages",
                            "size2": "Towns", "size3": "Cities"}
    assert M.counts is mapgen.counts and M.failure is mapgen.failure


def test_limits_at_the_default_map_options():
    assert M.limits(None) == M.limits({}) == M.limits(dict(M.MAP_OPTION_DEFAULTS)) == {
        "ports": 23, "ports_south": 3, "ports_north": 20,
        "towns": {"city_state": 3, "military": 6, "size1": 9, "size2": 9, "size3": 10}}


def test_limits_at_settlements_27():
    assert M.limits({"Settlements": 27}) == {
        "ports": 32, "ports_south": 3, "ports_north": 29,
        "towns": {"city_state": 3, "military": 9, "size1": 15, "size2": 15, "size3": 16}}


def test_the_most_towns_per_settlements_value():
    """The placement calls of Legends' buildSettlements for Settlements 19..27, as counted in map-search Task 5: the
    port limit is the town count (every list can make a port), southern + northern ports are all of them."""
    most = [M.limits({"Settlements": s}) for s in range(19, 28)]
    assert [m["ports"] for m in most] == [23, 23, 26, 26, 27, 28, 29, 30, 32]
    assert all(m["ports_south"] + m["ports_north"] == m["ports"] for m in most)
    # the size limits share the random calls: their sum is more than the town count
    assert all(sum(m["towns"].values()) > m["ports"] for m in most)


def test_only_settlements_changes_the_limits():
    others = {"LandRatio": 70, "Water": 28, "Snowline": 75, "Factions": 6, "StackCitadels": True,
              "AllTradeLocations": True}
    assert M.limits(others) == M.limits(None)
    assert M.limits(dict(others, Settlements="24")) == M.limits({"Settlements": 24})


def test_limits_rejects_bad_map_options():
    for bad in ({"Settlements": 18}, {"Settlements": 28}, {"Settlements": "many"},
                {"mod_legends:Settlements": 24}):          # the lab's key form is not a Map Options key here
        with pytest.raises(ValueError):
            M.limits(bad)


def test_problems():
    assert M.problems({"ports": 2, "ports_south": 2, "ports_north": 1})      # north + south > total
    assert M.problems({"ports_north": 1, "north_band": 0}) and M.problems({"ports_north": 1, "north_band": 100})
    assert M.problems({"ports": M.limits(None)["ports"] + 1})
    assert M.problems({"ports": 3, "north_band": 33}) == []


def test_problem_texts():
    assert M.problems({"ports": 24}) == [
        "Ports: a map has a maximum of 23 with these Map Options. Your condition is 24."]
    assert M.problems({"ports": 2, "ports_south": 2, "ports_north": 1}) == [
        "Ports: southern and northern ports are also ports. Set ports to 3 or more. Your condition is 2."]
    assert M.problems({"ports_north": 1, "north_band": 0}) == [
        "North band: set a value from 1 to 99 for northern ports. Your value is 0."]
    assert M.problems({"towns": {"city_state": 4}}) == [
        "City states: a map has a maximum of 3 with these Map Options. Your condition is 4."]
    assert M.problems({}, {"Settlements": 30}) == ["Settlements: set a value from 19 to 27. Your value is 30."]


def test_the_limits_follow_the_map_options():
    assert M.problems({"ports": 24}) and M.problems({"ports": 24}, {"Settlements": 27}) == []
    assert M.problems({"ports_north": 21}) and M.problems({"ports_north": 21}, {"Settlements": 21}) == []
    assert M.problems({"towns": {"military": 7}}) and M.problems({"towns": {"military": 7}}, {"Settlements": 21}) == []


def test_no_problem_without_conditions():
    assert M.problems(None) == [] and M.problems({}) == []
    assert M.problems({"north_band": 0}) == []          # the band matters only for northern ports
    assert M.problems({"ports_north": 1}) == []         # the default band (33)
    assert M.problems({"ports": 0, "towns": {"size1": 0}}) == []


def test_villages_towns_and_cities_share_the_same_placements():
    """At Settlements 19 the village lists make 2 villages, 2 towns and 3 cities first, then 7 more of a random
    size: 9 villages or 10 cities can happen, but not both."""
    assert M.problems({"towns": {"size1": 9}}) == [] and M.problems({"towns": {"size3": 10}}) == []
    assert M.problems({"towns": {"size1": 4, "size2": 4, "size3": 6}}) == []          # 2 + 2 + 3 more = 7
    joint = "Villages, Towns and Cities: a map cannot have all of these together with these Map Options."
    assert M.problems({"towns": {"size1": 9, "size3": 10}}) == [joint]
    assert M.problems({"towns": {"size1": 4, "size2": 4, "size3": 7}}) == [joint]     # 2 + 2 + 4 more = 8


def test_every_count_of_a_map_is_a_possible_condition():
    """What one map has is never an impossible condition."""
    s = summary(towns=[town(1, 9, port=True), town(2, 0, port=True, southern=True, size=3),
                       town(3, 3, military=True, size=3), town(4, 4, size=2)])
    c = mapgen.counts(s, north_band=33)
    criteria = {"ports": c["ports"], "ports_south": c["ports_south"], "ports_north": c["ports_north"],
                "north_band": 33, "towns": c["towns"]}
    assert M.problems(criteria) == []


def test_map_line():
    towns = ([town(i, 9, port=True) for i in range(3)] + [town(i, 0, port=True, southern=True, size=3) for i in range(2)]
             + [town(5, 5, port=True), town(6, 6, port=True), town(7, 0, southern=True, size=3), town(8, 4)])
    assert M.map_line(summary(towns=towns), north_band=33) == "Ports 7 (south 2, north 3) · 3 city states"
    one = summary(towns=[town(0, 0, port=True, southern=True, size=3)])
    assert M.map_line(one, north_band=33) == "Ports 1 (south 1, north 0) · 1 city state"

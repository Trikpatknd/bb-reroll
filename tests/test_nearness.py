"""How far a seed is from the conditions: the near-match search's order."""
import random

import pytest

from bbseed import mapgen
from bbseed.nearness import differences, distance, map_short, roster_distance, slot_distance
from bbseed.search import first_failure, normalize

ZERO = dict.fromkeys(("hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf"), 0)


def one(traits=(), background="background.farmhand", rolls=None, **stars):
    out = {"stars": dict(ZERO, **stars), "traits": list(traits), "background": background}
    if rolls is not None:
        out["rolls"] = {stat: {"tier": tier} for stat, tier in rolls.items()}
    return out


def bro(*a, **k):
    """A roster of one."""
    return [one(*a, **k)]


def town(x=0, y=0, script="small_farming_village", size=2, **kw):
    return dict({"name": "T", "script": script, "size": size, "x": x, "y": y, "southern": False, "military": False,
                 "port": False, "faction": None}, **kw)


def a_map(*towns, h=40):
    return {"size": [10, h], "terrain": "L" * (10 * h), "towns": list(towns)}


@pytest.mark.core
def test_two_stars_short_is_nearer_than_a_banned_trait():
    # the user's example: want res 3, ban dumb
    c = normalize({"stars_by_slot": {"1": {"res": 3}}, "banned": ["dumb"]})
    assert distance(bro(res=2), None, c) == (0, 1, 0)
    assert distance(bro(res=3, traits=["dumb"]), None, c) == (1, 0, 0)
    assert (0, 1, 0) < (1, 0, 0)


@pytest.mark.core
def test_each_kind_of_miss_counts_by_the_rule():
    banned = normalize({"banned": ["dumb", "fat"]})
    assert slot_distance(1, one(traits=["dumb", "fat"]), banned) == (2, 0)
    anyone = normalize({"required": ["iron_jaw", "lucky"], "required_slots": [1]})
    assert roster_distance([one(), one()], anyone) == (1, 0), "only the required slot counts"
    both = normalize({"required": ["iron_jaw", "lucky"], "required_mode": "all"})
    assert slot_distance(1, one(traits=["lucky"]), both) == (1, 0)
    assert slot_distance(1, one(), both) == (2, 0)
    place = normalize({"backgrounds_by_slot": {"1": ["background.farmhand"], "any": ["background.monk"]}})
    assert roster_distance([one(background="background.miller"), one()], place) == (2, 0)
    assert roster_distance([one(), one(background="background.monk")], place) == (0, 0)
    stars = normalize({"stars_by_slot": {"1": {"res": 3, "msk": 2}}})
    assert slot_distance(1, one(res=1, msk=3), stars) == (0, 2), "a stat with more stars pays nothing back"


@pytest.mark.core
def test_a_slot_row_replaces_row_all():
    c = normalize({"stars_by_slot": {"*": {"res": 3}, "2": {"msk": 1}}})
    assert slot_distance(1, one(), c) == (0, 3)
    assert slot_distance(2, one(), c) == (0, 1), "row 2 only, as in slot_failure"
    tiers = normalize({"tiers_by_slot": {"*": {"res": "high"}, "2": {"msk": "mid"}}})
    assert slot_distance(2, one(rolls={"res": "low", "msk": "low"}), tiers) == (0, 1)


@pytest.mark.core
def test_roll_tiers_count_their_levels():
    c = normalize({"tiers_by_slot": {"1": {"res": "high", "msk": "mid", "hp": "high"}}})
    assert slot_distance(1, one(rolls={"res": "low", "msk": "low", "hp": "mid"}), c) == (0, 2 + 1 + 1)
    assert slot_distance(1, one(rolls={"res": "high", "msk": "high", "hp": "high"}), c) == (0, 0)


@pytest.mark.core
def test_an_exact_roster_with_a_wrong_map_beats_a_near_roster():
    assert (0, 0, 1) < (0, 1, 0)
    c = normalize({"stars_by_slot": {"1": {"res": 3}}, "map": {"ports": 2}})
    assert distance(bro(res=3), a_map(town(port=True)), c) == (0, 0, 1)
    assert distance(bro(res=2), None, c) == (0, 1, 0), "no map was built: the map part is 0"


@pytest.mark.core
def test_the_map_part_adds_every_condition():
    want = normalize({"map": {"ports": 3, "ports_south": 1, "ports_north": 2, "north_band": 33,
                              "towns": {"city_state": 2}}})["map"]
    # one southern port in the south, one port in the north band: 1 port short, none south, 1 north, 1 city state
    summary = a_map(town(y=2, port=True, southern=True, script="city_state"), town(y=39, port=True))
    assert map_short(summary, want) == 1 + 0 + 1 + 1
    assert map_short(None, want) == 0
    assert map_short(summary, None) == 0


def _random_roster(rng):
    stats = list(ZERO)
    traits = ["dumb", "fat", "lucky", "iron_jaw"]
    backgrounds = ["background.farmhand", "background.miller", "background.monk"]
    roster = []
    for _ in range(rng.choice((1, 2, 3))):
        roster.append(one(traits=rng.sample(traits, rng.randrange(3)), background=rng.choice(backgrounds),
                          rolls={s: rng.choice(("low", "mid", "high", "fixed")) for s in stats} if rng.random() < .9 else None,
                          **{s: rng.randrange(4) for s in rng.sample(stats, 3)}))
    return roster


def _random_criteria(rng):
    stats = list(ZERO)
    criteria = {}
    if rng.random() < .6:
        criteria["stars_by_slot"] = {rng.choice(("*", "1", "2", "4")): {rng.choice(stats): rng.randrange(1, 3)}}
    if rng.random() < .3:
        criteria["tiers_by_slot"] = {rng.choice(("*", "1", "2")): {rng.choice(stats): rng.choice(("mid", "high"))}}
    if rng.random() < .3:
        criteria["backgrounds_by_slot"] = {rng.choice(("1", "2", "any", "4")): ["background.farmhand", "background.monk"]}
    if rng.random() < .4:
        criteria["banned"] = ["dumb"]
    if rng.random() < .4:
        criteria["required"] = rng.sample(["lucky", "iron_jaw", "fat"], rng.randrange(1, 3))
        criteria["required_mode"] = rng.choice(("any", "all"))
        if rng.random() < .5:
            criteria["required_slots"] = [rng.choice((1, 2))]
    if rng.random() < .5:
        criteria["map"] = {"ports": rng.randrange(0, 3), "towns": {"city_state": rng.randrange(0, 2)}}
    return normalize(criteria)


@pytest.mark.core
def test_zero_distance_is_exactly_no_first_failure():
    rng = random.Random(20261103)
    exact = near = 0
    for _ in range(2000):                  # (a plain 200 gives few exact ones)
        roster, c = _random_roster(rng), _random_criteria(rng)
        summary = a_map(*[town(port=True, script=rng.choice(("city_state", "x")), southern=rng.random() < .5)
                          for _ in range(rng.randrange(3))])
        passes = first_failure(roster, c) is None and (c["map"] is None or mapgen.failure(summary, c["map"]) is None)
        got = distance(roster, summary, c)
        assert (got == (0, 0, 0)) == passes, (roster, c, got)
        assert (differences(roster, summary, c) == []) == passes, (roster, c)
        exact += passes
        near += not passes
    assert exact > 50 and near > 50, "the sample has both"


@pytest.mark.edge
def test_a_fixed_stat_roll_asked_for_counts_short():
    c = normalize({"tiers_by_slot": {"1": {"res": "high"}}})
    assert slot_distance(1, one(rolls={"res": "fixed"}), c) == (0, 2)
    assert slot_distance(1, one(), c) == (0, 2), "no roll data: unknown counts as low"
    assert slot_distance(1, one(rolls={"res": "fixed"}), normalize({"tiers_by_slot": {"1": {"res": "mid"}}})) == (0, 1)


@pytest.mark.edge
def test_a_wanted_slot_the_origin_does_not_have_is_one_miss():
    c = normalize({"stars_by_slot": {"3": {"res": 3}}, "tiers_by_slot": {"3": {"msk": "mid"}, "4": {"msk": "mid"}},
                   "backgrounds_by_slot": {"3": ["background.monk"]}})
    assert roster_distance([one()], c) == (2, 0), "slots 3 and 4, once each"
    kinds = differences([one()], None, c)
    assert [(d["slot"], d["kind"]) for d in kinds] == [(3, "slot"), (4, "slot")]


@pytest.mark.core
def test_differences_are_empty_exactly_at_zero_distance():
    c = normalize({"stars_by_slot": {"1": {"res": 3}}, "tiers_by_slot": {"1": {"msk": "high"}}, "banned": ["dumb"],
                   "required": ["lucky"], "backgrounds_by_slot": {"1": ["background.monk"], "any": ["background.miller"]},
                   "map": {"ports": 1}})
    good = [one(traits=["lucky"], background="background.monk", rolls={"msk": "high"}, res=3),
            one(traits=["lucky"], background="background.miller", rolls={"msk": "low"})]
    summary = a_map(town(port=True))
    assert distance(good, summary, c) == (0, 0, 0) and differences(good, summary, c) == []
    bad = [one(traits=["dumb"], background="background.farmhand", rolls={"msk": "mid"}, res=1)]
    got = {(d["slot"], d["kind"], d["name"]): (d["have"], d["want"]) for d in differences(bad, a_map(), c)}
    assert got == {
        (1, "banned", "dumb"): (True, False),
        (1, "required", ""): ([], ["lucky"]),
        (1, "background", "background.farmhand"): ("background.farmhand", ["background.monk"]),
        (1, "stars", "res"): (1, 3),
        (1, "roll", "msk"): ("mid", "high"),
        (None, "background", "any"): (None, ["background.miller"]),
        (None, "map", "ports"): (0, 1),
    }
    assert distance(bad, a_map(), c) == (4, 3, 1)

"""How far a seed is from the conditions: distance = (trait_background_misses, star_and_roll_points_short, map_short),
compared left to right. Smaller is nearer; (0, 0, 0) is an exact match. The search reports the nearest seed it has
seen when no seed matches. The rule has no weights, so the player can check a card's rank by hand.

  trait_background_misses   1 per banned trait on a brother; required "any": 1 per brother in required_slots with none;
                            required "all": 1 per missing trait; 1 per brother with a wrong background; 1 if no brother
                            has an "any brother" background; 1 per wanted slot the origin does not have
  star_and_roll_points_short  per stat want - have stars (a slot's row replaces row All, as in search.slot_failure),
                            plus per stat the tier levels short (low 0, mid 1, high 2; "fixed" or unknown counts as 0)
  map_short                 the sum of max(0, want - have) over the map conditions; 0 when no map was built

An exact roster with a wrong map so outranks any near-miss roster, and no map is built only to rank a seed.
criteria: search.normalize's output. Distance 0 is exactly search.first_failure and mapgen.failure both finding nothing
(a test holds the two together): a change to those rules is a change here too.
"""
from .rolls import TIERS

_ANY = "any"        # search.ANY_BROTHER (search imports this module)


def _level(tier):
    return TIERS.index(tier) if tier in TIERS else 0


def _row(table, slot):
    table = table or {}
    return table.get(str(slot)) or table.get("*", {})


def _required_here(slot, criteria):
    return criteria["required"] and (criteria["required_slots"] is None or slot in criteria["required_slots"])


def slot_distance(slot, bro, criteria):
    """(misses, points short) of one brother, in roster slot `slot` (1 = first)."""
    misses = short = 0
    allowed = (criteria.get("backgrounds_by_slot") or {}).get(str(slot))
    if allowed and bro["background"] not in allowed:
        misses += 1
    for stat, want in _row(criteria["stars_by_slot"], slot).items():
        short += max(0, want - bro["stars"][stat])
    want = _row(criteria.get("tiers_by_slot"), slot)
    if want:
        rolls = bro.get("rolls")
        for stat, level in want.items():
            short += max(0, _level(level) - _level(rolls[stat]["tier"] if rolls else None))
    traits = set(bro["traits"])
    misses += len(traits & set(criteria["banned"]))
    if _required_here(slot, criteria):
        required = set(criteria["required"])
        misses += len(required - traits) if criteria["required_mode"] == "all" else not traits & required
    return misses, short


def _missing_slots(roster, criteria):
    """The wanted brothers the origin does not have, as numbers."""
    wanted = set(criteria["stars_by_slot"]) | set(criteria.get("tiers_by_slot") or {}) | set(
        criteria.get("backgrounds_by_slot") or {})
    return sorted(int(s) for s in wanted - {"*", _ANY} if int(s) > len(roster))


def _any_background_missing(roster, criteria):
    wanted = (criteria.get("backgrounds_by_slot") or {}).get(_ANY)
    return bool(wanted) and not any(bro["background"] in wanted for bro in roster)


def roster_distance(roster, criteria):
    """(misses, points short) of a whole roster."""
    misses = len(_missing_slots(roster, criteria)) + _any_background_missing(roster, criteria)
    short = 0
    for slot, bro in enumerate(roster, 1):
        m, s = slot_distance(slot, bro, criteria)
        misses += m
        short += s
    return misses, short


def _map_shortfalls(summary, map_criteria):
    """[(key, have, want)] of the map conditions the summary does not meet, in mapgen.failure's order."""
    if summary is None or not map_criteria:
        return []
    from .mapgen import DEFAULT_NORTH_BAND, PORT_KEYS, TOWN_TYPE_KEYS, counts
    band = map_criteria.get("north_band") if map_criteria.get("ports_north") else None
    have = counts(summary, DEFAULT_NORTH_BAND if band is None else band)
    towns = map_criteria.get("towns") or {}
    out = [(key, have[key], map_criteria.get(key) or 0) for key in PORT_KEYS]
    out += [(key, have["towns"][key], towns.get(key) or 0) for key in TOWN_TYPE_KEYS]
    return [(key, got, want) for key, got, want in out if got < want]


def map_short(summary, map_criteria):
    """How many ports and towns the map lacks; 0 when no map was built (summary None) or there is no condition."""
    return sum(want - got for _key, got, want in _map_shortfalls(summary, map_criteria))


def distance(roster, summary, criteria):
    """The whole order: (misses, points short, map short). roster None: no roster was rolled (a map-first search)."""
    misses, short = roster_distance(roster, criteria) if roster is not None else (0, 0)
    return misses, short, map_short(summary, criteria.get("map"))


def _slot_differences(slot, bro, criteria):
    out = []

    def add(kind, name, have, want):
        out.append({"slot": slot, "kind": kind, "name": name, "have": have, "want": want})

    traits = set(bro["traits"])
    for trait in sorted(traits & set(criteria["banned"])):
        add("banned", trait, True, False)
    if _required_here(slot, criteria):
        required = set(criteria["required"])
        if criteria["required_mode"] == "all":
            for trait in sorted(required - traits):
                add("required", trait, False, True)
        elif not traits & required:
            add("required", "", [], sorted(required))
    allowed = (criteria.get("backgrounds_by_slot") or {}).get(str(slot))
    if allowed and bro["background"] not in allowed:
        add("background", bro["background"], bro["background"], list(allowed))
    for stat, want in _row(criteria["stars_by_slot"], slot).items():
        if bro["stars"][stat] < want:
            add("stars", stat, bro["stars"][stat], want)
    want = _row(criteria.get("tiers_by_slot"), slot)
    if want:
        rolls = bro.get("rolls")
        for stat, level in want.items():
            tier = rolls[stat]["tier"] if rolls else None
            if _level(tier) < _level(level):
                add("roll", stat, tier, level)
    return out


def differences(roster, summary, criteria):
    """What keeps the seed from an exact match, one dict per point of its distance's kinds: {"slot": int | None, "kind":
    "banned" | "required" | "background" | "stars" | "roll" | "map" | "slot", "name": str, "have": ..., "want": ...}.
    Empty exactly at distance 0. bbreroll/near_view.py turns these into the card's lines."""
    out = []
    if roster is not None:
        for slot, bro in enumerate(roster, 1):
            out += _slot_differences(slot, bro, criteria)
        for slot in _missing_slots(roster, criteria):
            out.append({"slot": slot, "kind": "slot", "name": "", "have": None, "want": None})
        if _any_background_missing(roster, criteria):
            out.append({"slot": None, "kind": "background", "name": _ANY, "have": None,
                        "want": list(criteria["backgrounds_by_slot"][_ANY])})
    for key, got, want in _map_shortfalls(summary, criteria.get("map")):
        out.append({"slot": None, "kind": "map", "name": key, "have": got, "want": want})
    return out

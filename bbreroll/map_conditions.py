"""Map conditions for the GUI: the labels, the most a map can have with the player's Map Options, the
conditions no seed can meet, and the seed post's map line. tkinter-free, unit-tested
(tests/test_map_conditions.py). The counting itself (`counts`, `failure`, TOWN_TYPE_KEYS) is in bbseed/mapgen.py,
because the search workers need it and bbseed never imports bbreroll; it is re-exported here.

Conditions ({"ports", "ports_south", "ports_north", "north_band", "towns": {key: n}}) are minimums; 0 or missing is
no condition. A port is the game's own settlement flag IsCoastal. Southern ports are ports that are southern towns
(the city states); northern ports are the other ports in the north band (the top `north_band` percent of the map's
rows, see mapgen.in_north_band).

limits() is the most the scripts can place, not what maps usually have. The survey (bb_seedlab MODLOG "MAP SURVEY
(2026-10-19)"): 1,000 Legends 19.4.22 maps at the default Map Options, seeds 5000000000..5000000999; 997 finished
(3 runs raised in guaranteeAllBuildingsInSettlements). min / median / p90 / max:
  ports 0 / 4 / 5 / 7 (limit 23); southern ports 0 / 0 / 1 / 3 (limit 3)
  northern ports, band 20 %: 0 / 0 / 0 / 1; 33 %: 0 / 0 / 1 / 3; 50 %: 0 / 0 / 1 / 4
  city states 2 / 3 / 3 / 3; strongholds 6 on every map; villages 1 / 5 / 7 / 9; towns 1 / 4 / 5 / 8;
  cities 2 / 4 / 5 / 8; all towns 19 / 22 / 23 / 23
  maps with at least k ports: 1: 89.4 %, 2: 75.2 %, 3: 63.4 %, 4: 53.6 %, 5: 22.6 %, 6: 3.9 %, 7: 0.5 %
  at least 1 southern port: 39.1 % (2: 4.3 %); at least 1 northern port in the 33 % band: 22.2 % (2: 5.1 %)
No surveyed map was above its limit (also not 100 maps at Settlements 27).
"""
import math

from bbseed.mapgen import (DEFAULT_NORTH_BAND, PORT_KEYS, PORT_LABELS, TOWN_TYPE_KEYS, TOWN_TYPE_LABELS,  # noqa: F401
                           counts, failure)
from bbseed.sq.runtime import f32

TOWN_TYPES = TOWN_TYPE_LABELS

# Legends' Map Options (mod_legends/register/modsettings.nut:16-25) with their defaults, by the keys the seed post
# uses (seed_report._MAP_OPTION_LABELS).
MAP_OPTION_DEFAULTS = {"LandRatio": 50, "Water": 38, "Snowline": 85, "Settlements": 19, "Factions": 3,
                       "StackCitadels": False, "AllTradeLocations": False}
SETTLEMENTS_RANGE = (19, 27)          # RangeSetting("Settlements", 19, 19, 27, 1, ...)

# Legends 19.4.22 Const.World.Settlements.LegendsWorldMaster (mod_legends/!config/world.nut:79-156), in order:
# (town type of every town the list makes, Ratio, Sizes as (Size, Ratio, MinAmount)). The kind of each list comes
# from its Types (mod_legends/!!config/world_settlements.nut): Legends_villages_coast and Legends_villages are
# legends_village scripts (IsMilitary false), Legends_fortifications are legends_fort scripts (IsMilitary true),
# Legends_citystates is city_state (isSouthern). A game test checks this table against the game's.
LEGENDS_LISTS = (
    ("civil", 0.20, ((1, 5, 1), (2, 3, 1), (3, 2, 1))),            # Legends_villages_coast
    ("civil", 0.50, ((1, 5, 1), (2, 3, 1), (3, 2, 2))),            # Legends_villages
    ("military", 0.30, ((1, 5, 1), (2, 3, 1), (3, 2, 2))),         # Legends_fortifications
    ("city_state", 0.0, ((3, 10, 3),)),                            # Legends_citystates
)


def _settlements_raw(map_options):
    """The Settlements value as given (the default when missing); ValueError for a key that is not a Map Option
    (a programming error, e.g. the lab's "mod_legends:Settlements" form)."""
    opts = map_options or {}
    unknown = set(opts) - set(MAP_OPTION_DEFAULTS)
    if unknown:
        raise ValueError("unknown Map Options %s (known: %s)" % (sorted(unknown), ", ".join(MAP_OPTION_DEFAULTS)))
    return opts.get("Settlements", MAP_OPTION_DEFAULTS["Settlements"])


def _settlements_value(raw):
    """The Settlements value as an int in SETTLEMENTS_RANGE, or None when it is not one."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if SETTLEMENTS_RANGE[0] <= value <= SETTLEMENTS_RANGE[1] else None


def _settlements(map_options):
    """The Settlements Map Option (an int in SETTLEMENTS_RANGE); ValueError for an unknown key or a bad value."""
    raw = _settlements_raw(map_options)
    value = _settlements_value(raw)
    if value is None:
        raise ValueError("Settlements %r: the game allows %d..%d" % (raw, *SETTLEMENTS_RANGE))
    return value


def _placements(settlements):
    """The placement calls of Legends' buildSettlements (worldmap_generator.nut hook :388-436), per list:
    (kind, {size: MinAmount summed}, the random calls, the sizes a random call can pick).

    Per list: num = Math.ceil(Settlements * Ratio) (:399; Squirrel floats are 32-bit, as here); one addSettlement per
    MinAmount of each size, each one num-- (:407-414); then `while (num > 0)` one more call per num (:416-431), whose
    size is drawn: r = rand(1, 10) picks the first size whose running Ratio total reaches r (a size is never picked
    when the totals before it reach 10). addSettlement (:247-386) places at most one town per call (it gives up after
    3000 tries). Every list makes MinAmount towns first, so its calls are max(num, sum of MinAmount)."""
    out = []
    for kind, ratio, sizes in LEGENDS_LISTS:
        num = math.ceil(f32(f32(settlements) * f32(ratio)))
        mins = {}
        for size, _r, minimum in sizes:
            mins[size] = mins.get(size, 0) + minimum
        extra = max(0, num - sum(mins.values()))
        pickable, total = set(), 0
        for size, r, _m in sizes:
            if r > 0 and total < 10:
                pickable.add(size)
            total += r
        out.append((kind, mins, extra if pickable else 0, pickable))
    return out


def limits(map_options=None):
    """The most of each condition one map can have with these Map Options (None: Legends' defaults), in the shape of
    counts(): {"ports", "ports_south", "ports_north", "towns": {key: n}}. Only Settlements changes it: the other
    options act on the terrain or after the towns, never on the number of placement calls.

    Per town type: the MinAmount calls of its lists plus all of their random calls (see _placements). Ports: every
    list holds a type that can stand at the sea (the coastal fishing village and coast fort, the city state is
    IsFlexible), and the port flag comes from the tile's neighbours and the open sea (settlement.updateProperties),
    so the scripts give no tighter bound than the town count: ports <= all towns, southern ports <= city states,
    northern ports <= the towns that are not southern."""
    towns = dict.fromkeys(TOWN_TYPE_KEYS, 0)
    total = 0             # not the sum of the size limits: a random call makes one town of ONE size
    for kind, mins, extra, pickable in _placements(_settlements(map_options)):
        calls = sum(mins.values()) + extra
        total += calls
        if kind == "civil":
            for size, n in mins.items():
                towns["size%d" % size] += n + (extra if size in pickable else 0)
        else:
            towns[kind] += calls
    return {"ports": total, "ports_south": towns["city_state"], "ports_north": total - towns["city_state"],
            "towns": towns}


def _civil_fits(want, settlements):
    """Can one map have at least want[size] villages / towns / cities (want: {1: n, 2: n, 3: n}) at the same time?
    The civil lists make their MinAmount towns of each size first; what is more must come from their random calls,
    each of which makes one town of one size. Hall's condition over every set of sizes: the towns missing in those
    sizes fit into the random calls of the lists that can pick one of them."""
    lists = [(mins, extra, pickable) for kind, mins, extra, pickable in _placements(settlements) if kind == "civil"]
    made = {}
    for mins, _e, _p in lists:
        for size, n in mins.items():
            made[size] = made.get(size, 0) + n
    missing = {size: max(0, n - made.get(size, 0)) for size, n in want.items()}
    sizes = [s for s, n in missing.items() if n]
    for mask in range(1, 1 << len(sizes)):
        group = {s for i, s in enumerate(sizes) if mask >> i & 1}
        room = sum(extra for _m, extra, pickable in lists if pickable & group)
        if sum(missing[s] for s in group) > room:
            return False
    return True


def problems(map_criteria, map_options=None):
    """Map conditions no seed can meet with these Map Options (None: Legends' defaults), as texts for the GUI's
    pre-search check; [] when the search can run."""
    c = map_criteria or {}
    raw = _settlements_raw(map_options)
    settlements = _settlements_value(raw)
    if settlements is None:
        return ["Settlements: set a value from %d to %d. Your value is %s." % (*SETTLEMENTS_RANGE, raw)]
    lim = limits({"Settlements": settlements})
    out = []
    want = {key: c.get(key) or 0 for key in PORT_KEYS}
    want_towns = {key: (c.get("towns") or {}).get(key) or 0 for key in TOWN_TYPE_KEYS}
    for key in PORT_KEYS:
        if want[key] > lim[key]:
            out.append("%s: a map has a maximum of %d with these Map Options. Your condition is %d."
                       % (PORT_LABELS[key], lim[key], want[key]))
    if want["ports"] and want["ports_south"] and want["ports_north"] \
            and want["ports_south"] + want["ports_north"] > want["ports"]:
        out.append("Ports: southern and northern ports are also ports. Set ports to %d or more. Your condition is %d."
                   % (want["ports_south"] + want["ports_north"], want["ports"]))
    if want["ports_north"]:
        band = c.get("north_band")
        band = DEFAULT_NORTH_BAND if band is None else band
        if not 1 <= band <= 99:
            out.append("North band: set a value from 1 to 99 for northern ports. Your value is %s." % (band,))
    over = False
    for key in TOWN_TYPE_KEYS:
        if want_towns[key] > lim["towns"][key]:
            over = True
            out.append("%s: a map has a maximum of %d with these Map Options. Your condition is %d."
                       % (TOWN_TYPES[key], lim["towns"][key], want_towns[key]))
    civil = {size: want_towns["size%d" % size] for size in (1, 2, 3)}
    if not over and not _civil_fits(civil, settlements):
        out.append("Villages, Towns and Cities: a map cannot have all of these together with these Map Options.")
    return out


def map_line(summary, north_band=DEFAULT_NORTH_BAND):
    """The seed post's map line, e.g. "Ports 7 (south 2, north 3) · 3 city states"."""
    c = counts(summary, north_band)
    states = c["towns"]["city_state"]
    return "Ports %d (south %d, north %d) · %d city state%s" % (
        c["ports"], c["ports_south"], c["ports_north"], states, "" if states == 1 else "s")

"""Find campaign seeds whose starting roster meets your criteria — without the game.

    python -m bbseed.search --profile legends --origin trader_scenario ^
        --stars 1 "res2 fat2" --ban dumb --ban fat --workers 8 --count 3

Criteria follow BB Reroll's model (and its config keys, see --criteria):
  stars     minimum talent stars, e.g. "msk2 mdf2", per roster slot (1 = first recruit);
            "*" is the rule for every recruit that has no row of its own (a slot's row
            replaces "*" for that recruit, it is not added to it).
            Stats: hp fat res init msk rsk mdf rdf
  banned    no recruit may have any of these traits
  tiers     the least a stat's roll may be, per roster slot, measured against what that recruit's
            background can roll: low / mid / high = bottom / middle / top third, e.g. "msk:high"
  required  every recruit must have at least one of these traits (mode "any")
            or all of them (mode "all"); limit it to some slots with --require-slots
  backgrounds  the backgrounds a roster slot may have, e.g. --background 3 "hedge_knight swordmaster";
            slot "any": at least one recruit has one of them. Only origins that pick a
            recruit's background from a list (Free Company, Random Party, Militia ...) vary it.
  map       the world map's least ports / southern ports / northern ports (ports in the top --north-band
            percent of the rows that are not city states) / towns per type, e.g. --ports 5 --towns city_state=3.
            A map takes about 25 s to build, so it is built only for seeds whose roster meets the rest
            (with map conditions only: for every seed, and the roster only for the maps that meet them).
            The Map Options go in --mod-setting (mod_legends:Settlements=24 ...).
  Deserters  its brothers are made after the map, so every seed needs its whole map (about 25 s) and the roster comes
            from that one run (the Map Options change the brothers: pass them in --mod-setting). Only on a setup whose
            maps are verified (Legends 19.4.22 / the base game with all DLCs); start the seed as your first campaign
            after the game starts (Legends' black-market counter).

The seeds found are plain campaign seeds: typed into the new-campaign screen of a game
with the same game version, mods and mod settings, they give this roster. They are made
of digits only, so the game's case-sensitive seed text cannot be mistyped.

The world map of a seed (about 25 s): its towns and ports, and with --svg a picture, north at the top:

    python -m bbseed.search --profile legends --map 1234567890 --svg map.svg
"""
import argparse
import json
import multiprocessing as mp
import os
import queue
import random
import sys
import time
import traceback

from .nearness import differences as near_differences, distance as near_distance, slot_distance

STATS = ("hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf")


# ---------------------------------------------------------------------- criteria
def parse_stars(spec):
    """"msk2 mdf1" -> {"msk": 2, "mdf": 1}"""
    out = {}
    for token in spec.split():
        stat, num = token.rstrip("0123456789"), token[len(token.rstrip("0123456789")):]
        if stat not in STATS or not num or not 0 <= int(num) <= 3:
            raise ValueError("bad star requirement %r (use e.g. msk2; stats: %s)" % (token, " ".join(STATS)))
        out[stat] = int(num)
    return out


def parse_tiers(spec):
    """"msk:high res:mid" -> {"msk": "high", "res": "mid"} — the least a stat's roll may be,
    measured in what the recruit's background can roll (see rolls.py)."""
    out = {}
    for token in spec.split():
        stat, _, level = token.partition(":")
        if stat not in STATS or level not in ("mid", "high"):
            raise ValueError("bad roll requirement %r (use e.g. msk:high or res:mid; stats: %s)" % (token, " ".join(STATS)))
        out[stat] = level
    return out


def _trait(t):
    return t[6:] if t.startswith("trait.") else t


ANY_BROTHER = "any"         # the backgrounds row that at least one recruit must meet


def background_id(b):
    """"hedge_knight" or "background.hedge_knight" -> "background.hedge_knight" (the game's id)."""
    return b if b.startswith("background.") else "background." + b


MAP_KEYS = ("ports", "ports_south", "ports_north", "north_band", "towns")


def _minimum(value, what):
    """A map condition's number: 0 or more (None: 0)."""
    if value is None:
        return 0
    try:
        if isinstance(value, bool):
            raise TypeError
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("map condition %s: %r is not a number" % (what, value)) from None
    if n < 0:
        raise ValueError("map condition %s: %r (use 0 or more)" % (what, value))
    return n


def _band(value):
    """The north band as a number, or None when it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_map(map_criteria):
    """The map conditions ({"ports", "ports_south", "ports_north", "north_band", "towns": {type: n}}, see
    mapgen.failure) with every key filled in: missing counts are 0, the band is DEFAULT_NORTH_BAND when missing,
    town types with 0 are left out. None when there is no map condition (a band alone is none). The band matters
    only for northern ports: with "ports_north" set it must be 1..99 (ValueError otherwise), without it a band
    that is not 1..99 is replaced by the default. Unknown keys and town types are a ValueError (a typo would
    otherwise be no condition)."""
    if not map_criteria:
        return None
    from .mapgen import DEFAULT_NORTH_BAND, PORT_KEYS, TOWN_TYPE_KEYS
    unknown = set(map_criteria) - set(MAP_KEYS)
    if unknown:
        raise ValueError("unknown map conditions %s (known: %s)" % (sorted(unknown), ", ".join(MAP_KEYS)))
    out = {key: _minimum(map_criteria.get(key), key) for key in PORT_KEYS}
    towns = {}
    for key, n in (map_criteria.get("towns") or {}).items():
        if key not in TOWN_TYPE_KEYS:
            raise ValueError("unknown town type %r (known: %s)" % (key, ", ".join(TOWN_TYPE_KEYS)))
        n = _minimum(n, key)
        if n:
            towns[key] = n
    raw = map_criteria.get("north_band")
    band = DEFAULT_NORTH_BAND if raw is None else _band(raw)
    if band is None or not 1 <= band <= 99:
        if out["ports_north"]:
            raise ValueError("north band %r: northern ports need a north band of 1 to 99 percent" % (raw,))
        band = DEFAULT_NORTH_BAND
    out["north_band"] = band
    out["towns"] = towns
    if not any(out[key] for key in PORT_KEYS) and not towns:
        return None
    return out


def roster_conditions(criteria):
    """Does the (normalized) criteria hold a condition on the roster (stars, rolls, backgrounds, traits)?"""
    return bool(criteria["stars_by_slot"] or criteria.get("tiers_by_slot") or criteria.get("backgrounds_by_slot")
                or criteria["banned"] or criteria["required"])


def normalize(criteria):
    """Accepts BB Reroll's config dict (stars_by_slot / banned / required / required_mode, and "map": the map
    conditions, see normalize_map)."""
    stars = {}
    for slot, spec in (criteria.get("stars_by_slot") or {}).items():
        spec = parse_stars(spec) if isinstance(spec, str) else {k: int(v) for k, v in spec.items()}
        if spec:
            stars[str(slot)] = spec
    mode = criteria.get("required_mode", "any")
    if mode not in ("any", "all"):
        raise ValueError("required_mode must be 'any' or 'all'")
    slots = criteria.get("required_slots")
    tiers = {}
    for slot, spec in (criteria.get("tiers_by_slot") or {}).items():
        spec = parse_tiers(spec) if isinstance(spec, str) else {k: v for k, v in spec.items() if v in ("mid", "high")}
        if spec:
            tiers[str(slot)] = spec
    backgrounds = {}
    for slot, ids in (criteria.get("backgrounds_by_slot") or {}).items():
        if isinstance(ids, str):
            ids = ids.replace(",", " ").split()
        ids = sorted({background_id(b) for b in ids if b})
        if ids:
            backgrounds[str(slot)] = ids
    return {
        "stars_by_slot": stars,
        "tiers_by_slot": tiers,
        "backgrounds_by_slot": backgrounds,
        "banned": sorted({_trait(t) for t in criteria.get("banned") or ()}),
        "required": sorted({_trait(t) for t in criteria.get("required") or ()}),
        "required_mode": mode,
        "required_slots": sorted(int(s) for s in slots) if slots else None,
        "map": normalize_map(criteria.get("map")),
    }


def slot_failure(slot, bro, criteria):
    """None if this recruit (roster slot `slot`, 1 = first) meets his part of the criteria, else
    a short reason."""
    allowed = (criteria.get("backgrounds_by_slot") or {}).get(str(slot))
    if allowed and bro["background"] not in allowed:
        return "bro%d background %s" % (slot, bro["background"][len("background."):])
    # a slot's own row replaces the "*" row (BB Reroll's rule since the in-game search;
    # origin_hardcoded_stars.conflicts() checks the same way)
    stars = criteria["stars_by_slot"]
    need = stars.get(str(slot)) or stars.get("*", {})
    for stat, minimum in need.items():
        if bro["stars"][stat] < minimum:
            return "bro%d %s*%d<%d" % (slot, stat, bro["stars"][stat], minimum)
    tiers = criteria.get("tiers_by_slot") or {}
    want = tiers.get(str(slot)) or tiers.get("*", {})
    if want:
        from .rolls import meets
        rolls = bro.get("rolls")
        for stat, level in want.items():
            have = rolls[stat]["tier"] if rolls else None
            if not meets(have, level):
                return "bro%d %s roll %s<%s" % (slot, stat, have or "unknown", level)
    traits = set(bro["traits"])
    hit = traits & set(criteria["banned"])
    if hit:
        return "bro%d banned %s" % (slot, sorted(hit)[0])
    required = set(criteria["required"])
    if required and (criteria["required_slots"] is None or slot in criteria["required_slots"]):
        if criteria["required_mode"] == "all":
            missing = required - traits
            if missing:
                return "bro%d missing %s" % (slot, sorted(missing)[0])
        elif not traits & required:
            return "bro%d no_good_trait" % slot
    return None


def roster_failure(roster, criteria):
    """None if the roster as a whole meets its part of the criteria (a recruit with one of the
    "any" backgrounds), else a short reason."""
    wanted = (criteria.get("backgrounds_by_slot") or {}).get(ANY_BROTHER)
    if wanted and not any(bro["background"] in wanted for bro in roster):
        return "no bro with a wanted background"
    return None


def first_failure(roster, criteria):
    """None if the roster meets the (normalized) criteria, else a short reason."""
    for slot, bro in enumerate(roster, 1):
        failure = slot_failure(slot, bro, criteria)
        if failure is not None:
            return failure
    failure = roster_failure(roster, criteria)
    if failure is not None:
        return failure
    for slot in (list(criteria["stars_by_slot"]) + list(criteria.get("tiers_by_slot") or {})
                 + list(criteria.get("backgrounds_by_slot") or {})):
        if slot not in ("*", ANY_BROTHER) and int(slot) > len(roster):
            return "no bro%s in this origin's roster" % slot
    return None


# ---------------------------------------------------------------------- odds
class Odds:
    """How often each recruit slot meets its own part of the criteria, over the seeds tested so
    far. Recruits are rolled one after the other from the seed's random stream, so the slots are
    as good as independent: the chance a seed matches is about the product of the slots' rates —
    known long before the first match, and a slot that never passes shows what to loosen.
    A condition on the roster as a whole ("any" backgrounds) counts as one more factor.

    The map conditions are one more factor, "map", with a count of its own: the map is built only for some seeds
    (with roster conditions: only for the seeds whose roster met them), so its rate is over the maps built.
    Multiplying it with the roster's rates ASSUMES the map and the roster are independent. That is an approximation,
    not true by construction: both seedings use the same seed string (engine fact 2), so the roster's draws replay
    the first draws of the map's stream. It is plausible because a map's ports and towns depend on thousands of
    draws; it is not measured.
    With map conditions only, a seed is added with no slot results (its roster has no condition to meet).
    A seed that stopped early (search.prune) says nothing about the later slots, so each slot has its own count."""

    def __init__(self, map_wanted=False):
        """map_wanted: the search has map conditions — chance() is None until a map was tested."""
        self.tested = 0
        self.passed = []          # per slot: seeds on which that recruit met his criteria
        self.slot_tested = []     # per slot: seeds that got as far as that recruit
        self.team = None          # seeds on which the roster met its whole-roster criteria (None: there are none)
        self.map = None           # [maps built, maps that met the map conditions] (None: no map built)
        self.map_wanted = map_wanted

    def add_roster(self, roster, criteria, map=None):
        team = None
        if (criteria.get("backgrounds_by_slot") or {}).get(ANY_BROTHER):
            team = roster_failure(roster, criteria) is None
        self.add([slot_failure(slot, bro, criteria) is None for slot, bro in enumerate(roster, 1)], team, map)

    def add(self, passes, team=None, map=None):
        """One seed: per slot whether that recruit met his criteria (None, or a list that ends early: not known for him),
        whether the roster met the whole-roster ones (None: no such condition), whether its map met the map conditions
        (None: no map was built for it)."""
        self.tested += 1
        self._grow(len(passes))
        for i, ok in enumerate(passes):
            if ok is not None:
                self.slot_tested[i] += 1
                if ok:
                    self.passed[i] += 1
        if team is not None:
            self.team = (self.team or 0) + bool(team)
        if map is not None:
            self._add_map(1, int(bool(map)))

    def _grow(self, slots):
        while len(self.passed) < slots:
            self.passed.append(0)
            self.slot_tested.append(0)

    def _add_map(self, built, passed):
        if self.map is None:
            self.map = [0, 0]
        self.map[0] += built
        self.map[1] += passed

    def merge(self, tested, passed, team=None, map=None, slot_tested=None):
        self.tested += tested
        self._grow(len(passed))
        for i, n in enumerate(passed):
            self.passed[i] += n
            self.slot_tested[i] += tested if slot_tested is None else slot_tested[i]
        if team is not None:
            self.team = (self.team or 0) + team
        if map is not None:
            self._add_map(*map)

    def take(self):
        """(tested, passed, team, map, slot_tested) since the last take, and start counting afresh (for the workers)."""
        out = (self.tested, list(self.passed), self.team, None if self.map is None else list(self.map),
               list(self.slot_tested))
        self.tested, self.passed, self.team, self.map, self.slot_tested = 0, [], None, None, []
        return out

    def brothers_chance(self):
        """The brothers' part of chance(): the estimated chance that a seed's roster meets its conditions (no map
        factor), or None before a seed was tested. A search with brother and map conditions shows it until enough
        maps are built for the full estimate."""
        if not self.tested:
            return None
        p = 1.0
        for n, seen in zip(self.passed, self.slot_tested):
            if seen:
                p *= n / seen
        if self.team is not None:
            p *= self.team / self.tested
        return p

    def chance(self):
        """Estimated chance that a seed matches, or None before anything was tested (with map conditions: before
        a map was built — a figure without the map factor would be too high)."""
        if not self.tested or (self.map_wanted and self.map is None):
            return None
        p = self.brothers_chance()
        if self.map is not None:
            p *= self.map[1] / self.map[0]
        return p

    def team_never(self):
        """The whole-roster criteria have not been met once."""
        return self.team == 0

    def map_never(self):
        """Maps were built and none met the map conditions."""
        return self.map is not None and self.map[1] == 0

    def maps(self):
        """How many maps were built (and tested against the map conditions)."""
        return 0 if self.map is None else self.map[0]

    def never(self, least=1):
        """Slots (1 = first) that have not passed once, on at least `least` seeds that got as far as them."""
        return [i + 1 for i, n in enumerate(self.passed) if n == 0 and self.slot_tested[i] >= max(1, least)]

    def never_tested(self, slots):
        """The fewest seeds that reached one of these slots (1 = first); 0 without slots."""
        return min((self.slot_tested[slot - 1] for slot in slots), default=0)


# ---------------------------------------------------------------------- seeds
def seed_text(n, digits=10):
    return str(n % 10 ** digits).zfill(digits)


# ---------------------------------------------------------------------- workers
# The text of the one "fatal" event a search with map conditions ends with when the lab cannot build maps of this
# game setup (the GUI turns its Map view off for the session when a fatal event starts with it).
MAP_FATAL = "Map conditions do not work with this game setup: "

# Deserters (scenario script): its brothers are made after the map (engine fact 4), so every seed of its search needs its
# whole map, run on through the start (onSpawnPlayer): one lab.world_map(stop_at="spawn") gives the map AND the roster.
# The search tests Deserters only on a verified setup with the exact mod versions (mapgen.verified_setup(exact=True))
# and ends with DESERTERS_FATAL when it cannot. It says so in two ways: a setup that is not verified (the reason is
# mapgen.DESERTERS_UNVERIFIED), and a map run that fails (DESERTERS_FATAL + DESERTERS_MAP_FAILED + the error): that is
# a fault of the map code, not of the setup, and the text does not blame the setup.
DESERTERS_SCRIPT = "deserters_scenario"
DESERTERS_FATAL = "BB Reroll cannot search Deserters: "
DESERTERS_MAP_FAILED = "The map code failed. "

# Maps built, none of them meeting the map conditions, before the player is told (GUI notice, console hint). Valid
# conditions can be rare: 6 or more ports are 3.9 % of the maps, so 0 of 20 happens in 45 % of such searches and 0 of
# 100 in 2 %. The text says the conditions are rare and the search goes on; it does not say that no seed matches.
MAP_NEVER_MAPS = 100

# Legends' black-market counter (::Const.World.Buildings.Blackmarket, never reset by the game) as it is in the first
# campaign after the game starts. Every map of a search is built so (ruling AD): the sift map and the confirming map
# of a match are then built alike, whatever other maps the worker built in between. Towns and ports do not depend
# on it; only what comes after the roads does.
SEARCH_BLACKMARKET = 0

# With no exact match after this many tested seeds (searches with a map per seed: maps built), or at the end of a run with
# none, the search shows the nearest seed it has seen (nearness.py), and after that each nearer one. The defaults:
# search(near_seeds=, near_maps=) and the GUI's fields take others (a player picks what is reasonable for the computer).
NEAR_SEEDS = 35000
NEAR_MAPS = 100
# A worker rolls a near seed again on a new world state (1 s) only from this share of NEAR_SEEDS on, and at the end of its
# run: early on the nearest seed changes often and nobody sees it, and those rolls cost 4 % of a 4,000-seed search.
NEAR_CONFIRM_SHARE = 0.9
PROGRESS_SECONDS = 1.0      # how often a worker reports its count
STOP_FILE_VARIABLE = "BBSEED_STOP_FILE"     # --events-json: the file that stops the search when it is there
# Early exit (Lab.roster's stop_after): every this many seeds a worker rolls the roster in full and compares what the stop
# read with the finished roster. A difference turns early exit off for the rest of the worker's run.
EARLY_AUDIT_SEEDS = 200
EARLY_EXIT_OFF = ("A brother changed after BB Reroll read him. The search goes on without the early stop for this origin, and it "
                  "is slower. Matches that it stopped before this message can be missing from the results.")
WORKER_DIED = "A search process ended without a result (exit code %s)."
# A brother is named as one that never meets his conditions only when this many seeds got as far as him (a seed can stop early,
# so a later brother can be reached on few seeds): the same count the GUI waits for with a brother who is reached on every seed.
NEVER_SLOT_SEEDS = 300


def near_key(distance):
    """A near seed's distance for comparing. Its map part is None when its map was not built (a search with brother and map
    conditions builds the map of a seed whose brothers miss only when it is shown): an unknown map counts as farther than
    any built one, so such a seed is nearer only when its brothers are nearer."""
    misses, short, map_short = distance
    return misses, short, float("inf") if map_short is None else map_short


def prune(distance_so_far, best):
    """Stop a seed? True when the distance of its brothers so far is already no better than the best seed found: a distance
    only grows as more brothers roll, and an equally near seed does not replace the best one. So the seed cannot match and
    cannot be the nearest. While the brothers so far are exact (0, 0) the seed goes on: it can still match, or have a nearer
    map. Only the first two parts count (a map is built after the roster). best None: nothing to compare with yet."""
    if best is None:
        return False
    so_far, target = tuple(distance_so_far[:2]), tuple(best[:2])
    return so_far > target or (so_far == target and so_far != (0, 0))


class _EverySlotFrom:
    """The slots from `first` on, for Lab.roster's stop_slots."""

    def __init__(self, first):
        self.first = first

    def __contains__(self, slot):
        return slot >= self.first


def _stop_slots(criteria, final_from):
    """The brothers whose completion can stop a seed: from final_from on (before that a later part of the origin can still
    change them), and only those a condition reads. None: no brother can (an "any brother" background needs the whole
    roster to say anything)."""
    if (criteria.get("backgrounds_by_slot") or {}).get(ANY_BROTHER):
        return None
    tiers, backgrounds = criteria.get("tiers_by_slot") or {}, criteria.get("backgrounds_by_slot") or {}
    stars = criteria["stars_by_slot"]
    if criteria["banned"] or "*" in stars or "*" in tiers or (criteria["required"] and criteria["required_slots"] is None):
        return _EverySlotFrom(final_from)
    wanted = set(stars) | set(tiers) | set(backgrounds)
    slots = {int(s) for s in wanted} | set(criteria["required_slots"] or () if criteria["required"] else ())
    return {s for s in slots if s >= final_from} or None


def _final_from(profile, origin):
    """The catalog's first slot from which on this origin's brothers are final; None when it is not known (no catalog yet, a
    mod's origin it does not hold): then no seed stops early."""
    try:
        from . import catalog
        found = (catalog.load(profile) or {}).get("talents", {}).get(origin) or {}
    except Exception:           # (the search works without it, only slower)
        return None
    return found.get("final_from")

# The town fields of a map summary that the real game was checked against (CLAUDE.md engine fact 16): the confirming
# map of a match must have the sift map's towns in these.
_STABLE_TOWN_KEYS = ("script", "x", "y", "size", "port", "southern", "military")


def _towns_key(summary):
    return [tuple(t[k] for k in _STABLE_TOWN_KEYS) for t in summary["towns"]]


class _MapsDoNotWork(Exception):
    """The worker could not build a map twice, and never built one: the game setup cannot do map conditions."""


def checked_world_map(lab, seed, origin, **kwargs):
    """lab.world_map(seed, origin, **kwargs) for a search, a check or `--map`: a map run that used an engine
    stand-in that mapgen.HARMLESS_STUBS does not explain (a mod that reaches an engine function the lab does not
    model) is a LabError, because the map may be wrong without any other sign. The search then skips that seed, or
    ends with MAP_FATAL when the first two maps both fail (README: such a mod stops the search with a load error)."""
    from .lab import LabError
    from .mapgen import unexplained_stubs
    out = lab.world_map(seed, origin, **kwargs)
    unexplained = unexplained_stubs(out["stub_uses"])
    if unexplained:
        raise LabError("map of seed %r uses engine functions that BB Reroll does not model: %s" % (
            seed, ", ".join("%s.%s" % key for key in sorted(unexplained))))
    return out


def _make_lab(profile, mod_settings):
    """A search worker's lab (tests replace this)."""
    from .lab import Lab
    return Lab(profile, mod_settings).watch_rolls()      # stat rolls: criteria and results (~1 % slower)


def _worker(index, workers, profile, mod_settings, origin, criteria, start, limit, seeds, out, final_from=None,
            near_seeds=None):
    """Tests seeds start + index, start + index + workers, ... (or every workers-th of an
    explicit seed list) and reports to the queue.

    The order per seed: with roster conditions (or none at all) the roster is rolled first on the reused world
    state, and the map (about 25 s) is built only for a roster that meets them; with map conditions only, the map
    first, and the roster only for a map that meets them. Without map conditions no map is built. A seed that meets
    everything is confirmed: its roster rolled again on a new world state (with the perk trees), its map built
    again; "stable" says both are what the sift found. Deserters (DESERTERS_SCRIPT): the brothers are made on the map, so
    every seed gets its whole map run on through the start, and the roster comes from that run (and from the confirming
    run); the map conditions, if any, are checked on the same map. Checked seeds (`seeds`) are rolled on a new world state and
    get everything (a map too, when there are map conditions), whatever fails. A player waits for a checked seed, so its map
    is built once, with what a confirming map has; "stable" then says only that the roster is the same (Deserters: True).

    final_from (the catalog's, or None): a sift roster may stop as soon as a brother from that slot on makes it worse than
    the best seed so far (prune), except with a map per seed, where the map run is the cost. Every EARLY_AUDIT_SEEDS seeds
    the roster is rolled in full and compared with what the stop read.

    near_seeds (None: NEAR_SEEDS): the seeds after which search() shows the nearest seed; the worker confirms its near
    seeds from NEAR_CONFIRM_SHARE of them on. With brother and map conditions, a near seed whose brothers miss has no map
    from the sift: its map is built when it is confirmed (near_key: until then it is nearer only by its brothers).

    A map run that fails is an "error" event for that seed and the worker goes on (about 3 in 1,000 Legends seeds
    raise in guaranteeAllBuildingsInSettlements). Only when the worker's first two map runs both fail, without one
    that worked, is it a "fatal" event (MAP_FATAL + the first error) and the worker stops: one bad seed first must
    not end the search. An exception of the map code that is not a LabError (a bug, or map data the code cannot
    read) is a MAP_FATAL event at once. Any other unexpected exception is a "fatal" event too ("<type>: <text>
    (seed ...)"): a worker never dies without telling search(), which would otherwise wait for it forever."""
    from .lab import LabError, big_stack, without_perks
    from .mapgen import MAP_NOT_BUILT, failure as map_failure

    from .mapgen import DESERTERS_UNVERIFIED

    want_map = criteria.get("map")
    deserters = origin == DESERTERS_SCRIPT
    fatal_text = DESERTERS_FATAL + DESERTERS_MAP_FAILED if deserters else MAP_FATAL
    map_first = want_map is not None and not roster_conditions(criteria)
    checking = seeds is not None
    state = {"tested": 0, "last": 0.0, "maps_work": False, "first_map_error": None, "map_error": None, "seed": None,
             "near": None, "held": None, "seen": 0, "exact": False}
    want_near = not checking and (want_map is not None or roster_conditions(criteria))
    confirm_from = (NEAR_SEEDS if near_seeds is None else near_seeds) * NEAR_CONFIRM_SHARE / workers
    stop_slots = None
    if final_from is not None and want_near and not deserters and not map_first:
        stop_slots = _stop_slots(criteria, final_from)

    def numbered():
        n = start + index
        while limit is None or n < start + limit:
            yield seed_text(n)
            n += workers

    def run():
        try:
            lab = _make_lab(profile, mod_settings)
        except Exception as e:
            out.put(("fatal", index, "%s: %s" % (type(e).__name__, e)))
            return
        info = lab.info()
        if deserters and _setup_note(info, exact=True):      # the brothers need the map: an unverified map is no roster
            out.put(("fatal", index, DESERTERS_FATAL + DESERTERS_UNVERIFIED))
            return
        out.put(("ready", index, info))
        state["last"] = time.time()
        odds = Odds()

        def progress():
            out.put(("progress", index, (state["tested"], odds.take())))
            state["tested"], state["last"] = 0, time.time()

        def map_code(fn, *args):
            """fn(*args) on the map path. A LabError passes through; any other exception is one MAP_FATAL event
            (DESERTERS_FATAL + DESERTERS_MAP_FAILED for Deserters) and _MapsDoNotWork (the worker stops, search() ends)."""
            try:
                return fn(*args)
            except LabError:
                raise
            except Exception as e:
                out.put(("fatal", index, fatal_text + "%s: %s (seed %s)" % (type(e).__name__, e, state["seed"])))
                raise _MapsDoNotWork() from e

        def map_run(seed, perks=False):
            """The map run of a seed: the lab's result with "map". Deserters: run on through the start, so the result
            also has "roster" (with the perk trees when `perks`) and the map has the start tile."""
            kwargs = {"stop_at": "spawn", "perks": perks} if deserters else {}
            return map_code(lambda: checked_world_map(lab, seed, origin, blackmarket=SEARCH_BLACKMARKET, **kwargs))

        def world_map(seed):
            """The confirming map of a result, with the company's start tile (map["start"], for the picture: the map
            run goes on through the origin's start, mapgen.py "The start"). The start is not a condition: when that run
            fails (an origin whose start uses an engine function the lab does not model), the map alone is made,
            without a start (a map that fails itself fails here again, as before)."""
            try:
                return checked_world_map(lab, seed, origin, blackmarket=SEARCH_BLACKMARKET, stop_at="spawn")["map"]
            except Exception:       # (a picture only: whatever went wrong, the map without a start is the result)
                return map_run(seed)["map"]

        def checked_run(seed):
            """The one map run of a checked seed, complete at once: the map with its start; Deserters: the perk trees too."""
            return map_run(seed, perks=True) if deserters else {"map": world_map(seed)}

        def map_fails(summary):
            return map_code(map_failure, summary, want_map)

        def build_run(seed):
            """The seed's map run for the sift (map_run); None when it failed (reported; the reason is in
            state["map_error"]). Raises _MapsDoNotWork."""
            try:
                found = checked_run(seed) if checking else map_run(seed)
            except LabError as e:
                state["map_error"] = str(e)
                if state["maps_work"]:
                    out.put(("error", index, str(e)))
                elif state["first_map_error"] is None:
                    state["first_map_error"] = str(e)       # this seed's own, or every seed's: the next one tells
                else:
                    out.put(("fatal", index, fatal_text + state["first_map_error"]))
                    raise _MapsDoNotWork() from e
                return None
            if not state["maps_work"]:
                state["maps_work"] = True
                if state["first_map_error"] is not None:
                    out.put(("error", index, state["first_map_error"]))
            return found

        def build_map(seed):
            """The seed's map summary for the sift; None when its run failed (see build_run)."""
            found = build_run(seed)
            return None if found is None else found["map"]

        def send_near(seed, roster, summary, found, confirmed):
            out.put(("near", index, {"seed": seed, "roster": roster, "map": summary, "distance": found, "confirmed": confirmed,
                                     "differences": near_differences(roster, summary, criteria)}))

        def confirm_near(seed, roster, summary, found):
            """Roll a near seed again on a new world state; its distance when it gives the same brothers (and it is sent),
            else None. A near seed of a map search without its map gets it now (a map run that fails leaves it without one)."""
            again = lab.roster(seed, origin, fresh=True)
            if without_perks(again) != without_perks(roster):
                return None
            if summary is None and want_map is not None:
                try:
                    summary = world_map(seed)
                except LabError:
                    pass
                found = near_found(again, summary)
            send_near(seed, again, summary, found, True)
            return found

        def near_found(roster, summary):
            """The distance; its map part is None in a map search when the seed has no map (near_key)."""
            found = near_distance(roster, summary, criteria)
            if summary is None and want_map is not None:
                found = found[:2] + (None,)
            return found

        def near_seed(seed, roster, summary):
            """A seed that does not match: reported when it is nearer than this worker's nearest so far (search() keeps the
            nearest of all). With a map per seed (`deserters`, `map_first`) nothing is rolled again: a second map would cost
            a seed's time, and the card says "Not checked yet". Otherwise it is rolled again from NEAR_CONFIRM_SHARE on;
            before that it is sent as not checked, so a Stop still has it, and held for confirm_held. After an exact match
            of this worker its results no longer show."""
            if not want_near or state["exact"]:
                return
            found = near_found(roster, summary)
            if found == (0, 0, 0) or (state["near"] is not None and near_key(found) >= near_key(state["near"])):
                return      # (0, 0, 0): exact on the reused world state and not on a new one: that error is reported
            if deserters or map_first or state["seen"] < confirm_from:
                state["near"] = found
                send_near(seed, roster, summary, found, False)
                if not (deserters or map_first):
                    state["held"] = (seed, roster, summary, found)
            else:
                confirmed = confirm_near(seed, roster, summary, found)
                if confirmed is not None:
                    state["near"], state["held"] = confirmed, None

        def confirm_held():
            """The held near seed is rolled again now. One that differs is no longer this worker's nearest."""
            held, state["held"] = state["held"], None
            if held is None or state["exact"]:
                return
            confirmed = confirm_near(*held)
            if confirmed is None:
                state["near"] = None
                out.put(("near_void", index, held[0]))
            else:
                state["near"] = confirmed

        def stopping_roster(seed):
            """A sift roster that may stop early: the roster, or None after a stop (the seed is counted here)."""
            nonlocal stop_slots
            seen = []
            best = (0, 0, 0) if state["exact"] else state["near"]
            audit = (state["seen"] - 1) % EARLY_AUDIT_SEEDS == 0     # the first seed too: it shows a wrong catalog at once
            total = [0, 0]

            def stop_after(slot, bro):
                if bro is None:     # (the catalog said he can be read: this roster is rolled in full)
                    return False
                misses, short = slot_distance(slot, bro, criteria)
                seen.append((slot, bro, (misses, short)))
                total[0] += misses
                total[1] += short
                return not audit and prune(total, best)
            roster = lab.roster(seed, origin, fresh=False, stop_after=stop_after, stop_slots=stop_slots)
            if roster is None:
                passes = [None] * max(slot for slot, _bro, _found in seen)
                for slot, _bro, found in seen:
                    passes[slot - 1] = found == (0, 0)
                odds.add(passes)
                return None
            if audit and any(slot_distance(slot, roster[slot - 1], criteria) != found for slot, _bro, found in seen):
                stop_slots = None
                out.put(("notice", index, EARLY_EXIT_OFF))
            return roster

        def sift(seed):
            """(roster, map summary or None, why there is no map or None) of a seed to confirm, or None. A checked
            seed whose map run failed still has its roster: the map is None and the reason is the third part.
            Deserters: the roster comes with the map (one run for each seed, whatever the conditions are); a seed whose
            map run failed has no roster at all, also when it is checked."""
            if deserters:
                found = build_run(seed)
                if found is None:
                    return None
                roster, summary = found["roster"], found["map"]
                ok = first_failure(roster, criteria) is None
                map_ok = True if want_map is None else map_fails(summary) is None
                odds.add_roster(roster, criteria, map=map_ok)       # (no map condition: every map counts as met)
                if not (ok and map_ok):
                    near_seed(seed, roster, summary)
                return (roster, summary, None) if (ok and map_ok) or checking else None
            if map_first:
                summary = build_map(seed)
                if summary is None:
                    if not checking:
                        return None
                    return lab.roster(seed, origin, fresh=True), None, state["map_error"]
                ok = map_fails(summary) is None
                odds.add([], map=ok)
                if not ok:
                    near_seed(seed, None, summary)
                if not (ok or checking):
                    return None
                # the sift roll (kept for the stable flag); after a map run the lab builds a new world state anyway
                return lab.roster(seed, origin, fresh=checking), summary, None
            # sift on the reused world state (fast); an explicit seed is rolled on a fresh one
            if stop_slots is not None:
                roster = stopping_roster(seed)
                if roster is None:
                    return None
            else:
                roster = lab.roster(seed, origin, fresh=checking)
            ok = first_failure(roster, criteria) is None
            if want_map is None or not (ok or checking):
                odds.add_roster(roster, criteria)
                if not ok:
                    near_seed(seed, roster, None)
                return (roster, None, None) if ok or checking else None
            summary = build_map(seed)
            if summary is None:
                odds.add_roster(roster, criteria)
                return (roster, None, state["map_error"]) if checking else None
            map_ok = map_fails(summary) is None
            odds.add_roster(roster, criteria, map=map_ok)
            if ok and not map_ok:
                near_seed(seed, roster, summary)
            return (roster, summary, None) if (ok and map_ok) or checking else None

        def confirm(seed, roster, summary, map_error=None):
            # the authoritative roll: a newly built world state, as in a new campaign (with the recruits' perk
            # trees, which the sifting roll leaves out); and the map built once more
            confirmed_map = None
            if deserters and checking:      # its one map run (checked_run) had the perk trees
                confirmed, confirmed_map = roster, summary
            elif deserters:      # the recruits come from the map run again, with their perk trees
                again = map_run(seed, perks=True)
                confirmed, confirmed_map = again["roster"], again["map"]
            else:
                confirmed = lab.roster_with_perks(seed, origin)
                if summary is not None:
                    confirmed_map = summary if checking else world_map(seed)
            progress()                                   # current count when the match shows
            failure = first_failure(confirmed, criteria)
            if failure is None and confirmed_map is not None and want_map is not None:
                failure = map_fails(confirmed_map)
            if failure is None and map_error is not None:       # a checked seed: the roster is shown without a map
                failure = MAP_NOT_BUILT + map_error
            if failure is None:
                state["exact"] = True
            if checking or failure is None:
                stable = without_perks(confirmed) == without_perks(roster) and (
                    summary is None or _towns_key(confirmed_map) == _towns_key(summary))
                out.put(("match", index, {"seed": seed, "roster": confirmed, "stable": stable, "failure": failure,
                                          "map": confirmed_map if want_map is not None else None}))
            elif first_failure(confirmed, criteria) is not None:
                out.put(("error", index, "seed %s matched only on the reused world state, not on a fresh "
                                         "one — skipped" % seed))
            else:
                out.put(("error", index, "seed %s: its map met the map conditions, but not when it was built "
                                         "again (%s) — skipped" % (seed, failure)))

        for seed in (seeds[index::workers] if checking else numbered()):
            state["tested"] += 1
            state["seen"] += 1
            state["seed"] = seed
            try:
                found = sift(seed)
                if found is not None:
                    confirm(seed, *found)
                if state["held"] is not None and state["seen"] >= confirm_from:
                    confirm_held()
            except LabError as e:
                out.put(("error", index, str(e)))
            if time.time() - state["last"] >= PROGRESS_SECONDS:
                progress()
        if state["first_map_error"] is not None and not state["maps_work"]:
            out.put(("error", index, state["first_map_error"]))     # the worker's only map run failed
        try:
            confirm_held()
        except LabError as e:
            out.put(("error", index, str(e)))
        progress()
        out.put(("done", index, None))

    def run_to_the_end():
        """run(), and whatever happens a last event: a worker that dies without "done" or "fatal" would make
        search() wait for it forever."""
        try:
            run()
        except _MapsDoNotWork:
            pass                            # its MAP_FATAL event is sent
        except Exception as e:
            if sys.stderr is not None:
                traceback.print_exc()
            out.put(("fatal", index, "%s: %s (seed %s)" % (type(e).__name__, e, state["seed"])))

    big_stack(run_to_the_end)


def search(profile, origin, criteria, workers=None, count=1, max_seeds=None, start=None, on_event=None,
           mod_settings=None, seeds=None, should_stop=None, near_seeds=None, near_maps=None):
    """Run the search; returns the list of matches.

    on_event(kind, payload) receives: "preparing" (archive name, scripts done, scripts total —
    only the first time a game version is used: its scripts are read once and cached),
    "ready" (workers loaded, workers total, setup info),
    "progress" (seeds tested, seconds, matches, odds: {"chance": estimated chance a seed matches,
    "chance_brothers": the brothers' part of it (no map factor; None before a seed was tested),
    "never": [roster slots that have not met their criteria once, on NEVER_SLOT_SEEDS seeds or all so far], "never_tested": the
    fewest seeds that reached one of them, "never_any": the "any brother" backgrounds
    have not been met once, "never_map": maps were built and none met the map conditions, "maps": maps built,
    "tested"}),
    "match" (dict: seed, roster, stable, failure, map: the map summary (mapgen.summary) when there are map
    conditions, else None; a checked seed whose map run failed has map None and, when its roster meets the rest,
    the failure mapgen.MAP_NOT_BUILT + the reason),
    "near" (dict: seed, roster (None: a map-first search rolled none), map (the map built for it, or None), distance,
    differences (nearness.py), confirmed (the roster was rolled again on a new world state: False after a Stop before the
    limit, and always with a map per seed)): the nearest seed so far, while
    no seed matches: at near_seeds tested seeds (None: NEAR_SEEDS; a map per seed: near_maps maps, None: NEAR_MAPS), on each
    nearer seed after that, and at the end of a run with no match (with brother and map conditions a seed whose brothers miss
    gets its map when the worker confirms it; before that its distance's map part is None, see near_key),
    "notice" (text: something the player should know, the search goes on),
    "error" / "fatal" (text), "finished" (seeds tested, seconds, matches, stopped early?).
    A fatal event that starts with MAP_FATAL (the lab cannot build maps of this game setup) ends the search: it is
    sent once, however many workers find it.
    seeds: test exactly these seed texts and report every one of them (with the criterion it
    fails, if any) instead of searching. should_stop(): polled; return True to end the search.
    mod_settings: Mod Options that differ from the mods' defaults ({"mod_legends:Settlements": 24, ...}); the
    player's Map Options go here too.
    """
    criteria = normalize(criteria)
    workers = workers or max(1, min(8, (os.cpu_count() or 2) // 2))
    if seeds is not None:
        seeds = list(seeds)
        workers = max(1, min(workers, len(seeds)))
        count = len(seeds)
    start = random.SystemRandom().randrange(10 ** 10) if start is None else start
    emit = on_event or (lambda kind, payload: None)
    try:        # here, once, and not in every worker: the first use of a game version builds its script cache
        from . import profiles
        profiles.get(profile, on_progress=lambda name, done, total: emit("preparing", (name, done, total)))
    except (FileNotFoundError, KeyError, OSError) as e:
        emit("fatal", "%s" % (e.args[0] if e.args else e))
        emit("finished", (0, 0.0, 0, False))
        return []
    final_from = _final_from(profile, origin) if seeds is None else None
    near_seeds = NEAR_SEEDS if near_seeds is None else near_seeds
    near_maps = NEAR_MAPS if near_maps is None else near_maps
    ctx = mp.get_context("spawn")
    out = ctx.Queue()
    procs = [ctx.Process(target=_worker, daemon=True,
                         args=(i, workers, profile, mod_settings, origin, criteria, start, max_seeds, seeds, out, final_from,
                               near_seeds))
             for i in range(workers)]
    for p in procs:
        p.start()
    matches, tested, running, t0, ready, stopped = [], 0, workers, None, 0, False
    odds = Odds(map_wanted=criteria["map"] is not None)
    map_per_seed = origin == DESERTERS_SCRIPT or (criteria["map"] is not None and not roster_conditions(criteria))
    near = {"best": None, "shown": None}
    noticed = set()
    ended = set()       # the workers whose last event came, or that were found dead

    def take_near(payload):
        best = near["best"]
        if (best is None or near_key(payload["distance"]) < near_key(best["distance"])
                or (payload["seed"] == best["seed"] and payload["confirmed"] and not best["confirmed"])):
            near["best"] = payload

    def show_near(at_end=False):
        due = at_end or (odds.maps() >= near_maps if map_per_seed else tested >= near_seeds)
        if due and not matches and near["best"] is not None and near["best"] is not near["shown"]:
            near["shown"] = near["best"]
            emit("near", near["best"])

    try:
        while running and len(matches) < count:
            if should_stop is not None and should_stop():
                stopped = True
                break
            try:
                kind, index, payload = out.get(timeout=0.25)
            except queue.Empty:
                # A worker can die with no last event: an import that fails (a damaged PyPy add-on), a crash of the interpreter.
                for i, p in enumerate(procs):
                    if i not in ended and not p.is_alive():
                        ended.add(i)
                        running -= 1
                        emit("fatal", WORKER_DIED % getattr(p, "exitcode", None))
                continue
            if kind == "ready":
                ready += 1
                if t0 is None:
                    t0 = time.time()
                emit("ready", (ready, workers, payload))
            elif kind == "progress":
                tested += payload[0]
                odds.merge(*payload[1])
                never = odds.never(least=min(odds.tested, NEVER_SLOT_SEEDS))
                emit("progress", (tested, time.time() - (t0 or time.time()), len(matches),
                                  {"chance": odds.chance(), "chance_brothers": odds.brothers_chance(),
                                   "never": never, "never_tested": odds.never_tested(never), "never_any": odds.team_never(),
                                   "never_map": odds.map_never(), "maps": odds.maps(), "tested": odds.tested}))
                show_near()
            elif kind == "near":
                take_near(payload)
                show_near()
            elif kind == "near_void":       # a new world state gives that seed other brothers: it is no longer the nearest
                if near["best"] is not None and near["best"]["seed"] == payload and not near["best"]["confirmed"]:
                    near["best"] = None
            elif kind == "match":
                matches.append(payload)
                emit("match", payload)
            elif kind == "error":
                emit("error", payload)
            elif kind == "notice":
                if payload not in noticed:      # (every worker can find the same)
                    noticed.add(payload)
                    emit("notice", payload)
            elif kind in ("done", "fatal"):
                running -= 1
                ended.add(index)
                if kind == "fatal":
                    emit("fatal", payload)
                    if payload.startswith((MAP_FATAL, DESERTERS_FATAL)):      # no worker can build a map: nothing can match
                        break
        while stopped:      # what the workers sent before the Stop: the closest seed may be in it
            try:
                kind, index, payload = out.get_nowait()
            except queue.Empty:
                break
            if kind == "near":
                take_near(payload)
            elif kind == "near_void" and near["best"] is not None and near["best"]["seed"] == payload:
                near["best"] = None
    finally:
        for p in procs:
            if p.is_alive():
                p.terminate()
    show_near(at_end=True)
    emit("finished", (tested, time.time() - (t0 or time.time()), len(matches), stopped))
    return matches


# ---------------------------------------------------------------------- command line
def _value(text):
    """A command-line setting value: true/false, a number, or text."""
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def _print_origins(profile):
    from .lab import Lab, big_stack

    def run():
        lab = Lab(profile)
        print("origins offered by the new-campaign menu (profile %s):" % lab.profile)
        for script, sid, title in lab.origins():
            print("   %-36s %s" % (script, title))
    big_stack(run)


def _print_seed(profile, origin, seeds, mod_settings=None):
    from .lab import Lab, big_stack, describe

    def run():
        lab = Lab(profile, mod_settings).watch_rolls()
        deserters = origin == DESERTERS_SCRIPT
        info = lab.info()
        if deserters:
            from .mapgen import FIRST_CAMPAIGN
            note = _setup_note(info, exact=True)
            if note:
                print(note, flush=True)
        for seed in seeds:
            print("seed %s, origin %s:" % (seed, origin))
            if deserters:       # the brothers are made on the map: the whole map run on through the start
                roster = checked_world_map(lab, seed, origin, stop_at="spawn", perks=True,
                                           blackmarket=SEARCH_BLACKMARKET)["roster"]
            else:
                roster = lab.roster_with_perks(seed, origin)
            for i, bro in enumerate(roster, 1):
                print("   %d. %s" % (i, describe(bro)))
            extra = _deserters_lines(info, FIRST_CAMPAIGN) if deserters else ""
            if extra:
                print(extra)
    big_stack(run)


def _deserters_lines(info, first_campaign):
    """The lines after a Deserters roster on the console: the Map Options the roster used (they are part of its
    input) and, with Legends, the first-campaign line. ASCII only."""
    lines = []
    options = info.get("map_options") or {}
    if options:
        lines.append("   Map Options used: " + ", ".join("%s %s" % (k, options[k]) for k in sorted(options)))
    if info.get("legends_version"):
        lines.append("   " + first_campaign)       # Legends' black-market counter: the maps are built at 0
    return "\n".join(lines)


def _ascii(text):
    """The console here is cp1252: names with other characters are printed with '?' in their place."""
    return str(text).encode("ascii", "replace").decode()


def map_report(seed, m, origin=None, profile=None, seconds=None, verified=False, legends=False):
    """A map summary (mapgen.summary) as text lines for the console: the towns (name, kind = the settlement's script,
    size, port, southern, military) and the port counts. With `verified` (the setup's maps are checked against the
    game) the city states' names have no "(name not verified)" mark, and with a start in the summary the line
    "Start: x, y" (square coordinates) and, with `legends`, the first-campaign line. ASCII only."""
    from .mapdraw import town_name
    towns = m["towns"]
    ports = [t for t in towns if t["port"]]
    southern = [t for t in towns if t["southern"]]
    head = ["seed %s" % seed]
    if origin:
        head.append("origin %s" % origin)
    if profile:
        head.append("profile %s" % profile)
    head.append("layout %s" % m["layout"])
    head.append("%d attempt%s" % (m["attempts"], "" if m["attempts"] == 1 else "s"))
    if seconds is not None:
        head.append("%.0f s" % seconds)
    lines = ["map of %s" % ", ".join(head), "   %d x %d tiles, %d towns" % (m["size"][0], m["size"][1], len(towns))]
    if verified and m.get("start"):
        from .mapgen import FIRST_CAMPAIGN
        lines.append("   Start: %d, %d" % tuple(m["start"]))
        if legends:         # Legends' black-market counter: the maps are built at 0, the start comes after the roads
            lines.append("   " + FIRST_CAMPAIGN)
    lines.append("")
    width = max([len(town_name(t, verified)) for t in towns] + [4])
    kind = max([len(t["script"]) for t in towns] + [4])
    lines.append("   %-*s  %-*s  size  port  southern  military" % (width, "name", kind, "kind"))
    for t in towns:
        lines.append("   %-*s  %-*s  %-4d  %-4s  %-8s  %s" % (
            width, _ascii(town_name(t, verified)), kind, _ascii(t["script"]), t["size"], "yes" if t["port"] else "no",
            "yes" if t["southern"] else "no", "yes" if t["military"] else "no"))
    lines.append("")
    lines.append("ports: %d (southern %d, other %d)" % (len(ports), sum(1 for t in ports if t["southern"]),
                                                       sum(1 for t in ports if not t["southern"])))
    lines.append("towns: %d southern, %d military, size 1/2/3: %d/%d/%d" % (
        len(southern), sum(1 for t in towns if t["military"]), *(sum(1 for t in towns if t["size"] == n) for n in (1, 2, 3))))
    return lines


def _setup_note(info, exact=False):
    """The console note for a run with maps on a setup whose maps nobody checked against the game (Lab.info() or a
    worker's "ready" info: game 1.5.2.3, Legends 19.4.22 and no mod beyond the ones it needs, or the base game with
    every DLC and no mod, see mapgen.verified_setup); None when the setup is the verified one. An info without
    "dlc_complete" counts as not verified for the base game. exact=True (Deserters): the mods must also have the
    versions the maps were checked with. ASCII only."""
    from .mapgen import NOT_VERIFIED, verified_setup
    if verified_setup(info.get("game_version"), info.get("legends_version"), info.get("mods") or [],
                      info.get("dlc_complete", False), exact=exact):
        return None
    return NOT_VERIFIED


def _print_map(profile, origin, seed, svg_path=None, mod_settings=None):
    from . import mapdraw
    from .lab import Lab, big_stack

    def run():
        lab = Lab(profile, mod_settings)
        note = _setup_note(lab.info())
        if note:
            print(note, flush=True)
        # run on through the origin's start: the map then has the start tile (a picture only: without it, as before)
        try:
            return lab, checked_world_map(lab, seed, origin, stop_at="spawn", blackmarket=SEARCH_BLACKMARKET)
        except Exception:
            return lab, checked_world_map(lab, seed, origin)
    lab, out = big_stack(run)
    info = lab.info()
    verified = not _setup_note(info)
    legends = bool(info.get("legends_version"))
    for line in map_report(seed, out["map"], origin, lab.profile, out["seconds"], verified, legends):
        print(line)
    if svg_path:
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(mapdraw.svg(out["map"], verified=verified))
        print("\npicture written to %s" % svg_path)


def _search_for_a_program(args, criteria, mod_settings):
    """--events-json: the search for another program (bbreroll/external_search.py). stdout holds one JSON line per event and
    nothing else. The file named by STOP_FILE_VARIABLE, once it is there, ends the search as a Stop does. Not a line on stdin:
    on Windows a thread waiting on stdin makes every spawned worker hang at its start. When the other program is gone, the
    next event cannot be written, and that ends the search and its workers."""
    stop_file = os.environ.get(STOP_FILE_VARIABLE)

    def on_event(kind, payload):
        sys.stdout.write(json.dumps({"kind": kind, "payload": payload}) + "\n")
        sys.stdout.flush()
    search(args.profile, args.origin, criteria, workers=args.workers, count=args.count, max_seeds=args.max_seeds,
           start=args.start, on_event=on_event, mod_settings=mod_settings,
           should_stop=(lambda: os.path.exists(stop_file)) if stop_file else None,
           near_seeds=args.near_seeds, near_maps=args.near_maps)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m bbseed.search", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=None,
                    help="game setup: legends (default: your installed game with the mods in its data folder), "
                         "vanilla (your installed game without mods), modded (as legends, for mods without Legends)")
    ap.add_argument("--origin", help="origin script name, e.g. trader_scenario (see --list-origins)")
    ap.add_argument("--list-origins", action="store_true", help="list the origins of the profile and exit")
    ap.add_argument("--show", nargs="+", metavar="SEED", help="print the roster of these seeds and exit")
    ap.add_argument("--map", metavar="SEED", help="build the world map of this seed (about 25 s), print its towns and "
                                                  "ports and exit; the origin is trader_scenario unless --origin is given")
    ap.add_argument("--svg", metavar="PATH", help="with --map: also write the map as an SVG picture (north at the top)")
    ap.add_argument("--stars", nargs=2, action="append", metavar=("SLOT", "SPEC"), default=[],
                    help='minimum stars for a roster slot (1, 2, ... or "*"), e.g. --stars 1 "res2 fat2"')
    ap.add_argument("--tier", nargs=2, action="append", metavar=("SLOT", "SPEC"), default=[],
                    help='least stat rolls for a roster slot, against what its background can roll: low/mid/high '
                         'thirds, e.g. --tier 1 "msk:high res:mid"')
    ap.add_argument("--background", nargs=2, action="append", metavar=("SLOT", "IDS"), default=[],
                    help='backgrounds a roster slot may have (1, 2, ... or "any": at least one recruit), e.g. '
                         '--background 3 "hedge_knight swordmaster"')
    ap.add_argument("--ban", action="append", default=[], metavar="TRAIT", help="trait no recruit may have (repeatable)")
    ap.add_argument("--require", action="append", default=[], metavar="TRAIT", help="wanted trait (repeatable)")
    ap.add_argument("--require-mode", choices=("any", "all"), default="any")
    ap.add_argument("--require-slots", type=int, nargs="+", metavar="SLOT", help="only these slots need the wanted traits")
    ap.add_argument("--criteria", metavar="FILE", help="JSON file with BB Reroll's keys: stars_by_slot, banned, required, required_mode")
    ap.add_argument("--ports", type=int, metavar="N", help="map condition: at least N ports (about 25 s per map)")
    ap.add_argument("--ports-south", type=int, metavar="N", help="map condition: at least N southern ports (city states)")
    ap.add_argument("--ports-north", type=int, metavar="N",
                    help="map condition: at least N northern ports (ports in the north band that are not city states)")
    ap.add_argument("--north-band", type=int, metavar="P",
                    help="the north band for --ports-north: the top P percent (1-99) of the map's rows (default 33)")
    ap.add_argument("--towns", action="append", default=[], metavar="TYPE=N",
                    help="map condition: at least N towns of a type (repeatable); types: city_state, military "
                         "(strongholds), size1 (villages), size2 (towns), size3 (cities)")
    ap.add_argument("--mod-setting", action="append", default=[], metavar="MOD:SETTING=VALUE",
                    help="a Mod Options value that differs from the mod's default, e.g. mod_legends:GenderEquality=Disabled; "
                         "also the Map Options, e.g. mod_legends:Settlements=24")
    ap.add_argument("--count", type=int, default=1, help="stop after this many matches (default 1)")
    ap.add_argument("--near", action="store_true", help="print the nearest seed so far and how it differs, while no seed matches")
    ap.add_argument("--near-seeds", type=int, default=None, metavar="N",
                    help="show the nearest seed after N tested seeds (default %d)" % NEAR_SEEDS)
    ap.add_argument("--near-maps", type=int, default=None, metavar="N",
                    help="with a map per seed (map conditions only, or Deserters): after N maps (default %d)" % NEAR_MAPS)
    ap.add_argument("--events-json", action="store_true",
                    help="for another program: one JSON line per search event on stdout; the file named by the environment "
                         "variable BBSEED_STOP_FILE stops the search")
    ap.add_argument("--max-seeds", type=int, default=None, help="give up after testing this many seeds")
    ap.add_argument("--workers", type=int, default=None, help="parallel processes (default: half the CPU threads, at most 8)")
    ap.add_argument("--start", type=int, default=None, help="first seed number (default: random)")
    args = ap.parse_args(argv)

    if args.list_origins:
        return _print_origins(args.profile)
    mod_settings = {}
    for item in args.mod_setting:
        key, _, value = item.partition("=")
        mod_settings[key] = _value(value)
    if args.map:
        return _print_map(args.profile, args.origin or "trader_scenario", args.map, args.svg, mod_settings)
    if args.svg:
        ap.error("--svg goes with --map")
    if not args.origin:
        ap.error("--origin is required")
    if args.show:
        return _print_seed(args.profile, args.origin, args.show, mod_settings)

    criteria = json.load(open(args.criteria, encoding="utf-8")) if args.criteria else {}
    criteria.setdefault("stars_by_slot", {})
    for slot, spec in args.stars:
        criteria["stars_by_slot"][slot] = spec
    criteria.setdefault("tiers_by_slot", {})
    for slot, spec in args.tier:
        criteria["tiers_by_slot"][slot] = spec
    criteria.setdefault("backgrounds_by_slot", {})
    for slot, ids in args.background:
        criteria["backgrounds_by_slot"][slot] = ids
    criteria["banned"] = list(criteria.get("banned") or []) + args.ban
    criteria["required"] = list(criteria.get("required") or []) + args.require
    if args.require or "required_mode" not in criteria:
        criteria["required_mode"] = args.require_mode
    if args.require_slots:
        criteria["required_slots"] = args.require_slots
    from .mapgen import TOWN_TYPE_KEYS
    map_criteria = dict(criteria.get("map") or {})
    for key in ("ports", "ports_south", "ports_north", "north_band"):
        if getattr(args, key) is not None:
            map_criteria[key] = getattr(args, key)
    for item in args.towns:
        kind, _, num = item.partition("=")
        if kind not in TOWN_TYPE_KEYS or not num.strip().isdigit():
            ap.error("--towns %s: use TYPE=N with a type of %s" % (item, ", ".join(TOWN_TYPE_KEYS)))
        map_criteria.setdefault("towns", {})[kind] = int(num)
    criteria["map"] = map_criteria
    try:
        criteria = normalize(criteria)
    except ValueError as e:
        ap.error(str(e))
    if args.events_json:
        return _search_for_a_program(args, criteria, mod_settings)
    print("criteria:", json.dumps(criteria))

    from .lab import describe
    from .mapgen import FIRST_CAMPAIGN, counts
    show_near_seeds = args.near

    noted = []
    setup_info = []         # the first worker's "ready" info

    def on_event(kind, payload):
        if kind == "preparing":
            name, done, total = payload
            if done == total or done % 500 == 0:
                print("reading the game's scripts (first time only): %s %d of %d" % (name, done, total), flush=True)
        elif kind == "ready":
            print("worker %d of %d has loaded the game scripts" % payload[:2], flush=True)
            if not setup_info:
                setup_info.append(payload[2])
            if criteria["map"] is not None and not noted:       # once: every worker reports the same setup
                noted.append(True)
                note = _setup_note(payload[2], exact=args.origin == DESERTERS_SCRIPT)
                if note:
                    print(note, flush=True)
        elif kind == "progress":
            tested, secs, found, odds = payload
            hint = ""
            if odds["chance"]:
                hint = ", about 1 in %s seeds matches" % format(round(1 / odds["chance"]), ",")
            elif odds["never"] and odds["tested"] >= 200:
                hint = ", brother %s never met the criteria" % ", ".join(str(n) for n in odds["never"])
            elif odds.get("never_any") and odds["tested"] >= 200:
                hint = ", no brother had a wanted background yet"
            elif odds.get("never_map") and odds.get("maps", 0) >= MAP_NEVER_MAPS:
                hint = ", no map met the map conditions in %d maps (such maps are rare)" % odds["maps"]
            print("   %d seeds tested, %.1f per second, %d found%s" % (
                tested, tested / secs if secs > 0 else 0, found, hint), flush=True)
        elif kind == "match":
            print("\n*** MATCH: seed %s%s" % (payload["seed"], "" if payload["stable"] else "   (WARNING: not reproducible, do not trust)"))
            for i, bro in enumerate(payload["roster"], 1):
                print("   %d. %s" % (i, describe(bro)))
            extra = _deserters_lines((setup_info[:1] or [{}])[0], FIRST_CAMPAIGN) if args.origin == DESERTERS_SCRIPT else ""
            if extra:
                print(extra)
            if payload.get("map"):       # (a map is built only when there are map conditions)
                band = criteria["map"]["north_band"]
                c = counts(payload["map"], band)
                t = c["towns"]
                print("   map: %d ports (southern %d, northern %d in the top %s %%), %d city states, %d strongholds, "
                      "%d villages, %d towns, %d cities" % (
                          c["ports"], c["ports_south"], c["ports_north"], band,
                          t["city_state"], t["military"], t["size1"], t["size2"], t["size3"]))
            print(flush=True)
        elif kind == "near" and show_near_seeds:
            print("\n*** NEAREST SEED SO FAR: %s, distance %s%s" % (payload["seed"], tuple(payload["distance"]),
                                                                  "" if payload["confirmed"] else ", not checked yet"))
            for d in payload["differences"]:
                print("   %s%s %s: has %s, the condition is %s" % (
                    "brother %d: " % d["slot"] if d["slot"] else "", d["kind"], d["name"], d["have"], d["want"]))
            print(flush=True)
        elif kind == "notice":
            print("NOTE: %s" % payload, flush=True)
        elif kind in ("error", "fatal"):
            print("%s: %s" % (kind.upper(), payload), flush=True)
        elif kind == "finished":
            tested, secs, found, stopped = payload
            print("finished: %d seeds tested in %.0f s, %d match(es)" % (tested, secs, found))

    search(args.profile, args.origin, criteria, workers=args.workers, count=args.count,
           max_seeds=args.max_seeds, start=args.start, on_event=on_event, mod_settings=mod_settings,
           near_seeds=args.near_seeds, near_maps=args.near_maps)


if __name__ == "__main__":
    main()

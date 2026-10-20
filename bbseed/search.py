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
            A map takes about 40 s to build, so it is built only for seeds whose roster meets the rest
            (with map conditions only: for every seed, and the roster only for the maps that meet them).
            The Map Options go in --mod-setting (mod_legends:Settlements=24 ...).

The seeds found are plain campaign seeds: typed into the new-campaign screen of a game
with the same game version, mods and mod settings, they give this roster. They are made
of digits only, so the game's case-sensitive seed text cannot be mistyped.

The world map of a seed (about 40 s): its towns and ports, and with --svg a picture, north at the top:

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
    (with roster conditions: only for the seeds whose roster met them), so its rate is over the maps built. The
    map is made before the second seeding and the roster after it (engine fact 2), so the two are independent.
    With map conditions only, a seed is added with no slot results (its roster has no condition to meet)."""

    def __init__(self, map_wanted=False):
        """map_wanted: the search has map conditions — chance() is None until a map was tested."""
        self.tested = 0
        self.passed = []          # per slot: seeds on which that recruit met his criteria
        self.team = None          # seeds on which the roster met its whole-roster criteria (None: there are none)
        self.map = None           # [maps built, maps that met the map conditions] (None: no map built)
        self.map_wanted = map_wanted

    def add_roster(self, roster, criteria, map=None):
        team = None
        if (criteria.get("backgrounds_by_slot") or {}).get(ANY_BROTHER):
            team = roster_failure(roster, criteria) is None
        self.add([slot_failure(slot, bro, criteria) is None for slot, bro in enumerate(roster, 1)], team, map)

    def add(self, passes, team=None, map=None):
        """One seed: per slot whether that recruit met his criteria, whether the roster met the whole-roster ones
        (None: no such condition), whether its map met the map conditions (None: no map was built for it)."""
        self.tested += 1
        while len(self.passed) < len(passes):
            self.passed.append(0)
        for i, ok in enumerate(passes):
            if ok:
                self.passed[i] += 1
        if team is not None:
            self.team = (self.team or 0) + bool(team)
        if map is not None:
            self._add_map(1, int(bool(map)))

    def _add_map(self, built, passed):
        if self.map is None:
            self.map = [0, 0]
        self.map[0] += built
        self.map[1] += passed

    def merge(self, tested, passed, team=None, map=None):
        self.tested += tested
        while len(self.passed) < len(passed):
            self.passed.append(0)
        for i, n in enumerate(passed):
            self.passed[i] += n
        if team is not None:
            self.team = (self.team or 0) + team
        if map is not None:
            self._add_map(*map)

    def take(self):
        """(tested, passed, team, map) since the last take, and start counting afresh (for the workers)."""
        out = (self.tested, list(self.passed), self.team, None if self.map is None else list(self.map))
        self.tested, self.passed, self.team, self.map = 0, [], None, None
        return out

    def chance(self):
        """Estimated chance that a seed matches, or None before anything was tested (with map conditions: before
        a map was built — a figure without the map factor would be too high)."""
        if not self.tested or (self.map_wanted and self.map is None):
            return None
        p = 1.0
        for n in self.passed:
            p *= n / self.tested
        if self.team is not None:
            p *= self.team / self.tested
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

    def never(self):
        """Slots (1 = first) that have not passed once."""
        return [i + 1 for i, n in enumerate(self.passed) if n == 0]


# ---------------------------------------------------------------------- seeds
def seed_text(n, digits=10):
    return str(n % 10 ** digits).zfill(digits)


# ---------------------------------------------------------------------- workers
# The text of the one "fatal" event a search with map conditions ends with when the lab cannot build maps of this
# game setup (the GUI turns its Map view off for the session when a fatal event starts with it).
MAP_FATAL = "Map conditions do not work with this game setup: "

# Legends' black-market counter (::Const.World.Buildings.Blackmarket, never reset by the game) as it is in the first
# campaign after the game starts. Every map of a search is built so (ruling AD): the sift map and the confirming map
# of a match are then built alike, whatever other maps the worker built in between. Towns and ports do not depend
# on it; only what comes after the roads does.
SEARCH_BLACKMARKET = 0

# The town fields of a map summary that the real game was checked against (CLAUDE.md engine fact 16): the confirming
# map of a match must have the sift map's towns in these.
_STABLE_TOWN_KEYS = ("script", "x", "y", "size", "port", "southern", "military")


def _towns_key(summary):
    return [tuple(t[k] for k in _STABLE_TOWN_KEYS) for t in summary["towns"]]


class _MapsDoNotWork(Exception):
    """The worker could not build a map twice, and never built one: the game setup cannot do map conditions."""


def _make_lab(profile, mod_settings):
    """A search worker's lab (tests replace this)."""
    from .lab import Lab
    return Lab(profile, mod_settings).watch_rolls()      # stat rolls: criteria and results (~1 % slower)


def _worker(index, workers, profile, mod_settings, origin, criteria, start, limit, seeds, out):
    """Tests seeds start + index, start + index + workers, ... (or every workers-th of an
    explicit seed list) and reports to the queue.

    The order per seed: with roster conditions (or none at all) the roster is rolled first on the reused world
    state, and the map (about 40 s) is built only for a roster that meets them; with map conditions only, the map
    first, and the roster only for a map that meets them. Without map conditions no map is built. A seed that meets
    everything is confirmed: its roster rolled again on a new world state (with the perk trees), its map built
    again; "stable" says both are what the sift found. Checked seeds (`seeds`) are rolled on a new world state and
    get everything (a map too, when there are map conditions), whatever fails.

    A map run that fails is an "error" event for that seed and the worker goes on (about 3 in 1,000 Legends seeds
    raise in guaranteeAllBuildingsInSettlements). Only when the worker's first two map runs both fail, without one
    that worked, is it a "fatal" event (MAP_FATAL + the first error) and the worker stops: one bad seed first must
    not end the search."""
    from .lab import LabError, big_stack, without_perks
    from .mapgen import failure as map_failure

    want_map = criteria.get("map")
    map_first = want_map is not None and not roster_conditions(criteria)
    checking = seeds is not None

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
        out.put(("ready", index, lab.info()))
        state = {"tested": 0, "last": time.time(), "maps_work": False, "first_map_error": None}
        odds = Odds()

        def progress():
            out.put(("progress", index, (state["tested"], odds.take())))
            state["tested"], state["last"] = 0, time.time()

        def build_map(seed):
            """The seed's map summary for the sift; None when its run failed (reported). Raises _MapsDoNotWork."""
            try:
                summary = lab.world_map(seed, origin, blackmarket=SEARCH_BLACKMARKET)["map"]
            except LabError as e:
                if state["maps_work"]:
                    out.put(("error", index, str(e)))
                elif state["first_map_error"] is None:
                    state["first_map_error"] = str(e)       # this seed's own, or every seed's: the next one tells
                else:
                    out.put(("fatal", index, MAP_FATAL + state["first_map_error"]))
                    raise _MapsDoNotWork() from e
                return None
            if not state["maps_work"]:
                state["maps_work"] = True
                if state["first_map_error"] is not None:
                    out.put(("error", index, state["first_map_error"]))
            return summary

        def sift(seed):
            """(roster, map summary or None) of a seed to confirm, or None."""
            if map_first:
                summary = build_map(seed)
                if summary is None:
                    return None
                ok = map_failure(summary, want_map) is None
                odds.add([], map=ok)
                if not (ok or checking):
                    return None
                # the sift roll (kept for the stable flag); after a map run the lab builds a new world state anyway
                return lab.roster(seed, origin, fresh=checking), summary
            # sift on the reused world state (fast); an explicit seed is rolled on a fresh one
            roster = lab.roster(seed, origin, fresh=checking)
            ok = first_failure(roster, criteria) is None
            if want_map is None or not (ok or checking):
                odds.add_roster(roster, criteria)
                return (roster, None) if ok or checking else None
            summary = build_map(seed)
            if summary is None:
                odds.add_roster(roster, criteria)
                return None
            map_ok = map_failure(summary, want_map) is None
            odds.add_roster(roster, criteria, map=map_ok)
            return (roster, summary) if (ok and map_ok) or checking else None

        def confirm(seed, roster, summary):
            # the authoritative roll: a newly built world state, as in a new campaign (with the recruits' perk
            # trees, which the sifting roll leaves out); and the map built once more
            confirmed = lab.roster_with_perks(seed, origin)
            confirmed_map = None
            if summary is not None:
                confirmed_map = lab.world_map(seed, origin, blackmarket=SEARCH_BLACKMARKET)["map"]
            progress()                                   # current count when the match shows
            failure = first_failure(confirmed, criteria)
            if failure is None and confirmed_map is not None:
                failure = map_failure(confirmed_map, want_map)
            if checking or failure is None:
                stable = without_perks(confirmed) == without_perks(roster) and (
                    summary is None or _towns_key(confirmed_map) == _towns_key(summary))
                out.put(("match", index, {"seed": seed, "roster": confirmed, "stable": stable, "failure": failure,
                                          "map": confirmed_map}))
            elif first_failure(confirmed, criteria) is not None:
                out.put(("error", index, "seed %s matched only on the reused world state, not on a fresh "
                                         "one — skipped" % seed))
            else:
                out.put(("error", index, "seed %s: its map met the map conditions, but not when it was built "
                                         "again (%s) — skipped" % (seed, failure)))

        try:
            for seed in (seeds[index::workers] if checking else numbered()):
                state["tested"] += 1
                try:
                    found = sift(seed)
                    if found is not None:
                        confirm(seed, *found)
                except LabError as e:
                    out.put(("error", index, str(e)))
                if time.time() - state["last"] >= 1.0:
                    progress()
        except _MapsDoNotWork:
            return
        if state["first_map_error"] is not None and not state["maps_work"]:
            out.put(("error", index, state["first_map_error"]))     # the worker's only map run failed
        progress()
        out.put(("done", index, None))

    big_stack(run)


def search(profile, origin, criteria, workers=None, count=1, max_seeds=None, start=None, on_event=None,
           mod_settings=None, seeds=None, should_stop=None):
    """Run the search; returns the list of matches.

    on_event(kind, payload) receives: "preparing" (archive name, scripts done, scripts total —
    only the first time a game version is used: its scripts are read once and cached),
    "ready" (workers loaded, workers total, setup info),
    "progress" (seeds tested, seconds, matches, odds: {"chance": estimated chance a seed matches,
    "never": [roster slots that have not met their criteria once], "never_any": the "any brother" backgrounds
    have not been met once, "never_map": maps were built and none met the map conditions, "maps": maps built,
    "tested"}),
    "match" (dict: seed, roster, stable, failure, map: the map summary (mapgen.summary) when there are map
    conditions, else None),
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
    ctx = mp.get_context("spawn")
    out = ctx.Queue()
    procs = [ctx.Process(target=_worker, daemon=True,
                         args=(i, workers, profile, mod_settings, origin, criteria, start, max_seeds, seeds, out))
             for i in range(workers)]
    for p in procs:
        p.start()
    matches, tested, running, t0, ready, stopped = [], 0, workers, None, 0, False
    odds = Odds(map_wanted=criteria["map"] is not None)
    try:
        while running and len(matches) < count:
            if should_stop is not None and should_stop():
                stopped = True
                break
            try:
                kind, index, payload = out.get(timeout=0.25)
            except queue.Empty:
                continue
            if kind == "ready":
                ready += 1
                if t0 is None:
                    t0 = time.time()
                emit("ready", (ready, workers, payload))
            elif kind == "progress":
                tested += payload[0]
                odds.merge(*payload[1])
                emit("progress", (tested, time.time() - (t0 or time.time()), len(matches),
                                  {"chance": odds.chance(), "never": odds.never(), "never_any": odds.team_never(),
                                   "never_map": odds.map_never(), "maps": odds.maps(), "tested": odds.tested}))
            elif kind == "match":
                matches.append(payload)
                emit("match", payload)
            elif kind == "error":
                emit("error", payload)
            elif kind in ("done", "fatal"):
                running -= 1
                if kind == "fatal":
                    emit("fatal", payload)
                    if payload.startswith(MAP_FATAL):      # no worker can build a map: nothing can match
                        break
    finally:
        for p in procs:
            if p.is_alive():
                p.terminate()
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
        for seed in seeds:
            print("seed %s, origin %s:" % (seed, origin))
            for i, bro in enumerate(lab.roster_with_perks(seed, origin), 1):
                print("   %d. %s" % (i, describe(bro)))
    big_stack(run)


def _ascii(text):
    """The console here is cp1252: names with other characters are printed with '?' in their place."""
    return str(text).encode("ascii", "replace").decode()


def map_report(seed, m, origin=None, profile=None, seconds=None):
    """A map summary (mapgen.summary) as text lines for the console: the towns (name, kind = the settlement's script,
    size, port, southern, military) and the port counts. ASCII only."""
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
    lines = ["map of %s" % ", ".join(head), "   %d x %d tiles, %d towns" % (m["size"][0], m["size"][1], len(towns)), ""]
    width = max([len(t["name"]) for t in towns] + [4])
    kind = max([len(t["script"]) for t in towns] + [4])
    lines.append("   %-*s  %-*s  size  port  southern  military" % (width, "name", kind, "kind"))
    for t in towns:
        lines.append("   %-*s  %-*s  %-4d  %-4s  %-8s  %s" % (
            width, _ascii(t["name"]), kind, _ascii(t["script"]), t["size"], "yes" if t["port"] else "no",
            "yes" if t["southern"] else "no", "yes" if t["military"] else "no"))
    lines.append("")
    lines.append("ports: %d (southern %d, other %d)" % (len(ports), sum(1 for t in ports if t["southern"]),
                                                       sum(1 for t in ports if not t["southern"])))
    lines.append("towns: %d southern, %d military, size 1/2/3: %d/%d/%d" % (
        len(southern), sum(1 for t in towns if t["military"]), *(sum(1 for t in towns if t["size"] == n) for n in (1, 2, 3))))
    return lines


def _print_map(profile, origin, seed, svg_path=None, mod_settings=None):
    from . import mapdraw
    from .lab import Lab, big_stack

    def run():
        lab = Lab(profile, mod_settings)
        return lab, lab.world_map(seed, origin)
    lab, out = big_stack(run)
    for line in map_report(seed, out["map"], origin, lab.profile, out["seconds"]):
        print(line)
    if svg_path:
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(mapdraw.svg(out["map"]))
        print("\npicture written to %s" % svg_path)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m bbseed.search", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=None,
                    help="game setup: legends (default: your installed game with the mods in its data folder), "
                         "vanilla (your installed game without mods), modded (as legends, for mods without Legends)")
    ap.add_argument("--origin", help="origin script name, e.g. trader_scenario (see --list-origins)")
    ap.add_argument("--list-origins", action="store_true", help="list the origins of the profile and exit")
    ap.add_argument("--show", nargs="+", metavar="SEED", help="print the roster of these seeds and exit")
    ap.add_argument("--map", metavar="SEED", help="build the world map of this seed (about 40 s), print its towns and "
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
    ap.add_argument("--ports", type=int, metavar="N", help="map condition: at least N ports (about 40 s per map)")
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
    print("criteria:", json.dumps(criteria))

    from .lab import describe
    from .mapgen import counts

    def on_event(kind, payload):
        if kind == "preparing":
            name, done, total = payload
            if done == total or done % 500 == 0:
                print("reading the game's scripts (first time only): %s %d of %d" % (name, done, total), flush=True)
        elif kind == "ready":
            print("worker %d of %d has loaded the game scripts" % payload[:2], flush=True)
        elif kind == "progress":
            tested, secs, found, odds = payload
            hint = ""
            if odds["chance"]:
                hint = ", about 1 in %s seeds matches" % format(round(1 / odds["chance"]), ",")
            elif odds["never"] and odds["tested"] >= 200:
                hint = ", brother %s never met the criteria" % ", ".join(str(n) for n in odds["never"])
            elif odds.get("never_any") and odds["tested"] >= 200:
                hint = ", no brother had a wanted background yet"
            elif odds.get("never_map") and odds.get("maps", 0) >= 20:
                hint = ", no map met the map conditions yet (%d maps)" % odds["maps"]
            print("   %d seeds tested, %.1f per second, %d found%s" % (
                tested, tested / secs if secs > 0 else 0, found, hint), flush=True)
        elif kind == "match":
            print("\n*** MATCH: seed %s%s" % (payload["seed"], "" if payload["stable"] else "   (WARNING: not reproducible, do not trust)"))
            for i, bro in enumerate(payload["roster"], 1):
                print("   %d. %s" % (i, describe(bro)))
            if payload.get("map"):       # (a map is built only when there are map conditions)
                band = criteria["map"]["north_band"]
                c = counts(payload["map"], band)
                t = c["towns"]
                print("   map: %d ports (southern %d, northern %d in the top %s %%), %d city states, %d strongholds, "
                      "%d villages, %d towns, %d cities" % (
                          c["ports"], c["ports_south"], c["ports_north"], band,
                          t["city_state"], t["military"], t["size1"], t["size2"], t["size3"]))
            print(flush=True)
        elif kind in ("error", "fatal"):
            print("%s: %s" % (kind.upper(), payload), flush=True)
        elif kind == "finished":
            tested, secs, found, stopped = payload
            print("finished: %d seeds tested in %.0f s, %d match(es)" % (tested, secs, found))

    search(args.profile, args.origin, criteria, workers=args.workers, count=args.count,
           max_seeds=args.max_seeds, start=args.start, on_event=on_event, mod_settings=mod_settings)


if __name__ == "__main__":
    main()

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

The seeds found are plain campaign seeds: typed into the new-campaign screen of a game
with the same game version, mods and mod settings, they give this roster. They are made
of digits only, so the game's case-sensitive seed text cannot be mistyped.
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


def normalize(criteria):
    """Accepts BB Reroll's config dict (stars_by_slot / banned / required / required_mode)."""
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
    A condition on the roster as a whole ("any" backgrounds) counts as one more factor."""

    def __init__(self):
        self.tested = 0
        self.passed = []          # per slot: seeds on which that recruit met his criteria
        self.team = None          # seeds on which the roster met its whole-roster criteria (None: there are none)

    def add_roster(self, roster, criteria):
        team = None
        if (criteria.get("backgrounds_by_slot") or {}).get(ANY_BROTHER):
            team = roster_failure(roster, criteria) is None
        self.add([slot_failure(slot, bro, criteria) is None for slot, bro in enumerate(roster, 1)], team)

    def add(self, passes, team=None):
        self.tested += 1
        while len(self.passed) < len(passes):
            self.passed.append(0)
        for i, ok in enumerate(passes):
            if ok:
                self.passed[i] += 1
        if team is not None:
            self.team = (self.team or 0) + bool(team)

    def merge(self, tested, passed, team=None):
        self.tested += tested
        while len(self.passed) < len(passed):
            self.passed.append(0)
        for i, n in enumerate(passed):
            self.passed[i] += n
        if team is not None:
            self.team = (self.team or 0) + team

    def take(self):
        """(tested, passed, team) since the last take, and start counting afresh (for the workers)."""
        out = (self.tested, list(self.passed), self.team)
        self.tested, self.passed, self.team = 0, [], None
        return out

    def chance(self):
        """Estimated chance that a seed matches, or None before anything was tested."""
        if not self.tested:
            return None
        p = 1.0
        for n in self.passed:
            p *= n / self.tested
        if self.team is not None:
            p *= self.team / self.tested
        return p

    def team_never(self):
        """The whole-roster criteria have not been met once."""
        return self.team == 0

    def never(self):
        """Slots (1 = first) that have not passed once."""
        return [i + 1 for i, n in enumerate(self.passed) if n == 0]


# ---------------------------------------------------------------------- seeds
def seed_text(n, digits=10):
    return str(n % 10 ** digits).zfill(digits)


# ---------------------------------------------------------------------- workers
def _worker(index, workers, profile, mod_settings, origin, criteria, start, limit, seeds, out):
    """Tests seeds start + index, start + index + workers, ... (or every workers-th of an
    explicit seed list) and reports to the queue."""
    from .lab import Lab, LabError, big_stack, without_perks

    def numbered():
        n = start + index
        while limit is None or n < start + limit:
            yield seed_text(n)
            n += workers

    def run():
        try:
            lab = Lab(profile, mod_settings).watch_rolls()      # stat rolls: criteria and results (~1 % slower)
        except Exception as e:
            out.put(("fatal", index, "%s: %s" % (type(e).__name__, e)))
            return
        out.put(("ready", index, lab.info()))
        tested, last, odds = 0, time.time(), Odds()
        for seed in (seeds[index::workers] if seeds is not None else numbered()):
            tested += 1
            try:
                # sift on the reused world state (fast); an explicit seed is rolled on a fresh one
                roster = lab.roster(seed, origin, fresh=seeds is not None)
                odds.add_roster(roster, criteria)
                failure = first_failure(roster, criteria)
                if failure is None or seeds is not None:
                    # the authoritative roll: a newly built world state, as in a new campaign (with the
                    # recruits' perk trees, which the sifting roll leaves out)
                    confirmed = lab.roster_with_perks(seed, origin)
                    out.put(("progress", index, (tested, odds.take())))     # current count when the match shows
                    tested, last = 0, time.time()
                    if seeds is not None or first_failure(confirmed, criteria) is None:
                        stable = without_perks(confirmed) == without_perks(roster)
                        out.put(("match", index, {"seed": seed, "roster": confirmed, "stable": stable,
                                                  "failure": first_failure(confirmed, criteria)}))
                    else:
                        out.put(("error", index, "seed %s matched only on the reused world state, not on a fresh "
                                                 "one — skipped" % seed))
            except LabError as e:
                out.put(("error", index, str(e)))
            if time.time() - last >= 1.0:
                out.put(("progress", index, (tested, odds.take())))
                tested, last = 0, time.time()
        out.put(("progress", index, (tested, odds.take())))
        out.put(("done", index, None))

    big_stack(run)


def search(profile, origin, criteria, workers=None, count=1, max_seeds=None, start=None, on_event=None,
           mod_settings=None, seeds=None, should_stop=None):
    """Run the search; returns the list of matches.

    on_event(kind, payload) receives: "preparing" (archive name, scripts done, scripts total —
    only the first time a game version is used: its scripts are read once and cached),
    "ready" (workers loaded, workers total, setup info),
    "progress" (seeds tested, seconds, matches, odds: {"chance": estimated chance a seed matches,
    "never": [roster slots that have not met their criteria once], "tested"}),
    "match" (dict: seed, roster, stable, failure),
    "error" / "fatal" (text), "finished" (seeds tested, seconds, matches, stopped early?).
    seeds: test exactly these seed texts and report every one of them (with the criterion it
    fails, if any) instead of searching. should_stop(): polled; return True to end the search.
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
    odds = Odds()
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
                                   "tested": odds.tested}))
            elif kind == "match":
                matches.append(payload)
                emit("match", payload)
            elif kind == "error":
                emit("error", payload)
            elif kind in ("done", "fatal"):
                running -= 1
                if kind == "fatal":
                    emit("fatal", payload)
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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m bbseed.search", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=None,
                    help="game setup: legends (default: your installed game with the mods in its data folder), "
                         "vanilla (your installed game without mods), modded (as legends, for mods without Legends)")
    ap.add_argument("--origin", help="origin script name, e.g. trader_scenario (see --list-origins)")
    ap.add_argument("--list-origins", action="store_true", help="list the origins of the profile and exit")
    ap.add_argument("--show", nargs="+", metavar="SEED", help="print the roster of these seeds and exit")
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
    ap.add_argument("--mod-setting", action="append", default=[], metavar="MOD:SETTING=VALUE",
                    help="a Mod Options value that differs from the mod's default, e.g. mod_legends:GenderEquality=Disabled")
    ap.add_argument("--count", type=int, default=1, help="stop after this many matches (default 1)")
    ap.add_argument("--max-seeds", type=int, default=None, help="give up after testing this many seeds")
    ap.add_argument("--workers", type=int, default=None, help="parallel processes (default: half the CPU threads, at most 8)")
    ap.add_argument("--start", type=int, default=None, help="first seed number (default: random)")
    args = ap.parse_args(argv)

    if args.list_origins:
        return _print_origins(args.profile)
    if not args.origin:
        ap.error("--origin is required")
    mod_settings = {}
    for item in args.mod_setting:
        key, _, value = item.partition("=")
        mod_settings[key] = _value(value)
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
    criteria = normalize(criteria)
    print("criteria:", json.dumps(criteria))

    from .lab import describe

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
            print("   %d seeds tested, %.1f per second, %d found%s" % (
                tested, tested / secs if secs > 0 else 0, found, hint), flush=True)
        elif kind == "match":
            print("\n*** MATCH: seed %s%s" % (payload["seed"], "" if payload["stable"] else "   (WARNING: not reproducible, do not trust)"))
            for i, bro in enumerate(payload["roster"], 1):
                print("   %d. %s" % (i, describe(bro)))
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

"""Find campaign seeds whose starting roster meets your criteria — without the game.

    python -m bbseed.search --profile legends --origin trader_scenario ^
        --stars 1 "res2 fat2" --ban dumb --ban fat --workers 8 --count 3

Criteria follow BB Reroll's model (and its config keys, see --criteria):
  stars     minimum talent stars, e.g. "msk2 mdf2", per roster slot (1 = first recruit);
            "*" is the rule for every recruit that has no row of its own (a slot's row
            replaces "*" for that recruit, it is not added to it).
            Stats: hp fat res init msk rsk mdf rdf
  banned    no recruit may have any of these traits
  required  every recruit must have at least one of these traits (mode "any")
            or all of them (mode "all"); limit it to some slots with --require-slots

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


def _trait(t):
    return t[6:] if t.startswith("trait.") else t


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
    return {
        "stars_by_slot": stars,
        "banned": sorted({_trait(t) for t in criteria.get("banned") or ()}),
        "required": sorted({_trait(t) for t in criteria.get("required") or ()}),
        "required_mode": mode,
        "required_slots": sorted(int(s) for s in slots) if slots else None,
    }


def first_failure(roster, criteria):
    """None if the roster meets the (normalized) criteria, else a short reason."""
    banned = set(criteria["banned"])
    required = set(criteria["required"])
    stars = criteria["stars_by_slot"]
    for slot, bro in enumerate(roster, 1):
        # a slot's own row replaces the "*" row (BB Reroll's rule since the in-game search;
        # origin_hardcoded_stars.conflicts() checks the same way)
        need = stars.get(str(slot)) or stars.get("*", {})
        for stat, minimum in need.items():
            if bro["stars"][stat] < minimum:
                return "bro%d %s*%d<%d" % (slot, stat, bro["stars"][stat], minimum)
        traits = set(bro["traits"])
        hit = traits & banned
        if hit:
            return "bro%d banned %s" % (slot, sorted(hit)[0])
        if required and (criteria["required_slots"] is None or slot in criteria["required_slots"]):
            if criteria["required_mode"] == "all":
                missing = required - traits
                if missing:
                    return "bro%d missing %s" % (slot, sorted(missing)[0])
            elif not traits & required:
                return "bro%d no_good_trait" % slot
    for slot in criteria["stars_by_slot"]:
        if slot != "*" and int(slot) > len(roster):
            return "no bro%s in this origin's roster" % slot
    return None


# ---------------------------------------------------------------------- seeds
def seed_text(n, digits=10):
    return str(n % 10 ** digits).zfill(digits)


# ---------------------------------------------------------------------- workers
def _worker(index, workers, profile, mod_settings, origin, criteria, start, limit, seeds, out):
    """Tests seeds start + index, start + index + workers, ... (or every workers-th of an
    explicit seed list) and reports to the queue."""
    from .lab import Lab, LabError, big_stack

    def numbered():
        n = start + index
        while limit is None or n < start + limit:
            yield seed_text(n)
            n += workers

    def run():
        try:
            lab = Lab(profile, mod_settings)
        except Exception as e:
            out.put(("fatal", index, "%s: %s" % (type(e).__name__, e)))
            return
        out.put(("ready", index, lab.info()))
        tested, last = 0, time.time()
        for seed in (seeds[index::workers] if seeds is not None else numbered()):
            tested += 1
            try:
                # sift on the reused world state (fast); an explicit seed is rolled on a fresh one
                roster = lab.roster(seed, origin, fresh=seeds is not None)
                failure = first_failure(roster, criteria)
                if failure is None or seeds is not None:
                    # the authoritative roll: a newly built world state, as in a new campaign
                    confirmed = lab.roster(seed, origin, fresh=True)
                    out.put(("progress", index, tested))        # so the count is current when the match shows
                    tested, last = 0, time.time()
                    if seeds is not None or first_failure(confirmed, criteria) is None:
                        out.put(("match", index, {"seed": seed, "roster": confirmed, "stable": confirmed == roster,
                                                  "failure": first_failure(confirmed, criteria)}))
                    else:
                        out.put(("error", index, "seed %s matched only on the reused world state, not on a fresh "
                                                 "one — skipped" % seed))
            except LabError as e:
                out.put(("error", index, str(e)))
            if time.time() - last >= 1.0:
                out.put(("progress", index, tested))
                tested, last = 0, time.time()
        out.put(("progress", index, tested))
        out.put(("done", index, None))

    big_stack(run)


def search(profile, origin, criteria, workers=None, count=1, max_seeds=None, start=None, on_event=None,
           mod_settings=None, seeds=None, should_stop=None):
    """Run the search; returns the list of matches.

    on_event(kind, payload) receives: "preparing" (archive name, scripts done, scripts total —
    only the first time a game version is used: its scripts are read once and cached),
    "ready" (workers loaded, workers total, setup info),
    "progress" (seeds tested, seconds, matches), "match" (dict: seed, roster, stable, failure),
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
                tested += payload
                emit("progress", (tested, time.time() - (t0 or time.time()), len(matches)))
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
        lab = Lab(profile, mod_settings)
        for seed in seeds:
            print("seed %s, origin %s:" % (seed, origin))
            for i, bro in enumerate(lab.roster(seed, origin), 1):
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
            tested, secs, found = payload
            print("   %d seeds tested, %.1f per second, %d found" % (tested, tested / secs if secs > 0 else 0, found), flush=True)
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

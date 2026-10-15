"""What the installed game's scripts say about its origins and traits: the origins the
new-campaign menu offers, per origin and brother slot the talent stars the roster can have at
all (see talents.py), and what every trait does (see traits.py). Worked out once per game
setup — game version, mod zips, recruit-related Mod Options — by rolling seeds in parallel
worker processes, and kept next to the script cache:

    python -m bbseed.catalog --profile legends --workers 8

A catalog is a JSON file; load() returns None when there is none for the installed game yet
(or the game, a mod or a setting changed since): build() makes it.
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import os
import queue
import time
from pathlib import Path

from . import gamedata, profiles

CATALOG_VERSION = 5

# not surveyed: the tutorial and the random-origin picker are not origins of their own; Deserters
# creates its recruits only after the map exists (see bbreroll/offline_origins.NOT_SEARCHABLE)
SKIP = {"tutorial_scenario", "random_scenario", "deserters_scenario"}


def _key(profile, mod_settings):
    roots, version = profiles.get(profile)
    parts = [CATALOG_VERSION, profile or profiles.DEFAULT, version, sorted((mod_settings or {}).items())]
    for root in roots:
        p = Path(root)
        st = p.stat()
        parts.append([p.name, st.st_size, st.st_mtime_ns])
    return hashlib.sha1(json.dumps(parts, default=str).encode()).hexdigest()[:16]


def path(profile=None, mod_settings=None):
    """Where the catalog of this setup is (or will be) kept."""
    return gamedata.cache_dir() / "catalog" / ("%s-%s.json" % (profile or profiles.DEFAULT, _key(profile, mod_settings)))


def load(profile=None, mod_settings=None):
    """The catalog of the installed setup, or None if it has not been built yet."""
    try:
        data = json.loads(path(profile, mod_settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if data.get("version") == CATALOG_VERSION else None


def _worker(index, profile, mod_settings, tasks, out):
    from .lab import Lab, LabError, big_stack
    from .talents import TalentWatch, survey

    def run():
        try:
            lab = Lab(profile, mod_settings)
        except Exception as e:
            out.put(("fatal", index, "%s: %s" % (type(e).__name__, e)))
            return
        if index == 0:
            from .traits import tooltips
            try:
                traits = tooltips(lab)
            except Exception as e:          # the rest of the catalog is still worth having
                traits = {"_error": "%s: %s" % (type(e).__name__, e)}
            out.put(("origins", index, {"origins": [list(o) for o in lab.origins()], "info": lab.info(),
                                        "traits": traits}))
        out.put(("ready", index, None))
        lab.watch_rolls()               # which stats each slot's base roll can move
        watch = TalentWatch(lab)
        while True:
            script = tasks.get()
            if script is None:
                break
            t = time.time()
            try:
                result = survey(watch, script)
            except LabError as e:
                result = {"error": str(e)[:500]}
            result["seconds"] = round(time.time() - t, 1)
            out.put(("talents", index, (script, result)))
        out.put(("done", index, None))

    big_stack(run)


def build(profile=None, mod_settings=None, workers=None, on_event=None, should_stop=None):
    """Work the catalog out and save it; returns it (None if stopped or the game could not be
    loaded). on_event(kind, payload): "preparing" (archive, done, total — the first use of a game
    version), "ready" (workers ready, workers), "origin" (origins done, origins total, script),
    "fatal" (text)."""
    emit = on_event or (lambda kind, payload: None)
    workers = workers or max(1, min(8, (os.cpu_count() or 2) // 2))
    try:
        profiles.get(profile, on_progress=lambda name, done, total: emit("preparing", (name, done, total)))
        target = path(profile, mod_settings)
    except (FileNotFoundError, KeyError, OSError) as e:
        emit("fatal", "%s" % (e.args[0] if e.args else e))
        return None
    ctx = mp.get_context("spawn")
    tasks, out = ctx.Queue(), ctx.Queue()
    procs = [ctx.Process(target=_worker, daemon=True, args=(i, profile, mod_settings, tasks, out))
             for i in range(workers)]
    for p in procs:
        p.start()
    catalog = {"version": CATALOG_VERSION, "profile": profile or profiles.DEFAULT, "mod_settings": mod_settings or {},
               "built": time.strftime("%Y-%m-%d %H:%M:%S"), "origins": None, "info": None, "traits": {},
               "talents": {}}
    pending, ready, running = None, 0, workers
    try:
        while running and (pending is None or pending):
            if should_stop is not None and should_stop():
                return None
            try:
                kind, index, payload = out.get(timeout=0.25)
            except queue.Empty:
                continue
            if kind == "origins":
                catalog["origins"] = payload["origins"]
                catalog["info"] = payload["info"]
                catalog["traits"] = payload["traits"]
                pending = {o[0] for o in payload["origins"]} - SKIP
                for script, _sid, _title in payload["origins"]:
                    if script in pending:
                        tasks.put(script)
                for _ in procs:
                    tasks.put(None)
            elif kind == "ready":
                ready += 1
                emit("ready", (ready, workers))
            elif kind == "talents":
                script, result = payload
                catalog["talents"][script] = result
                if pending is not None:
                    pending.discard(script)
                    emit("origin", (len(catalog["talents"]), len(catalog["talents"]) + len(pending), script))
            elif kind == "fatal":
                emit("fatal", payload)
                return None
            elif kind == "done":
                running -= 1
    finally:
        for p in procs:
            if p.is_alive():
                p.terminate()
    if catalog["origins"] is None or pending:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(catalog, indent=1), encoding="utf-8")
    os.replace(tmp, target)
    return catalog


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m bbseed.catalog", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=None)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--mod-setting", action="append", default=[], metavar="MOD:SETTING=VALUE")
    ap.add_argument("--rebuild", action="store_true", help="build it even if there is one")
    args = ap.parse_args(argv)
    from .search import _value
    mod_settings = {}
    for item in args.mod_setting:
        key, _, value = item.partition("=")
        mod_settings[key] = _value(value)
    catalog = None if args.rebuild else load(args.profile, mod_settings)
    if catalog is None:
        t = time.time()

        def on_event(kind, payload):
            if kind == "origin":
                print("  %d of %d origins: %s" % payload, flush=True)
            elif kind == "fatal":
                print("FATAL:", payload, flush=True)
        catalog = build(args.profile, mod_settings, workers=args.workers, on_event=on_event)
        if catalog is None:
            return 1
        print("built in %.0f s: %s" % (time.time() - t, path(args.profile, mod_settings)))
    for script, sid, title in catalog["origins"]:
        found = catalog["talents"].get(script)
        if found is None:
            continue
        if "error" in found:
            print("%-36s ERROR %s" % (script, found["error"][:120]))
            continue
        print("%-36s %s (%d samples)" % (script, title, found["samples"]))
        for i, slot in enumerate(found["slots"], 1):
            never = [s for s, top in slot["max"].items() if top == 0]
            print("     %2d: up to %d stats with stars (%d rolled)  fixed %s  never %s" % (
                i, slot["most"], slot["picks"], slot["fixed"] or "-", " ".join(never) or "-"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

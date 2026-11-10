"""The optional PyPy download for map searches: a folder bb_reroll_pypy next to the exe, with PyPy and this version's bbseed.
PyPy builds maps about 2.7 times as fast (MODLOG "PYPY MAP SEARCH"), but loses on rosters and takes 1.5 GB per worker, so it
runs only the searches that build a map per seed. No tkinter. tools/build_pypy_addon.py makes the zip.

    bb_reroll_pypy\\pypy\\pypy3.exe     PyPy
    bb_reroll_pypy\\bbseed\\            the search, of exactly this BB Reroll version
    bb_reroll_pypy\\VERSION             that version

find(exe_dir, version) -> (Addon or None, reason): the reason says why a folder that is there cannot be used ("" when there
is no folder, or when it can). The window then says it, and the search runs in the exe's own Python.
"""
import atexit
import json
import os
import tempfile
from pathlib import Path

from bbreroll import external_search
from bbseed.search import DESERTERS_SCRIPT, normalize, roster_conditions

FOLDER = "bb_reroll_pypy"
NURSERY = "2M"              # PYPY_GC_NURSERY: Windows' default of 4 MB is 0.6 times as fast on 8 workers (measured 2026-11-02)
MEMORY_TEXT = "about 1.5 GB"
SWITCH_TEXT = "Search with PyPy"
SWITCH_TIP = ("PyPy builds maps about 2.7 times as fast. It uses %s of memory for each worker. It is used only when the "
              "search needs a map for each seed: map conditions and no condition on the brothers (a ticked trait is a "
              "condition), or Deserters." % MEMORY_TEXT)
OTHER_VERSION = "The %s folder is for BB Reroll %s, and this is %s. BB Reroll does not use it. Download the file for this version."
DAMAGED = "The %s folder is damaged: %s is missing. BB Reroll does not use it. Download the file again."
NO_START = "PyPy did not start: %s. The search runs without PyPy."
_NEEDED = (("pypy", "pypy3.exe"), ("pypy", "libpypy3.11-c.dll"), ("bbseed", "search.py"), ("bbseed", "lab.py"),
           ("bbseed", "native_surface.json"))


class Addon:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.python = self.folder / "pypy" / "pypy3.exe"

    def command(self, args):
        """The command line of `python -m bbseed.search` + args."""
        return [str(self.python), "-m", "bbseed.search"] + list(args)

    def env(self):
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY")}
        env.update(PYPY_GC_NURSERY=NURSERY, PYTHONPATH=str(self.folder), PYTHONIOENCODING="utf-8")
        return env


def find(exe_dir, version):
    folder = Path(exe_dir) / FOLDER
    if not folder.is_dir():
        return None, ""
    for parts in _NEEDED:
        if not folder.joinpath(*parts).is_file():
            return None, DAMAGED % (FOLDER, "\\".join(parts))
    try:
        found = (folder / "VERSION").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None, DAMAGED % (FOLDER, "VERSION")
    if found != version:
        return None, OTHER_VERSION % (FOLDER, found or "(unknown)", version)
    return Addon(folder), ""


def applies(criteria, origin):
    """A map per seed: map conditions with no roster conditions, or Deserters. Every other search rolls rosters most of the
    time, and PyPy is slower at that."""
    if origin == DESERTERS_SCRIPT:
        return True
    normal = normalize(criteria)
    return normal["map"] is not None and not roster_conditions(normal)


def arguments(profile, origin, criteria_path, workers, count, max_seeds, mod_settings, start=None, near_seeds=None,
              near_maps=None):
    """The arguments of a search as bbseed.search's command line takes them."""
    args = ["--events-json", "--origin", origin, "--criteria", str(criteria_path), "--workers", str(workers), "--count", str(count)]
    if profile:
        args += ["--profile", profile]
    if max_seeds:
        args += ["--max-seeds", str(max_seeds)]
    if start is not None:
        args += ["--start", str(start)]
    if near_seeds is not None:
        args += ["--near-seeds", str(near_seeds)]
    if near_maps is not None:
        args += ["--near-maps", str(near_maps)]
    for key, value in (mod_settings or {}).items():
        args += ["--mod-setting", "%s=%s" % (key, value)]
    return args


def search(addon, profile, origin, criteria, workers, count, max_seeds, mod_settings, on_event, should_stop=None, start=None,
           near_seeds=None, near_maps=None):
    """The search in PyPy, with the events of bbseed.search.search(). None when it ran. Else the text why PyPy did not start: no
    event has reached the caller then, except "preparing", and the caller searches on in its own Python. A child that ends
    before its workers are ready counts as not started, unless the player pressed Stop."""
    handle, path = tempfile.mkstemp(prefix="bb_reroll_search_", suffix=".json")
    held = []
    state = {"ready": False}

    def remove_file():
        try:
            os.unlink(path)
        except OSError:
            pass
    atexit.register(remove_file)    # (the search's thread is a daemon: its `finally` does not run when the program ends)

    def relay(kind, payload):
        if kind == "ready":
            state["ready"] = True
        if state["ready"] or kind == "preparing":
            on_event(kind, payload)
        else:
            held.append((kind, payload))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            json.dump(criteria, f)
        args = arguments(profile, origin, path, workers, count, max_seeds, mod_settings, start, near_seeds, near_maps)
        try:
            external_search.run(addon.command(args), addon.env(), relay, should_stop, cwd=str(addon.folder))
        except external_search.CannotStart as e:
            return NO_START % e
    finally:
        atexit.unregister(remove_file)
        remove_file()
    stopped = should_stop is not None and should_stop()
    fatal = next((payload for kind, payload in held if kind == "fatal"), None)
    if not state["ready"] and fatal is not None and not stopped:
        return NO_START % fatal
    for kind, payload in held:
        on_event(kind, payload)
    return None

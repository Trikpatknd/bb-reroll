"""Which script roots make up a game setup ("profile").

The scripts themselves are never part of this project: they are read where the player's
game has them, nothing extracted.

  vanilla  the installed base game alone (its compiled scripts inside data_*.dat)
  legends  the installed game with the mods in its data folder — Legends and whatever
           else is there, in the versions the game itself would load
  modded   the same, for a game whose mods do not include Legends

BB Reroll's own in-game mod (mod_bb_reroll*.zip) is never loaded: it re-seeds every
campaign start, so a game that has it rolls different recruits. The seeds found here are
for the game without it.

Research profiles (pinned copies of game and mod sources, kept outside the repo) can be
described in a `profiles.json` in the folder the environment variable BBSEED_DATA names:

  {"base": ["vanilla-1.5.2.3-fixes", "vanilla-1.5.2.3"],
   "profiles": {"research-legends": {"roots": ["msu-1.9.0", "legends-19.4.22", "@base"],
                                     "game_version": "1.5.2.3"}}}

Folders are relative to that data folder, highest priority first. "@base" stands for the
base game: the "base" folders (an extracted source-text copy), or — with BBSEED_BASE=game,
or when no "base" is given — the installed game's own compiled scripts.
"""
import json
import os
import zipfile
from pathlib import Path

DEFAULT = "legends"
INSTALLED = ("vanilla", "legends", "modded")
FALLBACK_VERSION = "1.5.2.3"        # reported to scripts when the game's exe does not tell its version
BASE = "@base"


def game_data_dir():
    """The game's data folder (see gamedata.game_data_dir), or None."""
    from . import gamedata
    return gamedata.game_data_dir()


def _data(game_data):
    data = Path(game_data) if game_data else game_data_dir()
    if data is None:
        raise FileNotFoundError("Battle Brothers was not found (set BBSEED_GAME_DATA to the game folder)")
    return data


def _is_reroll_mod(path):
    return "bb_reroll" in path.name.lower()


def _zips(data):
    return sorted((z for z in data.glob("*.zip") if zipfile.is_zipfile(z)), key=lambda z: z.name.lower())


def mod_zips(data):
    """The mod archives in the game's data folder, in the order the game mounts them (by
    name), without BB Reroll's own in-game mod. A file that is not a readable zip is left
    out (what the game does with one is not known; it cannot contribute scripts either way)."""
    return [z for z in _zips(data) if not _is_reroll_mod(z)]


def reroll_mod_zips(data):
    """BB Reroll's in-game mod, if it is installed in the game's data folder. While it is,
    the game itself rolls different recruits for every seed."""
    return [z for z in _zips(data) if _is_reroll_mod(z)]


def _has_legends(zips):
    for z in zips:
        try:
            with zipfile.ZipFile(z) as archive:
                if any(n.startswith("mod_legends/") for n in archive.namelist()):
                    return True
        except (OSError, zipfile.BadZipFile):
            pass
    return False


def vanilla(game_data=None, on_progress=None):
    """The installed base game alone: what a player without mods has."""
    from . import gamedata
    data = _data(game_data)
    return gamedata.base_roots(data, on_progress), gamedata.game_version(data) or FALLBACK_VERSION


def modded(game_data=None, on_progress=None):
    """The installed game with every mod zip in its data folder, read in place. The game
    mounts the archives in name order and a later one overrides an earlier one, so the last
    zip comes first here."""
    from . import gamedata
    data = _data(game_data)
    roots = list(reversed(mod_zips(data))) + gamedata.base_roots(data, on_progress)
    return roots, gamedata.game_version(data) or FALLBACK_VERSION


def legends(game_data=None, on_progress=None):
    """`modded`, for a game that has the Legends mod."""
    data = _data(game_data)
    if not _has_legends(mod_zips(data)):
        raise FileNotFoundError("the Legends mod is not in %s" % data)
    return modded(data, on_progress)


def installed_summary(game_data=None):
    """What is installed, without loading it: {"data": the game's data folder, "game_version":
    text or None, "mods": [mod zip names], "legends": is Legends among them?, "reroll_mod":
    [names of BB Reroll's own in-game mod zips there], "dlc_complete": are all the DLC files
    there (gamedata.all_dlc)?}. None when no game is found."""
    from . import gamedata
    data = Path(game_data) if game_data else game_data_dir()
    if data is None:
        return None
    zips = mod_zips(data)
    return {"data": data, "game_version": gamedata.game_version(data), "mods": [z.name for z in zips],
            "legends": _has_legends(zips), "reroll_mod": [z.name for z in reroll_mod_zips(data)],
            "dlc_complete": gamedata.all_dlc(data)}


# ---------------------------------------------------------------------- research profiles
def research_data():
    """The research data folder (BBSEED_DATA), or None."""
    folder = os.environ.get("BBSEED_DATA")
    return Path(folder) if folder else None


def _research():
    data = research_data()
    if data is None:
        return {}, []
    try:
        spec = json.loads((data / "profiles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, []
    return spec.get("profiles") or {}, [data / b for b in spec.get("base") or []]


def extracted_base():
    """The research data's extracted source-text copy of the base game (folders), if described."""
    return _research()[1]


def research_roots(name):
    """The folders of a research profile without its base game, or None if there is no such profile."""
    found = _research()[0].get(name)
    return None if found is None else [research_data() / r for r in found.get("roots", []) if r != BASE]


def base_roots(source=None, on_progress=None):
    """The base game for a research profile. source "extracted": the source-text copy the
    research data describes; "game": the installed game's own compiled scripts. Default:
    BBSEED_BASE, else "extracted" when there is such a copy."""
    extracted = extracted_base()
    source = source or os.environ.get("BBSEED_BASE") or ("extracted" if extracted else "game")
    if source == "game":
        from . import gamedata
        return gamedata.base_roots(on_progress=on_progress)
    if source != "extracted":
        raise ValueError("BBSEED_BASE must be 'game' or 'extracted', not %r" % source)
    if not extracted:
        raise FileNotFoundError("the research data describes no extracted base game")
    return extracted


def names():
    """Every profile name that can be asked for."""
    return list(INSTALLED) + sorted(_research()[0])


def get(name=None, on_progress=None):
    """(roots, game_version) of a profile; raises FileNotFoundError when the game, a mod or a
    folder it needs is not there. on_progress(archive name, done, total) is called while the
    base game's scripts are read for the first time."""
    name = name or os.environ.get("BBSEED_PROFILE") or DEFAULT
    if name in INSTALLED:
        return {"vanilla": vanilla, "legends": legends, "modded": modded}[name](on_progress=on_progress)
    found = _research()[0].get(name)
    if found is None:
        raise KeyError("unknown profile %r (have: %s)" % (name, ", ".join(names())))
    data = research_data()
    roots = []
    for r in found.get("roots", []):
        roots.extend(base_roots(on_progress=on_progress) if r == BASE else [data / r])
    missing = [str(r) for r in roots if not r.exists()]
    if missing:
        raise FileNotFoundError("profile %r needs: %s" % (name, ", ".join(missing)))
    return roots, found.get("game_version") or FALLBACK_VERSION

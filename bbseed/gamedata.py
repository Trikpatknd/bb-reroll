"""The base game's own scripts, read straight from the game's data archives.

The game's `data_*.dat` files are zip archives; the scripts in them are compiled (.cnut)
and scrambled (see sq/cnut.py). Unscrambling all of them takes a while in Python, so it
is done once per archive and the result kept in a local cache: a zip with the same
compiled scripts, unscrambled, plus the names (only the names) of the archive's other
files, which scripts can ask for. The lab then uses that zip as a script root like any
mod zip.

The cache is the player's own game data in another wrapping. It stays on this machine
(default %LOCALAPPDATA%\\BB Reroll\\script-cache, override with BBSEED_CACHE) and is never part of
the project.
"""
import os
import re
import struct
import zipfile
from pathlib import Path

from .engine import PLAIN_MARKER
from .sq import cnut

CACHE_VERSION = 2
GAME_DATA_GUESSES = (
    r"C:\Program Files (x86)\Steam\steamapps\common\Battle Brothers\data",
    r"C:\Program Files\Steam\steamapps\common\Battle Brothers\data",
    r"G:\SteamLibrary\steamapps\common\Battle Brothers\data",
)
# The DLC data files: DLC name -> the data_*.dat that holds it. Each holds one script, which sets the flag
# Const.DLC.<name> from hasDLC(<Steam app id>); the maps and rosters depend on those flags.
DLC_FILES = {
    # scripts/dlc/dlc_lindwurm.cnut; Lindwurm
    "Lindwurm": "data_003.dat",
    # scripts/dlc/dlc_unhold.cnut; Unhold
    "Unhold": "data_004.dat",
    # scripts/dlc/dlc_wildmen.cnut; Wildmen
    "Wildmen": "data_006.dat",
    # scripts/dlc/dlc_desert.cnut; Desert
    "Desert": "data_008.dat",
    # scripts/dlc/dlc_paladins.cnut; Paladins
    "Paladins": "data_010.dat",
}


def as_data_dir(folder):
    """The data folder for what a player may point at: the game folder or its data folder.
    None if it holds no game archives."""
    folder = Path(folder)
    for candidate in (folder, folder / "data"):
        if candidate.is_dir() and any(candidate.glob("data_*.dat")):
            return candidate
    return None


def _steam_libraries():
    """Steam's library folders, from Steam's own list (Windows registry -> libraryfolders.vdf)."""
    try:
        import winreg
    except ImportError:
        return []
    steam = None
    for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(hive, key) as k:
                steam = Path(winreg.QueryValueEx(k, value)[0])
                break
        except OSError:
            continue
    if steam is None:
        return []
    libraries = [steam]
    try:
        text = (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libraries
    for m in re.finditer(r'"path"\s+"([^"]+)"', text):
        libraries.append(Path(m.group(1).replace("\\\\", "\\")))
    return libraries


def game_data_dir():
    """The game's data folder: BBSEED_GAME_DATA (the game folder or its data folder), else the
    Steam library that has the game, else the usual places."""
    override = os.environ.get("BBSEED_GAME_DATA")
    if override:
        return as_data_dir(override)
    candidates = [lib / "steamapps" / "common" / "Battle Brothers" for lib in _steam_libraries()]
    candidates += [Path(p) for p in GAME_DATA_GUESSES]
    for candidate in candidates:
        found = as_data_dir(candidate)
        if found is not None:
            return found
    return None


def game_version(game_data=None):
    """The game's version ("1.5.2.3") as its exe states it in its Windows version resource —
    the number the engine gives scripts as GameInfo.getVersionNumber(). None if not found."""
    data = Path(game_data) if game_data else game_data_dir()
    if data is None:
        return None
    signature = struct.pack("<I", 0xFEEF04BD)           # VS_FIXEDFILEINFO
    for exe in sorted(data.parent.glob("win32/*.exe")):
        try:
            raw = exe.read_bytes()
        except OSError:
            continue
        at = raw.find(signature)
        if at != -1 and at + 16 <= len(raw):
            ms, ls = struct.unpack_from("<II", raw, at + 8)
            if ms or ls:
                return "%d.%d.%d.%d" % (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
    return None


def installed_dlc(game_data=None):
    """The DLC names of DLC_FILES whose data file is in the game's data folder (game_data: the game folder or
    its data folder, see as_data_dir; None: the found install). Empty when no install is found."""
    data = game_data_dir() if game_data is None else as_data_dir(game_data)
    if data is None:
        return set()
    return {name for name, archive in DLC_FILES.items() if (data / archive).is_file()}


def all_dlc(game_data=None):
    """Does the game's data folder hold every DLC file of DLC_FILES? Vanilla maps depend on the DLC flags, so
    they are verified only with all of them (see mapgen.verified_setup). False when no install is found."""
    return installed_dlc(game_data) == set(DLC_FILES)


def cache_dir():
    base = os.environ.get("BBSEED_CACHE")
    if base:
        return Path(base)
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home() / ".cache") / "BB Reroll" / "script-cache"


def _cache_path(archive):
    st = archive.stat()
    return cache_dir() / ("%s-%d-%d-v%d.zip" % (archive.stem, st.st_size, st.st_mtime_ns, CACHE_VERSION))


def unscrambled(archive, on_progress=None):
    """The cache zip for one data archive (built now if it is not there yet)."""
    archive = Path(archive)
    target = _cache_path(archive)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".%d.tmp" % os.getpid())
    with zipfile.ZipFile(archive) as src:
        everything = [n for n in src.namelist() if not n.endswith("/")]
        names = [n for n in everything if n.endswith(".cnut")]
        others = [n for n in everything if not n.endswith(".cnut")]
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as out:
            out.writestr(PLAIN_MARKER, "\n".join(
                ["Compiled scripts of %s, unscrambled, and the names of its other files. A local cache; safe to delete."
                 % archive.name] + others) + "\n")
            for i, name in enumerate(names):
                out.writestr(name, cnut.load(src.read(name))[1])
                if on_progress is not None and i % 100 == 0:
                    on_progress(archive.name, i, len(names))
    os.replace(tmp, target)
    for old in target.parent.glob(archive.stem + "-*.zip"):      # caches of earlier versions of this archive
        if old != target:
            try:
                old.unlink()
            except OSError:
                pass
    if on_progress is not None:
        on_progress(archive.name, len(names), len(names))
    return target


def base_roots(game_data=None, on_progress=None):
    """Script roots for the base game as installed, highest priority first. The game mounts
    its archives in name order and a later one overrides an earlier one."""
    data = Path(game_data) if game_data else game_data_dir()
    if data is None:
        raise FileNotFoundError("Battle Brothers data folder not found (set BBSEED_GAME_DATA)")
    archives = sorted(data.glob("data_*.dat"), key=lambda a: a.name.lower())
    if not archives:
        raise FileNotFoundError("no data_*.dat in %s" % data)
    return [unscrambled(a, on_progress) for a in reversed(archives)]

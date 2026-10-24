"""The GUI's Map view without tkinter: the fields and their texts, the checks that turn what the player typed into map
conditions and Legends Map Options, the values the settings file keeps, and the small rules the window needs (when the
view is closed, when the game version is not the verified one, when the odds estimate may show, how big the picture is).
Unit-tested (tests/test_map_view.py).

Fields (all text, as the player typed them):
    conditions: {"ports", "ports_south", "ports_north", "north_band", and one per town type (map_conditions.TOWN_TYPES)}
                "0" = no condition; the band is a percent (1..99, default 33)
    options:    the seven Legends Map Options {"LandRatio", "Water", "Snowline", "Settlements", "Factions",
                "StackCitadels", "AllTradeLocations"}; the last two are "Yes" / "No"
The conditions go to the search as criteria["map"]; the options go to it as mod_settings["mod_legends:<Key>"]
(mod_settings()) and into map_conditions.problems(). They matter only when a map condition is set: they never change
the brothers, so a search without map conditions sends none.
"""
import re

from bbreroll.map_conditions import MAP_OPTION_DEFAULTS, TOWN_TYPES
from bbseed import mapdraw
from bbseed.mapgen import DEFAULT_NORTH_BAND, NOT_VERIFIED, VERIFIED_GAME, VERIFIED_LEGENDS, verified_setup  # noqa: F401

# One map on one worker with Legends' default Map Options (bb_seedlab MODLOG "MAP SURVEY"); about 40 % more with 8
# workers. A low Land Mass Ratio with a high Water value makes the generator reject far more land / sea attempts: one
# seed's map took 149 attempts and 352 s at Land Mass Ratio 45 with Water 42 (final review M1). There is no attempt
# cap; the texts say so.
MAP_SECONDS = 40
MIN_MAPS = 30               # maps built before the "about 1 in N" estimate shows
MIN_TESTED = 100            # seeds tested before it shows (as for the brothers alone)

# ------------------------------------------------------------------ the fields
CONDITION_LABELS = {"ports": "Ports", "ports_south": "Southern ports", "ports_north": "Northern ports",
                    "north_band": "North band (%)"}
TOWN_LABELS = dict(TOWN_TYPES)
COUNT_KEYS = ("ports", "ports_south", "ports_north")

# The tooltips of the fields. "ports_south" counts the ports that are city states (mapgen.counts).
CONDITION_TIPS = {"ports": "The minimum number of ports on the map. A port lets you travel by ship.",
                  "ports_south": "The minimum number of city states that have a port. City states are in the south.",
                  "ports_north": "The minimum number of ports in the north band. City states do not count here.",
                  "north_band": "The top part of the map, in percent. A northern port is a port in this part."}


def town_tip(label):
    """The tooltip of a town field: 'The minimum number of strongholds on the map.'"""
    return "The minimum number of %s on the map." % label.lower()

# The Map Options page of Legends (mod_legends/register/modsettings.nut:16-25): the game's labels and ranges.
OPTION_LABELS = {"LandRatio": "Land Mass Ratio", "Water": "Water", "Snowline": "Snowline", "Settlements": "Settlements",
                 "Factions": "Factions", "StackCitadels": "Decked Out Citadels",
                 "AllTradeLocations": "All trade buildings available"}
OPTION_RANGES = {"LandRatio": (45, 70), "Water": (28, 42), "Snowline": (75, 95), "Settlements": (19, 27),
                 "Factions": (2, 6)}
YES_NO_OPTIONS = ("StackCitadels", "AllTradeLocations")
YES, NO = "Yes", "No"

# ------------------------------------------------------------------ texts (simplified writing rules)
WAIT = "Each map takes about %d seconds with the default Map Options." % MAP_SECONDS
SLOW_OPTIONS = "A low Land Mass Ratio with a high Water value can make one map take many minutes."
HELP = ("Set the minimum number of ports and towns. A port lets you travel by ship. North band: the top part of the "
        "map, in percent. Each map takes about %d seconds with the default Map Options. Set brother conditions too, "
        "if you can. %s\n"
        "The map depends on the Map Options of the game. Write the same values as in the Mod Options of the game "
        "(Legends Mod, page Map Options). The Map Options do not change the brothers." % (MAP_SECONDS, SLOW_OPTIONS))
OPTIONS_TITLE = "Map Options. Use the same values as in the Mod Options of the game."
NEEDS_LEGENDS = "Map conditions need the Legends setup for now."
TURNED_OFF = ("Map conditions are off. They did not work with this game setup. "
              "Change a Map Option to turn them on again.")
MAP_FATAL_ADVICE = ("Map conditions are off. Change a Map Option in the Map view to turn them on again. "
                    "Roster searches still work.")


def default_conditions():
    """Every condition field with no condition (the band with its default)."""
    out = {key: "0" for key in CONDITION_LABELS}
    out["north_band"] = str(DEFAULT_NORTH_BAND)
    out.update({key: "0" for key in TOWN_LABELS})
    return out


def default_options():
    """The Map Options with Legends' defaults, as text, in the order of the game's page."""
    return {key: (NO if key in YES_NO_OPTIONS else str(MAP_OPTION_DEFAULTS[key])) for key in OPTION_LABELS}


# ------------------------------------------------------------------ what the player typed
def _whole(text):
    """The whole number in `text` (spaces around it are ignored), or None when it is not one."""
    text = str(text if text is not None else "").strip()
    return int(text) if re.fullmatch(r"[0-9]+", text) else None


def build(conditions, options):
    """(map criteria, Map Options, errors) from the fields.

    No map condition set (and no error): (None, None, []) - the search then has no map and sends no Map Options.
    Otherwise criteria are in the shape bbseed.search.normalize_map takes as it is: every count a number, the band
    a number from 1 to 99 (blank = the default), "towns" with the town types above 0. The options are the seven
    values as numbers and booleans for map_conditions.problems() and mod_settings(); they are checked against the
    game's ranges only now, because without a map condition they are not used.
    Errors (texts for the player, in the order of the fields): then criteria and options are None."""
    counts, bad = {}, {}
    for key in list(COUNT_KEYS) + list(TOWN_LABELS):
        text = str(conditions.get(key) if conditions.get(key) is not None else "").strip()
        n = 0 if text == "" else _whole(text)
        if n is None:
            bad[key] = "%s must be a whole number of 0 or more." % (CONDITION_LABELS.get(key) or TOWN_LABELS[key])
        else:
            counts[key] = n
    band_text = str(conditions.get("north_band") if conditions.get("north_band") is not None else "").strip()
    band = DEFAULT_NORTH_BAND if band_text == "" else _whole(band_text)
    band_ok = band is not None and 1 <= band <= 99
    if not bad and not any(counts.values()):
        return None, None, []
    errors = [bad[key] for key in COUNT_KEYS if key in bad]
    if not band_ok:
        errors.append("%s must be a whole number from 1 to 99." % CONDITION_LABELS["north_band"])
    errors += [bad[key] for key in TOWN_LABELS if key in bad]
    parsed, option_errors = {}, []
    for key, label in OPTION_LABELS.items():
        text = str((options or {}).get(key, "")).strip()
        if key in YES_NO_OPTIONS:
            if text in (YES, NO):
                parsed[key] = text == YES
            else:
                option_errors.append("%s must be %s or %s." % (label, YES, NO))
            continue
        low, high = OPTION_RANGES[key]
        n = _whole(text)
        if n is not None and low <= n <= high:
            parsed[key] = n
        else:
            option_errors.append("%s must be a whole number from %d to %d." % (label, low, high))
    errors += option_errors
    if errors:
        return None, None, errors
    criteria = {key: counts[key] for key in COUNT_KEYS}
    criteria["north_band"] = band
    criteria["towns"] = {key: counts[key] for key in TOWN_LABELS if counts[key]}
    return criteria, parsed, []


def default_option_values():
    """The Legends defaults as build() gives them: numbers and booleans."""
    return {key: (MAP_OPTION_DEFAULTS[key] if key not in YES_NO_OPTIONS else bool(MAP_OPTION_DEFAULTS[key]))
            for key in OPTION_LABELS}


def fields_from_spec(map_criteria, options):
    """(conditions, options) as field texts from a self-test spec: "map" holds map conditions in the shape the search
    takes ({"ports": 3, "towns": {"city_state": 2}}), "map_options" holds numbers and booleans. What the spec leaves
    out has its default."""
    conditions, texts = default_conditions(), default_options()
    for key, value in (map_criteria or {}).items():
        if key == "towns":
            for town, n in value.items():
                conditions[town] = str(n)
        else:
            conditions[key] = str(value)
    for key, value in (options or {}).items():
        texts[key] = (YES if value else NO) if key in YES_NO_OPTIONS else str(value)
    return conditions, texts


def mod_settings(options):
    """The Map Options as the search takes them: exactly the seven keys, "mod_legends:<Key>"."""
    return {"mod_legends:" + key: value for key, value in options.items()}


# ------------------------------------------------------------------ the settings file
def to_settings(conditions, options):
    """The two dicts the settings file keeps for the Map view (the text as typed)."""
    return {"map": {key: str(conditions.get(key, "")) for key in default_conditions()},
            "map_options": {key: str(options.get(key, "")) for key in default_options()}}


def _saved_text(value, default, yes_no):
    if isinstance(value, bool):
        return (YES if value else NO) if yes_no else default
    if isinstance(value, int):
        return default if yes_no else str(value)
    if isinstance(value, str):
        return value if not yes_no or value in (YES, NO) else default
    return default


def from_settings(data):
    """(conditions, options) from a settings file; what is missing or damaged has its default (a file from before
    the Map view has none)."""
    data = data if isinstance(data, dict) else {}
    out = []
    for key, defaults in (("map", default_conditions()), ("map_options", default_options())):
        saved = data.get(key) if isinstance(data.get(key), dict) else {}
        out.append({name: _saved_text(saved.get(name), default, name in YES_NO_OPTIONS)
                    for name, default in defaults.items()})
    return out[0], out[1]


# ------------------------------------------------------------------ the game version and the view's state
def verified(game_version, legends_version, mods=None):
    """Were maps of this game, this Legends version and this mod set checked against the real game? mods: the mod
    zips (file names, or the workers' info["mods"]): any mod beyond Legends, MSU and Modern Hooks makes the maps
    "not verified" (a mod can hook the map generator). None: only the versions count."""
    return verified_setup(game_version, legends_version, mods)


def legends_version_from_files(mod_files):
    """The Legends version in the name of its mod zip (mod_legends-19.4.22.zip), or None. The zip of Legends'
    assets (mod_legends-assets-19.4.3.zip) is not it."""
    for name in mod_files or ():
        found = re.match(r"mod_legends[-_ ]v?([0-9]+(?:\.[0-9]+)+)", name, re.IGNORECASE)
        if found:
            return found.group(1)
    return None


def view_state(legends, off):
    """(do map conditions count?, the line that says why not - or None). The maps are made for Legends only; `off`
    is a session that met a fatal map event, until the player changes a Map Option, the setup or the game folder."""
    if not legends:
        return False, NEEDS_LEGENDS
    if off:
        return False, TURNED_OFF
    return True, None


def fields_open(legends):
    """May the player type in the fields? On Legends always, also while map conditions are off: the player must be
    able to change a Map Option, which turns them on again (the extreme Land Mass Ratio and Water values can make
    a map that the game never finishes). Vanilla and Modded have no map to set."""
    return bool(legends)


# ------------------------------------------------------------------ the odds estimate while maps are built
def estimate_ready(odds, map_run, map_first):
    """May "about 1 in N seeds" show? Without map conditions after 100 tested seeds (as always). With them after
    MIN_MAPS maps (a map costs 40 s, so 100 would take most of ten minutes on 8 workers); when brother conditions
    come first the seeds are cheap and the 100 are needed too (the brothers' own rates must be sound)."""
    tested, maps = odds.get("tested", 0), odds.get("maps", 0)
    if not map_run:
        return tested >= MIN_TESTED
    return maps >= MIN_MAPS and (map_first or tested >= MIN_TESTED)


def brother_estimate(odds, map_run, map_first):
    """The estimate for a run with brother AND map conditions until MIN_MAPS maps are built: how often a seed's
    brothers meet their conditions (the rate of the roster sift, which a roster-only search shows after 100 seeds),
    with the number of maps built so far. "" in any other case: the full estimate (estimate_ready) or the wait note
    speaks. Rare brother conditions need hours for 30 maps; this keeps their rate in view meanwhile."""
    if not map_run or map_first:
        return ""
    chance, maps = odds.get("chance_brothers"), odds.get("maps", 0)
    if not chance or maps >= MIN_MAPS or odds.get("tested", 0) < MIN_TESTED:
        return ""
    return ("Approximately 1 in %s seeds meets the brother conditions (from %s seeds). Maps built: %d. "
            "The estimate with the maps shows after %d maps." % (format(round(1 / chance), ","),
                                                                 format(odds["tested"], ","), maps, MIN_MAPS))


def rate_text(rate):
    """Seeds per second for the watch line: one decimal below 10 (a search that builds maps tests 0.1 seeds a second:
    "0/s" looked stuck), whole numbers from 10."""
    return "%.1f" % rate if rate < 10 else "%.0f" % rate


def wait_note(odds):
    """The note while the first maps are built, "" once there are MIN_MAPS."""
    maps = odds.get("maps", 0)
    if maps >= MIN_MAPS:
        return ""
    return "%s The estimate shows after %d maps. Maps built: %d." % (WAIT, MIN_MAPS, maps)


# ------------------------------------------------------------------ the picture
MIN_SCALE = 0.3
_RESERVE = 250              # title bar, the two text lines and the taskbar


def canvas_scale(summary, screen_height):
    """The scale (1.0 = mapdraw's own size, 7 x 8 pixels a tile) of the map window's picture: as big as fits a
    screen of that height, at most 1.0 and at least MIN_SCALE. On a 1440-pixel screen the Legends map (140 x 170
    tiles) is about 1190 pixels high."""
    _w, height = mapdraw.picture_size(summary, 1)
    return min(1.0, max(MIN_SCALE, (screen_height - _RESERVE) / height))

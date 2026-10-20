"""Assemble the Legends Discord seed-sharing post for a seed the search found.

Pure / tkinter-free so it is unit-tested (tests/test_seed_report.py). The GUI
calls build_seed_report() with the origin, a free-text description, the seed,
report_info (what the search's game setup reported: Legends version and build
name, the Battle Sisters setting) and the tool version for the footer.

Map Options: the starting brothers are rolled from the seed text alone, after
the map is made — they are the same whatever the Map Options are, so the post
says so unless the caller knows the options and passes them.

A search with map conditions passes the map of the seed (game_map, a map summary): the post then
adds a 'Map:' line and always lists the Map Options, because the map depends on them.
"""

from bbreroll.criteria import STATS
from bbreroll.map_conditions import DEFAULT_NORTH_BAND, map_line

GITHUB_URL = "github.com/Trikpatknd/bb-reroll"

# Order + in-game labels for the Map Options block, used when the caller passes them.
_MAP_OPTION_LABELS = [
    ("LandRatio", "Land Mass Ratio"),
    ("Water", "Water"),
    ("Snowline", "Snowline"),
    ("Settlements", "Settlements"),
    ("Factions", "Factions"),
    ("StackCitadels", "Decked Out Citadels"),
    ("AllTradeLocations", "All trade buildings available"),
]
_BOOLEAN_KEYS = {"StackCitadels", "AllTradeLocations"}
_UNKNOWN = "(unknown)"
_ANY_MAP = "Map Options: any. They change the map, not the starting brothers."


def _yes_no(raw) -> str:
    return "Yes" if str(raw).strip().lower() in ("true", "1", "yes", "on") else "No"


def _version_line(report_info: dict) -> str:
    ver = report_info.get("version")
    if not ver:
        return _UNKNOWN
    build = report_info.get("build_name")
    return f"{ver} {build}" if build else ver


def _bros_line(roster) -> str:
    """'Bros: 1) Hedge Knight MSK3 MDF2 | 2) Sellsword FAT2 | ...' — each brother's background
    (when the roster has it) and talent stars, in stat order."""
    parts = []
    for i, bro in enumerate(roster, 1):
        stars = bro.get("stars") or {}
        text = " ".join(f"{s.upper()}{stars[s]}" for s in STATS if stars.get(s)) or "no stars"
        background = (bro.get("background_name") or "").replace("Background: ", "")
        parts.append(f"{i}) {background + ' ' if background else ''}{text}")
    return "Bros: " + " | ".join(parts)


def _mods_text(mods) -> str:
    """'Legends Mod 19.4.22, MSU 1.9.0' — every installed mod zip, with its version when known."""
    parts = [" ".join(p for p in (m.get("name"), m.get("version")) if p) for m in mods or ()]
    return ", ".join(p for p in parts if p) or "none"


def _map_text(game_map, north_band) -> str:
    """'Map: Ports 7 (south 2, north 3) · 3 city states'. The north band sets which ports are northern, so a band
    other than the default is named: 'Map: Ports 7 (south 2, north 3) · 3 city states · north band: the top 50 % of
    the map'. A reader can search again with the same band."""
    text = "Map: " + map_line(game_map, north_band)
    if north_band != DEFAULT_NORTH_BAND:
        text += f" · north band: the top {north_band:g} % of the map"
    return text


def build_seed_report(origin, description, seed, report_info, tool_version, roster=None,
                      game_map=None, north_band=DEFAULT_NORTH_BAND) -> str:
    """Return the ready-to-paste Discord post as a single string. With the seed's
    roster, a 'Bros:' line lists every brother's talent stars.

    game_map: the seed's map summary (bbseed.mapgen.summary), from a search with map conditions;
    north_band: the band percent that search used. With a map the post has a 'Map:' line and
    lists every Map Option (one the game did not report shows as unknown); without it nothing
    changes."""
    report_info = report_info or {}
    map_options = report_info.get("map_options") or {}

    lines = [
        f"Version: {_version_line(report_info)}",
        f"Origin: {report_info.get('origin') or origin}",
        f"Brief description: {description}",
    ]
    if roster:
        lines.append(_bros_line(roster))
    lines += [
        f"Seed: {seed}",
        f"Battle sisters: {report_info.get('battle_sisters') or _UNKNOWN}",
    ]
    if "mods" in report_info:       # a seed is only valid for the same game and mod versions
        lines.append(f"Game version: {report_info.get('game_version') or _UNKNOWN}")
        lines.append(f"Mods: {_mods_text(report_info['mods'])}")
    lines.append("")
    with_map = game_map is not None
    if with_map:
        lines.append(_map_text(game_map, north_band))
    if map_options or with_map:
        lines.append("Map Options:")
        for key, label in _MAP_OPTION_LABELS:
            if key in map_options and not (with_map and map_options[key] is None):
                raw = map_options[key]
                lines.append(f"{label}: {_yes_no(raw) if key in _BOOLEAN_KEYS else raw}")
            elif with_map:      # the map depends on every option: say which one is not known
                lines.append(f"{label}: {_UNKNOWN}")
    else:
        lines.append(_ANY_MAP)

    lines.append("")
    footer = "Found with BB Reroll"
    if tool_version and tool_version != "unknown":
        footer += f" v{tool_version}"
    footer += f" — {GITHUB_URL}"
    lines.append(footer)

    return "\n".join(lines)

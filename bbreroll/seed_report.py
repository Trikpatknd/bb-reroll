"""Assemble the Legends Discord seed-sharing post from parsed game state.

Pure / tkinter-free so it is unit-tested (tests/test_seed_report.py). The GUI
calls build_seed_report() with the origin (from the dropdown), a free-text
description, the matched seed, the latest report_info parsed by
logscan.parse_report_info, and the tool version for the footer.
"""

GITHUB_URL = "github.com/Trikpatknd/bb-reroll"

# Order + in-game labels for the Map Options block (all affect world gen, so all
# matter for reproduction — see the design doc).
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


def _yes_no(raw) -> str:
    return "Yes" if str(raw).strip().lower() in ("true", "1", "yes", "on") else "No"


def _version_line(report_info: dict) -> str:
    ver = report_info.get("version")
    if not ver:
        return _UNKNOWN
    build = report_info.get("build_name")
    return f"{ver} {build}" if build else ver


def build_seed_report(origin, description, seed, report_info, tool_version) -> str:
    """Return the ready-to-paste Discord post as a single string."""
    report_info = report_info or {}
    map_options = report_info.get("map_options") or {}

    lines = [
        f"Version: {_version_line(report_info)}",
        f"Origin: {origin}",
        f"Brief description: {description}",
        f"Seed: {seed}",
        f"Battle sisters: {report_info.get('battle_sisters') or _UNKNOWN}",
        "",
        "Map Options:",
    ]
    if map_options:
        for key, label in _MAP_OPTION_LABELS:
            if key not in map_options:
                continue
            raw = map_options[key]
            lines.append(f"{label}: {_yes_no(raw) if key in _BOOLEAN_KEYS else raw}")
    else:
        lines.append(_UNKNOWN)

    lines.append("")
    footer = "Found with BB Reroll"
    if tool_version and tool_version != "unknown":
        footer += f" v{tool_version}"
    footer += f" — {GITHUB_URL}"
    lines.append(footer)

    return "\n".join(lines)

"""Pins the Discord seed-report formatter. Pure / tkinter-free."""
from bbreroll.seed_report import build_seed_report

FULL_INFO = {
    "version": "19.3.39",
    "build_name": "Left & Right",
    "battle_sisters": "Enabled",
    "map_options": {
        "LandRatio": "60", "Water": "38", "Snowline": "85",
        "Settlements": "24", "Factions": "3",
        "StackCitadels": "true", "AllTradeLocations": "false",
    },
}


def test_full_report_has_all_fields():
    out = build_seed_report("Gladiators", "Two melee 3-star bros", "UUG243P3BQ",
                            FULL_INFO, "3.4.6")
    assert "Version: 19.3.39 Left & Right" in out
    assert "Origin: Gladiators" in out
    assert "Brief description: Two melee 3-star bros" in out
    assert "Seed: UUG243P3BQ" in out
    assert "Battle sisters: Enabled" in out
    assert "Map Options:" in out
    assert "Land Mass Ratio: 60" in out
    assert "Settlements: 24" in out
    assert "Factions: 3" in out
    assert "Found with BB Reroll v3.4.6 — github.com/Trikpatknd/bb-reroll" in out


def test_booleans_render_yes_no():
    out = build_seed_report("Noble", "", "ABCDEFGH12", FULL_INFO, "3.4.6")
    assert "Decked Out Citadels: Yes" in out          # StackCitadels=true
    assert "All trade buildings available: No" in out  # AllTradeLocations=false


def test_unknown_info_renders_placeholders_not_crash():
    empty = {"version": None, "build_name": None, "battle_sisters": None, "map_options": {}}
    out = build_seed_report("Custom", "", "ABCDEFGH12", empty, "3.4.6")
    assert "Version: (unknown)" in out
    assert "Battle sisters: (unknown)" in out
    assert "Map Options:\n(unknown)" in out


def test_empty_description_leaves_blank_value():
    out = build_seed_report("Gladiators", "", "ABCDEFGH12", FULL_INFO, "3.4.6")
    assert "Brief description: \n" in out


def test_version_without_build_name_omits_trailing_space():
    info = dict(FULL_INFO, build_name=None)
    out = build_seed_report("Gladiators", "x", "ABCDEFGH12", info, "3.4.6")
    assert "Version: 19.3.39\n" in out


def test_footer_drops_version_when_unknown():
    out = build_seed_report("Gladiators", "x", "ABCDEFGH12", FULL_INFO, "unknown")
    assert "Found with BB Reroll — github.com/Trikpatknd/bb-reroll" in out

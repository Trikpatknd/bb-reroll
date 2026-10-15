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
    out = build_seed_report("Lone Wolf", "", "ABCDEFGH12", empty, "3.4.6")
    assert "Version: (unknown)" in out
    assert "Battle sisters: (unknown)" in out


def test_without_map_options_the_post_says_they_do_not_matter():
    # what the offline search passes: the recruits come from the seed text alone
    info = {"version": "19.4.22", "build_name": "Bandits & Greenskins", "battle_sisters": "Enabled",
            "origin": "Trading Caravan", "map_options": {}}
    out = build_seed_report("Trading Caravan", "", "8633698106", info, "4.0.0")
    assert "Map Options: any (the starting brothers do not depend on them; the map does)" in out
    assert "Land Mass Ratio" not in out
    assert out.endswith("Found with BB Reroll v4.0.0 — github.com/Trikpatknd/bb-reroll")


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


def test_origin_prefers_report_info_over_dropdown_arg():
    # The origin the search actually ran must win over the GUI dropdown value.
    info = dict(FULL_INFO, origin="Gladiators")
    out = build_seed_report("Lone Wolf", "x", "ABCDEFGH12", info, "3.4.6")
    assert "Origin: Gladiators" in out
    assert "Origin: Lone Wolf" not in out


def test_origin_falls_back_to_dropdown_arg_when_not_reported():
    info = dict(FULL_INFO)            # FULL_INFO has no "origin" key
    out = build_seed_report("Lone Wolf", "x", "ABCDEFGH12", info, "3.4.6")
    assert "Origin: Lone Wolf" in out


def test_roster_adds_a_bros_line_with_stars_per_brother():
    roster = [{"stars": {"hp": 0, "msk": 3, "mdf": 2, "rdf": 1}},
              {"stars": {"mdf": 1, "fat": 2}},          # dict order is not the stat order
              {"stars": {}}]
    out = build_seed_report("Gladiators", "x", "ABCDEFGH12", FULL_INFO, "4.0.0", roster=roster)
    assert "Brief description: x\nBros: 1) MSK3 MDF2 RDF1 | 2) FAT2 MDF1 | 3) no stars\nSeed:" in out


def test_game_version_and_mods_are_listed_for_compatibility():
    info = dict(FULL_INFO, game_version="1.5.2.3",
                mods=[{"name": "Legends Mod", "version": "19.4.22"}, {"name": "mod_textures", "version": None}])
    out = build_seed_report("Gladiators", "x", "ABCDEFGH12", info, "4.0.0")
    assert "Game version: 1.5.2.3\nMods: Legends Mod 19.4.22, mod_textures\n" in out


def test_an_unmodded_game_says_no_mods():
    info = dict(FULL_INFO, game_version="1.5.2.3", mods=[])
    out = build_seed_report("Gladiators", "x", "ABCDEFGH12", info, "4.0.0")
    assert "Mods: none\n" in out


def test_older_entries_without_mod_info_have_no_mods_line():
    out = build_seed_report("Gladiators", "x", "ABCDEFGH12", FULL_INFO, "4.0.0")
    assert "Mods:" not in out and "Game version:" not in out


def test_without_roster_there_is_no_bros_line():
    out = build_seed_report("Gladiators", "x", "ABCDEFGH12", FULL_INFO, "4.0.0")
    assert "Bros:" not in out

"""Pins the Discord seed-report formatter. Pure / tkinter-free."""
from bbreroll.seed_report import _ANY_MAP, _MAP_OPTION_LABELS, _UNKNOWN, build_seed_report

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
    assert "Map Options: any. They change the map, not the starting brothers." in out
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


def test_the_bros_line_names_each_brothers_background():
    roster = [{"stars": {"msk": 3}, "background_name": "Hedge Knight"},
              {"stars": {}, "background_name": "Background: Sellsword"}]
    out = build_seed_report("Free Company", "x", "1234567890", FULL_INFO, "4.2.0", roster=roster)
    assert "Bros: 1) Hedge Knight MSK3 | 2) Sellsword no stars\n" in out


# ---------------------------------------------------------------------------------- the map (map search)
ROSTER = [{"stars": {"msk": 3, "mdf": 2}, "background_name": "Hedge Knight"},
          {"stars": {"fat": 2}, "background_name": "Background: Sellsword"}]
OPTIONS = {"LandRatio": 55, "Water": 38, "Snowline": 85, "Settlements": 24, "Factions": 3,
           "StackCitadels": True, "AllTradeLocations": False}      # what Lab.info() reports: ints and bools


def info_with_map_options():
    return {"version": "19.4.22", "build_name": "Bandits & Greenskins", "battle_sisters": "Enabled",
            "origin": "Trading Caravan", "game_version": "1.5.2.3",
            "mods": [{"name": "Legends Mod", "version": "19.4.22"}, {"name": "MSU", "version": "1.9.0"}],
            "map_options": dict(OPTIONS)}


def _town(x, y, port=False, southern=False):
    return {"name": "Town %d %d" % (x, y), "script": "city_state" if southern else "legends_fishing_village",
            "size": 3 if southern else 1, "x": x, "y": y, "southern": southern, "military": False, "port": port,
            "faction": None}


# 10 rows, high y is north: the top 33 % are the rows 7-9, the top 50 % the rows 5-9.
# 9 ports: 2 southern, 3 northern in the 33 % band, 4 in the middle; 3 city states.
MAP_9_PORTS = {"size": [10, 10], "layout": "even-q-up", "terrain": "L" * 100, "attempts": 1, "towns": [
    _town(0, 0, port=True, southern=True), _town(1, 0, port=True, southern=True), _town(2, 0, southern=True),
    _town(0, 9, port=True), _town(1, 9, port=True), _town(2, 8, port=True),
    _town(3, 5, port=True), _town(4, 4, port=True), _town(5, 3, port=True), _town(6, 2, port=True)]}


def test_post_with_map_names_ports_and_map_options():
    text = build_seed_report("Trading Caravan", "", "0000000009", info_with_map_options(), "4.2.0",
                             roster=ROSTER, game_map=MAP_9_PORTS)
    assert "Map: Ports 9 (south 2, north 3) · 3 city states\n" in text
    assert "Land Mass Ratio: 55" in text and "Water: 38" in text and "Snowline: 85" in text
    assert "Decked Out Citadels: Yes" in text and "All trade buildings available: No" in text
    assert _ANY_MAP not in text


def test_the_post_with_a_map_in_full():
    """The Map line stands in the Map Options block's paragraph, above the block."""
    text = build_seed_report("Trading Caravan", "A port map", "0000000009", info_with_map_options(), "4.2.0",
                             roster=ROSTER, game_map=MAP_9_PORTS)
    assert text == (
        "Version: 19.4.22 Bandits & Greenskins\n"
        "Origin: Trading Caravan\n"
        "Brief description: A port map\n"
        "Bros: 1) Hedge Knight MSK3 MDF2 | 2) Sellsword FAT2\n"
        "Seed: 0000000009\n"
        "Battle sisters: Enabled\n"
        "Game version: 1.5.2.3\n"
        "Mods: Legends Mod 19.4.22, MSU 1.9.0\n"
        "\n"
        "Map: Ports 9 (south 2, north 3) · 3 city states\n"
        "Map Options:\n"
        "Land Mass Ratio: 55\n"
        "Water: 38\n"
        "Snowline: 85\n"
        "Settlements: 24\n"
        "Factions: 3\n"
        "Decked Out Citadels: Yes\n"
        "All trade buildings available: No\n"
        "\n"
        "Found with BB Reroll v4.2.0 — github.com/Trikpatknd/bb-reroll")


# The post of a search without map conditions, as build_seed_report made it before it knew about maps.
TODAY_WITH_OPTIONS = (
    "Version: 19.4.22 Bandits & Greenskins\nOrigin: Trading Caravan\nBrief description: A port map\n"
    "Bros: 1) Hedge Knight MSK3 MDF2 | 2) Sellsword FAT2\nSeed: 0000000009\nBattle sisters: Enabled\n"
    "Game version: 1.5.2.3\nMods: Legends Mod 19.4.22, MSU 1.9.0\n\n"
    "Map Options:\nLand Mass Ratio: 55\nWater: 38\nSnowline: 85\nSettlements: 24\nFactions: 3\n"
    "Decked Out Citadels: Yes\nAll trade buildings available: No\n\n"
    "Found with BB Reroll v4.2.0 — github.com/Trikpatknd/bb-reroll")
TODAY_ANY_MAP = (
    "Version: 19.4.22 Bandits & Greenskins\nOrigin: Trading Caravan\nBrief description: A port map\n"
    "Bros: 1) Hedge Knight MSK3 MDF2 | 2) Sellsword FAT2\nSeed: 0000000009\nBattle sisters: Enabled\n"
    "Game version: 1.5.2.3\nMods: Legends Mod 19.4.22, MSU 1.9.0\n\n"
    "Map Options: any. They change the map, not the starting brothers.\n\n"
    "Found with BB Reroll v4.2.0 — github.com/Trikpatknd/bb-reroll")


def test_post_without_map_is_unchanged():
    info = info_with_map_options()
    args = ("Trading Caravan", "A port map", "0000000009", info, "4.2.0")
    assert build_seed_report(*args, roster=ROSTER) == TODAY_WITH_OPTIONS
    assert build_seed_report(*args, roster=ROSTER, game_map=None, north_band=33) == TODAY_WITH_OPTIONS
    no_options = dict(info, map_options={})
    assert build_seed_report("Trading Caravan", "A port map", "0000000009", no_options, "4.2.0",
                             roster=ROSTER) == TODAY_ANY_MAP
    # a north band alone says nothing: there is no map to count it on
    assert build_seed_report("Trading Caravan", "A port map", "0000000009", no_options, "4.2.0",
                             roster=ROSTER, north_band=50) == TODAY_ANY_MAP


def test_a_post_with_a_map_always_lists_every_map_option():
    # the lab reported nothing (a game without these settings): every option is unknown, none is left out
    for info in (dict(info_with_map_options(), map_options={}),
                 {k: v for k, v in info_with_map_options().items() if k != "map_options"}):
        text = build_seed_report("Trading Caravan", "", "0000000009", info, "4.2.0", game_map=MAP_9_PORTS)
        assert _ANY_MAP not in text
        block = text.split("Map Options:\n", 1)[1].split("\n\n", 1)[0].split("\n")
        assert block == ["%s: %s" % (label, _UNKNOWN) for _key, label in _MAP_OPTION_LABELS]


def test_a_map_option_the_lab_did_not_report_is_unknown():
    options = {k: v for k, v in OPTIONS.items() if k not in ("Snowline", "StackCitadels")}
    options["Factions"] = None
    info = dict(info_with_map_options(), map_options=options)
    text = build_seed_report("Trading Caravan", "", "0000000009", info, "4.2.0", game_map=MAP_9_PORTS)
    assert "Land Mass Ratio: 55\nWater: 38\nSnowline: (unknown)\nSettlements: 24\nFactions: (unknown)\n" \
           "Decked Out Citadels: (unknown)\nAll trade buildings available: No\n" in text


def test_booleans_of_the_lab_render_yes_no_in_a_map_post():
    info = dict(info_with_map_options(), map_options=dict(OPTIONS, StackCitadels=False, AllTradeLocations=True))
    text = build_seed_report("Trading Caravan", "", "0000000009", info, "4.2.0", game_map=MAP_9_PORTS)
    assert "Decked Out Citadels: No\nAll trade buildings available: Yes\n" in text


def test_the_map_line_names_a_north_band_that_is_not_the_default():
    """The band decides which ports are northern: a reader repeats the search with the same band."""
    base = "Map: Ports 9 (south 2, north %d) · 3 city states"
    default = build_seed_report("Trading Caravan", "", "0000000009", info_with_map_options(), "4.2.0",
                                game_map=MAP_9_PORTS)
    assert base % 3 + "\n" in default and "band" not in default
    explicit = build_seed_report("Trading Caravan", "", "0000000009", info_with_map_options(), "4.2.0",
                                 game_map=MAP_9_PORTS, north_band=33)
    assert explicit == default
    wide = build_seed_report("Trading Caravan", "", "0000000009", info_with_map_options(), "4.2.0",
                             game_map=MAP_9_PORTS, north_band=50)
    assert (base % 4) + " · north band: the top 50 % of the map\nMap Options:\n" in wide
    narrow = build_seed_report("Trading Caravan", "", "0000000009", info_with_map_options(), "4.2.0",
                               game_map=MAP_9_PORTS, north_band=20)
    assert (base % 3) + " · north band: the top 20 % of the map\nMap Options:\n" in narrow   # rows 8-9: still 3


def test_the_lab_and_the_post_name_the_same_map_options():
    """bbseed never imports bbreroll, so the lab keeps its own list of the Map Options it reports."""
    from bbreroll import map_conditions
    from bbseed.lab import MAP_OPTION_KEYS
    assert tuple(key for key, _label in _MAP_OPTION_LABELS) == MAP_OPTION_KEYS
    assert tuple(map_conditions.MAP_OPTION_DEFAULTS) == MAP_OPTION_KEYS


def test_a_vanilla_map_post_says_the_base_game_has_no_map_options():
    """The base game has no Map Options (report_info legends False): one line after the Map line, no block."""
    info = dict(info_with_map_options(), legends=False, map_options={}, version="Vanilla 1.5.2.3", build_name=None)
    text = build_seed_report("Trading Caravan", "", "0000000009", info, "4.2.0", roster=ROSTER, game_map=MAP_9_PORTS)
    assert "\nMap: Ports 9 (south 2, north 3) · 3 city states\n" \
           "Map Options: none. The base game has no Map Options.\n\nFound with BB Reroll v4.2.0" in text
    assert "Map Options:\n" not in text and "Land Mass Ratio" not in text and _ANY_MAP not in text
    band = build_seed_report("Trading Caravan", "", "0000000009", info, "4.2.0", game_map=MAP_9_PORTS, north_band=50)
    assert "· north band: the top 50 % of the map\nMap Options: none. The base game has no Map Options.\n" in band


def test_a_legends_post_and_a_vanilla_roster_post_keep_their_text():
    """legends True reads the same as the old key-less info; without a map a Vanilla post says "any" as before."""
    args = ("Trading Caravan", "A port map", "0000000009")
    legends = dict(info_with_map_options(), legends=True)
    assert build_seed_report(*args, legends, "4.2.0", roster=ROSTER, game_map=MAP_9_PORTS) == \
        build_seed_report(*args, info_with_map_options(), "4.2.0", roster=ROSTER, game_map=MAP_9_PORTS)
    vanilla = dict(info_with_map_options(), legends=False, map_options={})
    assert build_seed_report(*args, vanilla, "4.2.0", roster=ROSTER) == TODAY_ANY_MAP


def _base_game_info(**changes):
    return dict(info_with_map_options(), legends=False, map_options={}, mods=[], version="Vanilla 1.5.2.3",
                build_name=None, **changes)


def test_a_base_game_post_names_the_dlcs_right_after_the_mods():
    """Final review F2: a base-game map depends on the DLCs, so the post says whether every DLC is installed."""
    text = build_seed_report("Trading Caravan", "", "0000000009", _base_game_info(dlc_complete=True), "4.2.0",
                             roster=ROSTER)
    assert "Game version: 1.5.2.3\nMods: none\nDLCs: all\n\nMap Options: any." in text
    text = build_seed_report("Trading Caravan", "", "0000000009", _base_game_info(dlc_complete=False), "4.2.0",
                             roster=ROSTER)
    assert "Mods: none\nDLCs: not all installed\n\nMap Options: any." in text
    text = build_seed_report("Trading Caravan", "", "0000000009", _base_game_info(dlc_complete=True), "4.2.0",
                             game_map=MAP_9_PORTS)
    assert "Mods: none\nDLCs: all\n\nMap: Ports 9 (south 2, north 3)" in text


def test_the_dlc_line_is_for_the_base_game_only():
    """A Legends post, and a report_info without the key (a search from before it), keep their text."""
    legends = build_seed_report("Trading Caravan", "", "0000000009",
                                dict(info_with_map_options(), legends=True, dlc_complete=True), "4.2.0", roster=ROSTER)
    assert "DLCs:" not in legends
    assert "DLCs:" not in build_seed_report("Trading Caravan", "", "0000000009", _base_game_info(), "4.2.0",
                                            roster=ROSTER)

"""Whole generated maps pinned to what the real game made (map-search Task 7, Checkpoint B).

On 2026-10-19 the game (Battle Brothers 1.5.2.3, Legends 19.4.22, MSU 1.9.0, Modern Hooks 0.6.0) started 40 Trader
campaigns by itself and logged every generated map (bb_seedlab tools/verify_template.nut, map jobs; the comparison
is bb_seedlab tools/map_compare.py and MODLOG "CHECKPOINT B"). In all 40 the lab's towns and its terrain before
buildRoads were the game's. Two of those seeds are pinned here:

- the towns: every VERIFIED field (script, x, y, size, name, port = the town's IsCoastal, southern, military), in
  the order the scripts created them. The values are the GAME's log rows, so this pin is game truth. The names of
  city states (drawn after the roads), the factions and the probe are not pinned: they depend on the roads' tiles,
  which the lab does not have exactly yet (stage 2).
- the number of land/sea attempts, also as the game logged it.
- a CRC32 of the lab's summary terrain: a LAB REGRESSION ONLY. The terrain before buildRoads was verified in game,
  but the summary is the terrain at the end, and the tiles changed after buildRoads (1 to 24 per map: hills along
  the roads) differ from the game's.

The maps use the Mod Options the game had for that run (its own log lists them), and Legends' black-market counter
as the run had it (BLACKMARKET_BEFORE). Skipped unless Legends 19.4.22 on 1.5.2.3 is installed. Two whole maps, each
built once per test session (MAPS).
"""
import zlib

import pytest

from bbseed import profiles

FOUND = profiles.installed_summary()
HAVE_GAME = FOUND is not None and FOUND["game_version"] == "1.5.2.3"
HAVE_LEGENDS = HAVE_GAME and any("mod_legends-19.4.22" in m for m in FOUND["mods"]) and any("1.9.0" in m for m in FOUND["mods"])

# the in-game run's Mod Options (logged by the game for every map)
MAP_OPTIONS = {"mod_legends:LandRatio": 55, "mod_legends:Water": 38, "mod_legends:Snowline": 85,
               "mod_legends:Settlements": 24, "mod_legends:Factions": 4, "mod_legends:StackCitadels": True,
               "mod_legends:AllTradeLocations": True}
ORIGIN = "trader_scenario"

# (script, x, y, size, name or None for a city state, port, southern, military), from the game's log
GAME_TOWNS = {
    "1234567890": [
        ("legends_fishing_village", 21, 34, 1, "Stohl", True, False, False),
        ("legends_fishing_village", 45, 61, 2, "Birkhaven", True, False, False),
        ("legends_fishing_village", 47, 46, 3, "Holnisland", True, False, False),
        ("legends_fishing_village", 61, 91, 1, "Grossenkoog", True, False, False),
        ("legends_fishing_village", 32, 52, 1, "Krakendorf", True, False, False),
        ("legends_mining_village", 13, 155, 1, "Thal", False, False, False),
        ("legends_lumber_village", 27, 77, 2, "Langholz", False, False, False),
        ("legends_mining_village", 73, 128, 3, "Reinbruch", False, False, False),
        ("legends_mining_village", 23, 137, 3, "Schachtheim", False, False, False),
        ("legends_mining_village", 24, 88, 2, "Eisenstein", False, False, False),
        ("legends_snow_village", 34, 161, 1, "Hellevad", False, False, False),
        ("legends_mining_village", 81, 148, 1, "Wolfhaiden", False, False, False),
        ("legends_farming_village", 79, 76, 3, "Grunmark", False, False, False),
        ("legends_tundra_village", 24, 126, 1, "Ogna", False, False, False),
        ("legends_farming_village", 37, 106, 1, "Hermannshof", False, False, False),
        ("legends_steppe_village", 70, 68, 3, "Rothstadt", False, False, False),
        ("legends_swamp_village", 55, 121, 1, "Ehlerstorf", False, False, False),
        ("legends_steppe_fort", 66, 50, 1, "Brackenwacht", False, False, True),
        ("legends_forest_fort", 45, 94, 2, "Wurzelburg", False, False, True),
        ("legends_tundra_fort", 5, 135, 3, "Sommersborg", False, False, True),
        ("legends_mountains_fort", 37, 144, 3, "Eisenfeste", False, False, True),
        ("legends_swamp_fort", 62, 109, 1, "Brunnwall", False, False, True),
        ("legends_swamp_fort", 14, 107, 1, "Furthwacht", False, False, True),
        ("legends_tundra_fort", 11, 126, 2, "Lundirsholm", False, False, True),
        ("legends_farm_fort", 24, 66, 1, "Speerheim", False, False, True),
        ("city_state", 71, 16, 3, None, False, True, False),
        ("city_state", 132, 20, 3, None, True, True, False),
        ("city_state", 101, 10, 3, None, False, True, False),
    ],
    "0000000002": [
        ("legends_fishing_village", 15, 36, 1, "Holmwik", True, False, False),
        ("legends_fishing_village", 41, 37, 2, "Harkendock", True, False, False),
        ("legends_fishing_village", 13, 57, 3, "Seestadt", True, False, False),
        ("legends_fishing_village", 37, 50, 1, "Niewik", True, False, False),
        ("legends_fishing_village", 46, 70, 2, "Salthaven", True, False, False),
        ("legends_steppe_village", 59, 78, 1, "Kargau", False, False, False),
        ("legends_steppe_village", 52, 51, 2, "Himmelsdorf", False, False, False),
        ("legends_farming_village", 57, 111, 3, "Konigsheim", False, False, False),
        ("legends_mining_village", 16, 114, 3, "Grubenheim", False, False, False),
        ("legends_farming_village", 70, 89, 3, "Hageland", False, False, False),
        ("legends_mining_village", 70, 148, 3, "Erzheim", False, False, False),
        ("legends_tundra_village", 45, 122, 3, "Ognasted", False, False, False),
        ("legends_snow_village", 84, 150, 1, "Ravestad", False, False, False),
        ("legends_swamp_village", 70, 125, 1, "Brookheim", False, False, False),
        ("legends_tundra_village", 35, 135, 3, "Norrested", False, False, False),
        ("legends_mining_village", 9, 101, 1, "Schweikhof", False, False, False),
        ("legends_lumber_village", 30, 93, 3, "Eulenmark", False, False, False),
        ("legends_mountains_fort", 27, 124, 1, "Steinberg", False, False, True),
        ("legends_steppe_fort", 79, 35, 2, "Wustenburg", False, False, True),
        ("legends_snow_fort", 48, 153, 3, "Eidsvikborg", False, False, True),
        ("legends_mountains_fort", 11, 84, 3, "Flechtenstein", False, False, True),
        ("legends_steppe_fort", 25, 52, 3, "Thunfeste", False, False, True),
        ("legends_snow_fort", 21, 161, 1, "Asentorn", False, False, True),
        ("legends_swamp_fort", 17, 71, 1, "Pfuhlwacht", False, False, True),
        ("legends_snow_fort", 14, 152, 2, "Asengard", False, False, True),
        ("city_state", 69, 8, 3, None, False, True, False),
        ("city_state", 116, 12, 3, None, False, True, False),
        ("city_state", 42, 5, 3, None, False, True, False),
    ],
}
GAME_ATTEMPTS = {"1234567890": 2, "0000000002": 1}            # the game's "Land Ocean ratio" lines per map
# LAB REGRESSION ONLY (see the module text): zlib.crc32 of the summary's terrain string
LAB_TERRAIN_CRC32 = {"1234567890": 0xFB00CA26, "0000000002": 0x610612B9}
# Legends counts the black markets it builds in ::Const.World.Buildings.Blackmarket and never resets it (its
# Buildings.reset() resets Stables only), so what refineSettlements draws depends on the campaigns started before in the
# same game session: 0 on the first one, at least 2 after any map (2 or more all act alike). The towns and the terrain
# before the roads do not depend on it; the terrain after the roads does. Set as in the in-game run (Lab.world_map's
# blackmarket): 1234567890 was its first campaign, 0000000002 its third. The fixture builds 0000000002 first, on a new
# lab (counter 0 there): its terrain pin then also checks that the parameter sets the counter (built at counter 0 its
# terrain CRC is 0x08A7E610, measured in map-search Task 9; 1234567890's is the same at 0 and 2).
BLACKMARKET_BEFORE = {"1234567890": 0, "0000000002": 2}

MAPS = {}


@pytest.fixture(scope="module")
def maps():
    if not HAVE_LEGENDS:
        pytest.skip("Battle Brothers 1.5.2.3 with Legends 19.4.22 + MSU 1.9.0 is not installed")
    from bbseed.lab import Lab, big_stack

    def run():
        lab = Lab("legends", mod_settings=MAP_OPTIONS)
        info = lab.info()
        if (info["game_version"], info["legends_version"]) != ("1.5.2.3", "19.4.22"):
            return info, None
        out = {}
        for seed in sorted(GAME_TOWNS):            # 0000000002 (counter 2) first, then 1234567890 (counter 0)
            out[seed] = lab.world_map(seed, ORIGIN, blackmarket=BLACKMARKET_BEFORE[seed])["map"]
        return info, out
    if not MAPS:
        info, built = big_stack(run)
        if built is None:
            pytest.skip("the lab did not load Legends 19.4.22 on 1.5.2.3: %r" % (info,))
        MAPS.update(built)
    return MAPS


def _verified(town):
    return (town["script"], town["x"], town["y"], town["size"], None if town["script"] == "city_state" else town["name"],
            town["port"], town["southern"], town["military"])


@pytest.mark.parametrize("seed", sorted(GAME_TOWNS))
def test_towns_are_the_games(maps, seed):
    assert [_verified(t) for t in maps[seed]["towns"]] == GAME_TOWNS[seed]


@pytest.mark.parametrize("seed", sorted(GAME_TOWNS))
def test_land_and_sea_attempts_are_the_games(maps, seed):
    assert maps[seed]["attempts"] == GAME_ATTEMPTS[seed]


@pytest.mark.parametrize("seed", sorted(GAME_TOWNS))
def test_terrain_lab_regression(maps, seed):
    """Not game truth: the summary terrain includes the tiles changed after buildRoads (unverified, stage 2)."""
    terrain = maps[seed]["terrain"]
    assert len(terrain) == 140 * 170
    assert zlib.crc32(terrain.encode("ascii")) == LAB_TERRAIN_CRC32[seed]

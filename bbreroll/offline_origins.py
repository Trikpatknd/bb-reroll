"""What the offline search offers: the game setups found on this PC and, per setup, the
origins — with the scenario script each of the GUI's origin names stands for.
Tkinter-free (unit-tested).
"""
import os

# GUI origin name -> scenario script under scripts/scenarios/world/
# (the `m.Name` of each scenario, Legends 19.4.22)
SCENARIO = {
    "A New Company": "early_access_scenario",
    "Anatomist": "anatomists_scenario",
    "Band of Poachers": "rangers_scenario",
    "Beast Slayers": "beast_hunters_scenario",
    "Davkul Cultists": "cultists_scenario",
    "Deserters": "deserters_scenario",
    "Gladiators": "gladiators_scenario",
    "Lone Wolf": "lone_wolf_scenario",
    "Manhunters": "manhunters_scenario",
    "Northern Raiders": "raiders_scenario",
    "Oathtakers": "paladins_scenario",
    "Peasant Militia": "militia_scenario",
    "Southern Mercenaries": "southern_quickstart_scenario",
    "Trading Caravan": "trader_scenario",
    "Adventuring Party": "legends_party_scenario",
    "Assassin": "legends_assassin_scenario",
    "Berserker": "legends_berserker_scenario",
    "Crusader": "legends_crusader_scenario",
    "Escaped Slaves": "legends_escaped_slaves_scenario",
    "The Free Company": "legends_free_company_scenario",
    "The Inquisition": "legends_inquisition_scenario",
    "Master Necromancer": "legends_solo_necro_scenario",
    "Noble": "legends_noble_scenario",
    "Nomad Tribe": "legends_nomad_scenario",
    "Original Beggar Challenge": "legends_beggar_scenario",
    "Random Party": "legend_random_party_scenario",
    "Random Solo": "legend_random_solo_scenario",
    "Random Trio": "legend_random_3_scenario",
    "Ranger": "legends_rangers_scenario",
    "Risen Legion": "legend_risen_legion_scenario",
    "Scaling Beggar Challenge": "legends_scaling_beggar_scenario",
    "Seer": "legends_seer_scenario",
    "Sisterhood": "legends_sisterhood_scenario",
    "The Cabal": "legends_necro_scenario",
    "The Troupe": "legends_troupe_scenario",
}

# (display name, brother count). None = no fixed count (Random Party rolls 4-6 bros per seed).
# Display names + counts confirmed from mod_legends/hooks/scenarios/world/*.nut
# and scripts/scenarios/world/legend*_scenario.nut (Legends 19.4.22).
# Skipped: tutorial / random-origin picker / developer debug, and the 4 origins Legends
# hard-disables (Build your own, Druid [Legacy], Horse Party, Mage — isValid() is false).
ORIGINS = [
    # Vanilla origins (Legends-hooked)
    ("A New Company",                3),
    ("Anatomist",                    3),
    ("Band of Poachers",             3),
    ("Beast Slayers",                3),
    ("Davkul Cultists",              5),
    ("Deserters",                    3),
    ("Gladiators",                   3),
    ("Lone Wolf",                    1),
    ("Manhunters",                   6),
    ("Northern Raiders",             4),
    ("Oathtakers",                   2),
    ("Peasant Militia",             12),
    ("Southern Mercenaries",         3),  # requires Blazing Deserts DLC
    ("Trading Caravan",              2),
    # Legends-added origins
    ("Adventuring Party",            6),
    ("Assassin",                     1),
    ("Berserker",                    1),
    ("Crusader",                     1),
    ("Escaped Slaves",               5),  # requires Blazing Deserts DLC
    ("The Free Company",             5),
    ("The Inquisition",              3),
    ("Master Necromancer",           6),
    ("Noble",                        6),
    ("Nomad Tribe",                  5),
    ("Original Beggar Challenge",    1),
    ("Random Party",              None),  # 4-6 bros, rolled per seed
    ("Random Solo",                  1),
    ("Random Trio",                  3),
    ("Ranger",                       2),
    ("Risen Legion",                 8),
    ("Scaling Beggar Challenge",     1),
    ("Seer",                         1),
    ("Sisterhood",                   6),
    ("The Cabal",                    4),
    ("The Troupe",                   4),
]
COUNTS = dict(ORIGINS)

# Its recruits are created in onSpawnPlayer, after a search that depends on the generated
# map: the roster is not a function of the seed text alone.
NOT_SEARCHABLE = {"Deserters": "its recruits are created after a step that depends on the generated map"}

# Game setup shown in the GUI -> (bbseed profile, does it have the Legends origins?).
# Filled by refresh() from the game found on this PC: nothing to extract or configure.
LEGENDS = "Legends"       # the installed game with the mods in its data folder (Legends among them)
VANILLA = "Vanilla"       # the installed game without mods
MODDED = "Modded"         # offered instead of "Legends" when the mods there do not include Legends
SETUPS = {}
DEFAULT_SETUP = None
FOUND = None        # bbseed.profiles.installed_summary(): data folder, game version, mod zips, ...

# roster sizes of the unmodded game where they differ from the Legends counts the GUI lists
VANILLA_COUNTS = {"Davkul Cultists": 4}

# Legends' Mod Option "Battle Sisters" (setting GenderEquality): it changes rosters. Default: Enabled.
BATTLE_SISTERS = ("Disabled", "Enabled", "Enabled (Cosmetic)")


def refresh():
    """(Re)build SETUPS from the installed game; returns FOUND (None if no game was found)."""
    global DEFAULT_SETUP, FOUND
    from bbseed import profiles
    SETUPS.clear()
    FOUND = profiles.installed_summary()
    if FOUND is not None:
        if FOUND["legends"]:
            SETUPS[LEGENDS] = ("legends", True)
        elif FOUND["mods"]:
            SETUPS[MODDED] = ("modded", False)
        SETUPS[VANILLA] = ("vanilla", False)
    if os.environ.get("BBSEED_RESEARCH_SETUPS"):        # pinned copies the engine was developed against
        known = profiles.names()
        if "research-legends" in known:
            SETUPS["Research: Legends 19.4.22"] = ("research-legends", True)
        if "research-vanilla" in known:
            SETUPS["Research: Vanilla 1.5.2.3"] = ("research-vanilla", False)
    DEFAULT_SETUP = next(iter(SETUPS), None)
    return FOUND


def found_text(details=False):
    """Which game and mods the setups stand for: one line, or with `details` the mod files too."""
    if FOUND is None:
        return "Battle Brothers was not found on this PC — click \"Game folder…\" and select where it is installed."
    mods = FOUND["mods"]
    line = "Game %s with %s found in %s" % (
        FOUND["game_version"] or "(version unknown)",
        "no mods" if not mods else "1 mod file" if len(mods) == 1 else "%d mod files" % len(mods), FOUND["data"].parent)
    if details and mods:
        line += "\n\nMods (the zip files in its data folder):\n" + "\n".join("  " + m for m in mods)
    return line


def reroll_mod_warning():
    """Text for the player when BB Reroll's in-game mod sits in the game's data folder, else None.
    That mod re-seeds every campaign start, so with it the game does not give the plain
    rosters the offline search finds."""
    if FOUND is None or not FOUND.get("reroll_mod"):
        return None
    return ("BB Reroll's in-game mod (%s) is in your game's data folder. While it is there the game rolls "
            "DIFFERENT brothers for every seed, so seeds found offline will not match. Remove that file "
            "(and restart Battle Brothers) before you play a seed found here." % ", ".join(FOUND["reroll_mod"]))


def is_legends_only(name):
    return SCENARIO[name].startswith(("legends_", "legend_"))


def names_for(setup):
    """Origin names offered for a game setup, in the GUI's order."""
    _profile, legends = SETUPS.get(setup, (None, False))
    return [n for n in SCENARIO if n not in NOT_SEARCHABLE and (legends or not is_legends_only(n))]


refresh()

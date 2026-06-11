"""Trait ID → display-name lookup for the BB Reroll GUI.

Source: live extraction of mod_legends-19.3.24 (scripts/skills/traits/*_trait.nut
and mod_legends/hooks/skills/traits/*.nut). The mod emits IDs like
`trait.legend_heavy`; the GUI strips the `trait.` prefix and looks the
remainder up here to get the player-facing label (e.g. "Lumbering").

Vanilla traits typically have a display name equal to their ID titlecased;
Legends adds renamed and net-new traits. Anything not in this map falls back
to `_id_to_display()` in gui.py — snake_case → Title Case with the
`legend_` prefix stripped.
"""

TRAIT_NAMES: dict[str, str] = {
    # Vanilla bad
    "addict":          "Addict",
    "ailing":          "Ailing",
    "asthmatic":       "Asthmatic",
    "bleeder":         "Bleeder",
    "brute":           "Brute",
    "clubfooted":      "Clubfooted",
    "clumsy":          "Clumsy",
    "cocky":           "Cocky",
    "craven":          "Craven",
    "dastard":         "Dastard",
    "disloyal":        "Disloyal",
    "drunkard":        "Drunkard",
    "dumb":            "Dumb",
    "fainthearted":    "Fainthearted",
    "fat":             "Fat",
    "fear_beasts":     "Fear of Beasts",
    "fear_greenskins": "Fear of Greenskins",
    "fear_undead":     "Fear of Undead",
    "fragile":         "Fragile",
    "gluttonous":      "Gluttonous",
    "greedy":          "Greedy",
    "hesitant":        "Hesitant",
    "impatient":       "Impatient",
    "insecure":        "Insecure",
    "irrational":      "Irrational",
    "mad":             "Mad",
    "night_blind":     "Night Blindness",
    "paranoid":        "Paranoid",
    "pessimist":       "Pessimist",
    "short_sighted":   "Short-Sighted",
    "superstitious":   "Superstitious",
    "tiny":            "Tiny",
    "weasel":          "Weasel",

    # Vanilla good
    "athletic":        "Athletic",
    "bloodthirsty":    "Bloodthirsty",
    "brave":           "Brave",
    "bright":          "Bright",
    "determined":      "Determined",
    "dexterous":       "Dexterous",
    "eagle_eyes":      "Eagle Eyes",
    "fearless":        "Fearless",
    "huge":            "Huge",
    "iron_jaw":        "Iron Jaw",
    "iron_lungs":      "Iron Lungs",
    "loyal":           "Loyal",
    "lucky":           "Lucky",
    "optimist":        "Optimist",
    "quick":           "Quick",
    "spartan":         "Spartan",
    "strong":          "Strong",
    "sure_footing":    "Sure Footing",
    "survivor":        "Survivor",
    "swift":           "Swift",
    "teamplayer":      "Team Player",
    "tough":           "Tough",

    # Legends-added bad
    "legend_cannibalistic":   "Cannibalistic",
    "legend_deathly_spectre": "Deathly Spectre",
    "legend_double_tongued":  "Double Tongued",
    "legend_fear_dark":       "Nyctophobia",
    "legend_fear_nobles":     "Fear of Nobles",
    "legend_fleshless":       "Fleshless",
    "legend_heavy":           "Lumbering",
    "legend_predictable":     "Predictable",
    "legend_rotten_flesh":    "Rotting Flesh",
    "legend_slack":           "Slack",
    "legend_withering_aura":  "Withering Aura",

    # Legends-added good
    "legend_aggressive":      "Aggressive",
    "legend_ambitious":       "Ambitious",
    "legend_arena_champion":  "Arena Champion",
    "legend_arena_invictus":  "Invictus",
    "legend_beastslayers":    "Natural Order",
    "legend_gift_of_people":  "Charming",
    "legend_martial":         "Martial",
    "legend_natural":         "Talented",
    "legend_pragmatic":       "Pragmatic",
    "legend_seductive":       "Seductive",
    "legend_steady_hands":    "Steady Hands",
    "legend_sureshot":        "Sureshot",
    "legend_undead_killer":   "Undead Killer",
    "legend_unpredictable":   "Unpredictable",

    # Combat-acquired (Legends)
    "noble_killer":           "Noble Killer",
    "undead_killer":          "Undead Killer",
    "hate_beasts":            "Hate Beasts",
    "hate_greenskins":        "Hate Greenskins",
    "hate_undead":            "Hate Undead",
    "legend_hate_nobles":     "Hate for Nobles",

    # Origin-baked / scenario / cosmetic
    "player":                          "Player Character",
    "cultist_acolyte":                 "Cultist Acolyte",
    "cultist_chosen":                  "Cultist Chosen",
    "cultist_disciple":                "Cultist Disciple",
    "cultist_fanatic":                 "Cultist Fanatic",
    "cultist_prophet":                 "Cultist Prophet",
    "cultist_zealot":                  "Cultist Zealot",
    "legend_intensive_training_trait": "Intensive Training",
    "legend_lw_relationship":          "Lone Wolf Relationship",
    "legend_brothers_in_chains":       "United in Chains",
    "legend_appetite_donkey":          "Appetite of a Donkey",
    "legend_inquisition_disciple":     "Disciple of the Inquisition",
    "legend_horse":                    "Horse",
    "legend_necromancer":              "Necromancer",
    "legend_nomad":                    "Nomad",
    "legend_peasant":                  "Peasant",
    "legend_light":                    "Light",

    # Prosthetics (acquired via amputation)
    "legend_prosthetic_ear":     "Prosthetic Ear",
    "legend_prosthetic_eye":     "Prosthetic Eye",
    "legend_prosthetic_finger":  "Prosthetic Finger",
    "legend_prosthetic_foot":    "Prosthetic Foot",
    "legend_prosthetic_forearm": "Prosthetic Forearm",
    "legend_prosthetic_hand":    "Prosthetic Hand",
    "legend_prosthetic_leg":     "Prosthetic Leg",
    "legend_prosthetic_nose":    "Prosthetic Nose",

    # Paladin oaths
    "oath_of_camaraderie":    "Oath of Camaraderie",
    "oath_of_distinction":    "Oath of Distinction",
    "oath_of_dominion":       "Oath of Dominion",
    "oath_of_endurance":      "Oath of Endurance",
    "oath_of_fortification":  "Oath of Fortification",
    "oath_of_honor":          "Oath of Honor",
    "oath_of_humility":       "Oath of Humility",
    "oath_of_righteousness":  "Oath of Righteousness",
    "oath_of_sacrifice":      "Oath of Sacrifice",
    "oath_of_valor":          "Oath of Valor",
    "oath_of_vengeance":      "Oath of Vengeance",
    "oath_of_wrath":          "Oath of Wrath",

    # Arena / situational
    "arena_fighter":          "Arena Fighter",
    "arena_veteran":          "Arena Veteran",
    "pit_fighter":            "Pit Fighter",
    "old":                    "Old",
    "night_owl":              "Night Owl",
    "glorious":               "Glorious Endurance",
    "deathwish":              "Deathwish",
}

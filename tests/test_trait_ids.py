"""Every trait ID the tool ships must be a real Legends trait. The search only
compares a bro's `trait.*` skills, so a perk ID (colossus, fortified_mind,
steel_brow) or a misspelling (night_blindness) in a list can never match.

LEGENDS_TRAIT_IDS = every `ID = "trait.X"` in Legends 19.4.22
mod_legends/!!config/trait_defs.nut (identical to 19.3.41). Refresh it when
checking a new Legends release.
"""
from bbreroll.criteria import DEFAULT_BANNED, DEFAULT_REQUIRED
from bbreroll.trait_names import TRAIT_NAMES

LEGENDS_TRAIT_IDS = frozenset({
    "addict", "ailing", "arena_fighter", "arena_veteran", "asthmatic", "athletic", "bleeder",
    "bloodthirsty", "brave", "bright", "brute", "clubfooted", "clumsy", "cocky", "craven",
    "cultist_acolyte", "cultist_chosen", "cultist_disciple", "cultist_fanatic",
    "cultist_prophet", "cultist_zealot", "dastard", "deathwish", "determined", "dexterous",
    "disloyal", "drunkard", "dumb", "eagle_eyes", "fainthearted", "fat", "fear_beasts",
    "fear_greenskins", "fear_undead", "fearless", "fragile", "glorious", "gluttonous", "greedy",
    "hate_beasts", "hate_greenskins", "hate_undead", "hesitant", "huge", "impatient",
    "insecure", "iron_jaw", "iron_lungs", "irrational", "legend_aggressive", "legend_ambitious",
    "legend_appetite_donkey", "legend_arena_champion", "legend_arena_invictus",
    "legend_beastslayers", "legend_brothers_in_chains", "legend_cannibalistic",
    "legend_deathly_spectre", "legend_double_tongued", "legend_fear_dark", "legend_fear_nobles",
    "legend_fleshless", "legend_gift_of_people", "legend_hate_nobles", "legend_heavy",
    "legend_horse", "legend_inquisition_disciple", "legend_intensive_training_trait",
    "legend_light", "legend_lw_relationship", "legend_martial", "legend_natural",
    "legend_necromancer", "legend_nomad", "legend_peasant", "legend_pragmatic",
    "legend_predictable", "legend_prosthetic_ear", "legend_prosthetic_eye",
    "legend_prosthetic_finger", "legend_prosthetic_foot", "legend_prosthetic_forearm",
    "legend_prosthetic_hand", "legend_prosthetic_leg", "legend_prosthetic_nose",
    "legend_rotten_flesh", "legend_seductive", "legend_slack", "legend_steady_hands",
    "legend_sureshot", "legend_unpredictable", "legend_withering_aura", "loyal", "lucky", "mad",
    "night_blind", "night_owl", "noble_killer", "oath_of_camaraderie", "oath_of_distinction",
    "oath_of_dominion", "oath_of_endurance", "oath_of_fortification", "oath_of_honor",
    "oath_of_humility", "oath_of_righteousness", "oath_of_sacrifice", "oath_of_valor",
    "oath_of_vengeance", "oath_of_wrath", "old", "optimist", "paranoid", "pessimist",
    "pit_fighter", "player", "quick", "short_sighted", "spartan", "strong", "superstitious",
    "sure_footing", "survivor", "swift", "teamplayer", "tiny", "tough", "undead_killer",
    "weasel",
})


def test_oracle_size():
    assert len(LEGENDS_TRAIT_IDS) == 129


def test_default_banned_are_real_traits():
    assert sorted(set(DEFAULT_BANNED) - LEGENDS_TRAIT_IDS) == []


def test_default_required_are_real_traits():
    assert sorted(set(DEFAULT_REQUIRED) - LEGENDS_TRAIT_IDS) == []


def test_trait_names_keys_are_real_traits():
    assert sorted(set(TRAIT_NAMES) - LEGENDS_TRAIT_IDS) == []

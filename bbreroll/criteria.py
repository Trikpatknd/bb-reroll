"""The search criteria as the GUI holds them: default trait lists, the criteria dict the
offline search takes, and the checks made before a search starts.

Tkinter-free so it is unit-tested (tests/test_criteria.py).

A criteria dict:
    {"stars_by_slot": {"*": {stat: min}, "1": {stat: min}, ...},   # slot = roster position
     "banned": [trait ids], "required": [trait ids], "required_mode": "any" | "all"}
A numeric slot row replaces the "*" row for that brother (it is not merged with it).
"""
import re

STATS = ["hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf"]

# Legends-aware trait categorization. IDs are the game's `trait.X` skill IDs without the
# `trait.` prefix. The defaults reflect a typical "strong roll, no glaring flaws" preset —
# every one of them can be unticked, renamed or removed in the GUI.
DEFAULT_BANNED = [
    # Vanilla bad traits (33)
    "addict", "ailing", "asthmatic", "bleeder", "brute", "clubfooted", "clumsy",
    "cocky", "craven", "dastard", "disloyal", "drunkard", "dumb", "fainthearted",
    "fat", "fear_beasts", "fear_greenskins", "fear_undead", "fragile",
    "gluttonous", "greedy", "hesitant", "impatient", "insecure", "irrational",
    "mad", "night_blind", "paranoid", "pessimist", "short_sighted",
    "superstitious", "tiny", "weasel",
    # Legends-added bad traits (11)
    "legend_cannibalistic", "legend_deathly_spectre", "legend_double_tongued",
    "legend_fear_dark", "legend_fear_nobles", "legend_fleshless", "legend_heavy",
    "legend_predictable", "legend_rotten_flesh", "legend_slack",
    "legend_withering_aura",
]
DEFAULT_REQUIRED = [
    # Vanilla good traits (22)
    "athletic", "bloodthirsty", "brave", "bright", "determined", "dexterous",
    "eagle_eyes", "fearless", "huge", "iron_jaw", "iron_lungs", "loyal", "lucky",
    "optimist", "quick", "spartan", "strong", "sure_footing", "survivor", "swift",
    "teamplayer", "tough",
    # Legends-added good traits (13)
    "legend_aggressive", "legend_ambitious", "legend_arena_champion",
    "legend_arena_invictus", "legend_beastslayers", "legend_gift_of_people",
    "legend_martial", "legend_natural", "legend_pragmatic", "legend_seductive",
    "legend_steady_hands", "legend_sureshot",
    "legend_unpredictable",
]


def default_criteria() -> dict:
    """What a fresh install starts with: the default lists, nothing ticked off, no stars."""
    return {"stars_by_slot": {"*": {}}, "banned": list(DEFAULT_BANNED), "required": list(DEFAULT_REQUIRED),
            "required_mode": "any"}


def is_trivial(criteria: dict) -> bool:
    """No stars and no traits asked for: every seed matches."""
    any_star = any(any(v > 0 for v in s.values()) for s in criteria["stars_by_slot"].values())
    return not (any_star or criteria["required"] or criteria["banned"])


def to_int(text):
    """int(text), or None when it is not a whole number."""
    try:
        return int(str(text).strip())
    except ValueError:
        return None


def number_errors(values: dict, cpu_threads: int) -> list:
    """Problems with the numeric search settings ({"Max seeds": n, "Stop after matches": n,
    "Workers": n}, None = not a number), as messages for the player; empty when fine."""
    errors = ["%s must be a whole number of at least 1." % name for name, v in values.items() if v is None or v < 1]
    if not errors and values.get("Workers", 1) > cpu_threads:
        errors.append("Workers: this PC has %d CPU threads." % cpu_threads)
    return errors


def sanitize_trait(name: str) -> str:
    """A typed trait name as a trait ID ([a-z0-9_]): 'Iron Lungs' -> 'iron_lungs'."""
    s = name.strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s.strip("_")


def id_to_display(trait_id: str) -> str:
    """Fallback display name for a trait ID without a known name: strips `legend_` and
    title-cases the rest. 'legend_steady_hands' -> 'Steady Hands'."""
    s = trait_id
    if s.startswith("legend_"):
        s = s[len("legend_"):]
    return s.replace("_", " ").title() if s else trait_id


def roster_lines(roster) -> list:
    """One compact line per recruit for the result list."""
    out = []
    for i, bro in enumerate(roster, 1):
        stars = " ".join("%s%d" % (k, v) for k, v in bro["stars"].items() if v) or "no stars"
        out.append("%2d. %s (%s)  [%s]  %s" % (
            i, bro["name"], bro["background_name"].replace("Background: ", ""), stars,
            ", ".join(bro["trait_names"]) or "no traits"))
    return out

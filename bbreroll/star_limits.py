"""What talent stars an origin's brothers can have at all, for the GUI: the info text above the
stars grid, the stars to pre-fill, the highest value each grid cell can take, and the criteria
that no seed can ever meet. The facts come from the game's own scripts (bbseed/catalog.py,
bbseed/talents.py); this module only reads them. tkinter-free, unit-tested.

A slot's facts (one dict per brother slot):
  most      how many stats can have stars at the same time
  picks     how many of them the talent roll chooses (the rest are fixed)
  max       {stat: highest stars possible}, 0 = never
  fixed     {stat: stars} the origin sets the same way on every seed
  rolled    [stats the roll can star] — each of them can reach 3
  varied    the slot's background changes from seed to seed: then the facts are only what the
            samples happened to show, so nothing is ruled out for that brother
"""
from bbreroll.criteria import STATS


def slots_for(catalog, script):
    """The slot facts of one origin (list, slot 1 first), or None if the catalog has none."""
    if not catalog:
        return None
    found = (catalog.get("talents") or {}).get(script)
    if not found or "error" in found:
        return None
    return found.get("slots") or None


def sizes_for(catalog, script):
    found = (catalog or {}).get("talents", {}).get(script) or {}
    return found.get("sizes") or []


def _need_for(stars_by_slot, slot):
    """A slot's own row replaces the "*" row (BB Reroll's rule); an empty row is no row."""
    return stars_by_slot.get(str(slot)) or stars_by_slot.get("*") or {}


def problems(slots, stars_by_slot):
    """Why no seed can meet these star criteria, as sentences (empty: possible).

    Checks per brother: a stat asked above what the slot can ever have; more starred stats
    than the slot can have; more stats than the roll can star besides the fixed ones."""
    out = []
    for n, facts in enumerate(slots or (), 1):
        need = {s: int(v) for s, v in _need_for(stars_by_slot, n).items() if int(v) > 0}
        if not need or facts.get("varied"):
            continue
        too_high = [s for s in STATS if s in need and need[s] > facts["max"][s]]
        for stat in too_high:
            top = facts["max"][stat]
            why = ("never gets %s stars" % stat.upper() if top == 0 else
                   "has %s fixed at %d" % (stat.upper(), top) if stat in facts["fixed"] else
                   "gets at most %d %s stars" % (top, stat.upper()))
            out.append("Brother %d %s — you ask for %d." % (n, why, need[stat]))
        if too_high:
            continue        # one reason per brother is enough
        if len(need) > facts["most"]:
            out.append("Brother %d can have stars in at most %d stats — you ask for %d." % (n, facts["most"], len(need)))
            continue
        rolled = [s for s in need if not (s in facts["fixed"] and facts["fixed"][s] >= need[s])]
        if len(rolled) > facts["picks"]:
            fixed = ", ".join("%s %d" % (s.upper(), v) for s, v in facts["fixed"].items())
            out.append("Brother %d: the roll stars only %d stat%s%s — you ask for %d (%s)." % (
                n, facts["picks"], "" if facts["picks"] == 1 else "s",
                " besides the fixed %s" % fixed if fixed else "", len(rolled),
                ", ".join(s.upper() for s in rolled)))
    return out


def prefill(slots):
    """{slot number (str): {stat: stars}} — the stars an origin fixes, to pre-fill the grid."""
    return {str(n): dict(facts["fixed"]) for n, facts in enumerate(slots or (), 1) if facts["fixed"]}


def cell_max(slots, slot, stat):
    """The highest value worth offering in a grid cell: 3 for the "*" row and for slots the
    facts do not cover (an origin whose roster size varies)."""
    if slot == "*" or not slots:
        return 3
    n = int(slot)
    if n > len(slots) or slots[n - 1].get("varied"):
        return 3
    return slots[n - 1]["max"][stat]


ROLL_LEVELS = ("any", "mid", "high")


def roll_options(slots, slot, stat):
    """What a stat-roll cell can ask for: "any" only when the seed cannot move that stat for
    that brother (his background's range for it is a single value), else any / mid / high.
    Everything for the "*" row, for slots the facts do not cover and for varied slots."""
    if slot == "*" or not slots:
        return list(ROLL_LEVELS)
    n = int(slot)
    if n > len(slots):
        return list(ROLL_LEVELS)
    facts = slots[n - 1]
    if facts.get("varied") or "spread" not in facts:
        return list(ROLL_LEVELS)
    return list(ROLL_LEVELS) if stat in facts["spread"] else ["any"]


def roll_problems(slots, tiers_by_slot):
    """Stat-roll criteria the seed can never meet: a stat the brother's background rolls as a
    single value (sentences, empty: possible)."""
    out = []
    for n, facts in enumerate(slots or (), 1):
        if facts.get("varied") or "spread" not in facts:
            continue
        want = tiers_by_slot.get(str(n)) or tiers_by_slot.get("*") or {}
        fixed = [s for s, level in want.items() if level in ("mid", "high") and s not in facts["spread"]]
        if fixed:
            out.append("Brother %d's %s %s always the same — the seed cannot make %s better." % (
                n, ", ".join(s.upper() for s in fixed), "is" if len(fixed) == 1 else "are",
                "it" if len(fixed) == 1 else "them"))
    return out


def describe(slots, sizes=None):
    """The info text above the stars grid."""
    if not slots:
        return ""
    texts = []
    for facts in slots:
        if facts.get("varied"):
            texts.append("background varies by seed — stars in up to %d stats seen" % facts["most"])
            continue
        fixed = "  ".join("%s %d" % (s.upper(), v) for s, v in facts["fixed"].items())
        never = [s.upper() for s in STATS if facts["max"][s] == 0]
        parts = []
        if fixed:
            parts.append("fixed %s" % fixed)
        if facts["picks"]:
            parts.append("%s%d rolled" % ("+ " if fixed else "", facts["picks"]))
        elif not fixed:
            parts.append("no stars")
        text = " ".join(parts)
        if facts["picks"] and never:
            text += "  · never %s" % " ".join(never)
        texts.append(text)
    lines = []
    if sizes and len(sizes) > 1:
        lines.append("Roster size varies: %s brothers." % ", ".join(str(s) for s in sizes))
    first = 0
    for n in range(1, len(texts) + 1):        # brothers in a row with the same facts share a line
        if n == len(texts) or texts[n] != texts[first]:
            label = "Brother %d" % (first + 1) if n - first == 1 else "Brothers %d–%d" % (first + 1, n)
            lines.append("%s: %s" % (label, texts[first]))
            first = n
    return "\n".join(lines)

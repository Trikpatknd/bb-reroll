"""Which backgrounds an origin's brothers can have, for the GUI's Backgrounds view: the choices per
brother, the "any brother" row, and background conditions no seed can meet. The facts come from
the game's own scripts (bbseed/catalog.py, bbseed/talents.py: the lists the origin hands
setStartValuesEx); this module only reads them. tkinter-free, unit-tested.

Most origins give each brother a fixed background. Only some (Legends' Free Company, Random
Party / Trio / Solo, both games' Peasant Militia) pick a brother's background with the seed —
only there is a background a condition.
"""
from bbreroll.star_limits import slots_for

ANY_BROTHER = "any"         # the same key as bbseed.search.ANY_BROTHER (kept free of the engine import)


def names_for(catalog, script):
    """{background id: name} of every background the origin's brothers can get ({} if unknown)."""
    found = (catalog or {}).get("talents", {}).get(script) or {}
    return dict(found.get("background_names") or {})


def display(background, names=None):
    """A background's name: from the catalog, else made from its id
    ("background.legend_noble_2h" -> "Noble 2H")."""
    if names and background in names:
        return names[background]
    s = background[len("background."):] if background.startswith("background.") else background
    if s.startswith("legend_"):
        s = s[len("legend_"):]
    return s.replace("_", " ").title() if s else background


def _menu(ids, names):
    """[(id, name)] by name; two backgrounds with the same name get their id added (the menus map
    names back to ids)."""
    pairs = [(b, display(b, names)) for b in ids]
    count = {}
    for _b, name in pairs:
        count[name] = count.get(name, 0) + 1
    pairs = [(b, name if count[name] == 1 else "%s (%s)" % (name, b[len("background."):])) for b, name in pairs]
    return sorted(pairs, key=lambda p: (p[1].lower(), p[0]))


def choices(slots, names=None):
    """Per brother slot: [(id, name)] of the backgrounds he can get, by name (one entry: fixed)."""
    return [_menu(facts.get("choices") or facts.get("backgrounds") or [], names) for facts in slots or ()]


def varied(slots):
    """Brother numbers (1 = first) whose background changes with the seed."""
    return [n for n, facts in enumerate(slots or (), 1) if len(facts.get("choices") or facts.get("backgrounds") or []) > 1]


def any_choices(slots, names=None):
    """[(id, name)] for the "any brother" row — every background a varied brother can get — or []
    when fewer than two brothers vary (then the brother's own row says the same)."""
    rows = varied(slots)
    if len(rows) < 2:
        return []
    ids = set()
    for n in rows:
        facts = slots[n - 1]
        ids.update(facts.get("choices") or facts.get("backgrounds") or [])
    return _menu(ids, names)


def problems(slots, backgrounds_by_slot, names=None):
    """Background conditions no seed can meet, as sentences (empty: possible). Only lists known
    to be complete rule a background out."""
    out = []
    for slot, wanted in sorted((backgrounds_by_slot or {}).items(), key=lambda kv: -1 if kv[0] == ANY_BROTHER else int(kv[0])):
        if not wanted:
            continue
        if slot == ANY_BROTHER:
            possible = {b for b, _name in any_choices(slots, names)} or {
                b for row in choices(slots, names) for b, _name in row}
            if slots and not possible & set(wanted):
                out.append("No brother of this origin can have the background %s." % _or(wanted, names))
            continue
        n = int(slot)
        if not slots or n > len(slots):
            continue
        facts = slots[n - 1]
        can = set(facts.get("choices") or facts.get("backgrounds") or [])
        if can & set(wanted) or not facts.get("choices_exact", False) and len(can) > 1:
            continue
        if len(can) == 1:
            name = display(next(iter(can)), names)
            out.append("Brother %d is always %s %s. Your condition is %s." % (
                n, "an" if name[:1].upper() in "AEIOU" else "a", name, _or(wanted, names)))
        else:
            out.append("Brother %d cannot have the background %s." % (n, _or(wanted, names)))
    return out


def _or(ids, names):
    return " or ".join(display(b, names) for b in ids)


def describe(slots, names=None):
    """The info text above the Backgrounds view."""
    if not slots:
        return ""
    rows = varied(slots)
    if not rows:
        return "The seed does not change the backgrounds of this origin. Each brother always has the same background."
    which = ", ".join(str(n) for n in rows)
    text = "The seed selects the background of brother%s %s." % ("" if len(rows) == 1 else "s", which)
    if any(not slots[n - 1].get("choices_exact", False) for n in rows):
        text += " Some lists show only the backgrounds that BB Reroll saw. Other backgrounds are possible."
    return text

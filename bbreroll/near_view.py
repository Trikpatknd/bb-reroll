"""The closest seed's differences (bbseed/nearness.py) as short lines for the player: the near card and the seed post.
No tkinter."""
from bbreroll.backgrounds import display as background_name
from bbreroll.criteria import id_to_display
from bbseed.mapgen import PORT_LABELS, TOWN_TYPE_LABELS

TITLE = "Closest seed so far: not an exact match"
NOT_CHECKED = "Not checked yet"
NOT_CHECKED_TIP = "BB Reroll did not roll this seed a second time. Check it before you use it."
_MAP_LABELS = {**PORT_LABELS, **TOWN_TYPE_LABELS}


def _line(d, display_for, background_names):
    slot, kind, name, have, want = d["slot"], d["kind"], d["name"], d["have"], d["want"]
    if kind == "stars":
        return "Brother %d: %s has %d star%s. The condition is %d." % (
            slot, name.upper(), have, "" if have == 1 else "s", want)
    if kind == "roll":
        return "Brother %d: the %s roll is %s. The condition is %s." % (
            slot, name.upper(), have if have else "not known", want)
    if kind == "banned":
        return "Brother %d has the banned trait %s." % (slot, display_for(name))
    if kind == "required":
        if name:
            return "Brother %d does not have the required trait %s." % (slot, display_for(name))
        return "Brother %d has none of the required traits." % slot
    if kind == "background":
        if slot is None:
            return "No brother has a background from the conditions."
        return "Brother %d has the background %s. The condition is a different background." % (
            slot, background_name(name, background_names))
    if kind == "map":
        return "%s: %d. The condition is %d." % (_MAP_LABELS.get(name, name), have, want)
    if kind == "slot":
        return "This origin has no brother %d." % slot
    return "%s %s" % (kind, name)


def lines(differences, display_for=None, background_names=None):
    """One line per difference, in the given order: "Brother 2: RES has 1 star. The condition is 2.",
    "Brother 1 has the banned trait Dumb.", "Ports: 4. The condition is 5."."""
    return [_line(d, display_for or id_to_display, background_names) for d in differences]

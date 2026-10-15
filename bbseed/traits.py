"""What each character trait does, as the game's own tooltip says it.

Every trait the game can give a recruit is in ::Const.CharacterTraits ([id, script]); Legends
lists all of its traits in ::Legends.Traits.TraitDefObjects. Each one is created, put on a
stand-in recruit (some tooltips read the recruit) and asked for getTooltip(). The tooltip's
effect lines colour good values green and bad ones red — the base game with its UI colours
(#135213 / #8f1e1e), Legends also with %positive% / %negative% — so every line can be marked
as a positive or negative effect without a hand-written table, and it stays right for the
installed game and mod versions.
"""
import re

from .sq.runtime import SqError, tostring

_TOOLTIPS = """
local defs = [];
local seen = {};
foreach (pair in ::Const.CharacterTraits)
    if (!(pair[0] in seen)) { defs.push([pair[0], pair[1]]); seen[pair[0]] <- true; }
if ("Legends" in ::getroottable() && "Traits" in ::Legends && "TraitDefObjects" in ::Legends.Traits)
    foreach (d in ::Legends.Traits.TraitDefObjects)
        if (!(d.ID in seen)) { defs.push([d.ID, d.Script]); seen[d.ID] <- true; }
local roster = ::World.getPlayerRoster();
local bro = roster.create("scripts/entity/tactical/player");
bro.setStartValuesEx(["beggar_background"]);
local out = [];
foreach (d in defs)
{
    if (d[0].find("trait.") != 0) continue;
    local row = [d[0], null, null, null, null];
    try
    {
        local t = ::new(d[1]);
        bro.getSkills().add(t);
        row[1] = t.getName();
        row[2] = t.getDescription();
        local lines = [];
        foreach (e in t.getTooltip())
            if ("text" in e && "type" in e && e.type == "text") lines.push(e.text);
        row[3] = lines;
        bro.getSkills().removeByID(d[0]);
    }
    catch (err)
    {
        row[4] = "" + err;
    }
    out.push(row);
}
roster.remove(bro);
return out;
"""

POSITIVE = ("#135213", "%positive%")
NEGATIVE = ("#8f1e1e", "%negative%")
_COLOR = re.compile(r"\[color=([^\]]*)\]", re.I)
_TAG = re.compile(r"\[/?[a-z]+(=[^\]]*)?\]", re.I)


def effect(text):
    """One tooltip line -> {"sign": "+", "-" or "", "text": plain text}. The first coloured value
    decides: green is good, red is bad; a line without colours is neither."""
    sign = ""
    for colour in _COLOR.findall(text):
        colour = colour.strip().lower()
        if colour in POSITIVE:
            sign = "+"
            break
        if colour in NEGATIVE:
            sign = "-"
            break
    plain = " ".join(_TAG.sub("", text).split())
    return {"sign": sign, "text": plain}


def plain(text):
    return " ".join(_TAG.sub("", text or "").split())


def tooltips(lab):
    """{trait id without "trait.": {"name", "description", "effects": [effect()...]}} for every
    trait the loaded game knows. Call inside big_stack(), on a lab between rosters."""
    eng = lab.eng
    try:
        rows = eng.vm.compile(_TOOLTIPS, "trait_tooltips").invoke(eng.root, ())
    except SqError:
        del eng.vm.stack[:]
        raise
    out = {}
    for tid, name, description, lines, error in rows:
        if error is not None:
            continue
        out[tostring(tid)[6:]] = {"name": tostring(name), "description": plain(tostring(description)),
                                  "effects": [effect(tostring(line)) for line in lines]}
    return out

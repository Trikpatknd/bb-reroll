"""How good a recruit's stat rolls are, measured against what his background can roll.

A recruit's base stats are rolled once, in character_background.buildAttributes(), from a range
per stat: the base game rolls once evenly in [low, high] (its own base ranges plus the
background's onChangeAttributes()); Legends rolls twice and averages, (rand + rand) / 2 in
integers, from Legends.Backgrounds.BaseAttr plus the female adjustment (Battle Sisters), the
background's onChangeAttributes() and the attributes of the recruit's perk trees. Measured on
15,000 Legends recruits, the background decides most of a stat; the seed only picks where in
that range the roll lands. So a roll's tier is its place in that background's own distribution:

  low    bottom third of the rolls that background can make
  mid    middle third
  high   top third

(by probability, the middle counted half: a value's place is P(roll < value) + P(roll = value)/2).
A stat whose range is a single value has no tier ("fixed").

The ranges are only known inside buildAttributes, so it is wrapped — in the class and in every
copy of it that derived backgrounds already hold — to record, per recruit, the ranges and the
values it rolled. The wrapper reads the ranges from the same tables the game uses and draws no
random numbers, so the roster stays exactly the same (tests/test_game_features.py checks this).
"""
from .sq.runtime import tostring

STATS = ("hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf")
_GAME = ("Hitpoints", "Stamina", "Bravery", "Initiative", "MeleeSkill", "RangedSkill", "MeleeDefense", "RangedDefense")
TIERS = ("low", "mid", "high")

# The wrapper. vargv[0]: the class tables to patch (character_background and its copies).
# Legends' range: sum() normalises every [a, b] to [min, max] before adding, as in its buildAttributes.
_WRAP = """
local tables = vargv[0];
if (!("BBR_RollLog" in ::getroottable())) ::BBR_RollLog <- [];
local names = ["Hitpoints", "Stamina", "Bravery", "Initiative", "MeleeSkill", "RangedSkill", "MeleeDefense", "RangedDefense"];
local legends = "Legends" in ::getroottable() && "Backgrounds" in ::Legends && "BaseAttr" in ::Legends.Backgrounds;
local add = function (a, b)
{
    local out = {};
    foreach (k, v in a)
    {
        local lo = v[0] < v[1] ? v[0] : v[1];
        local hi = v[0] < v[1] ? v[1] : v[0];
        if (b != null && k in b)
        {
            local w = b[k];
            lo += w[0] < w[1] ? w[0] : w[1];
            hi += w[0] < w[1] ? w[1] : w[0];
        }
        out[k] <- [lo, hi];
    }
    return out;
};
foreach (cls in tables)
{
    if ("BBR_RollWrapped" in cls) continue;
    local build = cls.buildAttributes;
    cls.BBR_RollWrapped <- true;
    cls.buildAttributes <- function (...)
    {
        local args = [this];
        args.extend(vargv);
        local ret = build.acall(args);
        local actor = this.getContainer().getActor();
        local a;
        if (legends)
        {
            local tag = vargv.len() > 0 ? vargv[0] : null;
            a = add(::Legends.Backgrounds.BaseAttr.resolve(tag), null);
            if (::Legends.Mod.ModSettings.getSetting("GenderEquality").getValue() == "Enabled" && actor.getGender() == 1)
                a = add(a, ::Legends.Backgrounds.BaseAttr.Female);
            a = add(a, this.onChangeAttributes());
            if (vargv.len() > 1 && vargv[1] != null)
                a = add(a, vargv[1]);
        }
        else
        {
            // the base game adds the background's [low, high] as they are
            a = {Hitpoints = [50, 60], Bravery = [30, 40], Stamina = [90, 100], MeleeSkill = [47, 57],
                 RangedSkill = [32, 42], MeleeDefense = [0, 5], RangedDefense = [0, 5], Initiative = [100, 110]};
            local c = this.onChangeAttributes();
            foreach (k, v in a)
                a[k] = [v[0] + c[k][0], v[1] + c[k][1]];
        }
        local b = actor.getBaseProperties();
        local ranges = [];
        local rolled = [];
        foreach (n in names)
        {
            ranges.push(a[n]);
            rolled.push(b[n]);
        }
        // logged by the background itself: the skill container hands out a weak reference to the
        // actor, which never equals the recruit in the roster; bro.getBackground() is this instance
        ::BBR_RollLog.push([this, ranges, rolled]);
        return ret;
    };
}
"""
# The last roll of every recruit, in roster order (Legends may call buildAttributes twice).
_TAKE = """
local out = [];
foreach (bro in ::World.getPlayerRoster().getAll())
{
    local found = null;
    local background = bro.getBackground();
    foreach (e in ::BBR_RollLog)
        if (e[0] == background) found = [e[1], e[2]];
    out.push(found);
}
::BBR_RollLog.clear();
return out;
"""


def distribution(lo, hi, averaged):
    """{value: probability} of one roll: once evenly in [lo, hi], or (Legends) the integer
    average of two such rolls, (a + b) / 2 truncated toward zero as Squirrel divides."""
    values = range(lo, hi + 1)
    n = len(values)
    if not averaged:
        return {v: 1 / n for v in values}
    out = {}
    for a in values:
        for b in values:
            s = a + b
            v = int(s / 2)          # truncation toward zero, also for negative sums
            out[v] = out.get(v, 0) + 1 / (n * n)
    return out


def place(lo, hi, value, averaged):
    """Where a rolled value sits among the background's possible rolls, 0..1 (None: no spread)."""
    if hi <= lo:
        return None
    dist = distribution(lo, hi, averaged)
    below = sum(p for v, p in dist.items() if v < value)
    return below + dist.get(value, 0) / 2


def tier(lo, hi, value, averaged):
    """"low", "mid", "high", or "fixed" when the range is a single value."""
    q = place(lo, hi, value, averaged)
    if q is None:
        return "fixed"
    return "low" if q < 1 / 3 else "high" if q > 2 / 3 else "mid"


def rolls_of(ranges, rolled, averaged):
    """{stat: {"lo", "hi", "value", "tier"}} for one recruit."""
    out = {}
    for stat, (lo, hi), value in zip(STATS, ranges, rolled):
        out[stat] = {"lo": lo, "hi": hi, "value": value, "tier": tier(lo, hi, value, averaged)}
    return out


def meets(have, want):
    """Does a rolled tier meet a minimum tier ("mid" = mid or high)? A stat with no spread
    ("fixed") cannot be chosen by the seed: it never meets a minimum."""
    if want not in TIERS or want == "low":
        return True
    return have in TIERS and TIERS.index(have) >= TIERS.index(want)


class RollWatch:
    """Makes a lab record every recruit's stat rolls. Call inside big_stack()."""

    def __init__(self, lab):
        eng = lab.eng
        base = eng.class_table("scripts/skills/backgrounds/character_background")
        tables = [base] + _copies(eng, base.get("ClassName"))
        eng.vm.compile(_WRAP, "rolls_wrap").invoke(eng.root, (tables,))
        self.probe = eng.vm.compile(_TAKE, "rolls_take")
        root = eng.root.d
        legends = root.get("Legends")
        self.averaged = legends is not None and "Backgrounds" in getattr(legends, "d", {})

    def attach(self, roster, taken):
        """Put each recruit's {"rolls": ...} into the roster (from the probe's result)."""
        for bro, found in zip(roster, taken):
            if found is not None:
                ranges, rolled = found
                bro["rolls"] = rolls_of([(int(r[0]), int(r[1])) for r in ranges], [int(v) for v in rolled],
                                        self.averaged)


def _copies(eng, name):
    """Every copy of class `name` that already-loaded classes hold (inherit() stores a copy of
    the base class in the derived one, so patching the base alone misses them)."""
    from .sq.runtime import SqTable
    out, seen = [], set()

    def walk(cls):
        if id(cls) in seen:
            return
        seen.add(id(cls))
        sup = cls.get("SuperName")
        if sup is None:
            return
        parent = cls.get(sup)
        if type(parent) is SqTable:
            if tostring(parent.get("ClassName") or "") == name:
                out.append(parent)
            walk(parent)

    for env in list(eng.envs.values()):
        for value in list(getattr(env, "d", {}).values()):
            if type(value) is SqTable and value.get("SuperName") is not None:
                walk(value)
    return out

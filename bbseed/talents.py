"""What talent stars an origin's brothers can get at all.

Every recruit's stars come from the player's fillTalentValues(): it picks stats that have no
star yet and that the background does not exclude, and gives each pick 1, 2 or 3 stars
(60 / 30 / 10 %, in the base game and in Legends). On top of that an origin or a background
can set stars itself, before the roll (Legends' Berserker: melee skill 3 and hitpoints 3, then
two forced picks) or after it, overwriting what was rolled (vanilla's A New Company, Legends'
Inquisition). So for each brother slot:

  rolled     stats the roll can give stars to: each of them can reach 3
  fixed      stars the origin's code sets, the same on every seed
  most       how many stats can have stars at the same time
  picks      how many of those the roll chooses

are facts of the scripts, not of luck. They are found by rolling a few seeds with
fillTalentValues wrapped: the wrapper records, for every call, the talents before and after
and what the call could choose from (stats without a star, minus the background's excluded
talents and, in Legends, the stats undead recruits cannot get; Legends' pick weights are never
0). A call whose picks survive to the final roster tells which stats the roll could have
starred; a call the origin overwrites afterwards tells nothing. More seeds are rolled only to
see every background an origin can give a slot.
"""
STATS = ("hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf")

# One log entry per fillTalentValues call: [entity, talents before, talents after, excluded talents,
# pick weights (Legends) or null, zombie?, skeleton?]. Vanilla's version takes no arguments,
# Legends' takes (_num, _force): pass them on as they come.
_WRAP = """
local cls = vargv[0];
if ("BBR_TalentLog" in ::getroottable()) return;
::BBR_TalentLog <- [];
local fill = cls.fillTalentValues;
cls.fillTalentValues <- function(...)
{
    local before = clone this.m.Talents;
    local background = this.getBackground();
    local excluded = background != null ? clone background.getExcludedTalents() : [];
    local weights = "StarWeights" in this.m ? clone this.m.StarWeights : null;
    local flags = this.getFlags();
    local args = [this];
    args.extend(vargv);
    local ret = fill.acall(args);
    ::BBR_TalentLog.push([this, before, clone this.m.Talents, excluded, weights,
                          flags.has("PlayerZombie"), flags.has("PlayerSkeleton")]);
    return ret;
};
"""
# The calls per recruit, in roster order.
_TAKE = """
local out = [];
foreach (bro in ::World.getPlayerRoster().getAll())
{
    local calls = [];
    foreach (e in ::BBR_TalentLog)
        if (e[0] == bro) calls.push(e.slice(1));
    out.push(calls);
}
::BBR_TalentLog.clear();
return out;
"""

# Legends' fillTalentValues skips these for undead recruits
_ZOMBIE_SKIPS = ("res", "fat", "init")
_SKELETON_SKIPS = ("res", "fat", "hp")


def _pad(talents, n):
    talents = list(talents)
    return talents + [0] * (n - len(talents))


def analyse(calls, stars, index):
    """One recruit: (rolled, fixed, can_roll).

    calls: [(before, after, excluded, weights, zombie, skeleton)] of every fillTalentValues call
    on this recruit; stars: {stat: final stars}; index: {stat: position in the talents array}.
    A call survives when every pick it made is still there in the final stars; when the origin
    sets stars after the roll, the roll's other picks are gone (a pick that equals what the
    origin sets is a coincidence, not a rolled star).
    rolled / fixed: the final stars split into those a surviving call made (and no later call
    changed) and those the origin's or background's code set.
    can_roll: the stats a surviving call could have starred instead — every stat it could
    choose from that the code did not fix afterwards."""
    n = len(index)
    final = [0] * n
    for stat, value in stars.items():
        final[index[stat]] = value
    surviving, last = [], {}
    for call in calls:
        before, after = _pad(call[0], n), _pad(call[1], n)
        picked = [i for i in range(n) if after[i] != before[i]]
        survives = bool(picked) and all(final[i] == after[i] for i in picked)
        for i in picked:
            last[i] = after[i] if survives else None
        if survives:
            surviving.append((before, call[2], call[3], call[4], call[5]))
    rolled, fixed = {}, {}
    for stat, value in stars.items():
        if value:
            (rolled if last.get(index[stat]) == value else fixed)[stat] = value
    can_roll = set()
    for before, excluded, weights, zombie, skeleton in surviving:
        skips = set(_ZOMBIE_SKIPS if zombie else ()) | set(_SKELETON_SKIPS if skeleton else ())
        for stat, i in index.items():
            if (before[i] == 0 and i not in excluded and stat not in skips and stat not in fixed
                    and (weights is None or i >= len(weights) or weights[i] > 0)):
                can_roll.add(stat)
    return rolled, fixed, can_roll


class SlotFacts:
    """What one brother slot of an origin showed over the samples.

    Fixed stars are the ones with the same value on every sample: a rolled star repeating on
    every seed is next to impossible (a pick has ~1 in 6 chances to be a given stat at a given
    level), while telling them apart call by call fails when an origin writes a star the roll
    happened to make already (Legends' Ranger sets MSK 2 / HP 2 after the roll, keeping the rest).
    Which stats the roll can star comes from the calls themselves (analyse(): can_roll)."""

    def __init__(self):
        self.samples = 0
        self.can_roll = set()          # stats a surviving roll could star
        self.values = {s: set() for s in STATS}    # final stars seen per stat
        self.starred = []              # per sample: the stats with stars
        self.backgrounds = set()
        self.spread = set()            # stats whose base roll has a range (rolls.py): the seed moves them

    def add(self, background, stars, can_roll, rolls=None):
        self.samples += 1
        self.backgrounds.add(background)
        self.can_roll.update(can_roll)
        for stat, r in (rolls or {}).items():
            if r["hi"] > r["lo"]:
                self.spread.add(stat)
        for stat in STATS:
            self.values[stat].add(stars.get(stat, 0))
        self.starred.append(frozenset(s for s in STATS if stars.get(s)))

    def _fixed(self):
        return {s: next(iter(v)) for s, v in self.values.items() if len(v) == 1 and next(iter(v)) > 0}

    def signature(self):
        """What the samples taught so far (a new background alone teaches nothing)."""
        return (frozenset(self.can_roll), tuple(sorted(self._fixed().items())),
                frozenset(len(s) for s in self.starred))

    def summary(self):
        """{"samples", "most" / "least": stats with stars, "picks": most stars besides the fixed
        ones, "max": {stat: highest stars possible}, "fixed": {stat: stars} the same on every
        seed, "rolled": [stats the roll can star], "backgrounds": [ids seen], "varied": does the
        background change from seed to seed (then the facts are only what the samples showed),
        "spread": [stats whose base roll the seed can move] (empty without roll data)}"""
        fixed = self._fixed()
        rolled = [s for s in STATS if s in self.can_roll and s not in fixed]
        top = {s: 3 if s in rolled else max(self.values[s]) for s in STATS}
        return {"samples": self.samples, "most": max(len(s) for s in self.starred),
                "least": min(len(s) for s in self.starred),
                "picks": max(len(s - fixed.keys()) for s in self.starred), "max": top, "fixed": fixed,
                "rolled": rolled, "backgrounds": sorted(self.backgrounds), "varied": len(self.backgrounds) > 1,
                "spread": [s for s in STATS if s in self.spread]}


class TalentWatch:
    """A lab whose recruits report which of their stars were rolled. Call inside big_stack()."""

    def __init__(self, lab):
        self.lab = lab
        eng = lab.eng
        cls = eng.class_table("scripts/entity/tactical/player")
        eng.vm.compile(_WRAP, "talents_wrap").invoke(eng.root, (cls,))
        self._take = eng.vm.compile(_TAKE, "talents_take")

    def roll(self, seed, origin):
        """(roster, [(rolled, fixed, can_roll) per recruit])."""
        roster, calls = self.lab.roster(seed, origin, fresh=False, probe=self._take)
        index = self.lab.attr_index
        out = []
        for bro, bro_calls in zip(roster, calls):
            plain = [(list(c[0]), list(c[1]), list(c[2]), None if c[3] is None else list(c[3]), c[4], c[5])
                     for c in bro_calls]
            out.append(analyse(plain, bro["stars"], index))
        return roster, out


def survey_seeds():
    """The seeds a survey rolls: fixed, so the same game gives the same answer."""
    n = 0
    while True:
        yield str(4000000000 + n * 7919)
        n += 1


def survey(watch, origin, least=12, most=100, calm=8, calm_varied=25):
    """Roll seeds for one origin until `calm` samples in a row taught nothing new (`calm_varied`
    when a slot has shown more than one background: its other backgrounds must get a chance to
    show up); at least `least`, at most `most` samples. Returns {"samples", "sizes": [roster sizes seen],
    "slots": [SlotFacts.summary() per slot]}. Raises LabError if the origin cannot be rolled."""
    slots, sizes, quiet = [], set(), 0
    for n, seed in enumerate(survey_seeds(), 1):
        roster, split = watch.roll(seed, origin)
        before = (frozenset(sizes), tuple(s.signature() for s in slots))
        sizes.add(len(split))
        while len(slots) < len(split):
            slots.append(SlotFacts())
        for facts, bro, (_rolled, _fixed, can_roll) in zip(slots, roster, split):
            facts.add(bro["background"], bro["stars"], can_roll, bro.get("rolls"))
        quiet = quiet + 1 if (frozenset(sizes), tuple(s.signature() for s in slots)) == before else 0
        varied = len(sizes) > 1 or any(len(s.backgrounds) > 1 for s in slots)
        if n >= most or (n >= least and quiet >= (calm_varied if varied else calm)):
            return {"samples": n, "sizes": sorted(sizes), "slots": [s.summary() for s in slots]}

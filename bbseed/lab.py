"""The game, minus the game: load a profile's scripts and ask what starting
roster a seed gives.

    from bbseed.lab import Lab, big_stack
    def work():
        lab = Lab("vanilla")
        for bro in lab.roster("1234567890", "early_access_scenario"):
            print(bro["name"], bro["traits"])
    big_stack(work)

`roster()` does what an unmodded campaign start does after world generation:
Math.seedRandomString(seed), then Assets.setCampaignSettings(settings) — which
runs the origin's onSpawnAssets() and re-rolls descriptions and level-up values.
Verified against the real game (BB 1.5.2.3, "A New Company", seed 1234567890).

The script interpreter recurses deeply: call into a Lab only from a thread
started by big_stack().
"""
import gc
import sys
import threading

from . import profiles
from .engine import Engine
from .sq import runtime as R
from .sq.runtime import SqError, SqTable, call, tostring
from .world import World

ATTRIBUTES = {"hp": "Hitpoints", "fat": "Fatigue", "res": "Bravery", "init": "Initiative",
              "msk": "MeleeSkill", "rsk": "RangedSkill", "mdf": "MeleeDefense", "rdf": "RangedDefense"}

# the settings table the new-campaign menu hands over (new_campaign_menu_module.parseSettingsFromJS);
# none of the options except the origin and the seed enters the roster's random draws
_START = """
local settings = {
    Name = "Battle Brothers", Banner = "banner_01", Difficulty = 1, EconomicDifficulty = 1, BudgetDifficulty = 1,
    Ironman = false, ExplorationMode = false, GreaterEvil = 0, PermanentDestruction = true,
    Seed = vargv[0], StartingScenario = vargv[1]
};
::World.State.m.CampaignSettings = settings;
::Math.seedRandomString(settings.Seed);
::World.Assets.setCampaignSettings(settings);
"""
# Quick reset between seeds when the world state is reused (search loop): what BB Reroll's own
# loop resets. Some origins shrink the stash on every start (Lone Wolf, Gladiators), so its
# capacity is put back too. A match is always confirmed on a freshly built world state.
_CLEANUP = """
local roster = ::World.getPlayerRoster();
foreach (bro in roster.getAll()) roster.remove(bro);
local stash = ::World.Assets.getStash();
stash.clear();
stash.resize(vargv[0]);
if ("MSU" in ::getroottable() && "__entityUIDMap" in ::MSU) ::MSU.__entityUIDMap.clear();   // one dead entry per recruit otherwise
local a = ::World.Assets;
a.m.Money = 0; a.m.Ammo = 0; a.m.Medicine = 0; a.m.ArmorParts = 0; a.m.BusinessReputation = 0; a.m.MoralReputation = 0;
"""
_REPORT = """
local out = [];
foreach (bro in ::World.getPlayerRoster().getAll())
{
    local traits = [];
    local trait_names = [];
    foreach (s in bro.getSkills().m.Skills)
    {
        if (s.isType(::Const.SkillType.Trait) && !s.isType(::Const.SkillType.Background) && s.getID().find("trait.") == 0)
        {
            traits.push(s.getID().slice(6));
            trait_names.push(s.getName());
        }
    }
    local b = bro.getBaseProperties();
    local c = bro.getCurrentProperties();
    local gear = [];
    foreach (slot in [::Const.ItemSlot.Mainhand, ::Const.ItemSlot.Offhand, ::Const.ItemSlot.Body, ::Const.ItemSlot.Head,
                      ::Const.ItemSlot.Ammo, ::Const.ItemSlot.Accessory])
    {
        local item = bro.getItems().getItemAtSlot(slot);
        if (item != null && item != -1) gear.push(item.getName());
    }
    foreach (item in bro.getItems().getAllItemsAtSlot(::Const.ItemSlot.Bag))
        if (item != null && item != -1) gear.push(item.getName() + " (bag)");
    out.push({
        name = bro.getName(), background = bro.getBackground().getID(), background_name = bro.getBackground().getName(),
        level = bro.getLevel(), talents = bro.getTalents(), traits = traits, trait_names = trait_names, gear = gear,
        base_stats = [b.Hitpoints, b.Stamina, b.Bravery, b.Initiative, b.MeleeSkill, b.RangedSkill, b.MeleeDefense, b.RangedDefense],
        shown_stats = [bro.getHitpointsMax(), bro.getFatigueMax(), bro.getBravery(), bro.getInitiative(), c.getMeleeSkill(),
                 c.getRangedSkill(), c.getMeleeDefense(), c.getRangedDefense()]
    });
}
return out;
"""
STAT_ORDER = ("hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf")      # order of the `base` / `shown` lists

# After the roster exists the game still runs the origin's onSpawnPlayer() (it places the company
# on the generated map, which the lab does not have). Where that step also touches the recruits,
# the lab repeats that part so the roster it reports is the one the player sees.
#   Noble: every recruit's body armor gets a noble tabard in the house's colours (+3 resolve).
#   Found by the in-game batch of 2026-10-13: everything matched except resolve, 3 lower in the lab.
_POST_SPAWN = {
    "legends_noble_scenario": """
foreach (bro in ::World.getPlayerRoster().getAll())
{
    local armor = bro.getItems().getItemAtSlot(::Const.ItemSlot.Body);
    local tabard = ::Const.World.Common.pickLegendArmor([[0, ""], [1, "tabard/legend_armor_tabard_noble"]]);
    if (tabard != null && armor != null)
    {
        tabard.setVariant(1);      // the house banner: looks only, depends on the map
        armor.setUpgrade(tabard);
    }
    bro.getSkills().update();
}
""",
}


def big_stack(fn, megabytes=200):
    """Run fn() in a thread whose stack is large enough for the script interpreter."""
    sys.setrecursionlimit(100000)
    threading.stack_size(megabytes * 1024 * 1024)
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as e:      # hand the exception to the caller's thread
            box["error"] = e

    t = threading.Thread(target=run)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


class LabError(Exception):
    pass


class Lab:
    def __init__(self, profile=None, mod_settings=None, extra_roots=()):
        """mod_settings: {"mod_id:SettingID": value} applied on top of the mods' defaults.
        extra_roots: further script folders (an extra mod), searched before the profile's."""
        roots, version = profiles.get(profile)
        roots = list(extra_roots) + list(roots)
        self.profile = profile or profiles.DEFAULT
        self.eng = eng = Engine(roots, game_version=version)
        eng.boot()
        if eng.errors:
            raise LabError("%d script files failed to load, first: %s -> %s" % (
                len(eng.errors), eng.errors[0][0], eng.errors[0][1][:200]))
        self.world = World(eng, discover=True).start()
        self._start = eng.vm.compile(_START, "lab_start")
        self._cleanup = eng.vm.compile(_CLEANUP, "lab_cleanup")
        self._report = eng.vm.compile(_REPORT, "lab_report")
        attrs = R.get(eng.root.get("Const"), "Attributes")
        self.attr_index = {short: R.get(attrs, long) for short, long in ATTRIBUTES.items()}
        self._scenarios = {}
        self._stash_capacity = eng.vm.compile("return ::World.Assets.getStash().getCapacity();", "lab_cap").invoke(eng.root, ())
        for key, value in (mod_settings or {}).items():
            mod_id, setting = key.split(":", 1)
            self.set_mod_setting(mod_id, setting, value)
        # The loaded scripts are ~10 million long-lived objects. Left in the collector's care they
        # make every full collection slow AND rare (it waits for 25% growth), while each roster
        # leaves reference cycles behind that only a full collection frees. Freezing takes the
        # loaded scripts out of the collector's view, so collections stay quick and frequent.
        gc.collect()
        gc.freeze()
        gc.collect()

    # ------------------------------------------------------------------ mod settings
    def set_mod_setting(self, mod_id, setting, value):
        """Set an MSU mod setting (the in-game "Mod Options"), e.g.
        ("mod_legends", "GenderEquality", "Disabled"). A player's own choices there are
        part of what decides a roster; the lab starts from the mods' defaults."""
        if "getModSetting" not in self.eng.root.d:
            raise LabError("this profile has no mod settings (MSU is not loaded)")
        try:
            self.eng.vm.compile("::getModSetting(vargv[0], vargv[1]).set(vargv[2]);", "lab_set").invoke(
                self.eng.root, (mod_id, setting, value))
        except SqError as e:
            del self.eng.vm.stack[:]
            raise LabError("mod setting %s:%s = %r: %s" % (mod_id, setting, value, tostring(e.value)))

    def get_mod_setting(self, mod_id, setting):
        try:
            return self.eng.vm.compile("return ::getModSetting(vargv[0], vargv[1]).getValue();", "lab_get").invoke(
                self.eng.root, (mod_id, setting))
        except SqError as e:
            del self.eng.vm.stack[:]
            raise LabError("mod setting %s:%s: %s" % (mod_id, setting, tostring(e.value)))

    # ------------------------------------------------------------------ origins
    def origins(self):
        """Origins the new-campaign menu offers: list of (script name, scenario id, title)."""
        mgr = R.get(self.eng.root.get("Const"), "ScenarioManager")
        out = []
        for s in R.get(R.get(mgr, "m"), "Scenarios"):
            out.append((s.get("ClassName"), call(R.get(s, "getID"), s, ()), tostring(R.get(R.get(s, "m"), "Name"))))
        return out

    def scenario(self, origin):
        s = self._scenarios.get(origin)
        if s is None:
            s = self._scenarios[origin] = self.world.scenario(origin)
        return s

    def info(self):
        """What a seed found here is valid for: the game setup the lab loaded."""
        root = self.eng.root.d
        out = {"profile": self.profile, "game_version": self.eng.game_version, "legends_version": None,
               "legends_build": None, "battle_sisters": None}
        legends = root.get("Legends")
        if type(legends) is SqTable:
            out["legends_version"] = legends.get("Version")
            out["legends_build"] = legends.get("BuildName")
            try:
                out["battle_sisters"] = self.get_mod_setting("mod_legends", "GenderEquality")
            except LabError:
                pass
        return out

    # ------------------------------------------------------------------ rosters
    def roster(self, seed, origin, fresh=True):
        """The starting roster of a campaign with this seed text and origin.

        fresh=True builds a new world state first, like the game does for every new
        campaign — the authoritative answer. fresh=False reuses the current one after a
        quick reset: much faster, used to sift seeds; confirm anything it finds."""
        eng = self.eng
        if fresh:
            self.world.build_state()
            self.world.add_placeholder_settlements()
        try:
            scenario = self.scenario(origin)
            self._start.invoke(eng.root, (seed, scenario))
            post = _POST_SPAWN.get(scenario.get("ClassName"))
            if post is not None:
                eng.vm.compile(post, "lab_post_spawn").invoke(eng.root, ())
            bros = [self._bro(b) for b in self._report.invoke(eng.root, ())]
        except SqError as e:
            eng.vm.note_trace(0)
            trace = " > ".join(eng.vm.last_trace[-6:])
            del eng.vm.stack[:]
            try:
                self._cleanup.invoke(eng.root, (self._stash_capacity,))
            except SqError:
                del eng.vm.stack[:]
            raise LabError("seed %r, origin %r: %s (at %s)" % (seed, origin, tostring(e.value), trace))
        self._cleanup.invoke(eng.root, (self._stash_capacity,))
        return bros

    def _bro(self, t):
        talents = t.get("talents")
        return {
            "name": t.get("name"),
            "background": t.get("background"),
            "background_name": t.get("background_name"),
            "level": t.get("level"),
            "stars": {short: talents[i] for short, i in self.attr_index.items()},
            "traits": list(t.get("traits")),
            "trait_names": list(t.get("trait_names")),
            "gear": list(t.get("gear")),
            "base": dict(zip(STAT_ORDER, t.get("base_stats"))),
            "shown": dict(zip(STAT_ORDER, t.get("shown_stats"))),
        }


def describe(bro):
    """One recruit as text, the way a player would check it on the character screen."""
    stars = ", ".join("%s %d" % (k, v) for k, v in bro["stars"].items() if v) or "none"
    s = bro["shown"]
    return ("%s (%s), level %d\n"
            "      stars: %s\n"
            "      hitpoints %d, fatigue %d, resolve %d, initiative %d, melee skill %d, ranged skill %d, "
            "melee defense %d, ranged defense %d\n"
            "      traits: %s\n"
            "      gear: %s") % (
        bro["name"], bro["background_name"], bro["level"], stars,
        s["hp"], s["fat"], s["res"], s["init"], s["msk"], s["rsk"], s["mdf"], s["rdf"],
        ", ".join(bro["trait_names"]) or "none", ", ".join(bro["gear"]) or "none")

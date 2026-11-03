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

`world_map()` runs the game's own campaign start, map generation included, up to the generated
world (see mapgen.py); rosters do not use it.

The script interpreter recurses deeply: call into a Lab only from a thread
started by big_stack().
"""
import gc
import sys
import threading
from pathlib import Path

from . import gamedata, mapgen, profiles
from .engine import Engine
from .sq import runtime as R
from .sq.runtime import NativeFn, SqError, SqTable, call, tostring
from .world import World

ATTRIBUTES = {"hp": "Hitpoints", "fat": "Fatigue", "res": "Bravery", "init": "Initiative",
              "msk": "MeleeSkill", "rsk": "RangedSkill", "mdf": "MeleeDefense", "rdf": "RangedDefense"}

# the settings table the new-campaign menu hands over (new_campaign_menu_module.parseSettingsFromJS);
# none of the options except the origin and the seed enters the roster's random draws
_SETTINGS = """
local settings = {
    Name = "Battle Brothers", Banner = "banner_01", Difficulty = 1, EconomicDifficulty = 1, BudgetDifficulty = 1,
    Ironman = false, ExplorationMode = false, GreaterEvil = 0, PermanentDestruction = true,
    Seed = vargv[0], StartingScenario = vargv[1]
};
::World.State.m.CampaignSettings = settings;
"""
# Legends' black-market counter before a map run (Lab.world_map's blackmarket); a game without it is left alone
_BLACKMARKET = """
if ("Buildings" in ::Const.World && "Blackmarket" in ::Const.World.Buildings)
    ::Const.World.Buildings.Blackmarket = vargv[0];
"""
# the roster: what startNewCampaign does after the world is generated
_START = _SETTINGS + """
::Math.seedRandomString(settings.Seed);
::World.Assets.setCampaignSettings(settings);
"""
# Deserters without a map (Lab.deserters_start): the same, then the origin's onSpawnPlayer, where it makes its recruits
_DESERTERS_START = _START + """
settings.StartingScenario.onSpawnPlayer();
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

# A brother is complete when the NEXT brother's setStartValuesEx starts: origins create all recruits first and configure them
# after that (bros[0].setStartValuesEx(...) after the create loop, MODLOG "EARLY EXIT"), so create says nothing. vargv[0]: the
# player class and the copies derived classes hold. It reads, it draws nothing.
_BROTHER_WRAP = """
foreach (c in vargv[0])
{
    if ("BBR_BrotherWrapped" in c) continue;
    local start = c.setStartValuesEx;
    c.BBR_BrotherWrapped <- true;
    c.setStartValuesEx <- function (...)
    {
        ::BBR_BrotherStarts(this);
        local args = [this];
        args.extend(vargv);
        return start.acall(args);
    };
}
"""
_ROLL_LOG_CLEAR = "if (\"BBR_RollLog\" in ::getroottable()) ::BBR_RollLog.clear();"
_ROLL_PEEK = """
local out = [];
foreach (bro in vargv[0])
{
    local found = null;
    local background = bro.getBackground();
    foreach (e in ::BBR_RollLog)
        if (e[0] == background) found = [e[1], e[2]];
    out.push(found);
}
return out;
"""


class _RosterStopped(Exception):
    """stop_after said the seed is decided: leaves the campaign start from inside the scripts (Lab.roster catches it)."""

# The Map Options of Legends' MSU page "Map Options" that change the generated map (mod_legends/register/modsettings.nut;
# the page's DebugMap only reveals the map), by their setting ids, in the order of the seed post.
# bbreroll/seed_report.py lists the same keys with their labels: a test keeps both lists equal (bbseed never
# imports bbreroll).
MAP_OPTION_KEYS = ("LandRatio", "Water", "Snowline", "Settlements", "Factions", "StackCitadels", "AllTradeLocations")

# Legends' perk trees, the way its character tooltip lists them (background.getPerkGroups():
# the complete perk groups per category, then the perks that belong to no complete group).
# The base game has fixed trees per background: null there.
_PERK_GROUPS = """
local out = [];
local legends = "Legends" in ::getroottable() && "Perks" in ::Legends && "PerkGroupCategoriesOrder" in ::Legends.Perks;
foreach (bro in ::World.getPlayerRoster().getAll())
{
    if (!legends) { out.push(null); continue; }
    local data = bro.getBackground().getPerkGroups();
    local groups = [];
    foreach (category in ::Legends.Perks.PerkGroupCategoriesOrder)
    {
        local names = [];
        foreach (id in data.CompleteGroupsIDs[category])
            names.push(::Const.Perks[id].Name);
        if (names.len() != 0) groups.push([category, names]);
    }
    local single = [];
    foreach (def in data.RemainingPerkDefs)
        single.push(::Const.Perks.PerkDefObjects[def].Name);
    out.push([groups, single]);
}
return out;
"""
PERK_KEYS = ("perk_groups", "single_perks")

# every mod registered with Modern Hooks (also the base game, the DLCs and mods bundled inside another zip)
_REGISTERED_MODS = """
local out = [];
if ("Hooks" in ::getroottable() && "getMods" in ::Hooks)
    foreach (id, mod in ::Hooks.getMods())
        out.push([id, mod.getName(), mod.getVersion().tostring()]);
return out;
"""


def _plain(text):
    return "".join(c if c.isalnum() else "_" for c in text.lower())


def installed_mods(registered, zip_names):
    """The mods a seed is found with, one per mod zip in the game's data folder:
    [{"file", "id", "name", "version"}]. registered: (id, name, version) of every mod that
    registered itself while the scripts loaded. A zip belongs to the registration whose id its
    file name starts with (the longest such id: mod_legends-assets-19.4.3.zip is
    mod_legends_assets, not mod_legends); a zip no registration matches keeps its file name."""
    by_id = sorted(registered, key=lambda r: -len(r[0]))
    out = []
    for name in zip_names:
        stem = name[:-4] if name.lower().endswith(".zip") else name
        found = next((r for r in by_id if _plain(stem).startswith(_plain(r[0]))), None)
        if found is None:
            out.append({"file": name, "id": None, "name": stem, "version": None})
        else:
            out.append({"file": name, "id": found[0], "name": found[1], "version": found[2]})
    return out

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
        self.roots = roots
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
        self._perks = eng.vm.compile(_PERK_GROUPS, "lab_perks")
        attrs = R.get(eng.root.get("Const"), "Attributes")
        self.attr_index = {short: R.get(attrs, long) for short, long in ATTRIBUTES.items()}
        self._scenarios = {}
        self._rolls = None
        self._maps = None               # mapgen.MapRun, made by the first world_map()
        self._blackmarket = None        # the compiled _BLACKMARKET, made with it
        self._no_map = None             # mapgen.NoMapStart, made by the first deserters_start()
        self._brother_watch = None      # Lab._watch_brothers: what happens when a brother starts
        self._state_spent = False       # a map run used the world state: the next roster needs a new one
        self._stash_capacity = eng.vm.compile("return ::World.Assets.getStash().getCapacity();", "lab_cap").invoke(eng.root, ())
        for key, value in (mod_settings or {}).items():
            mod_id, setting = key.split(":", 1)
            self.set_mod_setting(mod_id, setting, value)
        # The loaded scripts are ~10 million long-lived objects. Left in the collector's care they
        # make every full collection slow AND rare (it waits for 25% growth), while each roster
        # leaves reference cycles behind that only a full collection frees. Freezing takes the
        # loaded scripts out of the collector's view, so collections stay quick and frequent.
        gc.collect()
        if hasattr(gc, "freeze"):       # PyPy has none, and its memory stays flat without it (measured 2026-11-01)
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
        """What a seed found here is valid for: the game setup the lab loaded. "map_options": the values of
        MAP_OPTION_KEYS this lab uses ({key: int or bool}); a setting the game does not have is left out, so a game
        without Legends or without MSU gives {}. "dlc_complete": whether the installed game (the data folder the lab
        reads by default, gamedata.game_data_dir) has every DLC file, as Vanilla maps need."""
        root = self.eng.root.d
        out = {"profile": self.profile, "game_version": self.eng.game_version, "legends_version": None,
               "legends_build": None, "battle_sisters": None, "mods": self.mods(), "map_options": {},
               "dlc_complete": gamedata.all_dlc()}
        legends = root.get("Legends")
        if type(legends) is SqTable:
            out["legends_version"] = legends.get("Version")
            out["legends_build"] = legends.get("BuildName")
            try:
                out["battle_sisters"] = self.get_mod_setting("mod_legends", "GenderEquality")
            except LabError:
                pass
            for key in MAP_OPTION_KEYS:
                try:
                    out["map_options"][key] = self.get_mod_setting("mod_legends", key)
                except LabError:
                    pass
        return out

    def mods(self):
        """The mod zips this lab loaded, with the names and versions they registered (see
        installed_mods). The base game's script cache is not a mod; neither is a folder."""
        registered = [tuple(tostring(x) for x in row)
                      for row in self.eng.vm.compile(_REGISTERED_MODS, "lab_mods").invoke(self.eng.root, ())]
        from .gamedata import cache_dir
        cache = cache_dir().resolve()
        roots = [Path(r) for r in reversed(self.roots)]    # roots are highest priority first: back to load order
        zips = [r.name for r in roots if r.is_file() and r.suffix.lower() == ".zip" and r.resolve().parent != cache]
        return installed_mods(registered, zips)

    # ------------------------------------------------------------------ rosters
    def _watch_brothers(self):
        """The hook on setStartValuesEx, once per lab; returns its state: "members" (the player roster's list), "started"
        (the slots that started in this roster, 0 = first), "on_complete"."""
        if self._brother_watch is None:
            from .rolls import _copies
            eng = self.eng
            watch = {"started": [], "on_complete": None, "members": self.world.roster("player").members}
            roster = self.world.roster("player")

            def starts(_this, bro):
                if watch["on_complete"] is None:
                    return None
                for i, member in enumerate(roster.members):
                    if member is bro:
                        if i not in watch["started"]:
                            before = watch["started"][-1] if watch["started"] else None
                            watch["started"].append(i)
                            if before is not None:
                                watch["on_complete"](before + 1, roster.members[before])
                        break
                return None
            eng.root.d["BBR_BrotherStarts"] = NativeFn(starts, "BBR_BrotherStarts")
            cls = eng.class_table("scripts/entity/tactical/player")
            eng.vm.compile(_BROTHER_WRAP, "lab_brother_wrap").invoke(eng.root, ([cls] + _copies(eng, cls.get("ClassName")),))
            watch["report"] = eng.vm.compile(_REPORT.replace("foreach (bro in ::World.getPlayerRoster().getAll())",
                                                             "foreach (bro in vargv[0])"), "lab_brother_report")
            watch["peek"] = eng.vm.compile(_ROLL_PEEK, "lab_brother_peek")
            watch["clear"] = eng.vm.compile(_ROLL_LOG_CLEAR, "lab_brother_clear")
            self._brother_watch = watch
        return self._brother_watch

    def _brother_view(self, entity):
        """What one complete brother looks like now, as in a roster (with his rolls when they are watched); None when
        he cannot be read yet (Gladiators' stars come later: such an origin never stops, talents.survey)."""
        watch, eng = self._brother_watch, self.eng
        depth = len(eng.vm.stack)
        try:
            bro = self._bro(watch["report"].invoke(eng.root, ([entity],))[0])
            if self._rolls is not None:
                self._rolls.attach([bro], watch["peek"].invoke(eng.root, ([entity],)))
            return bro
        except (SqError, IndexError, KeyError, TypeError):
            del eng.vm.stack[depth:]
            return None

    def roster(self, seed, origin, fresh=True, probe=None, stop_after=None, stop_slots=None):
        """The starting roster of a campaign with this seed text and origin.

        fresh=True builds a new world state first, like the game does for every new
        campaign — the authoritative answer. fresh=False reuses the current one after a
        quick reset: much faster, used to sift seeds; confirm anything it finds.
        probe: a compiled script run while the recruits still exist; then the result is
        (roster, what the probe returned).
        stop_after(slot, bro): called each time a brother is complete (slot 1 = first), when the next one starts, with
        his view (None when he cannot be read yet); the last brother is not asked: the roster is complete then. True
        ends the roster there: it cleans up as after a full one and returns None. stop_slots: only these slots are asked
        (a view costs a little); None: all of them. Whether a slot's view is the final one is talents.survey's question."""
        eng = self.eng
        if fresh or self._state_spent:
            self.world.build_state()
            self.world.add_placeholder_settlements()
            self._state_spent = False
        if stop_after is not None:
            watch = self._watch_brothers()
            del watch["started"][:]

            def complete(slot, entity):
                if (stop_slots is None or slot in stop_slots) and stop_after(slot, self._brother_view(entity)):
                    raise _RosterStopped()
            watch["on_complete"] = complete
        try:
            scenario = self.scenario(origin)
            self._start.invoke(eng.root, (seed, scenario))
            post = _POST_SPAWN.get(scenario.get("ClassName"))
            if post is not None:
                eng.vm.compile(post, "lab_post_spawn").invoke(eng.root, ())
            bros = [self._bro(b) for b in self._report.invoke(eng.root, ())]
            if self._rolls is not None:
                self._rolls.attach(bros, self._rolls.probe.invoke(eng.root, ()))
            probed = probe.invoke(eng.root, ()) if probe is not None else None
        except _RosterStopped:
            del eng.vm.stack[:]
            self._cleanup.invoke(eng.root, (self._stash_capacity,))
            self._brother_watch["clear"].invoke(eng.root, ())
            return None
        except SqError as e:
            eng.vm.note_trace(0)
            trace = " > ".join(eng.vm.last_trace[-6:])
            del eng.vm.stack[:]
            try:
                self._cleanup.invoke(eng.root, (self._stash_capacity,))
            except SqError:
                del eng.vm.stack[:]
            raise LabError("seed %r, origin %r: %s (at %s)" % (seed, origin, tostring(e.value), trace))
        finally:
            if stop_after is not None:
                self._brother_watch["on_complete"] = None
        self._cleanup.invoke(eng.root, (self._stash_capacity,))
        return bros if probe is None else (bros, probed)

    def watch_rolls(self):
        """From now on every recruit also has "rolls": {stat: {"lo", "hi", "value", "tier"}} — where
        his stat rolls landed in what his background can roll (see rolls.py)."""
        if self._rolls is None:
            from .rolls import RollWatch
            self._rolls = RollWatch(self)
        return self

    def roster_with_perks(self, seed, origin):
        """roster() on a fresh world state, each recruit also with "perk_groups" ([[category,
        [group names]]]) and "single_perks" ([perk names]) when the game has Legends' perk trees."""
        bros, perks = self.roster(seed, origin, fresh=True, probe=self._perks)
        self._add_perks(bros, perks)
        return bros

    @staticmethod
    def _add_perks(bros, perks):
        """The perk trees `self._perks` read (one entry per recruit, None without Legends' trees) put on the roster."""
        for bro, found in zip(bros, perks):
            if found is not None:
                groups, single = found
                bro["perk_groups"] = [[tostring(cat), [tostring(n) for n in names]] for cat, names in groups]
                bro["single_perks"] = sorted({tostring(n) for n in single})

    # ------------------------------------------------------------------ maps
    def world_map(self, seed, origin="trader_scenario", stop_at="reseed", layout=None, blackmarket=0, perks=False):
        """The game's own campaign start (world_state.startNewCampaign, every mod hook included) on a
        fresh world state, stopped where the map is wanted (see mapgen.py): stop_at="accepted" right after
        the generator logs "World accepted.", "reseed" at the second Math.seedRandomString(seed).
        layout: one of hexmap.LAYOUTS (None: mapgen.LAYOUT).
        blackmarket: the value Legends' black-market counter (::Const.World.Buildings.Blackmarket) gets before the
        run. The game never resets it: it is 0 in the first campaign after the game starts and 2 or more in every
        later one (each map counts the black markets it builds), and what refineSettlements draws depends on it.
        0 (the default) builds every map as a first campaign, so a map does not depend on the maps this lab built
        before; None leaves the counter as the last run left it. The towns, their ports and the terrain before the
        roads do not depend on it (measured, map-search Task 7). A game without the counter (no Legends) ignores it.

        stop_at="spawn" runs on past the second seeding through setCampaignSettings and the origin's onSpawnPlayer
        (mapgen.py, "The start") and gives everything "reseed" gives ("draws" and "probe" are still the map's) plus
        "spawn": mapgen.spawn_summary() ({"tile", "fort", "loop", "draws", "isolated", "size"}; fort / loop / draws for
        Deserters only) and "roster": the recruits as roster() lists them (the origin's own onSpawnPlayer ran, so no
        _POST_SPAWN step is added). A start loop past mapgen.SPAWN_LOOP_CAP iterations raises LabError.
        perks=True (stop_at="spawn" only): the recruits also have their perk trees, as roster_with_perks() gives them.
        A "spawn" run also puts the party's square in the map summary: out["map"]["start"] = [x, y] (None when no
        party was spawned); the other stops leave the key out (mapdraw draws no start marker without it).

        Returns {"log": [the logInfo lines of the run], "draws": seeded draws in the run, "seconds",
        "stub_uses": {(kind, name): uses in this run}}, and for stop_at="reseed" (the whole map) also
        "map": mapgen.summary() - the terrain and the towns as plain data - and "probe": one
        Math.rand(*mapgen.PROBE_RANGE) drawn at the stop, before the second seeding (not counted in "draws"; the
        in-game verifier draws the same number there). Rosters are not changed by it. A run
        that fails (a script error, or a native the lab does not model yet: mapgen.MapError) raises LabError, also
        when the map path itself cannot be set up (the first call makes mapgen.MapRun, which runs scripts)."""
        try:
            if self._maps is None:
                blackmarket_script = self.eng.vm.compile(_BLACKMARKET, "lab_blackmarket")
                self._maps = mapgen.MapRun(self.eng, self.eng.vm.compile(_SETTINGS + mapgen.START, "lab_map_start"),
                                           self.world)
                self._blackmarket = blackmarket_script
            scenario = self.scenario(origin)
            self._state_spent = True      # the campaign start is left half done: roster() builds a new state
            self.world.build_state()
            if blackmarket is not None:
                self._blackmarket.invoke(self.eng.root, (blackmarket,))
            try:
                out = self._maps.run(seed, scenario, stop_at, layout)
                if stop_at in ("reseed", "spawn"):
                    out["map"] = mapgen.summary(self, out["log"])
                if stop_at == "spawn":
                    origin_id = call(R.get(scenario, "getID"), scenario, ())
                    out["spawn"] = mapgen.spawn_summary(self, out.pop("start"), out["map"], origin_id)
                    tile = out["spawn"]["tile"]
                    out["map"]["start"] = None if tile is None else [int(tile[0]), int(tile[1])]    # the picture's marker
                    out["roster"] = self._read_roster()
                    if perks:
                        self._add_perks(out["roster"], self._perks.invoke(self.eng.root, ()))
            finally:
                if stop_at == "spawn":
                    self._clear_roster()
            return out
        except SqError as e:
            if self.eng.vm.stack:         # an error outside the run (the run notes and clears its own)
                self.eng.vm.note_trace(0)
                del self.eng.vm.stack[:]
            raise LabError("map of seed %r: %s (at %s)" % (
                seed, tostring(e.value), " > ".join(self.eng.vm.last_trace[-6:]))) from e
        except mapgen.MapError as e:
            raise LabError("map of seed %r: %s (at %s)" % (
                seed, e, " > ".join(self.eng.vm.last_trace[-6:]))) from e

    def _read_roster(self):
        """The player roster as roster() reports it (with "rolls" when watch_rolls() is on)."""
        eng = self.eng
        bros = [self._bro(b) for b in self._report.invoke(eng.root, ())]
        if self._rolls is not None:
            self._rolls.attach(bros, self._rolls.probe.invoke(eng.root, ()))
        return bros

    def _clear_roster(self):
        try:
            self._cleanup.invoke(self.eng.root, (self._stash_capacity,))
        except SqError:
            del self.eng.vm.stack[:]

    # ------------------------------------------------------------------ Deserters without a map
    def deserters_start(self, seed, n, fort_xy=None, size=None, fresh=True, probe=None):
        """Deserters' start without a map: the campaign start's draws from the second seeding on (setCampaignSettings,
        then Deserters' own onSpawnPlayer) with its start loop made to run exactly n times (mapgen.NoMapStart). The
        recruits depend on the map only through the draws of that loop (engine fact 4), so with the n of a map
        (world_map(..., stop_at="spawn")["spawn"]["loop"]) and its fort's square this is that map's roster.

        fort_xy: the fort's square (x, y) (summary town x, y); None puts it in the middle of the map, where both of the
        loop's ranges have their full 15 values - which gives the same draws as any fort on a map whose sides are 5
        squares or more (mapgen.deserters_loop_draws), so None is wrong only on such tiny maps.
        size: (Const.World.Settings.SizeX, SizeY) for the run; None keeps the lab's values (the scripts' defaults, or
        what the last map run set).
        probe: a compiled script run while the recruits still exist (as roster() takes it).
        Returns {"roster": as roster() gives it, "tile": the square the n-th iteration drew (on the map: the start
        tile), "draws": seeded draws from onSpawnPlayer's entry to World.spawnEntity, "probe": what the probe returned
        (None without one)}."""
        if not isinstance(n, int) or not 1 <= n <= mapgen.SPAWN_LOOP_CAP:
            raise ValueError("n must be 1 .. %d iterations, not %r" % (mapgen.SPAWN_LOOP_CAP, n))
        eng = self.eng
        if fresh or self._state_spent:
            self.world.build_state()
            self.world.add_placeholder_settlements()
            self._state_spent = False
        if self._no_map is None:
            self._no_map = mapgen.NoMapStart(eng, self.world)
            self._desert_start = eng.vm.compile(_DESERTERS_START, "lab_deserters_start")
        scenario = self.scenario("deserters_scenario")
        stand = self._no_map
        try:
            stand.install(n, fort_xy, size)
            original = R.get(scenario, "onSpawnPlayer")

            def counted(this, *args):
                stand.entry(eng.rng)
                return call(original, this, ())
            had = scenario.d.get("onSpawnPlayer", R.MISSING)
            scenario.newslot("onSpawnPlayer", NativeFn(counted, "onSpawnPlayer"))
            try:
                self._desert_start.invoke(eng.root, (seed, scenario))
            finally:
                if had is R.MISSING:
                    scenario.remove("onSpawnPlayer")
                else:
                    scenario.d["onSpawnPlayer"] = had
            if stand.calls != n or stand.spawned is None:
                raise LabError("seed %r: the start loop ran %d of %d times" % (seed, stand.calls, n))
            bros = self._read_roster()
            probed = probe.invoke(eng.root, ()) if probe is not None else None
        except SqError as e:
            eng.vm.note_trace(0)
            trace = " > ".join(eng.vm.last_trace[-6:])
            del eng.vm.stack[:]
            raise LabError("seed %r, Deserters with n=%d: %s (at %s)" % (seed, n, tostring(e.value), trace))
        except mapgen.MapError as e:
            del eng.vm.stack[:]
            raise LabError("seed %r, Deserters with n=%d: %s" % (seed, n, e)) from e
        finally:
            stand.restore()
            self._clear_roster()
        return {"roster": bros, "tile": stand.drawn, "draws": stand.spawn_draws, "probe": probed}

    def deserters_roster(self, seed, n, fort_xy=None, size=None, fresh=True):
        """The roster of a Deserters campaign whose start loop ran n times (deserters_start(...)["roster"])."""
        return self.deserters_start(seed, n, fort_xy, size, fresh)["roster"]

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


def without_perks(roster):
    """The roster without the perk-tree keys (to compare it with one rolled without them)."""
    return [{k: v for k, v in bro.items() if k not in PERK_KEYS} for bro in roster]


def perk_text(bro):
    """'Weapon: Bow, Sword · Defense: Light Armor · ...' — empty when the roster has no perk trees."""
    parts = ["%s: %s" % (cat, ", ".join(names)) for cat, names in bro.get("perk_groups") or ()]
    if bro.get("single_perks"):
        parts.append("Single perks: %s" % ", ".join(bro["single_perks"]))
    return " · ".join(parts)


def roll_text(bro):
    """'HP 66 mid (64-68) · FAT 104 low (103-105) · RES 45 fixed · ...' — where each base stat
    roll landed in what the recruit's background can roll; empty without roll data."""
    names = {"hp": "HP", "fat": "FAT", "res": "RES", "init": "INIT", "msk": "MSK", "rsk": "RSK", "mdf": "MDF", "rdf": "RDF"}
    parts = []
    for stat, r in (bro.get("rolls") or {}).items():
        if r["tier"] == "fixed":
            parts.append("%s %d fixed" % (names[stat], r["value"]))
        else:
            parts.append("%s %d %s (%d-%d)" % (names[stat], r["value"], r["tier"], r["lo"], r["hi"]))
    return " · ".join(parts)


def describe(bro):
    """One recruit as text, the way a player would check it on the character screen."""
    stars = ", ".join("%s %d" % (k, v) for k, v in bro["stars"].items() if v) or "none"
    s = bro["shown"]
    text = ("%s (%s), level %d\n"
            "      stars: %s\n"
            "      hitpoints %d, fatigue %d, resolve %d, initiative %d, melee skill %d, ranged skill %d, "
            "melee defense %d, ranged defense %d\n"
            "      traits: %s\n"
            "      gear: %s") % (
        bro["name"], bro["background_name"], bro["level"], stars,
        s["hp"], s["fat"], s["res"], s["init"], s["msk"], s["rsk"], s["mdf"], s["rdf"],
        ", ".join(bro["trait_names"]) or "none", ", ".join(bro["gear"]) or "none")
    if bro.get("rolls"):
        text += "\n      stat rolls (in the range of the background): " + roll_text(bro)
    for cat, names in bro.get("perk_groups") or ():
        text += "\n      %s perk groups: %s" % (cat, ", ".join(names))
    if bro.get("single_perks"):
        text += "\n      single perks: %s" % ", ".join(bro["single_perks"])
    return text

// bb_reroll_dump.nut — two modes in one mod:
//
//   1) DUMP MODE (default). On every campaign start, log each starting brother's
//      stars (all 8) + traits between [BBREROLL] START / END markers so the
//      Python script can parse them.
//
//   2) BRUTE-FORCE MODE. If the user types REROLL_TRIGGER as the campaign seed,
//      the campaign never actually starts. Instead we loop seeds inside Squirrel,
//      generating a world + the chosen origin's brothers per iteration,
//      evaluating against built-in criteria, and logging matches via
//      ::logWarning. Inspired by mod_seedfinder.
//
// Supports any origin via the chosen scenario's onSpawnAssets(); falls back
// to a hardcoded Davkul Awaits roster if dynamic origin lookup fails.

::BBReroll <- {
    Version = "3.4.5",
    Tag     = "[BBREROLL]",
    Tag2    = "[BBREROLL2]",
    // Sentinel values thrown by the brute-force loop on a clean finish. The
    // startNewCampaign catch recognises these and swallows them (the loop has
    // already done its job); any OTHER exception is unexpected and is rethrown
    // so vanilla / Legends / other-mod error handling still fires. Keep unique.
    FinishMatch    = "BBRR_FINISH:match",
    FinishMaxIters = "BBRR_FINISH:maxiters",
};

// Short name → Const.Attributes name. (Const.Attributes.Fatigue, NOT Stamina —
// the latter is only on bro.getBaseProperties().Stamina.)
::BBReroll_STATS <- {
    hp   = "Hitpoints",
    fat  = "Fatigue",
    res  = "Bravery",
    init = "Initiative",
    msk  = "MeleeSkill",
    rsk  = "RangedSkill",
    mdf  = "MeleeDefense",
    rdf  = "RangedDefense",
};
::BBReroll_STAT_ORDER <- ["hp","fat","res","init","msk","rsk","mdf","rdf"];

// Resolve a stat short name to a Const.Attributes index. Returns null + logs once if missing.
::BBReroll_AttrIdx <- function (shortName) {
    if (!(shortName in ::BBReroll_STATS)) return null;
    local attrName = ::BBReroll_STATS[shortName];
    if (!(attrName in ::Const.Attributes)) {
        ::logWarning(::BBReroll.Tag + " Const.Attributes." + attrName + " not found (short=" + shortName + ")");
        return null;
    }
    return ::Const.Attributes[attrName];
};

// === Brute-force config — tweak as needed ===
//
// Star spec syntax: whitespace-separated tokens of the form "<stat><minStars>".
//   Stats:  hp  fat  res  init  msk  rsk  mdf  rdf
//   Examples:
//     "msk2 mdf2"           — at least 2 stars in melee skill AND melee defense
//     "rsk3 rdf2 init1"     — archer-y bro
//     ""                    — no star requirements (any stats accepted)
//
// StarsBySlot:
//   "*" is the default applied to every brother not otherwise listed.
//   Numeric keys ("1","2",...) override "*" for that 1-based slot.
//
::BBReroll_BF <- {
    TriggerSeed = "REROLL",  // type this in the seed field to trigger brute force
    MaxIters    = 10000,
    LogEvery    = 10,

    // === main thing to edit ===
    // (Squirrel table literals require [] around non-identifier keys.)
    StarsBySlot = {
        ["*"] = "",
        ["1"] = "msk1 mdf1 fat1",
    },

    BannedTraits = [
        "asthmatic","bleeder","brute","clubfooted","craven","dastard",
        "disloyal","drunkard","dumb","fainthearted","fat","fragile","greedy",
        "hesitant","hunchback","impatient","insecure","irrational","mad",
        "night_blindness","paranoid","pessimist","short_sighted","superstitious","tiny",
        "legend_fear_dark",
    ],

    // At least one of these must be present per brother. Empty = don't require any.
    RequiredAny = [
        "tough","determined","dexterous","brave","strong","iron_jaw","iron_lungs",
        "athletic","quick","fortified_mind","steel_brow","colossus",
        "legend_steady_hands",
    ],

    // Used only if dynamic origin lookup fails. Defaults to Davkul Awaits.
    Fallback = {
        backgrounds = [
            "legend_magister_background",
            "legend_husk_background",
            "cultist_background",
            "cultist_background",
            "legend_lurker_background",
        ],
        granted_traits = ["CultistFanatic"],
        removed_traits = ["Superstitious","Dastard","Insecure","Craven"],
    },
};

// These live OUTSIDE ::BBReroll_BF because the GUI's Save & Deploy rewrites
// that whole table and would drop unknown fields.
//
// Fixed master seed for reproducible benchmark / A-B runs: when non-null, the
// loop seeds its per-iter seed generator with this instead of wall-clock time,
// so two runs produce the identical seed sequence. Leave null for normal use.
::BBReroll_BF_FixedMasterSeed <- null;

// Diagnostic (perf research): when true, every stars-pass candidate is
// trait-evaluated on BOTH the cached fast-pass world AND the rebuilt
// candidate world, and any divergence is logged. Measures whether the
// expensive per-candidate world rebuild actually changes the trait outcome
// (i.e. whether it can be skipped). The authoritative match decision is
// unaffected — it always uses the post-rebuild result. Default off.
::BBReroll_BF_DiagVerify <- false;

// One sorted, comma-joined trait list for a bro — stable fingerprint for
// comparing the same bro across two worlds.
::BBReroll_BF_TraitFingerprint <- function (bro) {
    local traits = ::BBReroll_DumpTraits(bro);
    traits.sort();
    local out = "";
    foreach (j, t in traits) { if (j > 0) out += ","; out += t; }
    return out;
};


// ---------- shared helpers ----------

::BBReroll_DumpTraits <- function (bro) {
    local out = [];
    local container = bro.getSkills();
    local all = null;
    if ("m" in container && "Skills" in container.m) all = container.m.Skills;
    if (all == null && "getAllSkills" in container) all = container.getAllSkills();
    if (all == null) return out;
    foreach (sk in all) {
        if (sk == null) continue;
        local id = sk.getID();
        if (id == null) continue;
        if (id.len() > 6 && id.slice(0, 6) == "trait.") {
            out.append(id.slice(6));
        }
    }
    return out;
};

::BBReroll_FindTalents <- function (bro) {
    // Per-bro talents first. fillTalentValues writes to bro.m.Talents, and
    // scenarios may overwrite afterwards (e.g. Gladiators hardcodes
    // bros[2].getTalents()[MeleeSkill] = 2 in onSpawnAssets). The bg.m.*
    // arrays are the background-template rolling weights, NOT the bro's
    // actual stars — falling back to them gives 0 stars at indices the
    // background doesn't weight.
    if ("getTalents" in bro) {
        local t = bro.getTalents();
        if (t != null && t.len() > 0) return t;
    }
    try {
        if (bro.m.Talents != null && bro.m.Talents.len() > 0) return bro.m.Talents;
    } catch (e) {}
    try {
        if (bro.m.RawTalents != null && bro.m.RawTalents.len() > 0) return bro.m.RawTalents;
    } catch (e) {}
    local bg = bro.getBackground();
    if (bg != null) {
        try {
            if (bg.m.RawTalents != null && bg.m.RawTalents.len() > 0) return bg.m.RawTalents;
        } catch (e) {}
        try {
            if (bg.m.Talents != null && bg.m.Talents.len() > 0) return bg.m.Talents;
        } catch (e) {}
    }
    return null;
};

::BBReroll_BroStarsCsv <- function (bro) {
    // "hp*0 fat*1 res*0 init*2 msk*3 rsk*0 mdf*2 rdf*0"
    local talents = ::BBReroll_FindTalents(bro);
    if (talents == null) return "(no_talents)";
    local out = "";
    foreach (i, name in ::BBReroll_STAT_ORDER) {
        local idx = ::BBReroll_AttrIdx(name);
        if (i > 0) out += " ";
        out += name + "*" + (idx == null ? "?" : talents[idx]);
    }
    return out;
};


// ---------- dump mode (now logs all 8 stat stars) ----------

::BBReroll_Dump <- function (worldState = null, preReadSeed = null) {
    if (!("World" in ::getroottable()) || ::World == null) return;
    local roster = ::World.getPlayerRoster().getAll();
    if (roster == null || roster.len() == 0) return;
    ::logInfo(::BBReroll.Tag + " START v" + ::BBReroll.Version);
    foreach (i, bro in roster) {
        local bg = bro.getBackground();
        local talents = ::BBReroll_FindTalents(bro);
        local mskIdx = ::BBReroll_AttrIdx("msk");
        local mdfIdx = ::BBReroll_AttrIdx("mdf");
        local msk = (talents != null && mskIdx != null) ? talents[mskIdx] : 0;
        local mdf = (talents != null && mdfIdx != null) ? talents[mdfIdx] : 0;
        local stars = ::BBReroll_BroStarsCsv(bro);
        local traits = ::BBReroll_DumpTraits(bro);
        local traits_csv = "";
        foreach (j, t in traits) {
            if (j > 0) traits_csv += ",";
            traits_csv += t;
        }
        // Keep msk=N mdf=N for Python regex compatibility; stars=[...] is new full info.
        ::logInfo(::BBReroll.Tag + " bro=" + (i + 1)
            + " name=\"" + bro.getName() + "\""
            + " bg=\"" + bg.getID() + "\""
            + " msk=" + msk + " mdf=" + mdf
            + " stars=[" + stars + "]"
            + " traits=" + traits_csv);
    }
    // Seed: prefer the pre-read string from the onInit hook (private `m` is
    // accessible from inside the class but not when an instance is passed to
    // a free function). Falls back to direct access for callers that didn't
    // pre-read.
    local seed = "unknown";
    local seed_src = "no_seed";
    if (preReadSeed != null && preReadSeed != "") {
        seed = preReadSeed;
        seed_src = "passed_from_hook";
    } else {
        try {
            seed = worldState.m.CampaignSettings.Seed;
            seed_src = "worldState.m.CampaignSettings.Seed";
        } catch (e) {}
    }
    ::logInfo(::BBReroll.Tag + " END seed=" + seed + " src=" + seed_src);
};


// ---------- brute-force: star-spec parsing + per-bro eval ----------

::BBReroll_BF_ParseSpec <- function (spec) {
    // "msk2 mdf3 hp1" -> { msk = 2, mdf = 3, hp = 1 }
    local out = {};
    if (spec == null) return out;
    local tokens = [];
    local cur = "";
    for (local i = 0; i < spec.len(); i++) {
        local ch = spec[i];
        if (ch == ' ' || ch == '\t' || ch == ',') {
            if (cur.len() > 0) { tokens.append(cur); cur = ""; }
        } else {
            cur += spec.slice(i, i + 1);
        }
    }
    if (cur.len() > 0) tokens.append(cur);

    foreach (tok in tokens) {
        local digit_at = -1;
        for (local i = 0; i < tok.len(); i++) {
            local ch = tok[i];
            if (ch >= '0' && ch <= '9') { digit_at = i; break; }
        }
        if (digit_at <= 0) continue;
        local key = tok.slice(0, digit_at).tolower();
        try {
            out[key] <- tok.slice(digit_at).tointeger();
        } catch (e) {}
    }
    return out;
};

// Pre-parse all StarsBySlot entries once per brute-force run. Returns a table
// keyed by slot-string ("1","2",...,"*") -> { stat -> minStars }.
::BBReroll_BF_BuildStarMap <- function () {
    local out = {};
    foreach (k, v in ::BBReroll_BF.StarsBySlot) out[k] <- ::BBReroll_BF_ParseSpec(v);
    return out;
};

::BBReroll_BF_StarsFor <- function (parsed, slot1based) {
    local key = "" + slot1based;
    if (key in parsed) return parsed[key];
    if ("*"  in parsed) return parsed["*"];
    return {};
};

// Hot-path criteria: resolve everything ONCE per run. Returns an array indexed
// by 1-based slot (index 0 unused); each entry is an array of [attrIdx, min,
// statName] triples with the "*" fallback already applied. The per-iter eval
// then does pure integer indexing — no string conversion, no table lookups,
// no Const.Attributes resolution per bro per iteration.
::BBReroll_BF_BuildFastChecks <- function (parsed, maxSlots = 20) {
    local out = [[]];   // index 0 placeholder
    for (local slot = 1; slot <= maxSlots; slot++) {
        local spec = ::BBReroll_BF_StarsFor(parsed, slot);
        local checks = [];
        foreach (key, minStars in spec) {
            local idx = ::BBReroll_AttrIdx(key);   // logs once on unknown stat
            if (idx == null) continue;
            checks.append([idx, minStars, key]);
        }
        out.append(checks);
    }
    return out;
};

// Stars-only check. Used by the fast pre-filter in the brute-force loop.
// Returns [pass, fail_reason] like EvalBro but skips trait/banned/required
// checks (not world-faithful in the fast pass). Takes the pre-resolved
// fast_checks structure; slots with no criteria return before the talent
// lookup (hot path: this runs per bro per iteration).
::BBReroll_BF_EvalStarsOnly <- function (bro, slot1based, fast_checks) {
    // Explicit if/else, not ?: — this build's ternary evaluates BOTH branches
    // (gotcha #2), which would index out of bounds for slots past the table.
    local checks;
    if (slot1based < fast_checks.len()) {
        checks = fast_checks[slot1based];
    } else {
        checks = [];
    }
    if (checks.len() == 0) return [true, "ok"];
    local talents = ::BBReroll_FindTalents(bro);
    if (talents == null) return [false, "no_talents"];
    for (local i = 0; i < checks.len(); i++) {
        local c = checks[i];
        local got = talents[c[0]];
        if (got < c[1]) return [false, c[2] + "*" + got + "<" + c[1]];
    }
    return [true, "ok"];
};

::BBReroll_BF_EvalBro <- function (bro, slot1based, parsed_stars) {
    local talents = ::BBReroll_FindTalents(bro);
    if (talents == null) return [false, "no_talents"];

    local stars = ::BBReroll_BF_StarsFor(parsed_stars, slot1based);
    foreach (key, minStars in stars) {
        local idx = ::BBReroll_AttrIdx(key);
        if (idx == null) continue;  // unknown stat token — skip rather than crash
        local got = talents[idx];
        if (got < minStars) return [false, key + "*" + got + "<" + minStars];
    }

    local traits = ::BBReroll_DumpTraits(bro);
    foreach (t in traits) {
        if (::BBReroll_BF.BannedTraits.find(t) != null) return [false, "banned " + t];
    }
    // Required traits: mode is "any" (default) or "all".
    // (Use explicit if/else — Squirrel's ternary seems to evaluate both branches in
    //  this interpreter, so a missing slot on the unused side still throws.)
    local req = null;
    if ("Required" in ::BBReroll_BF) {
        req = ::BBReroll_BF.Required;
    } else if ("RequiredAny" in ::BBReroll_BF) {
        req = ::BBReroll_BF.RequiredAny;
    }
    local mode = "any";
    if ("RequiredMode" in ::BBReroll_BF) {
        mode = ::BBReroll_BF.RequiredMode;
    }
    if (req != null && req.len() > 0) {
        if (mode == "all") {
            foreach (need in req) {
                if (traits.find(need) == null) return [false, "missing " + need];
            }
        } else {
            local hit = false;
            foreach (t in traits) {
                if (req.find(t) != null) { hit = true; break; }
            }
            if (!hit) return [false, "no_good_trait"];
        }
    }
    return [true, "ok"];
};


// ---------- brute-force: roster spawning ----------

::BBReroll_BF_LogCampaignSettings <- function (worldState) {
    // Diagnostic — call once. Show what's in CampaignSettings so we can find the origin.
    if (!("CampaignSettings" in worldState.m) || worldState.m.CampaignSettings == null) {
        ::logInfo(::BBReroll.Tag2 + " no CampaignSettings");
        return;
    }
    local keys = "";
    foreach (k, v in worldState.m.CampaignSettings) {
        keys = keys + k + "=" + v + ",";
    }
    ::logInfo(::BBReroll.Tag2 + " CampaignSettings: " + keys);
};

::BBReroll_BF_TryScenarioSpawn <- function (worldState, roster, scenario = null) {
    // Call the chosen origin's onSpawnAssets. Returns true on success. The
    // scenario object can be pre-resolved with BBReroll_BF_FindScenario and
    // passed in — the brute-force loop does that once per run instead of
    // re-resolving it every iteration.
    if (scenario == null) scenario = ::BBReroll_BF_FindScenario(worldState);
    if (scenario == null) return false;
    try {
        scenario.onSpawnAssets();
        return true;
    } catch (e) {
        ::logWarning(::BBReroll.Tag2 + " scenario.onSpawnAssets failed: " + e + " (falling back)");
        return false;
    }
};

::BBReroll_BF_FindScenario <- function (worldState) {
    // Resolve the chosen origin's scenario object, or null. The object lives
    // on CampaignSettings for the whole campaign-setup session (world rebuilds
    // don't touch it), so one resolve per run is safe.
    local scenario = null;
    // Primary: CampaignSettings.StartingScenario (confirmed via diagnostic log).
    if ("CampaignSettings" in worldState.m
        && worldState.m.CampaignSettings != null
        && "StartingScenario" in worldState.m.CampaignSettings
        && worldState.m.CampaignSettings.StartingScenario != null) {
        scenario = worldState.m.CampaignSettings.StartingScenario;
    }
    // Fallbacks
    if (scenario == null && "Scenario" in worldState.m && worldState.m.Scenario != null) {
        scenario = worldState.m.Scenario;
    }
    if (scenario == null && ::World.Assets != null && "getOrigin" in ::World.Assets) {
        try { scenario = ::World.Assets.getOrigin(); } catch (e) {}
    }
    if (scenario == null || !("onSpawnAssets" in scenario)) return null;
    return scenario;
};

::BBReroll_BF_FallbackSpawn <- function (worldState, roster) {
    local f = ::BBReroll_BF.Fallback;
    foreach (bg in f.backgrounds) {
        local bro = roster.create("scripts/entity/tactical/player");
        bro.m.HireTime = ::Time.getVirtualTimeF();
        foreach (t in f.granted_traits) {
            try { ::Legends.Traits.grant(bro, ::Legends.Trait[t]); } catch (e) {}
        }
        foreach (t in f.removed_traits) {
            try { ::Legends.Traits.remove(bro, ::Legends.Trait[t]); } catch (e) {}
        }
        bro.setStartValuesEx([bg]);
    }
};

::BBReroll_BF_CleanupBros <- function (roster) {
    // Remove every brother we (or the scenario) added so the next iter starts clean.
    local bros = roster.getAll();
    foreach (bro in bros) {
        try { roster.remove(bro); } catch (e) {}
    }
};


// ---------- brute-force: main loop ----------

::BBReroll_BF_Run <- function (worldState) {
    local Tag = ::BBReroll.Tag2;
    ::logWarning(Tag + " brute force start, max " + ::BBReroll_BF.MaxIters + " iters");
    ::BBReroll_BF_LogCampaignSettings(worldState);

    // One-time: log every key on Const.Attributes so we can sanity-check our STATS map.
    local attrKeys = "";
    try { foreach (k, v in ::Const.Attributes) attrKeys += k + "=" + v + ","; } catch (e) {}
    ::logInfo(Tag + " Const.Attributes: " + attrKeys);

    // One-time dump of Legends Map-Options settings. World gen reads these; if
    // the user changes them between this brute-force run and the real campaign
    // that uses the matched seed, the world (and therefore the trait roll) will
    // differ. Logging them here gives the user a noted-down baseline.
    local msKeys = ["LandRatio","Water","Snowline","Settlements","Factions","StackCitadels","AllTradeLocations"];
    local msOut = "";
    foreach (k in msKeys) {
        try {
            msOut += k + "=" + ::Legends.Mod.ModSettings.getSetting(k).getValue() + " ";
        } catch (e) {
            msOut += k + "=?? ";
        }
    }
    ::logInfo(Tag + " Map Options: " + msOut);

    worldState.setAutoPause(true);
    ::Time.setVirtualTime(0);
    worldState.m.IsRunningUpdatesWhilePaused = true;
    worldState.setPause(true);
    ::Const.World.settingsUpdate();

    local chars = [
        "0","1","2","3","4","5","6","7","8","9",
        "A","B","C","D","E","F","G","H","I","J","K","L","M",
        "N","O","P","Q","R","S","T","U","V","W","X","Y","Z",
    ];
    ::logInfo(Tag + " setup: getting roster");
    local roster = ::World.getPlayerRoster();
    ::logInfo(Tag + " setup: getting worldmap generator");
    local worldmap = ::MapGen.get("world.worldmap_generator");
    local minX = worldmap.getMinX();
    local minY = worldmap.getMinY();
    ::logInfo(Tag + " setup: map dims " + minX + "x" + minY);

    if (::BBReroll_BF_FixedMasterSeed != null) {
        // Reproducible run (benchmark / A-B): identical seed sequence each time.
        ::Math.seedRandom(::BBReroll_BF_FixedMasterSeed);
        ::logWarning(Tag + " FIXED master seed " + ::BBReroll_BF_FixedMasterSeed
            + " — reproducible run (benchmark mode)");
    } else {
        ::Math.seedRandom(::Math.floor(::Time.getRealTime()));
    }

    // One-time world build. The scenarios' onSpawnAssets needs roster + entity
    // machinery initialized, but never queries map tiles or world entities
    // (confirmed against vanilla + Legends scenario sources). So a single
    // build at setup is enough for the whole session — 95% speedup vs
    // regenerating per iteration.
    ::logInfo(Tag + " one-time world build…");
    try {
        ::World.resizeScene(minX, minY);
        worldmap.fill({X=0, Y=0, W=minX, H=minY}, worldState.m.CampaignSettings);
    } catch (e) {
        ::logError(Tag + " one-time world build failed: " + e);
        return;
    }
    ::logInfo(Tag + " world built; entering loop");

    // Pre-parse star specs once so we don't reparse every iteration.
    local parsed_stars = ::BBReroll_BF_BuildStarMap();
    local spec_summary = "";
    foreach (k, v in parsed_stars) {
        spec_summary += k + "={";
        foreach (sk, sv in v) spec_summary += sk + ":" + sv + " ";
        spec_summary += "} ";
    }
    ::logInfo(Tag + " parsed stars: " + spec_summary);
    // Hot-path criteria, fully resolved once (per-slot [attrIdx, min, name]).
    local fast_checks = ::BBReroll_BF_BuildFastChecks(parsed_stars, 20);

    // Resolve the scenario object once — it lives on CampaignSettings and
    // survives world rebuilds, so per-iter re-resolution is wasted work.
    local scenario_obj = ::BBReroll_BF_FindScenario(worldState);

    // Phase timing (Tier-0 instrumentation). getExactTime() deltas accumulate
    // per phase; the LogEvery line reports rolling averages + iters/s.
    local t_spawn = 0.0;
    local t_eval = 0.0;
    local t_cleanup = 0.0;
    local t_verify = 0.0;      // slow-verify world rebuild + verify spawn + EvalBro
    local verify_count = 0;    // how many iters hit the slow path
    local diag_total = 0;      // DiagVerify: candidates compared cached-vs-rebuilt
    local diag_agree = 0;      // DiagVerify: of those, how many had identical traits
    local run_t0 = ::Time.getExactTime();

    local last_fail = "";
    local spawn_mode = "unknown";
    local skipped = 0;
    local cleanupBox = { X=0, Y=0, W=minX, H=minY };

    local doCleanup = function () {
        try { ::BBReroll_BF_CleanupBros(roster); } catch (e) {}
        // Reset stash — gladiators shrinks capacity by -9 each spawn; others
        // pile up items. clear() drops items; resize re-pins the capacity.
        try {
            local stash = ::World.Assets.getStash();
            try { stash.clear(); } catch (e) {}
            try { stash.resize(200); } catch (e) {}
        } catch (e) {}
        // Reset accumulating resources/reputation. 20 origins mutate Money,
        // 14 Ammo, 12 Medicine, 9 ArmorParts, 16 Reputation — pin to 0 each
        // iter to prevent surprises.
        try {
            local a = ::World.Assets;
            try { a.m.Money              = 0; } catch (e) {}
            try { a.m.Ammo               = 0; } catch (e) {}
            try { a.m.Medicine           = 0; } catch (e) {}
            try { a.m.ArmorParts         = 0; } catch (e) {}
            try { a.m.BusinessReputation = 0; } catch (e) {}
            try { a.m.MoralReputation    = 0; } catch (e) {}
        } catch (e) {}
        // INTENTIONALLY DROPPED: World.clearScene() / EntityManager.clear() /
        // worldmap.clearWorld() — these destroyed the world we want to reuse
        // across iters. v3.4.0 left these in place and broke spawning.
    };

    // Destroy the cached world and rebuild it with a specific seed. Called only
    // on candidate verify (stars-pass), so the cost amortizes well. Leaves the
    // world in the candidate's seed state — subsequent fast iters use it.
    local destroyAndRebuildWorld = function (forSeed) {
        try { ::BBReroll_BF_CleanupBros(roster); } catch (e) {}
        try { ::World.clearScene(); } catch (e) {}
        try { ::World.EntityManager.clear(); } catch (e) {}
        try { worldmap.clearWorld(cleanupBox); } catch (e) {}
        worldState.m.CampaignSettings.Seed = forSeed;
        ::Math.seedRandomString(forSeed);
        ::World.resizeScene(minX, minY);
        worldmap.fill({X=0, Y=0, W=minX, H=minY}, worldState.m.CampaignSettings);
    };

    // Set inside the match block; checked after the for loop. Lets us escape
    // the per-iter try/catch via `break` and then throw cleanly post-loop so
    // BB's top-level handler ends the process at our line instead of in
    // world_state.onRender() (where the half-init Player would crash anyway).
    local match_seed = null;

    for (local x = 0; x < ::BBReroll_BF.MaxIters; x++) {

        local seed = "";
        for (local i = 0; i < 10; i++) {
            seed = seed + chars[::Math.rand(0, chars.len() - 1)];
        }
        if (x < 3 || x % ::BBReroll_BF.LogEvery == 0) {
            ::logInfo(Tag + " iter " + x + " seed=" + seed);
        }

        // Per-iter try/catch — one bad seed shouldn't kill the whole run.
        try {
            // ===== FAST PASS: reuse cached world, stars-only filter =====
            // Traits aren't faithful in the fast pass (world was built with a
            // different seed than the user typed in-game), but stars are
            // determined entirely by the reseed below. So we filter on stars
            // here and only pay the world-rebuild cost on actual candidates.
            worldState.m.CampaignSettings.Seed = seed;
            ::Math.seedRandomString(seed + ::BBReroll_RESEED_SUFFIX);

            local pt0 = ::Time.getExactTime();
            if (x == 0) {
                if (scenario_obj != null && ::BBReroll_BF_TryScenarioSpawn(worldState, roster, scenario_obj)) {
                    spawn_mode = "scenario";
                } else {
                    ::BBReroll_BF_FallbackSpawn(worldState, roster);
                    spawn_mode = "fallback";
                }
                ::logInfo(Tag + " spawn_mode=" + spawn_mode);
            } else if (spawn_mode == "scenario") {
                ::BBReroll_BF_TryScenarioSpawn(worldState, roster, scenario_obj);
            } else {
                ::BBReroll_BF_FallbackSpawn(worldState, roster);
            }
            local pt1 = ::Time.getExactTime();
            t_spawn += pt1 - pt0;

            local bros = roster.getAll();
            if (x == 0) {
                ::logInfo(Tag + " iter 0 roster size after spawn: " + (bros == null ? -1 : bros.len()));
            }

            local stars_pass = true;
            foreach (i, bro in bros) {
                local res = ::BBReroll_BF_EvalStarsOnly(bro, i + 1, fast_checks);
                if (!res[0]) {
                    stars_pass = false;
                    last_fail = "bro" + (i+1) + " " + res[1];
                    break;
                }
            }
            t_eval += ::Time.getExactTime() - pt1;

            if (stars_pass) {
                local vt0 = ::Time.getExactTime();
                verify_count++;
                // ===== SLOW VERIFY: rebuild world with candidate seed =====
                // The world's seed affects RNG state by the time scenarios get
                // around to rolling traits, so the only way to guarantee that
                // brute-force traits match what the player sees in-game is to
                // build the world with the candidate seed first.
                ::logInfo(Tag + " iter " + x + " stars-pass seed=" + seed + " — verifying with full world rebuild…");

                // DIAGNOSTIC (perf research, no behavior change): capture the
                // FULL criteria result + per-bro trait fingerprints on the
                // CACHED fast-pass world (these bros are still spawned) so we
                // can compare against the rebuilt world below. Answers "does the
                // rebuild change traits?". The cached eval reads only (no RNG).
                local diag_on = ::BBReroll_BF_DiagVerify;
                local diag_cached_pass = true;
                local diag_cached_fp = [];
                if (diag_on) {
                    foreach (i, bro in bros) {
                        local r = ::BBReroll_BF_EvalBro(bro, i + 1, parsed_stars);
                        if (!r[0]) diag_cached_pass = false;
                        diag_cached_fp.append(::BBReroll_BF_TraitFingerprint(bro));
                    }
                }

                destroyAndRebuildWorld(seed);
                ::Math.seedRandomString(seed + ::BBReroll_RESEED_SUFFIX);

                // The verify spawn must be byte-identical to a real campaign
                // start (traits included) — full fidelity, nothing skipped.
                if (spawn_mode == "scenario") {
                    ::BBReroll_BF_TryScenarioSpawn(worldState, roster, scenario_obj);
                } else {
                    ::BBReroll_BF_FallbackSpawn(worldState, roster);
                }

                local vbros = roster.getAll();
                local vpass = true;
                local fps = [];
                foreach (i, bro in vbros) {
                    local res = ::BBReroll_BF_EvalBro(bro, i + 1, parsed_stars);
                    if (!res[0]) {
                        vpass = false;
                        last_fail = "verify:bro" + (i+1) + " " + res[1];
                        break;
                    }
                    local stars = ::BBReroll_BroStarsCsv(bro);
                    local traits = ::BBReroll_DumpTraits(bro);
                    local traitsCsv = "";
                    foreach (j, t in traits) { if (j > 0) traitsCsv += ","; traitsCsv += t; }
                    fps.append("bro" + (i+1) + "(" + bro.getName() + "/" + bro.getBackground().getID()
                        + "): [" + stars + "] " + traitsCsv);
                }

                // DIAGNOSTIC: compare cached-world vs rebuilt-world outcome +
                // per-bro trait fingerprints. (vbros are still spawned here; the
                // rebuilt fingerprint pass is full — the verify loop above may
                // have broken early on first fail.)
                if (diag_on) {
                    diag_total++;
                    local rebuilt_fp = [];
                    foreach (i, bro in vbros) rebuilt_fp.append(::BBReroll_BF_TraitFingerprint(bro));
                    local traits_match = (diag_cached_fp.len() == rebuilt_fp.len());
                    if (traits_match) {
                        for (local i = 0; i < rebuilt_fp.len(); i++) {
                            if (diag_cached_fp[i] != rebuilt_fp[i]) { traits_match = false; break; }
                        }
                    }
                    if (traits_match && diag_cached_pass == vpass) diag_agree++;
                    if (traits_match && diag_cached_pass == vpass) {
                        ::logInfo(Tag + " DIAGVERIFY seed=" + seed + " cached_pass=" + diag_cached_pass
                            + " rebuilt_pass=" + vpass + " traits=MATCH");
                    } else {
                        ::logWarning(Tag + " DIAGVERIFY seed=" + seed + " cached_pass=" + diag_cached_pass
                            + " rebuilt_pass=" + vpass + " traits=DIFFER");
                        local nmax = rebuilt_fp.len();
                        if (diag_cached_fp.len() > nmax) nmax = diag_cached_fp.len();
                        for (local i = 0; i < nmax; i++) {
                            // Explicit if/else — this build's ?: evaluates both
                            // branches and would index out of bounds (gotcha #2).
                            local c = "(none)";
                            if (i < diag_cached_fp.len()) c = diag_cached_fp[i];
                            local r = "(none)";
                            if (i < rebuilt_fp.len()) r = rebuilt_fp[i];
                            if (c != r) ::logWarning(Tag + "   bro" + (i+1) + " cached=[" + c + "] rebuilt=[" + r + "]");
                        }
                    }
                }

                if (vpass) {
                    ::logWarning(Tag + " *** MATCH at iter " + x + " seed=" + seed + " (verified) ***");
                    foreach (fp in fps) ::logWarning(Tag + "   " + fp);
                    doCleanup();
                    match_seed = seed;
                    break;
                }
                // Verify failed. The world is now in candidate's state —
                // subsequent fast iters reuse it; that's fine (we only care
                // about stars in fast pass, which depend purely on the reseed).
                t_verify += ::Time.getExactTime() - vt0;
            }
        } catch (e) {
            skipped++;
            ::logWarning(Tag + " iter " + x + " threw: " + e + " — skipping");
        }

        local ct0 = ::Time.getExactTime();
        doCleanup();
        t_cleanup += ::Time.getExactTime() - ct0;

        if ((x + 1) % ::BBReroll_BF.LogEvery == 0) {
            local n = (x + 1).tofloat();
            local elapsed = ::Time.getExactTime() - run_t0;
            local rate = "?";
            if (elapsed > 0) rate = "" + (::Math.floor((n / elapsed) * 10.0) / 10.0);
            // verify avg is per-verify (not per-iter) since it only fires on
            // stars-pass; verify_count shows how often that is.
            local v_avg = 0;
            if (verify_count > 0) v_avg = ::Math.floor(t_verify / verify_count.tofloat() * 1000.0);
            local diag_txt = "";
            if (diag_total > 0) diag_txt = " diag:" + diag_agree + "/" + diag_total + " agree";
            ::logInfo(Tag + " iter " + (x + 1) + "/" + ::BBReroll_BF.MaxIters
                + " last_fail=" + last_fail + " skipped=" + skipped
                + " | avg ms: spawn=" + ::Math.floor(t_spawn / n * 1000.0)
                + " eval=" + ::Math.floor(t_eval / n * 1000.0)
                + " cleanup=" + ::Math.floor(t_cleanup / n * 1000.0)
                + " verify=" + v_avg + "x" + verify_count
                + " (" + rate + " iters/s)" + diag_txt);
        }
    }
    // Both exits log a human-readable FINISH line (the GUI tails these) and
    // then throw a unique sentinel. The startNewCampaign catch swallows the
    // sentinel; it does NOT rethrow (rethrow was tried — BB recovers to a
    // half-initialised main menu, worse than letting BB resume into the
    // onRender crash). Throwing also unwinds us cleanly out of the loop.
    if (match_seed != null) {
        ::logWarning(Tag + " *** FINISH: match found at seed=" + match_seed + ". Restart BB, then enter this seed for a real campaign. ***");
        throw ::BBReroll.FinishMatch;
    } else {
        ::logWarning(Tag + " *** FINISH: no seed matched in " + ::BBReroll_BF.MaxIters + " iters. last_fail=" + last_fail + ". Restart BB. ***");
        throw ::BBReroll.FinishMaxIters;
    }
};


// ---------- registration ----------

::mods_registerMod("bb_reroll_dump", ::BBReroll.Version, "BB Reroll Dump + Brute Force");

// Deterministic-bro reseed key. Both the brute force loop AND the real
// in-game scenario.onSpawnAssets seed RNG with this exact value, so the
// brothers produced by either path are identical for the same seed.
::BBReroll_RESEED_SUFFIX <- "::BBR";

// The per-scenario reseed hook fires on every spawn — i.e. every brute-force
// iteration. Logging it each time produced multi-MB log.html files on long
// runs (BB's engine log can't be rotated from the sandboxed mod, so we cap our
// own output instead). Log only the first few to confirm the mechanism, then
// go quiet. A real campaign start spawns once, so it always logs.
::BBReroll_ReseedLogN <- 0;
::BBReroll_ReseedLogMax <- 3;

// ---------- dependency self-check ----------
// Queued with a NULL expression (no dependency), so it runs even when Legends
// is absent — unlike the main hook below, which is ordered after >mod_legends.
// Queued functions run after every mod has registered, so ::Hooks.hasMod and
// the ::Legends / ::MSU globals are reliable here. Reports missing deps both
// to the log (GUI surfaces it) and as an in-game popup via ::Hooks.error.
// (Explicit if/else, not ?: — this build's ternary evaluates BOTH branches,
//  which would call ::Hooks.hasMod even when ::Hooks is absent. See gotcha #2.)
::mods_queue("bb_reroll_dump", null, function () {
    local hasHooks = ("Hooks" in ::getroottable());
    local legendsOk = false;
    local msuOk = false;
    if (hasHooks) {
        try { legendsOk = ::Hooks.hasMod("mod_legends"); } catch (e) {}
        try { msuOk     = ::Hooks.hasMod("mod_msu"); } catch (e) {}
    } else {
        legendsOk = ("Legends" in ::getroottable());
        msuOk     = ("MSU" in ::getroottable());
    }
    local missing = [];
    if (!legendsOk) missing.append("Legends (mod_legends)");
    if (!msuOk)     missing.append("MSU (mod_msu)");
    if (missing.len() > 0) {
        local names = "";
        foreach (i, m in missing) { if (i > 0) names += ", "; names += m; }
        local msg = "BB Reroll: missing required mod(s): " + names
            + ". BB Reroll needs Legends + MSU plus the hooks framework (mod_hooks / "
            + "modern_hooks). Install them and restart Battle Brothers.";
        ::logError(::BBReroll.Tag2 + " " + msg);
        if (hasHooks) { try { ::Hooks.error(msg); } catch (e) {} }  // in-game popup
    } else {
        ::logInfo(::BBReroll.Tag + " dependency check OK: Legends + MSU present");
    }
});

::mods_queue("bb_reroll_dump", ">mod_legends", function () {
    ::logInfo(::BBReroll.Tag + " mod queued (v" + ::BBReroll.Version + ")");

    // Wrap each scenario's onSpawnAssets individually so the real campaign uses
    // RNG state derived ONLY from the seed (not from world-gen entropy).
    // mods_hookBaseClass doesn't work here — every scenario overrides
    // onSpawnAssets, so wrapping the base never fires for instances.
    local scenarios = [
        // Vanilla
        "scenarios/world/lone_wolf_scenario",
        "scenarios/world/cultists_scenario",
        "scenarios/world/manhunters_scenario",
        "scenarios/world/militia_scenario",
        "scenarios/world/anatomists_scenario",
        "scenarios/world/beast_hunters_scenario",
        "scenarios/world/deserters_scenario",
        "scenarios/world/gladiators_scenario",
        "scenarios/world/paladins_scenario",
        "scenarios/world/raiders_scenario",
        "scenarios/world/rangers_scenario",
        "scenarios/world/southern_quickstart_scenario",
        "scenarios/world/trader_scenario",
        // Legends-added
        "scenarios/world/legend_random_3_scenario",
        "scenarios/world/legend_random_party_scenario",
        "scenarios/world/legend_random_solo_scenario",
        "scenarios/world/legend_risen_legion_scenario",
        "scenarios/world/legends_assassin_scenario",
        "scenarios/world/legends_beggar_scenario",
        "scenarios/world/legends_berserker_scenario",
        "scenarios/world/legends_crusader_scenario",
        "scenarios/world/legends_custom_scenario",
        "scenarios/world/legends_druid_scenario",
        "scenarios/world/legends_escaped_slaves_scenario",
        "scenarios/world/legends_free_company_scenario",
        "scenarios/world/legends_horse_scenario",
        "scenarios/world/legends_inquisition_scenario",
        "scenarios/world/legends_mage_scenario",
        "scenarios/world/legends_necro_scenario",
        "scenarios/world/legends_noble_scenario",
        "scenarios/world/legends_nomad_scenario",
        "scenarios/world/legends_party_scenario",
        "scenarios/world/legends_rangers_scenario",
        "scenarios/world/legends_scaling_beggar_scenario",
        "scenarios/world/legends_seer_scenario",
        "scenarios/world/legends_sisterhood_scenario",
        "scenarios/world/legends_solo_necro_scenario",
        "scenarios/world/legends_troupe_scenario",
    ];
    local hookedCount = 0;
    foreach (cls in scenarios) {
        try {
            ::mods_hookExactClass(cls, function (o) {
                local oldOnSpawnAssets = o.onSpawnAssets;
                o.onSpawnAssets = function () {
                    // Direct access in try/catch — '"m" in instance' lies about class
                    // members on some Squirrel builds, but the dotted access works.
                    local s = null;
                    try { s = this.World.State.m.CampaignSettings.Seed; } catch (e) {}
                    if (s != null && s != "") {
                        ::Math.seedRandomString(s + ::BBReroll_RESEED_SUFFIX);
                        // Throttled — see ::BBReroll_ReseedLogN. Keeps long
                        // brute-force runs from bloating log.html.
                        if (::BBReroll_ReseedLogN < ::BBReroll_ReseedLogMax) {
                            local sid = "?";
                            try { sid = this.m.ID; } catch (e) {}
                            ::logInfo(::BBReroll.Tag + " reseed before spawn (id=" + sid + ", seed=" + s + ")");
                            ::BBReroll_ReseedLogN++;
                        }
                    } else {
                        ::logWarning(::BBReroll.Tag + " spawn hook fired but no seed found");
                    }
                    oldOnSpawnAssets();
                };
            });
            hookedCount++;
        } catch (e) {
            ::logInfo(::BBReroll.Tag + " no hook for " + cls + " (" + e + ")");
        }
    }
    ::logInfo(::BBReroll.Tag + " hooked " + hookedCount + "/" + scenarios.len() + " scenarios for deterministic spawn RNG");

    ::mods_hookExactClass("states/world_state", function (o) {
        local oldStart = o.startNewCampaign;
        o.startNewCampaign = function () {
            // BB stores the seed lowercase even though the UI shows uppercase, so
            // compare case-insensitively. Trigger matches REROLL/reroll/etc.
            local userSeed = "";
            try {
                if ("CampaignSettings" in this.m
                    && this.m.CampaignSettings != null
                    && "Seed" in this.m.CampaignSettings) {
                    userSeed = "" + this.m.CampaignSettings.Seed;
                }
            } catch (e) {}
            if (userSeed.tolower() == ::BBReroll_BF.TriggerSeed.tolower()) {
                try { ::BBReroll_BF_Run(this); }
                catch (e) {
                    if (e == ::BBReroll.FinishMatch || e == ::BBReroll.FinishMaxIters) {
                        // Expected clean-finish sentinel. SWALLOW it — do NOT
                        // rethrow (rethrow makes BB recover to a half-init main
                        // menu). Returning normally lets BB resume into the
                        // onRender crash, which the GUI's match pane warns
                        // about ("BB may crash OR return to menu — restart").
                        ::logWarning(::BBReroll.Tag2 + " brute force finished (" + e + "). BB is now in a half-initialised state — restart it before playing.");
                    } else {
                        // Unexpected exception from inside the hooked region —
                        // NOT one of our finish sentinels. Could originate in
                        // vanilla, Legends, or another mod. Log it unmistakably
                        // and rethrow so normal BB error handling still fires
                        // instead of being silently swallowed.
                        ::logError(::BBReroll.Tag2 + " UNEXPECTED exception in startNewCampaign (NOT a BB Reroll finish — passing it through): " + e);
                        // In-game popup too (modern_hooks): the rethrow may kill
                        // BB before the log line above is flushed to disk, in
                        // which case the popup is the only visible trace.
                        if ("Hooks" in ::getroottable()) {
                            try { ::Hooks.error("BB Reroll: unexpected error during the run (not from this mod — passing it to the game): " + e); } catch (e2) {}
                        }
                        throw e;
                    }
                }
                return;
            }
            oldStart();
        };

        local oldOnInit = o.onInit;
        o.onInit = function () {
            oldOnInit();
            ::logInfo(::BBReroll.Tag + " world onInit");
            // Pre-read the seed. Try both `this.m.…` (works in some BB builds)
            // and `::World.State.m.…` (works in the scenario hook on this build).
            local seed = null;
            try { seed = this.m.CampaignSettings.Seed; } catch (e) {}
            if (seed == null) {
                try { seed = ::World.State.m.CampaignSettings.Seed; } catch (e) {}
            }
            try { ::BBReroll_Dump(this, seed); }
            catch (e) { ::logError(::BBReroll.Tag + " dump error in onInit: " + e); }
        };
    });
});

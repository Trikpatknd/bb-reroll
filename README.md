# BB Reroll

Seed finder for **Battle Brothers** — vanilla or with the **Legends** mod. It searches campaign seeds for a starting roster that matches your criteria (talent stars per brother, banned and required traits) **without running the game**, and shows the full roster of every seed it finds. With Legends it can also search by the **world map**: the number of ports and towns.

The seeds are ordinary campaign seeds. Anyone with the same game version, mods and recruit-related Mod Options gets the same brothers by typing the seed into the New Campaign screen — no mod of ours needed on either side. For the map, the Map Options must be the same too.

> **Coming from 3.x?** The in-game search (type `REROLL`, wait, restart) is gone; 4.0 replaces it. Remove the old `mod_bb_reroll_dump.zip` from `Battle Brothers/data/` — while it is there the game rolls *different* brothers for every seed, so seeds found here would not match. The GUI warns about it and offers to remove it. If you want the old method, use the [3.4.7 release](https://github.com/Trikpatknd/bb-reroll/releases).

---

## How it works

Battle Brothers creates the starting brothers with its own scripts, from a random generator seeded with the seed text. BB Reroll runs **those same scripts** — the base game's and the installed mods' — in its own interpreter, with a stand-in for the engine underneath, straight from the files of your install:

- the base game's compiled scripts inside `data/data_*.dat`,
- every mod zip in `data/` (Legends, MSU, Modern Hooks, …), in the versions you actually have.

Nothing is extracted or copied into the game, and no game or mod files are part of this project. The first search after a game update takes about 15 seconds longer: the game's scripts are read once and cached under `%LOCALAPPDATA%\BB Reroll`.

The search runs in parallel worker processes. Every match is rolled a second time on a freshly built game state before it is shown.

The world map comes from the game's scripts in the same way. The game makes the map from the seed text, before it makes the brothers. BB Reroll runs the game's map scripts with stand-ins for the engine's map functions (the tile grid and the path finder), made from what the game does. This works with Legends only. Read **Map conditions** below.

### What it was checked against

- **Battle Brothers 1.5.2.3, unmodded** — rosters compared by hand in the real game.
- **Battle Brothers 1.5.2.3 + Legends 19.4.22 + MSU 1.9.0 + Modern Hooks 0.6.0** — 96 real campaign starts (every searchable origin, two seeds each, plus searched and letter seeds) logged by the game and reproduced on every field: names, backgrounds, talents, traits, stats and gear.
- **The world map, Battle Brothers 1.5.2.3 + Legends 19.4.22** — 40 maps made by the game itself, compared with the maps of this program. On all 40 maps, every town matches (kind, tile, size, port and name; the names of city states excepted), and so does the terrain before the roads are made. 96 older logged map generations match up to the end of the land and sea step. Roads and some names do not match yet (see Limits).

Other versions are read the same way and will usually just work, but they are unverified until someone compares a seed in the game. Seeds are specific to the game version and mod versions: an update that changes how recruits are rolled changes what every seed gives.

---

## Requirements

- Windows 10/11
- Battle Brothers installed (Steam installs are found automatically; otherwise point the GUI at the game folder)
- To build: Python 3.10+ (see `requirements.txt`)
- About 0.8 GB of memory per search worker with Legends (less for the unmodded game)

## Install

Build from source:

```powershell
git clone https://github.com/Trikpatknd/bb-reroll.git
cd bb-reroll
build_exe.bat
# → dist\bb_reroll_gui.exe
```

Put the `.exe` anywhere and double-click it. For dev mode (no build): `pip install -r requirements.txt` and `python gui.py`.

---

## Use

1. **Game setup** — `Legends` (your game with the mods in its data folder) or `Vanilla` (your game without mods). Only what is installed is offered; the header shows the game that was found, and **Game folder** lets you pick another install.
2. **Origin** — the brother count fills in by itself. Origins that other installed mods add to the game's menu are listed too.
3. **Stars grid** — 0 = no condition, 1-3 = minimum stars. Row **All** is for every brother; a numbered row is for one brother and replaces row All for him (a numbered row of all zeros uses row All). Above the grid you see what each brother of the origin gets — fixed stars, how many random stars, stats that never get stars. Each cell only offers what is possible: cells a brother can never get and the stars the origin fixes are grey and locked (fixed stars are shown with their value; they are no condition, so row All still applies to that brother). Conditions no seed can meet (more starred stats than a brother can have, a stat he never gets stars in, a fixed star asked higher) are named before the search starts.
   **Stat rolls** (switch above the grid) — the least a base stat's roll may be: *mid* = the middle third or better, *high* = the top third **of what that brother's background can roll**. The background sets most of a stat (a Minstrel always has 55 melee skill); the seed only moves it inside that range, so this is what a search can actually choose. Cells for stats the seed cannot move for that brother are greyed. **Set row** at the end of a row sets the whole row at once, e.g. every stat to *high*. Results show each brother's rolls under **Details**, e.g. `MSK 48 high (45-50)`.
   **Backgrounds** (third switch) — the background a brother must have. Most origins always give the same backgrounds (the view lists them); some let the seed pick a brother's background from a list: Legends' Free Company, Random Party / Trio / Solo and both games' Peasant Militia. For those, each brother whose background varies gets a menu with exactly the backgrounds his list holds, and row **Any brother** (two or more varied brothers) asks that at least one brother has the background. Together with **Stat rolls** this asks for strong stats outright: a *high* roll is high for that background, so *Hedge Knight* + *MSK high* is a strong fighter.
   **Map** (fourth switch) — conditions for the world map: ports and towns. Read **Map conditions** below.
4. **Banned / Required traits** — tick what matters. No brother may have a banned trait; every brother needs one (`any`) or all (`all`) of the required ones. Hover a trait to see what it does, from the game's own tooltip (▲ good, ▼ bad). Traits can be renamed, removed and added.
5. **Battle sisters** — set it as in the game's Mod Options (Legends only); it changes who is rolled.
6. **▶ Search** — searches until **Seeds to test** are tested or **Matches to find** are found. The status line shows progress, speed and, after a few hundred seeds, an estimate like *Approximately 1 in 3,400 seeds matches*. If a brother (or row Any brother) has not matched once in 300 seeds, a notice says so. **■ Stop** ends it. Matches appear in the result list with their roster and the buttons **Copy seed**, **Copy roster** (full details), **Copy seed post** (a ready-made Legends Discord post with every brother's background and stars, the game version and the installed mods, so others can tell whether the seed works for them) and **Details** (each brother's stat rolls and, with Legends, perk groups). A search with map conditions also gives the button **Show map**.
7. Start a New Campaign with the same origin and type the seed **exactly as shown**.

The program texts follow the writing rules of ASD-STE100 (Simplified Technical English).

The first start after installing or updating the game or a mod works out what each origin can roll and what each trait does (about 2 minutes with Legends, in the background; kept under `%LOCALAPPDATA%\BB Reroll`). Searching works meanwhile — only the extra checks and tooltips wait for it.

**Check a seed** → **Show roster** shows the roster any seed gives for the chosen setup and origin — handy for a seed someone shared. Seed text is case-sensitive in the game (`SEEDTEST` and `seedtest` are different seeds); the search only produces digit seeds, so there is nothing to mistype.

Speed with Legends is about 3 seeds per second per worker; each worker takes ~15 seconds to load the game's scripts.

### Map conditions

Use them to search for seeds by their world map. They work with the **Legends** setup only. Open the switch **Map** above the grid. Each condition is a minimum. 0 is no condition. A map must meet all conditions.

| Field | What it counts |
|---|---|
| Ports | Towns with a harbor. Ships travel between ports. |
| Southern ports | Ports of the southern city states. |
| Northern ports | Ports in the north band that are not southern. |
| North band (%) | The part of the map that counts as north: this percent of the map rows, counted from the north edge. The default is 33. |
| City states, Strongholds, Villages, Towns, Cities | The number of towns of each type. |

**Map Options.** The map depends on the Map Options of the game. The Map view has the seven Map Options of the Legends Mod: Land Mass Ratio, Water, Snowline, Settlements, Factions, Decked Out Citadels and All trade buildings available. They start with the Legends defaults (50, 38, 85, 19, 3, No, No). **Write the same values as in your own Mod Options** (Legends Mod, page Map Options). With other values the game makes a different map, and the seed does not match. The program does not read your saved Mod Options. The Map Options do not change the brothers. A search without map conditions does not use them.

**Speed.** One map takes about 40 seconds on one worker. With 8 workers this is about 0.15 to 0.2 maps per second. Set brother conditions too: then the search builds a map only for the seeds whose brothers match. With map conditions alone, it builds a map for every seed. The estimate *Approximately 1 in N seeds matches* shows after 30 maps. Conditions that no map can meet (for example, more southern ports than the map has city states) are named before the search starts.

**What to expect.** In a survey of 1,000 maps with the default Map Options, the median was 4 ports. 22.6 % of the maps had 5 or more ports, and 3.9 % had 6 or more. 39 % had at least one southern port. 22 % had at least one northern port (band 33 %). Every map had 6 strongholds.

**Results.** **Show map** on a result opens the map of the seed: terrain, towns and ports. North is at the top. A ring marks a port. A dashed line marks the north band. Point at a town to read its name and type. **Copy seed post** adds a Map line and the Map Options to the post. **Check a seed** with a map condition builds the map of that seed too.

The map depends on the seed, the Map Options, the game version and the mod versions. It does not depend on the origin. The brothers do not depend on the map. (Deserters is the exception; it is not offered.)

### Star keys

| Key | Stat |
|---|---|
| `hp` | Hitpoints |
| `fat` | Fatigue |
| `res` | Resolve |
| `init` | Initiative |
| `msk` | Melee Skill |
| `rsk` | Ranged Skill |
| `mdf` | Melee Defense |
| `rdf` | Ranged Defense |

### Command line

The search is also a command-line tool:

```powershell
python -m bbseed.search --profile legends --origin trader_scenario --stars 1 "res2 fat2" --ban dumb --count 3
python -m bbseed.search --profile legends --origin trader_scenario --tier 1 "msk:high hp:mid" --count 3
python -m bbseed.search --profile legends --origin legends_free_company_scenario --background 3 "hedge_knight swordmaster" --tier 3 "msk:high"
python -m bbseed.search --profile legends --origin legend_random_party_scenario --background any hedge_knight
python -m bbseed.search --profile vanilla --origin early_access_scenario --show 1234567890
python -m bbseed.search --profile legends --list-origins
python -m bbseed.catalog --profile legends     # what each origin's brothers can get (stars, backgrounds), per slot
python -m bbseed.search --profile legends --origin trader_scenario --ports 5 --ports-north 1 --towns city_state=3 --workers 8
python -m bbseed.search --profile legends --origin trader_scenario --ports 4 --mod-setting mod_legends:Settlements=24 --mod-setting mod_legends:StackCitadels=true
python -m bbseed.search --profile legends --map 1234567890 --svg map.svg     # the map of one seed (about 40 s): towns and ports as text, a picture as SVG
```

Map conditions: `--ports N`, `--ports-south N`, `--ports-north N`, `--north-band P` (default 33) and `--towns TYPE=N` (use it again for more types). The town types are `city_state`, `military` (strongholds), `size1` (villages), `size2` (towns) and `size3` (cities). Set the Map Options with `--mod-setting mod_legends:KEY=VALUE`. The keys are `LandRatio`, `Water`, `Snowline`, `Settlements`, `Factions`, `StackCitadels` and `AllTradeLocations` (the last two take `true` or `false`). Use the same values as in the Mod Options of your game; a key you leave out has the Legends default. `--map` uses the origin `trader_scenario` unless you give `--origin`; the map does not depend on it.

---

## Limits

- **Deserters is not offered.** Its recruits are created after a step that depends on the generated map, so the seed text alone does not decide them.
- **Vanilla's "Random" origin is not offered**: the game picks the origin with a random draw before the seed is used, so a seed cannot decide it. Pick the origin itself instead.
- **Mod Options**: only Legends' Battle Sisters and the seven Map Options (for map conditions) can be set. Every other mod setting is taken at the mod's default; if you changed one that affects recruits, results can differ.
- **Origins whose backgrounds change from seed to seed** (Legends' Random Party/Solo/Trio, Free Company, Peasant Militia) get no limits in the stars grid: what they can roll is only what a sample of seeds showed. Their background menus are exact: they hold the lists the origin picks from (a list the sample seeds never used, like Random Party's rare second list, can only show up when a brother who shares the first list used it).
- **Other mods** are loaded as they are installed. A mod that needs engine functions the stand-in does not model stops the search with a load error instead of giving wrong results.
- The game's **Map Options do not affect the starting brothers** (they are rolled from the seed after the map is made), only the map itself.
- **Map conditions work with Legends only.** Vanilla is not offered yet. The maps are checked for game 1.5.2.3 with Legends 19.4.22. For other versions the Map view says that the results are not verified.
- **The Map Options must match yours.** Type the values of your Mod Options into the Map view. The program does not read them from the game. With other values the seed gives another map.
- **Roads are not exact.** The program does not copy the path finder of the game exactly. Its roads, region names, faction names and city-state names differ from the game. No condition uses them. The drawn map shows terrain, towns and ports, with no roads. A few terrain tiles near roads (1 to 24 of about 24,000) can differ from the game. The program does not find the start position of your company.
- **Maps are slow.** One map takes about 40 seconds on one worker, so a map search tests far fewer seeds than a search for brothers alone. Set brother conditions too.
- **A few seeds stop the map step with an error** (3 of 1,000 in a survey). The program does not know if the game makes a map for these seeds. The search skips them.

---

## File layout

```
bb_reroll/
├── README.md
├── VERSION                       # single source of truth for the version
├── gui.py                        # GUI entry point
├── gui.spec                      # PyInstaller spec
├── build_exe.bat                 # one-click build
├── requirements.txt              # runtime deps (requirements-dev.txt for tests)
├── bbreroll/                     # GUI helpers (tkinter-free, unit-tested)
│   ├── criteria.py               #   criteria model, default trait lists, pre-search checks
│   ├── offline_origins.py        #   game setups found on this PC, origins and their scenario scripts
│   ├── origin_hardcoded_stars.py #   per-origin fixed talent stars (Legends; fallback until the catalog exists)
│   ├── star_limits.py            #   what stars each brother can get → grid limits, info text, impossible criteria
│   ├── backgrounds.py            #   which backgrounds each brother can get → Backgrounds view, impossible criteria
│   ├── seed_report.py            #   Discord seed-share post formatter (with the map and the Map Options)
│   ├── map_conditions.py         #   map conditions: labels, what a map can have at most, impossible conditions, the post's map line
│   ├── map_view.py               #   the Map view without tkinter: fields, checks, settings, Map Options
│   └── trait_names.py            #   trait ID → display name
├── bbseed/                       # the search: the game's campaign-start scripts, run without the game
│   ├── rng.py                    #   the game's seeded random generator
│   ├── sq/                       #   Squirrel interpreter (source text and compiled scripts)
│   ├── engine.py, world.py       #   stand-in for the engine's native side
│   ├── gamedata.py, profiles.py  #   finds the install, reads its script archives, defines the setups
│   ├── lab.py                    #   Lab(profile).roster(seed, origin), world_map(seed), perk groups, installed mods
│   ├── hexmap.py                 #   the tile grid of the world map: stand-in for the engine's tile functions
│   ├── navigator.py              #   the path finder of the world map: stand-in for the engine's navigator
│   ├── mapgen.py                 #   builds the map of a seed (the game's own map scripts), the map summary, the condition counts
│   ├── mapdraw.py                #   the map as a picture (SVG, and the same numbers for the GUI's canvas)
│   ├── search.py                 #   the parallel search (brothers and map) + match-odds estimate (+ command line)
│   ├── talents.py                #   which stars the talent roll makes, which ones an origin fixes, background lists
│   ├── rolls.py                  #   each stat roll's place in what the background can roll (low/mid/high)
│   ├── traits.py                 #   what each trait does, from the game's tooltips
│   └── catalog.py                #   per installed game: origins, star facts, trait effects (cached)
└── tests/                        # pytest suite (python -m pytest)
```

Tests that need the game (`tests/test_offline_game.py`, `tests/test_game_features.py`, `tests/test_mapgen_game.py`, `tests/test_offline_map.py`, part of `tests/test_offline_origins.py`) are skipped when it is not installed.

---

## Acknowledgements

The idea of brute-forcing seeds for a starting roster comes from `mod_seedfinder` (credit: Discord user **mmgru**), which BB Reroll 1.x–3.x built on inside the game. The layout of the game's compiled script files follows the public Squirrel 3.0.4 sources and the documentation of Adam Milazzo's Battle Brothers mod kit.

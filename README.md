# BB Reroll

Brute-force seed finder for **Battle Brothers + Legends mod**. Search thousands of campaign seeds inside the game until one produces a starting roster that matches your criteria. Configured from a one-window GUI.

---

## How it works

1. **Squirrel mod** hooks the new-campaign screen. Type **`REROLL`** in the seed input → instead of starting a campaign, the mod loops through random seeds:
   - **Fast pass** (cached world): generate seed → reseed RNG → spawn the chosen origin's roster → check star thresholds only
   - **Slow verify** (rebuild world with the candidate's seed): full evaluation including traits, banned, required — matches what BB does for a real campaign start with that seed
2. **GUI** generates the mod's config (stars per slot, banned/required traits, origin) and deploys the packaged ZIP to BB's `data/` folder.
3. **Verified matches** are logged to `Documents\Battle Brothers\log.html`. The GUI tails the log live, fires a desktop notification, and shows the seed in a copy-able banner.

---

## Install

Build from source — keeps you off deprecated prebuilt binaries.

1. Install Python 3.10+ and clone the repo.
2. Run `build_exe.bat` (Windows) or `pip install -r requirements.txt && pyinstaller --noconfirm gui.spec`. Output: `dist/bb_reroll_gui.exe`.
3. Double-click the .exe. The GUI opens.
4. **Save & Deploy** copies `mod_bb_reroll_dump.zip` into your BB `data/` folder (auto-detected on Steam installs; otherwise click Browse…).

For dev mode (no build), `python gui.py` runs the GUI directly.

---

## Use

1. **Origin** dropdown — pick yours. Brother count auto-fills.
2. **Stars grid** — 0 = don't care, 1-3 = minimum stars. Row `*` is the default; numeric rows override per-slot. Numeric rows of all zeros fall back to `*`. Cells with non-zero star requirements (your active criteria) highlight amber. The info panel above the grid shows which stars are hardcoded by the chosen origin — those pre-fill when you pick an origin so the brute-force baseline is visible at a glance.
3. **Banned / Required traits** — tick the trait IDs you care about. `🔍 Scan log` picks up any new trait IDs from your last play sessions.
4. **💾 Save & Deploy** — writes the mod and copies it into BB.
5. Launch BB → New Campaign → pick your origin → type **`REROLL`** as the seed → Start.
6. Watch the GUI's status line:
   - Green LED = fast pass running
   - Blue LED = slow verify (a candidate seed found, double-checking traits)
   - On match: green banner with seed + 📋 Copy. Desktop notification fires.
7. **Quit BB completely (Alt+F4), relaunch**, type the matched seed for a real campaign with the same origin. The bros will match the verified fingerprint.

⚠ Don't change Mod → Map Options between the brute force run and starting the real campaign. World gen reads those settings, so different settings = different world = different trait roll for the same seed.

---

## Star spec

The grid translates per slot to specs like `msk2 mdf2 fat3`. Stat keys:

| Key | Stat |
|---|---|
| `hp` | Hitpoints |
| `fat` | Fatigue |
| `res` | Bravery (Resolve) |
| `init` | Initiative |
| `msk` | Melee Skill |
| `rsk` | Ranged Skill |
| `mdf` | Melee Defense |
| `rdf` | Ranged Defense |

---

## Build from source

```powershell
git clone https://github.com/Trikpatknd/bb-reroll.git
cd bb-reroll
pip install -r requirements.txt
build_exe.bat
# → dist\bb_reroll_gui.exe
```

After editing `mod\bb_reroll_dump.nut`, regenerate the embedded template:
```powershell
python tools\embed_nut.py
```

---

## Caveats

- Brute force leaves BB in a half-initialized state. **You must restart BB** before starting a real campaign with the discovered seed.
- Strict criteria (e.g. 3 stars in 3 stats on every bro + specific trait) can take very long. Slot 1 with `msk2 mdf2` and "any good trait" is usually findable in minutes; tighter criteria push toward hours.
- BB Squirrel sandbox blocks file I/O from mods, so an in-GUI "Stop" button isn't possible. Use `MaxIters` to bound a run.
- The mod ships hooks for 38 known scenarios. If you pick an origin not in that list, brute force will fall back to a hardcoded Davkul roster.

---

## File layout

```
bb_reroll/
├── README.md
├── gui.py                      # GUI source
├── gui.spec                    # PyInstaller spec
├── build_exe.bat               # one-click build
├── requirements.txt
├── mod_template.py             # embedded copy of the .nut (auto-generated)
├── trait_names.py              # trait ID → display name (130 entries)
├── tools/embed_nut.py          # regenerate mod_template.py after .nut edits
└── mod/
    ├── bb_reroll_dump.nut      # Squirrel mod source
    ├── mod_bb_reroll_dump.zip  # packaged mod (auto-rebuilt by the GUI)
    └── _backup_v3.3.0-stable/  # last known-good snapshot
```

---

## Acknowledgements

Brute-force loop pattern inspired by `mod_seedfinder` (credit: Discord user **mmgru**). This project generalizes it to evaluate the chosen origin's actual starting roster via `scenario.onSpawnAssets()`, reseeds RNG deterministically per seed, and wraps everything in a GUI.

"""
BB Reroll Control Panel — single-window GUI for configuring the brute-force mod.

Features:
  • Origin dropdown (auto-sets brother count)
  • Stars grid (rows = brother slots, cols = the 8 stat keys, 0-3 each)
  • Banned + Required trait checklists (with custom additions)
  • Save & Deploy: regenerates mod/bb_reroll_dump.nut, builds the ZIP, copies
    it into <BB install>/data/.
  • Scan log for traits: pulls every trait ID the mod has emitted into the
    checklists so they grow over time.
  • Background log watcher: pops a desktop notification + flashes the GUI
    when [BBREROLL2] *** MATCH is found.

Runs as `python gui.py` for dev, or as a standalone `.exe` after PyInstaller.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

try:
    from plyer import notification
except Exception:
    notification = None

# Embedded copy of mod/bb_reroll_dump.nut so the GUI/exe can write a fresh .nut
# from scratch when none exists yet.
try:
    from mod_template import NUT_TEMPLATE
except Exception:
    NUT_TEMPLATE = ""

# Trait ID → display-name map (Lumbering / legend_heavy, etc.).
try:
    from trait_names import TRAIT_NAMES
except Exception:
    TRAIT_NAMES = {}

# Per-origin hardcoded talent stars — drives the info label above the grid
# and the auto-fill of the stars grid when an origin is picked.
try:
    from origin_hardcoded_stars import ORIGIN_HARDCODED_STARS, summarize as summarize_origin
except Exception:
    ORIGIN_HARDCODED_STARS = {}
    def summarize_origin(_origin: str) -> str:
        return ""


# ─────────────────────── paths ───────────────────────

def _app_dir() -> Path:
    """Where mod/, finds/, etc. live — next to the script in dev, next to the .exe when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _bundle_dir() -> Path:
    """Where bundled read-only resources live."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", _app_dir()))
    return _app_dir()


APP_DIR       = _app_dir()
BUNDLE_DIR    = _bundle_dir()
NUT_PATH      = APP_DIR / "mod" / "bb_reroll_dump.nut"
ZIP_PATH      = APP_DIR / "mod" / "mod_bb_reroll_dump.zip"
BB_DIR        = Path.home() / "Documents" / "Battle Brothers"
BB_LOG        = BB_DIR / "log.html"
SETTINGS_PATH = APP_DIR / "bb_reroll_gui.json"


def _read_app_version() -> str:
    """Version string from the repo-root VERSION file (the single source of
    truth). Bundled into the .exe via gui.spec; falls back to the version
    baked into the embedded template, then 'unknown'."""
    for base in (BUNDLE_DIR, APP_DIR):
        try:
            p = base / "VERSION"
            if p.exists():
                return p.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    try:
        from mod_template import NUT_VERSION
        return NUT_VERSION
    except Exception:
        return "unknown"


APP_VERSION = _read_app_version()


def _sanitize_trait(name: str) -> str:
    """Strip a user-typed trait name to a Squirrel-safe identifier ([a-z0-9_]).
    Spaces and hyphens become underscores so 'Iron Lungs' → 'iron_lungs'."""
    s = name.strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s.strip("_")


def _id_to_display(trait_id: str) -> str:
    """Fallback display name for trait IDs not in TRAIT_NAMES — strips the
    `legend_` prefix and titlecases the rest. 'legend_steady_hands' → 'Steady Hands'."""
    s = trait_id
    if s.startswith("legend_"):
        s = s[len("legend_"):]
    return s.replace("_", " ").title() if s else trait_id


# ─────────────────────── presets ───────────────────────

# (display name, brother count). None = let user set manually.
# Display names + counts confirmed from mod_legends/hooks/scenarios/world/*.nut
# and scripts/scenarios/world/legends_*_scenario.nut (Legends 19.3.24).
# Skipped: tutorial / random / debug-random scenarios (don't make sense for seed brute-forcing).
ORIGINS = [
    ("Custom",                    None),
    # Vanilla origins (Legends-hooked)
    ("Anatomist",                    3),
    ("Band of Poachers",             3),
    ("Beast Slayers",                3),
    ("Davkul Cultists",              5),
    ("Deserters",                    3),
    ("Gladiators",                   3),
    ("Lone Wolf",                    1),
    ("Manhunters",                   6),
    ("Northern Raiders",             4),
    ("Oathtakers",                   2),
    ("Peasant Militia",             12),
    ("Trading Caravan",              2),
    # Legends-added origins (4 dropped: Build your own, Druid [Legacy], Horse Party,
    # Mage — all hard-disabled via `function isValid() { return false; }` and
    # therefore not selectable in BB's new-campaign picker)
    ("Adventuring Party",            6),
    ("Assassin",                     1),
    ("Berserker",                    1),
    ("Crusader",                     1),
    ("Escaped Slaves",               5),  # requires Blazing Deserts DLC
    ("The Free Company",             5),
    ("The Inquisition",              3),
    ("Master Necromancer",           6),
    ("Noble",                        6),
    ("Nomad Tribe",                  5),
    ("Original Beggar Challenge",    1),
    ("Ranger",                       2),
    ("Scaling Beggar Challenge",     1),
    ("Seer",                         1),
    ("Sisterhood",                   6),
    ("The Cabal",                    4),
    ("The Troupe",                   4),
]

STATS = ["hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf"]

# Legends-aware trait categorization. IDs match the `trait.X` skill IDs the mod
# emits in dumps (after stripping the `trait.` prefix). Defaults reflect a
# typical "I want a strong roll, no glaring flaws" preset — user can tweak any
# of them via the GUI. See plans/first-we-should-get-abstract-sutton.md.
DEFAULT_BANNED = [
    # Vanilla bad traits (33)
    "addict", "ailing", "asthmatic", "bleeder", "brute", "clubfooted", "clumsy",
    "cocky", "craven", "dastard", "disloyal", "drunkard", "dumb", "fainthearted",
    "fat", "fear_beasts", "fear_greenskins", "fear_undead", "fragile",
    "gluttonous", "greedy", "hesitant", "impatient", "insecure", "irrational",
    "mad", "night_blind", "paranoid", "pessimist", "short_sighted",
    "superstitious", "tiny", "weasel",
    # Legends-added bad traits (10)
    "legend_cannibalistic", "legend_deathly_spectre", "legend_double_tongued",
    "legend_fear_dark", "legend_fear_nobles", "legend_fleshless", "legend_heavy",
    "legend_predictable", "legend_rotten_flesh", "legend_slack",
    "legend_withering_aura",
]
DEFAULT_REQUIRED = [
    # Vanilla good traits (22)
    "athletic", "bloodthirsty", "brave", "bright", "determined", "dexterous",
    "eagle_eyes", "fearless", "huge", "iron_jaw", "iron_lungs", "loyal", "lucky",
    "optimist", "quick", "spartan", "strong", "sure_footing", "survivor", "swift",
    "teamplayer", "tough",
    # Legends-added good traits (14)
    "legend_aggressive", "legend_ambitious", "legend_arena_champion",
    "legend_arena_invictus", "legend_beastslayers", "legend_gift_of_people",
    "legend_martial", "legend_natural", "legend_pragmatic", "legend_seductive",
    "legend_steady_hands", "legend_sureshot", "legend_undead_killer",
    "legend_unpredictable",
]

# Origin-baked, scenario-specific, acquired, or cosmetic traits.
# These IDs WILL appear in dumps but should never be auto-added to either
# checklist — banning one would reject the origin that grants it; requiring
# one would demand a trait an origin can't roll.
IGNORE_TRAITS = frozenset([
    "player",
    "cultist_acolyte", "cultist_chosen", "cultist_disciple", "cultist_fanatic",
    "cultist_prophet", "cultist_zealot",
    "legend_intensive_training_trait", "legend_lw_relationship",
    "legend_brothers_in_chains", "legend_appetite_donkey",
    "legend_inquisition_disciple", "legend_horse", "legend_necromancer",
    "legend_nomad", "legend_peasant", "legend_light",
    "hate_beasts", "hate_greenskins", "hate_undead",
    "noble_killer", "undead_killer",
    "old", "night_owl", "glorious", "deathwish",
    "pit_fighter", "arena_fighter", "arena_veteran",
])
# Anything starting with these prefixes is also ignored (covers the prosthetics
# + the paladin oath family — too many to enumerate, all origin/acquired).
IGNORE_PREFIXES = ("legend_prosthetic_", "oath_of_")


# ─────────────────────── .nut config codec ───────────────────────

def _find_config_block(text: str):
    """Return (start, end) indices of `::BBReroll_BF <- { … };` or None."""
    marker = "::BBReroll_BF <- {"
    start = text.find(marker)
    if start == -1:
        return None
    depth = 0
    i = text.find("{", start)
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                while end < len(text) and text[end] in " \t\r\n":
                    end += 1
                if end < len(text) and text[end] == ";":
                    end += 1
                return start, end
        i += 1
    return None


def parse_existing_config(nut_text: str) -> dict:
    """Best-effort parse of the existing ::BBReroll_BF block. Missing pieces → defaults."""
    cfg = {
        "trigger_seed": "REROLL",
        "max_iters":   10000,
        "log_every":   10,
        "stars_by_slot": {"*": {}},      # slot_key (str) -> {stat: int}
        "banned":   list(DEFAULT_BANNED),
        "required": list(DEFAULT_REQUIRED),
        "required_mode": "any",          # "any" = at least one match, "all" = every one
    }
    block = _find_config_block(nut_text)
    if block is None:
        return cfg
    body = nut_text[block[0]:block[1]]

    m = re.search(r'TriggerSeed\s*=\s*"([^"]*)"', body)
    if m: cfg["trigger_seed"] = m.group(1)
    m = re.search(r'MaxIters\s*=\s*(\d+)', body)
    if m: cfg["max_iters"] = int(m.group(1))
    m = re.search(r'LogEvery\s*=\s*(\d+)', body)
    if m: cfg["log_every"] = int(m.group(1))

    sbs = re.search(r'StarsBySlot\s*=\s*\{([^}]*)\}', body)
    if sbs:
        cfg["stars_by_slot"] = {}
        for key, spec in re.findall(r'\["([^"]*)"\]\s*=\s*"([^"]*)"', sbs.group(1)):
            stats = {}
            for tok in re.findall(r'([a-zA-Z]+)(\d+)', spec):
                stats[tok[0].lower()] = int(tok[1])
            cfg["stars_by_slot"][key] = stats
        if "*" not in cfg["stars_by_slot"]:
            cfg["stars_by_slot"]["*"] = {}

    bt = re.search(r'BannedTraits\s*=\s*\[([^\]]*)\]', body)
    if bt:
        cfg["banned"] = re.findall(r'"([^"]+)"', bt.group(1))
    # Accept either new field name (Required) or old (RequiredAny).
    rq = re.search(r'\bRequired\s*=\s*\[([^\]]*)\]', body) or \
         re.search(r'RequiredAny\s*=\s*\[([^\]]*)\]', body)
    if rq:
        cfg["required"] = re.findall(r'"([^"]+)"', rq.group(1))
    rm = re.search(r'RequiredMode\s*=\s*"(any|all)"', body)
    if rm:
        cfg["required_mode"] = rm.group(1)
    return cfg


def render_config_block(cfg: dict) -> str:
    """Render a fresh ::BBReroll_BF block from cfg."""
    # Spec strings
    spec_lines = []
    # always emit "*" first
    keys = ["*"] + sorted([k for k in cfg["stars_by_slot"] if k != "*"], key=lambda k: (len(k), k))
    for key in keys:
        if key not in cfg["stars_by_slot"]:
            continue
        stats = cfg["stars_by_slot"][key]
        spec = " ".join(f"{s}{n}" for s, n in stats.items() if n > 0)
        spec_lines.append(f'        ["{key}"] = "{spec}",')

    banned_lines = []
    for i, t in enumerate(cfg["banned"]):
        if i % 6 == 0:
            banned_lines.append("        ")
        banned_lines[-1] += f'"{t}",'
        if i % 6 != 5:
            banned_lines[-1] += " "

    req_lines = []
    for i, t in enumerate(cfg["required"]):
        if i % 6 == 0:
            req_lines.append("        ")
        req_lines[-1] += f'"{t}",'
        if i % 6 != 5:
            req_lines[-1] += " "

    required_mode = cfg.get("required_mode", "any")
    return (
"::BBReroll_BF <- {\n"
f'    TriggerSeed = "{cfg["trigger_seed"]}",\n'
f"    MaxIters    = {cfg['max_iters']},\n"
f"    LogEvery    = {cfg['log_every']},\n"
"\n"
"    StarsBySlot = {\n"
+ "\n".join(spec_lines) + "\n"
"    },\n"
"\n"
"    BannedTraits = [\n"
+ "\n".join(banned_lines) + "\n"
"    ],\n"
"\n"
f'    RequiredMode = "{required_mode}",  // "any" = at least one match; "all" = every one\n'
"    Required = [\n"
+ "\n".join(req_lines) + "\n"
"    ],\n"
"\n"
'    // Fallback used only if dynamic origin lookup fails.\n'
"    Fallback = {\n"
"        backgrounds = [\n"
'            "legend_magister_background",\n'
'            "legend_husk_background",\n'
'            "cultist_background",\n'
'            "cultist_background",\n'
'            "legend_lurker_background",\n'
"        ],\n"
'        granted_traits = ["CultistFanatic"],\n'
'        removed_traits = ["Superstitious","Dastard","Insecure","Craven"],\n'
"    },\n"
"};"
    )


# ─────────────────────── deploy ───────────────────────

def rewrite_nut(cfg: dict):
    """Write a fresh .nut with the GUI's config. Creates the file (and parent
    directory) from the embedded template if it doesn't exist yet."""
    NUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if NUT_PATH.exists():
        text = NUT_PATH.read_text(encoding="utf-8")
    elif NUT_TEMPLATE:
        text = NUT_TEMPLATE
    else:
        raise FileNotFoundError(
            f"{NUT_PATH} not found and no embedded template available. "
            "Place bb_reroll_dump.nut in the mod/ folder."
        )
    block = _find_config_block(text)
    if block is None:
        raise RuntimeError("Couldn't find ::BBReroll_BF block in the .nut/template.")
    new = text[:block[0]] + render_config_block(cfg) + text[block[1]:]
    NUT_PATH.write_text(new, encoding="utf-8")


def rebuild_zip():
    NUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(NUT_PATH, arcname="scripts/!mods_preload/bb_reroll_dump.nut")


def copy_to_bb(bb_data_dir: Path):
    target = bb_data_dir / ZIP_PATH.name
    shutil.copy2(ZIP_PATH, target)
    return target


# ─────────────────────── log watcher ───────────────────────

MATCH_RE    = re.compile(r"\[BBREROLL2\]\s+\*\*\*\s+MATCH\s+at\s+iter\s+(\d+)\s+seed=(\S+?)(?:\s+\(verified\))?\s+\*\*\*")
PROGRESS_RE = re.compile(r"\[BBREROLL2\]\s+iter\s+(\d+)/(\d+)")
START_RE    = re.compile(r"\[BBREROLL2\]\s+brute force start")
# Mod logs this line every time a fast-pass star check passes and a slow
# verify (full world rebuild + trait eval) kicks in.
VERIFY_RE   = re.compile(r"\[BBREROLL2\]\s+iter\s+(\d+)\s+stars-pass\s+seed=(\S+)")
# Init line, written once at BB launch (after Legends loads). Doubles as the
# "mod is loaded" signal and the source of the installed mod version.
INIT_RE     = re.compile(r"\[BBREROLL\]\s+mod queued \(v([0-9][0-9A-Za-z.\-]*)\)")
# Clean-finish marker emitted just before the loop throws its sentinel.
FINISH_RE   = re.compile(r"\[BBREROLL2\]\s+\*\*\*\s+FINISH:\s+(.+?)\s+\*\*\*")


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


class LogWatcher(threading.Thread):
    def __init__(self, log_path: Path, on_match, on_progress, on_brute_start, on_verify_start,
                 on_mod_init=None, on_finish=None, poll=1.0):
        super().__init__(daemon=True)
        self.log_path        = log_path
        self.on_match        = on_match
        self.on_progress     = on_progress
        self.on_brute_start  = on_brute_start
        self.on_verify_start = on_verify_start
        self.on_mod_init     = on_mod_init
        self.on_finish       = on_finish
        self.poll = poll
        self._stop = threading.Event()
        self._pos = log_path.stat().st_size if log_path.exists() else 0

    def run(self):
        while not self._stop.is_set():
            try:
                if self.log_path.exists():
                    size = self.log_path.stat().st_size
                    if size < self._pos:
                        self._pos = 0   # log rotated/truncated
                    if size > self._pos:
                        with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                            f.seek(self._pos)
                            chunk = f.read()
                            self._pos = f.tell()
                        text = _strip_html(chunk)
                        # Mod init line (fires once at BB launch after Legends).
                        if self.on_mod_init:
                            mi = INIT_RE.search(text)
                            if mi:
                                self.on_mod_init(mi.group(1))
                        # Brute force just started → consume any stale STOP request.
                        if START_RE.search(text):
                            self.on_brute_start()
                        # Clean-finish marker → loop done, BB now half-initialised.
                        if self.on_finish:
                            mf = FINISH_RE.search(text)
                            if mf:
                                self.on_finish(mf.group(1))
                        for m in MATCH_RE.finditer(text):
                            self.on_match(int(m.group(1)), m.group(2))
                        # If both verify and progress fire in the same chunk,
                        # progress (most recent state) should win for display.
                        last_verify = None
                        for m in VERIFY_RE.finditer(text):
                            last_verify = (int(m.group(1)), m.group(2))
                        if last_verify:
                            self.on_verify_start(*last_verify)
                        last_progress = None
                        for m in PROGRESS_RE.finditer(text):
                            last_progress = (int(m.group(1)), int(m.group(2)))
                        if last_progress:
                            self.on_progress(*last_progress)
            except Exception:
                pass
            self._stop.wait(self.poll)

    def stop(self):
        self._stop.set()


# ─────────────────────── GUI ───────────────────────

class _TraitEditDialog(ctk.CTkToplevel):
    """Modal dialog with two text inputs: display name + trait ID.

    Result is set to (display_name, sanitized_id) on OK, None on Cancel.
    Call .wait_window() (done in __init__) and then read .result on the parent."""

    def __init__(self, parent, current_display: str, current_id: str):
        super().__init__(parent)
        self.title("Edit trait")
        self.geometry("440x210")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        ctk.CTkLabel(self, text="Display name (label shown in the GUI):",
                     anchor="w").pack(fill="x", padx=14, pady=(14, 2))
        self._display = ctk.CTkEntry(self, width=400)
        self._display.pack(fill="x", padx=14)
        self._display.insert(0, current_display)

        ctk.CTkLabel(self, text="Trait ID (the snake_case name written into the .nut):",
                     anchor="w").pack(fill="x", padx=14, pady=(10, 2))
        self._tid = ctk.CTkEntry(self, width=400)
        self._tid.pack(fill="x", padx=14)
        self._tid.insert(0, current_id)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=14)
        ctk.CTkButton(btns, text="OK", width=90, command=self._ok).pack(side="right", padx=(6, 0))
        ctk.CTkButton(btns, text="Cancel", width=90, fg_color="transparent",
                      border_width=1, command=self._cancel).pack(side="right")

        self._display.focus_set()
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())
        # grab_set must come after the window is mapped on Windows; defer one tick.
        self.after(100, self.grab_set)
        self.wait_window()

    def _ok(self):
        self.result = (self._display.get().strip(), _sanitize_trait(self._tid.get()))
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(f"BB Reroll Control Panel — v{APP_VERSION}")
        self.geometry("960x900")
        self.minsize(880, 760)

        # Installed-mod version, learned from the dump log's init line.
        self.mod_version = None
        self._mod_seen = False

        self.origin_var       = ctk.StringVar(value="Custom")
        self.bro_count_var    = ctk.StringVar(value="5")
        self.trigger_seed_var = ctk.StringVar(value="REROLL")
        self.max_iters_var    = ctk.StringVar(value="10000")
        self.log_every_var    = ctk.StringVar(value="10")
        self.bb_path_var      = ctk.StringVar(value=self._guess_bb_path())
        self.status_var       = ctk.StringVar(value="Ready.")
        self.watch_var        = ctk.StringVar(value="idle")

        # Real status-LED tracking.
        self._last_activity_ts = 0.0
        self._watch_state      = "idle"

        self.stars_vars:             dict[tuple[str, str], ctk.StringVar] = {}
        self.stars_widgets:          dict[tuple[str, str], "ctk.CTkOptionMenu"] = {}
        # Default CTk colors captured at widget construction so we can restore
        # them when a cell's value returns to 0. Cells with value > 0 get the
        # active highlight palette applied to fg_color/button_color/text_color.
        self.stars_widget_defaults:  dict[tuple[str, str], dict] = {}
        self.banned_vars: dict[str, ctk.BooleanVar] = {}
        self.required_vars: dict[str, ctk.BooleanVar] = {}
        self.banned_known   = list(DEFAULT_BANNED)
        self.required_known = list(DEFAULT_REQUIRED)
        self.required_mode_var = ctk.StringVar(value="any")
        # ID -> display name. Seeded from TRAIT_NAMES; user-overrides
        # come from bb_reroll_gui.json (loaded by _load_settings).
        self.trait_display: dict[str, str] = dict(TRAIT_NAMES)

        # ETA tracking — list of (timestamp, current_iter) tuples for last-N progress events.
        self._progress_history: list[tuple[float, int]] = []
        self._matches: list[dict] = []   # session-level history of matches

        self._build_ui()
        self._load_settings()
        # Sync bro count + info label to the saved origin BEFORE pulling
        # config from the .nut. The .nut load skips stars at startup so the
        # grid stays at zero; user clicks "Reload .nut" to pull live stars.
        self._on_origin_change(self.origin_var.get())
        self._load_from_nut(load_stars=False)
        self._start_log_watcher()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── path helpers ──
    def _guess_bb_path(self) -> str:
        for p in [
            Path("G:/SteamLibrary/steamapps/common/Battle Brothers/data"),
            Path("C:/Program Files (x86)/Steam/steamapps/common/Battle Brothers/data"),
            Path("C:/Program Files/Steam/steamapps/common/Battle Brothers/data"),
        ]:
            if p.exists():
                return str(p)
        return ""

    # ── UI build ──
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Top: meta config
        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        for i in range(8):
            top.grid_columnconfigure(i, weight=1 if i in (1, 3, 5, 7) else 0)

        ctk.CTkLabel(top, text="Origin:").grid(row=0, column=0, padx=(8, 4), pady=8, sticky="e")
        ctk.CTkOptionMenu(top, values=[o[0] for o in ORIGINS], variable=self.origin_var,
                          command=self._on_origin_change).grid(row=0, column=1, sticky="ew", padx=4)
        ctk.CTkLabel(top, text="Brothers:").grid(row=0, column=2, padx=(8, 4), sticky="e")
        bc = ctk.CTkEntry(top, textvariable=self.bro_count_var, width=60)
        bc.grid(row=0, column=3, sticky="w", padx=4)
        self.bro_count_var.trace_add("write", lambda *_: self.after(120, self._rebuild_stars_grid))

        ctk.CTkLabel(top, text="Trigger seed:").grid(row=0, column=4, padx=(16, 4), sticky="e")
        ctk.CTkEntry(top, textvariable=self.trigger_seed_var, width=100).grid(row=0, column=5, sticky="w", padx=4)
        ctk.CTkLabel(top, text="Max iters:").grid(row=0, column=6, padx=(16, 4), sticky="e")
        ctk.CTkEntry(top, textvariable=self.max_iters_var, width=80).grid(row=0, column=7, sticky="w", padx=4)

        ctk.CTkLabel(top, text="Log every:").grid(row=1, column=0, padx=(8, 4), pady=(0, 8), sticky="e")
        ctk.CTkEntry(top, textvariable=self.log_every_var, width=80).grid(row=1, column=1, sticky="w", padx=4, pady=(0, 8))
        ctk.CTkLabel(top, text="BB data folder:").grid(row=1, column=2, padx=(8, 4), pady=(0, 8), sticky="e")
        ctk.CTkEntry(top, textvariable=self.bb_path_var).grid(row=1, column=3, columnspan=4, sticky="ew", padx=4, pady=(0, 8))
        ctk.CTkButton(top, text="Browse…", width=80, command=self._browse_bb).grid(row=1, column=7, sticky="ew", padx=4, pady=(0, 8))

        # Stars grid
        stars_outer = ctk.CTkFrame(self)
        stars_outer.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        ctk.CTkLabel(stars_outer,
                     text=("STARS  (0 = don't care, 1-3 = minimum stars.  "
                           "A numeric slot row with all zeros falls back to the * default rule.)"),
                     font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(6, 2))
        self.origin_info_var = ctk.StringVar(value=summarize_origin(self.origin_var.get()))
        self.origin_info_label = ctk.CTkLabel(
            stars_outer,
            textvariable=self.origin_info_var,
            justify="left",
            anchor="w",
            font=("Consolas", 11),
            text_color="#9aa3b0",
        )
        self.origin_info_label.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))
        self.stars_frame = ctk.CTkFrame(stars_outer, fg_color="transparent")
        self.stars_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))

        # Traits — two scrollable columns
        traits_row = ctk.CTkFrame(self, fg_color="transparent")
        traits_row.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
        traits_row.grid_columnconfigure(0, weight=1)
        traits_row.grid_columnconfigure(1, weight=1)

        self._build_trait_pane(traits_row, 0, "BANNED  (any of these on a bro = fail)",
                               self.banned_known, self.banned_vars, "banned")
        self._build_trait_pane(traits_row, 1, "REQUIRED  (at least one per bro)",
                               self.required_known, self.required_vars, "required")

        # Action bar
        actions = ctk.CTkFrame(self)
        actions.grid(row=3, column=0, sticky="ew", padx=10, pady=(5, 5))
        actions.grid_columnconfigure(99, weight=1)
        ctk.CTkButton(actions, text="💾 Save & Deploy", height=36,
                      command=self._on_save).grid(row=0, column=0, padx=8, pady=8)
        ctk.CTkButton(actions, text="🔍 Scan log for traits", height=36,
                      command=self._on_scan_log).grid(row=0, column=1, padx=8, pady=8)
        ctk.CTkButton(actions, text="🧹 Clean stale mods", height=36,
                      command=self._on_clean_stale).grid(row=0, column=2, padx=8, pady=8)
        ctk.CTkButton(actions, text="📂 Open BB log", height=36,
                      command=self._open_log).grid(row=0, column=3, padx=8, pady=8)
        ctk.CTkButton(actions, text="↻ Reload .nut", height=36,
                      command=self._load_from_nut).grid(row=0, column=4, padx=8, pady=8)
        ctk.CTkButton(actions, text="↗ Check for updates", height=36,
                      fg_color="transparent", border_width=1,
                      command=self._open_github).grid(row=0, column=99, padx=8, pady=8, sticky="e")

        # Match history — scrollable list. Hidden until a match comes in.
        self.match_pane = ctk.CTkFrame(self)
        self.match_pane.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 5))
        self.match_pane.grid_columnconfigure(0, weight=1)
        match_head = ctk.CTkFrame(self.match_pane, fg_color="transparent")
        match_head.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        match_head.grid_columnconfigure(0, weight=1)
        self.match_title = ctk.CTkLabel(match_head, text="MATCHES (this session)",
                                        font=("Segoe UI", 12, "bold"))
        self.match_title.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(match_head, text="Clear", width=60, height=24,
                      command=self._clear_matches).grid(row=0, column=1, sticky="e")
        # Reminder: mod Map Options affect world gen → changing them between the
        # brute force run and the real campaign changes which bros that seed produces.
        ctk.CTkLabel(self.match_pane,
                     text=("⚠ Don't change Mod → Map Options between now and starting the campaign — "
                           "would change the world the seed produces."),
                     font=("Segoe UI", 11), text_color="#c89500", anchor="w"
                     ).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 2))
        # After a match BB is in a half-initialised state. Depending on BB
        # build / mods / RNG, it may pop a "critical exception" dialog OR
        # silently return to the main menu — neither outcome leaves a usable
        # world. User MUST restart BB regardless before the real campaign.
        ctk.CTkLabel(self.match_pane,
                     text=("ℹ After a match, BB may pop a \"critical exception\" dialog OR may just return to the main menu — both are expected. "
                           "BB's world state is half-initialised either way; do NOT try to continue from there. "
                           "Quit BB completely (Alt+F4 if needed), relaunch, and start a new campaign with the matched seed."),
                     font=("Segoe UI", 11), text_color="#e85a3c", anchor="w", justify="left",
                     wraplength=820,
                     ).grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))
        self.match_list = ctk.CTkScrollableFrame(self.match_pane, height=140, fg_color="transparent")
        self.match_list.grid(row=3, column=0, sticky="ew", padx=8, pady=(2, 8))
        self.match_pane.grid_remove()

        # Reusable notice banner — hidden until something needs attention
        # (version mismatch, brute-force finish, mod-not-loaded). One strip,
        # recolored per severity. See _show_notice / _clear_notice.
        self.notice_var = ctk.StringVar(value="")
        self.notice_banner = ctk.CTkLabel(self, textvariable=self.notice_var,
                                          font=("Segoe UI", 12, "bold"),
                                          anchor="w", justify="left", wraplength=900,
                                          fg_color="#3a2a00", text_color="#ffcf66",
                                          corner_radius=6)
        self.notice_banner.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 5))
        self.notice_banner.grid_remove()

        status = ctk.CTkFrame(self)
        status.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 10))
        status.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(status, textvariable=self.status_var, anchor="w").grid(row=0, column=0, sticky="ew", padx=10, pady=4)

        # Right side: colored LED + "Log watch: <text>"
        right = ctk.CTkFrame(status, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e", padx=10, pady=4)
        self.watch_dot = ctk.CTkLabel(right, text="●", font=("Segoe UI", 16, "bold"),
                                      text_color="#6a6e76", width=14)
        self.watch_dot.pack(side="left")
        ctk.CTkLabel(right, text=" Log watch: ").pack(side="left")
        ctk.CTkLabel(right, textvariable=self.watch_var).pack(side="left")

    def _build_trait_pane(self, parent, col, title, known_list, vars_dict, kind):
        pane = ctk.CTkFrame(parent)
        pane.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 5, 5 if col == 0 else 0))
        pane.grid_rowconfigure(2, weight=1)
        pane.grid_columnconfigure(0, weight=1)

        # Title row — title on left, mode selector on right for "required" pane
        title_row = ctk.CTkFrame(pane, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        title_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(title_row, text=title, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        if kind == "required":
            ctk.CTkLabel(title_row, text="match:", font=("Segoe UI", 11)).grid(row=0, column=1, padx=(8, 4))
            ctk.CTkOptionMenu(title_row, values=["any", "all"], width=80,
                              variable=self.required_mode_var).grid(row=0, column=2, sticky="e")

        # Header buttons: bulk check/uncheck
        hdr = ctk.CTkFrame(pane, fg_color="transparent")
        hdr.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
        ctk.CTkButton(hdr, text="✓ All",  width=70, height=26,
                      command=lambda k=kind: self._bulk_check(k, True)).pack(side="left", padx=(0, 4))
        ctk.CTkButton(hdr, text="☐ None", width=70, height=26,
                      command=lambda k=kind: self._bulk_check(k, False)).pack(side="left", padx=4)
        ctk.CTkButton(hdr, text="↺ Invert", width=70, height=26,
                      command=lambda k=kind: self._bulk_invert(k)).pack(side="left", padx=4)
        ctk.CTkLabel(hdr, text="(✏ rename · × remove)", text_color="#7a8290",
                     font=("Segoe UI", 10)).pack(side="right", padx=(4, 0))

        # Scrollable list
        sf = ctk.CTkScrollableFrame(pane, fg_color="transparent")
        sf.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)

        # Add-custom row at bottom
        add_row = ctk.CTkFrame(pane, fg_color="transparent")
        add_row.grid(row=3, column=0, sticky="ew", padx=8, pady=(2, 8))
        add_row.grid_columnconfigure(0, weight=1)
        entry = ctk.CTkEntry(add_row, placeholder_text=f"add custom {kind} trait…")
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(add_row, text="+", width=32,
                      command=lambda: self._add_custom_trait(kind, entry)).grid(row=0, column=1)
        entry.bind("<Return>", lambda _e: self._add_custom_trait(kind, entry))

        setattr(self, f"_{kind}_scroll", sf)
        self._populate_trait_pane(kind)

    def _display_for(self, trait_id: str) -> str:
        return self.trait_display.get(trait_id) or _id_to_display(trait_id)

    def _populate_trait_pane(self, kind):
        """Rebuild the rows for one trait pane. Preserves existing check states.
        Rows are labeled by display name (Lumbering, Iron Lungs) and sorted that way;
        the trait ID stays as the underlying dict key so the .nut still gets the
        correct snake_case identifier."""
        sf, known_list, vars_dict = self._pane_ctx(kind)
        existing_states = {t: v.get() for t, v in vars_dict.items()}
        for w in sf.winfo_children():
            w.destroy()
        vars_dict.clear()

        # Sort by display name (what the user reads) — falls back to the ID if no
        # mapping exists. Stable on the ID so duplicate display names don't shuffle.
        ordered = sorted(known_list, key=lambda t: (self._display_for(t).lower(), t))
        for trait in ordered:
            v = ctk.BooleanVar(value=existing_states.get(trait, True))
            vars_dict[trait] = v
            row = ctk.CTkFrame(sf, fg_color="transparent")
            row.pack(fill="x", padx=2, pady=0)
            row.grid_columnconfigure(0, weight=1)

            cb = ctk.CTkCheckBox(row, text=self._display_for(trait), variable=v)
            cb.grid(row=0, column=0, sticky="w", padx=(2, 4))
            ctk.CTkButton(row, text="✏", width=26, height=22,
                          fg_color="transparent", hover_color="#2b3441",
                          command=lambda t=trait, k=kind: self._edit_trait(k, t)
                          ).grid(row=0, column=1, padx=1)
            ctk.CTkButton(row, text="×", width=26, height=22,
                          fg_color="transparent", hover_color="#5a1f1f",
                          text_color="#d97676",
                          command=lambda t=trait, k=kind: self._remove_trait(k, t)
                          ).grid(row=0, column=2, padx=(1, 2))

    def _pane_ctx(self, kind):
        sf = getattr(self, f"_{kind}_scroll")
        known_list = self.banned_known if kind == "banned" else self.required_known
        vars_dict  = self.banned_vars  if kind == "banned" else self.required_vars
        return sf, known_list, vars_dict

    def _bulk_check(self, kind, state: bool):
        _, _, vars_dict = self._pane_ctx(kind)
        for v in vars_dict.values():
            v.set(state)

    def _bulk_invert(self, kind):
        _, _, vars_dict = self._pane_ctx(kind)
        for v in vars_dict.values():
            v.set(not v.get())

    def _remove_trait(self, kind, trait):
        _, known_list, vars_dict = self._pane_ctx(kind)
        if trait in known_list:
            known_list.remove(trait)
        if trait in vars_dict:
            del vars_dict[trait]
        self._populate_trait_pane(kind)
        self.status_var.set(f"Removed '{trait}' from {kind}.")

    def _edit_trait(self, kind, trait):
        """Two-field edit dialog: display name (what the user sees) + trait ID
        (what gets written to the .nut)."""
        _, known_list, vars_dict = self._pane_ctx(kind)
        current_display = self._display_for(trait)
        dlg = _TraitEditDialog(self, current_display=current_display, current_id=trait)
        if dlg.result is None:
            return
        new_display, new_id = dlg.result
        if not new_id:
            self.status_var.set("Trait ID can't be empty.")
            return
        if new_id != trait and new_id in known_list:
            self.status_var.set(f"'{new_id}' is already in the {kind} list.")
            return
        was_checked = vars_dict.get(trait, ctk.BooleanVar(value=True)).get()
        if new_id != trait:
            idx = known_list.index(trait)
            known_list[idx] = new_id
            if trait in vars_dict:
                del vars_dict[trait]
            # Migrate the display-name entry too.
            if trait in self.trait_display:
                del self.trait_display[trait]
            vars_dict[new_id] = ctk.BooleanVar(value=was_checked)
        # Always update the display name (it may have been edited even if ID wasn't).
        self.trait_display[new_id] = new_display or _id_to_display(new_id)
        self._populate_trait_pane(kind)
        if new_id != trait:
            self.status_var.set(f"Renamed '{trait}' → '{new_id}' ({new_display}).")
        else:
            self.status_var.set(f"Display name for '{trait}' set to '{new_display}'.")

    def _add_custom_trait(self, kind, entry: ctk.CTkEntry):
        raw  = entry.get()
        name = _sanitize_trait(raw)
        entry.delete(0, "end")
        if not name:
            if raw.strip():
                self.status_var.set(f"Trait '{raw}' has no valid characters (use letters, digits, _).")
            return
        _, known_list, vars_dict = self._pane_ctx(kind)
        if name in known_list:
            vars_dict[name].set(True)
            return
        known_list.append(name)
        self._populate_trait_pane(kind)
        if name in vars_dict:
            vars_dict[name].set(True)

    # ── stars grid (rebuilds when brother count changes) ──
    # Non-zero cells highlight the whole CTkOptionMenu box; zero cells use the
    # widget's CTk-theme defaults captured at construction time.
    _STAR_ACTIVE_FG   = "#ffc857"   # amber face
    _STAR_ACTIVE_BTN  = "#d4a64a"   # darker amber for the dropdown chevron
    _STAR_ACTIVE_TEXT = "#1a1a1a"   # near-black for contrast on amber

    def _on_star_changed(self, slot: str, stat: str, *_):
        widget = self.stars_widgets.get((slot, stat))
        if widget is None:
            return
        try:
            active = int(self.stars_vars[(slot, stat)].get() or "0") > 0
        except ValueError:
            active = False
        try:
            if active:
                widget.configure(
                    fg_color=self._STAR_ACTIVE_FG,
                    button_color=self._STAR_ACTIVE_BTN,
                    text_color=self._STAR_ACTIVE_TEXT,
                )
            else:
                d = self.stars_widget_defaults.get((slot, stat))
                if d:
                    widget.configure(**d)
        except Exception:
            pass

    def _rebuild_stars_grid(self):
        # preserve current values
        prior = {k: v.get() for k, v in self.stars_vars.items()}
        for w in self.stars_frame.winfo_children():
            w.destroy()
        self.stars_vars.clear()
        self.stars_widgets.clear()
        self.stars_widget_defaults.clear()

        try:
            n = max(1, min(20, int(self.bro_count_var.get() or "1")))
        except ValueError:
            n = 5

        # column headers
        ctk.CTkLabel(self.stars_frame, text="slot", width=50,
                     font=("Segoe UI", 11, "bold")).grid(row=0, column=0, padx=2, pady=2)
        for j, stat in enumerate(STATS):
            ctk.CTkLabel(self.stars_frame, text=stat.upper(), width=46,
                         font=("Segoe UI", 11, "bold")).grid(row=0, column=j + 1, padx=2, pady=2)

        rows = ["*"] + [str(i) for i in range(1, n + 1)]
        for ri, slot in enumerate(rows, start=1):
            ctk.CTkLabel(self.stars_frame, text=slot, width=50,
                         text_color="#aab2c0" if slot == "*" else None,
                         font=("Segoe UI", 11, "bold")).grid(row=ri, column=0, padx=2, pady=2)
            for j, stat in enumerate(STATS):
                v = ctk.StringVar(value=prior.get((slot, stat), "0"))
                self.stars_vars[(slot, stat)] = v
                w = ctk.CTkOptionMenu(self.stars_frame, values=["0", "1", "2", "3"],
                                      variable=v, width=50)
                w.grid(row=ri, column=j + 1, padx=2, pady=2)
                self.stars_widgets[(slot, stat)] = w
                self.stars_widget_defaults[(slot, stat)] = {
                    "fg_color":     w.cget("fg_color"),
                    "button_color": w.cget("button_color"),
                    "text_color":   w.cget("text_color"),
                }
                v.trace_add("write", lambda *_a, s=slot, t=stat: self._on_star_changed(s, t))
                self._on_star_changed(slot, stat)

    # ── origin dropdown ──
    def _on_origin_change(self, value: str):
        for name, count in ORIGINS:
            if name == value and count is not None:
                self.bro_count_var.set(str(count))
                break
        # Rebuild synchronously so we can pre-fill hardcoded stars right away.
        # The bro_count_var trace also schedules a debounced rebuild in 120ms,
        # but that one just preserves the values we set here — idempotent.
        self._rebuild_stars_grid()
        self._apply_hardcoded_stars(value)
        self._refresh_origin_info()

    def _apply_hardcoded_stars(self, origin: str):
        """Reset numeric slots, then pre-fill the origin's hardcoded stars."""
        slots = ORIGIN_HARDCODED_STARS.get(origin, [])
        # Wipe any leftover values on numeric slots; preserve the "*" row,
        # which is a user-defined universal default, not origin-specific.
        for (slot, stat), var in self.stars_vars.items():
            if slot != "*":
                var.set("0")
        for slot_idx, hardcoded in enumerate(slots, start=1):
            for stat, value in hardcoded.items():
                key = (str(slot_idx), stat)
                if key in self.stars_vars:
                    self.stars_vars[key].set(str(value))

    def _refresh_origin_info(self):
        try:
            self.origin_info_var.set(summarize_origin(self.origin_var.get()))
        except Exception:
            self.origin_info_var.set("")

    # ── browse ──
    def _browse_bb(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(title="Select Battle Brothers/data folder",
                                       initialdir=self.bb_path_var.get() or str(Path.home()))
        if path:
            self.bb_path_var.set(path)

    # ── nut I/O ──
    def _load_from_nut(self, load_stars: bool = True):
        try:
            if NUT_PATH.exists():
                cfg = parse_existing_config(NUT_PATH.read_text(encoding="utf-8"))
                self.status_var.set(f"Loaded settings from {NUT_PATH.name}.")
            elif NUT_TEMPLATE:
                cfg = parse_existing_config(NUT_TEMPLATE)
                self.status_var.set("No .nut on disk — defaults loaded from embedded template. Click Save & Deploy to create it.")
            else:
                cfg = parse_existing_config("")
                self.status_var.set("No .nut and no template — defaults loaded.")
        except Exception as e:
            self.status_var.set(f"Couldn't read .nut: {e}")
            return

        self.trigger_seed_var.set(cfg["trigger_seed"])
        self.max_iters_var.set(str(cfg["max_iters"]))
        self.log_every_var.set(str(cfg["log_every"]))
        self.required_mode_var.set(cfg.get("required_mode", "any"))

        # extend trait lists with whatever's already in the .nut
        for t in cfg["banned"]:
            if t not in self.banned_known: self.banned_known.append(t)
        for t in cfg["required"]:
            if t not in self.required_known: self.required_known.append(t)
        self._populate_trait_pane("banned")
        self._populate_trait_pane("required")
        for t in self.banned_known:
            self.banned_vars[t].set(t in cfg["banned"])
        for t in self.required_known:
            self.required_vars[t].set(t in cfg["required"])

        if load_stars:
            # set brother count from highest numeric slot key
            numeric_slots = [int(k) for k in cfg["stars_by_slot"] if k.isdigit()]
            if numeric_slots:
                self.bro_count_var.set(str(max(max(numeric_slots), 1)))
            elif not self.bro_count_var.get():
                self.bro_count_var.set("5")
            self._rebuild_stars_grid()
            for slot, stats in cfg["stars_by_slot"].items():
                for stat, n in stats.items():
                    if (slot, stat) in self.stars_vars:
                        self.stars_vars[(slot, stat)].set(str(n))

    def _gather_cfg(self) -> dict:
        try:
            n = max(1, min(20, int(self.bro_count_var.get())))
        except ValueError:
            n = 5
        stars_by_slot: dict[str, dict[str, int]] = {}
        for slot in ["*"] + [str(i) for i in range(1, n + 1)]:
            entry = {}
            for stat in STATS:
                try:
                    val = int(self.stars_vars.get((slot, stat), ctk.StringVar(value="0")).get())
                except ValueError:
                    val = 0
                if val > 0:
                    entry[stat] = val
            # "*" is always kept (even when empty — explicit "no global default").
            # Numeric slots are ONLY kept if they have any non-zero stat —
            # otherwise an all-zero row would override "*" with "no constraint",
            # which is almost never the user's intent. Empty numeric row = use
            # the "*" default for that slot.
            if slot == "*" or entry:
                stars_by_slot[slot] = entry
        return {
            "trigger_seed": self.trigger_seed_var.get().strip() or "REROLL",
            "max_iters":    int(self.max_iters_var.get() or "10000"),
            "log_every":    int(self.log_every_var.get() or "10"),
            "stars_by_slot": stars_by_slot,
            "banned":   [t for t, v in self.banned_vars.items()   if v.get()],
            "required": [t for t, v in self.required_vars.items() if v.get()],
            "required_mode": self.required_mode_var.get(),
        }

    def _on_save(self):
        try:
            cfg = self._gather_cfg()
            # Pre-flight: trivially-passing criteria match every seed immediately.
            if self._is_criteria_trivial(cfg):
                if not messagebox.askyesno(
                    "Trivial criteria",
                    "No star thresholds and no required traits are set.\n"
                    "Every random seed will match on iteration 0.\n\nDeploy anyway?",
                ):
                    self.status_var.set("Deploy cancelled.")
                    return
            rewrite_nut(cfg)
            rebuild_zip()
            bb = Path(self.bb_path_var.get())
            if not bb.exists():
                self.status_var.set(f"⚠ wrote .nut + .zip, but BB data folder not found: {bb}")
                return
            dest = copy_to_bb(bb)
            self._save_settings()             # persist BB path + window state
            self.status_var.set(f"✓ Deployed → {dest}")
        except Exception as e:
            self.status_var.set(f"✗ {e}")

    @staticmethod
    def _is_criteria_trivial(cfg) -> bool:
        any_star = any(any(v > 0 for v in s.values()) for s in cfg["stars_by_slot"].values())
        return not (any_star or cfg["required"] or cfg["banned"])

    def _on_scan_log(self):
        if not BB_LOG.exists():
            self.status_var.set(f"No log at {BB_LOG}")
            return
        try:
            text = BB_LOG.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            self.status_var.set(f"✗ read log: {e}")
            return
        text = _strip_html(text)
        found = set()
        for m in re.finditer(r'\[BBREROLL\] bro=\d+[^\n]*?traits=([^\s<]*)', text):
            for t in m.group(1).split(","):
                if t:
                    found.add(t)
        new = 0
        ignored = 0
        for t in sorted(found):
            if t in IGNORE_TRAITS or t.startswith(IGNORE_PREFIXES):
                ignored += 1
                continue
            if t not in self.banned_known and t not in self.required_known:
                # heuristic: if name looks bad-ish, drop in banned, else required
                bad_hints = ("fragile","craven","dumb","mad","weak","sick","fear","brute","clumsy","cocky")
                target = self.banned_known if any(h in t for h in bad_hints) else self.required_known
                target.append(t)
                new += 1
        self._populate_trait_pane("banned")
        self._populate_trait_pane("required")
        self.status_var.set(
            f"Scanned log: {len(found)} unique traits, {new} new added, "
            f"{ignored} ignored (origin/acquired)."
        )

    def _open_log(self):
        if BB_LOG.exists():
            os.startfile(str(BB_LOG))      # type: ignore[attr-defined]
        else:
            self.status_var.set(f"No log at {BB_LOG}")

    def _open_github(self):
        webbrowser.open("https://github.com/Trikpatknd/bb-reroll/releases")

    # ── log watching ──
    def _start_log_watcher(self):
        if not BB_LOG.exists():
            self._set_watch_state("waiting")
            self.watch_var.set("waiting for log file…")
            self.after(3000, self._start_log_watcher)   # poll until BB writes log.html
            return
        self.watcher = LogWatcher(BB_LOG, self._on_match, self._on_progress,
                                  self._on_brute_start, self._on_verify_start,
                                  on_mod_init=self._on_mod_init)
        self.watcher.start()
        self._set_watch_state("idle")
        self.watch_var.set("connected — waiting for brute force")
        self._tick_watch_state()

    def _on_verify_start(self, iter_num, seed):
        """Mod just entered slow-verify for a stars-pass candidate. Distinguish
        from the normal fast-pass progress with a different LED color and label."""
        self._last_activity_ts = time.time()
        self.after(0, lambda: (self._set_watch_state("verifying"),
                               self.watch_var.set(f"verifying seed {seed} (iter {iter_num})")))

    def _on_brute_start(self):
        """Watcher saw '[BBREROLL2] brute force start'."""
        self._last_activity_ts = time.time()
        self.after(0, lambda: (self._set_watch_state("running"),
                               self.status_var.set("Brute force started.")))

    def _on_mod_init(self, mod_version):
        """Watcher saw '[BBREROLL] mod queued (vX)'. Confirms the mod loaded and
        tells us its version; warn if it doesn't match this GUI."""
        self._mod_seen = True
        self.mod_version = mod_version
        self.after(0, lambda: self._apply_version_check(mod_version))

    def _apply_version_check(self, mod_version):
        if APP_VERSION != "unknown" and mod_version != APP_VERSION:
            self._show_notice(
                f"⚠ Version mismatch — this GUI is v{APP_VERSION} but the installed mod is v{mod_version}. "
                "Rebuild and redeploy (Save & Deploy, or run build_exe.bat) so they match.",
                kind="warn")
        elif self.notice_var.get().startswith("⚠ Version mismatch"):
            self._clear_notice()  # versions agree now — drop a stale mismatch notice

    # ── notice banner (version mismatch / finish / mod-not-loaded) ──
    _NOTICE_COLORS = {
        "warn":  ("#3a2a00", "#ffcf66"),   # amber
        "error": ("#3a1410", "#ff8a6e"),   # red
        "info":  ("#10263a", "#79b8e0"),   # blue
    }

    def _show_notice(self, text: str, kind: str = "warn"):
        fg, tc = self._NOTICE_COLORS.get(kind, self._NOTICE_COLORS["warn"])
        self.notice_var.set(text)
        try:
            self.notice_banner.configure(fg_color=fg, text_color=tc)
            self.notice_banner.grid()
        except Exception:
            pass

    def _clear_notice(self):
        self.notice_var.set("")
        try:
            self.notice_banner.grid_remove()
        except Exception:
            pass

    def _on_match(self, iter_num, seed):
        self._last_activity_ts = time.time()
        self.after(0, lambda: self._add_match(iter_num, seed))

    def _on_progress(self, cur, total):
        now = time.time()
        self._last_activity_ts = now
        self._progress_history.append((now, cur))
        if len(self._progress_history) > 20:
            self._progress_history.pop(0)
        eta = ""
        if len(self._progress_history) >= 2:
            t0, c0 = self._progress_history[0]
            t1, c1 = self._progress_history[-1]
            dt, dc = t1 - t0, c1 - c0
            if dt > 0 and dc > 0:
                rate = dc / dt
                remaining_s = max(0, (total - cur) / rate)
                eta = f" · ETA {self._fmt_duration(remaining_s)}"
        msg = f"scanning stars · iter {cur}/{total}{eta}"
        self.after(0, lambda: (self._set_watch_state("running"), self.watch_var.set(msg)))

    # ── LED state machine ──
    _DOT_COLORS = {
        "idle":      "#6a6e76",   # grey
        "waiting":   "#c89500",   # amber — log file not visible yet
        "running":   "#22b14c",   # green — fast pass (stars filter)
        "verifying": "#3aa0d9",   # blue  — slow verify (rebuilding world)
    }

    def _set_watch_state(self, state: str):
        self._watch_state = state
        try:
            self.watch_dot.configure(text_color=self._DOT_COLORS.get(state, "#6a6e76"))
        except Exception:
            pass

    def _idle_threshold(self) -> float:
        """Adaptive idle threshold — based on the longest gap between recent
        progress events, clamped to [20s, 120s]. With LogEvery=10 and ~2s/iter
        progress events come every ~20s, so a hardcoded 15s would falsely
        drop the LED to idle every cycle."""
        if len(self._progress_history) < 2:
            return 20.0
        h = self._progress_history
        intervals = [h[i+1][0] - h[i][0] for i in range(len(h) - 1)]
        if not intervals:
            return 20.0
        return max(20.0, min(120.0, max(intervals) * 1.5))

    def _tick_watch_state(self):
        """Every 2s, drop the dot to idle if no activity within the adaptive
        threshold. Re-armed on every event."""
        try:
            if self._watch_state in ("running", "verifying") and self._last_activity_ts:
                if time.time() - self._last_activity_ts > self._idle_threshold():
                    self._set_watch_state("idle")
                    self.watch_var.set("idle (no recent activity)")
        finally:
            self.after(2000, self._tick_watch_state)

    @staticmethod
    def _fmt_duration(secs: float) -> str:
        secs = int(secs)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h{m:02d}m"
        if m:
            return f"{m}m{s:02d}s"
        return f"{s}s"

    # ── matches ──
    def _add_match(self, iter_num: int, seed: str):
        if any(m["seed"] == seed for m in self._matches):
            return  # de-dupe re-reads of the same log line
        self._matches.insert(0, {"seed": seed, "iter": iter_num, "ts": time.time()})
        self._render_match_list()
        self.match_pane.grid()
        if notification:
            try:
                notification.notify(title="BB Reroll: MATCH — restart BB",
                                    message=(f"Seed {seed} at iter {iter_num}. "
                                             "BB may crash or return to menu — restart it either way, "
                                             "then enter the seed for a real campaign."),
                                    timeout=15)
            except Exception:
                pass

    def _render_match_list(self):
        for w in self.match_list.winfo_children():
            w.destroy()
        if not self._matches:
            self.match_pane.grid_remove()
            return
        for entry in self._matches:
            row = ctk.CTkFrame(self.match_list, fg_color="#1f6f3a", corner_radius=6)
            row.pack(fill="x", padx=2, pady=2)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row,
                         text=f"seed: {entry['seed']}    iter {entry['iter']}",
                         font=("Segoe UI", 13, "bold"),
                         text_color="white").grid(row=0, column=0, sticky="w", padx=10, pady=6)
            ctk.CTkButton(row, text="📋 Copy", width=90, height=28,
                          fg_color="#155028", hover_color="#0e3d1d",
                          command=lambda s=entry["seed"]: self._copy_to_clipboard(s)).grid(row=0, column=1, padx=4)
            ctk.CTkButton(row, text="×", width=32, height=28,
                          fg_color="transparent", hover_color="#5a1f1f",
                          command=lambda s=entry["seed"]: self._dismiss_match(s)).grid(row=0, column=2, padx=(0, 6))

    def _dismiss_match(self, seed: str):
        self._matches = [m for m in self._matches if m["seed"] != seed]
        self._render_match_list()

    def _clear_matches(self):
        self._matches.clear()
        self._render_match_list()

    def _copy_to_clipboard(self, text: str):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
            self.status_var.set(f"Copied: {text}")
        except Exception as e:
            self.status_var.set(f"clipboard error: {e}")

    # ── stale mod cleanup ──
    def _on_clean_stale(self):
        bb = Path(self.bb_path_var.get())
        if not bb.exists():
            self.status_var.set(f"BB data folder not found: {bb}")
            return
        active = ZIP_PATH.name  # don't offer to delete the currently-deployed zip
        candidates = []
        try:
            for p in bb.iterdir():
                if p.is_file() and p.suffix.lower() == ".zip" and "bb_reroll" in p.name.lower() and p.name != active:
                    candidates.append(p)
        except Exception as e:
            self.status_var.set(f"scan failed: {e}")
            return
        if not candidates:
            messagebox.showinfo("Clean stale mods",
                                f"No stale bb_reroll zips in:\n{bb}\n\n(Currently-deployed: {active})")
            self.status_var.set("No stale zips found.")
            return
        listing = "\n  ".join(p.name for p in candidates)
        if not messagebox.askyesno(
            "Clean stale mods",
            f"Found {len(candidates)} other bb_reroll zip(s) in:\n{bb}\n\n  {listing}\n\nDelete all of them?",
        ):
            return
        deleted = 0
        for p in candidates:
            try:
                p.unlink(); deleted += 1
            except Exception as e:
                self.status_var.set(f"delete failed for {p.name}: {e}")
        self.status_var.set(f"Deleted {deleted} stale zip(s).")

    # ── settings persistence ──
    def _load_settings(self):
        if not SETTINGS_PATH.exists():
            return
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        if data.get("bb_path"):
            self.bb_path_var.set(data["bb_path"])
        if data.get("geometry"):
            try:    self.geometry(data["geometry"])
            except Exception: pass
        if data.get("last_origin") and data["last_origin"] in {o[0] for o in ORIGINS}:
            self.origin_var.set(data["last_origin"])
        # Layered display-name overrides — only persist deltas from the builtin
        # map so a future TRAIT_NAMES update flows through automatically.
        overrides = data.get("display_overrides") or {}
        if isinstance(overrides, dict):
            for tid, name in overrides.items():
                if isinstance(tid, str) and isinstance(name, str):
                    self.trait_display[tid] = name

    def _save_settings(self):
        try:
            overrides = {
                tid: name for tid, name in self.trait_display.items()
                if TRAIT_NAMES.get(tid) != name
            }
            SETTINGS_PATH.write_text(json.dumps({
                "bb_path":           self.bb_path_var.get(),
                "geometry":          self.geometry(),
                "last_origin":       self.origin_var.get(),
                "display_overrides": overrides,
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _on_close(self):
        self._save_settings()
        self.destroy()


# ─────────────────────── entry ───────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()

"""
BB Reroll — find Battle Brothers campaign seeds whose starting brothers meet your
criteria, without running the game.

One window:
  • Game setup (Vanilla / Legends — read from the installed game) and Origin
  • Stars grid (rows = brother slots, cols = the 8 stat keys, 0-3 each)
  • Banned + Required trait checklists (with custom additions)
  • Search: the game's own campaign-start scripts are run for seed after seed in
    parallel worker processes (bbseed/), straight from the game's files
  • Results: every match with its full starting roster, copy buttons, and a
    ready-made Legends Discord seed post
  • Check a seed: shows the roster any seed gives

The seeds are ordinary campaign seeds: they work in any game with the same game
version, mods and recruit-related Mod Options — no mod of ours involved.

Runs as `python gui.py` for dev, or as a standalone `.exe` after PyInstaller.
"""

import json
import os
import queue
import sys
import threading
import time
import webbrowser
from pathlib import Path

# A windowed exe has no console: sys.stdout / sys.stderr are None, also in the search's
# worker processes (which start by running this file). Anything that prints would crash.
for _stream in ("stdout", "stderr"):
    if getattr(sys, _stream) is None:
        setattr(sys, _stream, open(os.devnull, "w"))

from tkinter import messagebox

import customtkinter as ctk

try:
    from plyer import notification
except Exception:
    notification = None

# Trait ID → display-name map (Lumbering / legend_heavy, etc.).
try:
    from bbreroll.trait_names import TRAIT_NAMES
except Exception:
    TRAIT_NAMES = {}

# Per-origin hardcoded talent stars (Legends) — drives the info label above the grid
# and the auto-fill of the stars grid when an origin is picked.
try:
    from bbreroll.origin_hardcoded_stars import (
        ORIGIN_HARDCODED_STARS,
        summarize as summarize_origin,
        conflicts as origin_conflicts,
    )
except Exception:
    ORIGIN_HARDCODED_STARS = {}
    def summarize_origin(_origin: str) -> str:
        return ""
    def origin_conflicts(_origin, _stars_by_slot):
        return []

from bbreroll import offline_origins as O
from bbreroll import star_limits
from bbreroll.criteria import (
    DEFAULT_BANNED, DEFAULT_REQUIRED, STATS, id_to_display, is_trivial, number_errors,
    roster_lines, sanitize_trait, to_int,
)
from bbreroll.seed_report import build_seed_report


# ─────────────────────── paths ───────────────────────

def _app_dir() -> Path:
    """Where the settings file lives — next to the script in dev, next to the .exe when frozen."""
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
SETTINGS_PATH = APP_DIR / "bb_reroll_gui.json"
SETTINGS_VERSION = 4      # settings written by 3.x (the in-game search) carry no version


def _read_app_version() -> str:
    """Version string from the repo-root VERSION file (the single source of
    truth). Bundled into the .exe via gui.spec."""
    for base in (BUNDLE_DIR, APP_DIR):
        try:
            p = base / "VERSION"
            if p.exists():
                return p.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return "unknown"


APP_VERSION = _read_app_version()


def default_workers() -> int:
    return max(1, min(8, (os.cpu_count() or 2) // 2))


def _attach_tooltip(widget, text):
    """Hover tooltip (CTk has none) that cannot get stuck: it goes away when the mouse
    leaves, on any click or loss of focus, when the widget is destroyed, and by itself
    after 6 s. `text` may be a function, asked each time the tooltip is shown; it may give
    a list of (line, colour or None, bold?) instead of one text, or nothing (no tooltip).
    Not for dropdowns: once their list opens the widget never hears the mouse leave."""
    state = {"win": None, "job": None}

    def hide(_event=None):
        if state["job"] is not None:
            try:
                widget.after_cancel(state["job"])
            except Exception:
                pass
            state["job"] = None
        if state["win"] is not None:
            try:
                state["win"].destroy()
            except Exception:
                pass
            state["win"] = None

    def show(_event=None):
        if state["win"] is not None:
            return
        try:
            content = text() if callable(text) else text
            if not content:
                return
            win = ctk.CTkToplevel(widget)
            win.overrideredirect(True)
            win.geometry(f"+{widget.winfo_rootx() + 20}+{widget.winfo_rooty() + widget.winfo_height() + 6}")
            win.attributes("-topmost", True)
            if isinstance(content, str):
                ctk.CTkLabel(win, text=content, font=("Segoe UI", 11),
                             fg_color="#222222", corner_radius=6, wraplength=420, justify="left").pack(padx=8, pady=4)
            else:
                box = ctk.CTkFrame(win, fg_color="#222222", corner_radius=6)
                box.pack(padx=0, pady=0)
                for line, colour, bold in content:
                    ctk.CTkLabel(box, text=line, font=("Segoe UI", 11, "bold" if bold else "normal"),
                                 text_color=colour, wraplength=420, justify="left", anchor="w",
                                 ).pack(fill="x", padx=10, pady=(4 if bold else 0, 0))
                ctk.CTkFrame(box, height=6, fg_color="transparent").pack()
            state["win"] = win
            state["job"] = widget.after(6000, hide)
        except Exception:
            state["win"] = None

    widget.bind("<Enter>", show, add="+")
    for sequence in ("<Leave>", "<ButtonPress>", "<FocusOut>", "<Destroy>"):
        widget.bind(sequence, hide, add="+")


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

        ctk.CTkLabel(self, text="Trait ID (the game's snake_case name, e.g. legend_heavy):",
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
        self.result = (self._display.get().strip(), sanitize_trait(self._tid.get()))
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(f"BB Reroll v{APP_VERSION} — offline seed search")
        self.geometry("980x940")
        self.minsize(900, 820)

        self._saved = self._read_settings()
        self._game_folder = None
        self._restore_game_folder()      # decides which game setups exist — before the UI lists them

        # Banner texts the user has ✕'d this session (sticky dismissal).
        self._dismissed_notices: set[str] = set()
        self._notice_action = None

        self.setup_var      = ctk.StringVar(value=O.DEFAULT_SETUP or "")
        self.origin_var     = ctk.StringVar(value="")
        self.bro_count_var  = ctk.StringVar(value="3")
        self.max_iters_var  = ctk.StringVar(value="100000")
        self.count_var      = ctk.StringVar(value="3")
        self.workers_var    = ctk.StringVar(value=str(default_workers()))
        self.sisters_var    = ctk.StringVar(value=O.BATTLE_SISTERS[1])
        self.check_seed_var = ctk.StringVar(value="")
        self.status_var     = ctk.StringVar(value="Ready.")
        self.watch_var      = ctk.StringVar(value="idle")
        self._watch_state   = "idle"

        self.stars_vars:             dict[tuple[str, str], ctk.StringVar] = {}
        self.stars_widgets:          dict[tuple[str, str], "ctk.CTkOptionMenu"] = {}
        # Default CTk colors captured at widget construction so we can restore
        # them when a cell's value returns to 0. Cells with value > 0 get the
        # active highlight palette applied to fg_color/button_color/text_color.
        self.stars_widget_defaults:  dict[tuple[str, str], dict] = {}
        # stat rolls: the least tier per stat ("any" / "mid" / "high"), same rows as the stars
        self.tiers_vars:             dict[tuple[str, str], ctk.StringVar] = {}
        self.tiers_widgets:          dict[tuple[str, str], "ctk.CTkOptionMenu"] = {}
        self.tiers_widget_defaults:  dict[tuple[str, str], dict] = {}
        self.banned_vars: dict[str, ctk.BooleanVar] = {}
        self.required_vars: dict[str, ctk.BooleanVar] = {}
        self.banned_known   = self._saved_list("known_banned", DEFAULT_BANNED)
        self.required_known = self._saved_list("known_required", DEFAULT_REQUIRED)
        self.required_mode_var = ctk.StringVar(value="any")
        # ID -> display name. Seeded from TRAIT_NAMES; user-overrides
        # come from bb_reroll_gui.json (loaded by _load_settings).
        self.trait_display: dict[str, str] = dict(TRAIT_NAMES)

        # The search runs in worker processes; a thread relays their events into this
        # queue and the Tk thread drains it — every handler below runs on the Tk thread.
        self._events = queue.Queue()
        self._stop = threading.Event()
        self._searching = False
        self._search_total = 0
        self._run = {}
        self._matches: list[dict] = []   # session-level list of results, newest first
        self._report_info: dict = {"version": None, "build_name": None,
                                   "battle_sisters": None, "origin": None,
                                   "map_options": {}}
        self._selftest = None
        # What each origin can roll, per game setup (profile -> catalog, None = could not be made).
        # Worked out from the game's scripts once per installed game, in the background.
        self._catalogs: dict = {}
        self._catalog_job = None          # profile being loaded / built
        self._catalog_progress = ""
        self._catalog_stop = threading.Event()

        self._grid_rebuild_id = None   # pending debounced stars-grid rebuild
        self._build_ui()
        self._load_settings()
        self._on_setup_change()        # origin list, brother count, stars grid for the saved setup/origin
        self._restore_criteria()
        self._ready_status()
        self._warn_old_mod()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # CustomTkinter 5.2.x on Windows can leave a backgrounded window blank/
        # transparent until it regains focus. Force a repaint when focus returns
        # so a match that arrived while another window was focused becomes visible.
        self.bind("<FocusIn>", lambda _e: self.after(10, self._force_repaint))
        # Proactive repaint loop — keeps the window painted while it's unfocused
        # (a search runs for a while) or parked on a different-DPI second monitor.
        self.after(1000, self._repaint_tick)
        self.after(100, self._drain_events)
        self.after(1500, self._ensure_catalog)     # after a self-test spec, if any, is known

    # ── UI build ──
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        # Only the traits row carries the vertical stretch; it must not collapse
        # when the result list grows.
        self.grid_rowconfigure(2, weight=1, minsize=190)

        # Top: what to search. Two independent rows (their columns need not line up).
        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        row_a = ctk.CTkFrame(top, fg_color="transparent")
        row_a.pack(fill="x", padx=4, pady=(8, 4))
        row_b = ctk.CTkFrame(top, fg_color="transparent")
        row_b.pack(fill="x", padx=4, pady=(0, 8))

        def label(parent, text, first=False):
            ctk.CTkLabel(parent, text=text).pack(side="left", padx=(4 if first else 16, 4))

        label(row_a, "Game setup:", first=True)
        self.setup_menu = ctk.CTkOptionMenu(row_a, values=list(O.SETUPS) or ["(game not found)"],
                                            variable=self.setup_var, width=160, command=self._on_setup_change)
        self.setup_menu.pack(side="left")
        label(row_a, "Origin:")
        self.origin_menu = ctk.CTkOptionMenu(row_a, values=O.names_for(self.setup_var.get()), width=230,
                                             variable=self.origin_var, command=self._on_origin_change)
        self.origin_menu.pack(side="left")
        label(row_a, "Brothers:")
        ctk.CTkEntry(row_a, textvariable=self.bro_count_var, width=50).pack(side="left")
        self.bro_count_var.trace_add("write", lambda *_: self._schedule_grid_rebuild())
        folder_btn = ctk.CTkButton(row_a, text="Game folder…", width=110, fg_color="#3a3f4a", hover_color="#4a505c",
                                   command=self._on_game_folder)
        folder_btn.pack(side="right", padx=(8, 4))
        _attach_tooltip(folder_btn, lambda: O.found_text(details=True) + "\n\nThe search reads the game's own files "
                        "and these mod zips where they are — nothing has to be extracted. Click to choose another install.")

        label(row_b, "Max seeds:", first=True)
        ctk.CTkEntry(row_b, textvariable=self.max_iters_var, width=100).pack(side="left")
        label(row_b, "Stop after matches:")
        ctk.CTkEntry(row_b, textvariable=self.count_var, width=60).pack(side="left")
        label(row_b, "Workers:")
        workers = ctk.CTkEntry(row_b, textvariable=self.workers_var, width=50)
        workers.pack(side="left")
        _attach_tooltip(workers, f"Parallel processes (this PC has {os.cpu_count() or 1} CPU threads). With Legends "
                                 "each one needs about 0.8 GB of memory and ~15 s to load.")
        label(row_b, "Battle sisters:")
        self.sisters_menu = ctk.CTkOptionMenu(row_b, values=list(O.BATTLE_SISTERS), variable=self.sisters_var, width=170)
        self.sisters_menu.pack(side="left")
        ctk.CTkLabel(row_b, text="(as in the game's Mod Options)",
                     font=("Segoe UI", 11), text_color="#9aa3b0").pack(side="left", padx=(8, 4))

        # Stars grid
        stars_outer = ctk.CTkFrame(self)
        stars_outer.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        stars_outer.grid_columnconfigure(0, weight=1)
        self.grid_title = ctk.CTkLabel(stars_outer, text=self._GRID_TITLES["Stars"], font=("Segoe UI", 13, "bold"))
        self.grid_title.grid(row=0, column=0, sticky="w", padx=10, pady=(6, 2))
        # Stars and stat rolls share the space: one grid at a time, both always count
        self.grid_mode_var = ctk.StringVar(value="Stars")
        ctk.CTkSegmentedButton(stars_outer, values=["Stars", "Stat rolls"], variable=self.grid_mode_var,
                               command=self._on_grid_mode).grid(row=0, column=1, sticky="e", padx=10, pady=(6, 2))
        self.origin_info_var = ctk.StringVar(value="")
        self.origin_info_label = ctk.CTkLabel(
            stars_outer,
            textvariable=self.origin_info_var,
            justify="left",
            anchor="w",
            font=("Consolas", 11),
            text_color="#9aa3b0",
        )
        self.origin_info_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 4))
        self.rolls_info_label = ctk.CTkLabel(
            stars_outer, justify="left", anchor="w", font=("Segoe UI", 11), text_color="#9aa3b0", wraplength=880,
            text=("Where a brother's base stat landed in what HIS background can roll — mid = middle third or "
                  "better, high = top third. The background sets most of a stat; the seed only moves it within "
                  "that range. Greyed: the seed cannot change that stat for that brother."))
        self.rolls_info_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 4))
        self.rolls_info_label.grid_remove()
        self.stars_frame = ctk.CTkFrame(stars_outer, fg_color="transparent")
        self.stars_frame.grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 8))
        self.tiers_frame = ctk.CTkFrame(stars_outer, fg_color="transparent")
        self.tiers_frame.grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 8))
        self.tiers_frame.grid_remove()

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
        self.search_btn = ctk.CTkButton(actions, text="▶ Search", height=36, command=self._on_search)
        self.search_btn.grid(row=0, column=0, padx=8, pady=8)
        self.stop_btn = ctk.CTkButton(actions, text="■ Stop", height=36, width=90, state="disabled",
                                      fg_color="#7a2a2a", hover_color="#5a1f1f", command=self._on_stop)
        self.stop_btn.grid(row=0, column=1, padx=8, pady=8)
        ctk.CTkLabel(actions, text="Check a seed:").grid(row=0, column=2, padx=(24, 4))
        entry = ctk.CTkEntry(actions, textvariable=self.check_seed_var, width=130)
        entry.grid(row=0, column=3, padx=4)
        entry.bind("<Return>", lambda _e: self._on_check_seed())
        self.check_btn = ctk.CTkButton(actions, text="Show its roster", height=36, command=self._on_check_seed)
        self.check_btn.grid(row=0, column=4, padx=8, pady=8)
        _attach_tooltip(self.check_btn, "Shows the starting roster this seed gives for the chosen game setup "
                                        "and origin — type it exactly as in the game (capitals matter).")
        ctk.CTkButton(actions, text="↗ Check for updates", height=36,
                      fg_color="transparent", border_width=1,
                      command=self._open_github).grid(row=0, column=99, padx=8, pady=8, sticky="e")

        # Results — scrollable list. Hidden until a result comes in.
        self.match_pane = ctk.CTkFrame(self)
        self.match_pane.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 5))
        self.match_pane.grid_columnconfigure(0, weight=1)
        match_head = ctk.CTkFrame(self.match_pane, fg_color="transparent")
        match_head.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        match_head.grid_columnconfigure(0, weight=1)
        self.match_title = ctk.CTkLabel(match_head, text="RESULTS (this session)",
                                        font=("Segoe UI", 12, "bold"))
        self.match_title.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(match_head, text="Clear", width=60, height=24,
                      command=self._clear_matches).grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(self.match_pane,
                     text=("These are ordinary campaign seeds: start a New Campaign with the same game version, "
                           "mods, origin and recruit-related Mod Options, and type the seed exactly as shown."),
                     font=("Segoe UI", 11), text_color="#79b8e0", anchor="w", justify="left", wraplength=880,
                     ).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))
        desc_frame = ctk.CTkFrame(self.match_pane, fg_color="transparent")
        desc_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 2))
        desc_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(desc_frame, text="Brief description (for the Legends Discord seed post):",
                     font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w")
        self.share_desc_var = ctk.StringVar(value="")
        ctk.CTkEntry(desc_frame, textvariable=self.share_desc_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))

        self.match_list = ctk.CTkScrollableFrame(self.match_pane, height=140, fg_color="transparent")
        self.match_list.grid(row=4, column=0, sticky="ew", padx=8, pady=(2, 8))
        self.match_pane.grid_remove()

        # Reusable notice banner — hidden until something needs attention (the old
        # in-game mod still installed, a search that could not run, no match found).
        # One strip, recolored per severity, with an optional action button and a ✕ to
        # dismiss. Dismissal is sticky per message text for this GUI session.
        self.notice_var = ctk.StringVar(value="")
        self.notice_banner = ctk.CTkFrame(self, fg_color="#3a2a00", corner_radius=6)
        self.notice_banner.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 5))
        self.notice_banner.grid_columnconfigure(0, weight=1)
        self.notice_label = ctk.CTkLabel(self.notice_banner, textvariable=self.notice_var,
                                         font=("Segoe UI", 12, "bold"),
                                         anchor="w", justify="left", wraplength=760,
                                         text_color="#ffcf66")
        self.notice_label.grid(row=0, column=0, sticky="ew", padx=(10, 4), pady=6)
        self.notice_action_btn = ctk.CTkButton(self.notice_banner, text="", width=90, height=24,
                                               command=self._on_notice_action)
        self.notice_action_btn.grid(row=0, column=1, sticky="ne", padx=(0, 6), pady=6)
        self.notice_action_btn.grid_remove()
        self.notice_close = ctk.CTkButton(self.notice_banner, text="✕", width=28, height=24,
                                          fg_color="transparent", border_width=1,
                                          command=self._dismiss_notice)
        self.notice_close.grid(row=0, column=2, sticky="ne", padx=(0, 8), pady=6)
        self.notice_banner.grid_remove()

        status = ctk.CTkFrame(self)
        status.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 10))
        status.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(status, textvariable=self.status_var, anchor="w").grid(row=0, column=0, sticky="ew", padx=10, pady=4)

        # Right side: colored LED + "Search: <text>"
        right = ctk.CTkFrame(status, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e", padx=10, pady=4)
        self.watch_dot = ctk.CTkLabel(right, text="●", font=("Segoe UI", 16, "bold"),
                                      text_color="#6a6e76", width=14)
        self.watch_dot.pack(side="left")
        ctk.CTkLabel(right, text=" Search: ").pack(side="left")
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
        ctk.CTkLabel(hdr, text="(hover: effects · ✏ rename · × remove)", text_color="#7a8290",
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
        return self.trait_display.get(trait_id) or id_to_display(trait_id)

    def _populate_trait_pane(self, kind):
        """Rebuild the rows for one trait pane. Preserves existing check states.
        Rows are labeled by display name (Lumbering, Iron Lungs) and sorted that way;
        the trait ID stays as the underlying dict key — it is what the search compares."""
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
            _attach_tooltip(cb, lambda t=trait: self._trait_tooltip(t))
            ctk.CTkButton(row, text="✏", width=26, height=22,
                          fg_color="transparent", hover_color="#2b3441",
                          command=lambda t=trait, k=kind: self._edit_trait(k, t)
                          ).grid(row=0, column=1, padx=1)
            ctk.CTkButton(row, text="×", width=26, height=22,
                          fg_color="transparent", hover_color="#5a1f1f",
                          text_color="#d97676",
                          command=lambda t=trait, k=kind: self._remove_trait(k, t)
                          ).grid(row=0, column=2, padx=(1, 2))

    _EFFECT_COLOURS = {"+": "#6fd38a", "-": "#ff8a7a", "": "#c9d1d9"}

    def _trait_tooltip(self, trait):
        """What a trait does, from the game's own tooltip: [(line, colour, bold)], or None when
        the game's facts are not known (yet) or the trait is not one of the game's."""
        found = (self._catalog() or {}).get("traits", {}).get(trait)
        if not found:
            return None
        lines = [(found["name"], "white", True)]
        for e in found["effects"]:
            mark = {"+": "▲ ", "-": "▼ "}.get(e["sign"], "• ")
            lines.append((mark + e["text"], self._EFFECT_COLOURS[e["sign"]], False))
        if not found["effects"]:
            lines.append((found["description"] or "No effects listed in the game's tooltip.", "#9aa3b0", False))
        return lines

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
        (what the search compares against a brother's traits)."""
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
        self.trait_display[new_id] = new_display or id_to_display(new_id)
        self._populate_trait_pane(kind)
        if new_id != trait:
            self.status_var.set(f"Renamed '{trait}' → '{new_id}' ({new_display}).")
        else:
            self.status_var.set(f"Display name for '{trait}' set to '{new_display}'.")

    def _add_custom_trait(self, kind, entry: ctk.CTkEntry):
        raw  = entry.get()
        name = sanitize_trait(raw)
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

    _GRID_TITLES = {
        "Stars": "STARS  (0 = don't care, 1-3 = minimum stars.  A numeric slot row with all zeros falls back to "
                 "the * default rule.)",
        "Stat rolls": "STAT ROLLS  (any / mid / high = the least a stat's roll may be.  A numeric row replaces *.)",
    }
    _TIER_ACTIVE_FG = "#4fb3a6"     # teal face for a stat-roll requirement
    _TIER_ACTIVE_BTN = "#3a8a80"

    def _on_grid_mode(self, mode=None):
        mode = self.grid_mode_var.get()
        self.grid_title.configure(text=self._GRID_TITLES.get(mode, ""))
        rolls = mode == "Stat rolls"
        for widget, show in ((self.stars_frame, not rolls), (self.origin_info_label, not rolls),
                             (self.tiers_frame, rolls), (self.rolls_info_label, rolls)):
            widget.grid() if show else widget.grid_remove()

    def _on_tier_changed(self, slot: str, stat: str, *_):
        widget = self.tiers_widgets.get((slot, stat))
        if widget is None:
            return
        try:
            if self.tiers_vars[(slot, stat)].get() in ("mid", "high"):
                widget.configure(fg_color=self._TIER_ACTIVE_FG, button_color=self._TIER_ACTIVE_BTN,
                                 text_color=self._STAR_ACTIVE_TEXT)
            else:
                d = self.tiers_widget_defaults.get((slot, stat))
                if d:
                    widget.configure(**d)
        except Exception:
            pass

    def _rebuild_tiers_grid(self, n, facts):
        """The stat-rolls grid: same rows as the stars grid; a cell offers only "any" where the seed
        cannot move that stat for that brother."""
        prior = {k: v.get() for k, v in self.tiers_vars.items()}
        for w in self.tiers_frame.winfo_children():
            w.destroy()
        self.tiers_vars.clear()
        self.tiers_widgets.clear()
        self.tiers_widget_defaults.clear()
        ctk.CTkLabel(self.tiers_frame, text="slot", width=50,
                     font=("Segoe UI", 11, "bold")).grid(row=0, column=0, padx=2, pady=2)
        for j, stat in enumerate(STATS):
            ctk.CTkLabel(self.tiers_frame, text=stat.upper(), width=46,
                         font=("Segoe UI", 11, "bold")).grid(row=0, column=j + 1, padx=2, pady=2)
        for ri, slot in enumerate(["*"] + [str(i) for i in range(1, n + 1)], start=1):
            ctk.CTkLabel(self.tiers_frame, text=slot, width=50, text_color="#aab2c0" if slot == "*" else None,
                         font=("Segoe UI", 11, "bold")).grid(row=ri, column=0, padx=2, pady=2)
            for j, stat in enumerate(STATS):
                options = star_limits.roll_options(facts, slot, stat)
                value = prior.get((slot, stat), "any")
                if value not in options:
                    value = "any"
                v = ctk.StringVar(value=value)
                self.tiers_vars[(slot, stat)] = v
                w = ctk.CTkOptionMenu(self.tiers_frame, values=options, variable=v, width=64,
                                      state="normal" if len(options) > 1 else "disabled")
                w.grid(row=ri, column=j + 1, padx=2, pady=2)
                self.tiers_widgets[(slot, stat)] = w
                self.tiers_widget_defaults[(slot, stat)] = {
                    "fg_color": w.cget("fg_color"), "button_color": w.cget("button_color"),
                    "text_color": w.cget("text_color")}
                v.trace_add("write", lambda *_a, s=slot, t=stat: self._on_tier_changed(s, t))
                self._on_tier_changed(slot, stat)

    def _schedule_grid_rebuild(self):
        """Debounce: typing a count or picking an origin writes bro_count_var
        once or more; rebuild the grid once, 120 ms after the last write."""
        if self._grid_rebuild_id is not None:
            self.after_cancel(self._grid_rebuild_id)
        self._grid_rebuild_id = self.after(120, self._rebuild_stars_grid)

    def _rebuild_stars_grid(self):
        # A synchronous rebuild supersedes any pending debounced one.
        if self._grid_rebuild_id is not None:
            self.after_cancel(self._grid_rebuild_id)
            self._grid_rebuild_id = None
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

        # a cell offers only what that brother can get at all (when the origin's facts are known)
        facts = self._slot_facts(self.origin_var.get())
        rows = ["*"] + [str(i) for i in range(1, n + 1)]
        for ri, slot in enumerate(rows, start=1):
            ctk.CTkLabel(self.stars_frame, text=slot, width=50,
                         text_color="#aab2c0" if slot == "*" else None,
                         font=("Segoe UI", 11, "bold")).grid(row=ri, column=0, padx=2, pady=2)
            for j, stat in enumerate(STATS):
                top = star_limits.cell_max(facts, slot, stat)
                value = prior.get((slot, stat), "0")
                if to_int(value) is not None and to_int(value) > top:
                    value = str(top)
                v = ctk.StringVar(value=value)
                self.stars_vars[(slot, stat)] = v
                w = ctk.CTkOptionMenu(self.stars_frame, values=[str(i) for i in range(top + 1)],
                                      variable=v, width=50, state="normal" if top > 0 else "disabled")
                w.grid(row=ri, column=j + 1, padx=2, pady=2)
                self.stars_widgets[(slot, stat)] = w
                self.stars_widget_defaults[(slot, stat)] = {
                    "fg_color":     w.cget("fg_color"),
                    "button_color": w.cget("button_color"),
                    "text_color":   w.cget("text_color"),
                }
                v.trace_add("write", lambda *_a, s=slot, t=stat: self._on_star_changed(s, t))
                self._on_star_changed(slot, stat)
        self._rebuild_tiers_grid(n, facts)

    # ── game setup / origin ──
    def _legends(self) -> bool:
        return O.SETUPS.get(self.setup_var.get(), (None, False))[1]

    def _on_setup_change(self, _value=None):
        names = O.names_for(self.setup_var.get())
        self.origin_menu.configure(values=names)
        if self.origin_var.get() not in names:
            self.origin_var.set(names[0])
        self.sisters_menu.configure(state="normal" if self._legends() else "disabled")
        self._on_origin_change(self.origin_var.get())
        if hasattr(self, "_catalog_stop"):     # also called while the window is being built
            self.after(10, self._ensure_catalog)

    def _on_origin_change(self, value: str):
        if value not in O.SCENARIO or value in O.NOT_SEARCHABLE:
            value = O.names_for(self.setup_var.get())[0]
            self.origin_var.set(value)
        count = O.COUNTS.get(value)
        if not self._legends():
            count = O.VANILLA_COUNTS.get(value) or count
        sizes = star_limits.sizes_for(self._catalog(), O.SCENARIO.get(value))
        if len(sizes) == 1:
            count = sizes[0]            # what the game's scripts actually give
        if count is not None:
            self.bro_count_var.set(str(count))
        # Rebuild synchronously so hardcoded stars can be pre-filled right away;
        # this also cancels the debounced rebuild the bro_count_var write just
        # scheduled.
        self._rebuild_stars_grid()
        facts = self._slot_facts(value)
        if facts is not None:
            for (slot, _stat), var in self.stars_vars.items():
                if slot != "*":
                    var.set("0")
            for slot, fixed in star_limits.prefill(facts).items():
                for stat, n in fixed.items():
                    if (slot, stat) in self.stars_vars:
                        self.stars_vars[(slot, stat)].set(str(n))
            self.origin_info_var.set(star_limits.describe(facts, sizes))
        elif self._legends():
            self._apply_hardcoded_stars(value)
            self._refresh_origin_info()
        else:
            # The table of origin-fixed stars describes Legends: nothing is pre-filled.
            for (slot, _stat), var in self.stars_vars.items():
                if slot != "*":
                    var.set("0")
            self.origin_info_var.set(f"{self.setup_var.get()}: stars an origin fixes are not pre-filled here.")
        if facts is None and self._catalog_progress:
            self.origin_info_var.set((self.origin_info_var.get() + "\n" + self._catalog_progress).strip())

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

    # ── what each origin can roll (bbseed/catalog.py) ──
    def _profile(self):
        return O.SETUPS.get(self.setup_var.get(), (None, False))[0]

    def _catalog(self):
        return self._catalogs.get(self._profile())

    def _slot_facts(self, origin):
        """Per brother slot: the stars the origin can give at all (None until known)."""
        return star_limits.slots_for(self._catalog(), O.SCENARIO.get(origin))

    def _ensure_catalog(self):
        """Load the current setup's catalog, or work it out (once per installed game, ~1-2
        minutes in worker processes) when there is none yet."""
        profile = self._profile()
        if profile is None or profile in self._catalogs or self._catalog_job is not None:
            return
        self._catalog_job = profile
        may_build = not self._selftest or bool(self._selftest.get("catalog"))
        workers = to_int(self.workers_var.get()) or default_workers()
        workers = max(1, min(workers, os.cpu_count() or 1))
        put = self._events.put
        stop = self._catalog_stop

        def run():
            from bbseed import catalog
            found = None
            try:
                found = catalog.load(profile)
                if found is None and may_build:
                    put(("catalog_progress", "Working out what each origin can roll (first time only)…"))
                    found = catalog.build(profile, workers=workers, should_stop=stop.is_set,
                                          on_event=lambda kind, payload: put(("catalog_event", (kind, payload))))
            except Exception as e:      # the search works without it: only the extra checks are missing
                put(("catalog_progress", f"Could not work out what the origins can roll: {type(e).__name__}: {e}"))
            put(("catalog_done", (profile, found)))

        threading.Thread(target=run, daemon=True).start()

    def _ev_catalog_progress(self, text):
        self._catalog_progress = text
        if self._slot_facts(self.origin_var.get()) is None:
            base = self.origin_info_var.get().split("\n")
            kept = [line for line in base if not line.startswith(("Working out", "Could not work out"))]
            self.origin_info_var.set("\n".join(kept + [text]).strip())

    def _ev_catalog_event(self, payload):
        kind, data = payload
        if kind == "preparing":
            name, done, total = data
            self._ev_catalog_progress(f"Working out what each origin can roll: reading the game's scripts "
                                      f"(first time only) · {done:,} of {total:,}")
        elif kind == "ready":
            self._ev_catalog_progress(f"Working out what each origin can roll (first time only): "
                                      f"loading · {data[0]} of {data[1]} workers ready")
        elif kind == "origin":
            self._ev_catalog_progress(f"Working out what each origin can roll (first time only): "
                                      f"{data[0]} of {data[1]} origins")
        elif kind == "fatal":
            self._ev_catalog_progress(f"Could not work out what the origins can roll: {str(data)[:200]}")

    def _ev_catalog_done(self, payload):
        profile, found = payload
        self._catalogs[profile] = found
        self._catalog_job = None
        if found is not None:
            self._catalog_progress = ""
            extras = O.add_extras(profile, found)
            if extras and profile == self._profile():      # origins other mods add
                self.origin_menu.configure(values=O.names_for(self.setup_var.get()))
                if self._saved.get("last_origin") in extras and not self._searching:
                    self.origin_var.set(self._saved["last_origin"])     # the last session ended on one of them
                    self._on_origin_change(self._saved["last_origin"])
        if profile == self._profile() and found is not None:
            self._apply_catalog()
        self._ensure_catalog()          # the setup may have changed meanwhile

    def _apply_catalog(self):
        """The facts arrived: limit the grid cells and show them, without touching the player's
        criteria (only empty cells get an origin's fixed stars)."""
        origin = self.origin_var.get()
        facts = self._slot_facts(origin)
        if facts is None:
            return
        sizes = star_limits.sizes_for(self._catalog(), O.SCENARIO.get(origin))
        if len(sizes) == 1 and self.bro_count_var.get() != str(sizes[0]):
            self.bro_count_var.set(str(sizes[0]))
        self._rebuild_stars_grid()
        for slot, fixed in star_limits.prefill(facts).items():
            for stat, n in fixed.items():
                var = self.stars_vars.get((slot, stat))
                if var is not None and to_int(var.get()) == 0:
                    var.set(str(n))
        self.origin_info_var.set(star_limits.describe(facts, sizes))

    def _refresh_origin_info(self):
        try:
            self.origin_info_var.set(summarize_origin(self.origin_var.get()))
        except Exception:
            self.origin_info_var.set("")

    def _ready_status(self):
        if O.FOUND is None:
            self.status_var.set(O.found_text())
        else:
            self.status_var.set(f"{O.found_text()}. Pick an origin and criteria, then Search.")

    # ── the game's folder ──
    def _restore_game_folder(self):
        """A folder the player pointed at earlier wins over auto-detection; the data folder a
        3.x settings file remembers is tried when the game is not found by itself."""
        if os.environ.get("BBSEED_GAME_DATA"):
            return
        chosen = self._saved.get("game_folder")
        if chosen and Path(chosen).is_dir():
            self._game_folder = chosen
        elif O.FOUND is None and self._saved.get("bb_path") and Path(self._saved["bb_path"]).is_dir():
            chosen = self._saved["bb_path"]
        else:
            return
        os.environ["BBSEED_GAME_DATA"] = chosen     # inherited by the search's worker processes
        O.refresh()

    def _on_game_folder(self):
        """Let the player point at the game (its folder or the data folder inside it)."""
        if self._searching:
            return
        from tkinter import filedialog
        from bbseed import gamedata
        start = str(O.FOUND["data"].parent) if O.FOUND else None
        chosen = filedialog.askdirectory(parent=self, initialdir=start, mustexist=True,
                                         title="Select the Battle Brothers folder (the one that contains \"data\")")
        if not chosen:
            return
        if gamedata.as_data_dir(chosen) is None:
            messagebox.showerror("Game folder", f"No game files (data\\data_001.dat) in\n{chosen}")
            return
        self._game_folder = chosen
        os.environ["BBSEED_GAME_DATA"] = chosen
        O.refresh()
        self.setup_menu.configure(values=list(O.SETUPS))
        if self.setup_var.get() not in O.SETUPS:
            self.setup_var.set(O.DEFAULT_SETUP)
        self._on_setup_change()
        self._ready_status()
        self._warn_old_mod()
        self._save_settings()

    def _have_game(self) -> bool:
        if self.setup_var.get() in O.SETUPS:
            return True
        messagebox.showerror("Game not found", "Battle Brothers was not found on this PC.\n\n"
                             "Click \"Game folder…\" and select the folder the game is installed in.")
        return False

    # ── the old in-game mod (BB Reroll 3.x) ──
    def _warn_old_mod(self):
        text = O.reroll_mod_warning()
        if text:
            self._show_notice("⚠ " + text, kind="warn", action=("Remove it", self._on_remove_old_mod))

    def _on_remove_old_mod(self):
        names = list((O.FOUND or {}).get("reroll_mod") or [])
        if not names:
            return
        data = O.FOUND["data"]
        listing = "\n  ".join(names)
        if not messagebox.askyesno("Remove the old in-game mod",
                                   f"Delete from\n{data}\n\n  {listing}\n\n"
                                   "(BB Reroll 3.x's in-game search mod. Restart Battle Brothers afterwards.)"):
            return
        failed = []
        for name in names:
            try:
                (data / name).unlink()
            except Exception as e:
                failed.append(f"{name}: {e}")
        O.refresh()
        self._clear_notice()
        if failed:
            self._show_notice("Could not delete (is Battle Brothers running?): " + "; ".join(failed), kind="error")
        else:
            self.status_var.set("Removed the old in-game mod. Restart Battle Brothers if it is running.")

    # ── criteria ──
    def _gather_criteria(self) -> dict:
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
        # stat rolls: the same rule — "*" always, a numeric row only when it asks for something
        tiers_by_slot: dict[str, dict[str, str]] = {}
        for slot in ["*"] + [str(i) for i in range(1, n + 1)]:
            entry = {stat: var.get() for (s, stat), var in self.tiers_vars.items()
                     if s == slot and var.get() in ("mid", "high")}
            if slot == "*" or entry:
                tiers_by_slot[slot] = entry
        return {
            "stars_by_slot": stars_by_slot,
            "tiers_by_slot": tiers_by_slot,
            "banned":   [t for t, v in self.banned_vars.items()   if v.get()],
            "required": [t for t, v in self.required_vars.items() if v.get()],
            "required_mode": self.required_mode_var.get(),
        }

    def _restore_criteria(self):
        """Tick the traits and set the stars the last session ended with."""
        saved = self._saved.get("criteria")
        if not isinstance(saved, dict):
            return
        self.required_mode_var.set(saved.get("required_mode", "any"))
        banned, required = saved.get("banned") or [], saved.get("required") or []
        for t in banned:
            if t not in self.banned_known:
                self.banned_known.append(t)
        for t in required:
            if t not in self.required_known:
                self.required_known.append(t)
        self._populate_trait_pane("banned")
        self._populate_trait_pane("required")
        for t in self.banned_known:
            self.banned_vars[t].set(t in banned)
        for t in self.required_known:
            self.required_vars[t].set(t in required)
        stars = saved.get("stars_by_slot")
        if isinstance(stars, dict) and self._saved.get("last_origin") == self.origin_var.get():
            for slot, stats in stars.items():
                for stat, n in (stats or {}).items():
                    if (slot, stat) in self.stars_vars:
                        self.stars_vars[(slot, stat)].set(str(n))
        tiers = saved.get("tiers_by_slot")
        if isinstance(tiers, dict) and self._saved.get("last_origin") == self.origin_var.get():
            for slot, stats in tiers.items():
                for stat, level in (stats or {}).items():
                    if (slot, stat) in self.tiers_vars and level in ("mid", "high"):
                        self.tiers_vars[(slot, stat)].set(level)

    def _numbers(self):
        values = {"Max seeds": to_int(self.max_iters_var.get()),
                  "Stop after matches": to_int(self.count_var.get()),
                  "Workers": to_int(self.workers_var.get())}
        return values, number_errors(values, os.cpu_count() or 1)

    # ── starting / stopping a search ──
    def _on_search(self):
        if self._searching or not self._have_game():
            return
        criteria = self._gather_criteria()
        numbers, errors = self._numbers()
        if errors:
            messagebox.showerror("Can't search", "\n".join(errors))
            return
        # Pre-flight: trivially-passing criteria match every seed immediately.
        if is_trivial(criteria):
            if not messagebox.askyesno("Trivial criteria", "No star thresholds and no traits are set.\n"
                                       "Every seed will match.\n\nSearch anyway?"):
                return
        # Pre-flight: criteria no seed can meet — stars an origin fixes lower, stats a brother never
        # gets stars in, more starred stats than he can have (the game's own facts, when known).
        facts = self._slot_facts(self.origin_var.get())
        if facts is not None:
            found = (star_limits.problems(facts, criteria["stars_by_slot"])
                     + star_limits.roll_problems(facts, criteria["tiers_by_slot"]))
            if found and not messagebox.askyesno(
                    "Impossible criteria",
                    f"No seed can ever match these criteria for \"{self.origin_var.get()}\":\n\n"
                    + "\n".join(f"  • {p}" for p in found) + "\n\nSearch anyway?"):
                return
        # Without them: hardcoded-stars unsatisfiability from the built-in table (the Gladiators-bear case).
        elif self._legends():
            conflicts = origin_conflicts(self.origin_var.get(), criteria["stars_by_slot"])
            if conflicts:
                lines = "\n".join(
                    f"  • Slot {slot}: needs {stat.upper()} ≥ {need}, but the origin fixes it at {have}"
                    for slot, stat, need, have in conflicts
                )
                if not messagebox.askyesno(
                    "Unsatisfiable criteria",
                    f"\"{self.origin_var.get()}\" fixes some starting stars below what you ask for:\n\n"
                    f"{lines}\n\nNo seed will ever match. Search anyway?",
                ):
                    return
        self._launch(criteria, numbers, seeds=None)

    def _on_check_seed(self):
        if self._searching or not self._have_game():
            return
        seed = self.check_seed_var.get().strip()
        if not 1 <= len(seed) <= 10:
            messagebox.showerror("Check a seed", "Type the seed as in the game: 1 to 10 characters.")
            return
        numbers, _errors = self._numbers()
        self._launch(self._gather_criteria(), numbers, seeds=[seed])

    def _launch(self, criteria, numbers, seeds):
        from bbseed.search import search
        setup, origin = self.setup_var.get(), self.origin_var.get()
        profile = O.SETUPS[setup][0]
        scenario = O.SCENARIO[origin]
        workers = 1 if seeds else numbers["Workers"] or default_workers()
        mod_settings = {"mod_legends:GenderEquality": self.sisters_var.get()} if self._legends() else None
        self._run = {"setup": setup, "origin": origin, "checking": bool(seeds)}
        self._search_total = len(seeds) if seeds else numbers["Max seeds"]
        self._stop.clear()
        self._searching = True
        self._save_settings()
        if not self.notice_var.get().startswith("⚠ BB Reroll's in-game mod"):
            self._clear_notice()
        self.search_btn.configure(state="disabled")
        self.check_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_watch_state("waiting")
        self.watch_var.set(f"loading the game scripts in {workers} worker{'' if workers == 1 else 's'}…")
        self.status_var.set(f"Checking seed {seeds[0]}" if seeds else
                            f"Searching {origin} — {setup}, up to {self._search_total:,} seeds.")
        put = self._events.put

        def run():
            try:
                search(profile, scenario, criteria, workers=workers, count=numbers["Stop after matches"] or 1,
                       max_seeds=None if seeds else numbers["Max seeds"], seeds=seeds,
                       mod_settings=mod_settings,
                       on_event=lambda kind, payload: put((kind, payload)), should_stop=self._stop.is_set)
            except Exception as e:      # report instead of dying silently in the thread
                put(("fatal", f"{type(e).__name__}: {e}"))
                put(("finished", (0, 0.0, 0, True)))

        threading.Thread(target=run, daemon=True).start()

    def _on_stop(self):
        self._stop.set()
        self.status_var.set("Stopping…")

    # ── events from the search ──
    def _drain_events(self):
        try:
            while True:
                kind, payload = self._events.get_nowait()
                handler = getattr(self, "_ev_" + kind, None)
                if handler:
                    handler(payload)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._drain_events)

    def _ev_preparing(self, payload):
        name, done, total = payload
        self.watch_var.set(f"reading the game's scripts (first time only) · {name} · {done:,} of {total:,}")

    def _ev_ready(self, payload):
        ready, total, info = payload
        self.watch_var.set(f"loading the game scripts · {ready} of {total} workers ready")
        legends = info.get("legends_version")
        self._report_info = {
            "version": legends or f"Vanilla {info.get('game_version')}",
            "build_name": info.get("legends_build") if legends else None,
            "battle_sisters": info.get("battle_sisters") if legends else "n/a (no Legends)",
            "origin": self._run["origin"],
            "map_options": {},
            "game_version": info.get("game_version"),
            "mods": info.get("mods") or [],
        }

    def _ev_progress(self, payload):
        tested, secs, _found = payload[:3]
        odds = payload[3] if len(payload) > 3 else {}
        self._set_watch_state("running")
        rate = tested / secs if secs > 0 else 0.0
        eta = ""
        if rate > 0 and self._search_total > tested and not self._run["checking"]:
            eta = f" · up to {self._fmt_duration((self._search_total - tested) / rate)} left"
        self.watch_var.set(f"searching · {tested:,} of {self._search_total:,} seeds · {rate:.0f}/s{eta}")
        if self._run["checking"]:
            return
        hint = self._odds_text(odds, rate)
        if hint:
            self.status_var.set(hint)
            self._run["odds_text"] = hint
        never = odds.get("never") or []
        self._run["never"] = never
        if never and odds.get("tested", 0) >= 300 and not self._run.get("warned_never"):
            self._run["warned_never"] = True
            who = ", ".join(str(n) for n in never)
            self._show_notice(f"Brother {who} has not met the criteria once in {odds['tested']:,} seeds — "
                              f"this may never match. Loosen what you ask of {'him' if len(never) == 1 else 'them'}.",
                              kind="info")

    def _odds_text(self, odds, rate):
        """'About 1 in 3,400 seeds matches — one every ~1m15s at this speed.' (or nothing yet)"""
        chance, tested = odds.get("chance"), odds.get("tested", 0)
        if not chance or tested < 100:
            return ""
        one_in = 1 / chance
        text = f"About 1 in {one_in:,.0f} seeds matches (estimated from {tested:,} seeds)"
        if rate > 0:
            text += f" — one every ~{self._fmt_duration(one_in / rate)} at this speed"
        return text + "."

    def _ev_match(self, payload):
        # the same seed found or checked again replaces its earlier entry
        self._matches = [m for m in self._matches if not (
            m["seed"] == payload["seed"] and m["origin"] == self._run["origin"] and m["setup"] == self._run["setup"])]
        entry = dict(payload, ts=time.time(), origin=self._run["origin"], setup=self._run["setup"],
                     checked=self._run["checking"], info=dict(self._report_info))
        self._matches.insert(0, entry)
        self._render_match_list()
        self.match_pane.grid()
        if not entry["checked"]:
            self._surface_window()   # pull the window to front so the match is seen
            if notification:
                try:
                    notification.notify(title="BB Reroll: match",
                                        message=f"Seed {entry['seed']} for {entry['origin']}.", timeout=10)
                except Exception:
                    pass

    def _ev_error(self, payload):
        self._run["errors"] = self._run.get("errors", 0) + 1
        if self._run["errors"] == 1:        # show the first one; a count follows when the run ends
            self._show_notice(f"A seed could not be evaluated: {payload[:300]}", kind="warn")

    def _ev_fatal(self, payload):
        self._show_notice(f"The search could not run: {payload[:400]}", kind="error")

    def _ev_finished(self, payload):
        tested, secs, found, stopped = payload
        self._searching = False
        self.search_btn.configure(state="normal")
        self.check_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._set_watch_state("idle")
        self.watch_var.set("idle")
        if self._run["checking"]:
            self.status_var.set("Seed checked — see the result list.")
        else:
            errors = self._run.get("errors", 0)
            self.status_var.set(
                f"{'Stopped' if stopped else 'Search finished'}: {tested:,} seed{'' if tested == 1 else 's'} tested "
                f"in {self._fmt_duration(secs)}, {found} match{'' if found == 1 else 'es'}"
                f"{f', {errors} could not be evaluated' if errors else ''}."
                + (f" {self._run['odds_text']}" if not found and self._run.get("odds_text") else ""))
            if not found and not stopped and tested:
                never = self._run.get("never") or []
                if never:
                    who = ", ".join(str(n) for n in never)
                    self._show_notice(f"No seed matched in {tested:,} seeds: brother {who} never met the criteria. "
                                      f"Loosen what you ask of {'him' if len(never) == 1 else 'them'}.", kind="info")
                else:
                    self._show_notice(f"No seed matched in {tested:,} seeds. Loosen the criteria or raise Max seeds.",
                                      kind="info")
        if self._selftest:
            self._selftest_done(payload)

    # ── notice banner ──
    _NOTICE_COLORS = {
        "warn":  ("#3a2a00", "#ffcf66"),   # amber
        "error": ("#3a1410", "#ff8a6e"),   # red
        "info":  ("#10263a", "#79b8e0"),   # blue
    }

    def _show_notice(self, text: str, kind: str = "warn", action=None):
        """action: (button label, function) shown next to the text, or None."""
        if text in self._dismissed_notices:
            return   # user already ✕'d this exact message this session
        fg, tc = self._NOTICE_COLORS.get(kind, self._NOTICE_COLORS["warn"])
        self.notice_var.set(text)
        self._notice_action = action[1] if action else None
        try:
            self.notice_banner.configure(fg_color=fg)
            self.notice_label.configure(text_color=tc)
            if action:
                self.notice_action_btn.configure(text=action[0])
                self.notice_action_btn.grid()
            else:
                self.notice_action_btn.grid_remove()
            self.notice_banner.grid()
        except Exception:
            pass

    def _on_notice_action(self):
        if self._notice_action:
            self._notice_action()

    def _dismiss_notice(self):
        """✕ on the banner (also wired to the result pane's Clear). Sticky: the
        same text won't re-show this session."""
        txt = self.notice_var.get()
        if txt:
            self._dismissed_notices.add(txt)
        self._clear_notice()

    def _clear_notice(self):
        self.notice_var.set("")
        self._notice_action = None
        try:
            self.notice_banner.grid_remove()
        except Exception:
            pass

    # ── LED ──
    _DOT_COLORS = {
        "idle":    "#6a6e76",   # grey
        "waiting": "#c89500",   # amber — the workers are loading the game's scripts
        "running": "#22b14c",   # green — testing seeds
    }

    def _set_watch_state(self, state: str):
        self._watch_state = state
        try:
            self.watch_dot.configure(text_color=self._DOT_COLORS.get(state, "#6a6e76"))
        except Exception:
            pass

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

    # ── window surfacing / repaint (CTk 5.2.x Windows blank-on-unfocus bug) ──
    def _force_repaint(self):
        try:
            self.update_idletasks()
        except Exception:
            pass

    def _repaint_tick(self):
        """CTk 5.2.x can skip redraws while the window is unfocused or parked on a
        different-DPI monitor, leaving it blank/transparent. Force a repaint on a
        steady cadence so live status stays visible without clicking back into
        the window."""
        try:
            self.update_idletasks()
        except Exception:
            pass
        finally:
            self.after(1000, self._repaint_tick)

    def _surface_window(self):
        """Bring the window to the foreground and force a repaint. A search runs
        for a while, so the GUI is usually backgrounded and (CTk bug) may be
        blank — a match would otherwise be invisible. Lift + brief topmost +
        repaint makes sure the user actually sees it."""
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(1500, lambda: self.attributes("-topmost", False))
            try: self.bell()
            except Exception: pass
            self.update_idletasks()
        except Exception:
            pass

    # ── results ──
    def _render_match_list(self):
        from bbseed.lab import perk_text, roll_text
        for w in self.match_list.winfo_children():
            w.destroy()
        if not self._matches:
            self.match_pane.grid_remove()
            return
        # as tall as its content needs, up to a limit (it scrolls beyond that)
        wanted = sum(54 + 15 * len(m["roster"]) * (6 if m.get("show_perks") else 1) for m in self._matches)
        self.match_list.configure(height=max(80, min(300, wanted)))
        for entry in self._matches:
            ok = entry.get("failure") is None
            row = ctk.CTkFrame(self.match_list, fg_color="#1f6f3a" if ok else "#3a3f4a", corner_radius=6)
            row.pack(fill="x", padx=2, pady=2)
            row.grid_columnconfigure(0, weight=1)
            head = f"seed: {entry['seed']}    {entry['origin']}  ({entry['setup']})"
            if entry.get("checked"):
                head += "    (checked — %s)" % ("meets your criteria" if ok else "fails: " + entry["failure"])
            if not entry.get("stable", True):
                head += "    ⚠ NOT reproducible — do not rely on it"
            ctk.CTkLabel(row, text=head, font=("Segoe UI", 13, "bold"), text_color="white").grid(
                row=0, column=0, sticky="w", padx=10, pady=(6, 0))
            ctk.CTkButton(row, text="📋 Copy", width=70, height=28, fg_color="#155028", hover_color="#0e3d1d",
                          command=lambda s=entry["seed"]: self._copy_to_clipboard(s)).grid(row=0, column=1, padx=3, pady=(6, 0))
            ctk.CTkButton(row, text="📋 Roster", width=80, height=28, fg_color="#155028", hover_color="#0e3d1d",
                          command=lambda e=entry: self._copy_roster(e)).grid(row=0, column=2, padx=3, pady=(6, 0))
            share_btn = ctk.CTkButton(row, text="📋 Seed share", width=100, height=28, fg_color="#155028",
                                      hover_color="#0e3d1d", command=lambda e=entry: self._copy_seed_share(e))
            share_btn.grid(row=0, column=3, padx=3, pady=(6, 0))
            _attach_tooltip(share_btn,
                            "Copies a ready-to-paste Legends Discord seed-sharing post to the clipboard")
            ctk.CTkButton(row, text="×", width=32, height=28, fg_color="transparent", hover_color="#5a1f1f",
                          command=lambda e=entry: self._dismiss_match(e)).grid(row=0, column=5, padx=(0, 6), pady=(6, 0))
            has_perks = any(b.get("perk_groups") or b.get("rolls") for b in entry["roster"])
            if has_perks:
                perks_btn = ctk.CTkButton(row, text="▾ Details" if entry.get("show_perks") else "▸ Details",
                                          width=86, height=28, fg_color="#155028", hover_color="#0e3d1d",
                                          command=lambda e=entry: self._toggle_perks(e))
                perks_btn.grid(row=0, column=4, padx=3, pady=(6, 0))
                _attach_tooltip(perks_btn, "Each brother's stat rolls (where they landed in what his background "
                                           "can roll) and, with Legends, his perk trees")
            ctk.CTkLabel(row, text="\n".join(roster_lines(entry["roster"])), font=("Consolas", 11), justify="left",
                         anchor="w", text_color="#e6efe8").grid(row=1, column=0, columnspan=6, sticky="w",
                                                                padx=12, pady=(2, 8))
            if has_perks and entry.get("show_perks"):
                lines = []
                for i, b in enumerate(entry["roster"], 1):
                    lines.append(f"{i:2d}. {b['name']} — rolls: {roll_text(b) or 'unknown'}")
                    if perk_text(b):
                        lines.append(f"      perk trees: {perk_text(b)}")
                text = "\n".join(lines)
                ctk.CTkLabel(row, text=text, font=("Segoe UI", 11), justify="left", anchor="w", wraplength=860,
                             text_color="#cfe3d4").grid(row=2, column=0, columnspan=6, sticky="w", padx=12, pady=(0, 8))

    def _toggle_perks(self, entry: dict):
        entry["show_perks"] = not entry.get("show_perks")
        self._render_match_list()

    def _dismiss_match(self, entry: dict):
        self._matches = [m for m in self._matches if m is not entry]
        self._render_match_list()

    def _clear_matches(self):
        self._matches.clear()
        self._render_match_list()
        self._dismiss_notice()   # users reach for Clear to dismiss banners too

    def _copy_to_clipboard(self, text: str, label: str | None = None):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
            self.status_var.set(label or f"Copied: {text}")
        except Exception as e:
            self.status_var.set(f"clipboard error: {e}")

    def _copy_roster(self, entry: dict):
        from bbseed.lab import describe
        text = f"Seed {entry['seed']} — {entry['origin']} — {entry['setup']}\n"
        text += "\n".join(f"{i}. {describe(b)}" for i, b in enumerate(entry["roster"], 1))
        self._copy_to_clipboard(text, label=f"Copied the roster of seed {entry['seed']}")

    def _share_report(self, entry: dict) -> str:
        return build_seed_report(
            origin=entry["origin"],
            description=self.share_desc_var.get().strip(),
            seed=entry["seed"],
            report_info=entry.get("info") or self._report_info,
            tool_version=APP_VERSION,
            roster=entry.get("roster"),
        )

    def _copy_seed_share(self, entry: dict):
        self._copy_to_clipboard(self._share_report(entry), label=f"Copied Discord seed share for {entry['seed']}")

    def _open_github(self):
        webbrowser.open("https://github.com/Trikpatknd/bb-reroll/releases")

    # ── settings persistence ──
    @staticmethod
    def _read_settings() -> dict:
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _saved_list(self, key, default) -> list:
        """A trait list as the player left it (additions, removals), else the defaults."""
        saved = self._saved.get(key)
        if isinstance(saved, list) and all(isinstance(t, str) for t in saved):
            return list(saved)
        return list(default)

    def _load_settings(self):
        data = self._saved
        # A window size saved by 3.x was made for another layout: only the new one is restored.
        if data.get("v") == SETTINGS_VERSION and data.get("geometry"):
            try:    self.geometry(data["geometry"])
            except Exception: pass
        if data.get("setup") in O.SETUPS:
            self.setup_var.set(data["setup"])
        if data.get("last_origin") in O.names_for(self.setup_var.get()):
            self.origin_var.set(data["last_origin"])
        for key, var in (("workers", self.workers_var), ("count", self.count_var), ("max_seeds", self.max_iters_var)):
            if isinstance(data.get(key), int) and data[key] >= 1:
                var.set(str(data[key]))
        if data.get("battle_sisters") in O.BATTLE_SISTERS:
            self.sisters_var.set(data["battle_sisters"])
        # Layered display-name overrides — only persist deltas from the builtin
        # map so a future TRAIT_NAMES update flows through automatically.
        overrides = data.get("display_overrides") or {}
        if isinstance(overrides, dict):
            for tid, name in overrides.items():
                if isinstance(tid, str) and isinstance(name, str):
                    self.trait_display[tid] = name
        if overrides:
            self._populate_trait_pane("banned")
            self._populate_trait_pane("required")

    def _save_settings(self):
        try:
            overrides = {
                tid: name for tid, name in self.trait_display.items()
                if TRAIT_NAMES.get(tid) != name
            }
            SETTINGS_PATH.write_text(json.dumps({
                "v":                 SETTINGS_VERSION,
                "geometry":          self.geometry(),
                "setup":             self.setup_var.get(),
                "game_folder":       self._game_folder,
                "last_origin":       self.origin_var.get(),
                "workers":           to_int(self.workers_var.get()),
                "count":             to_int(self.count_var.get()),
                "max_seeds":         to_int(self.max_iters_var.get()),
                "battle_sisters":    self.sisters_var.get(),
                "display_overrides": overrides,
                "known_banned":      list(self.banned_known),
                "known_required":    list(self.required_known),
                "criteria":          self._gather_criteria(),
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _on_close(self):
        self._stop.set()
        self._catalog_stop.set()
        self._save_settings()
        self.destroy()

    # ── unattended self-test (BB_REROLL_SELFTEST=<spec.json>) ──
    def run_selftest(self, spec: dict):
        """Drive one search without a human: set the fields from `spec`, press Search,
        write what happened to spec["out"], optionally close. For automated checks of the
        GUI and of the built .exe; nothing in normal use reaches this."""
        self._selftest = spec
        self._save_settings = lambda: None      # a self-test must not overwrite the player's settings

        def go():
            self.setup_var.set(spec.get("setup", O.DEFAULT_SETUP))
            self._on_setup_change()
            # "catalog": true — load (or build) what the origins can roll first, and wait for it
            if spec.get("catalog") and self._profile() not in self._catalogs:
                self._ensure_catalog()
                self.after(500, go)
                return
            self.origin_var.set(spec["origin"])
            self._on_origin_change(spec["origin"])
            for var in self.banned_vars.values():
                var.set(False)
            for var in self.required_vars.values():
                var.set(False)
            for t in spec.get("banned", []):
                if t in self.banned_vars:
                    self.banned_vars[t].set(True)
            for t in spec.get("required", []):
                if t in self.required_vars:
                    self.required_vars[t].set(True)
            for (slot, stat), var in self.stars_vars.items():
                var.set(str(spec.get("stars", {}).get(slot, {}).get(stat, 0)))
            for (slot, stat), var in self.tiers_vars.items():
                var.set(spec.get("tiers", {}).get(slot, {}).get(stat, "any"))
            if spec.get("grid"):
                self.grid_mode_var.set(spec["grid"])
                self._on_grid_mode()
            self.max_iters_var.set(str(spec.get("max_seeds", 2000)))
            self.sisters_var.set(spec.get("battle_sisters", O.BATTLE_SISTERS[1]))
            self.count_var.set(str(spec.get("count", 2)))
            self.workers_var.set(str(spec.get("workers", 4)))
            self.share_desc_var.set(spec.get("description", ""))
            if spec.get("check"):
                self.check_seed_var.set(spec["check"])
                self._on_check_seed()
            else:
                self._launch(self._gather_criteria(), self._numbers()[0], seeds=None)
            if spec.get("stop_after"):
                self.after(int(spec["stop_after"] * 1000), self._on_stop)
        self.after(800, go)

    def _selftest_done(self, payload):
        spec = self._selftest
        if spec.get("show_perks"):          # open every result's perk trees before the screenshot
            for m in self._matches:
                m["show_perks"] = True
            self._render_match_list()
        Path(spec["out"]).write_text(json.dumps({
            "finished": list(payload), "status": self.status_var.get(), "notice": self.notice_var.get(),
            "title": self.title(), "setups": list(O.SETUPS),
            "catalog": self._catalog() is not None, "origin_info": self.origin_info_var.get(),
            "tooltips": {t: self._trait_tooltip(t) for t in spec.get("tooltips", [])},
            "stars": {f"{slot}:{stat}": v.get() for (slot, stat), v in self.stars_vars.items() if v.get() != "0"},
            "cells": {f"{slot}:{stat}": len(w.cget("values")) - 1 for (slot, stat), w in self.stars_widgets.items()},
            "matches": [{"seed": m["seed"], "origin": m["origin"], "stable": m["stable"], "failure": m["failure"],
                         "checked": m["checked"], "lines": roster_lines(m["roster"])} for m in self._matches],
            "share": None if not self._matches else self._share_report(self._matches[0]),
        }, indent=2), encoding="utf-8")
        if spec.get("screenshot"):          # a picture of the window, to check the layout unattended
            try:
                from PIL import ImageGrab
                self.update()
                x, y = self.winfo_rootx(), self.winfo_rooty()
                box = (x, y, x + self.winfo_width(), y + self.winfo_height())
                try:        # this process is not DPI aware (see main): Tk's pixels are scaled screen pixels
                    import ctypes
                    scale = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
                except Exception:
                    scale = 1.0
                ImageGrab.grab(bbox=tuple(int(v * scale) for v in box)).save(spec["screenshot"])
            except Exception:
                pass
        if spec.get("close_after") is not None:
            self.after(int(spec["close_after"] * 1000), self.destroy)


# ─────────────────────── entry ───────────────────────

def main():
    # Mixed-DPI monitors blank/transparent the CTk canvas when the window crosses
    # between them — CTk's per-monitor auto-rescale is the trigger. Going DPI-unaware
    # lets Windows bitmap-scale instead (slightly softer on a high-DPI monitor, but
    # never blank). Must run before the first window (App) is created.
    ctk.deactivate_automatic_dpi_awareness()
    app = App()
    spec = os.environ.get("BB_REROLL_SELFTEST")
    if spec:
        app.run_selftest(json.loads(Path(spec).read_text(encoding="utf-8")))
    app.mainloop()


if __name__ == "__main__":
    # The search's worker processes are this same program started again (in the .exe:
    # the .exe itself). freeze_support() turns such a start into a worker and never returns.
    import multiprocessing
    multiprocessing.freeze_support()
    main()

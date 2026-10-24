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
from bbreroll import backgrounds as background_limits
from bbreroll import map_conditions
from bbreroll import map_view
from bbreroll.criteria import (
    DEFAULT_BANNED, DEFAULT_REQUIRED, STATS, id_to_display, is_trivial, number_errors,
    explain_failure, roster_lines, sanitize_trait, to_int,
)
from bbreroll.seed_report import build_seed_report
from bbseed import mapdraw
from bbseed import msu_settings


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


# The numeric search settings: their names in the window and the keys of App._numbers() — one
# constant each, so renaming a label cannot break the search start again.
SEEDS_TO_TEST = "Seeds to test"
MATCHES_TO_FIND = "Matches to find"
WORKERS = "Workers"


# ─────────────────────── look ───────────────────────
# One calm dark palette and one font. Colour marks meaning only: blue = the main action,
# amber = a star requirement, teal = a stat-roll requirement, green / red = good / bad.
FONT = "Segoe UI"
PALETTE = {
    "bg": "#1d1e21", "panel": "#26282c", "panel_border": "#35383d",
    "field": "#1b1c1f", "field_border": "#41454b",
    "control": "#32353a", "control_btn": "#3b3f45", "control_hover": "#464a51",
    "text": "#e4e6e9", "muted": "#9aa1ab", "faint": "#636973",
    "accent": "#2f6fde", "accent_hover": "#2559b8",
    "danger": "#c45454", "danger_hover": "#3a2426",
    "star": "#e0aa45", "star_btn": "#c79430", "on_colour": "#17181a",
    # closed grid cells, one look per reason
    "never": "#202225", "never_text": "#4c5158",          # the brother never gets this
    "fixed": "#3a3121", "fixed_text": "#d8b062",          # the origin sets this star
    "full": "#29303d", "full_text": "#73839c",            # all his random stars are in use
    "roll": "#3aa596", "roll_btn": "#2f897c",
    "card": "#202a24", "card_border": "#2f7a4b", "card_other": "#25272b", "card_other_border": "#4a4e55",
    "tooltip": "#26282c", "tooltip_border": "#4a4e55",
    "good": "#6fd38a", "bad": "#ff8a7a",
}
STAT_NAMES = {"hp": "Hitpoints", "fat": "Fatigue", "res": "Resolve", "init": "Initiative",
              "msk": "Melee skill", "rsk": "Ranged skill", "mdf": "Melee defense", "rdf": "Ranged defense"}


def _panel(parent, **grid):
    frame = ctk.CTkFrame(parent, fg_color=PALETTE["panel"], border_width=1, border_color=PALETTE["panel_border"],
                         corner_radius=8)
    if grid:
        frame.grid(**grid)
    return frame


def _title(parent, text, **kw):
    return ctk.CTkLabel(parent, text=text, font=(FONT, 12, "bold"), text_color=PALETTE["text"], **kw)


def _hint(parent, text="", wrap=880, **kw):
    return ctk.CTkLabel(parent, text=text, font=(FONT, 11), text_color=PALETTE["muted"], justify="left",
                        anchor="w", wraplength=wrap, **kw)


def _button(parent, text, command, kind="secondary", **kw):
    """kind: "primary" (the main action), "secondary", "ghost" (outline, quiet) or "danger"."""
    style = {
        "primary": dict(fg_color=PALETTE["accent"], hover_color=PALETTE["accent_hover"], text_color="white"),
        "secondary": dict(fg_color=PALETTE["control"], hover_color=PALETTE["control_hover"],
                          text_color=PALETTE["text"]),
        "ghost": dict(fg_color="transparent", hover_color=PALETTE["control"], text_color=PALETTE["muted"],
                      border_width=1, border_color=PALETTE["panel_border"]),
        "danger": dict(fg_color="transparent", hover_color=PALETTE["danger_hover"], text_color=PALETTE["danger"],
                       border_width=1, border_color=PALETTE["danger"]),
    }[kind]
    style.update(kw)
    style.setdefault("height", 30)
    style.setdefault("font", (FONT, 12))
    return ctk.CTkButton(parent, text=text, command=command, text_color_disabled=PALETTE["faint"], **style)


def _menu(parent, values, variable, width, command=None, **kw):
    return ctk.CTkOptionMenu(parent, values=values, variable=variable, width=width, command=command, height=28,
                             font=(FONT, 12), dropdown_font=(FONT, 12),
                             fg_color=PALETTE["control"], button_color=PALETTE["control_btn"],
                             button_hover_color=PALETTE["control_hover"], text_color=PALETTE["text"],
                             text_color_disabled=PALETTE["faint"], dropdown_fg_color=PALETTE["panel"],
                             dropdown_hover_color=PALETTE["control_hover"], dropdown_text_color=PALETTE["text"],
                             **kw)


def _entry(parent, variable, width, placeholder=None):
    return ctk.CTkEntry(parent, textvariable=variable, width=width, height=28, font=(FONT, 12),
                        placeholder_text=placeholder, fg_color=PALETTE["field"], border_color=PALETTE["field_border"],
                        border_width=1, text_color=PALETTE["text"], placeholder_text_color=PALETTE["faint"])


def _field(parent, label, widget_factory, tooltip=None):
    """A label above its control, packed from the left."""
    box = ctk.CTkFrame(parent, fg_color="transparent")
    box.pack(side="left", padx=(0, 18))
    lab = ctk.CTkLabel(box, text=label, font=(FONT, 11), text_color=PALETTE["muted"], anchor="w")
    lab.pack(anchor="w")
    widget = widget_factory(box)
    widget.pack(anchor="w")
    if tooltip:
        _attach_tooltip(lab, tooltip)
    return widget


def _attach_tooltip(widget, text):
    """Hover tooltip (CTk has none) that cannot get stuck. It is a plain Tk window (a
    CTkToplevel does delayed focus and lift work of its own), it goes away when the mouse
    leaves, on any click, when the widget is destroyed and after 8 s, and while it is open it
    checks every 150 ms that the pointer is still on the widget — a CTk widget is made of
    several inner widgets, so its enter / leave events can come in the wrong order.
    `text` may be a function, asked each time the tooltip is shown; it may give a list of
    (line, colour or None, bold?) instead of one text, or nothing (no tooltip).
    Not for dropdowns: once their list opens the widget never hears the mouse leave."""
    import tkinter as tk
    state = {"win": None, "jobs": []}

    def cancel_jobs():
        for job in state["jobs"]:
            try:
                widget.after_cancel(job)
            except Exception:
                pass
        state["jobs"] = []

    def hide(_event=None):
        cancel_jobs()
        if state["win"] is not None:
            try:
                state["win"].destroy()
            except Exception:
                pass
            state["win"] = None

    def pointer_inside():
        try:
            x, y = widget.winfo_pointerxy()
            left, top = widget.winfo_rootx(), widget.winfo_rooty()
            return (widget.winfo_viewable() and left <= x < left + widget.winfo_width()
                    and top <= y < top + widget.winfo_height())
        except Exception:
            return False

    def watch():
        if state["win"] is None:
            return
        if not pointer_inside():
            hide()
            return
        state["jobs"].append(widget.after(150, watch))

    def show(_event=None):
        if state["win"] is not None:
            return
        try:
            content = text() if callable(text) else text
            if not content:
                return
            win = tk.Toplevel(widget)
            win.withdraw()
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg=PALETTE["tooltip_border"])
            box = ctk.CTkFrame(win, fg_color=PALETTE["tooltip"], corner_radius=0)
            box.pack(padx=1, pady=1)
            lines = [(content, PALETTE["text"], False)] if isinstance(content, str) else content
            for i, (line, colour, bold) in enumerate(lines):
                ctk.CTkLabel(box, text=line, font=(FONT, 11, "bold" if bold else "normal"),
                             text_color=colour or PALETTE["text"], wraplength=420, justify="left", anchor="w",
                             ).pack(fill="x", padx=10, pady=(6 if i == 0 else 0, 6 if i == len(lines) - 1 else 0))
            win.geometry(f"+{widget.winfo_rootx() + 12}+{widget.winfo_rooty() + widget.winfo_height() + 6}")
            win.deiconify()
            state["win"] = win
            state["jobs"] = [widget.after(8000, hide), widget.after(150, watch)]
        except Exception:
            hide()

    widget.bind("<Enter>", show, add="+")
    for sequence in ("<Leave>", "<ButtonPress>", "<Destroy>"):
        widget.bind(sequence, hide, add="+")


class _TraitEditDialog(ctk.CTkToplevel):
    """Modal dialog with two text inputs: display name + trait ID.

    Result is set to (display_name, sanitized_id) on OK, None on Cancel.
    Call .wait_window() (done in __init__) and then read .result on the parent."""

    def __init__(self, parent, current_display: str, current_id: str):
        super().__init__(parent)
        self.title("Change trait")
        self.geometry("440x210")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        ctk.CTkLabel(self, text="Name in the list:",
                     anchor="w").pack(fill="x", padx=14, pady=(14, 2))
        self._display = ctk.CTkEntry(self, width=400)
        self._display.pack(fill="x", padx=14)
        self._display.insert(0, current_display)

        ctk.CTkLabel(self, text="Trait ID in the game (for example legend_heavy):",
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


class _MapWindow(ctk.CTkToplevel):
    """The map of one result on a canvas: one rectangle per tile, a circle per town, a ring round each port and
    the north band's line, north at the top. The geometry and the colours are the ones of bbseed/mapdraw.svg().
    It is not modal and lives until it is closed; App._map_windows keeps it by (setup, origin, seed)."""

    def __init__(self, app, key, entry, screen_height=None):
        import tkinter as tk
        super().__init__(app)
        self._app, self._key = app, key
        summary, band = entry["map"], entry.get("north_band")
        self.summary, self.band = summary, band     # what the picture shows (App._show_map compares them)
        self.title(f"Map of seed {entry['seed']} - {entry['origin']}")
        self.configure(fg_color=PALETTE["bg"])
        self.resizable(False, False)
        self.scale = map_view.canvas_scale(summary, screen_height or self.winfo_screenheight())
        width, height = mapdraw.picture_size(summary, self.scale)
        self.info_var = ctk.StringVar()
        self._line = map_conditions.map_line(summary, band or map_view.DEFAULT_NORTH_BAND)
        self.info_var.set(self._line)
        ctk.CTkLabel(self, textvariable=self.info_var, font=(FONT, 12), text_color=PALETTE["text"], anchor="w").pack(
            fill="x", padx=12, pady=(8, 4))
        self.canvas = tk.Canvas(self, width=round(width), height=round(height), bg=PALETTE["field"],
                                highlightthickness=0)
        self.canvas.pack(padx=12)
        self._draw(summary, band, round(width))
        self._legend(band)
        self.bind("<Destroy>", self._forget, add="+")
        # beside the main window, and not lower than the screen allows
        self.update_idletasks()
        top = max(0, min(app.winfo_rooty() + 20, (screen_height or self.winfo_screenheight()) - self.winfo_reqheight() - 60))
        self.geometry(f"+{max(0, app.winfo_rootx() + 40)}+{top}")
        # CTkToplevel hides and shows itself again in its first 200 ms (title bar colour, icon) and gives the focus
        # back to the main window, which then covers the map: bring it forward after that.
        self.after(250, self.bring_forward)

    def bring_forward(self):
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _forget(self, event):
        if event.widget is self and self._app._map_windows.get(self._key) is self:
            del self._app._map_windows[self._key]

    def _draw(self, summary, band, width):
        canvas, scale = self.canvas, self.scale
        # Every edge is rounded once from the unscaled cell, so two tiles that touch share their edge: no gaps and
        # no overlap at any scale.
        for x0, y0, x1, y1, colour in mapdraw.cells(summary, 1):
            canvas.create_rectangle(round(x0 * scale), round(y0 * scale), round(x1 * scale), round(y1 * scale),
                                    fill=colour, outline="")
        if band is not None:
            y = mapdraw.band_y(summary, band, scale)
            canvas.create_line(0, y, width, y, fill=mapdraw.BAND_COLOUR, width=max(1, round(1.5 * scale)),
                               dash=(max(2, round(8 * scale)), max(2, round(5 * scale))))
        for cx, cy, r, fill, port, label in mapdraw.town_marks(summary, scale):
            items = [canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline="#111111",
                                        width=max(1, round(scale)))]
            if port:
                ring = r + 2.5 * scale
                items.append(canvas.create_oval(cx - ring, cy - ring, cx + ring, cy + ring, outline=mapdraw.PORT_RING,
                                                width=max(1, round(1.5 * scale))))
            for item in items:
                canvas.tag_bind(item, "<Enter>", lambda _e, text=label: self.info_var.set(text))
                canvas.tag_bind(item, "<Leave>", lambda _e: self.info_var.set(self._line))
        # north is at the top: an arrow on a dark plate in the corner (it must show on snow and on sea)
        canvas.create_polygon(4, 4, 32, 4, 32, 44, 4, 44, fill="#111111", outline="#ffffff")
        canvas.create_polygon(18, 8, 26, 24, 18, 20, 10, 24, fill="#ffffff", outline="#ffffff")
        canvas.create_text(18, 35, text="N", fill="#ffffff", font=(FONT, 11, "bold"))

    def _legend(self, band):
        """One line under the map: what the circles, the ring and the dashed line mean."""
        import tkinter as tk
        legend = ctk.CTkFrame(self, fg_color="transparent")
        legend.pack(fill="x", padx=12, pady=(4, 8))

        def chip(draw, bg=PALETTE["bg"]):
            c = tk.Canvas(legend, width=18, height=16, bg=bg, highlightthickness=0)
            draw(c)
            c.pack(side="left")

        def text(label):
            ctk.CTkLabel(legend, text=label, font=(FONT, 11), text_color=PALETTE["muted"]).pack(side="left", padx=(2, 12))

        for kind, label in mapdraw.KIND_LABELS.items():
            chip(lambda c, k=kind: c.create_oval(4, 3, 14, 13, fill=mapdraw.TOWN_FILL[k], outline="#111111"))
            text(label)
        # the ring is dark blue: it needs a light plate (on the map it lies on the coast)
        chip(lambda c: (c.create_oval(5, 4, 13, 12, fill=mapdraw.TOWN_FILL["town"], outline="#111111"),
                        c.create_oval(2, 1, 16, 15, outline=mapdraw.PORT_RING, width=2)), bg="#cfd8dc")
        text("Port")
        if band is not None:
            chip(lambda c: c.create_line(0, 8, 18, 8, fill=mapdraw.BAND_COLOUR, width=2, dash=(4, 2)))
            text(f"North band: the top {band:g} %")
        text("North is at the top.")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(f"BB Reroll {APP_VERSION} - Seed search")
        self.geometry("1000x960")
        self.minsize(960, 820)

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
        self.watch_var      = ctk.StringVar(value="Idle")
        self._watch_state   = "idle"

        self.stars_vars:             dict[tuple[str, str], ctk.StringVar] = {}
        self.stars_widgets:          dict[tuple[str, str], "ctk.CTkOptionMenu"] = {}
        # stars the origin fixes: shown, locked, and no condition (the brother always has them)
        self._locked:                dict[tuple[str, str], int] = {}
        self._row_picks: list = []                  # per brother: random stars he gets (None: not known)
        self._cell_top: dict[tuple[str, str], int] = {}     # the highest value each open cell offers
        # stat rolls: the least tier per stat ("any" / "mid" / "high"), same rows as the stars
        self.tiers_vars:             dict[tuple[str, str], ctk.StringVar] = {}
        self.tiers_widgets:          dict[tuple[str, str], "ctk.CTkOptionMenu"] = {}
        # backgrounds: per brother slot (and "any" for at least one brother) the background asked
        # for, by name; ANY_BACKGROUND = no condition. Name -> id per row.
        self.background_vars:        dict[str, ctk.StringVar] = {}
        self._background_ids:        dict[str, dict[str, str]] = {}
        self._background_widgets:    dict[str, "ctk.CTkOptionMenu"] = {}
        self._pending_backgrounds:   dict[str, str] = {}    # saved conditions, until the catalog shows the menus
        # the Map view: the conditions and the Map Options as the player typed them (bbreroll/map_view.py)
        self.map_vars:               dict[str, ctk.StringVar] = {}
        self.map_option_vars:        dict[str, ctk.StringVar] = {}
        self._map_widgets:           list = []          # the fields; they close with the view
        self._map_off = False                           # a fatal map event turned map conditions off (until a Map
        self._map_fatal_notice = None                   # Option, the setup or the game folder changes); its notice
        self._map_versions = (None, None)               # the game and Legends version the workers reported
        self._map_mods = None                           # the mod zips the workers reported (None: not yet)
        self._map_windows:           dict = {}          # (setup, origin, seed) -> the open map window
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
        self._options_note: str | None = None      # the saved-options line of the Map view note (map_view texts)
        self._options_read: dict | None = None     # the Map Options last read from the saved Mod Options (texts)
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
        self._startup_saved_options()  # the Map Options from the saved Mod Options (Legends only)
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
        self.configure(fg_color=PALETTE["bg"])
        self.grid_columnconfigure(0, weight=1)
        # Only the traits row carries the vertical stretch; it must not collapse
        # when the result list grows.
        self.grid_rowconfigure(3, weight=1, minsize=170)

        # Header: name, what it does, the game that was found
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text="BB Reroll", font=(FONT, 20, "bold"), text_color=PALETTE["text"]).grid(
            row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text=f"v{APP_VERSION}", font=(FONT, 11), text_color=PALETTE["faint"]).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        _hint(head, "Find campaign seeds that give the starting brothers you want.").grid(
            row=1, column=0, columnspan=2, sticky="w")
        self.found_var = ctk.StringVar(value=O.found_short())
        found = ctk.CTkLabel(head, textvariable=self.found_var, font=(FONT, 11), text_color=PALETTE["muted"])
        found.grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 10))
        _attach_tooltip(found, lambda: O.found_text(details=True))
        folder_btn = _button(head, "Game folder", self._on_game_folder, kind="secondary", width=110)
        folder_btn.grid(row=0, column=3, rowspan=2, sticky="e")
        _attach_tooltip(folder_btn, lambda: O.found_text(details=True) + "\n\nBB Reroll reads the game files and the "
                        "mod files where they are. It does not copy or change them. Click to select a different "
                        "game folder.")
        _button(head, "Updates", self._open_github, kind="ghost", width=80).grid(
            row=0, column=4, rowspan=2, sticky="e", padx=(8, 0))

        # What to search: labels above their controls
        settings = _panel(self, row=1, column=0, sticky="ew", padx=10, pady=4)
        line_a = ctk.CTkFrame(settings, fg_color="transparent")
        line_a.pack(fill="x", padx=14, pady=(10, 4))
        line_b = ctk.CTkFrame(settings, fg_color="transparent")
        line_b.pack(fill="x", padx=14, pady=(0, 12))
        self.setup_menu = _field(line_a, "Game setup", lambda p: _menu(
            p, list(O.SETUPS) or ["(no game)"], self.setup_var, 150, command=self._on_setup_change))
        self.origin_menu = _field(line_a, "Origin", lambda p: _menu(
            p, O.names_for(self.setup_var.get()), self.origin_var, 230, command=self._on_origin_change))
        bros = _field(line_a, "Brothers", lambda p: _entry(p, self.bro_count_var, 60))
        _attach_tooltip(bros, "The number of brothers that the origin starts with. "
                              "BB Reroll sets it when you select an origin.")
        self.bro_count_var.trace_add("write", lambda *_: self._schedule_grid_rebuild())
        self.sisters_menu = _field(line_a, "Battle sisters", lambda p: _menu(
            p, list(O.BATTLE_SISTERS), self.sisters_var, 170),
            tooltip="Legends only. Use the same setting as in the Mod Options of the game. It changes the brothers.")
        seeds = _field(line_b, SEEDS_TO_TEST, lambda p: _entry(p, self.max_iters_var, 110))
        _attach_tooltip(seeds, "The search stops after it tests this number of seeds.")
        matches = _field(line_b, MATCHES_TO_FIND, lambda p: _entry(p, self.count_var, 70))
        _attach_tooltip(matches, "The search stops when it finds this number of matching seeds.")
        workers = _field(line_b, WORKERS, lambda p: _entry(p, self.workers_var, 60))
        _attach_tooltip(workers, f"The number of search processes that run at the same time. This computer has "
                                 f"{os.cpu_count() or 1} processor threads. With Legends, each process uses "
                                 f"approximately 0.8 GB of memory and needs approximately 15 seconds to start.")

        # Conditions: stars or stat rolls (one grid at a time; both always count)
        cond = _panel(self, row=2, column=0, sticky="ew", padx=10, pady=4)
        cond.grid_columnconfigure(0, weight=1)
        self.grid_title = _title(cond, "STARS")
        self.grid_title.grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))
        self.grid_mode_var = ctk.StringVar(value="Stars")
        self.grid_switch = ctk.CTkSegmentedButton(
            cond, values=["Stars", "Stat rolls", "Backgrounds", "Map"], variable=self.grid_mode_var,
            command=self._on_grid_mode, font=(FONT, 12), height=28,
            fg_color=PALETTE["control"], selected_color=PALETTE["accent"],
            selected_hover_color=PALETTE["accent_hover"], unselected_color=PALETTE["control"],
            unselected_hover_color=PALETTE["control_hover"], text_color=PALETTE["text"])
        self.grid_switch.grid(row=0, column=1, sticky="e", padx=14, pady=(10, 0))
        self.grid_help = _hint(cond, self._GRID_HELP["Stars"])
        self.grid_help.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(2, 0))
        self.origin_info_var = ctk.StringVar(value="")
        self.origin_info_label = ctk.CTkLabel(cond, textvariable=self.origin_info_var, justify="left", anchor="w",
                                              font=(FONT, 11), text_color=PALETTE["star"])
        self.origin_info_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 2))
        self.stars_frame = ctk.CTkFrame(cond, fg_color="transparent")
        self.stars_frame.grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(2, 4))
        self.tiers_frame = ctk.CTkFrame(cond, fg_color="transparent")
        self.tiers_frame.grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(2, 10))
        self.tiers_frame.grid_remove()
        self.backgrounds_frame = ctk.CTkFrame(cond, fg_color="transparent")
        self.backgrounds_frame.grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(2, 10))
        self.backgrounds_frame.grid_remove()
        self._build_map_view(cond)
        # why a stars cell is closed: one colour per reason
        self.stars_legend = ctk.CTkFrame(cond, fg_color="transparent")
        self.stars_legend.grid(row=4, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 10))
        for face, text, label in (("fixed", "fixed_text", "Fixed by the origin"),
                                  ("full", "full_text", "All random stars of the brother are in use"),
                                  ("never", "never_text", "Not possible for this brother")):
            ctk.CTkLabel(self.stars_legend, text="3" if face == "fixed" else "0", width=26, height=20,
                         corner_radius=4, fg_color=PALETTE[face], text_color=PALETTE[text],
                         font=(FONT, 11)).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(self.stars_legend, text=label, font=(FONT, 11), text_color=PALETTE["muted"]).pack(
                side="left", padx=(0, 18))

        # Traits — two scrollable columns
        traits_row = ctk.CTkFrame(self, fg_color="transparent")
        traits_row.grid(row=3, column=0, sticky="nsew", padx=10, pady=4)
        traits_row.grid_columnconfigure(0, weight=1, uniform="traits")
        traits_row.grid_columnconfigure(1, weight=1, uniform="traits")
        traits_row.grid_rowconfigure(0, weight=1)
        self._build_trait_pane(traits_row, 0, "BANNED TRAITS",
                               "A brother with one of these traits does not match.",
                               self.banned_known, self.banned_vars, "banned")
        self._build_trait_pane(traits_row, 1, "REQUIRED TRAITS",
                               "Each brother must have one of these traits (any) or all of them (all).",
                               self.required_known, self.required_vars, "required")

        # Action bar
        actions = _panel(self, row=4, column=0, sticky="ew", padx=10, pady=4)
        actions.grid_columnconfigure(2, weight=1)
        self.search_btn = _button(actions, "▶  Search", self._on_search, kind="primary", width=140, height=34,
                                  font=(FONT, 13, "bold"))
        self.search_btn.grid(row=0, column=0, padx=(12, 6), pady=10)
        self.stop_btn = _button(actions, "■  Stop", self._on_stop, kind="danger", width=90, height=34,
                                state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=6, pady=10)
        ctk.CTkLabel(actions, text="Check a seed", font=(FONT, 12), text_color=PALETTE["muted"]).grid(
            row=0, column=3, padx=(0, 8))
        entry = _entry(actions, self.check_seed_var, 130, placeholder="Seed")
        entry.grid(row=0, column=4, padx=0)
        entry.bind("<Return>", lambda _e: self._on_check_seed())
        self.check_btn = _button(actions, "Show roster", self._on_check_seed, kind="secondary", width=110, height=34)
        self.check_btn.grid(row=0, column=5, padx=(8, 12), pady=10)
        _attach_tooltip(self.check_btn, "Show the starting brothers that this seed gives for the selected game setup "
                                        "and origin. Write the seed exactly as in the game. Upper case and lower "
                                        "case letters are different.")

        # Results — scrollable list. Hidden until a result comes in. While shown it shares the
        # window's spare height with the traits row and the list fills what its panel gets: a
        # list taller than the space left would run past the bottom of the window, and scrolling
        # to its end would show nothing.
        self.match_pane = _panel(self, row=5, column=0, sticky="nsew", padx=10, pady=4)
        self.match_pane.grid_columnconfigure(0, weight=1)
        self.match_pane.grid_rowconfigure(2, weight=1)
        # one line above the list: title, the seed-post description, Clear (the list keeps the height)
        match_head = ctk.CTkFrame(self.match_pane, fg_color="transparent")
        match_head.grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 0))
        match_head.grid_columnconfigure(2, weight=1)
        self.match_title = _title(match_head, "RESULTS")
        self.match_title.grid(row=0, column=0, sticky="w", padx=(0, 16))
        ctk.CTkLabel(match_head, text="Description for the seed post", font=(FONT, 11),
                     text_color=PALETTE["muted"]).grid(row=0, column=1, sticky="w")
        self.share_desc_var = ctk.StringVar(value="")
        _entry(match_head, self.share_desc_var, 200, placeholder="For example: two melee brothers with 3 stars").grid(
            row=0, column=2, sticky="ew", padx=(8, 8))
        _button(match_head, "Clear", self._clear_matches, kind="ghost", width=64, height=26).grid(
            row=0, column=3, sticky="e")
        _attach_tooltip(self.match_title, "These are normal campaign seeds. Start a new campaign with the same game "
                                          "version, mods, origin and recruit Mod Options. Then write the seed exactly "
                                          "as shown.")
        self.match_list = ctk.CTkScrollableFrame(self.match_pane, height=140, fg_color="transparent")
        self.match_list.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self.match_pane.grid_remove()

        # Reusable notice banner — hidden until something needs attention (the old
        # in-game mod still installed, a search that could not run, no match found).
        # One strip, recolored per severity, with an optional action button and a ✕ to
        # dismiss. Dismissal is sticky per message text for this GUI session.
        self.notice_var = ctk.StringVar(value="")
        self.notice_banner = ctk.CTkFrame(self, fg_color="#3a2a00", corner_radius=8, border_width=1)
        self.notice_banner.grid(row=6, column=0, sticky="ew", padx=10, pady=4)
        self.notice_banner.grid_columnconfigure(0, weight=1)
        self.notice_label = ctk.CTkLabel(self.notice_banner, textvariable=self.notice_var, font=(FONT, 12),
                                         anchor="w", justify="left", wraplength=760, text_color="#ffcf66")
        self.notice_label.grid(row=0, column=0, sticky="ew", padx=(14, 4), pady=8)
        self.notice_action_btn = _button(self.notice_banner, "", self._on_notice_action, kind="secondary",
                                         width=90, height=26)
        self.notice_action_btn.grid(row=0, column=1, sticky="ne", padx=(0, 6), pady=8)
        self.notice_action_btn.grid_remove()
        self.notice_close = _button(self.notice_banner, "✕", self._dismiss_notice, kind="ghost", width=28, height=26)
        self.notice_close.grid(row=0, column=2, sticky="ne", padx=(0, 10), pady=8)
        self.notice_banner.grid_remove()

        # Status bar
        status = ctk.CTkFrame(self, fg_color="transparent")
        status.grid(row=7, column=0, sticky="ew", padx=14, pady=(2, 8))
        status.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(status, textvariable=self.status_var, anchor="w", font=(FONT, 12),
                     text_color=PALETTE["text"]).grid(row=0, column=0, sticky="ew")
        right = ctk.CTkFrame(status, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e")
        self.watch_dot = ctk.CTkLabel(right, text="●", font=(FONT, 14), text_color="#6a6e76", width=14)
        self.watch_dot.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(right, textvariable=self.watch_var, font=(FONT, 12), text_color=PALETTE["muted"]).pack(side="left")

    def _build_trait_pane(self, parent, col, title, help_text, known_list, vars_dict, kind):
        pane = _panel(parent)
        pane.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 4, 4 if col == 0 else 0))
        pane.grid_rowconfigure(2, weight=1)
        pane.grid_columnconfigure(0, weight=1)

        # Title row: title on the left, the bulk buttons (and, for "required", any / all) on the right
        title_row = ctk.CTkFrame(pane, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        title_row.grid_columnconfigure(0, weight=1)
        _title(title_row, title).grid(row=0, column=0, sticky="w")
        bulk = ctk.CTkFrame(title_row, fg_color="transparent")
        bulk.grid(row=0, column=1, sticky="e")
        if kind == "required":
            ctk.CTkSegmentedButton(bulk, values=["any", "all"], variable=self.required_mode_var, width=90, height=26,
                                   font=(FONT, 11), fg_color=PALETTE["control"], selected_color=PALETTE["accent"],
                                   selected_hover_color=PALETTE["accent_hover"],
                                   unselected_color=PALETTE["control"], unselected_hover_color=PALETTE["control_hover"],
                                   text_color=PALETTE["text"]).pack(side="left", padx=(0, 10))
        for text, command in (("All", lambda k=kind: self._bulk_check(k, True)),
                              ("None", lambda k=kind: self._bulk_check(k, False)),
                              ("Invert", lambda k=kind: self._bulk_invert(k))):
            _button(bulk, text, command, kind="ghost", width=54, height=24, font=(FONT, 11)).pack(side="left", padx=2)
        _hint(pane, help_text + " Point to a trait to see its effects.", wrap=420).grid(
            row=1, column=0, sticky="ew", padx=14, pady=(2, 2))

        # Scrollable list
        sf = ctk.CTkScrollableFrame(pane, fg_color="transparent")
        sf.grid(row=2, column=0, sticky="nsew", padx=8, pady=2)

        # Add-custom row at bottom
        add_row = ctk.CTkFrame(pane, fg_color="transparent")
        add_row.grid(row=3, column=0, sticky="ew", padx=12, pady=(2, 10))
        add_row.grid_columnconfigure(0, weight=1)
        entry = _entry(add_row, None, 100, placeholder="Trait ID, for example iron_jaw")
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        _button(add_row, "Add", lambda: self._add_custom_trait(kind, entry), kind="secondary", width=56,
                height=28).grid(row=0, column=1)
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

            cb = ctk.CTkCheckBox(row, text=self._display_for(trait), variable=v, font=(FONT, 12),
                                 text_color=PALETTE["text"], fg_color=PALETTE["accent"],
                                 hover_color=PALETTE["accent_hover"], border_color=PALETTE["faint"],
                                 border_width=2, checkbox_width=18, checkbox_height=18, corner_radius=4)
            cb.grid(row=0, column=0, sticky="w", padx=(2, 4), pady=1)
            _attach_tooltip(cb, lambda t=trait: self._trait_tooltip(t))
            edit = ctk.CTkButton(row, text="✏", width=24, height=22, font=(FONT, 11), fg_color="transparent",
                                 hover_color=PALETTE["control"], text_color=PALETTE["faint"],
                                 command=lambda t=trait, k=kind: self._edit_trait(k, t))
            edit.grid(row=0, column=1, padx=1)
            _attach_tooltip(edit, "Change the name or the trait ID")
            remove = ctk.CTkButton(row, text="✕", width=24, height=22, font=(FONT, 11), fg_color="transparent",
                                   hover_color=PALETTE["danger_hover"], text_color=PALETTE["faint"],
                                   command=lambda t=trait, k=kind: self._remove_trait(k, t))
            remove.grid(row=0, column=2, padx=(1, 2))
            _attach_tooltip(remove, "Remove this trait from the list")

    _EFFECT_COLOURS = {"+": PALETTE["good"], "-": PALETTE["bad"], "": "#c9d1d9"}

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
            lines.append((found["description"] or "The game tooltip shows no effects.", PALETTE["muted"], False))
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
        self.status_var.set(f"Trait {self._display_for(trait)} is removed from the {kind} list.")

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
            self.status_var.set("The trait ID cannot be empty.")
            return
        if new_id != trait and new_id in known_list:
            self.status_var.set(f"{new_id} is already in the {kind} list.")
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
            self.status_var.set(f"The trait ID {trait} is now {new_id} ({new_display}).")
        else:
            self.status_var.set(f"The name of {trait} is now {new_display}.")

    def _add_custom_trait(self, kind, entry: ctk.CTkEntry):
        raw  = entry.get()
        name = sanitize_trait(raw)
        entry.delete(0, "end")
        if not name:
            if raw.strip():
                self.status_var.set(f"{raw} is not a trait ID. Use only letters, digits and _.")
            return
        _, known_list, vars_dict = self._pane_ctx(kind)
        if name in known_list:
            vars_dict[name].set(True)
            return
        known_list.append(name)
        self._populate_trait_pane(kind)
        if name in vars_dict:
            vars_dict[name].set(True)

    # ── stars grid and stat-rolls grid (rebuilt when the brother count or the origin changes) ──
    # A cell is neutral until it asks for something: amber for stars, teal for stat rolls.
    _GRID_HELP = {
        "Stars": "Select the minimum number of stars for each stat (0 = no condition).\n"
                 "Row All is for each brother. Rows 1, 2, 3 ... are for one brother and replace row All for him.\n"
                 "The colour of a closed cell shows why it is closed (see below the grid).",
        "Stat rolls": "Select the minimum roll for each stat: mid = middle third or better, high = top third.\n"
                      "The thirds are of the values that the background of the brother can roll. "
                      "The background sets most of a stat; the seed changes it only in this range.\n"
                      "Row All is for each brother. Dark cells: the seed cannot change this stat for this brother.",
        "Backgrounds": "Select the background that a brother must have. Some origins let the seed select the "
                       "background. Other origins always give the same backgrounds.\n"
                       "Row Any brother: at least one brother must have this background. Use it with the stat "
                       "rolls: a high roll is high for the background of the brother.",
        "Map": map_view.HELP,
    }
    _SET_ROW = "Set row"
    ANY_BACKGROUND = "Any background"
    _GRID_TITLES = {"Stars": "STARS", "Stat rolls": "STAT ROLLS", "Backgrounds": "BACKGROUNDS", "Map": "MAP"}

    # closed cells: why they are closed decides their look (legend under the grid)
    _CLOSED = {"never": ("never", "never_text"), "fixed": ("fixed", "fixed_text"), "full": ("full", "full_text")}

    def _close_cell(self, widget, reason):
        """Disable a grid cell and give it the look of its reason: "never" (the brother never gets
        it), "fixed" (the origin sets it) or "full" (his random stars are all in use)."""
        face, text = self._CLOSED[reason]
        try:
            widget.configure(state="disabled", fg_color=PALETTE[face], button_color=PALETTE[face],
                             button_hover_color=PALETTE[face], text_color_disabled=PALETTE[text])
        except Exception:
            pass

    def _style_cell(self, widget, active_fg, active_btn, active):
        try:
            if active:
                widget.configure(fg_color=active_fg, button_color=active_btn, button_hover_color=active_btn,
                                 text_color=PALETTE["on_colour"])
            else:
                widget.configure(fg_color=PALETTE["control"], button_color=PALETTE["control_btn"],
                                 button_hover_color=PALETTE["control_hover"], text_color=PALETTE["text"])
        except Exception:
            pass

    def _on_star_changed(self, slot: str, stat: str, *_):
        key = (slot, stat)
        widget = self.stars_widgets.get(key)
        if widget is None or key in self._locked or self._cell_top.get(key, 0) == 0:
            return          # a closed cell keeps the look of its reason
        if str(widget.cget("state")) == "disabled":
            return          # closed because the brother's random stars are in use
        self._style_cell(widget, PALETTE["star"], PALETTE["star_btn"], (to_int(self.stars_vars[key].get()) or 0) > 0)
        self._limit_random_stars(slot)

    def _limit_random_stars(self, slot):
        """A brother gets random stars in only so many stats (Berserker: 2, besides his fixed HP and
        MSK). When his own row asks for that many, his other open cells can only stay 0: they turn
        grey until one of the asked stats is set back to 0. Row All covers brothers with different
        numbers, so it stays open (the check before the search covers it)."""
        if slot == "*" or not self._row_picks:
            return
        n = int(slot)
        if n > len(self._row_picks) or self._row_picks[n - 1] is None:
            return
        picks = self._row_picks[n - 1]
        open_cells = [stat for stat in STATS if (slot, stat) not in self._locked
                      and self._cell_top.get((slot, stat), 0) > 0]
        if any((slot, stat) not in self.stars_widgets for stat in open_cells):
            return          # the row is still being built
        asked = [stat for stat in open_cells if (to_int(self.stars_vars[(slot, stat)].get()) or 0) > 0]
        full = len(asked) >= picks
        for stat in open_cells:
            if stat not in asked:
                widget = self.stars_widgets[(slot, stat)]
                if full:
                    self._close_cell(widget, "full")
                elif str(widget.cget("state")) == "disabled":
                    widget.configure(state="normal")
                    self._style_cell(widget, PALETTE["star"], PALETTE["star_btn"], False)

    def _on_tier_changed(self, slot: str, stat: str, *_):
        widget = self.tiers_widgets.get((slot, stat))
        if widget is not None and len(widget.cget("values")) > 1:     # a closed cell keeps its look
            self._style_cell(widget, PALETTE["roll"], PALETTE["roll_btn"],
                             self.tiers_vars[(slot, stat)].get() in ("mid", "high"))

    def _on_grid_mode(self, mode=None):
        mode = self.grid_mode_var.get()
        if mode not in self._GRID_HELP:
            mode = "Stars"
        stars = mode == "Stars"
        self.grid_title.configure(text=self._GRID_TITLES[mode])
        self.grid_help.configure(text=self._GRID_HELP[mode])
        for widget, show in ((self.stars_frame, stars), (self.origin_info_label, stars),
                             (self.stars_legend, stars), (self.tiers_frame, mode == "Stat rolls"),
                             (self.backgrounds_frame, mode == "Backgrounds"), (self.map_frame, mode == "Map")):
            widget.grid() if show else widget.grid_remove()

    def _grid_header(self, frame):
        """Column titles (full stat names on hover) and the "Set row" column."""
        ctk.CTkLabel(frame, text="", width=46).grid(row=0, column=0)
        for j, stat in enumerate(STATS):
            head = ctk.CTkLabel(frame, text=stat.upper(), font=(FONT, 11, "bold"), text_color=PALETTE["muted"])
            head.grid(row=0, column=j + 1, padx=2, pady=(0, 2))
            _attach_tooltip(head, STAT_NAMES[stat])
        head = ctk.CTkLabel(frame, text="", font=(FONT, 11, "bold"), text_color=PALETTE["muted"])
        head.grid(row=0, column=len(STATS) + 1, padx=(12, 2))

    def _row_label(self, frame, row, slot):
        label = ctk.CTkLabel(frame, text="All" if slot == "*" else slot, width=46, anchor="w",
                             font=(FONT, 12, "bold"), text_color=PALETTE["muted"] if slot == "*" else PALETTE["text"])
        label.grid(row=row, column=0, padx=(4, 2), pady=2)
        if slot == "*":
            _attach_tooltip(label, "Row All applies to each brother that has no row of his own.")

    def _row_setter(self, frame, row, slot, values, apply):
        """A menu at the end of a row that sets each cell of the row to one value."""
        var = ctk.StringVar(value=self._SET_ROW)
        menu = _menu(frame, values, var, 86, command=lambda value, s=slot, v=var: (apply(s, value),
                                                                                    v.set(self._SET_ROW)))
        menu.configure(fg_color=PALETTE["panel"], button_color=PALETTE["panel"], text_color=PALETTE["muted"])
        menu.grid(row=row, column=len(STATS) + 1, padx=(12, 2), pady=2)

    def _set_roll_row(self, slot, value):
        """Each cell of a stat-rolls row to `value`; cells the seed cannot change stay "any"."""
        for stat in STATS:
            widget = self.tiers_widgets.get((slot, stat))
            if widget is not None and value in widget.cget("values"):
                self.tiers_vars[(slot, stat)].set(value)

    def _rebuild_tiers_grid(self, n, facts):
        """The stat-rolls grid: same rows as the stars grid; a cell offers only "any" where the seed
        cannot move that stat for that brother."""
        prior = {k: v.get() for k, v in self.tiers_vars.items()}
        for w in self.tiers_frame.winfo_children():
            w.destroy()
        self.tiers_vars.clear()
        self.tiers_widgets.clear()
        self._grid_header(self.tiers_frame)
        for ri, slot in enumerate(["*"] + [str(i) for i in range(1, n + 1)], start=1):
            self._row_label(self.tiers_frame, ri, slot)
            for j, stat in enumerate(STATS):
                options = star_limits.roll_options(facts, slot, stat)
                value = prior.get((slot, stat), "any")
                if value not in options:
                    value = "any"
                v = ctk.StringVar(value=value)
                self.tiers_vars[(slot, stat)] = v
                w = _menu(self.tiers_frame, options, v, 66, state="normal" if len(options) > 1 else "disabled")
                w.grid(row=ri, column=j + 1, padx=2, pady=2)
                self.tiers_widgets[(slot, stat)] = w
                v.trace_add("write", lambda *_a, s=slot, t=stat: self._on_tier_changed(s, t))
                self._on_tier_changed(slot, stat)
                if len(options) == 1:
                    self._close_cell(w, "never")
            self._row_setter(self.tiers_frame, ri, slot, ["high", "mid", "any"], self._set_roll_row)

    def _on_background_changed(self, slot, *_):
        widget = self._background_widgets.get(slot)
        if widget is not None:
            self._style_cell(widget, PALETTE["roll"], PALETTE["roll_btn"],
                             self.background_vars[slot].get() != self.ANY_BACKGROUND)

    def _rebuild_backgrounds_view(self, n, facts):
        """One row per brother: a menu of the backgrounds he can get when the seed selects it, else
        his fixed background as text; and the row "Any brother" when two or more brothers vary."""
        prior = {k: v.get() for k, v in self.background_vars.items()}
        for w in self.backgrounds_frame.winfo_children():
            w.destroy()
        self.background_vars.clear()
        self._background_ids.clear()
        self._background_widgets = {}
        names = background_limits.names_for(self._catalog(), O.SCENARIO.get(self.origin_var.get()))
        per_slot = background_limits.choices(facts, names)
        info = background_limits.describe(facts, names) if facts else (
            self._catalog_progress or "The backgrounds of this origin are not known yet.")
        ctk.CTkLabel(self.backgrounds_frame, text=info, font=(FONT, 11), text_color=PALETTE["star"], justify="left",
                     anchor="w", wraplength=880).grid(row=0, column=0, columnspan=3, sticky="w", padx=(4, 2), pady=(0, 4))
        rows = []
        some = background_limits.any_choices(facts, names)
        if some:
            rows.append((background_limits.ANY_BROTHER, "Any brother", some))
        for i in range(1, n + 1):
            rows.append((str(i), str(i), per_slot[i - 1] if facts and i <= len(per_slot) else None))
        # two columns of rows for a big roster (Peasant Militia has 12 brothers)
        half = (len(rows) + 1) // 2 if len(rows) > 7 else len(rows)
        for k, (slot, label, options) in enumerate(rows):
            row, col = 1 + k % half, 3 * (k // half)
            ctk.CTkLabel(self.backgrounds_frame, text=label, width=46 if slot != background_limits.ANY_BROTHER else 90,
                         anchor="w", font=(FONT, 12, "bold"),
                         text_color=PALETTE["text"]).grid(row=row, column=col, sticky="w", padx=(4 if col == 0 else 24, 2),
                                                          pady=2)
            if options is not None and len(options) > 1:
                ids = {name: bid for bid, name in options}
                self._background_ids[slot] = ids
                value = prior.get(slot, self.ANY_BACKGROUND)
                pending = self._pending_backgrounds.get(slot)
                if pending is not None:
                    value = next((name for name, bid in ids.items() if bid == pending), value)
                if value not in ids:
                    value = self.ANY_BACKGROUND
                v = ctk.StringVar(value=value)
                self.background_vars[slot] = v
                w = _menu(self.backgrounds_frame, [self.ANY_BACKGROUND] + list(ids), v, 230)
                w.grid(row=row, column=col + 1, sticky="w", padx=2, pady=2)
                self._background_widgets[slot] = w
                v.trace_add("write", lambda *_a, s=slot: self._on_background_changed(s))
                self._on_background_changed(slot)
            else:
                text = options[0][1] if options else "Not known yet"
                ctk.CTkLabel(self.backgrounds_frame, text=text, font=(FONT, 12), anchor="w", width=230,
                             text_color=PALETTE["muted"]).grid(row=row, column=col + 1, sticky="w", padx=8, pady=2)
        if facts:
            self._pending_backgrounds = {}

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

        try:
            n = max(1, min(20, int(self.bro_count_var.get() or "1")))
        except ValueError:
            n = 5

        # a cell offers only what that brother can get at all (when the origin's facts are known);
        # a star the origin fixes is shown but locked, like a cell the brother can never get
        facts = self._slot_facts(self.origin_var.get())
        was_locked, self._locked = self._locked, self._locked_for(self.origin_var.get(), facts)
        self._row_picks = star_limits.random_stars(facts)       # per brother: how many random stars
        self._cell_top = {}
        self._grid_header(self.stars_frame)
        for ri, slot in enumerate(["*"] + [str(i) for i in range(1, n + 1)], start=1):
            self._row_label(self.stars_frame, ri, slot)
            for j, stat in enumerate(STATS):
                key = (slot, stat)
                if key in self._locked:
                    v = ctk.StringVar(value=str(self._locked[key]))
                    self.stars_vars[key] = v
                    w = _menu(self.stars_frame, [v.get()], v, 66, state="disabled")
                    self._close_cell(w, "fixed")
                    w.grid(row=ri, column=j + 1, padx=2, pady=2)
                    self.stars_widgets[key] = w
                    continue
                top = star_limits.cell_max(facts, slot, stat)
                self._cell_top[key] = top
                value = "0" if key in was_locked else prior.get(key, "0")
                if to_int(value) is not None and to_int(value) > top:
                    value = str(top)
                v = ctk.StringVar(value=value)
                self.stars_vars[(slot, stat)] = v
                w = _menu(self.stars_frame, [str(i) for i in range(top + 1)], v, 66,
                          state="normal" if top > 0 else "disabled")
                w.grid(row=ri, column=j + 1, padx=2, pady=2)
                self.stars_widgets[(slot, stat)] = w
                v.trace_add("write", lambda *_a, s=slot, t=stat: self._on_star_changed(s, t))
                self._on_star_changed(slot, stat)
                if top == 0:
                    self._close_cell(w, "never")
            self._limit_random_stars(slot)
            # no "Set row" here: a brother gets stars in only 2 to 4 stats, so a full row never matches
        self._rebuild_tiers_grid(n, facts)
        self._rebuild_backgrounds_view(n, facts)

    # ── the Map view (the logic is in bbreroll/map_view.py) ──
    def _build_map_view(self, parent):
        """The minimum ports and towns a map must have, and the Map Options of the game: the map depends on them."""
        frame = self.map_frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(2, 10))
        frame.grid_remove()
        self.map_note_var = ctk.StringVar(value="")
        self.map_note = ctk.CTkLabel(frame, textvariable=self.map_note_var, justify="left", anchor="w",
                                     font=(FONT, 11), text_color=PALETTE["star"], wraplength=880)
        self.map_note.grid(row=0, column=0, sticky="w", padx=4, pady=(0, 4))
        self.map_note.grid_remove()
        conditions, options = map_view.default_conditions(), map_view.default_options()

        def line(row):
            box = ctk.CTkFrame(frame, fg_color="transparent")
            box.grid(row=row, column=0, sticky="w", padx=(4, 0), pady=2)
            return box

        def entry(box, label, variables, key, default, tooltip=None):
            var = variables[key] = ctk.StringVar(value=default)
            self._map_widgets.append(_field(box, label, lambda p: _entry(p, var, 70), tooltip=tooltip))

        top, towns = line(1), line(2)
        for key, label in map_view.CONDITION_LABELS.items():
            entry(top, label, self.map_vars, key, conditions[key], map_view.CONDITION_TIPS[key])
        for key, label in map_view.TOWN_LABELS.items():
            entry(towns, label, self.map_vars, key, conditions[key], map_view.town_tip(label))
        bar = ctk.CTkFrame(frame, fg_color="transparent")       # the title of the Map Options and their read button
        bar.grid(row=3, column=0, sticky="w", padx=4, pady=(6, 0))
        _hint(bar, map_view.OPTIONS_TITLE, wrap=640).grid(row=0, column=0, sticky="w")
        read = _button(bar, map_view.READ_BUTTON, self._read_saved_options, width=180)
        read.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self._map_widgets.append(read)
        box = line(4)
        for key, label in map_view.OPTION_LABELS.items():
            if key in map_view.YES_NO_OPTIONS:
                var = self.map_option_vars[key] = ctk.StringVar(value=options[key])
                # no tooltip: they got stuck on dropdowns
                self._map_widgets.append(_field(box, label, lambda p: _menu(p, [map_view.YES, map_view.NO], var, 80)))
            else:
                low, high = map_view.OPTION_RANGES[key]
                entry(box, f"{label} ({low}-{high})", self.map_option_vars, key, options[key])
            # a changed Map Option turns map conditions on again after a map fatal
            self.map_option_vars[key].trace_add("write", self._lift_map_lockout)

    def _map_usable(self) -> bool:
        return map_view.view_state(self._legends(), self._map_off)[0]

    def _lift_map_lockout(self, *_):
        """Map conditions count again: the player changed a Map Option, the setup or the game folder (after a
        fatal map event the cause can be a Map Option that the game cannot make a map of). The notice of the
        map fatal goes away with it; another notice stays."""
        if not self._map_off:
            return
        self._map_off = False
        if self._map_fatal_notice and self.notice_var.get() == self._map_fatal_notice:
            self._clear_notice()
        self._map_fatal_notice = None
        self._apply_map_state()

    def _map_verified(self) -> bool:
        """Were maps of this game, Legends version and mod set checked against the real game? The versions and
        the mods the workers reported win over what the mod file names say."""
        found = O.FOUND or {}
        game = self._map_versions[0] or found.get("game_version")
        legends = self._map_versions[1] or map_view.legends_version_from_files(found.get("mods"))
        mods = found.get("mods") if self._map_mods is None else self._map_mods
        return map_view.verified(game, legends, mods)

    def _apply_map_state(self):
        """Open or close the fields and show the line that says why (not Legends, turned off, version)."""
        if not hasattr(self, "map_note"):       # the window is still being built
            return
        usable, why = map_view.view_state(self._legends(), self._map_off)
        opened = map_view.fields_open(self._legends())      # also while conditions are off: a Map Option can fix it
        for widget in self._map_widgets:
            widget.configure(state="normal" if opened else "disabled")
            if isinstance(widget, ctk.CTkEntry):
                widget.configure(text_color=PALETTE["text"] if opened else PALETTE["faint"])
        lines = [why] if why else []
        if opened and self._options_note:
            lines.append(self._options_note)
        if usable and not self._map_verified():
            lines.append(map_view.NOT_VERIFIED)
        self.map_note_var.set("\n".join(lines))
        self.map_note.grid() if lines else self.map_note.grid_remove()

    def _map_setup(self):
        """(map conditions or None, Map Options or None, errors) from the fields; nothing while the view is closed."""
        if not self._map_usable():
            return None, None, []
        return map_view.build({k: v.get() for k, v in self.map_vars.items()},
                              {k: v.get() for k, v in self.map_option_vars.items()})

    def _set_map_fields(self, map_criteria, options):
        """Fill the fields from map conditions and numeric Map Options (the self-test's spec); None: the defaults."""
        conditions, texts = map_view.fields_from_spec(map_criteria, options)
        for key, var in self.map_vars.items():
            var.set(conditions[key])
        for key, var in self.map_option_vars.items():
            var.set(texts[key])

    def _restore_map_values(self, data):
        """The Map view's values from a settings file; a file from before the Map view gives the defaults."""
        conditions, options = map_view.from_settings(data)
        for key, var in self.map_vars.items():
            var.set(conditions[key])
        for key, var in self.map_option_vars.items():
            var.set(options[key])
        read = data.get("map_options_read") if isinstance(data, dict) else None
        self._options_read = read if isinstance(read, dict) and all(isinstance(v, str) for v in read.values()) else None

    def _fill_options(self, texts: dict):
        """The seven Map Options from the texts of the saved Mod Options; they are remembered for the settings file
        ("map_options_read") and the note about the file goes."""
        self._options_note = None
        for key, var in self.map_option_vars.items():
            var.set(texts[key])
        self._options_read = texts

    def _read_saved_options(self, show_note: bool = True) -> bool:
        """The button: the Map Options from the saved Mod Options. False when nothing could be read: the fields stay
        as they are and, with show_note, the Map view says so."""
        texts = map_view.saved_option_texts(msu_settings.read_map_options())
        if texts is None:
            if show_note:
                self._options_note = map_view.NO_SAVED_OPTIONS
                self._apply_map_state()
            return False
        self._fill_options(texts)
        self._apply_map_state()
        return True

    def _startup_saved_options(self):
        """Start-up on Legends: the Map Options come from the saved Mod Options unless the player typed other values
        since the program last read them (map_view.fill_at_startup); otherwise the Map view says when they differ. A
        self-test never reads the file (its spec sets the Map Options). Switching the setup later does not read."""
        if os.environ.get("BB_REROLL_SELFTEST") or not self._legends():
            return
        try:        # a failed read must not stop the start: the exe has no console, nobody would see the error
            saved = map_view.saved_option_texts(msu_settings.read_map_options())
        except Exception:
            saved = None
        current = {key: var.get() for key, var in self.map_option_vars.items()}
        if map_view.fill_at_startup(self._saved, current, saved):
            self._fill_options(saved)
        elif saved is None:
            self._options_note = map_view.NO_SAVED_OPTIONS
        elif saved != current:
            self._options_note = map_view.OPTIONS_DIFFER
        else:                       # the fields hold the saved values: the next start sees them as untouched
            self._options_read = saved
        self._apply_map_state()

    # ── game setup / origin ──
    def _legends(self) -> bool:
        return O.SETUPS.get(self.setup_var.get(), (None, False))[1]

    def _on_setup_change(self, _value=None):
        names = O.names_for(self.setup_var.get())
        self.origin_menu.configure(values=names)
        if self.origin_var.get() not in names:
            self.origin_var.set(names[0])
        self.sisters_menu.configure(state="normal" if self._legends() else "disabled")
        self._lift_map_lockout()        # (also the game folder: it ends here)
        self._apply_map_state()
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
        # a new origin starts with no background conditions (saved ones are for the saved origin only)
        if value != self._saved.get("last_origin"):
            self._pending_backgrounds = {}
        for var in self.background_vars.values():
            var.set(self.ANY_BACKGROUND)
        self._rebuild_stars_grid()
        # a new origin starts with empty brother rows (row All stays; locked cells show the origin's stars)
        for key, var in self.stars_vars.items():
            if key[0] != "*" and key not in self._locked:
                var.set("0")
        facts = self._slot_facts(value)
        if facts is not None:
            self.origin_info_var.set(f"What {value} gives:\n" + star_limits.describe(facts, sizes))
        elif self._legends():
            self._refresh_origin_info()
        else:
            self.origin_info_var.set("The fixed stars of this origin are not known yet.")
        if facts is None and self._catalog_progress:
            self.origin_info_var.set((self.origin_info_var.get() + "\n" + self._catalog_progress).strip())

    def _locked_for(self, origin, facts):
        """{(slot, stat): stars} the origin fixes: from the game's facts, else (Legends, until the
        catalog is there) from the built-in table."""
        if facts is not None:
            return star_limits.locked_cells(facts)
        if self._legends():
            return {(str(n), stat): value for n, fixed in enumerate(ORIGIN_HARDCODED_STARS.get(origin, []), 1)
                    for stat, value in fixed.items()}
        return {}

    # ── what each origin can roll (bbseed/catalog.py) ──
    def _profile(self):
        return O.SETUPS.get(self.setup_var.get(), (None, False))[0]

    def _catalog(self):
        return self._catalogs.get(self._profile())

    def _background_names(self):
        return background_limits.names_for(self._catalog(), O.SCENARIO.get(self.origin_var.get()))

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
                    put(("catalog_progress", "Reading what each origin can roll. This occurs one time only."))
                    found = catalog.build(profile, workers=workers, should_stop=stop.is_set,
                                          on_event=lambda kind, payload: put(("catalog_event", (kind, payload))))
            except Exception as e:      # the search works without it: only the extra checks are missing
                put(("catalog_progress", f"Cannot read what the origins can roll: {type(e).__name__}: {e}"))
            put(("catalog_done", (profile, found)))

        threading.Thread(target=run, daemon=True).start()

    def _ev_catalog_progress(self, text):
        self._catalog_progress = text
        if self._slot_facts(self.origin_var.get()) is None:
            base = self.origin_info_var.get().split("\n")
            kept = [line for line in base if not line.startswith(("Reading what", "Cannot read what"))]
            self.origin_info_var.set("\n".join(kept + [text]).strip())

    def _ev_catalog_event(self, payload):
        kind, data = payload
        if kind == "preparing":
            name, done, total = data
            self._ev_catalog_progress(f"Reading what each origin can roll (one time only): game scripts, "
                                      f"{done:,} of {total:,}")
        elif kind == "ready":
            self._ev_catalog_progress(f"Reading what each origin can roll (one time only): "
                                      f"{data[0]} of {data[1]} workers are ready")
        elif kind == "origin":
            self._ev_catalog_progress(f"Reading what each origin can roll (one time only): "
                                      f"{data[0]} of {data[1]} origins")
        elif kind == "fatal":
            self._ev_catalog_progress(f"Cannot read what the origins can roll: {str(data)[:200]}")

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
        self._rebuild_stars_grid()          # also locks the stars the origin fixes
        self.origin_info_var.set(f"What {origin} gives:\n" + star_limits.describe(facts, sizes))

    def _refresh_origin_info(self):
        try:
            self.origin_info_var.set(summarize_origin(self.origin_var.get()))
        except Exception:
            self.origin_info_var.set("")

    def _ready_status(self):
        if O.FOUND is None:
            self.status_var.set(O.found_text())
        else:
            self.status_var.set("Ready. Select an origin and set the conditions. Then click Search.")
        if hasattr(self, "found_var"):
            self.found_var.set(O.found_short())

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
                                         title="Select the Battle Brothers folder (the folder with the \"data\" folder)")
        if not chosen:
            return
        if gamedata.as_data_dir(chosen) is None:
            messagebox.showerror("Game folder", f"There are no game files (data\\data_001.dat) in\n{chosen}")
            return
        self._game_folder = chosen
        os.environ["BBSEED_GAME_DATA"] = chosen
        O.refresh()
        self._map_versions = (None, None)       # another game: the versions of the last search do not count
        self._map_mods = None
        self._lift_map_lockout()                # and a map fatal of the other game does not count either
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
        messagebox.showerror("Game not found", "BB Reroll cannot find Battle Brothers on this computer.\n\n"
                             "Click \"Game folder\". Then select the folder of the game.")
        return False

    # ── the old in-game mod (BB Reroll 3.x) ──
    def _warn_old_mod(self):
        text = O.reroll_mod_warning()
        if text:
            self._show_notice("⚠ " + text, kind="warn", action=("Remove", self._on_remove_old_mod))

    def _on_remove_old_mod(self):
        names = list((O.FOUND or {}).get("reroll_mod") or [])
        if not names:
            return
        data = O.FOUND["data"]
        listing = "\n  ".join(names)
        if not messagebox.askyesno("Remove the old mod",
                                   f"Delete these files from\n{data}?\n\n  {listing}\n\n"
                                   "This is the in-game search mod of BB Reroll 3. "
                                   "Start Battle Brothers again after this."):
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
            self._show_notice("Cannot delete the file. Make sure that Battle Brothers is closed. "
                              + "; ".join(failed), kind="error")
        else:
            self.status_var.set("The old mod is removed. If Battle Brothers is open, start it again.")

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
                if (slot, stat) in self._locked:
                    continue        # the origin's own star: no condition, and it must not replace row All
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
        # backgrounds: the rows that ask for one (saved ones still waiting for the catalog count too)
        backgrounds_by_slot = {slot: [bid] for slot, bid in self._pending_backgrounds.items()}
        for slot, var in self.background_vars.items():
            bid = self._background_ids.get(slot, {}).get(var.get())
            if bid:
                backgrounds_by_slot[slot] = [bid]
            else:
                backgrounds_by_slot.pop(slot, None)
        criteria = {
            "stars_by_slot": stars_by_slot,
            "tiers_by_slot": tiers_by_slot,
            "backgrounds_by_slot": backgrounds_by_slot,
            "banned":   [t for t, v in self.banned_vars.items()   if v.get()],
            "required": [t for t, v in self.required_vars.items() if v.get()],
            "required_mode": self.required_mode_var.get(),
        }
        map_criteria = self._map_setup()[0]
        if map_criteria:            # only a run with a map condition has the key (a map costs about 40 s)
            criteria["map"] = map_criteria
        return criteria

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
                    if (slot, stat) in self.stars_vars and (slot, stat) not in self._locked:
                        self.stars_vars[(slot, stat)].set(str(n))
        tiers = saved.get("tiers_by_slot")
        if isinstance(tiers, dict) and self._saved.get("last_origin") == self.origin_var.get():
            for slot, stats in tiers.items():
                for stat, level in (stats or {}).items():
                    if (slot, stat) in self.tiers_vars and level in ("mid", "high"):
                        self.tiers_vars[(slot, stat)].set(level)
        backgrounds = saved.get("backgrounds_by_slot")
        if isinstance(backgrounds, dict) and self._saved.get("last_origin") == self.origin_var.get():
            for slot, ids in backgrounds.items():
                if isinstance(ids, list) and ids and isinstance(ids[0], str):
                    name = next((n for n, bid in self._background_ids.get(slot, {}).items() if bid == ids[0]), None)
                    if name is not None:
                        self.background_vars[slot].set(name)
                    else:           # the menus come with the catalog
                        self._pending_backgrounds[slot] = ids[0]

    def _numbers(self):
        values = {SEEDS_TO_TEST: to_int(self.max_iters_var.get()),
                  MATCHES_TO_FIND: to_int(self.count_var.get()),
                  WORKERS: to_int(self.workers_var.get())}
        return values, number_errors(values, os.cpu_count() or 1)

    # ── starting / stopping a search ──
    def _on_search(self):
        if self._searching or not self._have_game():
            return
        criteria = self._gather_criteria()
        numbers, errors = self._numbers()
        _map, map_options, map_errors = self._map_setup()
        if errors or map_errors:
            messagebox.showerror("Cannot search", "\n".join(errors + map_errors))
            return
        # Pre-flight: trivially-passing criteria match every seed immediately (a map condition is a condition).
        if is_trivial(criteria) and not criteria.get("map"):
            if not messagebox.askyesno("No conditions", "You set no stars, no stat rolls, no backgrounds and no traits. "
                                       "Each seed matches.\n\nSearch?"):
                return
        # Pre-flight: criteria no seed can meet — stars an origin fixes lower, stats a brother never
        # gets stars in, more starred stats than he can have (the game's own facts, when known), and map
        # conditions that no map can meet with these Map Options.
        facts = self._slot_facts(self.origin_var.get())
        found = []
        if facts is not None:
            found = (star_limits.problems(facts, criteria["stars_by_slot"])
                     + star_limits.roll_problems(facts, criteria["tiers_by_slot"])
                     + background_limits.problems(facts, criteria["backgrounds_by_slot"], self._background_names()))
        if criteria.get("map"):
            found += map_conditions.problems(criteria["map"], map_options)
        if found:
            if not messagebox.askyesno(
                    "Impossible conditions",
                    f"No seed can match these conditions for {self.origin_var.get()}:\n\n"
                    + "\n".join(f"  • {p}" for p in found) + "\n\nSearch?"):
                return
        # Without the game's facts: hardcoded-stars unsatisfiability from the built-in table (the Gladiators-bear case).
        if facts is None and self._legends():
            conflicts = origin_conflicts(self.origin_var.get(), criteria["stars_by_slot"])
            if conflicts:
                lines = "\n".join(
                    f"  • Brother {slot} needs {need} {stat.upper()} stars or more. The origin sets {have}."
                    for slot, stat, need, have in conflicts
                )
                if not messagebox.askyesno(
                    "Impossible conditions",
                    f"{self.origin_var.get()} sets some stars lower than your conditions:\n\n"
                    f"{lines}\n\nNo seed can match. Search?",
                ):
                    return
        self._launch(criteria, numbers, seeds=None)

    def _on_check_seed(self):
        if self._searching or not self._have_game():
            return
        seed = self.check_seed_var.get().strip()
        if not 1 <= len(seed) <= 10:
            messagebox.showerror("Check a seed", "Write the seed as in the game: 1 to 10 characters.")
            return
        numbers, _errors = self._numbers()
        map_errors = self._map_setup()[2]
        if map_errors:          # a map condition makes the check build the map of the seed too
            messagebox.showerror("Check a seed", "\n".join(map_errors))
            return
        self._launch(self._gather_criteria(), numbers, seeds=[seed])

    def _launch(self, criteria, numbers, seeds):
        from bbseed.search import normalize, roster_conditions, search
        setup, origin = self.setup_var.get(), self.origin_var.get()
        profile = O.SETUPS[setup][0]
        scenario = O.SCENARIO[origin]
        workers = 1 if seeds else numbers[WORKERS] or default_workers()
        mod_settings = {"mod_legends:GenderEquality": self.sisters_var.get()} if self._legends() else None
        map_criteria = criteria.get("map")
        map_first = False
        if map_criteria:
            # The Map Options change the map and nothing else, so only a run with a map condition sends them
            # (a search for brothers alone must stay as it was). The workers report the values they used.
            options = self._map_setup()[1] or map_view.default_option_values()
            mod_settings = {**(mod_settings or {}), **map_view.mod_settings(options)}
            try:        # no brother condition: the map is built for every seed (the estimate waits for maps)
                map_first = not roster_conditions(normalize(criteria))
            except ValueError:
                pass
        self._run = {"setup": setup, "origin": origin, "checking": bool(seeds), "map": map_criteria,
                     "map_first": map_first, "north_band": (map_criteria or {}).get("north_band")}
        self._search_total = len(seeds) if seeds else numbers[SEEDS_TO_TEST]
        self._stop.clear()
        self._searching = True
        self._save_settings()
        if self._notice_action != self._on_remove_old_mod:      # that warning stays until it is handled
            self._clear_notice()
        self.search_btn.configure(state="disabled")
        self.check_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_watch_state("waiting")
        self.watch_var.set(f"Loading the game scripts in {workers} worker{'' if workers == 1 else 's'}")
        self.status_var.set((f"Checking seed {seeds[0]}." if seeds else
                             f"Searching {origin} ({setup}): a maximum of {self._search_total:,} seeds.")
                            + (f" {map_view.WAIT}" if map_criteria else ""))
        put = self._events.put

        def run():
            try:
                search(profile, scenario, criteria, workers=workers, count=numbers[MATCHES_TO_FIND] or 1,
                       max_seeds=None if seeds else numbers[SEEDS_TO_TEST], seeds=seeds,
                       mod_settings=mod_settings,
                       on_event=lambda kind, payload: put((kind, payload)), should_stop=self._stop.is_set)
            except Exception as e:      # report instead of dying silently in the thread
                put(("fatal", f"{type(e).__name__}: {e}"))
                put(("finished", (0, 0.0, 0, True)))

        threading.Thread(target=run, daemon=True).start()

    def _on_stop(self):
        self._stop.set()
        self.status_var.set("Stopping.")

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
        self.watch_var.set(f"Reading the game scripts (one time only): {done:,} of {total:,}")

    def _ev_ready(self, payload):
        ready, total, info = payload
        self.watch_var.set(f"Loading: {ready} of {total} workers are ready")
        legends = info.get("legends_version")
        self._run["ready"] = ready              # a fatal after this is not "cannot start"
        self._report_info = {
            "version": legends or f"Vanilla {info.get('game_version')}",
            "build_name": info.get("legends_build") if legends else None,
            "battle_sisters": info.get("battle_sisters") if legends else "n/a (no Legends)",
            "origin": self._run["origin"],
            # the Map Options the workers used: they are part of the post only for a run with map conditions
            # (a roster does not depend on them; a post for a roster alone says "any")
            "map_options": dict(info.get("map_options") or {}) if self._run.get("map") else {},
            "game_version": info.get("game_version"),
            "mods": info.get("mods") or [],
        }
        if legends:
            self._map_versions = (info.get("game_version"), legends)
            if info.get("mods") is not None:
                self._map_mods = info["mods"]
            self._apply_map_state()

    def _ev_progress(self, payload):
        from bbseed.search import MAP_NEVER_MAPS
        tested, secs, _found = payload[:3]
        odds = payload[3] if len(payload) > 3 else {}
        self._set_watch_state("running")
        rate = tested / secs if secs > 0 else 0.0
        eta = ""
        if rate > 0 and self._search_total > tested and not self._run["checking"]:
            eta = f", {self._fmt_duration((self._search_total - tested) / rate)} or less to go"
        self.watch_var.set(f"Searching: {tested:,} of {self._search_total:,} seeds, "
                           f"{map_view.rate_text(rate)}/s{eta}")
        if self._run["checking"]:
            return
        hint = self._odds_text(odds, rate)
        if hint:
            self.status_var.set(hint)
            self._run["odds_text"] = hint
        elif self._wait_text(odds):         # the first maps are still being built
            self.status_var.set(self._wait_text(odds))
        never = odds.get("never") or []
        self._run["never"] = never
        if never and odds.get("tested", 0) >= 300 and not self._run.get("warned_never"):
            self._run["warned_never"] = True
            who = ", ".join(str(n) for n in never)
            self._show_notice(f"Brother {who} did not match the conditions in {odds['tested']:,} seeds. "
                              f"Possibly no seed matches. Use easier conditions for "
                              f"{'this brother' if len(never) == 1 else 'these brothers'}.", kind="info")
        elif odds.get("never_any") and odds.get("tested", 0) >= 300 and not self._run.get("warned_never"):
            self._run["warned_never"] = True
            self._show_notice(f"No brother had the background of row Any brother in {odds['tested']:,} seeds. "
                              f"Possibly no seed matches. Select a different background.", kind="info")
        elif odds.get("never_map") and odds.get("maps", 0) >= MAP_NEVER_MAPS and not self._run.get("warned_never"):
            # valid conditions can be rare (6 ports: 4 % of the maps): this is no sign that no seed matches
            self._run["warned_never"] = True
            self._show_notice(f"No map met the map conditions in {odds['maps']:,} maps. Maps like this are rare. "
                              f"The search continues.", kind="info")
        self._run["never_map"] = bool(odds.get("never_map"))

    def _wait_text(self, odds):
        """The note while the first maps are built (a map takes about 40 seconds); "" for other runs."""
        return map_view.wait_note(odds) if self._run.get("map") else ""

    def _odds_text(self, odds, rate):
        """'Approximately 1 in 3,400 seeds matches (...). At this speed, that is 1 match in ...' (or nothing).
        With map conditions it waits for maps, not for seeds, and "chance" can be None until a map is built."""
        chance, tested, maps = odds.get("chance"), odds.get("tested", 0), odds.get("maps", 0)
        map_run = bool(self._run.get("map"))
        if not chance or not map_view.estimate_ready(odds, map_run, self._run.get("map_first", False)):
            # brother and map conditions: until enough maps are built, the rate of the brothers alone
            return map_view.brother_estimate(odds, map_run, self._run.get("map_first", False))
        one_in = 1 / chance
        basis = f"{tested:,} seeds, {maps:,} maps" if map_run else f"{tested:,} seeds"
        text = f"Approximately 1 in {one_in:,.0f} seeds matches (from {basis})."
        if rate > 0:
            text += f" At this speed, that is 1 match in approximately {self._fmt_duration(one_in / rate)}."
        return text

    def _ev_match(self, payload):
        # the same seed found or checked again replaces its earlier entry
        self._matches = [m for m in self._matches if not (
            m["seed"] == payload["seed"] and m["origin"] == self._run["origin"] and m["setup"] == self._run["setup"])]
        entry = dict(payload, ts=time.time(), origin=self._run["origin"], setup=self._run["setup"],
                     checked=self._run["checking"], info=dict(self._report_info),
                     north_band=self._run.get("north_band"))     # the band of this run: the map's ports count by it
        self._matches.insert(0, entry)
        self._render_match_list()
        self.match_pane.grid()
        if not entry["checked"]:
            self._surface_window()   # pull the window to front so the match is seen
            if notification:
                try:
                    notification.notify(title="BB Reroll: match",
                                        message=f"Seed {entry['seed']} matches ({entry['origin']}).", timeout=10)
                except Exception:
                    pass

    def _ev_error(self, payload):
        self._run["errors"] = self._run.get("errors", 0) + 1
        if self._run["errors"] == 1:        # show the first one; a count follows when the run ends
            self._show_notice(f"BB Reroll cannot test a seed: {payload[:300]}", kind="warn")

    def _ev_fatal(self, payload):
        """A worker ended with an error. The first one of a run is the notice (each worker reports the same
        error), and the red banner stays: search() sends "finished" after a fatal too. Before the workers
        are ready the search could not start. After that one search process stopped, and the others go on:
        search() ends the whole run only for a map fatal. A map fatal always counts, also after another fatal:
        it turns map conditions off until the player changes a Map Option, the setup or the game folder
        (_lift_map_lockout); the search for brothers alone works without them."""
        from bbseed.search import MAP_FATAL
        text = str(payload)
        if text.startswith(MAP_FATAL):
            if self._run.get("map_fatal"):
                return
            self._run["map_fatal"] = True
            self._run["fatal"] = self._run.get("fatal") or text
            self._map_off = True
            self._apply_map_state()
            self._map_fatal_notice = f"{text[:400]} {map_view.MAP_FATAL_ADVICE}"
            self._show_notice(self._map_fatal_notice, kind="error")
            return
        if self._run.get("fatal"):
            return
        self._run["fatal"] = text
        who = "A search process stopped" if self._run.get("ready") else "The search cannot start"
        self._show_notice(f"{who}: {text[:400]}", kind="error")

    def _ev_finished(self, payload):
        tested, secs, found, stopped = payload
        self._searching = False
        self.search_btn.configure(state="normal")
        self.check_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._set_watch_state("idle")
        self.watch_var.set("Idle")
        failed = bool(self._run.get("fatal"))       # the banner of the fatal stays; no "No seed matched" over it
        # a map fatal ended the run; after another fatal the other workers may have gone on to the end
        verb = "Stopped" if stopped or self._run.get("map_fatal") else "Search ended" if failed else "Search complete"
        if self._run["checking"]:
            self.status_var.set("The seed check is complete. See the results." if not failed else
                                "The seed check stopped.")
        else:
            errors = self._run.get("errors", 0)
            self.status_var.set(
                f"{verb}: {tested:,} seed{'' if tested == 1 else 's'} tested "
                f"in {self._fmt_duration(secs)}, {found} match{'' if found == 1 else 'es'}"
                f"{f', {errors} could not be tested' if errors else ''}."
                + (f" {self._run['odds_text']}" if not found and self._run.get("odds_text") else ""))
            if not found and not stopped and not failed and tested:
                never = self._run.get("never") or []
                if never:
                    who = ", ".join(str(n) for n in never)
                    self._show_notice(f"No seed matched in {tested:,} seeds. Brother {who} never matched the "
                                      f"conditions. Use easier conditions for "
                                      f"{'this brother' if len(never) == 1 else 'these brothers'}.", kind="info")
                elif self._run.get("never_map"):
                    self._show_notice(f"No seed matched in {tested:,} seeds. No map met the map conditions. "
                                      f"Use easier map conditions.", kind="info")
                else:
                    self._show_notice(f"No seed matched in {tested:,} seeds. Use easier conditions or test more "
                                      f"seeds.", kind="info")
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
        # the results row stretches only while it is shown (an empty row with weight takes space too).
        # When the window is too short for everything, grid takes the missing height from the rows
        # with weight, in proportion to it: the traits row (weight 4) gives up most of it, down to its
        # title line — Clear gives it back — so the results keep a usable list.
        shown = bool(self._matches)
        self.grid_rowconfigure(3, weight=4 if shown else 1, minsize=60 if shown else 170)
        self.grid_rowconfigure(5, weight=1 if shown else 0)
        if not self._matches:
            self.match_pane.grid_remove()
            return
        # as tall as its content needs, up to a limit (it scrolls beyond that)
        wanted = sum(64 + 16 * len(m["roster"]) * (6 if m.get("show_perks") else 1) for m in self._matches)
        self.match_list.configure(height=max(90, min(300, wanted)))
        for entry in self._matches:
            ok = entry.get("failure") is None
            card = ctk.CTkFrame(self.match_list, corner_radius=8, border_width=1,
                                fg_color=PALETTE["card"] if ok else PALETTE["card_other"],
                                border_color=PALETTE["card_border"] if ok else PALETTE["card_other_border"])
            card.pack(fill="x", padx=2, pady=3)
            card.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(card, text=f"Seed {entry['seed']}", font=(FONT, 14, "bold"), text_color=PALETTE["text"]).grid(
                row=0, column=0, sticky="w", padx=(12, 8), pady=(8, 0))
            sub = f"{entry['origin']} · {entry['setup']}"
            if entry.get("checked"):
                sub += ("  ·  Checked: matches the conditions" if ok else
                        "  ·  Checked: " + explain_failure(entry["failure"], self._display_for,
                                                           self._background_names()))
            ctk.CTkLabel(card, text=sub, font=(FONT, 12), text_color=PALETTE["muted"] if ok else PALETTE["bad"],
                         anchor="w").grid(row=0, column=1, sticky="w", pady=(8, 0))
            buttons = ctk.CTkFrame(card, fg_color="transparent")
            buttons.grid(row=0, column=2, sticky="e", padx=(4, 8), pady=(8, 0))
            _button(buttons, "Copy seed", lambda s=entry["seed"]: self._copy_to_clipboard(s), width=84, height=26,
                    font=(FONT, 11)).pack(side="left", padx=2)
            _button(buttons, "Copy roster", lambda e=entry: self._copy_roster(e), width=90, height=26,
                    font=(FONT, 11)).pack(side="left", padx=2)
            share_btn = _button(buttons, "Copy seed post", lambda e=entry: self._copy_seed_share(e), width=108,
                                height=26, font=(FONT, 11))
            share_btn.pack(side="left", padx=2)
            _attach_tooltip(share_btn, "Copy a seed post for the Legends Discord to the clipboard.")
            has_details = any(b.get("perk_groups") or b.get("rolls") for b in entry["roster"])
            if has_details:
                details = _button(buttons, "Hide details" if entry.get("show_perks") else "Details",
                                  lambda e=entry: self._toggle_perks(e), width=92, height=26, font=(FONT, 11))
                details.pack(side="left", padx=2)
                _attach_tooltip(details, "Show the stat rolls of each brother and, with Legends, his perk trees.")
            if entry.get("map"):
                map_btn = _button(buttons, "Show map", lambda e=entry: self._show_map(e), width=84, height=26,
                                  font=(FONT, 11))
                map_btn.pack(side="left", padx=2)
                _attach_tooltip(map_btn, "Show the world map of this seed with its towns and ports. North is at the top.")
            remove = _button(buttons, "✕", lambda e=entry: self._dismiss_match(e), kind="ghost", width=28, height=26,
                             font=(FONT, 11))
            remove.pack(side="left", padx=(6, 0))
            _attach_tooltip(remove, "Remove this result from the list.")
            if not entry.get("stable", True):
                ctk.CTkLabel(card, text="⚠ This result is not stable. Do not use it.", font=(FONT, 12, "bold"),
                             text_color=PALETTE["bad"]).grid(row=1, column=0, columnspan=3, sticky="w", padx=12)
            ctk.CTkLabel(card, text="\n".join(roster_lines(entry["roster"])), font=("Consolas", 11), justify="left",
                         anchor="w", text_color=PALETTE["text"]).grid(row=2, column=0, columnspan=3, sticky="w",
                                                                      padx=12, pady=(4, 10))
            if has_details and entry.get("show_perks"):
                lines = []
                for i, b in enumerate(entry["roster"], 1):
                    lines.append(f"{i:2d}. {b['name']}. Rolls: {roll_text(b) or 'not known'}")
                    if perk_text(b):
                        lines.append(f"      Perk trees: {perk_text(b)}")
                ctk.CTkLabel(card, text="\n".join(lines), font=(FONT, 11), justify="left", anchor="w", wraplength=880,
                             text_color=PALETTE["muted"]).grid(row=3, column=0, columnspan=3, sticky="w",
                                                               padx=12, pady=(0, 10))

    def _show_map(self, entry: dict, screen_height=None):
        """The map of a result in a window of its own. A second click on the same result brings its window
        forward; a closed window leaves nothing behind (App._map_windows forgets it)."""
        if not entry.get("map"):
            return
        try:        # a new match keeps the main window topmost for 1.5 s (_surface_window): it would cover the map
            self.attributes("-topmost", False)
        except Exception:
            pass
        key = (entry["setup"], entry["origin"], entry["seed"])
        window = self._map_windows.get(key)
        try:
            if window is not None and window.winfo_exists():
                # The map depends on the Map Options and the picture on the north band, so the same seed found
                # again can have another map: the window of the old one is not brought forward but replaced.
                if window.summary is entry["map"] and window.band == entry.get("north_band"):
                    window.bring_forward()
                    return
                window.destroy()
        except Exception:
            pass
        self._map_windows.pop(key, None)
        try:
            self._map_windows[key] = _MapWindow(self, key, entry, screen_height=screen_height)
        except Exception as e:      # a damaged map: no half-built window stays open
            known = list(self._map_windows.values())
            for child in self.winfo_children():
                if isinstance(child, _MapWindow) and child not in known:
                    child.destroy()
            self.status_var.set(f"Cannot draw the map: {type(e).__name__}: {e}")

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
            self.status_var.set(label or f"Seed {text} is copied.")
        except Exception as e:
            self.status_var.set(f"Cannot copy: {e}")

    def _copy_roster(self, entry: dict):
        from bbseed.lab import describe
        text = f"Seed {entry['seed']} — {entry['origin']} — {entry['setup']}\n"
        text += "\n".join(f"{i}. {describe(b)}" for i, b in enumerate(entry["roster"], 1))
        self._copy_to_clipboard(text, label=f"The roster of seed {entry['seed']} is copied.")

    def _share_report(self, entry: dict) -> str:
        return build_seed_report(
            origin=entry["origin"],
            description=self.share_desc_var.get().strip(),
            seed=entry["seed"],
            report_info=entry.get("info") or self._report_info,
            tool_version=APP_VERSION,
            roster=entry.get("roster"),
            game_map=entry.get("map") or None,      # None, never {}: a post without a map stays as it was
            north_band=entry.get("north_band") or map_view.DEFAULT_NORTH_BAND,
        )

    def _copy_seed_share(self, entry: dict):
        self._copy_to_clipboard(self._share_report(entry), label=f"The seed post for seed {entry['seed']} is copied.")

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
        self._restore_map_values(data)
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
            criteria = self._gather_criteria()
            criteria.pop("map", None)       # the Map view's values are saved as typed, below
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
                "criteria":          criteria,
                **map_view.to_settings({k: v.get() for k, v in self.map_vars.items()},
                                       {k: v.get() for k, v in self.map_option_vars.items()},
                                       read=self._options_read),
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
                if (slot, stat) not in self._locked:
                    var.set(str(spec.get("stars", {}).get(slot, {}).get(stat, 0)))
            for (slot, stat), var in self.tiers_vars.items():
                var.set(spec.get("tiers", {}).get(slot, {}).get(stat, "any"))
            for slot, var in self.background_vars.items():
                wanted = spec.get("backgrounds", {}).get(slot)
                var.set(next((n for n, bid in self._background_ids[slot].items() if bid == wanted), self.ANY_BACKGROUND))
            if spec.get("grid"):
                self.grid_mode_var.set(spec["grid"])
                self._on_grid_mode()
            self.max_iters_var.set(str(spec.get("max_seeds", 2000)))
            self.sisters_var.set(spec.get("battle_sisters", O.BATTLE_SISTERS[1]))
            self.count_var.set(str(spec.get("count", 2)))
            self.workers_var.set(str(spec.get("workers", 4)))
            self.share_desc_var.set(spec.get("description", ""))
            # the Map view: the spec's conditions and Map Options, else the defaults (never the player's saved ones)
            self._set_map_fields(spec.get("map"), spec.get("map_options"))
            self._apply_map_state()
            if spec.get("search") is False:     # a picture of the window only: no search
                self.after(1000, lambda: self._selftest_done((0, 0.0, 0, False)))
            elif spec.get("check"):
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
        report = {
            "finished": list(payload), "status": self.status_var.get(), "notice": self.notice_var.get(),
            "title": self.title(), "setups": list(O.SETUPS),
            "catalog": self._catalog() is not None, "origin_info": self.origin_info_var.get(),
            "tooltips": {t: self._trait_tooltip(t) for t in spec.get("tooltips", [])},
            "stars": {f"{slot}:{stat}": v.get() for (slot, stat), v in self.stars_vars.items() if v.get() != "0"},
            "cells": {f"{slot}:{stat}": len(w.cget("values")) - 1 for (slot, stat), w in self.stars_widgets.items()},
            "backgrounds": {slot: len(ids) for slot, ids in self._background_ids.items()},
            "criteria": self._gather_criteria(),
            "map_note": self.map_note_var.get(),
            "matches": [{"seed": m["seed"], "origin": m["origin"], "stable": m["stable"], "failure": m["failure"],
                         "checked": m["checked"], "lines": roster_lines(m["roster"]),
                         "map": map_conditions.map_line(m["map"], m.get("north_band") or map_view.DEFAULT_NORTH_BAND)
                                if m.get("map") else None} for m in self._matches],
            "share": None if not self._matches else self._share_report(self._matches[0]),
        }
        Path(spec["out"]).write_text(json.dumps(report, indent=2), encoding="utf-8")
        if spec.get("screenshot"):          # a picture of the window, to check the layout unattended
            self._grab(self, spec["screenshot"])
        shown = next((m for m in self._matches if m.get("map")), None) if spec.get("show_map") else None
        if shown is not None:               # the map window of the first result with a map, in a second picture
            try:
                self._show_map(shown)
                window = self._map_windows[(shown["setup"], shown["origin"], shown["seed"])]
                self.update()
                report["map_window"] = {"title": window.title(), "scale": window.scale, "info": window.info_var.get(),
                                        "canvas": [int(window.canvas.cget("width")), int(window.canvas.cget("height"))],
                                        "items": len(window.canvas.find_all())}
                Path(spec["out"]).write_text(json.dumps(report, indent=2), encoding="utf-8")
                if spec.get("screenshot"):
                    shot = Path(spec["screenshot"])
                    self._grab(window, str(shot.with_name(shot.stem + "_map" + shot.suffix)))
            except Exception as e:
                report["map_window"] = {"error": f"{type(e).__name__}: {e}"}
                Path(spec["out"]).write_text(json.dumps(report, indent=2), encoding="utf-8")
        if spec.get("close_after") is not None:
            self.after(int(spec["close_after"] * 1000), self.destroy)

    def _grab(self, window, path):
        """A picture of `window` from the screen (needs Pillow). The picture is of the screen, so the window
        must be on top: the player's own BB Reroll window can be open at the same place."""
        try:
            from PIL import ImageGrab
            window.deiconify()
            window.lift()
            window.attributes("-topmost", True)
            window.update()
            time.sleep(0.4)
            window.update()
            x, y = window.winfo_rootx(), window.winfo_rooty()
            box = (x, y, x + window.winfo_width(), y + window.winfo_height())
            try:        # this process is not DPI aware (see main): Tk's pixels are scaled screen pixels
                import ctypes
                scale = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
            except Exception:
                scale = 1.0
            ImageGrab.grab(bbox=tuple(int(v * scale) for v in box)).save(path)
        except Exception:
            pass


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

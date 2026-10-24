"""The window's Search and Show roster buttons really start a search with the settings in the
fields. A real App is built (hidden) with a stand-in for the search itself, so no game is
needed. Guards against a renamed field breaking the search start silently (2026-10-15: the
"Seeds to test" label rename left the start looking up "Max seeds" — Search did nothing)."""
import time
from pathlib import Path

import pytest

ctk = pytest.importorskip("customtkinter")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """One window for the whole file: Tk on Windows does not always start a second interpreter
    in the same process."""
    import gui
    from bbreroll import offline_origins as O
    from bbseed import profiles

    found = {"data": Path("X:/Battle Brothers/data"), "game_version": "1.5.2.3", "mods": ["mod_legends.zip"],
             "legends": True, "reroll_mod": [], "dlc_complete": True}
    mp = pytest.MonkeyPatch()
    mp.setattr(profiles, "installed_summary", lambda game_data=None: found)
    mp.setattr(gui, "SETTINGS_PATH", tmp_path_factory.mktemp("gui") / "settings.json")
    mp.setattr(gui.App, "_ensure_catalog", lambda self: None)       # no game, no catalog
    mp.setattr(gui.msu_settings, "read_map_options", lambda path=None: None)   # no test reads the player's file
    mp.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    errors = []
    mp.setattr(gui.messagebox, "showerror", lambda *a, **k: errors.append(a))
    O.refresh()
    try:
        window = gui.App()
    except Exception as e:
        mp.undo()
        O.refresh()
        import tkinter as tk
        if isinstance(e, tk.TclError):  # no display at all; any other error is a bug and must fail the tests
            pytest.skip("no display: %s" % e)
        raise
    window.withdraw()
    window.errors = errors
    yield window
    window.destroy()
    mp.undo()
    O.refresh()


@pytest.fixture()
def calls(monkeypatch):
    import bbseed.search
    seen = []

    def fake_search(profile, origin, criteria, **kw):
        seen.append(dict(kw, profile=profile, origin=origin, criteria=criteria))
        kw["on_event"]("finished", (0, 0.0, 0, False))
        return []
    monkeypatch.setattr(bbseed.search, "search", fake_search)
    return seen


def pump(app, until, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end and not until():
        app.update()
        time.sleep(0.02)


def test_search_starts_with_the_numbers_in_the_fields(app, calls):
    app.errors.clear()
    app.origin_var.set("Trading Caravan")
    app._on_origin_change("Trading Caravan")
    app.max_iters_var.set("1234")
    app.count_var.set("3")
    app.workers_var.set("2")
    app.stars_vars[("1", "res")].set("2")
    app._on_search()
    pump(app, lambda: calls and not app._searching)
    assert app.errors == []
    assert len(calls) == 1, "Search must start a search"
    call = calls[0]
    assert call["origin"] == "trader_scenario" and call["profile"] == "legends"
    assert call["max_seeds"] == 1234 and call["count"] == 3 and call["workers"] == 2
    assert call["criteria"]["stars_by_slot"]["1"] == {"res": 2}


def test_show_roster_checks_one_seed(app, calls):
    app.check_seed_var.set("1234567890")
    app._on_check_seed()
    pump(app, lambda: calls and not app._searching)
    assert len(calls) == 1 and calls[0]["seeds"] == ["1234567890"] and calls[0]["max_seeds"] is None


def test_cells_turn_grey_when_a_brothers_random_stars_are_all_asked_for(app):
    # Berserker: HP 3 and MSK 3 fixed, then the roll stars 2 more stats (catalog facts of Legends 19.4.22)
    every = {s: 3 for s in ("hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf")}
    facts = {"most": 4, "least": 4, "picks": 2, "max": every, "fixed": {"hp": 3, "msk": 3},
             "rolled": ["fat", "res", "init", "rsk", "mdf", "rdf"], "varied": False,
             "spread": list(every)}
    app._catalogs["legends"] = {"talents": {"legends_berserker_scenario": {"slots": [facts], "sizes": [1]}}}
    app.origin_var.set("Berserker")
    app._on_origin_change("Berserker")
    state = lambda stat: app.stars_widgets[("1", stat)].cget("state")
    assert state("hp") == "disabled" and state("msk") == "disabled"         # fixed: locked
    assert state("fat") == "normal" and state("init") == "normal"
    app.stars_vars[("1", "fat")].set("1")
    assert state("init") == "normal", "one random star used, one left"
    app.stars_vars[("1", "res")].set("2")
    assert [state(s) for s in ("init", "rsk", "mdf", "rdf")] == ["disabled"] * 4
    assert state("fat") == "normal" and state("res") == "normal", "the asked cells stay open"
    # each reason for a closed cell has its own look
    import gui
    face = lambda stat: app.stars_widgets[("1", stat)].cget("fg_color")
    assert face("hp") == gui.PALETTE["fixed"] and face("init") == gui.PALETTE["full"]
    app.stars_vars[("1", "res")].set("0")
    assert [state(s) for s in ("init", "rsk", "mdf", "rdf")] == ["normal"] * 4
    assert face("init") == gui.PALETTE["control"] and face("hp") == gui.PALETTE["fixed"]
    # row All is shared by brothers with different numbers of random stars: it stays open
    for stat in ("fat", "res", "init"):
        app.stars_vars[("*", stat)].set("1")
    assert app.stars_widgets[("*", "rdf")].cget("state") == "normal"


def test_a_fixed_star_is_locked_and_no_condition(app, calls):
    # Trading Caravan's brother 2 has HP 1, MSK 2, MDF 1 on every seed (built-in table until the catalog)
    app.origin_var.set("Trading Caravan")
    app._on_origin_change("Trading Caravan")
    assert app.stars_widgets[("2", "msk")].cget("state") == "disabled"
    assert app.stars_vars[("2", "msk")].get() == "2"
    app.stars_vars[("*", "res")].set("1")
    criteria = app._gather_criteria()
    assert "2" not in criteria["stars_by_slot"], "a locked row must not replace row All"


def test_the_last_result_can_be_scrolled_into_view(app):
    # 2026-10-15: in a 980x940 window the result list ran past the bottom of the window, so
    # scrolling to its end showed nothing; the last of three seeds could not be seen
    app._catalogs.pop("legends", None)
    app.origin_var.set("The Free Company")
    app._on_origin_change("The Free Company")
    app.deiconify()
    app.geometry("980x940+40+40")
    roster = [{"name": "Bro %d" % i, "background": "background.sellsword", "background_name": "Sellsword",
               "stars": {"hp": 1}, "trait_names": [], "traits": []} for i in range(5)]
    try:
        for n in range(3):
            app._run = {"origin": "The Free Company", "setup": "Legends", "checking": True}
            app._ev_match({"seed": "000000000%d" % n, "roster": roster, "stable": True, "failure": None})
        pump(app, lambda: False, 1.0)
        canvas = app.match_list._parent_canvas
        canvas.yview_moveto(1.0)
        pump(app, lambda: False, 0.3)
        bottom = lambda w: w.winfo_rooty() + w.winfo_height()
        window = bottom(app)
        last = app.match_list.winfo_children()[-1]
        assert bottom(canvas) <= window, "the list must end inside the window"
        assert bottom(last) <= bottom(canvas) + 2, "scrolled to the end, the last result is in view"
        assert canvas.winfo_height() >= 60, "the list keeps a usable height"
    finally:
        app._clear_matches()
        app.withdraw()


# ====================================================================== the Map view
# The map conditions, the Map Options, the card's "Show map" button and its window. The stand-in search is the
# same; nothing here needs the game.

def small_map(w=30, h=40):
    """A hand-made map summary: land in the south, sea in the north, a southern port, a northern port and a fort."""
    def town(x, y, **kw):
        base = {"name": "Town %d/%d" % (x, y), "script": "small_farming_village", "size": 2, "x": x, "y": y,
                "southern": False, "military": False, "port": False, "faction": None}
        return dict(base, **kw)
    return {"size": [w, h], "layout": "even-q-up", "attempts": 1,
            "terrain": "L" * (w * (h // 2)) + "O" * (w * (h - h // 2)),
            "towns": [town(3, 2, port=True, southern=True, size=3, script="city_state"), town(20, h - 3, port=True),
                      town(10, 20, military=True, script="legends_fort")]}


@pytest.fixture()
def map_app(app):
    """The window on Legends with an empty Map view and no conditions; whatever a test does is undone."""
    from bbreroll import map_view

    def reset():
        app._map_off = False
        app._options_note = None
        app._options_read = None
        app._map_versions = (None, None)
        app._map_mods = None
        if app.setup_var.get() != "Legends":        # (rebuilding the grids takes a second: only when needed)
            app.setup_var.set("Legends")
            app._on_setup_change()
        if app.origin_var.get() != "Trading Caravan":
            app.origin_var.set("Trading Caravan")
            app._on_origin_change("Trading Caravan")
        conditions, options = map_view.default_conditions(), map_view.default_options()
        for key, var in app.map_vars.items():
            var.set(conditions[key])
        for key, var in app.map_option_vars.items():
            var.set(options[key])
        for key, var in app.stars_vars.items():
            if key not in app._locked:
                var.set("0")
        app.share_desc_var.set("")
        app.grid_mode_var.set("Stars")
        app._on_grid_mode()
        app._apply_map_state()
        for window in list(app._map_windows.values()):
            window.destroy()
        app._map_windows.clear()
        app._matches.clear()
        app._clear_notice()
        app._dismissed_notices.clear()
        app._bulk_check("banned", True)
        app._bulk_check("required", True)
        app._searching = False
    reset()
    app.errors.clear()
    yield app
    reset()
    app.errors.clear()


def asked(monkeypatch, answer=True):
    """Record the yes / no dialogs: [(title, message)]; they answer `answer`."""
    import gui
    seen = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda title, message, **k: seen.append((title, message)) or answer)
    return seen


def search_now(app, calls):
    """Press Search; the searches the stand-in saw since."""
    before = len(calls)
    app._on_search()
    if app._searching:
        pump(app, lambda: not app._searching, 3.0)
    return calls[before:]


MAP_OPTION_KEYS = ["LandRatio", "Water", "Snowline", "Settlements", "Factions", "StackCitadels", "AllTradeLocations"]
RUN = {"origin": "Trading Caravan", "setup": "Legends", "checking": False}


def test_map_view_builds_map_criteria(map_app, calls):
    app = map_app
    app.grid_mode_var.set("Map")
    app._on_grid_mode()
    app.map_vars["ports"].set("6")
    app.map_vars["north_band"].set("33")
    app.map_vars["city_state"].set("2")
    (call,) = search_now(app, calls)
    assert call["criteria"]["map"] == {"ports": 6, "ports_south": 0, "ports_north": 0, "north_band": 33,
                                       "towns": {"city_state": 2}}
    assert "stars_by_slot" in call["criteria"], "the conditions of the other views are still there"


def test_the_map_view_replaces_the_stars_grid_and_has_its_own_title(map_app):
    app = map_app
    assert "Map" in app.grid_switch.cget("values")
    app.grid_mode_var.set("Map")
    app._on_grid_mode()
    assert app.grid_title.cget("text") == "MAP"
    shown = lambda widget: bool(widget.grid_info())
    assert shown(app.map_frame) and not shown(app.stars_frame) and not shown(app.tiers_frame)
    assert not shown(app.origin_info_label) and not shown(app.stars_legend)
    assert app.grid_help.cget("text").startswith("Set the minimum number of ports and towns.")
    app.grid_mode_var.set("Stars")
    app._on_grid_mode()
    assert shown(app.stars_frame) and not shown(app.map_frame)


def test_the_map_view_has_a_field_for_everything(map_app):
    from bbreroll import map_view
    app = map_app
    assert set(app.map_vars) == set(map_view.default_conditions())
    assert list(app.map_option_vars) == MAP_OPTION_KEYS
    assert {k: v.get() for k, v in app.map_option_vars.items()} == map_view.default_options()
    assert list(map_view.TOWN_LABELS.values()) == ["City states", "Strongholds", "Villages", "Towns", "Cities"]


def test_map_options_reach_the_search_as_exactly_seven_keys_only_with_a_map_condition(map_app, calls):
    app = map_app
    app.map_option_vars["Settlements"].set("24")
    app.map_option_vars["StackCitadels"].set("Yes")
    # no map condition: a search for brothers alone stays exactly as it was
    (roster_only,) = search_now(app, calls)
    assert roster_only["mod_settings"] == {"mod_legends:GenderEquality": "Enabled"}
    assert "map" not in roster_only["criteria"]
    # a map condition: the seven Map Options go along, with what the player typed
    app.map_vars["ports"].set("2")
    (with_map,) = search_now(app, calls)
    settings = with_map["mod_settings"]
    assert sorted(k for k in settings if k != "mod_legends:GenderEquality") == sorted("mod_legends:" + k
                                                                                      for k in MAP_OPTION_KEYS)
    assert settings["mod_legends:GenderEquality"] == "Enabled"
    assert settings["mod_legends:Settlements"] == 24 and settings["mod_legends:StackCitadels"] is True
    assert settings["mod_legends:LandRatio"] == 50 and settings["mod_legends:AllTradeLocations"] is False


def test_show_roster_with_a_map_condition_builds_the_map_with_the_same_options(map_app, calls):
    app = map_app
    app.map_vars["ports"].set("2")
    app.map_option_vars["Factions"].set("5")
    app.check_seed_var.set("1234567890")
    app._on_check_seed()
    pump(app, lambda: calls and not app._searching)
    assert calls[0]["criteria"]["map"]["ports"] == 2 and calls[0]["mod_settings"]["mod_legends:Factions"] == 5


def test_a_map_condition_alone_is_not_a_search_without_conditions(map_app, calls, monkeypatch):
    app = map_app
    app._bulk_check("banned", False)
    app._bulk_check("required", False)
    seen = asked(monkeypatch)
    search_now(app, calls)
    assert [t for t, _m in seen] == ["No conditions"], "nothing asked for: every seed matches"
    seen.clear()
    app.map_vars["ports"].set("3")
    assert len(search_now(app, calls)) == 1
    assert [t for t, _m in seen] == [], "a map condition is a condition"


def test_impossible_map_conditions_block_the_search(map_app, calls, monkeypatch):
    app = map_app
    app.map_vars["ports"].set("6")
    app.map_vars["ports_south"].set("5")
    app.map_vars["ports_north"].set("5")
    seen = asked(monkeypatch, answer=False)
    assert search_now(app, calls) == []
    (title, message), = seen
    assert title == "Impossible conditions"
    assert "Southern ports: a map has a maximum of 3 with these Map Options. Your condition is 5." in message
    assert "Ports: southern and northern ports are also ports. Set ports to 10 or more. Your condition is 6." in message
    asked(monkeypatch, answer=True)         # the player may search anyway (as with conditions for the brothers)
    assert len(search_now(app, calls)) == 1


def test_the_map_options_decide_what_is_impossible(map_app, calls, monkeypatch):
    app = map_app
    app.map_vars["military"].set("8")           # Strongholds: at most 6 with Settlements 19, 9 with 27
    seen = asked(monkeypatch, answer=False)
    assert search_now(app, calls) == []
    assert "Strongholds: a map has a maximum of 6 with these Map Options. Your condition is 8." in seen[0][1]
    app.map_option_vars["Settlements"].set("27")
    seen.clear()
    assert len(search_now(app, calls)) == 1 and seen == []


def test_numbers_that_are_not_numbers_stop_the_search_with_a_message(map_app, calls):
    app = map_app
    app.map_vars["ports"].set("many")
    assert search_now(app, calls) == []
    assert app.errors and "Ports must be a whole number of 0 or more." in app.errors[-1][1]
    app.errors.clear()
    app.map_vars["ports"].set("2")
    app.map_option_vars["Water"].set("99")
    assert search_now(app, calls) == []
    assert "Water must be a whole number from 28 to 42." in app.errors[-1][1]
    app.errors.clear()
    app.map_option_vars["Water"].set("40")
    assert len(search_now(app, calls)) == 1 and app.errors == []


def test_a_map_option_that_is_wrong_does_not_stop_a_search_for_brothers_alone(map_app, calls):
    app = map_app
    app.map_option_vars["Water"].set("99")
    assert len(search_now(app, calls)) == 1 and app.errors == []


# ---- the game version and the setups
def test_unverified_version_shows_the_note(map_app, monkeypatch):
    from bbreroll import map_view
    from bbreroll import offline_origins as O
    app = map_app
    monkeypatch.setitem(O.FOUND, "mods", ["mod_legends-19.5.0.zip", "mod_msu 479 1.9.0.zip"])
    app._apply_map_state()
    assert map_view.NOT_VERIFIED in app.map_note_var.get()
    assert app.map_note.grid_info()
    monkeypatch.setitem(O.FOUND, "mods", ["mod_legends-19.4.22.zip"])
    app._apply_map_state()
    assert app.map_note_var.get() == "" and not app.map_note.grid_info()
    monkeypatch.setitem(O.FOUND, "game_version", "1.5.3.0")
    app._apply_map_state()
    assert map_view.NOT_VERIFIED in app.map_note_var.get()


def test_the_versions_the_workers_report_decide_the_note(map_app, monkeypatch):
    from bbreroll import map_view
    from bbreroll import offline_origins as O
    app = map_app
    monkeypatch.setitem(O.FOUND, "mods", ["mod_legends-19.4.22.zip"])
    app._run = dict(RUN)
    app._ev_ready((1, 1, {"legends_version": "19.5.0", "game_version": "1.5.2.3", "map_options": {}}))
    assert map_view.NOT_VERIFIED in app.map_note_var.get()
    app._ev_ready((1, 1, {"legends_version": "19.4.22", "game_version": "1.5.2.3", "map_options": {}}))
    assert app.map_note_var.get() == ""


def test_map_view_opens_for_vanilla_with_all_dlc(map_app, calls):
    # the base game (all DLCs, no mod) has the condition fields; it has no Map Options, so they are not shown
    app = map_app
    app.map_vars["ports"].set("3")
    app.map_option_vars["Water"].set("abc")         # typed on Legends: the base game does not read it
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    assert app._map_widgets and all(str(w.cget("state")) == "normal" for w in app._map_widgets)
    bar, box = app._map_options_parts
    assert not bar.grid_info() and not box.grid_info(), "the base game shows no Map Options"
    assert app.map_note_var.get() == "", "all DLCs: verified, although the mod zip is on disk (it is not loaded)"
    (call,) = search_now(app, calls)
    assert call["criteria"]["map"]["ports"] == 3 and call["profile"] == "vanilla"
    assert call["mod_settings"] is None, "no Map Option reaches a base game lab"
    assert app.errors == [], "the Water typed for Legends is not checked for the base game"
    app.setup_var.set("Legends")
    app._on_setup_change()
    assert bar.grid_info() and box.grid_info(), "back on Legends the Map Options are shown again"
    assert app.map_vars["ports"].get() == "3", "the values stay"


def test_vanilla_without_all_dlc_closes_the_map_view(map_app, calls, monkeypatch):
    # Review Focus 4: a base game without every DLC has maps that the checks do not cover
    from bbreroll import map_view
    from bbreroll import offline_origins as O
    app = map_app
    monkeypatch.setitem(O.FOUND, "dlc_complete", False)
    app.map_vars["ports"].set("5")
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    assert app.map_note_var.get() == map_view.NEEDS_ALL_DLC
    assert app._map_widgets and all(str(w.cget("state")) == "disabled" for w in app._map_widgets)
    (call,) = search_now(app, calls)
    assert "map" not in call["criteria"], "what is left in the closed fields is no condition"
    assert call["mod_settings"] is None


def test_modded_closes_the_map_view(map_app, calls, monkeypatch):
    # Review Focus 4: mods without Legends have no map view (their maps are not checked)
    from bbreroll import map_view
    from bbreroll import offline_origins as O
    app = map_app
    monkeypatch.setitem(O.SETUPS, "Modded", ("modded", False))
    app.map_vars["ports"].set("5")
    app.setup_var.set("Modded")
    app._on_setup_change()
    assert app.map_note_var.get() == map_view.NEEDS_SETUP
    assert all(str(w.cget("state")) == "disabled" for w in app._map_widgets)
    bar, box = app._map_options_parts
    assert not bar.grid_info() and not box.grid_info()
    (call,) = search_now(app, calls)
    assert call["profile"] == "modded" and "map" not in call["criteria"]
    assert call["mod_settings"] is None


def test_vanilla_ignores_the_mods_and_legends_versions(map_app, monkeypatch):
    # the base game loads no mod zip: the mods on disk and the Legends versions of an earlier run do not count
    from bbreroll import map_view
    from bbreroll import offline_origins as O
    app = map_app
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    app._map_versions = ("1.5.2.3", "19.4.22")
    app._map_mods = [{"file": "mod_other.zip", "id": None, "name": "other", "version": None}]
    assert app._map_verified() is True
    app._apply_map_state()
    assert app.map_note_var.get() == ""
    monkeypatch.setitem(O.FOUND, "game_version", "1.5.3.0")
    app._map_versions = (None, None)
    assert app._map_verified() is False
    app._apply_map_state()
    assert map_view.NOT_VERIFIED in app.map_note_var.get()


def test_a_vanilla_map_fatal_says_start_the_program_again(map_app, calls):
    # the base game has no Map Option to change: the map fatal says to start the program again
    from bbreroll import map_view
    from bbseed.search import MAP_FATAL
    app = map_app
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    app.map_vars["ports"].set("3")
    app._run = dict(RUN, setup="Vanilla")
    app._searching = True
    app._ev_ready((1, 1, VANILLA_INFO))
    app._ev_fatal(MAP_FATAL + "KeyError: 'x' (seed 5)")
    app._ev_finished((0, 1.0, 0, False))
    assert app._map_off
    assert app.notice_var.get().endswith(map_view.MAP_FATAL_ADVICE_BASE)
    assert "Change a Map Option" not in app.notice_var.get()
    assert app.map_note_var.get() == map_view.TURNED_OFF_BASE
    assert "map" not in search_now(app, calls)[0]["criteria"], "a roster search goes on"


# ---- the settings file
def test_the_map_values_are_saved_and_restored(map_app):
    import json
    import gui
    app = map_app
    app.map_vars["ports"].set("5")
    app.map_vars["north_band"].set("45")
    app.map_vars["size3"].set("2")
    app.map_option_vars["Settlements"].set("23")
    app.map_option_vars["AllTradeLocations"].set("Yes")
    app._save_settings()
    data = json.loads(gui.SETTINGS_PATH.read_text(encoding="utf-8"))
    assert data["v"] == 4
    assert data["map"]["ports"] == "5" and data["map"]["north_band"] == "45" and data["map"]["size3"] == "2"
    assert data["map_options"]["Settlements"] == "23" and data["map_options"]["AllTradeLocations"] == "Yes"
    assert "map" not in data["criteria"], "the conditions of the Map view are saved once"
    for var in list(app.map_vars.values()) + list(app.map_option_vars.values()):
        var.set("7")
    app._restore_map_values(data)
    assert app.map_vars["ports"].get() == "5" and app.map_vars["north_band"].get() == "45"
    assert app.map_vars["size3"].get() == "2" and app.map_vars["ports_south"].get() == "0"
    assert app.map_option_vars["Settlements"].get() == "23" and app.map_option_vars["Water"].get() == "38"
    assert app.map_option_vars["AllTradeLocations"].get() == "Yes" and app.map_option_vars["StackCitadels"].get() == "No"


def test_a_settings_file_from_before_the_map_view_loads_with_the_defaults(map_app):
    app = map_app
    app.map_vars["ports"].set("5")
    app.map_option_vars["Water"].set("30")
    app._restore_map_values({"v": 4, "setup": "Legends", "criteria": {"stars_by_slot": {"*": {}}}})
    assert app.map_vars["ports"].get() == "0" and app.map_vars["north_band"].get() == "33"
    assert app.map_option_vars["Water"].get() == "38"


# ---- the saved Mod Options (the Map Options the player saved in the game's Mod Options, read from MSU's file)
def test_read_my_mod_options_fills_the_fields(map_app, monkeypatch):
    import gui
    from bbreroll import map_view
    app = map_app
    app.map_option_vars["Water"].set("40")                  # typed: the read sets it back to the saved value
    monkeypatch.setattr(gui.msu_settings, "read_map_options", lambda path=None: None)
    assert app._read_saved_options() is False
    assert map_view.NO_SAVED_OPTIONS in app.map_note_var.get(), "a read that finds no file says so"
    monkeypatch.setattr(gui.msu_settings, "read_map_options",
                        lambda path=None: {"Settlements": 24, "StackCitadels": True})
    assert app._read_saved_options() is True
    texts = {key: var.get() for key, var in app.map_option_vars.items()}
    assert texts["Settlements"] == "24" and texts["StackCitadels"] == "Yes"
    defaults = map_view.default_options()
    assert all(texts[key] == defaults[key] for key in texts if key not in ("Settlements", "StackCitadels")), \
        "the Map Options the file does not hold have Legends' defaults"
    assert texts["Water"] == defaults["Water"] == "38"
    assert app._options_read == texts
    assert map_view.NO_SAVED_OPTIONS not in app.map_note_var.get(), "a read that works takes the note away"
    assert app._options_note is None


def test_read_my_mod_options_without_file(map_app, monkeypatch):
    import gui
    from bbreroll import map_view
    app = map_app
    app.map_option_vars["Settlements"].set("23")
    monkeypatch.setattr(gui.msu_settings, "read_map_options", lambda path=None: None)
    assert app._read_saved_options() is False
    assert app.map_option_vars["Settlements"].get() == "23", "the fields stay as they are"
    assert map_view.NO_SAVED_OPTIONS in app.map_note_var.get()
    assert app._options_read is None


def test_saved_settings_keep_the_read_values(map_app, monkeypatch):
    import json
    import gui
    from bbreroll import map_view
    app = map_app
    monkeypatch.setattr(gui.msu_settings, "read_map_options", lambda path=None: {"Settlements": 24})
    app._read_saved_options()
    app._save_settings()
    data = json.loads(gui.SETTINGS_PATH.read_text(encoding="utf-8"))
    assert data["map_options_read"]["Settlements"] == "24" and data["map_options_read"]["StackCitadels"] == "No"
    assert set(data["map_options_read"]) == set(map_view.default_options())


def test_start_up_fills_untouched_map_options(map_app, monkeypatch):
    import gui
    from bbreroll import map_view
    app = map_app
    monkeypatch.delenv("BB_REROLL_SELFTEST", raising=False)
    monkeypatch.setattr(gui.msu_settings, "read_map_options", lambda path=None: {"Settlements": 24})
    monkeypatch.setattr(app, "_saved", {})                  # no Map Options in the settings file yet
    app._startup_saved_options()
    assert app.map_option_vars["Settlements"].get() == "24"
    assert map_view.OPTIONS_DIFFER not in app.map_note_var.get()
    assert app._options_read == map_view.saved_option_texts({"Settlements": 24})


def test_start_up_keeps_typed_map_options(map_app, monkeypatch):
    # the player typed 21 after the program last read the file (which held the defaults): the typed value stays
    import gui
    from bbreroll import map_view
    app = map_app
    monkeypatch.delenv("BB_REROLL_SELFTEST", raising=False)
    monkeypatch.setattr(gui.msu_settings, "read_map_options", lambda path=None: {"Settlements": 24})
    read_before = map_view.default_options()
    monkeypatch.setattr(app, "_saved", {"map_options": dict(read_before, Settlements="21"),
                                        "map_options_read": read_before})
    app.map_option_vars["Settlements"].set("21")
    app._startup_saved_options()
    assert app.map_option_vars["Settlements"].get() == "21", "the typed value is kept"
    assert map_view.OPTIONS_DIFFER in app.map_note_var.get()


def test_start_up_without_a_readable_file_keeps_the_fields(map_app, monkeypatch):
    import gui
    from bbreroll import map_view
    app = map_app
    monkeypatch.delenv("BB_REROLL_SELFTEST", raising=False)
    app.map_option_vars["Water"].set("40")
    monkeypatch.setattr(gui.msu_settings, "read_map_options", lambda path=None: None)
    monkeypatch.setattr(app, "_saved", {})
    app._startup_saved_options()                            # no exception
    assert app.map_option_vars["Water"].get() == "40"
    assert map_view.NO_SAVED_OPTIONS in app.map_note_var.get()


def test_start_up_when_the_read_raises_keeps_the_fields(map_app, monkeypatch):
    # Review Focus 2: the exe has no console; a failed read must not stop the start
    import gui
    from bbreroll import map_view
    app = map_app
    monkeypatch.delenv("BB_REROLL_SELFTEST", raising=False)
    app.map_option_vars["Water"].set("40")

    def unreadable(path=None):
        raise OSError("the save file is locked")
    monkeypatch.setattr(gui.msu_settings, "read_map_options", unreadable)
    monkeypatch.setattr(app, "_saved", {})
    app._startup_saved_options()                            # no exception
    assert app.map_option_vars["Water"].get() == "40"
    assert map_view.NO_SAVED_OPTIONS in app.map_note_var.get()


def test_start_up_remembers_saved_values_the_fields_already_have(map_app, monkeypatch):
    # the fields hold the saved values, but the settings file's marker is older: the marker is updated, so the next
    # start sees the fields as untouched and fills them again (the saved file wins while nothing was typed)
    import gui
    from bbreroll import map_view
    app = map_app
    monkeypatch.delenv("BB_REROLL_SELFTEST", raising=False)
    monkeypatch.setattr(gui.msu_settings, "read_map_options", lambda path=None: {"Settlements": 24})
    app.map_option_vars["Settlements"].set("24")
    monkeypatch.setattr(app, "_saved", {"map_options": dict(map_view.default_options(), Settlements="24"),
                                        "map_options_read": map_view.default_options()})
    app._startup_saved_options()
    assert app._options_read == map_view.saved_option_texts({"Settlements": 24})
    assert app.map_option_vars["Settlements"].get() == "24"
    assert map_view.OPTIONS_DIFFER not in app.map_note_var.get()


def test_the_start_up_read_also_runs_on_vanilla(map_app, monkeypatch):
    # final review F1: the program reads the saved Mod Options at start-up on every setup, so a player who starts on
    # the base game and switches to Legends sees the saved values (the note of a difference stays Legends-only)
    import gui
    from bbreroll import map_view
    app = map_app
    monkeypatch.delenv("BB_REROLL_SELFTEST", raising=False)
    monkeypatch.setattr(gui.msu_settings, "read_map_options",
                        lambda path=None: {"Settlements": 24, "StackCitadels": True})
    monkeypatch.setattr(app, "_saved", {})                  # no Map Options in the settings file yet
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    app._startup_saved_options()
    app.setup_var.set("Legends")
    app._on_setup_change()
    assert app.map_option_vars["Settlements"].get() == "24"
    assert app.map_option_vars["StackCitadels"].get() == map_view.YES
    assert map_view.OPTIONS_DIFFER not in app.map_note_var.get()


def test_a_self_test_never_reads_the_saved_options(map_app, monkeypatch):
    import gui
    app = map_app
    seen = []
    monkeypatch.setattr(gui.msu_settings, "read_map_options", lambda path=None: seen.append(path) or {"Settlements": 24})
    monkeypatch.setenv("BB_REROLL_SELFTEST", "spec.json")
    app._startup_saved_options()
    assert seen == [] and app.map_option_vars["Settlements"].get() == "19"


# ---- the seed post and the results
def roster_of(n=2):
    return [{"name": "Bro %d" % i, "background": "background.sellsword", "background_name": "Sellsword",
             "stars": {"hp": 1}, "trait_names": [], "traits": []} for i in range(n)]


def result(app, seed, summary=None):
    app._ev_match({"seed": seed, "roster": roster_of(), "stable": True, "failure": None, "map": summary})
    return app._matches[0]


ROSTER_INFO = {"legends_version": "19.4.22", "legends_build": "Bandits & Greenskins", "battle_sisters": "Enabled",
               "game_version": "1.5.2.3", "mods": [{"name": "Legends Mod", "version": "19.4.22"}],
               "map_options": {"LandRatio": 50, "Water": 38, "Snowline": 85, "Settlements": 24, "Factions": 3,
                               "StackCitadels": False, "AllTradeLocations": True}}
VANILLA_INFO = {"legends_version": None, "legends_build": None, "battle_sisters": None,
                "game_version": "1.5.2.3", "mods": [], "map_options": {}}


def test_a_roster_only_post_is_what_it_was_before_the_map_view(map_app, calls):
    import gui
    from bbreroll.seed_report import build_seed_report
    app = map_app
    search_now(app, calls)                  # sets the run
    app._ev_ready((1, 1, ROSTER_INFO))
    assert app._report_info == {"version": "19.4.22", "build_name": "Bandits & Greenskins",
                                "battle_sisters": "Enabled", "origin": app._run["origin"], "map_options": {},
                                "game_version": "1.5.2.3", "mods": ROSTER_INFO["mods"], "legends": True,
                                "dlc_complete": None}, \
        "no map condition: the Map Options are not part of the post"
    entry = result(app, "1111111111")
    expected = build_seed_report(origin=entry["origin"], description="", seed="1111111111",
                                 report_info=dict(app._report_info), tool_version=gui.APP_VERSION, roster=entry["roster"])
    assert app._share_report(entry) == expected
    assert "Map Options: any." in expected and "Map:" not in expected


def test_a_vanilla_map_post_has_no_map_options(map_app, calls):
    app = map_app
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    app.map_vars["ports"].set("2")
    search_now(app, calls)
    app._ev_ready((1, 1, dict(VANILLA_INFO, dlc_complete=True)))
    assert app._report_info["legends"] is False
    text = app._share_report(result(app, "2222222222", small_map()))
    assert "Map: Ports 2" in text
    assert "Map Options: none. The base game has no Map Options." in text
    assert "Land Mass Ratio" not in text and "Settlements:" not in text
    assert "Mods: none\nDLCs: all\n" in text, "a base-game map depends on the DLCs: the post names them"


def test_the_post_call_gets_the_map_and_the_band_of_the_run(map_app, calls, monkeypatch):
    import gui
    app = map_app
    seen = []
    real = gui.build_seed_report
    monkeypatch.setattr(gui, "build_seed_report", lambda **kw: seen.append(kw) or real(**kw))
    # a result without a map: game_map is None (never {}) and the band is the default
    search_now(app, calls)
    app._ev_ready((1, 1, ROSTER_INFO))
    app._share_report(result(app, "1111111111"))
    assert seen[-1]["game_map"] is None and seen[-1]["north_band"] == 33
    # a run with map conditions: the map, the band typed in the field and the Map Options of the workers
    app.map_vars["ports_north"].set("1")
    app.map_vars["north_band"].set("50")
    search_now(app, calls)
    assert app._run["north_band"] == 50
    app._ev_ready((1, 1, ROSTER_INFO))
    assert app._report_info["map_options"] == ROSTER_INFO["map_options"]
    summary = small_map()
    text = app._share_report(result(app, "2222222222", summary))
    assert seen[-1]["game_map"] is summary and seen[-1]["north_band"] == 50
    assert "Map: Ports 2 (south 1, north 1) · 1 city state · north band: the top 50 % of the map" in text
    assert "Settlements: 24" in text and "All trade buildings available: Yes" in text


def test_a_result_with_a_map_has_a_show_map_button(map_app):
    app = map_app
    app._run = dict(RUN, north_band=33)
    result(app, "1111111111")
    result(app, "2222222222", small_map())

    def buttons(widget):
        out = []
        for child in widget.winfo_children():
            if isinstance(child, ctk.CTkButton):
                out.append(child.cget("text"))
            out += buttons(child)
        return out
    assert buttons(app.match_list).count("Show map") == 1


def canvas_of(window):
    import tkinter as tk
    found = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Canvas) and int(child.cget("height")) > 100:
                found.append(child)
            walk(child)
    walk(window)
    return found[0]


def test_show_map_opens_a_window(map_app):
    import tkinter as tk
    from bbseed import mapdraw
    app = map_app
    summary = small_map()
    app._run = dict(RUN, north_band=40)
    app._show_map(result(app, "2222222222", summary))
    pump(app, lambda: False, 0.3)
    (window,) = app._map_windows.values()
    assert isinstance(window, ctk.CTkToplevel) and window.winfo_exists()
    assert "2222222222" in window.title()
    canvas = canvas_of(window)
    assert isinstance(canvas, tk.Canvas)
    # one rectangle per tile, one circle per town, a ring per port, the band's line: the geometry of mapdraw
    kinds = [canvas.type(item) for item in canvas.find_all()]
    assert kinds.count("rectangle") == 30 * 40
    assert kinds.count("oval") == 3 + 2
    assert kinds.count("line") == 1
    width, height = mapdraw.picture_size(summary, window.scale)
    assert abs(int(canvas.cget("width")) - width) <= 1 and abs(int(canvas.cget("height")) - height) <= 1


def test_the_map_window_has_north_at_the_top_and_the_band_line_where_mapdraw_puts_it(map_app):
    from bbseed import mapdraw
    app = map_app
    summary = small_map()
    app._run = dict(RUN, north_band=40)
    app._show_map(result(app, "2222222222", summary))
    pump(app, lambda: False, 0.2)
    window = next(iter(app._map_windows.values()))
    canvas, scale = canvas_of(window), window.scale
    towns = [i for i in canvas.find_all() if canvas.type(i) == "oval" and canvas.itemcget(i, "fill")]
    assert len(towns) == 3
    centre = lambda i: ((canvas.coords(i)[0] + canvas.coords(i)[2]) / 2, (canvas.coords(i)[1] + canvas.coords(i)[3]) / 2)
    at = lambda x: next(centre(i)[1] for i in towns if abs(centre(i)[0] - (x * mapdraw.CELL_W + mapdraw.CELL_W / 2) * scale) < 2)
    # the northern port (row 37 of 40) is drawn above the southern one (row 2): north at the top
    assert at(20) < at(3)
    (line,) = [i for i in canvas.find_all() if canvas.type(i) == "line"]
    assert abs(canvas.coords(line)[1] - mapdraw.band_y(summary, 40, scale)) <= 1
    assert canvas.itemcget(line, "fill") == mapdraw.BAND_COLOUR
    # the colours of the picture are mapdraw's
    assert {canvas.itemcget(i, "fill") for i in canvas.find_all() if canvas.type(i) == "rectangle"} == {
        mapdraw.TERRAIN_COLOURS["L"], mapdraw.TERRAIN_COLOURS["O"]}
    assert {canvas.itemcget(i, "fill") for i in towns} == {mapdraw.TOWN_FILL["southern"], mapdraw.TOWN_FILL["military"],
                                                             mapdraw.TOWN_FILL["town"]}
    rings = [i for i in canvas.find_all() if canvas.type(i) == "oval" and not canvas.itemcget(i, "fill")]
    assert len(rings) == 2 and {canvas.itemcget(i, "outline") for i in rings} == {mapdraw.PORT_RING}


def test_the_map_window_opens_on_top_of_the_main_window(map_app):
    # 2026-10-24: Show map opened the window behind the main window. CTkToplevel hides and shows itself again to
    # colour its title bar, and gives the focus back to the main window.
    app = map_app
    app._run = dict(RUN, north_band=33)
    app.deiconify()
    app.geometry("980x940+40+40")
    try:
        entry = result(app, "2222222222", small_map())
        pump(app, lambda: False, 1.7)       # a match keeps the main window topmost for 1.5 s (_surface_window)
        app.focus_force()
        pump(app, lambda: False, 0.2)
        app._show_map(entry)
        window = next(iter(app._map_windows.values()))
        pump(app, lambda: False, 1.0)
        assert app.tk.eval(f"wm stackorder {window} isabove .") == "1"
        app.lift()                                          # a second click brings it forward again
        pump(app, lambda: False, 0.3)
        app._show_map(entry)
        pump(app, lambda: False, 0.5)
        assert app.tk.eval(f"wm stackorder {window} isabove .") == "1"
        # Show map at once after a new match (the main window is still topmost)
        app._show_map(result(app, "3333333333", small_map()))
        other = app._map_windows[(app._matches[0]["setup"], app._matches[0]["origin"], "3333333333")]
        pump(app, lambda: False, 1.0)
        assert app.tk.eval(f"wm stackorder {other} isabove .") == "1"
    finally:
        for window in list(app._map_windows.values()):
            window.destroy()
        app._clear_matches()
        app.withdraw()
        pump(app, lambda: False, 0.2)


def test_a_second_click_brings_the_window_forward_and_closing_leaves_nothing(map_app):
    app = map_app
    app._run = dict(RUN, north_band=33)
    entry = result(app, "2222222222", small_map())
    app._show_map(entry)
    first = next(iter(app._map_windows.values()))
    app._show_map(entry)
    assert len(app._map_windows) == 1 and next(iter(app._map_windows.values())) is first
    app._show_map(result(app, "3333333333", small_map()))      # another seed gets a window of its own
    assert len(app._map_windows) == 2
    first.destroy()
    pump(app, lambda: False, 0.2)
    assert len(app._map_windows) == 1, "a closed window is gone from the list"
    for window in list(app._map_windows.values()):
        window.destroy()
    pump(app, lambda: False, 0.2)
    assert app._map_windows == {}
    assert [w for w in app.winfo_children() if isinstance(w, ctk.CTkToplevel)] == []


def test_the_same_seed_with_a_new_map_gets_a_fresh_window(map_app):
    # The map depends on the Map Options: a seed that is found again after a change of Settlements has another map.
    # The result replaces the old one; its Show map must not bring the old window forward.
    app = map_app
    app._run = dict(RUN, north_band=33)
    old = result(app, "2222222222", small_map(30, 40))
    app._show_map(old)
    first = next(iter(app._map_windows.values()))
    assert len([i for i in canvas_of(first).find_all() if canvas_of(first).type(i) == "rectangle"]) == 30 * 40
    new = result(app, "2222222222", small_map(32, 44))          # the same seed, a new map (a new event)
    assert len(app._matches) == 1 and app._matches[0] is new
    app._show_map(new)
    pump(app, lambda: False, 0.2)
    (window,) = app._map_windows.values()
    assert window is not first, "a window with the old map is not reused"
    assert not first.winfo_exists(), "and it does not stay open beside the new one"
    canvas = canvas_of(window)
    assert len([i for i in canvas.find_all() if canvas.type(i) == "rectangle"]) == 32 * 44
    app._show_map(new)                                          # the same result again: the same window
    assert next(iter(app._map_windows.values())) is window
    # the band of the run is part of the picture too: the same map found with another band is drawn again
    other_band = dict(new, north_band=60)
    app._show_map(other_band)
    (again,) = app._map_windows.values()
    assert again is not window and again.band == 60 and not window.winfo_exists()


def test_the_whole_legends_map_fits_a_screen_1440_pixels_high(map_app):
    app = map_app
    app._run = dict(RUN, north_band=33)
    started = time.time()
    app._show_map(result(app, "2222222222", small_map(140, 170)), screen_height=1440)
    pump(app, lambda: False, 0.3)
    window = next(iter(app._map_windows.values()))
    window.update_idletasks()
    assert window.winfo_reqheight() <= 1440 - 80, "room for the title bar and the taskbar"
    assert time.time() - started < 8.0, "23,800 tiles are drawn in a few seconds"


# ---- events
def test_a_fatal_before_the_workers_are_ready_cannot_start_and_after_it_stopped(map_app, monkeypatch):
    app = map_app
    shown = []
    monkeypatch.setattr(app, "_show_notice", lambda text, kind="warn", action=None: shown.append((text, kind)))
    app._run = dict(RUN)
    app._ev_fatal("OSError: no memory")
    assert shown == [("The search cannot start: OSError: no memory", "error")]
    shown.clear()
    app._run = dict(RUN)
    app._ev_ready((2, 2, ROSTER_INFO))
    app._ev_fatal("KeyError: 'x' (seed 123)")
    # search() goes on with the other workers after a fatal that is not a map fatal: not "the search stopped"
    assert shown == [("A search process stopped: KeyError: 'x' (seed 123)", "error")]


def test_several_identical_fatals_show_one_notice(map_app, monkeypatch):
    app = map_app
    shown = []
    monkeypatch.setattr(app, "_show_notice", lambda text, kind="warn", action=None: shown.append(text))
    app._run = dict(RUN)
    app._ev_ready((4, 4, ROSTER_INFO))
    for _ in range(4):
        app._ev_fatal("ValueError: bad (seed 5)")
    assert len(shown) == 1


def test_fatal_then_finished_keeps_the_red_banner(map_app):
    app = map_app
    app._run = dict(RUN)
    app._searching = True
    app._ev_ready((1, 1, ROSTER_INFO))
    app._ev_fatal("ValueError: bad (seed 5)")
    red = app.notice_banner.cget("fg_color")
    assert app.notice_var.get().startswith("A search process stopped: ValueError: bad (seed 5)")
    app._ev_finished((12, 3.0, 0, False))           # search() sends this after a fatal, with stopped = False
    assert app.notice_var.get().startswith("A search process stopped: ValueError: bad (seed 5)")
    assert app.notice_banner.cget("fg_color") == red == app._NOTICE_COLORS["error"][0]
    # the other workers may have gone on to the end: the status does not say the search "stopped" or "completed"
    assert app.status_var.get().startswith("Search ended: 12 seeds tested in 3s, 0 matches.")
    assert "No seed matched" not in app.notice_var.get()


def test_a_map_fatal_after_a_different_fatal_still_turns_the_map_view_off(map_app, calls):
    from bbreroll import map_view
    from bbseed.search import MAP_FATAL
    app = map_app
    app.map_vars["ports"].set("3")
    app._run = dict(RUN)
    app._searching = True
    app._ev_ready((2, 2, ROSTER_INFO))
    app._ev_fatal("OSError: no memory")             # one worker; the other goes on
    assert not app._map_off and app.notice_var.get().startswith("A search process stopped: OSError")
    app._ev_fatal(MAP_FATAL + "KeyError: 'x' (seed 5)")      # search() ends on this one
    assert app._map_off, "first-fatal-only must not hide a map fatal"
    assert app.notice_var.get().startswith(MAP_FATAL + "KeyError: 'x' (seed 5)")
    assert map_view.TURNED_OFF in app.map_note_var.get()
    app._ev_fatal("OSError: another (seed 9)")      # a later fatal of another kind changes nothing
    assert app.notice_var.get().startswith(MAP_FATAL)
    app._ev_finished((3, 5.0, 0, False))
    assert app.status_var.get().startswith("Stopped: 3 seeds tested")
    assert "map" not in search_now(app, calls)[0]["criteria"]


def test_a_map_fatal_turns_the_map_view_off_and_leaves_roster_searches_alone(map_app, calls):
    from bbreroll import map_view
    from bbseed.search import MAP_FATAL
    app = map_app
    app.map_vars["ports"].set("3")
    app._run = dict(RUN)
    app._searching = True
    app._ev_ready((1, 1, ROSTER_INFO))
    app._ev_fatal(MAP_FATAL + "KeyError: 'x' (seed 5)")
    app._ev_finished((0, 1.0, 0, False))
    assert app._map_off
    assert app.notice_var.get().startswith(MAP_FATAL + "KeyError: 'x' (seed 5)")
    assert "Change a Map Option in the Map view to turn them on again." in app.notice_var.get()
    assert "Roster searches still work" in app.notice_var.get()
    assert map_view.TURNED_OFF in app.map_note_var.get()
    # the fields stay open: the player must be able to change a Map Option
    assert all(str(w.cget("state")) == "normal" for w in app._map_widgets)
    (call,) = search_now(app, calls)
    assert "map" not in call["criteria"], "the roster search goes on without map conditions"
    assert call["mod_settings"] == {"mod_legends:GenderEquality": "Enabled"}


def lockout(app):
    """The state after a map fatal: map conditions off, the red notice up."""
    from bbseed.search import MAP_FATAL
    app.map_vars["ports"].set("3")
    app._run = dict(RUN)
    app._searching = True
    app._ev_ready((1, 1, ROSTER_INFO))
    app._ev_fatal(MAP_FATAL + "KeyError: 'x' (seed 5)")
    app._ev_finished((0, 1.0, 0, False))
    assert app._map_off and app.notice_var.get()


def test_changing_a_map_option_turns_map_conditions_on_again(map_app, calls):
    app = map_app
    lockout(app)
    assert "map" not in search_now(app, calls)[0]["criteria"]
    app.map_option_vars["LandRatio"].set("52")      # the player types in a Map Option field
    assert not app._map_off
    assert app.notice_var.get() == "", "the notice about the map fatal goes away with the lockout"
    assert "turn them on again" not in app.map_note_var.get()
    (call,) = search_now(app, calls)
    assert call["criteria"]["map"]["ports"] == 3 and call["mod_settings"]["mod_legends:LandRatio"] == 52
    # a Yes / No Map Option does it too
    lockout(app)
    app.map_option_vars["StackCitadels"].set("Yes")
    assert not app._map_off
    # a condition field alone does not: the cause of the fatal can be the Map Options
    lockout(app)
    app.map_vars["ports"].set("5")
    assert app._map_off
    # another notice (not the map fatal's) is left alone
    app._clear_notice()
    app._show_notice("Another notice.", kind="info")
    app.map_option_vars["Water"].set("40")
    assert not app._map_off and app.notice_var.get() == "Another notice."


def test_changing_the_setup_turns_map_conditions_on_again(map_app, calls):
    app = map_app
    lockout(app)
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    assert not app._map_off
    app.setup_var.set("Legends")
    app._on_setup_change()
    assert all(str(w.cget("state")) == "normal" for w in app._map_widgets)
    assert search_now(app, calls)[0]["criteria"]["map"]["ports"] == 3


def test_a_new_game_folder_turns_map_conditions_on_again(map_app, calls, monkeypatch):
    import gui
    from tkinter import filedialog
    from bbseed import gamedata
    app = map_app
    lockout(app)
    folder = app._game_folder
    monkeypatch.setenv("BBSEED_GAME_DATA", "")
    monkeypatch.setattr(filedialog, "askdirectory", lambda **k: "X:/Battle Brothers")
    monkeypatch.setattr(gamedata, "as_data_dir", lambda chosen: Path(chosen) / "data")
    monkeypatch.setattr(app, "_warn_old_mod", lambda: None)
    try:
        app._searching = False
        app._on_game_folder()
        assert not app._map_off
        assert search_now(app, calls)[0]["criteria"]["map"]["ports"] == 3
    finally:
        app._game_folder = folder


def test_the_estimate_waits_for_the_first_maps_and_a_missing_chance_shows_nothing(map_app):
    app = map_app
    app._run = dict(RUN, map={"ports": 3}, map_first=True)
    odds = {"chance": None, "tested": 4, "maps": 4}
    assert app._odds_text(odds, 0.1) == ""
    assert app._wait_text(odds) == ("Each map takes about 40 seconds with the default Map Options. "
                                    "The estimate shows after 30 maps. Maps built: 4.")
    assert app._odds_text({"chance": None, "tested": 30, "maps": 30}, 0.1) == "", "no chance, no estimate"
    assert app._wait_text({"chance": None, "tested": 30, "maps": 30}) == ""
    app._run = dict(RUN)
    assert app._wait_text(odds) == "", "a search for brothers alone has no map note"
    app._run = dict(RUN, map={"ports": 3}, map_first=True)
    text = app._odds_text({"chance": 0.04, "tested": 30, "maps": 30}, 0.1)
    assert text == ("Approximately 1 in 25 seeds matches (from 30 seeds, 30 maps)."
                    " At this speed, that is 1 match in approximately 4m10s.")
    # a run for brothers alone is what it was: nothing before 100 seeds, no maps in the text
    app._run = dict(RUN)
    assert app._odds_text({"chance": 0.04, "tested": 99}, 2.0) == ""
    assert app._odds_text({"chance": 0.04, "tested": 100}, 2.0) == (
        "Approximately 1 in 25 seeds matches (from 100 seeds). At this speed, that is 1 match in approximately 12s.")


def test_the_progress_of_a_map_search_shows_the_wait_note_and_the_never_notice(map_app):
    app = map_app
    app._run = dict(RUN, map={"ports": 9}, map_first=True)
    app._search_total = 1000
    app._ev_progress((6, 90.0, 0, {"chance": None, "never": [], "never_any": False, "never_map": False,
                                   "maps": 6, "tested": 6}))
    assert app.status_var.get() == ("Each map takes about 40 seconds with the default Map Options. "
                                    "The estimate shows after 30 maps. Maps built: 6.")
    never = lambda maps: {"chance": 0.0, "never": [], "never_any": False, "never_map": True,       # noqa: E731
                          "maps": maps, "tested": maps}
    # Final review I2: valid conditions can be rare (6 or more ports: 4 % of the maps), so 20 maps without a hit
    # say nothing; at 100 the notice says the maps are rare and that the search goes on
    app._ev_progress((99, 3000.0, 0, never(99)))
    assert app.notice_var.get() == ""
    app._ev_progress((100, 3050.0, 0, never(100)))
    assert app.notice_var.get() == ("No map met the map conditions in 100 maps. Maps like this are rare. "
                                    "The search continues.")
    assert "Possibly" not in app.notice_var.get() and "no seed matches" not in app.notice_var.get().lower()
    app._ev_finished((100, 3050.0, 0, False))
    assert app.notice_var.get().startswith("No seed matched in 100 seeds. No map met the map conditions.")


def test_a_self_test_spec_sets_the_map_fields(map_app):
    app = map_app
    app._set_map_fields({"ports": 3, "towns": {"city_state": 2}}, {"Settlements": 24, "StackCitadels": True})
    assert app.map_vars["ports"].get() == "3" and app.map_vars["city_state"].get() == "2"
    assert app.map_option_vars["Settlements"].get() == "24" and app.map_option_vars["StackCitadels"].get() == "Yes"
    app._set_map_fields(None, None)
    assert app.map_vars["ports"].get() == "0" and app.map_option_vars["Settlements"].get() == "19"


# ---- the final fix wave (final review of map search stage 1)
ZIPS = ["mod_legends-19.4.22.zip", "mod_legends-assets-19.4.3.zip", "mod_modern_hooks-685-0-6-0-1748620177.zip",
        "mod_msu 479 1.9.0 2026-06-23T04-27Z eVJjKbX9c.zip"]
IDS = ("mod_legends", "mod_legends_assets", "mod_modern_hooks", "mod_msu")


def worker_info(mods):
    return {"legends_version": "19.4.22", "game_version": "1.5.2.3", "map_options": {}, "mods": mods}


def worker_mods(*extra):
    return [{"file": z, "id": i, "name": i, "version": "1"} for z, i in zip(ZIPS, IDS)] + [
        {"file": f, "id": None, "name": f[:-4], "version": None} for f in extra]


def test_a_mod_beyond_legends_msu_and_modern_hooks_shows_the_not_verified_note(map_app, monkeypatch):
    """Final review I1 (b): another mod can hook the map generator, so its maps are not verified. The mods of the
    installed game decide before a search; the mods the workers report win once a search has started."""
    from bbreroll import map_view
    from bbreroll import offline_origins as O
    app = map_app
    monkeypatch.setitem(O.FOUND, "mods", ZIPS)
    app._apply_map_state()
    assert app.map_note_var.get() == ""
    monkeypatch.setitem(O.FOUND, "mods", ZIPS + ["mod_jimmys_tooltips-1.0.5.zip"])
    app._apply_map_state()
    assert app.map_note_var.get() == map_view.NOT_VERIFIED == "Map results are not verified for this setup."
    assert app.map_note.grid_info()
    # the workers loaded the verified set: the note goes; they loaded one more mod: it comes back
    app._run = dict(RUN)
    app._ev_ready((1, 1, worker_info(worker_mods())))
    assert app.map_note_var.get() == ""
    app._ev_ready((1, 1, worker_info(worker_mods("mod_other.zip"))))
    assert app.map_note_var.get() == map_view.NOT_VERIFIED
    # a game folder change forgets what the last search reported
    monkeypatch.setitem(O.FOUND, "mods", ZIPS)
    app._map_mods = None
    app._apply_map_state()
    assert app.map_note_var.get() == ""


def test_the_watch_line_shows_a_decimal_below_ten_seeds_a_second(map_app):
    """Final review M2: a search with maps tests about 0.14 seeds a second; "0/s" looked stuck."""
    app = map_app
    app._run = dict(RUN, map={"ports": 9}, map_first=True)
    app._search_total = 1000
    app._ev_progress((3, 21.0, 0, {}))
    assert app.watch_var.get().startswith("Searching: 3 of 1,000 seeds, 0.1/s, ")
    app._ev_progress((600, 20.0, 0, {}))
    assert app.watch_var.get().startswith("Searching: 600 of 1,000 seeds, 30/s, ")
    app._ev_progress((50, 10.0, 0, {}))
    assert app.watch_var.get().startswith("Searching: 50 of 1,000 seeds, 5.0/s, ")


def test_brother_and_map_conditions_show_the_brothers_rate_until_30_maps_are_built(map_app):
    """Final review M7: rare brother conditions need hours for 30 maps; meanwhile the status line shows the brothers'
    rate with the number of maps built. Before 100 seeds and from 30 maps the old texts speak."""
    app = map_app
    app._run = dict(RUN, map={"ports": 5}, map_first=False)
    app._search_total = 100000
    odds = {"chance": None, "chance_brothers": 0.0002, "never": [], "never_any": False, "never_map": False,
            "tested": 500, "maps": 0}
    app._ev_progress((500, 10.0, 0, odds))
    assert app.status_var.get() == ("Approximately 1 in 5,000 seeds meets the brother conditions (from 500 seeds). "
                                    "Maps built: 0. The estimate with the maps shows after 30 maps.")
    app._ev_progress((900, 20.0, 0, dict(odds, chance=0.0001, maps=7, tested=900)))
    assert "(from 900 seeds). Maps built: 7." in app.status_var.get()
    app._ev_progress((50, 5.0, 0, dict(odds, tested=50)))
    assert app.status_var.get().startswith("Each map takes about 40 seconds with the default Map Options.")
    app._ev_progress((6000, 100.0, 0, dict(odds, chance=0.00004, tested=6000, maps=30)))
    assert app.status_var.get().startswith("Approximately 1 in 25,000 seeds matches (from 6,000 seeds, 30 maps).")
    # map conditions alone have no brothers' rate
    app._run = dict(RUN, map={"ports": 5}, map_first=True)
    app._ev_progress((500, 10.0, 0, odds))
    assert app.status_var.get().startswith("Each map takes about 40 seconds")


def labels_of(widget, kind=ctk.CTkLabel):
    """The texts of all labels (kind=ctk.CTkButton: of all buttons) below a widget."""
    out = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            out.append(str(child.cget("text")))
        out += labels_of(child, kind)
    return out


def test_the_map_window_legend_and_the_tooltips_use_the_words_of_the_map_view_fields(map_app):
    """Final review M8 and 163. The white circle is a village, town or city (the field "Towns" is size 2 only) and
    the forts are strongholds; tooltips say "minimum"."""
    from bbreroll import map_view
    from bbseed import mapdraw
    app = map_app
    app._run = dict(RUN, north_band=33)
    app._show_map(result(app, "2222222222", small_map()))
    pump(app, lambda: False, 0.2)
    texts = labels_of(next(iter(app._map_windows.values())))
    for label in mapdraw.KIND_LABELS.values():
        assert label in texts
    assert "Village, town or city" in texts and "Stronghold" in texts and "City state" in texts and "Town" not in texts
    assert "fort" not in " ".join(texts).lower()
    assert not hasattr(app, "_MAP_TIPS"), "the tooltips live in map_view (unit-tested)"
    assert all("least" not in tip for tip in map_view.CONDITION_TIPS.values())


def test_a_checked_seed_whose_map_could_not_be_built_shows_its_roster_and_the_reason(map_app):
    """Final review M3: the search reports the roster of a checked seed with the failure "map could not be built"
    and no map; the window shows that card, not "See the results" over nothing."""
    from bbseed.mapgen import MAP_NOT_BUILT
    app = map_app
    app._run = dict(RUN, checking=True, map={"ports": 4})
    reason = "map of seed '1234567890': the index '0' does not exist"
    app._ev_match({"seed": "1234567890", "roster": roster_of(), "stable": True, "failure": MAP_NOT_BUILT + reason,
                   "map": None})
    app._ev_error(reason)
    app._ev_finished((1, 1.0, 1, False))
    assert len(app._matches) == 1 and app.status_var.get() == "The seed check is complete. See the results."
    texts = labels_of(app.match_list)
    assert any("Checked: The map could not be built: " + reason in t for t in texts)
    assert any("Bro 0" in t for t in texts), "the roster is there"
    assert "Copy roster" in labels_of(app.match_list, ctk.CTkButton) and "Show map" not in labels_of(
        app.match_list, ctk.CTkButton)
    # a map failure of the conditions reads as a sentence too
    app._ev_match({"seed": "1234567891", "roster": roster_of(), "stable": True, "failure": "Ports: 1, needs 4",
                   "map": small_map()})
    assert any("Checked: Ports: the map has 1. The minimum is 4." in t for t in labels_of(app.match_list))


# ---- the final fix wave (final review of 4.2.0): the base game's texts, its checks and the options note
def test_the_base_game_map_texts_name_the_dlcs_and_no_map_options(map_app, calls):
    """Final review F3: the base game has no Map Options and no Land Mass Ratio. Its Map view help, its start line
    and the progress line of its map search say so; the help follows a setup change while the Map mode is shown."""
    from bbreroll import map_view
    app = map_app
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    app.grid_mode_var.set("Map")
    app._on_grid_mode()
    assert app.grid_help.cget("text") == map_view.HELP_BASE
    app.setup_var.set("Legends")
    app._on_setup_change()
    assert app.grid_help.cget("text") == map_view.HELP
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    assert app.grid_help.cget("text") == map_view.HELP_BASE
    app.map_vars["ports"].set("3")
    app._on_search()                        # the start line is set before the stand-in search runs
    assert app.status_var.get().endswith(map_view.WAIT_BASE)
    pump(app, lambda: not app._searching, 3.0)
    assert len(calls) == 1
    app._run = dict(RUN, setup="Vanilla", map={"ports": 3}, map_first=True)
    app._search_total = 1000
    app._ev_progress((6, 90.0, 0, {"chance": None, "never": [], "never_any": False, "never_map": False,
                                   "maps": 6, "tested": 6}))
    assert app.status_var.get() == ("Each map takes about 40 seconds. "
                                    "The estimate shows after 30 maps. Maps built: 6.")
    assert "Land Mass" not in app.grid_help.cget("text") and "default Map Options" not in app.status_var.get()


def test_vanilla_impossible_conditions_use_the_base_game_maximum(map_app, calls, monkeypatch):
    """Final review F4 (task 9): the base game checks its own maxima, and its message names the base game."""
    app = map_app
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    app.map_vars["city_state"].set("4")
    seen = asked(monkeypatch, answer=False)
    assert search_now(app, calls) == []
    (title, message), = seen
    assert title == "Impossible conditions"
    assert "a map of the base game has a maximum of 3" in message
    assert "City states: a map of the base game has a maximum of 3. Your condition is 4." in message


def test_the_saved_options_note_shows_only_on_legends(map_app):
    """Final review F4 (task 9): the note about the saved Map Options belongs to the Map Options, which the base game
    does not show; it is back on Legends."""
    from bbreroll import map_view
    app = map_app
    app._options_note = map_view.OPTIONS_DIFFER
    app._apply_map_state()
    assert map_view.OPTIONS_DIFFER in app.map_note_var.get()
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    assert map_view.OPTIONS_DIFFER not in app.map_note_var.get()
    app.setup_var.set("Legends")
    app._on_setup_change()
    assert map_view.OPTIONS_DIFFER in app.map_note_var.get()
    app._options_note = None

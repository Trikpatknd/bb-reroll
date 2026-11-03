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
    real_ensure_catalog = gui.App._ensure_catalog
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
    window.real_ensure_catalog = real_ensure_catalog      # for the tests of the catalog build itself
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


@pytest.mark.core
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


@pytest.mark.core
def test_show_roster_checks_one_seed(app, calls):
    app.check_seed_var.set("1234567890")
    app._on_check_seed()
    pump(app, lambda: calls and not app._searching)
    assert len(calls) == 1 and calls[0]["seeds"] == ["1234567890"] and calls[0]["max_seeds"] is None


@pytest.mark.edge
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


@pytest.mark.core
def test_a_fixed_star_is_locked_and_no_condition(app, calls):
    # Trading Caravan's brother 2 has HP 1, MSK 2, MDF 1 on every seed (built-in table until the catalog)
    app.origin_var.set("Trading Caravan")
    app._on_origin_change("Trading Caravan")
    assert app.stars_widgets[("2", "msk")].cget("state") == "disabled"
    assert app.stars_vars[("2", "msk")].get() == "2"
    app.stars_vars[("*", "res")].set("1")
    criteria = app._gather_criteria()
    assert "2" not in criteria["stars_by_slot"], "a locked row must not replace row All"


@pytest.mark.edge
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
        last = app.match_list.pack_slaves()[-1]
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
        app._render_match_list()
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


@pytest.mark.core
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


@pytest.mark.core
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


@pytest.mark.core
def test_the_map_view_has_a_field_for_everything(map_app):
    from bbreroll import map_view
    app = map_app
    assert set(app.map_vars) == set(map_view.default_conditions())
    assert list(app.map_option_vars) == MAP_OPTION_KEYS
    assert {k: v.get() for k, v in app.map_option_vars.items()} == map_view.default_options()
    assert list(map_view.TOWN_LABELS.values()) == ["City states", "Strongholds", "Villages", "Towns", "Cities"]


@pytest.mark.core
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


@pytest.mark.core
def test_show_roster_with_a_map_condition_builds_the_map_with_the_same_options(map_app, calls):
    app = map_app
    app.map_vars["ports"].set("2")
    app.map_option_vars["Factions"].set("5")
    app.check_seed_var.set("1234567890")
    app._on_check_seed()
    pump(app, lambda: calls and not app._searching)
    assert calls[0]["criteria"]["map"]["ports"] == 2 and calls[0]["mod_settings"]["mod_legends:Factions"] == 5


@pytest.mark.edge
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


@pytest.mark.dirty
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


@pytest.mark.dirty
def test_the_map_options_decide_what_is_impossible(map_app, calls, monkeypatch):
    app = map_app
    app.map_vars["military"].set("8")           # Strongholds: at most 6 with Settlements 19, 9 with 27
    seen = asked(monkeypatch, answer=False)
    assert search_now(app, calls) == []
    assert "Strongholds: a map has a maximum of 6 with these Map Options. Your condition is 8." in seen[0][1]
    app.map_option_vars["Settlements"].set("27")
    seen.clear()
    assert len(search_now(app, calls)) == 1 and seen == []


@pytest.mark.dirty
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


@pytest.mark.dirty
def test_a_map_option_that_is_wrong_does_not_stop_a_search_for_brothers_alone(map_app, calls):
    app = map_app
    app.map_option_vars["Water"].set("99")
    assert len(search_now(app, calls)) == 1 and app.errors == []


# ---- the game version and the setups
@pytest.mark.dirty
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


@pytest.mark.dirty
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


@pytest.mark.edge
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


@pytest.mark.dirty
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


@pytest.mark.dirty
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


@pytest.mark.edge
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


@pytest.mark.dirty
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
@pytest.mark.core
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


@pytest.mark.edge
def test_a_settings_file_from_before_the_map_view_loads_with_the_defaults(map_app):
    app = map_app
    app.map_vars["ports"].set("5")
    app.map_option_vars["Water"].set("30")
    app._restore_map_values({"v": 4, "setup": "Legends", "criteria": {"stars_by_slot": {"*": {}}}})
    assert app.map_vars["ports"].get() == "0" and app.map_vars["north_band"].get() == "33"
    assert app.map_option_vars["Water"].get() == "38"


# ---- the saved Mod Options (the Map Options the player saved in the game's Mod Options, read from MSU's file)
@pytest.mark.core
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


@pytest.mark.dirty
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


@pytest.mark.core
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


@pytest.mark.core
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


@pytest.mark.edge
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


@pytest.mark.dirty
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


@pytest.mark.dirty
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


@pytest.mark.edge
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


@pytest.mark.edge
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


@pytest.mark.edge
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


@pytest.mark.core
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


@pytest.mark.edge
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


@pytest.mark.core
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


@pytest.mark.core
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
            if isinstance(child, tk.Canvas) and float(child.cget("height")) > 100:      # Tk 9: customtkinter's read '42.0'
                found.append(child)
            walk(child)
    walk(window)
    return found[0]


@pytest.mark.core
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


@pytest.mark.core
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


@pytest.mark.core
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


@pytest.mark.edge
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


@pytest.mark.edge
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


@pytest.mark.edge
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
@pytest.mark.dirty
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


@pytest.mark.dirty
def test_several_identical_fatals_show_one_notice(map_app, monkeypatch):
    app = map_app
    shown = []
    monkeypatch.setattr(app, "_show_notice", lambda text, kind="warn", action=None: shown.append(text))
    app._run = dict(RUN)
    app._ev_ready((4, 4, ROSTER_INFO))
    for _ in range(4):
        app._ev_fatal("ValueError: bad (seed 5)")
    assert len(shown) == 1


@pytest.mark.dirty
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


@pytest.mark.dirty
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


@pytest.mark.dirty
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


@pytest.mark.dirty
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


@pytest.mark.dirty
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


@pytest.mark.dirty
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


@pytest.mark.edge
def test_the_estimate_waits_for_the_first_maps_and_a_missing_chance_shows_nothing(map_app):
    app = map_app
    app._run = dict(RUN, map={"ports": 3}, map_first=True)
    odds = {"chance": None, "tested": 4, "maps": 4}
    assert app._odds_text(odds, 0.1) == ""
    assert app._wait_text(odds) == ("Each map takes about 25 seconds with the default Map Options. "
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


@pytest.mark.edge
def test_the_progress_of_a_map_search_shows_the_wait_note_and_the_never_notice(map_app):
    app = map_app
    app._run = dict(RUN, map={"ports": 9}, map_first=True)
    app._search_total = 1000
    app._ev_progress((6, 90.0, 0, {"chance": None, "never": [], "never_any": False, "never_map": False,
                                   "maps": 6, "tested": 6}))
    assert app.status_var.get() == ("Each map takes about 25 seconds with the default Map Options. "
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


@pytest.mark.core
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


@pytest.mark.dirty
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


@pytest.mark.edge
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


@pytest.mark.edge
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
    assert app.status_var.get().startswith("Each map takes about 25 seconds with the default Map Options.")
    app._ev_progress((6000, 100.0, 0, dict(odds, chance=0.00004, tested=6000, maps=30)))
    assert app.status_var.get().startswith("Approximately 1 in 25,000 seeds matches (from 6,000 seeds, 30 maps).")
    # map conditions alone have no brothers' rate
    app._run = dict(RUN, map={"ports": 5}, map_first=True)
    app._ev_progress((500, 10.0, 0, odds))
    assert app.status_var.get().startswith("Each map takes about 25 seconds")


def labels_of(widget, kind=ctk.CTkLabel):
    """The texts of all labels (kind=ctk.CTkButton: of all buttons) below a widget."""
    out = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            out.append(str(child.cget("text")))
        out += labels_of(child, kind)
    return out


@pytest.mark.core
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


LEGENDS_VERIFIED = {"version": "19.4.22", "legends": True, "game_version": "1.5.2.3", "dlc_complete": None,
                    "mods": [{"file": "mod_legends-19.4.22.zip", "id": "mod_legends", "version": "19.4.22"},
                             {"file": "mod_msu 479 1.9.0.zip", "id": "mod_msu", "version": "1.9.0"}]}
VANILLA_VERIFIED = {"version": "Vanilla 1.5.2.3", "legends": False, "game_version": "1.5.2.3", "dlc_complete": True,
                    "mods": []}


def start_window(app, info, start=(10, 25), seed="2222222222"):
    summary = dict(small_map(), start=None if start is None else list(start))
    app._run = dict(RUN, north_band=33)
    entry = result(app, seed, summary)
    entry["info"] = dict(info)
    app._show_map(entry)
    pump(app, lambda: False, 0.2)
    window = next(iter(app._map_windows.values()))
    return window, summary


@pytest.mark.core
def test_the_map_window_draws_the_start_star_on_a_verified_setup(map_app):
    """Stage 2 C1: a star on the company's start tile, the same polygon as the SVG's, a legend entry "Start", the
    tooltip "Your company starts here." and, with Legends, the first-campaign note."""
    from bbreroll import map_view
    from bbseed import mapdraw
    window, summary = start_window(map_app, LEGENDS_VERIFIED)
    canvas, scale = canvas_of(window), window.scale
    stars = [i for i in canvas.find_all() if canvas.type(i) == "polygon" and canvas.itemcget(i, "fill") == mapdraw.START_FILL]
    assert len(stars) == 1
    cx, cy, r, _fill, tip = mapdraw.start_mark(summary, True, scale)
    want = [v for point in mapdraw.star_points(cx, cy, r) for v in point]
    assert canvas.coords(stars[0]) == pytest.approx(want)
    # the SVG draws the same corners (scale 1 there; same formula)
    svg_cx, svg_cy, svg_r, *_ = mapdraw.start_mark(summary, True, 1)
    assert (cx / scale, cy / scale, r / scale) == pytest.approx((svg_cx, svg_cy, svg_r))
    # on the tile of summary["start"]
    tile_x0 = 10 * mapdraw.CELL_W * scale
    assert tile_x0 < cx < tile_x0 + mapdraw.CELL_W * scale
    texts = labels_of(window)
    assert "Start" in texts and map_view.FIRST_CAMPAIGN in texts
    # the pointer on the star shows the tooltip line, and takes it away again
    window.update()
    canvas.event_generate("<Enter>", x=round(cx), y=round(cy))
    canvas.event_generate("<Motion>", x=round(cx), y=round(cy))
    pump(map_app, lambda: window.info_var.get() == tip, 1.0)
    assert window.info_var.get() == "Your company starts here."
    # (the star lies above the towns: it is the last item drawn but the north arrow)
    assert canvas.find_all().index(stars[0]) > max(canvas.find_all().index(i) for i in canvas.find_all()
                                                   if canvas.type(i) == "oval")


@pytest.mark.edge
def test_the_map_window_has_no_first_campaign_note_on_the_base_game(map_app):
    from bbreroll import map_view
    window, _summary = start_window(map_app, VANILLA_VERIFIED)
    canvas = canvas_of(window)
    assert [i for i in canvas.find_all() if canvas.type(i) == "polygon" and canvas.itemcget(i, "fill") == "#ffd400"]
    texts = labels_of(window)
    assert "Start" in texts and map_view.FIRST_CAMPAIGN not in texts


@pytest.mark.dirty
def test_the_map_window_draws_no_star_when_the_setup_is_not_verified_or_the_start_is_not_known(map_app):
    from bbreroll import map_view
    from bbseed import mapdraw
    unverified = dict(LEGENDS_VERIFIED, game_version="1.5.2.4")
    for info, start in ((unverified, (10, 25)), (LEGENDS_VERIFIED, None), ({}, (10, 25))):
        for window in list(map_app._map_windows.values()):
            window.destroy()
        map_app._map_windows.clear()
        window, _summary = start_window(map_app, info, start)
        canvas = canvas_of(window)
        assert not [i for i in canvas.find_all() if canvas.type(i) == "polygon" and canvas.itemcget(i, "fill") == mapdraw.START_FILL]
        texts = labels_of(window)
        assert "Start" not in texts and map_view.FIRST_CAMPAIGN not in texts
        assert [canvas.type(i) for i in canvas.find_all()].count("polygon") == 2, "only the north arrow's two plates"


def roads_window(app, info, roads=True, seed="2222222222"):
    """The map window of small_map() (30 x 40) with a road: (10,5) - (11,5) east, (11,5) - (11,6) north, and (11,6) NE."""
    from bbseed.mapdraw import ROAD_CHARS
    chars = ["."] * (30 * 40)
    chars[5 * 30 + 10] = ROAD_CHARS[2]              # (10,5) is an even column: NE is (11,5)
    chars[5 * 30 + 11] = ROAD_CHARS[16 | 1]         # (11,5): SW back to (10,5) and N to (11,6)
    chars[6 * 30 + 11] = ROAD_CHARS[8]              # (11,6): S back to (11,5)
    summary = dict(small_map(), roads="".join(chars)) if roads else small_map()
    app._run = dict(RUN, north_band=33)
    entry = result(app, seed, summary)
    entry["info"] = dict(info)
    app._show_map(entry)
    pump(app, lambda: False, 0.2)
    return next(iter(app._map_windows.values())), summary


@pytest.mark.core
def test_the_map_window_draws_the_roads_like_the_svg_and_names_them_in_the_legend(map_app):
    """The roads: one canvas line per segment of mapdraw.road_segments (the SVG's path has the same numbers), brown,
    above the terrain and below the band, the towns and the star; the legend has "Road"."""
    from bbseed import mapdraw
    window, summary = roads_window(map_app, LEGENDS_VERIFIED)
    canvas, scale = canvas_of(window), window.scale
    items = canvas.find_all()
    road = [i for i in items if canvas.type(i) == "line" and canvas.itemcget(i, "fill") == mapdraw.ROAD_COLOUR]
    segments = mapdraw.road_segments(summary, True, scale)
    assert len(segments) == 4 and len(road) == 4
    assert [v for i in road for v in canvas.coords(i)] == pytest.approx([v for seg in segments for v in seg])
    assert all(int(float(canvas.itemcget(i, "width"))) == max(1, round(mapdraw.ROAD_WIDTH * scale)) for i in road)
    assert all(canvas.itemcget(i, "capstyle") == "round" for i in road)
    # the SVG's numbers at scale 1 are the canvas' at scale 1 (one function gives both)
    svg_text = mapdraw.svg(summary, verified=True)
    assert "brown line = road" in svg_text and svg_text.count('class="roads"') == 1
    assert [v for seg in segments for v in seg] == pytest.approx(
        [scale * v for seg in mapdraw.road_segments(summary, True) for v in seg])
    # layers: above every terrain rectangle, below the band's dashed line, the towns' circles and the north arrow
    index = {i: n for n, i in enumerate(items)}
    rects = [index[i] for i in items if canvas.type(i) == "rectangle"]
    above = [index[i] for i in items if canvas.type(i) != "rectangle" and i not in road]
    assert above and max(rects) < min(index[i] for i in road) and max(index[i] for i in road) < min(above)
    texts = labels_of(window)
    assert mapdraw.ROAD_LABEL in texts and "Road" in texts


@pytest.mark.dirty
def test_the_map_window_has_no_roads_without_a_verified_setup_or_without_roads_in_the_summary(map_app):
    from bbseed import mapdraw
    unverified = dict(LEGENDS_VERIFIED, game_version="1.5.2.4")
    for info, roads in ((unverified, True), ({}, True), (LEGENDS_VERIFIED, False)):      # False: a summary cached before
        for window in list(map_app._map_windows.values()):
            window.destroy()
        map_app._map_windows.clear()
        window, _summary = roads_window(map_app, info, roads)
        canvas = canvas_of(window)
        assert not [i for i in canvas.find_all() if canvas.itemcget(i, "fill") == mapdraw.ROAD_COLOUR]
        assert [canvas.type(i) for i in canvas.find_all()].count("line") == 1, "only the band's line"
        assert "Road" not in labels_of(window)


@pytest.mark.dirty
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
@pytest.mark.edge
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
    assert app.status_var.get() == ("Each map takes about 25 seconds. "
                                    "The estimate shows after 30 maps. Maps built: 6.")
    assert "Land Mass" not in app.grid_help.cget("text") and "default Map Options" not in app.status_var.get()


@pytest.mark.dirty
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


@pytest.mark.edge
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


# ---------------------------------------------------------------- Deserters (stage 2 C2 Task 4)
VERIFIED_LEGENDS_MODS = ["mod_legends-19.4.22.zip", "mod_legends-assets-19.4.3.zip",
                         "mod_modern_hooks-685-0-6-0-1748620177.zip", "mod_msu 479 1.9.0 2026-06-23T04-27Z eVJjKbX9c.zip"]


@pytest.fixture()
def deserters_app(map_app, monkeypatch):
    """The window on a setup whose maps are verified (the fixture's mod file has no version: not verified), with
    Deserters selected."""
    from bbreroll import offline_origins as O
    monkeypatch.setitem(O.FOUND, "mods", VERIFIED_LEGENDS_MODS)
    map_app.setup_var.set("Legends")
    map_app._on_setup_change()
    map_app.origin_var.set("Deserters")
    map_app._on_origin_change("Deserters")
    yield map_app
    monkeypatch.undo()
    map_app.origin_var.set("Trading Caravan")
    map_app._on_origin_change("Trading Caravan")


@pytest.mark.dirty
def test_deserters_are_offered_with_a_note_on_a_verified_setup_only(map_app, monkeypatch):
    from bbreroll import map_view
    from bbreroll import offline_origins as O
    app = map_app
    # the fixture's setup: a mod file without a version, so the maps are not verified
    assert "Deserters" not in O.names_for("Legends")
    app.origin_var.set("Deserters")
    app._on_origin_change("Deserters")
    assert app.origin_var.get() != "Deserters"
    assert "The Deserters origin is not in the list. Deserters need the world map." in app.origin_info_var.get()
    monkeypatch.setitem(O.FOUND, "mods", VERIFIED_LEGENDS_MODS)
    app.origin_var.set("Deserters")
    app._on_origin_change("Deserters")
    assert app.origin_var.get() == "Deserters" and app.bro_count_var.get() == "3"
    assert map_view.DESERTERS_INFO in app.origin_info_var.get()
    assert "is not in the list" not in app.origin_info_var.get()
    app._on_origin_change("Deserters")
    assert app.origin_info_var.get().count(map_view.DESERTERS_INFO) == 1, "the note is not added twice"
    app.origin_var.set("Trading Caravan")
    app._on_origin_change("Trading Caravan")
    assert map_view.DESERTERS_INFO not in app.origin_info_var.get()


@pytest.mark.core
def test_a_deserters_search_always_sends_the_map_options_and_builds_every_map(deserters_app, calls):
    from bbreroll import map_view
    app = deserters_app
    app.map_option_vars["Settlements"].set("24")
    app.map_option_vars["StackCitadels"].set("Yes")
    app.workers_var.set("8")
    app.stars_vars[("1", "res")].set("1")
    app._on_search()
    assert "Deserters make their brothers on the map." in app.status_var.get()
    assert "With 8 workers, the search tests about 19.2 seeds each minute." in app.status_var.get()
    pump(app, lambda: calls and not app._searching)
    (call,) = calls
    assert call["origin"] == "deserters_scenario" and "map" not in call["criteria"] and call["workers"] == 8
    settings = call["mod_settings"]
    assert sorted(k for k in settings if k != "mod_legends:GenderEquality") == sorted("mod_legends:" + k
                                                                                      for k in MAP_OPTION_KEYS)
    assert settings["mod_legends:Settlements"] == 24 and settings["mod_legends:StackCitadels"] is True
    assert app._run["deserters"] is True and app._run["map_first"] is True and app._run["workers"] == 8
    assert app.errors == []


@pytest.mark.core
def test_a_deserters_check_builds_the_map_too(deserters_app, calls):
    app = deserters_app
    app.map_option_vars["Factions"].set("5")
    app.check_seed_var.set("1234567890")
    app._on_check_seed()
    from bbreroll import map_view
    assert map_view.DESERTERS_INFO in app.status_var.get() and "tests about" not in app.status_var.get()
    pump(app, lambda: calls and not app._searching)
    assert calls[0]["seeds"] == ["1234567890"] and calls[0]["mod_settings"]["mod_legends:Factions"] == 5


@pytest.mark.dirty
def test_a_wrong_map_option_stops_a_deserters_search_but_not_other_origins(deserters_app, calls):
    app = deserters_app
    app.map_option_vars["Water"].set("abc")
    assert search_now(app, calls) == [] and app.errors and "Water must be a whole number" in app.errors[-1][1]
    app.errors.clear()
    app.check_seed_var.set("1234567890")
    app._on_check_seed()
    assert calls == [] and app.errors and "Water must be a whole number" in app.errors[-1][1]
    app.errors.clear()
    app.origin_var.set("Trading Caravan")
    app._on_origin_change("Trading Caravan")
    assert len(search_now(app, calls)) == 1 and app.errors == []


@pytest.mark.dirty
def test_deserters_need_working_maps(deserters_app, calls):
    from bbreroll import map_view
    app = deserters_app
    app._map_off = True             # a map fatal turned the maps off
    try:
        assert search_now(app, calls) == []
        assert app.errors and app.errors[-1][1].startswith(map_view.DESERTERS_NEEDS_MAPS)
    finally:
        app._map_off = False


@pytest.mark.edge
def test_a_vanilla_deserters_search_has_no_map_options(deserters_app, calls):
    app = deserters_app
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    assert app.origin_var.get() == "Deserters"
    (call,) = search_now(app, calls)
    assert call["profile"] == "vanilla" and call["origin"] == "deserters_scenario" and call["mod_settings"] is None
    assert app._run["deserters"] is True


@pytest.mark.edge
def test_the_progress_of_a_deserters_search_waits_for_30_seeds(deserters_app):
    app = deserters_app
    app._run = dict(RUN, origin="Deserters", deserters=True, map_first=True, workers=4)
    app._search_total = 1000
    app._ev_progress((6, 90.0, 0, {"chance": None, "never": [], "never_any": False, "never_map": False,
                                   "maps": 6, "tested": 6}))
    assert app.status_var.get() == ("Each seed needs its whole map. A map takes about 25 seconds for each worker. "
                                    "The estimate of the odds shows after 30 seeds. Seeds tested: 6.")
    app._ev_progress((30, 600.0, 0, {"chance": 0.04, "never": [], "never_any": False, "never_map": False,
                                     "maps": 30, "tested": 30}))
    assert app.status_var.get().startswith("Approximately 1 in 25 seeds matches (from 30 seeds).")
    assert "maps" not in app.status_var.get()


@pytest.mark.core
def test_a_deserters_seed_post_lists_the_map_options_and_the_counter_line(deserters_app, calls):
    app = deserters_app
    app.map_option_vars["Settlements"].set("24")
    search_now(app, calls)
    options = {"LandRatio": 50, "Water": 38, "Snowline": 85, "Settlements": 24, "Factions": 3,
               "StackCitadels": False, "AllTradeLocations": False}
    app._ev_ready((1, 1, {"legends_version": "19.4.22", "legends_build": "Bandits & Greenskins",
                          "game_version": "1.5.2.3", "battle_sisters": "Enabled", "mods": [], "map_options": options}))
    app._ev_match({"seed": "0000000001", "stable": True, "failure": None, "map": None, "roster": [
        {"name": "A", "background": "background.deserter", "background_name": "Background: Deserter",
         "stars": {"hp": 1, "msk": 2}, "traits": [], "trait_names": []}]})
    text = app._share_report(app._matches[0])
    assert "Origin: Deserters" in text and "Settlements: 24" in text
    assert text.count("Start this seed as your first campaign after you start the game.") == 1
    assert "Map Options: any" not in text and "\nMap:" not in text


def _card_texts(app):
    """Every label text in the result list."""
    import gui
    out = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, gui.ctk.CTkLabel):         # (a CTkLabel holds a tk label of its own with the same text)
                out.append(child.cget("text"))
            else:
                walk(child)
    walk(app.match_list)
    return out


def _deserters_match(app, legends):
    app._run = dict(RUN, origin="Deserters", deserters=True, map_first=True, workers=2)
    app._report_info = dict(app._report_info, legends=legends)
    app._ev_match({"seed": "0000000001", "stable": True, "failure": None, "map": None, "roster": [
        {"name": "A", "background": "background.deserter", "background_name": "Background: Deserter",
         "stars": {"hp": 1, "msk": 2}, "traits": [], "trait_names": []}]})


@pytest.mark.core
def test_a_deserters_result_on_legends_shows_the_first_campaign_line(deserters_app):
    """Not only the seed post: the result card says to start the seed as the first campaign (the maps are built at
    counter 0), for every Deserters result on Legends."""
    from bbseed.mapgen import FIRST_CAMPAIGN
    app = deserters_app
    try:
        _deserters_match(app, legends=True)
        assert _card_texts(app).count(FIRST_CAMPAIGN) == 1
    finally:
        app._matches.clear()
        app._render_match_list()


@pytest.mark.edge
def test_a_vanilla_or_other_result_shows_no_first_campaign_line(deserters_app):
    from bbseed.mapgen import FIRST_CAMPAIGN
    app = deserters_app
    try:
        _deserters_match(app, legends=False)            # the base game: no black-market counter
        assert FIRST_CAMPAIGN not in _card_texts(app)
        app._matches.clear()
        app._run = dict(RUN, origin="Trading Caravan")
        app._report_info = dict(app._report_info, legends=True)
        app._ev_match({"seed": "0000000002", "stable": True, "failure": None, "map": None, "roster": [
            {"name": "B", "background": "background.fisherman", "background_name": "Background: Fisherman",
             "stars": {"hp": 1}, "traits": [], "trait_names": []}]})
        assert FIRST_CAMPAIGN not in _card_texts(app)
    finally:
        app._matches.clear()
        app._render_match_list()


@pytest.mark.core
def test_the_deserters_info_tells_a_legends_player_to_use_the_same_map_options(deserters_app):
    from bbreroll import map_view
    assert map_view.DESERTERS_INFO.endswith(" Use the same Map Options in the game.")
    assert "Map Options" not in map_view.DESERTERS_INFO_BASE, "the base game has no Map Options"
    assert map_view.deserters_info("Legends") == map_view.DESERTERS_INFO
    assert map_view.deserters_info("Vanilla") == map_view.DESERTERS_INFO_BASE
    assert "about 25 seconds" in map_view.DESERTERS_INFO and "Use the same Map Options" in map_view.deserters_note(4)
    assert "Map Options" not in map_view.deserters_note(4, "Vanilla")
    app = deserters_app
    assert map_view.DESERTERS_INFO in app.origin_info_var.get()
    app.setup_var.set("Vanilla")
    app._on_setup_change()
    assert map_view.DESERTERS_INFO_BASE in app.origin_info_var.get()
    assert "Map Options" not in app.origin_info_var.get()


@pytest.mark.dirty
def test_a_failed_catalog_build_is_tried_again_when_the_mods_change(app, monkeypatch):
    # B-3 (a player's 4.2.0 report): a build that failed (a broken mod) was kept for the whole session, so after the
    # player removed the mod the origin info still said "Cannot read what the origins can roll"
    from bbseed import catalog
    signature = {"mods": "with-the-broken-mod"}
    monkeypatch.setattr(catalog, "path", lambda profile=None, mod_settings=None: Path(signature["mods"]))
    monkeypatch.setattr(catalog, "load", lambda *a, **k: None)
    builds = []
    good = {"talents": {}, "origins": []}

    def fake_build(profile, **kw):
        builds.append(profile)
        if len(builds) == 1:
            kw["on_event"]("fatal", "3 script files failed to load, first: stdlib/packer")
            return None
        return good
    monkeypatch.setattr(catalog, "build", fake_build)
    monkeypatch.setattr(gui_module().App, "_ensure_catalog", app.real_ensure_catalog)
    app.setup_var.set("Legends")
    app._on_setup_change()
    app._catalogs.pop("legends", None)
    app._catalog_failed.clear()
    app._catalog_job = None
    try:
        app._ensure_catalog()
        pump(app, lambda: builds and app._catalog_job is None and "legends" in app._catalog_failed)
        assert builds == ["legends"]
        assert "legends" in app._catalog_failed and "legends" not in app._catalogs, "a failure is not kept as the answer"
        assert "Cannot read what the origins can roll" in app.origin_info_var.get()
        # nothing changed: no new attempt, however often an origin is picked
        app._on_origin_change(app.origin_var.get())
        pump(app, lambda: False, 0.4)
        app._ensure_catalog()
        pump(app, lambda: False, 0.2)
        assert builds == ["legends"]
        # the mods changed: the next origin pick builds again, the build works, the old line goes
        signature["mods"] = "without-the-broken-mod"
        app._on_origin_change(app.origin_var.get())
        pump(app, lambda: "legends" in app._catalogs)
        assert builds == ["legends", "legends"]
        assert app._catalogs["legends"] == good and "legends" not in app._catalog_failed
        assert "Cannot read what" not in app.origin_info_var.get()
        assert "Reading what" not in app.origin_info_var.get()
    finally:
        app._catalogs.pop("legends", None)
        app._catalog_failed.clear()
        app._catalog_job = None
        app._refresh_origin_info()


def gui_module():
    import gui
    return gui


@pytest.mark.dirty
def test_the_status_does_not_count_seeds_that_could_not_be_tested_as_tested(map_app):
    # B-4: "4,890 seeds tested ... 4912 could not be tested" read as if half of the seeds failed. The failed seeds
    # are part of the search's count: the status shows the seeds that were tested, and the failed ones apart.
    app = map_app
    app._run = dict(RUN, errors=22)
    app._searching = True
    app._ev_finished((4912, 3.0, 0, False))
    assert app.status_var.get().startswith("Search complete: 4,890 seeds tested in 3s, 0 matches, "
                                           "22 seeds could not be tested.")
    app._run = dict(RUN, errors=1)
    app._ev_finished((5, 3.0, 1, False))
    assert app.status_var.get().startswith("Search complete: 4 seeds tested in 3s, 1 match, 1 seed could not be tested.")
    app._run = dict(RUN, errors=7)
    app._ev_finished((7, 3.0, 0, False))
    assert app.status_var.get().startswith("Search complete: 0 seeds tested in 3s, 0 matches, 7 seeds could not be tested.")
    app._run = dict(RUN)
    app._ev_finished((1, 3.0, 0, False))
    assert app.status_var.get().startswith("Search complete: 1 seed tested in 3s, 0 matches.")


@pytest.mark.edge
def test_the_map_window_marks_city_state_names_only_off_a_verified_setup(map_app):
    """Stage 2 B2 checked the city states' names against the game: on a verified setup (the one that gets the start
    star) the tooltip of a city state is the plain name; on any other setup it says "(name not verified)"."""
    from bbseed import mapdraw
    for info, marked in ((LEGENDS_VERIFIED, False), (dict(LEGENDS_VERIFIED, game_version="1.5.2.4"), True)):
        window, summary = start_window(map_app, info, seed="4444444444" if marked else "5555555555")
        canvas, scale = canvas_of(window), window.scale
        cx, cy, *_ = mapdraw.town_marks(summary, scale, not marked)[0]       # the southern port, a city state
        window.update()
        canvas.event_generate("<Enter>", x=round(cx), y=round(cy))
        canvas.event_generate("<Motion>", x=round(cx), y=round(cy))
        pump(map_app, lambda: window.info_var.get().startswith("Town 3/2"), 1.0)
        assert window.info_var.get().startswith("Town 3/2"), window.info_var.get()
        assert ("(name not verified)" in window.info_var.get()) is marked
        window.destroy()
        map_app._map_windows.clear()


# ====================================================================== the results list
# A card is added, replaced or removed on its own: rebuilding the whole list for each match kept the window busy
# with many matches (A New Company, ~1 match in 8 seeds).
def _checked_match(app, seed, roster=None):
    app._run = {"origin": "Trading Caravan", "setup": "Legends", "checking": True}
    app._ev_match({"seed": seed, "roster": roster or roster_of(), "stable": True, "failure": None})
    return app._matches[0]


def _cards(app):
    """The cards on the screen, top first."""
    return app.match_list.pack_slaves()


@pytest.mark.core
def test_a_new_match_leaves_the_other_cards_alone(app):
    try:
        first = _checked_match(app, "0000000001")["card"]
        inside = first.winfo_children()
        new = _checked_match(app, "0000000002")["card"]
        assert _cards(app) == [new, first], "the newest card is on top, the other one is the same widget"
        assert first.winfo_exists() and first.winfo_children() == inside
    finally:
        app._clear_matches()


@pytest.mark.edge
def test_two_hundred_results_can_be_removed_toggled_and_cleared(app):
    roster = [dict(b, rolls={"hp": {"lo": 0, "hi": 9, "value": 5, "tier": "high"}}) for b in roster_of()]
    try:
        for n in range(200):
            _checked_match(app, "%010d" % n, roster)
        assert len(_cards(app)) == 200
        assert [m["card"] for m in app._matches] == _cards(app), "the cards are in the order of the list"
        gone = app._matches[100]
        app._dismiss_match(gone)
        assert len(_cards(app)) == 199 and not gone["card"].winfo_exists()
        shown = app._matches[50]
        others = [m["card"] for m in app._matches if m is not shown]
        app._toggle_perks(shown)
        assert len(_cards(app)) == 199
        assert [m["card"] for m in app._matches] == _cards(app), "Details leaves the card in its place"
        assert others == [m["card"] for m in app._matches if m is not shown], "and the other cards alone"
        assert any("Rolls:" in t for t in _card_texts(app))
        app._toggle_perks(shown)
        assert not any("Rolls:" in t for t in _card_texts(app))
        app._clear_matches()
        assert _cards(app) == [] and app.match_list.winfo_children() == []
    finally:
        app._clear_matches()


@pytest.mark.core
def test_the_same_seed_again_replaces_its_card(app):
    try:
        old = _checked_match(app, "0000000001")["card"]
        other = _checked_match(app, "0000000002")["card"]
        new = _checked_match(app, "0000000001")["card"]
        assert not old.winfo_exists()
        assert _cards(app) == [new, other], "no second card for the seed"
    finally:
        app._clear_matches()


@pytest.mark.edge
def test_the_list_height_stops_growing_at_its_limit(app):
    try:
        for n in range(30):
            _checked_match(app, "%010d" % n)
        assert app.match_list.cget("height") == 300
    finally:
        app._clear_matches()


@pytest.mark.edge
def test_the_long_deserters_note_wraps_inside_the_window(app):
    from bbreroll import map_view
    before = app.origin_info_var.get()
    app.deiconify()
    app.geometry("980x940+40+40")
    try:
        app.origin_info_var.set(map_view.DESERTERS_INFO + " " + map_view.DESERTERS_INFO)
        pump(app, lambda: False, 0.3)
        assert app.origin_info_label.winfo_reqwidth() <= app.winfo_width()
    finally:
        app.origin_info_var.set(before)
        app.withdraw()


@pytest.mark.core
def test_many_matches_pull_the_window_forward_once_and_notify_once(app, monkeypatch):
    import gui
    surfaced, told = [], []
    monkeypatch.setattr(app, "_surface_window", lambda: surfaced.append(1))
    monkeypatch.setattr(gui, "notification", type("N", (), {"notify": staticmethod(lambda **k: told.append(k))}))
    monkeypatch.setattr(app, "_announced", {}, raising=False)
    now = [1000.0]
    monkeypatch.setattr(gui.time, "time", lambda: now[0])
    app._run = {"origin": "Trading Caravan", "setup": "Legends", "checking": False}
    match = lambda n: app._ev_match({"seed": "%010d" % n, "roster": roster_of(), "stable": True, "failure": None})
    try:
        for n in range(20):
            match(n)
        assert (len(surfaced), len(told)) == (1, 1)
        now[0] += gui.SURFACE_SECONDS
        match(20)
        assert (len(surfaced), len(told)) == (2, 1), "the window again after its time on top ends"
        now[0] += gui.NOTIFY_SECONDS
        match(21)
        assert (len(surfaced), len(told)) == (3, 2), "a notice again when the last one is gone"
    finally:
        app._clear_matches()


@pytest.mark.edge
def test_a_long_queue_of_events_leaves_the_window_time_for_stop(app, monkeypatch):
    """Stop is a window event: with events always waiting the drain never gave it a turn (A New Company, 1,656 events
    waiting and Stop not run after 200 s)."""
    left = []

    def slow(payload):
        if payload == 0:
            app.after(1, lambda: left.append(app._events.qsize()))
        time.sleep(0.01)
    monkeypatch.setattr(app, "_ev_slow", slow, raising=False)
    for n in range(100):
        app._events.put(("slow", n))
    pump(app, lambda: left and app._events.empty(), 10.0)
    assert app._events.empty(), "every event is handled"
    assert left and left[0] > 0, "the window had its turn before the queue was empty"


# ====================================================================== the map as a picture
def _buttons_of(widget):
    return [w for w in _walk(widget) if isinstance(w, ctk.CTkButton)]


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _press(widget, text):
    (button,) = [b for b in _buttons_of(widget) if b.cget("text") == text]
    button.invoke()


@pytest.mark.core
def test_the_map_window_copies_its_picture(map_app):
    from bbreroll import map_picture
    entry = result(map_app, "1111111111", small_map())
    try:
        map_app._show_map(entry)
        window = map_app._map_windows[(entry["setup"], entry["origin"], entry["seed"])]
        map_app.update()
        _press(window, "Copy map picture")
        map_app.update()
        assert map_picture.clipboard_picture_size() == map_app._map_picture(entry).size
        assert map_app.status_var.get() == gui_text().MAP_PICTURE_COPIED
        assert window.info_var.get() == gui_text().MAP_PICTURE_COPIED
        window.destroy()
    finally:
        map_app._clear_matches()


def gui_text():
    import gui
    return gui


@pytest.mark.core
def test_a_result_with_a_map_copies_and_saves_its_picture(map_app, monkeypatch, tmp_path):
    from PIL import Image
    from bbreroll import map_picture
    entry = result(map_app, "1111111111", small_map())
    try:
        _press(entry["card"], "Copy map picture")
        assert map_picture.clipboard_picture_size() == map_app._map_picture(entry).size
        path = tmp_path / "picture.png"
        asked_for = []

        def ask(**kw):
            asked_for.append(kw)
            return str(path)
        monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", ask)
        _press(entry["card"], "Save map picture")
        assert asked_for[0]["initialfile"] == "map_1111111111.png"
        with Image.open(path) as back:
            assert back.size == map_app._map_picture(entry).size
        assert str(path) in map_app.status_var.get()
    finally:
        map_app._clear_matches()


@pytest.mark.edge
def test_a_result_without_a_map_has_no_picture_button(map_app):
    entry = result(map_app, "1111111111")
    try:
        texts = [b.cget("text") for b in _buttons_of(entry["card"])]
        assert "Copy map picture" not in texts and "Save map picture" not in texts
    finally:
        map_app._clear_matches()


@pytest.mark.edge
def test_a_cancelled_save_changes_nothing(map_app, monkeypatch):
    entry = result(map_app, "1111111111", small_map())
    try:
        map_app.status_var.set("before")
        monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kw: "")
        _press(entry["card"], "Save map picture")
        assert map_app.status_var.get() == "before"
    finally:
        map_app._clear_matches()


@pytest.mark.dirty
def test_a_failed_copy_or_save_says_why_in_the_status_line(map_app, monkeypatch, tmp_path):
    from bbreroll import map_picture
    entry = result(map_app, "1111111111", small_map())
    try:
        monkeypatch.setattr(map_picture, "copy_to_clipboard", lambda image: map_picture.NO_CLIPBOARD)
        _press(entry["card"], "Copy map picture")
        assert map_app.status_var.get() == map_picture.NO_CLIPBOARD
        monkeypatch.setattr(map_picture, "save_png", lambda image, path: "Cannot save the map picture: no.")
        monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kw: str(tmp_path / "x.png"))
        _press(entry["card"], "Save map picture")
        assert map_app.status_var.get() == "Cannot save the map picture: no."
        monkeypatch.setattr(map_picture, "render", lambda *a, **k: (_ for _ in ()).throw(ValueError("damaged")))
        _press(entry["card"], "Copy map picture")
        assert "damaged" in map_app.status_var.get()
    finally:
        map_app._clear_matches()


# ====================================================================== the closest seed
NEAR_DIFFERENCE = [{"slot": 2, "kind": "stars", "name": "res", "have": 1, "want": 2}]


def near_payload(seed="0000000007", distance=(0, 1, 0), confirmed=True, roster=True, summary=None, differences=None):
    return {"seed": seed, "roster": roster_of() if roster else None, "map": summary, "distance": distance,
            "confirmed": confirmed, "differences": NEAR_DIFFERENCE if differences is None else differences}


@pytest.fixture()
def near_app(map_app):
    map_app._run = dict(RUN)
    map_app._forget_near()
    yield map_app
    map_app._forget_near()
    map_app._clear_matches()
    map_app._forget_near()


def near_card_seed(app):
    return app._near["seed"] if app._near else None


@pytest.mark.core
def test_the_near_card_says_it_is_not_exact_and_lists_the_differences(near_app):
    from bbreroll import near_view
    near_app._ev_near(near_payload())
    texts = _card_texts(near_app)
    assert near_view.TITLE in texts
    assert any("Seed 0000000007" in t for t in texts)
    assert "Brother 2: RES has 1 star. The condition is 2." in "\n".join(texts)
    assert near_view.NOT_CHECKED not in texts
    assert near_app.match_pane.winfo_manager() == "grid", "the results part shows"
    assert near_app._matches == [], "it is no match: nothing counts it as one"


@pytest.mark.core
def test_a_nearer_seed_replaces_the_card(near_app):
    near_app._ev_near(near_payload())
    old = near_app._near["card"]
    near_app._ev_near(near_payload(seed="0000000008", distance=(0, 0, 1)))
    assert not old.winfo_exists() and near_card_seed(near_app) == "0000000008"
    assert _cards(near_app) == [near_app._near["card"]], "one card"


@pytest.mark.core
def test_an_exact_match_removes_the_card(near_app):
    near_app._ev_near(near_payload())
    card = near_app._near["card"]
    near_app._run = dict(RUN, checking=True)        # (a checked seed does not pull the window forward)
    near_app._ev_match({"seed": "0000000009", "roster": roster_of(), "stable": True, "failure": None})
    assert near_app._near is not None, "a checked seed is no search result: the card stays"
    near_app._run = dict(RUN)
    near_app._announced["surface"] = near_app._announced["notify"] = time.time()
    near_app._ev_match({"seed": "0000000010", "roster": roster_of(), "stable": True, "failure": None})
    assert near_app._near is None and not card.winfo_exists()


@pytest.mark.edge
def test_a_match_card_goes_under_the_near_card_and_a_near_card_over_the_matches(near_app):
    near_app._ev_near(near_payload())
    near_app._run = dict(RUN, checking=True)
    first = _checked_match(near_app, "0000000009")["card"]
    assert _cards(near_app) == [near_app._near["card"], first]
    near_app._ev_near(near_payload(seed="0000000008", distance=(0, 0, 1)))
    assert _cards(near_app) == [near_app._near["card"], first]


@pytest.mark.edge
def test_a_dismissed_near_seed_stays_away_until_a_nearer_one_comes(near_app):
    near_app._ev_near(near_payload(distance=(0, 2, 0)))
    _press(near_app._near["card"], "✕")
    assert near_app._near is None
    assert _cards(near_app) == [] and near_app.match_pane.winfo_manager() == ""
    near_app._ev_near(near_payload(distance=(0, 2, 0)))         # the same seed, its checked copy
    near_app._ev_near(near_payload(seed="0000000008", distance=(0, 3, 0)))
    assert near_app._near is None
    near_app._ev_near(near_payload(seed="0000000009", distance=(0, 1, 0)))
    assert near_card_seed(near_app) == "0000000009" and len(_cards(near_app)) == 1


@pytest.mark.edge
def test_clear_while_the_search_runs_counts_as_dismissed(near_app):
    near_app._ev_near(near_payload(distance=(0, 2, 0)))
    near_app._clear_matches()
    assert near_app._near is None and _cards(near_app) == []
    near_app._ev_near(near_payload(distance=(0, 2, 0)))
    assert near_app._near is None
    near_app._ev_near(near_payload(seed="0000000009", distance=(0, 1, 0)))
    assert len(_cards(near_app)) == 1


@pytest.mark.edge
def test_a_full_rebuild_of_the_list_keeps_the_near_card_on_top(near_app):
    near_app._ev_near(near_payload())
    _checked_match(near_app, "0000000009")
    near_app._render_match_list()
    assert _cards(near_app) == [near_app._near["card"], near_app._matches[0]["card"]]


@pytest.mark.edge
def test_a_new_search_removes_the_old_near_card_and_forgets_what_was_dismissed(near_app, calls):
    near_app._ev_near(near_payload(distance=(0, 2, 0)))
    near_app.origin_var.set("Trading Caravan")
    near_app._on_origin_change("Trading Caravan")
    near_app.stars_vars[("1", "res")].set("1")
    near_app._on_search()
    pump(near_app, lambda: calls and not near_app._searching)
    assert near_app._near is None and _cards(near_app) == []
    near_app._ev_near(near_payload(distance=(0, 5, 0)))
    assert near_app._near is not None


@pytest.mark.core
def test_the_seed_post_of_a_near_seed_says_not_an_exact_match(near_app):
    near_app._ev_near(near_payload())
    post = near_app._share_report(near_app._near)
    assert "Not an exact match." in post
    assert "Brother 2: RES has 1 star. The condition is 2." in post
    assert "Seed: 0000000007" in post
    _press(near_app._near["card"], "Copy seed post")
    assert near_app.clipboard_get() == post


@pytest.mark.core
def test_the_build_map_button_uses_the_check_path_and_builds_one_map(near_app, calls):
    near_app._run = dict(RUN, map={"ports": 4})
    near_app.origin_var.set("Trading Caravan")
    near_app._on_origin_change("Trading Caravan")
    near_app.map_vars["ports"].set("4")
    near_app._ev_near(near_payload())
    _press(near_app._near["card"], "Build map")
    pump(near_app, lambda: calls and not near_app._searching)
    assert len(calls) == 1 and calls[0]["seeds"] == ["0000000007"] and calls[0]["criteria"]["map"]["ports"] == 4
    assert near_app._near is not None, "the check leaves the card"


@pytest.mark.edge
def test_build_map_during_a_search_says_to_stop_first(near_app, calls):
    near_app._run = dict(RUN, map={"ports": 4})
    near_app.map_vars["ports"].set("4")
    near_app._ev_near(near_payload())
    near_app._searching = True
    try:
        _press(near_app._near["card"], "Build map")
        assert calls == [] and "Stop the search" in near_app.status_var.get()
    finally:
        near_app._searching = False


@pytest.mark.edge
def test_a_roster_only_near_card_has_no_map_button(near_app):
    near_app._ev_near(near_payload())
    texts = [b.cget("text") for b in _buttons_of(near_app._near["card"])]
    assert "Build map" not in texts and "Show map" not in texts and "Check this seed" not in texts
    assert "Copy seed" in texts and "Copy roster" in texts and "Copy seed post" in texts


@pytest.mark.core
def test_a_map_per_seed_near_card_says_not_checked_yet(near_app, calls):
    near_app._run = dict(RUN, map={"ports": 4})
    from bbreroll import near_view
    near_app.origin_var.set("Trading Caravan")
    near_app._on_origin_change("Trading Caravan")
    near_app.map_vars["ports"].set("4")
    near_app._ev_near(near_payload(confirmed=False, roster=False, summary=small_map(), distance=(0, 0, 2), differences=[
        {"slot": None, "kind": "map", "name": "ports", "have": 2, "want": 4}]))
    assert any(near_view.NOT_CHECKED in t for t in _card_texts(near_app))
    texts = [b.cget("text") for b in _buttons_of(near_app._near["card"])]
    assert "Copy roster" not in texts and "Show map" in texts and "Build map" not in texts
    _press(near_app._near["card"], "Check this seed")
    pump(near_app, lambda: calls and not near_app._searching)
    assert calls[0]["seeds"] == ["0000000007"]
    assert near_app._share_report(near_app._near)        # a post without brothers


@pytest.mark.edge
def test_a_stopped_search_shows_an_unchecked_roster_as_not_checked_yet(near_app):
    from bbreroll import near_view
    near_app._ev_near(near_payload(confirmed=False))
    assert any(near_view.NOT_CHECKED in t for t in _card_texts(near_app))
    assert "Check this seed" in [b.cget("text") for b in _buttons_of(near_app._near["card"])]
    near_app._ev_near(near_payload(confirmed=True))      # its checked copy: no longer "not checked"
    assert not any(near_view.NOT_CHECKED in t for t in _card_texts(near_app))
    assert len(_cards(near_app)) == 1


@pytest.mark.dirty
def test_a_notice_of_the_search_shows_in_the_banner(app):
    from bbseed.search import EARLY_EXIT_OFF
    app._ev_notice(EARLY_EXIT_OFF)
    try:
        assert app.notice_var.get() == EARLY_EXIT_OFF
    finally:
        app._clear_notice()


# ====================================================================== the optional PyPy download
@pytest.fixture()
def pypy_app(map_app):
    from bbreroll import pypy_addon
    yield map_app
    map_app._find_pypy(Path("X:/no such folder"))
    map_app.pypy_var.set(True)


def _addon_folder(tmp_path, version):
    from bbreroll import pypy_addon
    folder = tmp_path / pypy_addon.FOLDER
    for parts in pypy_addon._NEEDED:
        path = folder.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    (folder / "VERSION").write_text(version, encoding="utf-8")
    return folder


@pytest.mark.core
def test_the_option_shows_only_when_found(pypy_app, tmp_path):
    import gui
    pypy_app.grid_mode_var.set("Map")
    pypy_app._on_grid_mode()
    pypy_app._find_pypy(tmp_path)
    assert pypy_app._pypy is None and pypy_app.pypy_switch.winfo_manager() == ""
    assert pypy_app.map_note_var.get() == "" or "PyPy" not in pypy_app.map_note_var.get()
    _addon_folder(tmp_path, gui.APP_VERSION)
    pypy_app._find_pypy(tmp_path)
    assert pypy_app._pypy is not None and pypy_app.pypy_switch.winfo_manager() == "grid"
    assert pypy_app.pypy_var.get() is True, "on when found"


@pytest.mark.dirty
def test_a_folder_of_another_version_says_why_in_the_map_view(pypy_app, tmp_path):
    _addon_folder(tmp_path, "0.0.1")
    pypy_app._find_pypy(tmp_path)
    assert pypy_app._pypy is None and pypy_app.pypy_switch.winfo_manager() == ""
    assert "0.0.1" in pypy_app.map_note_var.get()


def _search_with_addon(pypy_app, calls, monkeypatch, why=None, map_ports="4", star=False, banned=False):
    """A search with the add-on found; returns the arguments the add-on's search got (None: it was not used)."""
    from bbreroll import pypy_addon
    pypy_app._pypy = pypy_addon.Addon(Path("X:/addon"))
    used = []

    def fake(addon, profile, origin, criteria, workers, count, max_seeds, mod_settings, on_event, should_stop=None, start=None):
        used.append(dict(profile=profile, origin=origin, criteria=criteria, workers=workers, count=count, max_seeds=max_seeds,
                         mod_settings=mod_settings))
        if why:
            return why
        on_event("finished", [0, 0.0, 0, False])
        return None
    monkeypatch.setattr(pypy_addon, "search", fake)
    pypy_app.origin_var.set("Trading Caravan")
    pypy_app._on_origin_change("Trading Caravan")
    pypy_app._bulk_check("banned", banned)      # (a ticked trait is a condition on the brothers)
    pypy_app._bulk_check("required", False)
    pypy_app.map_vars["ports"].set(map_ports)
    if star:
        pypy_app.stars_vars[("1", "res")].set("1")
    pypy_app._on_search()
    pump(pypy_app, lambda: (used or calls) and not pypy_app._searching)
    return used


@pytest.mark.core
def test_a_map_only_search_runs_in_pypy(pypy_app, calls, monkeypatch):
    used = _search_with_addon(pypy_app, calls, monkeypatch)
    assert len(used) == 1 and calls == [], "PyPy, and not the exe's Python"
    assert used[0]["origin"] == "trader_scenario" and used[0]["criteria"]["map"]["ports"] == 4
    assert set(used[0]["mod_settings"]) >= {"mod_legends:Settlements"}, "the Map Options go along"


@pytest.mark.core
def test_a_search_with_brothers_stays_on_the_exes_python(pypy_app, calls, monkeypatch):
    used = _search_with_addon(pypy_app, calls, monkeypatch, star=True)
    assert used == [] and len(calls) == 1


@pytest.mark.core
def test_a_ticked_trait_is_a_search_with_brothers(pypy_app, calls, monkeypatch):
    used = _search_with_addon(pypy_app, calls, monkeypatch, banned=True)
    assert used == [] and len(calls) == 1


@pytest.mark.edge
def test_the_switch_turned_off_stays_on_the_exes_python(pypy_app, calls, monkeypatch):
    pypy_app.pypy_var.set(False)
    used = _search_with_addon(pypy_app, calls, monkeypatch)
    assert used == [] and len(calls) == 1


@pytest.mark.dirty
def test_a_failed_pypy_start_searches_on_in_the_window(pypy_app, calls, monkeypatch):
    used = _search_with_addon(pypy_app, calls, monkeypatch, why="PyPy did not start: no. The search runs without PyPy.")
    assert len(used) == 1 and len(calls) == 1, "tried, then on with the exe's Python"
    pump(pypy_app, lambda: "PyPy did not start" in pypy_app.notice_var.get(), 2.0)
    assert "PyPy did not start" in pypy_app.notice_var.get()


@pytest.mark.edge
def test_a_checked_seed_never_uses_pypy(pypy_app, calls, monkeypatch):
    from bbreroll import pypy_addon
    pypy_app._pypy = pypy_addon.Addon(Path("X:/addon"))
    monkeypatch.setattr(pypy_addon, "search", lambda *a, **k: pytest.fail("a check rolls one seed: no PyPy"))
    pypy_app.origin_var.set("Trading Caravan")
    pypy_app._on_origin_change("Trading Caravan")
    pypy_app.map_vars["ports"].set("4")
    pypy_app.check_seed_var.set("1234567890")
    pypy_app._on_check_seed()
    pump(pypy_app, lambda: calls and not pypy_app._searching)
    assert len(calls) == 1

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
             "legends": True, "reroll_mod": []}
    mp = pytest.MonkeyPatch()
    mp.setattr(profiles, "installed_summary", lambda game_data=None: found)
    mp.setattr(gui, "SETTINGS_PATH", tmp_path_factory.mktemp("gui") / "settings.json")
    mp.setattr(gui.App, "_ensure_catalog", lambda self: None)       # no game, no catalog
    mp.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    errors = []
    mp.setattr(gui.messagebox, "showerror", lambda *a, **k: errors.append(a))
    O.refresh()
    try:
        window = gui.App()
    except Exception as e:          # no display at all
        mp.undo()
        O.refresh()
        pytest.skip("no display: %s" % e)
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

"""The offline search's setup / origin tables (bbreroll/offline_origins.py), and — when the
game is installed — that what they offer really exists in the game's new-campaign menu."""
from pathlib import Path

import pytest

from bbreroll import offline_origins as O
from bbseed import profiles


@pytest.mark.core
def test_setups_are_named_vanilla_and_legends():
    assert (O.LEGENDS, O.VANILLA) == ("Legends", "Vanilla")
    for setup, (profile, _legends) in O.SETUPS.items():
        assert profile in profiles.names()
        names = O.names_for(setup)
        assert ("Deserters" in names) == O.verified_for_maps(setup) and "Trading Caravan" in names
    assert not any(O.is_legends_only(n) for n in O.names_for(O.VANILLA))
    assert not any(O.is_legends_only(n) for n in O.names_for("a setup that does not exist"))


@pytest.mark.core
def test_setups_follow_what_is_installed(monkeypatch):
    def setups(found):
        monkeypatch.setattr(profiles, "installed_summary", lambda game_data=None: found)
        O.refresh()
        return dict(O.SETUPS), O.DEFAULT_SETUP

    try:
        base = {"data": Path("X:/Battle Brothers/data"), "game_version": "1.5.2.3", "reroll_mod": [],
                "dlc_complete": True}
        assert setups(None) == ({}, None)
        assert "cannot find Battle Brothers" in O.found_text() and O.reroll_mod_warning() is None
        assert O.found_short() == "Game not found"
        assert setups(dict(base, mods=[], legends=False)) == ({"Vanilla": ("vanilla", False)}, "Vanilla")
        assert setups(dict(base, mods=["mod_legends.zip", "mod_msu.zip"], legends=True)) == (
            {"Legends": ("legends", True), "Vanilla": ("vanilla", False)}, "Legends")
        assert "2 mod files" in O.found_text() and "mod_msu.zip" in O.found_text(details=True)
        assert O.found_short() == "Battle Brothers 1.5.2.3 · 2 mods"
        assert "Sisterhood" in O.names_for("Legends") and "Sisterhood" not in O.names_for("Vanilla")
        assert setups(dict(base, mods=["mod_other.zip"], legends=False)) == (
            {"Modded": ("modded", False), "Vanilla": ("vanilla", False)}, "Modded")
        # BB Reroll's own in-game mod changes what the game rolls: the player is told
        setups(dict(base, mods=[], legends=False, reroll_mod=["mod_bb_reroll_dump.zip"]))
        assert "mod_bb_reroll_dump.zip" in O.reroll_mod_warning()
    finally:
        monkeypatch.undo()
        O.refresh()


@pytest.mark.core
def test_the_in_game_mod_is_never_loaded_by_the_offline_search(tmp_path):
    import zipfile
    data = tmp_path / "data"
    data.mkdir()
    for name, member in (("mod_bb_reroll_dump.zip", "scripts/!mods_preload/bb_reroll_dump.nut"),
                         ("mod_legends-1.zip", "mod_legends/load.nut"), ("mod_zz.zip", "scripts/x.nut")):
        with zipfile.ZipFile(data / name, "w") as z:
            z.writestr(member, "")
    (data / "broken.zip").write_bytes(b"not a zip")
    assert [z.name for z in profiles.mod_zips(data)] == ["mod_legends-1.zip", "mod_zz.zip"]
    assert [z.name for z in profiles.reroll_mod_zips(data)] == ["mod_bb_reroll_dump.zip"]
    summary = profiles.installed_summary(data)
    assert summary["legends"] is True and summary["reroll_mod"] == ["mod_bb_reroll_dump.zip"]


@pytest.mark.core
@pytest.mark.xdist_group("labs")          # it takes the session labs through request.getfixturevalue
@pytest.mark.skipif(O.FOUND is None, reason="no installed game found")
def test_every_offered_origin_exists_in_the_game_menu(request):
    from bbseed.lab import Lab, big_stack

    shared = {}            # the session's shared labs (conftest.py) that can run here; any other profile gets a new lab
    for profile in ("legends", "vanilla"):
        if any(p == profile for p, _legends in O.SETUPS.values()):
            try:
                shared[profile] = request.getfixturevalue(profile + "_lab").lab
            except pytest.skip.Exception:
                pass

    def run():
        return {setup: {script for script, _id, _title in (shared.get(profile) or Lab(profile)).origins()}
                for setup, (profile, _legends) in O.SETUPS.items()}
    offered = big_stack(run)
    for setup in O.SETUPS:
        missing = [n for n in O.names_for(setup) if O.SCENARIO[n] not in offered[setup]]
        assert not missing, "%s: not in the game's new-campaign menu: %s" % (setup, missing)


@pytest.mark.edge
def test_origins_other_mods_add_are_offered_for_their_setup_only():
    catalog = {"origins": [["trader_scenario", "scenario.trader", "Trading Caravan"],
                           ["random_scenario", "scenario.random", "Random"],
                           ["mod_pirates_scenario", "scenario.pirates", "Pirates"],
                           ["mod_other_trader", "scenario.other_trader", "Trading Caravan"],
                           ["mod_broken_scenario", "scenario.broken", "Broken"]],
               "talents": {"trader_scenario": {"slots": []}, "mod_pirates_scenario": {"slots": []},
                           "mod_other_trader": {"slots": []}, "mod_broken_scenario": {"error": "boom"}}}
    assert O.menu_extras(catalog) == [("Pirates", "mod_pirates_scenario"),
                                      ("Trading Caravan (mod_other_trader)", "mod_other_trader")]
    assert O.menu_extras(None) == []
    saved = dict(O.SCENARIO), dict(O.EXTRAS), dict(O.SETUPS)
    try:
        O.SETUPS.clear()
        O.SETUPS.update({"Modded": ("modded", False), "Vanilla": ("vanilla", False)})
        O.add_extras("modded", catalog)
        assert O.names_for("Modded")[-2:] == ["Pirates", "Trading Caravan (mod_other_trader)"]
        assert "Pirates" not in O.names_for("Vanilla")
        assert O.SCENARIO["Pirates"] == "mod_pirates_scenario"
    finally:
        O.SCENARIO.clear(); O.SCENARIO.update(saved[0])
        O.EXTRAS.clear(); O.EXTRAS.update(saved[1])
        O.SETUPS.clear(); O.SETUPS.update(saved[2])


# ---------------------------------------------------------------- Deserters (stage 2 C2 Task 4)
LEGENDS_MODS = ["mod_legends-19.4.22.zip", "mod_legends-assets-19.4.3.zip", "mod_modern_hooks-685-0-6-0-1748620177.zip",
                "mod_msu 479 1.9.0 2026-06-23T04-27Z eVJjKbX9c.zip"]


def _installed(monkeypatch, **found):
    base = {"data": Path("X:/Battle Brothers/data"), "game_version": "1.5.2.3", "reroll_mod": [], "dlc_complete": True,
            "mods": [], "legends": False}
    monkeypatch.setattr(profiles, "installed_summary", lambda game_data=None: dict(base, **found))
    O.refresh()


@pytest.mark.edge
def test_deserters_are_offered_only_where_the_maps_are_verified(monkeypatch):
    """Their brothers are made on the map: Legends 19.4.22 with its own mods, or the base game with every DLC."""
    try:
        _installed(monkeypatch, mods=LEGENDS_MODS, legends=True)
        assert "Deserters" in O.names_for("Legends") and "Deserters" in O.names_for("Vanilla")
        assert O.not_offered("Legends") == {} and O.not_offered("Vanilla") == {}
        assert O.searchable("Deserters", "Legends") and O.searchable("Trading Caravan", "Legends")
        # the mod zips of Legends do not matter to the base game (it loads none); a missing DLC does
        _installed(monkeypatch, mods=LEGENDS_MODS, legends=True, dlc_complete=False)
        assert "Deserters" in O.names_for("Legends") and "Deserters" not in O.names_for("Vanilla")
        assert list(O.not_offered("Vanilla")) == ["Deserters"] and O.not_offered("Legends") == {}
        # a mod beyond Legends' own set, another Legends version, another game version
        _installed(monkeypatch, mods=LEGENDS_MODS + ["mod_other-1.0.zip"], legends=True)
        assert "Deserters" not in O.names_for("Legends") and "Deserters" in O.names_for("Vanilla")
        _installed(monkeypatch, mods=["mod_legends-19.5.0.zip"] + LEGENDS_MODS[1:], legends=True)
        assert "Deserters" not in O.names_for("Legends")
        _installed(monkeypatch, mods=LEGENDS_MODS, legends=True, game_version="1.5.3.0")
        assert "Deserters" not in O.names_for("Legends") and "Deserters" not in O.names_for("Vanilla")
        # mods without Legends, or no game
        _installed(monkeypatch, mods=["mod_other-1.0.zip"], legends=False)
        assert "Deserters" not in O.names_for("Modded") and "Deserters" in O.names_for("Vanilla")
        monkeypatch.setattr(profiles, "installed_summary", lambda game_data=None: None)
        O.refresh()
        assert not O.verified_for_maps("Vanilla") and O.names_for("Vanilla") == [
            n for n in O.BUILT_IN if n != "Deserters" and not O.is_legends_only(n)]
    finally:
        monkeypatch.undo()
        O.refresh()


@pytest.mark.core
def test_the_note_for_a_setup_without_deserters_is_short_plain_text():
    note = O.NOT_SEARCHABLE["Deserters"]
    assert "map" in note and note.isascii() and all(len(s.split()) <= 25 for s in note.split(". "))
    assert O.is_deserters("Deserters") and not O.is_deserters("Gladiators") and not O.is_deserters("nobody")

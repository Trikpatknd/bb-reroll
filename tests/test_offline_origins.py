"""The offline search's setup / origin tables (bbreroll/offline_origins.py), and — when the
game is installed — that what they offer really exists in the game's new-campaign menu."""
from pathlib import Path

import pytest

from bbreroll import offline_origins as O
from bbseed import profiles


def test_setups_are_named_vanilla_and_legends():
    assert (O.LEGENDS, O.VANILLA) == ("Legends", "Vanilla")
    for setup, (profile, _legends) in O.SETUPS.items():
        assert profile in profiles.names()
        names = O.names_for(setup)
        assert "Deserters" not in names and "Trading Caravan" in names
    assert not any(O.is_legends_only(n) for n in O.names_for(O.VANILLA))
    assert not any(O.is_legends_only(n) for n in O.names_for("a setup that does not exist"))


def test_setups_follow_what_is_installed(monkeypatch):
    def setups(found):
        monkeypatch.setattr(profiles, "installed_summary", lambda game_data=None: found)
        O.refresh()
        return dict(O.SETUPS), O.DEFAULT_SETUP

    try:
        base = {"data": Path("X:/Battle Brothers/data"), "game_version": "1.5.2.3", "reroll_mod": []}
        assert setups(None) == ({}, None)
        assert "not found" in O.found_text() and O.reroll_mod_warning() is None
        assert setups(dict(base, mods=[], legends=False)) == ({"Vanilla": ("vanilla", False)}, "Vanilla")
        assert setups(dict(base, mods=["mod_legends.zip", "mod_msu.zip"], legends=True)) == (
            {"Legends": ("legends", True), "Vanilla": ("vanilla", False)}, "Legends")
        assert "2 mod files" in O.found_text() and "mod_msu.zip" in O.found_text(details=True)
        assert "Sisterhood" in O.names_for("Legends") and "Sisterhood" not in O.names_for("Vanilla")
        assert setups(dict(base, mods=["mod_other.zip"], legends=False)) == (
            {"Modded": ("modded", False), "Vanilla": ("vanilla", False)}, "Modded")
        # BB Reroll's own in-game mod changes what the game rolls: the player is told
        setups(dict(base, mods=[], legends=False, reroll_mod=["mod_bb_reroll_dump.zip"]))
        assert "mod_bb_reroll_dump.zip" in O.reroll_mod_warning()
    finally:
        monkeypatch.undo()
        O.refresh()


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


@pytest.mark.skipif(O.FOUND is None, reason="no installed game found")
def test_every_offered_origin_exists_in_the_game_menu():
    from bbseed.lab import Lab, big_stack

    def run():
        return {setup: {script for script, _id, _title in Lab(profile).origins()}
                for setup, (profile, _legends) in O.SETUPS.items()}
    offered = big_stack(run)
    for setup in O.SETUPS:
        missing = [n for n in O.names_for(setup) if O.SCENARIO[n] not in offered[setup]]
        assert not missing, "%s: not in the game's new-campaign menu: %s" % (setup, missing)

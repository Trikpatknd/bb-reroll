"""Which mods a seed was found with: the mod zips in the game's data folder, named and
versioned the way the mods register themselves with Modern Hooks. Also which DLC files the game
has: Vanilla maps need all of them."""
from bbseed import gamedata, mapgen, profiles
from bbseed.lab import installed_mods

# what ::Hooks.getMods() reported for Legends 19.4.22 + MSU 1.9.0 + Modern Hooks 0.6.0 (2026-10-15)
REGISTERED = [
    ("dlc_wildmen", "DLC: Warriors of the North", "1.0.0"),
    ("mod_legends_load_order_fix", "Legends Mod - Load order fix", "19.4.22"),
    ("mod_legends", "Legends Mod", "19.4.22"),
    ("mod_modern_hooks", "Modern Hooks", "0.6.0"),
    ("mod_Jimmys_Tooltips_legends", "ModJimmysTooltips", "1.0.5"),
    ("mod_msu", "Modding Standards & Utilities (MSU)", "1.9.0"),
    ("vanilla", "Vanilla", "1.5.2-3"),
    ("mod_legends_assets", "Legends assets", "19.4.3"),
    ("mod_hooks", "modding script hooks", "21.1"),
]
ZIPS = ["mod_legends-19.4.22.zip", "mod_legends-assets-19.4.3.zip",
        "mod_modern_hooks-685-0-6-0-1748620177.zip", "mod_msu 479 1.9.0 2026-06-23T04-27Z eVJjKbX9c.zip"]


def test_every_zip_gets_the_name_and_version_its_mod_registers():
    assert installed_mods(REGISTERED, ZIPS) == [
        {"file": "mod_legends-19.4.22.zip", "id": "mod_legends", "name": "Legends Mod", "version": "19.4.22"},
        {"file": "mod_legends-assets-19.4.3.zip", "id": "mod_legends_assets", "name": "Legends assets",
         "version": "19.4.3"},
        {"file": "mod_modern_hooks-685-0-6-0-1748620177.zip", "id": "mod_modern_hooks", "name": "Modern Hooks",
         "version": "0.6.0"},
        {"file": "mod_msu 479 1.9.0 2026-06-23T04-27Z eVJjKbX9c.zip", "id": "mod_msu",
         "name": "Modding Standards & Utilities (MSU)", "version": "1.9.0"},
    ]


def test_a_zip_no_registration_matches_is_listed_by_its_file_name():
    out = installed_mods(REGISTERED, ["mod_some_textures.zip"])
    assert out == [{"file": "mod_some_textures.zip", "id": None, "name": "mod_some_textures", "version": None}]


def test_without_zips_nothing_is_listed():
    # sub-mods bundled inside a zip, DLCs and the base game register too, but they are not installed files
    assert installed_mods(REGISTERED, []) == []


# ------------------------------------------------------------------ the DLC files
def _data_folder(folder, names):
    folder.mkdir(exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"")
    return folder


def test_all_dlc_needs_every_file(tmp_path):
    data = _data_folder(tmp_path, ["data_001.dat"] + sorted(set(gamedata.DLC_FILES.values())))
    assert gamedata.installed_dlc(data) == set(gamedata.DLC_FILES)
    assert gamedata.all_dlc(data) is True
    (data / gamedata.DLC_FILES["Wildmen"]).unlink()
    assert gamedata.installed_dlc(data) == set(gamedata.DLC_FILES) - {"Wildmen"}
    assert gamedata.all_dlc(data) is False


def test_no_install_has_no_dlc(monkeypatch):
    monkeypatch.setattr(gamedata, "game_data_dir", lambda: None)
    assert gamedata.installed_dlc() == set()
    assert gamedata.all_dlc() is False


def test_the_summary_says_whether_every_dlc_is_there(tmp_path):
    some = _data_folder(tmp_path / "some", ["data_001.dat", "data_003.dat"])
    every = _data_folder(tmp_path / "every", ["data_001.dat"] + sorted(set(gamedata.DLC_FILES.values())))
    assert profiles.installed_summary(some)["dlc_complete"] is False
    assert profiles.installed_summary(every)["dlc_complete"] is True


def test_verified_setup_vanilla_is_off_until_verified(monkeypatch):
    monkeypatch.setattr(mapgen, "VANILLA_MAPS_VERIFIED", False)
    assert mapgen.verified_setup("1.5.2.3", None, [], True) is False
    monkeypatch.setattr(mapgen, "VANILLA_MAPS_VERIFIED", True)
    assert mapgen.verified_setup("1.5.2.3", None, [], True) is True
    assert mapgen.verified_setup("1.5.2.3", None, [], False) is False
    assert mapgen.verified_setup("1.5.2.3", None, ["mod_msu 479 1.9.0 2026-06-23T04-27Z eVJjKbX9c.zip"], True) is False
    assert mapgen.verified_setup("1.5.3.0", None, [], True) is False


def test_vanilla_maps_are_verified_in_the_module():
    """Gate A3 (bb_seedlab MODLOG "CHECKPOINT V", 2026-10-24): 40 Vanilla maps and rosters matched the game."""
    assert mapgen.VANILLA_MAPS_VERIFIED is True


def test_verified_setup_legends_is_as_before_and_ignores_the_dlc():
    assert mapgen.verified_setup("1.5.2.3", "19.4.22", [], False) is True
    assert mapgen.verified_setup("1.5.3.0", "19.4.22", [], True) is False

"""Which mods a seed was found with: the mod zips in the game's data folder, named and
versioned the way the mods register themselves with Modern Hooks."""
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

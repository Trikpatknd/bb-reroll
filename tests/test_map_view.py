"""bbreroll/map_view.py: the Map view's fields turned into map conditions and Map Options, the texts, the saved
values and the small rules the window needs. tkinter-free, no game needed."""
import json

import pytest

from bbreroll import map_conditions as MC
from bbreroll import map_view as V
from bbseed import mapdraw
from bbseed.search import normalize_map

OPTION_KEYS = ["LandRatio", "Water", "Snowline", "Settlements", "Factions", "StackCitadels", "AllTradeLocations"]


def texts(**changes):
    out = V.default_conditions()
    out.update({k: str(v) for k, v in changes.items()})
    return out


def option_texts(**changes):
    out = V.default_options()
    out.update({k: str(v) for k, v in changes.items()})
    return out


# ------------------------------------------------------------------ the fields
def test_the_fields_start_with_no_condition_and_the_legends_defaults():
    c = V.default_conditions()
    assert set(c) == {"ports", "ports_south", "ports_north", "north_band", "city_state", "military", "size1", "size2",
                      "size3"}
    assert c["north_band"] == "33" and all(v == "0" for k, v in c.items() if k != "north_band")
    assert V.default_options() == {"LandRatio": "50", "Water": "38", "Snowline": "85", "Settlements": "19",
                                   "Factions": "3", "StackCitadels": "No", "AllTradeLocations": "No"}
    assert list(V.default_options()) == OPTION_KEYS      # the order of the game's Map Options page


def test_the_labels_are_the_games():
    assert V.CONDITION_LABELS == {"ports": "Ports", "ports_south": "Southern ports", "ports_north": "Northern ports",
                                  "north_band": "North band (%)"}
    assert V.TOWN_LABELS == MC.TOWN_TYPES
    assert list(V.TOWN_LABELS.values()) == ["City states", "Strongholds", "Villages", "Towns", "Cities"]
    assert V.OPTION_LABELS == {"LandRatio": "Land Mass Ratio", "Water": "Water", "Snowline": "Snowline",
                               "Settlements": "Settlements", "Factions": "Factions",
                               "StackCitadels": "Decked Out Citadels",
                               "AllTradeLocations": "All trade buildings available"}
    # the ranges of mod_legends/register/modsettings.nut:16-25
    assert V.OPTION_RANGES == {"LandRatio": (45, 70), "Water": (28, 42), "Snowline": (75, 95), "Settlements": (19, 27),
                               "Factions": (2, 6)}


# ------------------------------------------------------------------ build
def test_no_condition_is_no_map_and_no_map_options():
    assert V.build(V.default_conditions(), V.default_options()) == (None, None, [])
    # a band alone is no condition; Map Options that do not parse matter only with a condition
    assert V.build(texts(north_band=50), option_texts(Water="x")) == (None, None, [])
    assert V.build(texts(north_band="abc"), V.default_options()) == (None, None, [])


def test_conditions_become_the_criteria_the_search_takes():
    criteria, options, errors = V.build(texts(ports=6, ports_south=1, ports_north=2, north_band=40, city_state=2,
                                              size2=3), V.default_options())
    assert errors == []
    assert criteria == {"ports": 6, "ports_south": 1, "ports_north": 2, "north_band": 40,
                        "towns": {"city_state": 2, "size2": 3}}
    assert options == {"LandRatio": 50, "Water": 38, "Snowline": 85, "Settlements": 19, "Factions": 3,
                       "StackCitadels": False, "AllTradeLocations": False}
    assert normalize_map(criteria) == criteria          # the search takes them as they are


def test_the_band_is_always_a_number_even_for_a_run_without_northern_ports():
    criteria, _o, _e = V.build(texts(ports=1, north_band=""), V.default_options())
    assert criteria["north_band"] == 33 and isinstance(criteria["north_band"], int)


def test_blank_fields_are_zero_and_spaces_are_ignored():
    criteria, _o, errors = V.build(texts(ports=" 4 ", ports_south="", size1=" "), V.default_options())
    assert errors == [] and criteria["ports"] == 4 and criteria["ports_south"] == 0 and criteria["towns"] == {}


@pytest.mark.parametrize("bad", ["abc", "-1", "2.5", "1e3"])
def test_a_condition_that_is_not_a_whole_number_is_an_error(bad):
    criteria, options, errors = V.build(texts(ports=bad, size3=2), V.default_options())
    assert criteria is None and options is None
    assert errors == ["Ports must be a whole number of 0 or more."]


def test_every_bad_field_is_named_once():
    _c, _o, errors = V.build(texts(ports_south="x", city_state="y", north_band="0"), V.default_options())
    assert errors == ["Southern ports must be a whole number of 0 or more.",
                      "North band (%) must be a whole number from 1 to 99.",
                      "City states must be a whole number of 0 or more."]


@pytest.mark.parametrize("band", ["0", "100", "-5", "abc", "33.5"])
def test_the_band_must_be_1_to_99(band):
    # a map condition is set, so the band is read (the post names it)
    _c, _o, errors = V.build(texts(ports=1, north_band=band), V.default_options())
    assert errors == ["North band (%) must be a whole number from 1 to 99."]


def test_the_map_options_are_checked_against_the_games_ranges_when_a_condition_is_set():
    _c, options, errors = V.build(texts(ports=1), option_texts(LandRatio=44, Water=43, Snowline="x", Settlements=28,
                                                                Factions=1))
    assert options is None
    assert errors == ["Land Mass Ratio must be a whole number from 45 to 70.",
                      "Water must be a whole number from 28 to 42.",
                      "Snowline must be a whole number from 75 to 95.",
                      "Settlements must be a whole number from 19 to 27.",
                      "Factions must be a whole number from 2 to 6."]


def test_the_edges_of_the_ranges_are_allowed_and_yes_no_are_booleans():
    _c, options, errors = V.build(texts(ports=1), option_texts(LandRatio=70, Water=28, Snowline=95, Settlements=27,
                                                               Factions=6, StackCitadels="Yes", AllTradeLocations="Yes"))
    assert errors == []
    assert options == {"LandRatio": 70, "Water": 28, "Snowline": 95, "Settlements": 27, "Factions": 6,
                       "StackCitadels": True, "AllTradeLocations": True}
    _c, _o, errors = V.build(texts(ports=1), option_texts(StackCitadels="maybe"))
    assert errors == ["Decked Out Citadels must be Yes or No."]


def test_the_search_gets_exactly_the_seven_map_options():
    _c, options, _e = V.build(texts(ports=1), option_texts(Settlements=24, StackCitadels="Yes"))
    mod_settings = V.mod_settings(options)
    assert sorted(mod_settings) == sorted("mod_legends:" + k for k in OPTION_KEYS)
    assert mod_settings["mod_legends:Settlements"] == 24 and mod_settings["mod_legends:StackCitadels"] is True


def test_the_settlements_option_changes_what_is_impossible():
    # Strongholds: at most 6 on a map with Settlements 19, at most 9 with 27 (map_conditions.limits)
    criteria, options19, _e = V.build(texts(military=8), V.default_options())
    assert MC.problems(criteria, options19) == [
        "Strongholds: a map has a maximum of 6 with these Map Options. Your condition is 8."]
    criteria, options27, _e = V.build(texts(military=8), option_texts(Settlements=27))
    assert MC.problems(criteria, options27) == []


def test_the_default_option_values_are_the_defaults_as_numbers_and_booleans():
    assert V.default_option_values() == {"LandRatio": 50, "Water": 38, "Snowline": 85, "Settlements": 19, "Factions": 3,
                                         "StackCitadels": False, "AllTradeLocations": False}


def test_a_self_test_spec_fills_the_fields():
    # "map" is a criteria dict (as the search takes it), "map_options" the seven values as numbers / booleans
    conditions, options = V.fields_from_spec({"ports": 3, "north_band": 50, "towns": {"city_state": 2, "size1": 4}},
                                             {"Settlements": 24, "StackCitadels": True})
    assert conditions == texts(ports=3, north_band=50, city_state=2, size1=4)
    assert options == option_texts(Settlements=24, StackCitadels="Yes")
    assert V.fields_from_spec(None, None) == (V.default_conditions(), V.default_options())
    # and the fields build the same conditions back
    criteria, _o, errors = V.build(conditions, options)
    assert errors == [] and criteria == {"ports": 3, "ports_south": 0, "ports_north": 0, "north_band": 50,
                                         "towns": {"city_state": 2, "size1": 4}}


# ------------------------------------------------------------------ the saved values
def test_the_saved_values_round_trip_through_json():
    conditions = texts(ports=5, north_band=50, size1=2)
    options = option_texts(Settlements=24, StackCitadels="Yes")
    saved = json.loads(json.dumps(V.to_settings(conditions, options)))
    assert V.from_settings(saved) == (conditions, options)


def test_a_settings_file_without_map_values_gives_the_defaults():
    assert V.from_settings({"v": 4, "setup": "Legends"}) == (V.default_conditions(), V.default_options())


def test_a_damaged_settings_file_gives_the_defaults_for_the_damaged_values():
    saved = {"map": {"ports": 5, "north_band": None, "city_state": [1], "bogus": "7", "size1": True},
             "map_options": {"Settlements": 22, "Water": {"a": 1}, "StackCitadels": "Maybe"}}
    conditions, options = V.from_settings(saved)
    assert conditions == texts(ports=5)                 # a number is kept (as text); the rest is the default
    assert options == option_texts(Settlements=22)      # "Maybe" is not Yes / No
    assert V.from_settings({"map": "x", "map_options": 3}) == (V.default_conditions(), V.default_options())
    assert V.from_settings(None) == (V.default_conditions(), V.default_options())


# ------------------------------------------------------------------ the saved Mod Options
def test_saved_option_texts_fills_missing_with_defaults():
    assert V.saved_option_texts({"Settlements": 24, "StackCitadels": True}) == option_texts(Settlements="24",
                                                                                         StackCitadels="Yes")


def test_saved_option_texts_none():
    assert V.saved_option_texts(None) is None


def test_saved_option_texts_takes_every_saved_value_as_text_in_the_games_order():
    read = {"AllTradeLocations": True, "StackCitadels": False, "Factions": 6, "Settlements": 27, "Snowline": 80,
            "Water": 33.5, "LandRatio": 61}
    out = V.saved_option_texts(read)
    assert out == {"LandRatio": "61", "Water": "33.5", "Snowline": "80", "Settlements": "27", "Factions": "6",
                   "StackCitadels": "No", "AllTradeLocations": "Yes"}
    assert list(out) == OPTION_KEYS


def test_saved_option_texts_gives_the_default_for_a_value_of_the_wrong_kind():
    read = {"Settlements": "24", "Water": True, "StackCitadels": "Yes", "Factions": None, "AllTradeLocations": 1}
    assert V.saved_option_texts(read) == V.default_options()


def test_the_saved_option_texts_are_the_texts_of_the_brief():
    assert V.OPTIONS_TITLE == ("Map Options. The program reads them from your saved Mod Options. You can change them, "
                               "for example to the Mod Options of a friend.")
    assert V.READ_BUTTON == "Read my Mod Options"
    assert V.OPTIONS_DIFFER == ("These Map Options are not the same as your saved Mod Options. Click Read my Mod "
                                "Options to use the saved values.")
    assert V.NO_SAVED_OPTIONS == "The program cannot read your saved Mod Options. It uses the values in the fields."


def test_the_help_text_says_the_program_reads_the_saved_mod_options():
    assert "The program reads them from your saved Mod Options (Legends Mod, page Map Options)." in V.HELP
    assert "Write the same values" not in V.HELP


def test_fill_at_startup_first_start():
    saved = V.saved_option_texts({"Settlements": 24})
    assert V.fill_at_startup({}, V.default_options(), saved) is True
    assert V.fill_at_startup({"v": 4, "setup": "Legends"}, V.default_options(), saved) is True


def test_fill_at_startup_untouched_fields():
    current = option_texts(Settlements="24")
    settings = {"map_options": current, "map_options_read": current}
    assert V.fill_at_startup(settings, current, V.saved_option_texts({"Settlements": 25})) is True


def test_fill_at_startup_keeps_typed_values():
    """The player's typed values stay when they differ from the values the program last read."""
    read = option_texts(Settlements="24")
    typed = option_texts(Settlements="26")
    settings = {"map_options": typed, "map_options_read": read}
    assert V.fill_at_startup(settings, typed, V.saved_option_texts({"Settlements": 24})) is False


def test_fill_at_startup_without_file():
    assert V.fill_at_startup({}, V.default_options(), None) is False
    assert V.fill_at_startup({"map_options": V.default_options()}, V.default_options(), None) is False


def test_fill_at_startup_never_raises_on_damaged_settings():
    current = V.default_options()
    for settings in (None, [], "x", {"map_options": None, "map_options_read": [1]}, {"map_options_read": None}):
        assert isinstance(V.fill_at_startup(settings, current, current), bool)


def test_settings_round_trip_keeps_read():
    conditions, options = texts(ports=5), option_texts(Settlements="24")
    read = option_texts(Settlements="24", StackCitadels="Yes")
    saved = V.to_settings(conditions, options, read=read)
    assert saved["map_options_read"] == read
    assert json.loads(json.dumps(saved))["map_options_read"] == read
    assert "map_options_read" not in V.to_settings(conditions, options)


def test_a_raw_read_is_kept_in_the_text_shape_of_the_map_options():
    raw = {"LandRatio": 50, "Water": 38, "Snowline": 85, "Settlements": 24, "Factions": 3, "StackCitadels": True,
           "AllTradeLocations": False}
    saved = V.to_settings(texts(), option_texts(), read=raw)
    assert saved["map_options_read"] == option_texts(Settlements="24", StackCitadels="Yes")


# ------------------------------------------------------------------ the game version
def test_only_the_game_and_legends_the_maps_were_checked_against_are_verified():
    assert V.verified("1.5.2.3", "19.4.22")
    assert not V.verified("1.5.2.3", "19.5.0")
    assert not V.verified("1.5.3.0", "19.4.22")
    assert not V.verified(None, "19.4.22") and not V.verified("1.5.2.3", None)


VERIFIED_ZIPS = ["mod_legends-19.4.22.zip", "mod_legends-assets-19.4.3.zip",
                 "mod_modern_hooks-685-0-6-0-1748620177.zip", "mod_msu 479 1.9.0 2026-06-23T04-27Z eVJjKbX9c.zip"]


def test_any_mod_beyond_legends_msu_and_modern_hooks_makes_the_maps_not_verified():
    """Final review I1 (b): HARMLESS_STUBS reviews the engine stand-ins for Legends + MSU + Modern Hooks only; another
    mod may hook the map generator. The mods come as file names (the installed game) or as the workers' info["mods"]."""
    assert V.verified("1.5.2.3", "19.4.22", VERIFIED_ZIPS)
    assert V.verified("1.5.2.3", "19.4.22", ["mod_legends-19.4.22.zip"]), "extra mods count, missing ones do not"
    assert V.verified("1.5.2.3", "19.4.22", [])
    assert V.verified("1.5.2.3", "19.4.22", None), "mods not asked: only the versions count"
    assert not V.verified("1.5.2.3", "19.4.22", VERIFIED_ZIPS + ["mod_jimmys_tooltips-1.0.5.zip"])
    assert not V.verified("1.5.2.3", "19.4.22", VERIFIED_ZIPS + ["mod_legends_load_order_fix.zip"])
    assert not V.verified("1.5.2.3", "19.4.22", ["mod_legends-19.4.22.zip", "mod_msu_extras-1.0.zip"])
    assert not V.verified("1.5.3.0", "19.4.22", VERIFIED_ZIPS), "the versions still count"
    info_mods = [{"file": z, "id": i, "name": "x", "version": "1"} for z, i in zip(
        VERIFIED_ZIPS, ("mod_legends", "mod_legends_assets", "mod_modern_hooks", "mod_msu"))]
    assert V.verified("1.5.2.3", "19.4.22", info_mods)
    assert not V.verified("1.5.2.3", "19.4.22", info_mods + [{"file": "mod_other.zip", "id": None, "name": "mod_other",
                                                            "version": None}])
    assert not V.verified("1.5.2.3", "19.4.22", [{"id": "mod_other"}])


def test_the_legends_version_is_read_from_the_mod_file_name():
    mods = ["mod_legends-19.4.22.zip", "mod_legends-assets-19.4.3.zip", "mod_msu 479 1.9.0 2026-06-23T04-27Z eVJjKbX9c.zip"]
    assert V.legends_version_from_files(mods) == "19.4.22"
    assert V.legends_version_from_files(["mod_legends_19.5.0.zip"]) == "19.5.0"
    assert V.legends_version_from_files(["mod_legends-assets-19.4.3.zip"]) is None
    assert V.legends_version_from_files(["mod_legends.zip", "other.zip"]) is None
    assert V.legends_version_from_files([]) is None


def test_the_view_state_says_why_the_fields_are_closed():
    assert V.view_state(legends=True, off=False) == (True, None)
    usable, line = V.view_state(legends=False, off=False)
    assert not usable and line == "Map conditions need the Legends setup for now."
    usable, line = V.view_state(legends=True, off=True)
    assert not usable and line == ("Map conditions are off. They did not work with this game setup. "
                                   "Change a Map Option to turn them on again.")
    assert V.view_state(legends=False, off=True)[0] is False


def test_the_fields_stay_open_while_the_conditions_are_off_so_a_map_option_can_be_changed():
    assert V.fields_open(legends=True)
    assert not V.fields_open(legends=False)


# ------------------------------------------------------------------ texts
def test_the_help_text_names_the_map_time_and_the_map_options():
    assert V.HELP.startswith("Set the minimum number of ports and towns. A port lets you travel by ship. North band: "
                             "the top part of the map, in percent. Each map takes about 40 seconds with the default "
                             "Map Options. Set brother conditions too, if you can. A low Land Mass Ratio with a high "
                             "Water value can make one map take many minutes.")
    assert V.SLOW_OPTIONS in V.HELP
    assert "Mod Options" in V.HELP and "Map Options" in V.HELP
    assert V.NOT_VERIFIED == "Map results are not verified for this setup."


def test_the_time_of_a_map_is_the_time_with_the_default_map_options():
    """Final review M1: 40 s is with Legends' defaults; a low Land Mass Ratio with a high Water value took 352 s for
    one map. Text only: there is no attempt cap."""
    assert V.WAIT == "Each map takes about 40 seconds with the default Map Options."
    assert "many minutes" in V.SLOW_OPTIONS and "Land Mass Ratio" in V.SLOW_OPTIONS and "Water" in V.SLOW_OPTIONS


def test_the_tooltips_say_minimum_and_have_no_noun_stack():
    """Final review 163: "minimum number", not "least number"; "Southern ports" counts the ports that are city states."""
    assert set(V.CONDITION_TIPS) == set(V.CONDITION_LABELS)
    assert V.CONDITION_TIPS["ports_south"] == ("The minimum number of city states that have a port. "
                                               "City states are in the south.")
    assert V.CONDITION_TIPS["ports"].startswith("The minimum number of ports on the map.")
    assert V.CONDITION_TIPS["ports_north"].startswith("The minimum number of ports in the north band.")
    assert V.town_tip("Strongholds") == "The minimum number of strongholds on the map."
    assert [V.town_tip(label) for label in V.TOWN_LABELS.values()][0] == "The minimum number of city states on the map."
    for text in list(V.CONDITION_TIPS.values()) + [V.town_tip(label) for label in V.TOWN_LABELS.values()]:
        assert "least" not in text and "n't" not in text and "'s " not in text, text
        assert all(len(sentence.split()) <= 25 for sentence in text.split(". ")), text


def test_the_texts_follow_the_simplified_writing_rules():
    for text in (V.HELP, V.NOT_VERIFIED, V.NEEDS_LEGENDS, V.TURNED_OFF, V.MAP_FATAL_ADVICE, V.WAIT, V.OPTIONS_TITLE,
                 V.READ_BUTTON, V.OPTIONS_DIFFER, V.NO_SAVED_OPTIONS,
                 V.SLOW_OPTIONS, V.brother_estimate({"chance_brothers": 0.001, "tested": 500, "maps": 3}, True, False)):
        assert "n't" not in text and "'s " not in text and "criteria" not in text.lower(), text
        assert all(len(sentence.split()) <= 25 for sentence in text.replace("\n", " ").split(". ")), text


# ------------------------------------------------------------------ the estimate while maps are built
def test_the_estimate_waits_for_maps_not_for_seeds_when_maps_are_all_there_is():
    odds = {"tested": 40, "maps": 5}
    assert not V.estimate_ready(odds, map_run=True, map_first=True)
    assert V.estimate_ready({"tested": V.MIN_MAPS, "maps": V.MIN_MAPS}, map_run=True, map_first=True)
    # with brother conditions the seeds are cheap: 100 of them AND the maps
    assert not V.estimate_ready({"tested": 99, "maps": V.MIN_MAPS}, map_run=True, map_first=False)
    assert not V.estimate_ready({"tested": 5000, "maps": V.MIN_MAPS - 1}, map_run=True, map_first=False)
    assert V.estimate_ready({"tested": 100, "maps": V.MIN_MAPS}, map_run=True, map_first=False)
    # a run without map conditions: as before, 100 seeds
    assert not V.estimate_ready({"tested": 99}, map_run=False, map_first=False)
    assert V.estimate_ready({"tested": 100}, map_run=False, map_first=False)


def test_the_note_while_the_first_maps_are_built():
    assert V.wait_note({"maps": 0}) == ("Each map takes about 40 seconds with the default Map Options. "
                                        "The estimate shows after 30 maps. Maps built: 0.")
    assert V.wait_note({"maps": 12}).endswith("Maps built: 12.")
    assert V.wait_note({"maps": V.MIN_MAPS}) == ""
    assert V.WAIT.startswith("Each map takes about 40 seconds")


def test_brother_and_map_conditions_show_the_brothers_rate_until_the_maps_estimate_is_ready():
    """Final review M7: rare brother conditions (1 in 5,000) need hours for 30 maps; the brothers' rate shows
    meanwhile, with the number of maps built. It needs the same 100 seeds as a search for brothers alone."""
    odds = {"chance_brothers": 0.0002, "tested": 12000, "maps": 3, "chance": 0.00004}
    assert V.brother_estimate(odds, map_run=True, map_first=False) == (
        "Approximately 1 in 5,000 seeds meets the brother conditions (from 12,000 seeds). Maps built: 3. "
        "The estimate with the maps shows after 30 maps.")
    assert V.brother_estimate(dict(odds, maps=0), True, False).count("Maps built: 0.") == 1
    assert V.brother_estimate(dict(odds, chance_brothers=0.5, tested=100), True, False).startswith(
        "Approximately 1 in 2 seeds meets")
    assert V.brother_estimate(dict(odds, tested=99), True, False) == "", "100 seeds first, as for the brothers alone"
    assert V.brother_estimate(dict(odds, maps=V.MIN_MAPS), True, False) == "", "the full estimate speaks from here"
    assert V.brother_estimate(odds, map_run=True, map_first=True) == "", "map conditions alone: no brothers"
    assert V.brother_estimate(odds, map_run=False, map_first=False) == "", "no map conditions: the usual estimate"
    assert V.brother_estimate(dict(odds, chance_brothers=0.0), True, False) == "", "never met: the notices speak"
    assert V.brother_estimate(dict(odds, chance_brothers=None), True, False) == ""
    assert V.brother_estimate({}, True, False) == ""


def test_the_watch_line_shows_a_decimal_below_ten_seeds_a_second():
    """Final review M2: a search with maps tests about 0.14 seeds a second, which "0/s" showed as stuck."""
    assert [V.rate_text(r) for r in (0.0, 0.14, 0.96, 3.0, 9.94)] == ["0.0", "0.1", "1.0", "3.0", "9.9"]
    assert [V.rate_text(r) for r in (10, 12.4, 12.6, 250.0)] == ["10", "12", "13", "250"]


# ------------------------------------------------------------------ the picture
def summary(w=140, h=170):
    return {"size": [w, h], "layout": "even-q-up", "terrain": "L" * (w * h), "towns": []}


def test_the_picture_fits_a_screen_1440_pixels_high():
    s = summary()
    scale = V.canvas_scale(s, 1440)
    width, height = mapdraw.picture_size(s, scale)
    assert 0.8 < scale < 1.0
    assert height + 240 <= 1440, "room for the title bar, the legend and the taskbar"
    # a smaller screen: a smaller picture; a very big one: not bigger than the cells' own size
    assert V.canvas_scale(s, 1080) < scale
    assert V.canvas_scale(s, 4000) == 1.0
    assert V.canvas_scale(s, 300) == V.MIN_SCALE
    assert V.canvas_scale(summary(10, 10), 1440) == 1.0

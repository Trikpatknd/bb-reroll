"""Features read from the installed game (Legends 19.4.22 + MSU 1.9.0 + Modern Hooks 0.6.0 on
Battle Brothers 1.5.2.3). One lab per setup is shared by the whole module: booting one takes
~15 s. Skipped when that game / those mods are not installed."""
import pytest

from bbseed import profiles

FOUND = profiles.installed_summary()
HAVE_GAME = FOUND is not None and FOUND["game_version"] == "1.5.2.3"
HAVE_LEGENDS = HAVE_GAME and any("mod_legends-19.4.22" in m for m in FOUND["mods"]) and any("1.9.0" in m for m in FOUND["mods"])

legends_only = pytest.mark.skipif(not HAVE_LEGENDS, reason="Battle Brothers 1.5.2.3 with Legends 19.4.22 + MSU 1.9.0 is not installed")
game_only = pytest.mark.skipif(not HAVE_GAME, reason="Battle Brothers 1.5.2.3 is not installed")


def _in_lab(lab, fn):
    from bbseed.lab import big_stack
    return big_stack(lambda: fn(lab))


@pytest.fixture(scope="module")
def legends():
    from bbseed.lab import Lab, big_stack
    return big_stack(lambda: Lab("legends"))


@pytest.fixture(scope="module")
def vanilla():
    from bbseed.lab import Lab, big_stack
    return big_stack(lambda: Lab("vanilla"))


@legends_only
def test_info_lists_the_installed_mod_zips_with_their_versions(legends):
    mods = _in_lab(legends, lambda lab: lab.info()["mods"])
    assert [(m["name"], m["version"]) for m in mods] == [
        ("Legends Mod", "19.4.22"), ("Legends assets", "19.4.3"),
        ("Modern Hooks", "0.6.0"), ("Modding Standards & Utilities (MSU)", "1.9.0")]


@game_only
def test_the_unmodded_game_has_no_mods(vanilla):
    assert _in_lab(vanilla, lambda lab: lab.info()["mods"]) == []


# ---------------------------------------------------------------- perk trees
@legends_only
def test_a_confirmed_roster_lists_each_recruits_perk_groups(legends):
    from bbseed.lab import describe, without_perks
    with_perks, plain = _in_lab(legends, lambda lab: (lab.roster_with_perks("1234567890", "trader_scenario"),
                                                      lab.roster("1234567890", "trader_scenario")))
    assert without_perks(with_perks) == plain, "reading the perk trees changes nothing in the roll"
    merchant = dict(with_perks[0]["perk_groups"])
    assert merchant["Profession"] == ["Caravaneering", "Barter"]
    assert "Light Armor" in merchant["Defense"] and len(merchant["Weapon"]) >= 4
    assert "Profession perk groups: Caravaneering, Barter" in describe(with_perks[0])


@game_only
def test_the_unmodded_game_has_no_perk_groups(vanilla):
    roster = _in_lab(vanilla, lambda lab: lab.roster_with_perks("1234567890", "early_access_scenario"))
    assert all("perk_groups" not in b for b in roster)


# ---------------------------------------------------------------- stat rolls
def _rolls_unchanged_and_in_range(make_lab, origins):
    from bbseed.lab import Lab, big_stack

    def run():
        plain, watched = make_lab(), make_lab().watch_rolls()
        out = []
        for origin in origins:
            for seed in ("1234567890", "4000007919"):
                a = plain.roster(seed, origin, fresh=True)
                b = watched.roster(seed, origin, fresh=True)
                out.append((a, b))
        return out
    for plain, watched in big_stack(run):
        assert plain == [{k: v for k, v in bro.items() if k != "rolls"} for bro in watched], \
            "watching the rolls must not change the roll"
        for bro in watched:
            for stat, r in bro["rolls"].items():
                assert r["lo"] <= r["value"] <= r["hi"], (bro["background"], stat, r)


@legends_only
def test_legends_rolls_are_recorded_inside_their_ranges_without_changing_rosters():
    from bbseed.lab import Lab
    _rolls_unchanged_and_in_range(lambda: Lab("legends"), ["trader_scenario", "militia_scenario",
                                                            "legends_rangers_scenario", "legend_risen_legion_scenario"])


@game_only
def test_vanilla_rolls_are_recorded_inside_their_ranges_without_changing_rosters():
    from bbseed.lab import Lab
    _rolls_unchanged_and_in_range(lambda: Lab("vanilla"), ["early_access_scenario", "militia_scenario"])


# ---------------------------------------------------------------- which stars an origin can have
def _survey(lab, origin):
    from bbseed.talents import TalentWatch, survey

    def run(lab):
        watch = getattr(lab, "_test_watch", None) or TalentWatch(lab)
        lab._test_watch = watch
        return survey(watch, origin)
    return _in_lab(lab, run)


@legends_only
def test_berserker_always_has_stars_in_four_stats(legends):
    (slot,) = _survey(legends, "legends_berserker_scenario")["slots"]
    assert slot["most"] == slot["least"] == 4 and slot["picks"] == 2
    assert slot["fixed"] == {"hp": 3, "msk": 3}
    assert all(top == 3 for top in slot["max"].values())


@legends_only
def test_scaling_beggar_can_never_have_four_starred_stats_nor_hp_or_resolve_stars(legends):
    # the user's case of 2026-10-15: 100,000 seeds searched for 4 starred stats, none found
    (slot,) = _survey(legends, "legends_scaling_beggar_scenario")["slots"]
    assert slot["most"] == 3 and slot["fixed"] == {}
    assert slot["max"]["hp"] == 0 and slot["max"]["res"] == 0
    assert slot["rolled"] == ["fat", "init", "msk", "rsk", "mdf", "rdf"]


@legends_only
def test_inquisition_fixes_stars_after_the_roll(legends):
    slots = _survey(legends, "legends_inquisition_scenario")["slots"]
    assert [s["fixed"] for s in slots] == [{"hp": 3, "res": 3, "msk": 2}, {"res": 3, "rsk": 3},
                                           {"res": 3, "msk": 2, "mdf": 3}]
    assert slots[0]["most"] == 3 and slots[0]["rolled"] == []          # nothing rolled survives
    assert slots[1]["most"] == 3 and slots[1]["picks"] == 1            # one forced pick on top


@legends_only
def test_ranger_brother_two_gets_stars_from_his_background_and_the_origin(legends):
    # the druid background fixes FAT 2 and rolls two more; then the origin writes MSK 2 and HP 2
    slots = _survey(legends, "legends_rangers_scenario")["slots"]
    assert slots[1]["fixed"] == {"hp": 2, "fat": 2, "msk": 2}
    assert slots[1]["picks"] == 2 and slots[1]["most"] == 5


@legends_only
def test_legends_a_new_company_has_fixed_stars_too(legends):
    # the hand-written table had these as rolled; the game gives every seed the same stars
    slots = _survey(legends, "early_access_scenario")["slots"]
    assert [s["fixed"] for s in slots] == [{"hp": 2, "fat": 1, "res": 1}, {"res": 1, "msk": 2, "mdf": 1},
                                           {"init": 1, "rsk": 2, "rdf": 1}]
    assert all(s["picks"] == 0 for s in slots)


@game_only
def test_vanilla_a_new_company_has_the_same_stars_on_every_seed(vanilla):
    slots = _survey(vanilla, "early_access_scenario")["slots"]
    assert [s["fixed"] for s in slots] == [{"hp": 2, "fat": 1, "res": 1}, {"res": 1, "msk": 2, "mdf": 1},
                                           {"init": 1, "rsk": 2, "rdf": 1}]
    assert all(s["rolled"] == [] for s in slots)

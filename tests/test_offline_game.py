"""The offline search against the installed game: everything is read in place from the
game's folder — the mods from their zips, the base game from its compiled scripts in
data_*.dat — and the rosters must be the ones the real game gave for these seeds
(checked in game on 2026-10-13: Battle Brothers 1.5.2.3, unmodded and with Legends 19.4.22,
MSU 1.9.0, Modern Hooks 0.6.0). Skipped when that game / those mods are not installed.
"""
import pytest

from bbseed import profiles

FOUND = profiles.installed_summary()
HAVE_GAME = FOUND is not None and FOUND["game_version"] == "1.5.2.3"
HAVE_LEGENDS = HAVE_GAME and any("mod_legends-19.4.22" in m for m in FOUND["mods"]) and any("1.9.0" in m for m in FOUND["mods"])


@pytest.mark.skipif(not HAVE_GAME, reason="Battle Brothers 1.5.2.3 is not installed")
def test_vanilla_gives_the_rosters_the_game_gave():
    from bbseed.lab import Lab, big_stack

    def run():
        lab = Lab("vanilla")
        return {seed: lab.roster(seed, "early_access_scenario") for seed in ("1234567890", "SEEDTEST", "seedtest")}, lab.eng
    rosters, eng = big_stack(run)
    bros = rosters["1234567890"]
    assert [b["name"] for b in bros] == ["Berthold the Dog", "Baldomar", "Reimar"]
    assert [b["trait_names"] for b in bros] == [["Determined"], ["Gluttonous", "Dumb"], ["Brave"]]
    shown = [[b["shown"][k] for k in ("hp", "fat", "res", "init", "msk", "rsk", "mdf", "rdf")] for b in bros]
    assert shown == [[56, 77, 44, 77, 62, 46, 22, 24], [65, 81, 44, 83, 62, 35, 4, 3], [57, 87, 47, 104, 57, 52, 1, 1]]
    assert bros[0]["gear"] == ["Militia Spear", "Wooden Shield", "Rugged Surcoat", "Aketon Cap"]
    assert bros[2]["gear"] == ["Light Crossbow", "Thick Tunic", "Quiver of Bolts", "Knife (bag)"]
    # the seed text is case-sensitive: typed as SEEDTEST the game gave Alvar first
    assert rosters["SEEDTEST"][0]["name"] == "Alvar" and rosters["seedtest"][0]["name"] == "Winrich"
    assert not eng.files and len(eng.cfiles) > 3000, "the base game ran from its compiled scripts only"


@pytest.mark.skipif(not HAVE_LEGENDS, reason="Battle Brothers 1.5.2.3 with Legends 19.4.22 + MSU 1.9.0 is not installed")
def test_legends_gives_the_rosters_the_game_gave():
    from bbseed.lab import Lab, big_stack

    roots, _version = profiles.get("legends")
    assert all(r.is_file() for r in roots), "every root is an archive: nothing extracted"

    def run():
        lab = Lab("legends")
        eng = lab.eng
        compiled = [p for p in eng.included if p in eng.cfiles]
        return (len(compiled), not eng.files.keys() & eng.cfiles.keys(), lab.info(),
                [b["name"] for b in lab.roster("1234567890", "early_access_scenario")],
                [b["name"] for b in lab.roster("1234567890", "trader_scenario")])
    compiled_run, one_source_each, info, company, caravan = big_stack(run)
    assert one_source_each, "a script comes either from a mod (text) or from the base game (compiled)"
    assert compiled_run > 2000, "the base game ran from its compiled scripts"
    assert info["game_version"] == "1.5.2.3" and info["legends_version"]
    assert company == ["Simon", "Ansovald", "Thibault the Older"]
    assert caravan == ["Rikvi", "Ansovald"]

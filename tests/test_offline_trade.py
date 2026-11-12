"""The towns' trade data read from the lab (bbseed/trade.py read_trade), pinned to what the real game had.

On 2026-11-12 the game (1.5.2.3, Legends 19.4.22, MSU 1.9.0, Modern Hooks 0.6.0) started 20 Trader campaigns
(7430000000..019, map jobs, black-market counter 0) with the player's Map Options 55/38/85/24/4/yes/yes and logged
every town's price mult, attached locations and marketplace entries (bb_seedlab MODLOG "TRADE DATA OF THE TOWNS"):
the lab equals the game on all 20 maps. The values here are the game's log rows. Its getBuyPriceMult /
getSellPriceMult gave the Trading Caravan's barter: 0.033 (job 0), 0.0363 (job 7, a second brother with barter).

Whole maps (one spawn run each, ~15 s): every test is slow (--full). Skips unless the setup is installed.
"""
import pytest

from bbseed import profiles

FOUND = profiles.installed_summary()
HAVE_GAME = FOUND is not None and FOUND["game_version"] == "1.5.2.3"
HAVE_LEGENDS = HAVE_GAME and any("mod_legends-19.4.22" in m for m in FOUND["mods"]) \
    and any("1.9.0" in m for m in FOUND["mods"])

# the in-game batch's Mod Options
MAP_OPTIONS = {"mod_legends:LandRatio": 55, "mod_legends:Water": 38, "mod_legends:Snowline": 85,
               "mod_legends:Settlements": 24, "mod_legends:Factions": 4, "mod_legends:StackCitadels": True,
               "mod_legends:AllTradeLocations": True}
RUNS = {}


@pytest.fixture(scope="module")
def trade_maps():
    """seed|origin -> the map summary of a stop_at="spawn" run with trade=True, built on first use."""
    if not HAVE_LEGENDS:
        pytest.skip("Battle Brothers 1.5.2.3 with Legends 19.4.22 + MSU 1.9.0 is not installed")
    from bbseed.lab import Lab, big_stack
    from bbseed.search import checked_world_map
    lab = big_stack(lambda: Lab(None, MAP_OPTIONS))

    def get(seed, origin="trader_scenario"):
        key = seed + "|" + origin
        if key not in RUNS:
            RUNS[key] = big_stack(lambda: checked_world_map(lab, seed, origin, stop_at="spawn", blackmarket=0,
                                                            trade=True))["map"]
        return RUNS[key]
    return get


@pytest.mark.core
@pytest.mark.slow
def test_trade_matches_game_7430000000(trade_maps):
    summary = trade_maps("7430000000")
    data = summary["trade"]
    assert len(data["towns"]) == len(summary["towns"])
    assert summary["towns"][0]["name"] == "Schiffbauen"
    town = data["towns"][0]
    assert town["price_mult"] == pytest.approx(1.07)
    assert town["shop"] == [["trade/amber_shards_item", 0, 1.0], ["trade/legend_seashells_item", 0, 1.0]]
    assert summary["towns"][1]["name"] == "Seedock"
    assert data["towns"][1]["price_mult"] == pytest.approx(1.11)
    assert len(data["towns"][1]["shop"]) == 4
    company = data["company"]
    assert company["barter"] == pytest.approx(0.033)
    assert (company["assets_buy"], company["assets_sell"]) == pytest.approx((1.0, 1.0))
    assert company["brothers"] == 2
    good = data["goods"]["trade/amber_shards_item"]
    assert good["value"] > 0 and good["makers"] and good["name"]
    assert data["consts"]["BuyPriceNotProducedHere"] == pytest.approx(1.5)
    assert data["consts"]["SellPriceNotLocalCulture"] == pytest.approx(1.1)


@pytest.mark.core
@pytest.mark.slow
def test_speed_table_legends(trade_maps):
    speed = trade_maps("7430000000")["trade"]["speed"]
    assert speed["terrain"][4] == pytest.approx(0.64)               # hills, Legends' table
    # the lab's Legends player party has 100 (the base game's player_party.create sets 105, and so does the lab on
    # Vanilla): NOT measured in the game; the routes' days are "about"
    assert speed["base"] == pytest.approx(100.0)
    assert speed["global"] == pytest.approx(0.75)
    assert speed["road"] == pytest.approx(1.5)
    assert speed["assets"] == pytest.approx([1.0] * len(speed["assets"]))


@pytest.mark.core
@pytest.mark.slow
def test_barter_second_brother_7430000007(trade_maps):
    assert trade_maps("7430000007")["trade"]["company"]["barter"] == pytest.approx(0.0363)


@pytest.mark.core
@pytest.mark.slow
def test_origin_assets_legends(trade_maps):
    company = trade_maps("7430000000", "beast_hunters_scenario")["trade"]["company"]
    assert (company["assets_buy"], company["assets_sell"]) == pytest.approx((1.2, 0.8))


@pytest.mark.core
@pytest.mark.slow
@pytest.mark.parametrize("origin, assets", [("trader_scenario", (0.9, 1.1)), ("beast_hunters_scenario", (1.1, 0.9))])
def test_origin_assets_vanilla(vanilla_lab, origin, assets):
    summary = vanilla_lab.world_map("7450000000", origin, stop_at="spawn", trade=True)["map"]
    company = summary["trade"]["company"]
    assert (company["assets_buy"], company["assets_sell"]) == pytest.approx(assets)
    assert company["barter"] == 0.0
    assert summary["trade"]["speed"]["base"] == pytest.approx(105.0)
    assert summary["trade"]["speed"]["terrain"][4] == pytest.approx(0.65)

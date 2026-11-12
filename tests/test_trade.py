"""Trade routes (bbseed/trade.py): prices, stock, travel times and the route finder. No game needed: the towns, goods and
maps here are made by hand, with the game's constants (vanilla config/world_assets.nut, Legends' speed table) and the
values measured in the game (bb_seedlab MODLOG "TRADE DATA OF THE TOWNS")."""
import pytest

from bbseed import trade

CONSTS = {"BaseBuyPrice": 1.0, "BuyPriceNotProducedHere": 1.5, "BuyPriceNotLocalCulture": 1.5,
          "BaseSellPrice": 0.15, "SellPriceNotProducedHere": 1.01, "SellPriceNotLocalCulture": 1.1}
NEUTRAL, NORTHERN, SOUTHERN = 0, 1, 2


def company(barter=0.0, buy=1.0, sell=1.0, brothers=12):
    return {"barter": barter, "assets_buy": buy, "assets_sell": sell, "brothers": brothers}


def town(price_mult=1.0, culture=NORTHERN, active=(), port=False, shop=(), market_mult=1.0):
    return {"shop": [list(e) for e in shop], "price_mult": price_mult, "market_mult": market_mult, "culture": culture,
            "active": list(active), "port": port}


AMBER = {"value": 260, "culture": NEUTRAL, "makers": ["attached_location.amber_collector"], "name": "Amber"}
SILK = {"value": 460, "culture": SOUTHERN, "makers": ["attached_location.silk_farm"], "name": "Silk"}


# ------------------------------------------------------------------------------------------------- Task 1: the model
@pytest.mark.core
def test_expected_count():
    assert trade.expected_count(0) == 2.0
    assert trade.expected_count(10) == pytest.approx(1.226546, abs=1e-6)
    assert trade.expected_count(50) == pytest.approx(0.505049, abs=1e-6)
    assert trade.expected_count(80) == pytest.approx(0.207921, abs=1e-6)


@pytest.mark.core
def test_town_mults_measured():
    c = company(barter=0.033)
    assert trade.town_mults(1.07, c) == pytest.approx((1.03469, 1.10531), abs=1e-5)
    assert trade.town_mults(1.04, c) == pytest.approx((1.00568, 1.07432), abs=1e-5)


@pytest.mark.core
def test_prices():
    maker = town(1.07, active=["attached_location.amber_collector"])
    assert trade.buy_price(AMBER, maker, 1.0, company(barter=0.033), CONSTS) == 270
    buyer = town(1.28)
    assert trade.sell_price(AMBER, buyer, company(barter=0.033), CONSTS) == 347
    assert trade.sell_price(SILK, town(1.28, culture=NORTHERN), company(), CONSTS) == 654
    # sold where it is made: BaseSellPrice 0.15 (and silk is local in a southern town)
    silk_town = town(1.28, culture=SOUTHERN, active=["attached_location.silk_farm"])
    assert trade.sell_price(SILK, silk_town, company(), CONSTS) == int(460 * 1.28 * 0.15)


@pytest.mark.core
def test_local_culture():
    assert trade.local_culture(SILK, town(culture=NORTHERN, port=True))
    assert not trade.local_culture(SILK, town(culture=NORTHERN))
    assert trade.local_culture(SILK, town(culture=SOUTHERN))
    assert trade.local_culture(AMBER, town(culture=SOUTHERN))
    assert trade.made_here(AMBER, town(active=["attached_location.amber_collector"]))
    assert not trade.made_here(AMBER, town(active=["attached_location.silk_farm"]))


SPEED = {"base": 105.0, "global": 0.75, "road": 1.5,
         "terrain": [0.0, 0.0, 1.0, 0.5, 0.64, 0.64, 0.64, 0.64, 0.64, 0.25, 0.5, 1.0, 0.75, 0.9, 0.9, 1.0, 0.5, 0.75,
                     0.9, 0.64, 0.64]}


@pytest.mark.core
def test_tile_seconds():
    summary = {"size": [3, 1], "terrain": "LHO", "roads": "1..", "trade": {"speed": SPEED}}
    out = trade.tile_seconds(summary)
    assert out[0] == pytest.approx(170 / 118.125)
    assert out[1] == pytest.approx(170 / (78.75 * 0.64))
    assert out[2] is None
    assert trade.travel_days(105) == 1.0
    assert trade.travel_days(210) == pytest.approx(2.2)


@pytest.mark.edge
def test_tile_seconds_slow_terrain_on_a_road_is_at_least_open_land():
    summary = {"size": [2, 1], "terrain": "SM", "roads": "11", "trade": {"speed": SPEED}}
    out = trade.tile_seconds(summary)
    assert out[0] == pytest.approx(170 / 78.75)              # swamp 0.5 x 1.5 = 0.75 -> 1.0
    assert out[1] == pytest.approx(170 / 78.75)              # mountains 0.25 x 1.5 -> 1.0


@pytest.mark.core
def test_ship_fare():
    a = {"x": 0, "y": 0}
    b = {"x": 0, "y": 20}
    assert trade.hex_distance(a, b) == 20
    assert trade.ship_fare(a, b, 12) == 120
    assert trade.ship_fare(a, b, 2) == 20
    c = {"x": 20, "y": 10}                                    # Coords (20, 0): 20 steps along the columns
    assert trade.hex_distance(a, c) == 20

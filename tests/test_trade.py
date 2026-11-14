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


@pytest.mark.edge
def test_tile_seconds_brothers_and_assets():
    speed = dict(SPEED, mods=[0.0, 0.5, 0.0, 0.0, 0.01] + [0.0] * 16, wheel=1.1, assets=[1.0, 1.0, 2.0])
    summary = {"size": [3, 1], "terrain": "LHO", "roads": "1..", "trade": {"speed": speed}}
    out = trade.tile_seconds(summary)
    assert out[0] == pytest.approx(170 / (78.75 * 1.1 * 1.5 * 2.0))     # wheel, road, then the Assets' mult
    assert out[1] == pytest.approx(170 / (78.75 * 0.65 * 1.1))         # hills 0.64 + a brother's 0.01
    assert out[2] is None                                              # a modifier never opens the ocean


@pytest.mark.core
def test_ship_fare():
    a = {"x": 0, "y": 0}
    b = {"x": 0, "y": 20}
    assert trade.hex_distance(a, b) == 20
    assert trade.ship_fare(a, b, 12) == 120
    assert trade.ship_fare(a, b, 2) == 20
    c = {"x": 20, "y": 10}                                    # Coords (20, 0): 20 steps along the columns
    assert trade.hex_distance(a, c) == 20


# ------------------------------------------------------------------------------------------- Task 2: the route finder
AMBER_ID = "trade/amber_shards_item"
SILK_ID = "trade/silk_item"
GOODS = {AMBER_ID: AMBER, SILK_ID: SILK}


def _map(w, h, places, terrain=None, roads=None, barter=0.0, brothers=12):
    """A hand-made summary with a "trade" entry. `places`: one dict per town: x, y and optional price_mult, port,
    makes (a good id the town makes and sells, R 0, P 1.0), shop (entries), culture, market (False = no marketplace)."""
    towns, rows = [], []
    for n, p in enumerate(places):
        towns.append({"name": p.get("name", "T%d" % n), "script": "small_farming_village", "size": 2, "x": p["x"],
                      "y": p["y"], "southern": False, "military": False, "port": p.get("port", False),
                      "faction": None})
        shop = [list(e) for e in p.get("shop", ())]
        active = []
        if "makes" in p:
            shop.append([p["makes"], 0, 1.0])
            active += GOODS[p["makes"]]["makers"]
        rows.append({"shop": shop, "price_mult": p.get("price_mult", 1.0),
                     "market_mult": 1.0 if p.get("market", True) else None, "culture": p.get("culture", NORTHERN),
                     "active": active, "port": p.get("port", False)})
    return {"size": [w, h], "layout": "even-q-up", "attempts": 1, "terrain": terrain or "L" * (w * h),
            "roads": roads or "." * (w * h), "towns": towns,
            "trade": {"towns": rows, "goods": GOODS, "company": company(barter=barter, brothers=brothers),
                      "consts": CONSTS, "speed": SPEED}}


def _names(summary, route):
    return [summary["towns"][i]["name"] for i in route["towns"]]


def _check_against_full_search(summary):
    """The pruned search must give the same routes as the search over every combination."""
    fast = trade.find_routes(summary)
    full = trade.find_routes(summary, _prune=False)
    assert fast == full
    return fast


@pytest.mark.core
def test_two_town_back_and_forth():
    summary = _map(40, 12, [{"name": "A", "x": 5, "y": 5, "makes": AMBER_ID},
                            {"name": "B", "x": 25, "y": 5, "price_mult": 1.2}])
    routes = _check_against_full_search(summary)
    assert len(routes) == 1
    route = routes[0]
    assert sorted(_names(summary, route)) == ["A", "B"]
    assert route["ships"] == [False, False] and route["fares"] == 0
    each = 315 - 260                                          # floor(260 x 1.2 x 1.01) - ceil(260 x 1.0)
    assert route["deals"] == [{"good": "Amber", "buy_in": 0, "sell_in": 1, "each": each, "count": 2.0}]
    assert route["per_lap"] == each * 2
    assert route["lap_days"] < 3
    assert route["per_day"] == pytest.approx(each * 2 / 3)
    # each walked leg is a path of neighbouring tiles from one town to the other
    order = route["towns"]
    for n, path in enumerate(route["paths"]):
        a, b = summary["towns"][order[n]], summary["towns"][order[(n + 1) % len(order)]]
        assert path[0] == (a["x"], a["y"])
        assert path[-1] == (b["x"], b["y"])
        assert len(path) == 21                                # 20 steps


@pytest.mark.core
def test_lap_counts_at_least_restock():
    near = _map(40, 12, [{"x": 5, "y": 5, "makes": AMBER_ID}, {"x": 15, "y": 5, "price_mult": 1.2}])
    far = _map(120, 12, [{"x": 5, "y": 5, "makes": AMBER_ID}, {"x": 105, "y": 5, "price_mult": 1.2}])
    (short,) = trade.find_routes(near)
    (long,) = trade.find_routes(far)
    assert short["lap_days"] < 1
    assert short["per_day"] == pytest.approx(short["per_lap"] / 3)
    assert 4 < long["lap_days"] <= trade.MAX_LAP_DAYS
    assert long["per_day"] == pytest.approx(long["per_lap"] / long["lap_days"])
    # each leg of more than a day takes 10 % longer
    seconds = 100 * trade.tile_seconds(far)[0]
    assert long["lap_days"] == pytest.approx(2 * trade.travel_days(seconds))


@pytest.mark.edge
def test_lap_over_five_days_is_no_route():
    far = _map(150, 12, [{"x": 5, "y": 5, "makes": AMBER_ID}, {"x": 140, "y": 5, "price_mult": 1.2}])
    assert trade.find_routes(far) == []


@pytest.mark.core
def test_top3_share_no_town():
    # three groups of three towns, too far apart for one loop; in each a maker and two buyers: the loops {maker, buyer}
    # and {maker, both buyers} share towns
    places = []
    for group, x0 in enumerate((4, 134, 264)):
        places.append({"name": "M%d" % group, "x": x0, "y": 6, "makes": SILK_ID if group == 1 else AMBER_ID,
                       "culture": SOUTHERN})
        places.append({"name": "B%d" % group, "x": x0 + 8, "y": 6, "price_mult": 1.2 + 0.05 * group})
        places.append({"name": "C%d" % group, "x": x0 + 16, "y": 6, "price_mult": 1.1})
    summary = _map(284, 14, places)
    routes = _check_against_full_search(summary)
    assert len(routes) == trade.TOP
    assert sorted(sorted(_names(summary, r))[0] for r in routes) == ["B0", "B1", "B2"]
    seen = set()
    for route in routes:
        assert seen.isdisjoint(route["towns"])
        seen.update(route["towns"])
        assert 2 <= len(route["towns"]) <= trade.MAX_TOWNS
    per_day = [r["per_day"] for r in routes]
    assert per_day == sorted(per_day, reverse=True)


def _bay(w=40, h=40, gap=(8, 22), land_rows=8):
    """Land on the left and right, an ocean between the columns `gap` that reaches up to the top `land_rows` rows:
    walking from one side to the other goes round the north end of the bay."""
    rows = []
    for y in range(h):
        rows.append("".join("O" if gap[0] <= x <= gap[1] and y < h - land_rows else "L" for x in range(w)))
    return "".join(rows)


@pytest.mark.core
def test_ship_leg_rules():
    terrain = _bay(h=70)
    ports = [{"name": "A", "x": 5, "y": 10, "port": True, "makes": AMBER_ID},
             {"name": "B", "x": 25, "y": 10, "port": True, "price_mult": 1.5}]
    # 20 tiles apart over a deep bay: walking round it both ways takes more than 5 days, so one leg goes by ship (never
    # both: a loop never only sails)
    summary = _map(40, 70, ports, terrain=terrain)
    (route,) = _check_against_full_search(summary)
    assert route["ships"].count(True) == 1
    assert route["fares"] == trade.ship_fare(summary["towns"][0], summary["towns"][1], 12) == 120
    ship_leg = route["ships"].index(True)
    assert route["paths"][ship_leg] == []
    assert route["per_day"] == pytest.approx((route["per_lap"] - 120) / max(route["lap_days"], 3))
    # a shallow bay, 30 tiles apart: too far for a ship, walked
    far = _map(40, 40, [dict(ports[0], x=3), dict(ports[1], x=33)], terrain=_bay(gap=(6, 30)))
    (route,) = trade.find_routes(far)
    assert route["ships"] == [False, False] and route["fares"] == 0
    # no bay: walking takes less than 0.75 days, walked
    (route,) = trade.find_routes(_map(40, 40, ports))
    assert route["ships"] == [False, False] and route["fares"] == 0


@pytest.mark.dirty
def test_no_profitable_loop():
    empty = _map(30, 10, [{"x": 3, "y": 3}, {"x": 20, "y": 3}])
    assert trade.find_routes(empty) == []
    no_gain = _map(30, 10, [{"x": 3, "y": 3, "makes": AMBER_ID}, {"x": 20, "y": 3, "price_mult": 0.8}])
    assert trade.find_routes(no_gain) == []
    no_market = _map(30, 10, [{"x": 3, "y": 3, "makes": AMBER_ID},
                              {"x": 20, "y": 3, "price_mult": 1.3, "market": False}])
    assert trade.find_routes(no_market) == []
    old = _map(30, 10, [{"x": 3, "y": 3, "makes": AMBER_ID}, {"x": 20, "y": 3, "price_mult": 1.3}])
    del old["trade"]
    assert trade.find_routes(old) == []
    assert trade.find_routes(dict(old, trade=None)) == []


@pytest.mark.edge
def test_island_only_by_ship():
    w, h = 60, 30

    def sea_with(land):
        return "".join("L" if land(x, y) else "O" for y in range(h) for x in range(w))

    # mainland x < 20, the sea, an island at x 34..38, y 12..16
    terrain = sea_with(lambda x, y: x < 20 or (34 <= x <= 38 and 12 <= y <= 16))
    places = [{"name": "M1", "x": 18, "y": 10, "port": True, "price_mult": 1.3},
              {"name": "M2", "x": 18, "y": 20, "port": True, "price_mult": 1.25},
              {"name": "I", "x": 36, "y": 14, "port": True, "makes": AMBER_ID}]
    summary = _map(w, h, places, terrain=terrain, brothers=2)
    routes = _check_against_full_search(summary)
    island = [r for r in routes if 2 in r["towns"]]
    assert len(island) == 1
    route = island[0]
    k = len(route["towns"])
    at = route["towns"].index(2)
    assert route["ships"][at] and route["ships"][(at - 1) % k]          # sails in and out
    assert not all(route["ships"])
    # the island too far from every port: in no route, no error
    terrain = sea_with(lambda x, y: x < 10 or (52 <= x <= 56 and 12 <= y <= 16))
    far = _map(w, h, [dict(places[0], x=8), dict(places[1], x=8), dict(places[2], x=54)], terrain=terrain,
               brothers=2)
    assert all(2 not in r["towns"] for r in trade.find_routes(far))


# ------------------------------------------------------------------------------------------ Task 3: a real lab map
@pytest.mark.core
def test_real_map_7430000000():
    """The lab's map of 7430000000 (Trading Caravan, the in-game batch's Map Options, black-market counter 0) with its
    trade entry (tests/data, written by Lab.world_map(..., stop_at="spawn", trade=True)): the three loops, checked once
    by hand against the research prototype (same towns; its laps were longer: it added 10 % to the whole lap)."""
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent / "data" / "trade_map_7430000000.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    routes = trade.find_routes(summary)
    assert [_names(summary, r) for r in routes] == [
        ["Seedock", "Thurn", "Rothenfeste", "Quadim", "Malaluk"],
        ["Schiffbauen", "Fischschlachten", "Asad", "Hohenbruch", "Krauchthal"],
        ["Sandehaven", "Finsterstadt", "Gunnsted", "Horn", "Finsterwalde"]]
    assert [r["per_day"] for r in routes] == pytest.approx([851.3, 345.5, 225.0], abs=0.5)
    assert [r["lap_days"] for r in routes] == pytest.approx([3.083, 3.943, 4.174], abs=0.01)
    assert all(r["fares"] == 0 for r in routes)
    top = routes[0]["deals"][0]
    assert (top["good"], top["each"], top["count"]) == ("Silk", 137, 4.0)        # two shop entries, one deal
    assert routes == trade.find_routes(summary, _prune=False)


@pytest.mark.dirty
def test_a_failed_read_is_kept_in_the_map(monkeypatch):
    """Lab._add_trade: a read that fails leaves the map without "trade" and puts the reason in the map too
    (map["trade_error"]: the legend then says the data could not be read, not "check the seed again")."""
    from types import SimpleNamespace
    from bbseed.lab import Lab

    def broken(_lab):
        raise ValueError("no marketplace list")
    monkeypatch.setattr(trade, "read_trade", broken)
    fake = SimpleNamespace(eng=SimpleNamespace(vm=SimpleNamespace(stack=[1, 2])))
    out = {"map": {"towns": []}}
    Lab._add_trade(fake, out)
    assert "trade" not in out["map"] and fake.eng.vm.stack == []
    assert out["trade_error"] == out["map"]["trade_error"] == "ValueError: no marketplace list"

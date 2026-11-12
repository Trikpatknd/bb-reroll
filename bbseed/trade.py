"""Trade routes for the start of a campaign: what the towns sell, what they pay, how long the walk between them is, and
the best loops of towns to trade along.

Standard library only (no tkinter, no bbreroll). The facts are bb_seedlab MODLOG "TRADE DATA OF THE TOWNS": the lab
equals the game on 20 of 20 Legends maps (531 towns) at black-market counter 0 for the towns' shop entries, buildings,
attached locations and getPriceMult(); the prices below are trading_good_item's own formulas (not hooked by Legends).

The "trade" entry of a map summary (read_trade fills it after a stop_at="spawn" run):

    {"towns": [{"shop": [[S, R, P], ...],   the marketplace's trade-good entries (script under scripts/items/, rarity,
                                             price mult), from settlement.onUpdateShopList
                "price_mult": f,             settlement.getPriceMult()
                "market_mult": f | None,     the marketplace building's getPriceMult(); None = the town has no marketplace
                "culture": i,                settlement.getCulture()
                "active": [ids],             the IDs of the town's active attached locations
                "port": bool}, ...],         hasBuilding("building.port") (a harbor: ships, and every culture is local)
                                             (same order as summary["towns"])
     "goods": {S: {"value": i, "culture": i, "makers": [ids], "name": s}},
     "company": {"barter": f, "assets_buy": f, "assets_sell": f, "brothers": i},
     "consts": {"BaseBuyPrice", "BuyPriceNotProducedHere", "BuyPriceNotLocalCulture", "BaseSellPrice",
                "SellPriceNotProducedHere", "SellPriceNotLocalCulture"},     ::Const.World.Assets
     "speed": {"base": f, "global": f, "road": f, "terrain": [f, ...]}}      the player's speed and the terrain table

Prices (trading_good_item.getBuyPrice / getSellPrice, a town's getBuy/SellPriceMult as measured in the game):
    buy  = ceil(value x P x market mult x buy mult x (made here ? BaseBuyPrice : BuyPriceNotProducedHere)
                x (local ? 1 : BuyPriceNotLocalCulture))
    sell = floor(value x sell mult x (made here ? BaseSellPrice : SellPriceNotProducedHere)
                 x (local ? 1 : SellPriceNotLocalCulture))
    buy mult = getPriceMult x assets buy x (1 - barter), sell mult = getPriceMult x assets sell x (1 + barter)
Relations at the start act as neutral (measured), town situations are not modelled (a fresh map has none).

Travel (not measured in the game, so the GUI says "about"): seconds per tile = 170 / (base x global x m),
m = the terrain's speed mult, on a road max(m x road mult, 1.0); a step between neighbours costs the mean of the two
tiles; a day is 105 s; a trip of more than a day takes 10 % longer (the game's own getDaysRequiredToTravel rule).
"""
import math

DAY_SECONDS = 105.0
TILE_PIXELS = 170.0
LONG_TRIP = 1.1             # the game's estimate adds 10 % to a trip of more than one day (nights are slower)
STOCK_CAP = 2               # trade goods per shop entry without the trader follower (nobody has one at the start)


# ------------------------------------------------------------------------------------------------- stock
_count_cache = {}


def expected_count(rarity, cap=STOCK_CAP):
    """How many items building.fillStash puts in the shop for one entry of rarity `rarity`, on average (no town
    modifiers: RarityMult 1.0). Each try draws p = rand(0, 100): p < r ends the entry; else an item, and (r != 0) r += p;
    at most `cap` items. Exact: the sum over every way the draws can go."""
    key = (rarity, cap)
    if key not in _count_cache:
        def tries(r, num):
            if num >= cap:
                return 0.0
            total = 0.0
            for p in range(101):
                if p >= r:
                    total += 1.0 + tries(r + p if r != 0 else r, num + 1)
            return total / 101.0
        _count_cache[key] = tries(rarity, 0)
    return _count_cache[key]


# ------------------------------------------------------------------------------------------------- prices
def town_mults(price_mult, company):
    """(buy mult, sell mult) of a town for the company: its getPriceMult with the company's Assets buy / sell
    multipliers and barter (Legends; 0 in the base game)."""
    barter = company["barter"]
    return (price_mult * company["assets_buy"] * (1.0 - barter),
            price_mult * company["assets_sell"] * (1.0 + barter))


def made_here(good, town):
    """The town has an active attached location that makes the good (its ProducingBuildings)."""
    return any(m in town["active"] for m in good["makers"])


def local_culture(good, town):
    """The good is Neutral (culture 0), or the town has the good's culture, or the town has a harbor."""
    return good["culture"] == 0 or town["culture"] == good["culture"] or bool(town["port"])


def buy_price(good, town, entry_p, company, consts):
    buy, _sell = town_mults(town["price_mult"], company)
    market = town["market_mult"] if town.get("market_mult") is not None else 1.0
    return math.ceil(good["value"] * entry_p * market * buy
                     * (consts["BaseBuyPrice"] if made_here(good, town) else consts["BuyPriceNotProducedHere"])
                     * (1.0 if local_culture(good, town) else consts["BuyPriceNotLocalCulture"]))


def sell_price(good, town, company, consts):
    _buy, sell = town_mults(town["price_mult"], company)
    return math.floor(good["value"] * sell
                      * (consts["BaseSellPrice"] if made_here(good, town) else consts["SellPriceNotProducedHere"])
                      * (1.0 if local_culture(good, town) else consts["SellPriceNotLocalCulture"]))


# ------------------------------------------------------------------------------------------------- travel
def tile_seconds(summary):
    """Seconds the company needs to cross each tile, in the order of summary["terrain"] (y-major); None = it cannot
    walk there (a speed mult of 0: ocean, impassable). Reads summary["trade"]["speed"] and the roads ("." = none)."""
    speed = summary["trade"]["speed"]
    table = speed["terrain"]
    base = speed["base"] * speed["global"]
    road_mult = speed["road"]
    roads = summary.get("roads") or "." * len(summary["terrain"])
    from bbseed.mapgen import TERRAIN_CHARS
    index = {ch: i for i, ch in enumerate(TERRAIN_CHARS)}
    out = []
    for ch, road in zip(summary["terrain"], roads):
        i = index[ch]
        m = table[i] if i < len(table) else 0.0
        if m <= 0:
            out.append(None)
            continue
        if road != ".":
            m = max(m * road_mult, 1.0)
        out.append(TILE_PIXELS / (base * m))
    return out


def travel_days(seconds):
    """Days for a walk of `seconds` (game seconds at full speed): over one day the game's estimate adds 10 %."""
    days = seconds / DAY_SECONDS
    return days * LONG_TRIP if days > 1 else days


def hex_distance(a, b):
    """Tiles between two towns (their square x, y): the game's getDistanceTo on the hex coordinates
    X = x, Y = y - x // 2."""
    ax, ay = a["x"], a["y"] - a["x"] // 2
    bx, by = b["x"], b["y"] - b["x"] // 2
    dx, dy = ax - bx, ay - by
    return max(abs(dx), abs(dy), abs(dx + dy))


def ship_fare(a, b, brothers):
    """port_building.getCostTo: Math.round(distance x brothers x 0.5 x 0.1) x 10 crowns."""
    return int(math.floor(hex_distance(a, b) * brothers * 0.5 * 0.1 + 0.5)) * 10

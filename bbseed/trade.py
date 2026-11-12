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


# ------------------------------------------------------------------------------------------------- the route finder
MAX_TOWNS = 5               # a loop has 2 to 5 towns (2 = a back-and-forth run)
MAX_LAP_DAYS = 5.0          # longer laps are not considered
RESTOCK_DAYS = 3.0          # shops restock every 3 days: a faster lap earns no more, so a lap counts at least this long
SHIP_MAX_TILES = 25         # a ship leg only between two ports at most this far apart (straight) ...
SHIP_MIN_WALK_DAYS = 0.75   # ... whose walk would take at least this long ("short passages that save a lot of walking")
MAX_SHIP_LEGS = 2           # a loop sails at most this often, and never on every leg
TOP = 3


def _walks(summary, cost, start, limit):
    """Dijkstra from the tile `start` over the tile costs (a step costs the mean of the two tiles; a tile of cost None
    is never entered; when the start tile itself has no cost, the next tile's counts for it). Stops past `limit`
    seconds. -> (seconds by tile, the previous tile by tile)."""
    import heapq
    from bbseed.mapdraw import ROAD_DIRECTIONS
    w, h = summary["size"]
    dist = {start: 0.0}
    prev = {}
    heap = [(0.0, start)]
    while heap:
        d, here = heapq.heappop(heap)
        if d > dist[here]:
            continue
        x, y = here
        c_here = cost[y * w + x]
        for dx, dy in ROAD_DIRECTIONS[x & 1]:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            c = cost[ny * w + nx]
            if c is None:
                continue
            nd = d + ((c_here if c_here is not None else c) + c) / 2
            if nd > limit:
                continue
            if nd < dist.get((nx, ny), math.inf):
                dist[(nx, ny)] = nd
                prev[(nx, ny)] = here
                heapq.heappush(heap, (nd, (nx, ny)))
    return dist, prev


def _cliques(n, compatible, size):
    """Every set of 2..size of the indices 0..n-1 (sorted tuples) in which each pair is compatible."""
    def grow(combo, candidates):
        for pos, j in enumerate(candidates):
            bigger = combo + (j,)
            if len(bigger) >= 2:
                yield bigger
            if len(bigger) < size:
                yield from grow(bigger, [k for k in candidates[pos + 1:] if compatible[j][k]])
    yield from grow((), list(range(n)))


def _pick(found, top):
    """The best rows first, skipping a row that shares a town with one picked before; `found` is sorted."""
    chosen, used = [], set()
    for row in found:
        towns = row[0][3]
        if used.isdisjoint(towns):
            chosen.append(row)
            used.update(towns)
            if len(chosen) == top:
                break
    return chosen


def find_routes(summary, top=TOP, _prune=True):
    """The `top` best trade loops of the map by crowns per day, sharing no town; [] when the summary has no "trade"
    entry or no loop earns anything. Each route:

        {"towns": [i, ...]       the loop in walking order (indices into summary["towns"]), back to the first at the end
         "ships": [bool, ...]    per leg (town n to town n + 1, the last back to the first): by ship
         "paths": [[(x, y), ...], ...]  per leg the tiles walked, both towns included; [] for a ship leg
         "lap_days": f           walking days of one lap (ship legs take none; each leg over a day x 1.1)
         "fares": i              crowns of the lap's ship legs for the starting company
         "per_lap": f            crowns one lap earns before fares: each deal's gain x its expected stock
         "per_day": f            (per_lap - fares) / max(lap_days, RESTOCK_DAYS)
         "deals": [{"good": name, "buy_in": i, "sell_in": i, "each": crowns, "count": expected items}, ...]
                                 largest each x count first}

    The rules (the spec's): towns with a marketplace only; a good is bought only in a town that makes it and sold at
    the stop of the loop that pays the most; a leg may go by ship only between two ports at most SHIP_MAX_TILES apart
    whose walk would take at least SHIP_MIN_WALK_DAYS, at most MAX_SHIP_LEGS ships and never only ships; laps of at
    most MAX_LAP_DAYS. Per set of towns the order and the ship legs with the most crowns per day are taken; the best
    sets are then picked greedily, the best first, skipping any that shares a town with one picked before. `_prune`
    (tests only: False) checks every set in full; the result is the same."""
    import itertools
    data = summary.get("trade")
    if not data:
        return []
    towns, rows = summary["towns"], data["towns"]
    goods, company, consts = data["goods"], data["company"], data["consts"]
    market = [i for i, row in enumerate(rows) if row.get("market_mult") is not None]
    n = len(market)
    if n < 2:
        return []
    # what each market town can buy: per entry of a good it makes, the gain at every market town
    sells = {}
    deals = []                      # deals[a] = [(expected count, gains by market town b, good id), ...]
    for a in market:
        row, mine = rows[a], []
        for s, r, p in row["shop"]:
            good = goods.get(s)
            if good is None or not made_here(good, row):
                continue
            count = expected_count(int(r))
            if count <= 0:
                continue
            buy = buy_price(good, row, p, company, consts)
            if s not in sells:
                sells[s] = [sell_price(good, rows[b], company, consts) for b in market]
            mine.append((count, [v - buy for v in sells[s]], s))
        deals.append(mine)

    def profit(combo):
        total = 0.0
        for a in combo:
            for count, gains, _s in deals[a]:
                best = max(gains[b] for b in combo if b != a)
                if best > 0:
                    total += best * count
        return total

    # walking times between the market towns
    cost = tile_seconds(summary)
    limit = MAX_LAP_DAYS * DAY_SECONDS          # a leg longer than a whole lap (in plain days) is never walked
    tiles = [(towns[i]["x"], towns[i]["y"]) for i in market]
    runs = [_walks(summary, cost, t, limit) for t in tiles]
    seconds = [[runs[a][0].get(tiles[b], math.inf) for b in range(n)] for a in range(n)]
    walk = [[travel_days(seconds[a][b]) for b in range(n)] for a in range(n)]
    port = [bool(rows[i]["port"]) for i in market]
    brothers = company["brothers"]
    fare = [[None] * n for _ in range(n)]       # the fare of a leg that may go by ship, else None
    for a in range(n):
        for b in range(n):
            if a != b and port[a] and port[b] and walk[a][b] >= SHIP_MIN_WALK_DAYS \
                    and hex_distance(towns[market[a]], towns[market[b]]) <= SHIP_MAX_TILES:
                fare[a][b] = ship_fare(towns[market[a]], towns[market[b]], brothers)
    if _prune:
        # two towns can share a loop only when going there and back takes at most a lap (a ship leg counts 0 days)
        least = [[0.0 if a == b or fare[a][b] is not None else seconds[a][b] / DAY_SECONDS for b in range(n)]
                 for a in range(n)]
        for k in range(n):
            for a in range(n):
                for b in range(n):
                    if least[a][k] + least[k][b] < least[a][b]:
                        least[a][b] = least[a][k] + least[k][b]
        compatible = [[2 * least[a][b] <= MAX_LAP_DAYS for b in range(n)] for a in range(n)]
    else:
        compatible = [[True] * n for _ in range(n)]

    def best_way(combo, gain):
        """The sort key (-per_day, lap, fares, order, ships) of the best way round `combo`, or None."""
        k = len(combo)
        first, rest = combo[0], combo[1:]
        best = None
        for perm in itertools.permutations(rest):
            if k > 2 and perm[0] > perm[-1]:
                continue                        # the same loop the other way round: the same times and fares
            order = (first,) + perm
            legs = [(order[i], order[(i + 1) % k]) for i in range(k)]
            sailable = [i for i, (a, b) in enumerate(legs) if fare[a][b] is not None]
            for m in range(min(MAX_SHIP_LEGS, k - 1, len(sailable)) + 1):
                for sail in itertools.combinations(sailable, m):
                    lap = sum(walk[a][b] for i, (a, b) in enumerate(legs) if i not in sail)
                    if lap > MAX_LAP_DAYS:
                        continue
                    fares = sum(fare[legs[i][0]][legs[i][1]] for i in sail)
                    key = (-(gain - fares) / max(lap, RESTOCK_DAYS), lap, fares, order,
                           tuple(i in sail for i in range(k)))
                    if best is None or key < best:
                        best = key
        return best

    candidates = []                             # (profit of a lap, set of towns), the most profitable first
    for combo in _cliques(n, compatible, MAX_TOWNS):
        gain = profit(combo)
        if gain > 0:
            candidates.append((gain, combo))
    candidates.sort(key=lambda c: (-c[0], c[1]))
    found = []                                  # (sort key, profit of a lap) of every set with a loop that earns
    for pos, (gain, combo) in enumerate(candidates):
        best = best_way(combo, gain)
        if best is not None and best[0] < 0:
            found.append((best, gain))
            if _prune:
                # a set not tried yet earns at most its profit / RESTOCK_DAYS per day: when every pick made so far beats
                # that, no later set can come before any of them, and the picks are final
                bound = candidates[pos + 1][0] / RESTOCK_DAYS if pos + 1 < len(candidates) else 0.0
                found.sort()
                chosen = _pick(found, top)
                if len(chosen) == top and all(-row[0][0] > bound for row in chosen):
                    break
    found.sort()
    out = []
    for (neg_day, lap, fares, order, ships), gain in _pick(found, top):
        k = len(order)
        paths = []
        for i in range(k):
            a, b = order[i], order[(i + 1) % k]
            if ships[i]:
                paths.append([])
                continue
            prev = runs[a][1]
            here, path = tiles[b], [tiles[b]]
            while here != tiles[a]:
                here = prev[here]
                path.append(here)
            paths.append(path[::-1])
        route_deals = []
        for a in order:
            for count, gains, s in deals[a]:
                each, b = max((gains[b], -b) for b in order if b != a)      # the first such town on a tie
                if each > 0:
                    route_deals.append({"good": goods[s]["name"], "buy_in": market[a], "sell_in": market[-b],
                                        "each": each, "count": count})
        route_deals.sort(key=lambda d: -d["each"] * d["count"])
        out.append({"towns": [market[i] for i in order], "ships": list(ships), "paths": paths, "lap_days": lap,
                    "fares": fares, "per_lap": gain, "per_day": -neg_day, "deals": route_deals})
    return out

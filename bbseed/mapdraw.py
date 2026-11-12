"""A picture of a map summary (see mapgen.summary): terrain cells, towns, ports and the north band.

Standard library only, and no tkinter: the GUI draws the same numbers on a Tk canvas. All geometry is here, so the
SVG and the canvas show one picture:

    cells(summary)                 -> [(x0, y0, x1, y1, colour)]   one rectangle per tile, in the order of the terrain
    town_marks(summary, scale=1, verified=False)  -> [(cx, cy, radius, fill, port, label)]
    road_segments(summary, verified=False, scale=1)  -> [(x0, y0, x1, y1)] the roads: from a road tile's centre half way
                                   to the neighbour in each direction its RoadDirections has (two neighbours' halves meet)
    has_roads(summary, verified)   -> whether road_segments has anything to draw (the key entry is shown only then)
    start_mark(summary, verified)  -> (cx, cy, radius, fill, label) of the start star, or None
    star_points(cx, cy, radius)    -> the star's ten corners [(x, y)]
    band_y(summary, north_band)    -> y of the north band's line
    svg(summary, north_band=None, verified=False)  -> the whole picture as SVG text
    route_lines(summary, routes, verified, scale=1)  -> the trade routes (trade.find_routes) to draw: lines, ship
                                   dashes and a tag per route; [] off a verified setup
    route_legend(summary, routes, verified)  -> the routes' legend lines (or the line that says why there are none)

How the tiles are placed (the layout the lab measured against the game, mapgen.LAYOUT "even-q-up"): the map is
drawn with NORTH AT THE TOP, i.e. high y is up the picture (the game's direction N is y + 1). Flat-topped hexes in
columns: column x is CELL_W wide and a tile CELL_H high, and the EVEN columns (0, 2, ...) sit half a row lower (further
south) than the odd ones. A hex is drawn as the rectangle round its centre; the two columns' offset of half a row makes
the rectangles fill the picture without gaps or overlaps. Coordinates are in pixels from the top left corner; `scale`
multiplies all of them (the SVG and the Tk canvas use the same numbers at the same scale).

`north_band` is a percent of the map's rows counted from the top (north) edge; the dashed line is its lower edge.
"""
from xml.sax.saxutils import escape

CELL_W = 7                  # pixels (at scale 1) of one column ...
CELL_H = 8                  # ... and of one tile in it; a hex is about 1.15 times as high as the column pitch is wide
FOOTER = 18                 # the strip under the map with the key (SVG only)

# One colour per terrain character of mapgen.TERRAIN_CHARS (the test suite keeps the two in step).
TERRAIN_COLOURS = {
    "X": "#1b1b1b",         # Impassable
    "O": "#1d4f91",         # Ocean
    "L": "#8cc152",         # Plains (the game's Land)
    "S": "#607d4a",         # Swamp
    "H": "#b59f5a",         # Hills
    "F": "#2e7d32",         # Forest
    "J": "#a9c7bd",         # SnowyForest
    "V": "#5cab4d",         # LeaveForest
    "A": "#c27a2c",         # AutumnForest
    "M": "#8a8a8a",         # Mountains
    "U": "#a39382",         # Urban
    "G": "#d9c85a",         # Farmland
    "N": "#f4f8fb",         # Snow
    "B": "#b4583a",         # Badlands
    "T": "#9fb09d",         # Tundra
    "E": "#cdbb78",         # Steppe
    "C": "#4f9bd0",         # Shore
    "D": "#ecd9a0",         # Desert
    "Q": "#2fb3a0",         # Oasis
    "g": "#6f9a64",         # SwampGreen (Legends)
    "f": "#3d5f3f",         # SwampForest (Legends)
}

TOWN_RADIUS = {1: 3.0, 2: 4.0, 3: 5.0}      # pixels at scale 1, by the settlement's size
TOWN_FILL = {"southern": "#8e44ad", "military": "#c0392b", "town": "#ffffff"}
# What the three circle colours mean, in the words of the Map view's fields: its "Towns" is size 2 only, so the white
# circle is a village, town or city; "Stronghold" is the field's word for the forts. The GUI's legend and the SVG's key
# both use these.
KIND_LABELS = {"town": "Village, town or city", "military": "Stronghold", "southern": "City state"}
NAME_NOT_VERIFIED = "(name not verified)"
PORT_RING = "#0b2a4a"
# The company's start tile (summary["start"], from a stop_at="spawn" run): a star in the middle of its tile, drawn only on
# a setup whose maps were checked against the game (mapgen.verified_setup: the caller says so with `verified`).
START_RADIUS = 6.0          # pixels at scale 1: a little bigger than the biggest town circle
START_FILL = "#ffd400"
START_OUTLINE = "#111111"
START_LABEL = "Start"
START_TIP = "Your company starts here."
# The roads (summary["roads"], the finished map's RoadDirections): a thin line above the terrain and below the towns,
# drawn only on a setup whose maps were checked against the game (`verified`, as the start star).
ROAD_COLOUR = "#6b4423"
ROAD_WIDTH = 1.8            # pixels at scale 1
ROAD_LABEL = "Road"
# One character per tile, the lab's / mapgen's ROAD_CHARS (a test keeps the copies equal): the index is the tile's
# RoadDirections, bit d set = the road leaves the tile in direction d of the game's Const.Direction.
ROAD_CHARS = ".123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"
_ROAD_VALUE = {ch: i for i, ch in enumerate(ROAD_CHARS)}
# The square offset (dx, dy) of the neighbour in each direction N NE SE S SW NW (bit 1 2 4 8 16 32), by the PARITY of the
# tile's column x, in the measured layout even-q-up (N is y + 1; the even columns sit half a row lower). It is
# hexmap's table for that layout (HexMap neighbours, `Tile.nb`); a test compares the two.
ROAD_DIRECTIONS = (
    ((0, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0)),      # even x
    ((0, 1), (1, 1), (1, 0), (0, -1), (-1, 0), (-1, 1)),        # odd x
)
BAND_COLOUR = "#e11d48"
_BACKGROUND = "#f4f1ea"


def town_kind(town):
    """"southern" (the city states), "military" (the forts) or "town" - what decides the circle's colour."""
    return "southern" if town["southern"] else "military" if town["military"] else "town"


def _checked(summary):
    """(width, height, terrain) of the summary; ValueError when its terrain string does not fit its size or holds a
    character that has no colour."""
    w, h = summary["size"]
    terrain = summary["terrain"]
    if len(terrain) != w * h:
        raise ValueError("the terrain string has %d characters, the map is %d x %d tiles" % (len(terrain), w, h))
    unknown = sorted(set(terrain) - set(TERRAIN_COLOURS))
    if unknown:
        raise ValueError("the terrain string has characters with no colour: %s" % " ".join(map(repr, unknown)))
    return w, h, terrain


def _top(y, height):
    """The top edge (pixels at scale 1) of row y in an ODD column of a map `height` rows high. Row 0 is the south
    edge, so it is the lowest one in the picture."""
    return (height - 1 - y) * CELL_H


def _lower(x):
    """How much lower column x sits than an odd column: half a row for the even columns (0, 2, ...)."""
    return 0 if x & 1 else CELL_H // 2


def cells(summary, scale=1):
    """One rectangle (x0, y0, x1, y1, colour) per tile, in the order of the summary's terrain string (row y = 0, the
    south edge, first; x within a row). North is at the top."""
    w, h, terrain = _checked(summary)
    out = []
    for y in range(h):
        top = _top(y, h)
        for x in range(w):
            x0 = x * CELL_W
            y0 = top + _lower(x)
            out.append((x0 * scale, y0 * scale, (x0 + CELL_W) * scale, (y0 + CELL_H) * scale,
                        TERRAIN_COLOURS[terrain[y * w + x]]))
    return out


def picture_size(summary, scale=1):
    """(width, height) in pixels of the cells' picture (without the SVG's footer)."""
    w, h, _ = _checked(summary)
    return w * CELL_W * scale, (h * CELL_H + CELL_H // 2) * scale


def town_name(town, verified=False):
    """The name of a town as the picture and the console report show it. The names of the city states are checked
    against the game since stage 2 B2 (CLAUDE.md engine fact 16) on a verified setup (`verified`, as the start mark
    has it: mapgen.verified_setup). On any other setup they are not checked, so they say so."""
    if town["southern"] and not verified:
        return town["name"] + " " + NAME_NOT_VERIFIED
    return town["name"]


def town_label(town, verified=False):
    """"Name (size 2, small_farming_village, port, southern)" - the text of a town's tooltip. Off a verified setup a
    city state's name is followed by "(name not verified)"."""
    parts = ["size %d" % town["size"], town["script"]]
    parts += [word for word in ("port", "southern", "military") if town[word]]
    return "%s (%s)" % (town_name(town, verified), ", ".join(parts))


def town_marks(summary, scale=1, verified=False):
    """One (cx, cy, radius, fill, port, label) per town: the circle on the middle of its tile (radius by size, colour
    by town_kind), and whether it gets a port ring. `verified`: see town_name."""
    w, h, _ = _checked(summary)
    out = []
    for t in summary["towns"]:
        cx = (t["x"] * CELL_W + CELL_W / 2) * scale
        cy = (_top(t["y"], h) + _lower(t["x"]) + CELL_H / 2) * scale
        radius = TOWN_RADIUS.get(t["size"], max(TOWN_RADIUS.values()))      # (a mod's size 4 is drawn as the biggest)
        out.append((cx, cy, radius * scale, TOWN_FILL[town_kind(t)], bool(t["port"]), town_label(t, verified)))
    return out


def start_mark(summary, verified=False, scale=1):
    """(cx, cy, radius, fill, label) of the start star: the middle of the tile summary["start"] = [x, y], with the same
    formulas as the towns' circles. None when `verified` is false (the setup's maps are not checked against the game),
    when the summary has no start (a run that did not go on through the start) or when it is not a tile of the map."""
    w, h, _ = _checked(summary)
    start = summary.get("start")
    if not verified or not start or len(start) != 2:
        return None
    x, y = start
    if not (isinstance(x, int) and isinstance(y, int) and 0 <= x < w and 0 <= y < h):
        return None
    cx = (x * CELL_W + CELL_W / 2) * scale
    cy = (_top(y, h) + _lower(x) + CELL_H / 2) * scale
    return cx, cy, START_RADIUS * scale, START_FILL, START_TIP


def _road_values(summary):
    """The summary's roads as one number (RoadDirections, 0..63) per tile, or None when it has none (a summary cached
    before the roads were kept, or a run that did not read them). ValueError when the string does not fit the map or
    holds a character that is not a road."""
    roads = summary.get("roads")
    if not roads:
        return None
    w, h = summary["size"]
    if len(roads) != w * h:
        raise ValueError("the roads string has %d characters, the map is %d x %d tiles" % (len(roads), w, h))
    unknown = sorted(set(roads) - set(_ROAD_VALUE))
    if unknown:
        raise ValueError("the roads string has characters that are no road: %s" % " ".join(map(repr, unknown)))
    return roads


def has_roads(summary, verified=False):
    """Whether the picture has roads: `verified`, and a roads string with at least one road tile."""
    roads = summary.get("roads")
    return bool(verified and roads and set(roads) != {"."})


def road_segments(summary, verified=False, scale=1):
    """The roads as line segments (x0, y0, x1, y1) in pixels (scale 1 = the cells' pixels): for every road tile, one
    segment per direction bit of its RoadDirections, from the tile's centre to the middle of the step to the neighbour
    in that direction (the same centres as the towns' circles). The neighbour's own bit for the way back ends at the
    same point, so a road of several tiles is one continuous line. Tile order is the roads string's (south row first),
    the directions N NE SE S SW NW within a tile. [] when `verified` is false (the setup's maps are not checked
    against the game) or the summary has no roads (an old cached one): no roads, no error."""
    if not verified:
        return []
    w, h, _ = _checked(summary)
    roads = _road_values(summary)
    if roads is None:
        return []
    out = []
    for i, ch in enumerate(roads):
        if ch == ".":
            continue
        bits = _ROAD_VALUE[ch]
        y, x = divmod(i, w)
        cx = x * CELL_W + CELL_W / 2
        cy = _top(y, h) + _lower(x) + CELL_H / 2
        for d, (dx, dy) in enumerate(ROAD_DIRECTIONS[x & 1]):
            if bits >> d & 1:
                nx, ny = x + dx, y + dy
                ex = (cx + (nx * CELL_W + CELL_W / 2)) / 2
                ey = (cy + (_top(ny, h) + _lower(nx) + CELL_H / 2)) / 2
                out.append((cx * scale, cy * scale, ex * scale, ey * scale))
    return out


def star_points(cx, cy, radius):
    """The ten corners of a five-pointed star with one point straight up: outer corners at `radius`, inner ones at
    0.4 of it. The SVG polygon and the Tk canvas polygon use these numbers."""
    import math
    out = []
    for i in range(10):
        r = radius if i % 2 == 0 else radius * 0.4
        angle = -math.pi / 2 + i * math.pi / 5
        out.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return out


def band_y(summary, north_band, scale=1):
    """The y of the north band's lower edge: `north_band` percent of the rows down from the top (0..100)."""
    _w, h, _ = _checked(summary)
    return h * min(max(north_band, 0), 100) / 100.0 * CELL_H * scale


def _num(v):
    v = round(v, 2)
    return str(int(v)) if v == int(v) else repr(v)


def svg(summary, north_band=None, scale=1, verified=False):
    """The map as SVG text: one <rect> per tile, a circle (class "town") per town, a ring (class "port") round the
    ports, and with `north_band` (percent of the rows from the top) a dashed line (class "north-band"). With `verified`
    (the setup's maps are checked against the game) the city states' names have no "(name not verified)" mark, the
    roads of the summary are one <path> (class "roads", above the terrain, below the towns), and with a start tile in
    the summary a star (class "start") is drawn."""
    w, h, terrain = _checked(summary)
    width, height = picture_size(summary, scale)
    foot = FOOTER * scale
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %s %s" width="%s" height="%s" style="background:%s">'
           % (_num(width), _num(height + foot), _num(width), _num(height + foot), _BACKGROUND)]
    ports = sum(1 for t in summary["towns"] if t["port"])
    out.append("<title>%s</title>" % escape("Battle Brothers world map, %d x %d tiles, %d towns, %d ports"
                                           % (w, h, len(summary["towns"]), ports)))
    by_char = {}
    for ch, (x0, y0, x1, y1, _colour) in zip(terrain, cells(summary, scale)):
        by_char.setdefault(ch, []).append('<rect x="%s" y="%s" width="%s" height="%s"/>'
                                          % (_num(x0), _num(y0), _num(x1 - x0), _num(y1 - y0)))
    for ch in sorted(by_char):
        out.append('<g class="terrain-%s" fill="%s" shape-rendering="crispEdges">%s</g>'
                   % (ch, TERRAIN_COLOURS[ch], "".join(by_char[ch])))
    segments = road_segments(summary, verified, scale)
    if segments:
        out.append('<path class="roads" d="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linecap="round"/>'
                   % ("".join("M%s,%sL%s,%s" % (_num(x0), _num(y0), _num(x1), _num(y1)) for x0, y0, x1, y1 in segments),
                      ROAD_COLOUR, _num(ROAD_WIDTH * scale)))
    if north_band is not None:
        y = _num(band_y(summary, north_band, scale))
        out.append('<line class="north-band" x1="0" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s" '
                   'stroke-dasharray="%s %s"/>' % (y, _num(width), y, BAND_COLOUR, _num(1.5 * scale),
                                                    _num(8 * scale), _num(5 * scale)))
    marks = town_marks(summary, scale, verified)
    out.append('<g class="towns" stroke="#111111" stroke-width="%s">' % _num(max(1, scale)))
    for cx, cy, r, fill, _port, label in marks:
        out.append('<circle class="town" cx="%s" cy="%s" r="%s" fill="%s"><title>%s</title></circle>'
                   % (_num(cx), _num(cy), _num(r), fill, escape(label)))
    out.append("</g>")
    out.append('<g class="ports" stroke="%s" stroke-width="%s">' % (PORT_RING, _num(1.5 * scale)))
    for cx, cy, r, _fill, port, _label in marks:
        if port:
            out.append('<circle class="port" cx="%s" cy="%s" r="%s" fill="none"/>' % (_num(cx), _num(cy), _num(r + 2.5 * scale)))
    out.append("</g>")
    start = start_mark(summary, verified, scale)
    if start is not None:
        cx, cy, r, fill, label = start
        points = " ".join("%s,%s" % (_num(x), _num(y)) for x, y in star_points(cx, cy, r))
        out.append('<polygon class="start" points="%s" fill="%s" stroke="%s" stroke-width="%s" stroke-linejoin="round">'
                   '<title>%s</title></polygon>' % (points, fill, START_OUTLINE, _num(max(1, scale)), escape(label)))
    key = "circle = %s (white), %s (red), %s (purple); ring = port" % (
        KIND_LABELS["town"].lower(), KIND_LABELS["military"].lower(), KIND_LABELS["southern"].lower())
    if segments:
        key += "; brown line = %s" % ROAD_LABEL.lower()
    if start is not None:
        key += "; star = %s" % START_LABEL.lower()
    if north_band is not None:
        key += "; dashed line = north band (%d%% from the top)" % north_band
    out.append('<text x="%s" y="%s" font-family="sans-serif" font-size="%s" fill="#222222">%s</text>'
               % (_num(4 * scale), _num(height + 12 * scale), _num(10 * scale), escape(key)))
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------------- trade routes (bbseed/trade.py find_routes)
# Drawn only on a setup whose maps were checked against the game (`verified`, as the roads): above the roads, below the
# towns; a ship leg is a dashed straight line from port to port. The legend goes under the map.
ROUTE_COLOURS = ("#ff2d95", "#00e5ff", "#ffb300")
ROUTE_WIDTH = 4.0           # pixels at scale 1
ROUTE_UNDERLAY = "#ffffff"  # under a ship leg's dashes, so they show on the sea
ROUTE_DASH = (9, 5)         # a ship leg's dash and gap, pixels at scale 1
ROUTE_TAG_OUTLINE = "#111111"
ROUTE_TAG_SPACE = (90, 18)  # pixels at scale 1 a tag keeps from the tags before it (about its width and height)
ROUTE_NOTE = ("Crowns per day before wages, at the start: your starting company's prices, neutral relations, no town "
              "events. Shops restock every 3 days. Days are about. For the first campaign after starting the game.")
NO_ROUTES = "No profitable trade loop on this map."
ROUTES_UNVERIFIED = "Trade routes need a checked game setup."
NO_TRADE_DATA = "This map has no trade data. Check the seed again to see its trade routes."
ROUTE_TEXTS = {"note": ROUTE_NOTE, "none": NO_ROUTES, "unverified": ROUTES_UNVERIFIED, "no_data": NO_TRADE_DATA}
ROUTE_DEALS_SHOWN = 4       # deal lines per route in the legend


def _tile_centre(x, y, h):
    """The middle of tile (x, y) at scale 1, where the towns' circles are."""
    return x * CELL_W + CELL_W / 2, _top(y, h) + _lower(x) + CELL_H / 2


def route_lines(summary, routes, verified=False, scale=1):
    """What to draw for each route (find_routes' order: the best first): {"colour", "polylines": [[(x, y), ...] per
    walked leg, along its tiles' centres], "dashes": [((x0, y0), (x1, y1)) per ship leg, town to town], "tag": (cx, cy,
    "#n  X/day") at the middle of the loop's towns}. [] when `verified` is false."""
    if not verified:
        return []
    _w, h, _ = _checked(summary)
    towns = summary["towns"]
    out = []
    for n, route in enumerate(routes):
        order = route["towns"]
        k = len(order)
        polylines, dashes = [], []
        for i in range(k):
            if route["ships"][i]:
                a, b = towns[order[i]], towns[order[(i + 1) % k]]
                pa, pb = _tile_centre(a["x"], a["y"], h), _tile_centre(b["x"], b["y"], h)
                dashes.append(((pa[0] * scale, pa[1] * scale), (pb[0] * scale, pb[1] * scale)))
            else:
                polylines.append([(cx * scale, cy * scale)
                                  for cx, cy in (_tile_centre(x, y, h) for x, y in route["paths"][i])])
        centres = [_tile_centre(towns[i]["x"], towns[i]["y"], h) for i in order]
        cx = sum(p[0] for p in centres) / k * scale
        cy = sum(p[1] for p in centres) / k * scale
        while any(abs(cx - t[0]) < ROUTE_TAG_SPACE[0] * scale and abs(cy - t[1]) < ROUTE_TAG_SPACE[1] * scale
                  for t in (r["tag"] for r in out)):
            cy += ROUTE_TAG_SPACE[1] * scale        # a tag on another one moves down below it
        out.append({"colour": ROUTE_COLOURS[n % len(ROUTE_COLOURS)], "polylines": polylines, "dashes": dashes,
                    "tag": (cx, cy, "#%d  %s/day" % (n + 1, "{:,}".format(round(route["per_day"]))))})
    return out


def _count(value):
    value = round(value, 1)
    return "%d" % value if value == int(value) else "%.1f" % value


def route_legend(summary, routes, verified=False):
    """The legend lines: per route a head line ("#1: about 494 crowns per day. Lap 3.3 days, about 1,482 crowns a lap.
    A > B > sail to C > A") and up to ROUTE_DEALS_SHOWN deal lines (indented: "Silk: buy in A, sell in B, +189 each
    x 2"), then ROUTE_NOTE. Without routes the line that says why: ROUTES_UNVERIFIED off a verified setup,
    NO_TRADE_DATA for a map without trade data (kept from before, or one without its start), else NO_ROUTES."""
    if not verified:
        return [ROUTES_UNVERIFIED]
    if summary.get("trade") is None:
        return [NO_TRADE_DATA]
    if not routes:
        return [NO_ROUTES]
    towns = summary["towns"]

    def name(i):
        return town_name(towns[i], verified)
    lines = []
    for n, route in enumerate(routes):
        order = route["towns"]
        k = len(order)
        parts = [name(order[0])]
        for i in range(k):
            nxt = name(order[(i + 1) % k])
            parts.append("sail to " + nxt if route["ships"][i] else nxt)
        fares = route["fares"]
        lines.append("#%d: about %s crowns per day. Lap %.1f days, %sabout %s crowns a lap. %s" % (
            n + 1, "{:,}".format(round(route["per_day"])), route["lap_days"],
            "ships %s crowns, " % "{:,}".format(fares) if fares else "",
            "{:,}".format(round(route["per_lap"] - fares)), " > ".join(parts)))
        for deal in route["deals"][:ROUTE_DEALS_SHOWN]:
            lines.append("    %s: buy in %s, sell in %s, +%d each x %s" % (
                deal["good"], name(deal["buy_in"]), name(deal["sell_in"]), deal["each"], _count(deal["count"])))
    lines.append(ROUTE_NOTE)
    return lines

"""A picture of a map summary (see mapgen.summary): terrain cells, towns, ports and the north band.

Standard library only, and no tkinter: the GUI draws the same numbers on a Tk canvas. All geometry is here, so the
SVG and the canvas show one picture:

    cells(summary)                 -> [(x0, y0, x1, y1, colour)]   one rectangle per tile, in the order of the terrain
    town_marks(summary)            -> [(cx, cy, radius, fill, port, label)]
    band_y(summary, north_band)    -> y of the north band's line
    svg(summary, north_band=None)  -> the whole picture as SVG text

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


def town_name(town):
    """The name of a town as the picture and the console report show it. The names of the city states are not
    checked against the game (CLAUDE.md engine fact 16: they come after the lab's own road tiles), so they say so."""
    return town["name"] + " " + NAME_NOT_VERIFIED if town["southern"] else town["name"]


def town_label(town):
    """"Name (size 2, small_farming_village, port, southern)" - the text of a town's tooltip. A city state's name
    is followed by "(name not verified)"."""
    parts = ["size %d" % town["size"], town["script"]]
    parts += [word for word in ("port", "southern", "military") if town[word]]
    return "%s (%s)" % (town_name(town), ", ".join(parts))


def town_marks(summary, scale=1):
    """One (cx, cy, radius, fill, port, label) per town: the circle on the middle of its tile (radius by size, colour
    by town_kind), and whether it gets a port ring."""
    w, h, _ = _checked(summary)
    out = []
    for t in summary["towns"]:
        cx = (t["x"] * CELL_W + CELL_W / 2) * scale
        cy = (_top(t["y"], h) + _lower(t["x"]) + CELL_H / 2) * scale
        radius = TOWN_RADIUS.get(t["size"], max(TOWN_RADIUS.values()))      # (a mod's size 4 is drawn as the biggest)
        out.append((cx, cy, radius * scale, TOWN_FILL[town_kind(t)], bool(t["port"]), town_label(t)))
    return out


def band_y(summary, north_band, scale=1):
    """The y of the north band's lower edge: `north_band` percent of the rows down from the top (0..100)."""
    _w, h, _ = _checked(summary)
    return h * min(max(north_band, 0), 100) / 100.0 * CELL_H * scale


def _num(v):
    v = round(v, 2)
    return str(int(v)) if v == int(v) else repr(v)


def svg(summary, north_band=None, scale=1):
    """The map as SVG text: one <rect> per tile, a circle (class "town") per town, a ring (class "port") round the
    ports, and with `north_band` (percent of the rows from the top) a dashed line (class "north-band")."""
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
    if north_band is not None:
        y = _num(band_y(summary, north_band, scale))
        out.append('<line class="north-band" x1="0" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s" '
                   'stroke-dasharray="%s %s"/>' % (y, _num(width), y, BAND_COLOUR, _num(1.5 * scale),
                                                    _num(8 * scale), _num(5 * scale)))
    marks = town_marks(summary, scale)
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
    key = "circle = %s (white), %s (red), %s (purple); ring = port" % (
        KIND_LABELS["town"].lower(), KIND_LABELS["military"].lower(), KIND_LABELS["southern"].lower())
    if north_band is not None:
        key += "; dashed line = north band (%d%% from the top)" % north_band
    out.append('<text x="%s" y="%s" font-family="sans-serif" font-size="%s" fill="#222222">%s</text>'
               % (_num(4 * scale), _num(height + 12 * scale), _num(10 * scale), escape(key)))
    out.append("</svg>")
    return "\n".join(out)

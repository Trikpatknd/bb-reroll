"""The map picture (bbseed/mapdraw.py) and the terrain encoding of a map summary (mapgen.TERRAIN_CHARS,
mapgen.terrain_string). No game needed: the summaries here are made by hand.

Terrain strings are y-major: the characters of row y = 0 first (the SOUTH edge: high y is north), x = 0.. within
a row. A 4x3 map written as terrain="OOLL" "OLLL" "LLLL" is therefore the rows y = 0, 1, 2 from the south up."""
import ast
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bbseed import mapdraw  # noqa: E402
from bbseed.mapdraw import CELL_H, CELL_W, TERRAIN_COLOURS, cells, svg  # noqa: E402
from bbseed.mapgen import TERRAIN_CHARS, TERRAIN_NAMES  # noqa: E402

SVG_NS = "{http://www.w3.org/2000/svg}"


def town(x, y, port=False, size=2, southern=False, military=False, name=None, script="small_farming_village",
         faction=None):
    return {"name": name or "Town %d/%d" % (x, y), "script": script, "size": size, "x": x, "y": y,
            "southern": southern, "military": military, "port": port, "faction": faction}


def tiny_summary(terrain, towns, size=(4, 3)):
    return {"size": list(size), "layout": "even-q-up", "terrain": terrain, "towns": towns, "attempts": 1}


# ---------------------------------------------------------------- the brief's test
def test_svg_has_one_cell_per_tile_and_marks_ports():
    s = tiny_summary(terrain="OOLL" "OLLL" "LLLL", towns=[town(2, 1, port=True), town(3, 2, port=False)])
    text = svg(s, north_band=33)
    assert text.startswith("<svg") and text.count("<rect") == 12
    assert text.count('class="port"') == 1 and text.count('class="town"') == 2
    assert 'class="north-band"' in text


# ---------------------------------------------------------------- the terrain table
def test_terrain_chars_are_one_distinct_printable_character_per_terrain_value():
    assert len(TERRAIN_CHARS) == len(TERRAIN_NAMES) == 21      # the game's TerrainType.COUNT with Legends' 2 extra
    assert len(set(TERRAIN_CHARS)) == len(TERRAIN_CHARS)
    assert all(c.isascii() and c.isprintable() and c != " " for c in TERRAIN_CHARS)
    assert TERRAIN_NAMES[0] == "Impassable" and TERRAIN_NAMES[1] == "Ocean" and TERRAIN_NAMES[16] == "Shore"
    assert TERRAIN_CHARS[1] == "O" and TERRAIN_CHARS[2] == "L"           # the letters the tiny summaries use


def test_every_terrain_char_has_a_colour():
    assert set(TERRAIN_COLOURS) == set(TERRAIN_CHARS)
    assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in TERRAIN_COLOURS.values())
    assert len(set(TERRAIN_COLOURS.values())) == len(TERRAIN_COLOURS), "two terrains share a colour"


def test_terrain_string_is_y_major_from_y_zero():
    """terrain_string(hexmap): row y = 0 first, x within a row — the order the summary documents."""
    from bbseed.hexmap import HexMap
    from bbseed.mapgen import terrain_string
    hm = HexMap(None, 4, 3, "even-q-up")
    for t in hm.tiles:
        t.Type = 2
    hm.tile(0, 0).Type = 1
    hm.tile(3, 0).Type = 16
    hm.tile(1, 2).Type = 17
    assert terrain_string(hm) == "O" "LL" "C" "LLLL" "LD" "LL"


def test_terrain_string_refuses_a_terrain_type_it_has_no_character_for():
    from bbseed.hexmap import HexMap
    from bbseed.mapgen import MapError, terrain_string
    for bad in (len(TERRAIN_CHARS), -1, 2.5):
        hm = HexMap(None, 2, 2, "even-q-up")
        hm.tile(1, 1).Type = bad
        with pytest.raises(MapError, match="terrain type"):
            terrain_string(hm)


# ---------------------------------------------------------------- the cells
def test_cells_follow_the_terrain_string_with_north_at_the_top():
    s = tiny_summary("OOLL" "OLLL" "LLLL", [])
    c = cells(s)
    assert len(c) == 12
    at = lambda x, y: c[y * 4 + x]               # noqa: E731  (cells come in the order of the terrain string)
    assert all(x1 - x0 == CELL_W and y1 - y0 == CELL_H for x0, y0, x1, y1, _ in c)
    for x in range(4):                           # north = high y = up the picture; no gaps within a column
        for y in range(2):
            assert at(x, y + 1)[3] == at(x, y)[1]
    assert at(2, 2)[1] < at(2, 0)[1]
    for y in range(3):                           # columns side by side
        for x in range(3):
            assert at(x + 1, y)[0] == at(x, y)[2]
    assert [at(x, 0)[4] for x in range(4)] == [TERRAIN_COLOURS[ch] for ch in "OOLL"]


def test_even_columns_sit_half_a_row_lower_than_odd_ones():
    """The measured layout even-q-up: the even columns (0, 2, ...) are half a row further south."""
    c = cells(tiny_summary("LLLL" "LLLL" "LLLL", []))
    at = lambda x, y: c[y * 4 + x]               # noqa: E731
    for y in range(3):
        for x in (0, 2):
            assert at(x, y)[1] - at(x + 1, y)[1] == CELL_H // 2
    assert CELL_H % 2 == 0, "half a row must be a whole pixel"


def test_cells_cover_the_picture_without_overlap():
    c = cells(tiny_summary("LLLLL" "LLLLL" "LLLLL" "LLLLL", [], size=(5, 4)))
    boxes = {(x0, y0, x1, y1) for x0, y0, x1, y1, _ in c}
    assert len(boxes) == 20
    for a in boxes:
        for b in boxes:
            if a != b:
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (a, b)


def test_cells_scale():
    s = tiny_summary("OOLL" "OLLL" "LLLL", [])
    base, big = cells(s), cells(s, scale=2)
    assert [tuple(2 * v for v in b[:4]) + b[4:] for b in base] == big


def test_a_summary_with_a_wrong_terrain_string_is_refused():
    with pytest.raises(ValueError, match="terrain"):
        cells(tiny_summary("OOLL" "OLLL", [], size=(4, 3)))
    with pytest.raises(ValueError, match="terrain"):
        cells(tiny_summary("OOLL" "OLL?" "LLLL", []))


# ---------------------------------------------------------------- the SVG
def _parse(text):
    return ET.fromstring(text)


def _circles(root, cls):
    return [e for e in root.iter(SVG_NS + "circle") if e.get("class") == cls]


def test_svg_is_well_formed_and_sized_to_the_cells():
    s = tiny_summary("OOLL" "OLLL" "LLLL", [town(2, 1, port=True)])
    root = _parse(svg(s))
    c = cells(s)
    width = max(x1 for _, _, x1, _, _ in c)
    height = max(y1 for _, _, _, y1, _ in c)
    x, y, w, h = (float(v) for v in root.get("viewBox").split())
    assert (x, y, w) == (0, 0, width) and h >= height            # (a legend strip below may add height)
    assert len(list(root.iter(SVG_NS + "rect"))) == 12


def test_towns_are_circles_on_the_centre_of_their_tile_with_north_up():
    s = tiny_summary("LLLL" "LLLL" "LLLL", [town(1, 0, name="South"), town(2, 2, name="North")])
    c = cells(s)
    centre = lambda x, y: ((c[y * 4 + x][0] + c[y * 4 + x][2]) / 2, (c[y * 4 + x][1] + c[y * 4 + x][3]) / 2)  # noqa: E731
    circles = {e.find(SVG_NS + "title").text.split(" (")[0]: e for e in _circles(_parse(svg(s)), "town")}
    assert (float(circles["South"].get("cx")), float(circles["South"].get("cy"))) == centre(1, 0)
    assert (float(circles["North"].get("cx")), float(circles["North"].get("cy"))) == centre(2, 2)
    assert float(circles["North"].get("cy")) < float(circles["South"].get("cy"))


def test_a_bigger_town_is_a_bigger_circle():
    s = tiny_summary("LLLL" "LLLL" "LLLL", [town(0, 0, size=1, name="S"), town(1, 1, size=2, name="M"),
                                            town(2, 2, size=3, name="L")])
    radius = {e.find(SVG_NS + "title").text.split(" (")[0]: float(e.get("r")) for e in _circles(_parse(svg(s)), "town")}
    assert 0 < radius["S"] < radius["M"] < radius["L"]


def test_a_port_has_a_ring_round_its_town():
    s = tiny_summary("OOLL" "OLLL" "LLLL", [town(2, 1, port=True, name="Harbour"), town(3, 2, name="Inland")])
    root = _parse(svg(s))
    ring, = _circles(root, "port")
    harbour, = [e for e in _circles(root, "town") if e.find(SVG_NS + "title").text.startswith("Harbour")]
    assert (ring.get("cx"), ring.get("cy")) == (harbour.get("cx"), harbour.get("cy"))
    assert float(ring.get("r")) > float(harbour.get("r"))
    assert ring.get("fill") == "none"


def test_the_north_band_is_a_dashed_line_that_many_percent_of_the_rows_down_from_the_top():
    s = tiny_summary("LLLL" "LLLL" "LLLL" "LLLL", [], size=(4, 4))
    line, = [e for e in _parse(svg(s, north_band=50)).iter(SVG_NS + "line") if e.get("class") == "north-band"]
    assert line.get("stroke-dasharray")
    assert float(line.get("y1")) == float(line.get("y2")) == 2 * CELL_H      # half of 4 rows
    assert float(line.get("x1")) == 0 and float(line.get("x2")) == 4 * CELL_W
    assert 'class="north-band"' not in svg(s) and 'class="north-band"' not in svg(s, north_band=None)


def test_text_in_the_svg_is_escaped():
    s = tiny_summary("LLLL" "LLLL" "LLLL", [town(1, 1, name='A & B <"x">')])
    root = _parse(svg(s))                                    # would raise on bad XML
    assert 'A & B <"x">' in [e.find(SVG_NS + "title").text for e in _circles(root, "town")][0]


def test_a_city_states_name_is_marked_unverified_in_the_tooltip_and_the_svg():
    """Final review M4 / Ruling AO: the names of the city states come after the lab's own road tiles and are not
    checked against the game; the picture says so. Every other name is verified and has no mark."""
    s = tiny_summary("LLLL" "LLLL" "LLLL", [town(1, 1, name="City State of Tiber", southern=True, script="city_state",
                                                size=3, port=True), town(2, 2, name="Hafen")])
    labels = {label.split(" (")[0]: label for *_rest, label in mapdraw.town_marks(s)}
    assert labels["City State of Tiber"] == "City State of Tiber (name not verified) (size 3, city_state, port, southern)"
    assert labels["Hafen"] == "Hafen (size 2, small_farming_village)"
    titles = [e.find(SVG_NS + "title").text for e in _circles(_parse(svg(s)), "town")]
    assert titles == list(labels.values())
    assert mapdraw.town_name(town(0, 0, name="Burg", southern=True)) == "Burg (name not verified)"
    assert mapdraw.town_name(town(0, 0, name="Burg", military=True)) == "Burg"


def test_the_svg_key_and_the_gui_legend_use_the_words_of_the_map_view_fields():
    """Final review M8: the white circle is a village, town or city (the field "Towns" is size 2 only) and the forts
    are "Strongholds" in the field. The GUI's legend reads mapdraw.KIND_LABELS, so both say the same."""
    assert mapdraw.KIND_LABELS == {"town": "Village, town or city", "military": "Stronghold", "southern": "City state"}
    text = svg(tiny_summary("LLLL" "LLLL" "LLLL", []))
    assert "circle = village, town or city (white), stronghold (red), city state (purple); ring = port" in text
    assert "fort" not in text


def test_the_svg_of_an_empty_map_has_only_cells():
    text = svg(tiny_summary("OOLL" "OLLL" "LLLL", []))
    assert text.count('class="town"') == text.count('class="port"') == 0 and text.count("<rect") == 12


def test_svg_scale():
    s = tiny_summary("OOLL" "OLLL" "LLLL", [town(2, 1, port=True)])
    one, two = _parse(svg(s)), _parse(svg(s, scale=2))
    assert float(two.get("viewBox").split()[2]) == 2 * float(one.get("viewBox").split()[2])
    assert float(_circles(two, "town")[0].get("cx")) == 2 * float(_circles(one, "town")[0].get("cx"))


# ---------------------------------------------------------------- the command line (--map SEED [--svg PATH])
def _sample():
    return tiny_summary("OOLL" "OLLL" "LLLL", [
        town(2, 1, port=True, name="Hafen", script="small_fishing_village", size=1),
        town(3, 2, name="Zürich", southern=True, script="city_state", size=3),
        town(1, 1, military=True, port=True, southern=True, size=2, name="Burg")])


def test_map_report_lists_towns_and_counts_ports_in_ascii():
    from bbseed.search import map_report
    lines = map_report("1234567890", _sample(), origin="trader_scenario", profile="legends", seconds=36.6)
    text = "\n".join(lines)
    text.encode("ascii")                                         # the console here is cp1252
    assert lines[0] == ("map of seed 1234567890, origin trader_scenario, profile legends, layout even-q-up, "
                        "1 attempt, 37 s")
    assert "4 x 3 tiles, 3 towns" in text
    row = [l for l in lines if "Hafen" in l][0].split()
    assert row == ["Hafen", "small_fishing_village", "1", "yes", "no", "no"]
    # the city states' names are not verified (Ruling S, README Limits): the report says so, in ASCII
    assert [l for l in lines if "Burg" in l][0].split() == ["Burg", "(name", "not", "verified)", "small_farming_village",
                                                            "2", "yes", "yes", "yes"]
    assert "Z?rich (name not verified)" in text
    assert text.count("(name not verified)") == 2 and "Hafen (name" not in text
    assert "ports: 2 (southern 1, other 1)" in lines
    assert "towns: 2 southern, 1 military, size 1/2/3: 1/1/1" in lines


def test_map_option_runs_a_map_and_writes_the_picture(monkeypatch, tmp_path, capsys):
    import bbseed.lab
    import bbseed.search as search
    calls = []

    class FakeLab:
        profile = "legends"

        def __init__(self, profile=None, mod_settings=None):
            calls.append(("lab", profile, mod_settings))

        def info(self):
            return {"game_version": "1.5.2.3", "legends_version": "19.4.22", "mods": []}

        def world_map(self, seed, origin="trader_scenario", stop_at="reseed", layout=None):
            calls.append(("map", seed, origin))
            return {"map": _sample(), "seconds": 1.0, "log": [], "stub_uses": {}}

    monkeypatch.setattr(bbseed.lab, "Lab", FakeLab)
    monkeypatch.setattr(bbseed.lab, "big_stack", lambda fn: fn())
    path = tmp_path / "m.svg"
    search.main(["--profile", "legends", "--map", "1234567890", "--svg", str(path),
                 "--mod-setting", "mod_legends:LandRatio=55"])
    assert calls == [("lab", "legends", {"mod_legends:LandRatio": 55}), ("map", "1234567890", "trader_scenario")]
    assert path.read_text(encoding="utf-8") == svg(_sample())
    out = capsys.readouterr().out
    assert "ports: 2" in out and "picture written to %s" % path in out
    assert "not verified" not in out.replace("(name not verified)", ""), "game 1.5.2.3 + Legends 19.4.22: no note"
    calls.clear()
    search.main(["--map", "42", "--origin", "legends_noble_scenario"])
    assert calls == [("lab", None, {}), ("map", "42", "legends_noble_scenario")]


def cli_map_lab(monkeypatch, info, stub_uses=None):
    """--map SEED on a stand-in lab with this info and these stub uses; returns what the lab saw."""
    import bbseed.lab
    seen = []

    class StandIn:
        profile = "legends"

        def __init__(self, profile=None, mod_settings=None):
            pass

        def info(self):
            return info

        def world_map(self, seed, origin="trader_scenario", stop_at="reseed", layout=None):
            seen.append(seed)
            return {"map": _sample(), "seconds": 1.0, "log": [], "stub_uses": stub_uses or {}}

    monkeypatch.setattr(bbseed.lab, "Lab", StandIn)
    monkeypatch.setattr(bbseed.lab, "big_stack", lambda fn: fn())
    return seen


VERIFIED_INFO = {"game_version": "1.5.2.3", "legends_version": "19.4.22",
                 "mods": [{"file": "mod_legends-19.4.22.zip", "id": "mod_legends", "name": "Legends Mod",
                           "version": "19.4.22"},
                          {"file": "mod_msu 479 1.9.0 2026-06-23T04-27Z eVJjKbX9c.zip", "id": "mod_msu",
                           "name": "MSU", "version": "1.9.0"}]}


def test_map_option_notes_a_setup_whose_maps_are_not_verified(monkeypatch, capsys):
    """Final review M10: --map builds a map on any setup; the console says when nobody checked it."""
    import bbseed.search as search
    note = "Map results are not verified for this setup."
    for info in (dict(VERIFIED_INFO, game_version="1.5.3.0"),
                 dict(VERIFIED_INFO, legends_version=None, mods=[], dlc_complete=False),
                 dict(VERIFIED_INFO, mods=VERIFIED_INFO["mods"] + [{"file": "mod_jimmys_tooltips-1.0.5.zip"}])):
        cli_map_lab(monkeypatch, info)
        search.main(["--map", "42"])
        out = capsys.readouterr().out
        assert out.startswith(note + "\n") and out.count(note) == 1
    assert note.isascii()
    cli_map_lab(monkeypatch, VERIFIED_INFO)
    search.main(["--map", "42"])
    assert note not in capsys.readouterr().out


def test_map_option_refuses_a_map_that_used_engine_functions_nobody_reviewed(monkeypatch, capsys):
    """Final review I1: a counted stand-in that HARMLESS_STUBS does not explain may mean a wrong map: no map is
    printed, the error names the seed and the functions."""
    import bbseed.search as search
    from bbseed.lab import LabError
    harmless = {("sprite", "varyColor"): 3}
    seen = cli_map_lab(monkeypatch, VERIFIED_INFO,
                       {**harmless, ("World", "spawnEntity"): 2, ("entity", "getFoo"): 1})
    with pytest.raises(LabError, match=r"map of seed '42' uses engine functions that BB Reroll does not model: "
                                       r"World\.spawnEntity, entity\.getFoo$"):
        search.main(["--map", "42"])
    assert seen == ["42"] and "ports:" not in capsys.readouterr().out
    cli_map_lab(monkeypatch, VERIFIED_INFO, harmless)
    search.main(["--map", "42"])
    assert "ports: 2" in capsys.readouterr().out


def test_svg_option_needs_map(capsys):
    from bbseed import search
    with pytest.raises(SystemExit):
        search.main(["--svg", "x.svg", "--origin", "trader_scenario"])
    assert "--svg goes with --map" in capsys.readouterr().err


# ---------------------------------------------------------------- rules of the module
def test_mapdraw_is_standard_library_only_and_never_imports_tkinter():
    tree = ast.parse(Path(mapdraw.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
            [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
        for name in names:
            assert name.split(".")[0] in sys.stdlib_module_names and not name.startswith("tkinter"), name
    out = subprocess.run([sys.executable, "-c", "import sys, bbseed.mapdraw; sys.exit('tkinter' in sys.modules)"],
                         cwd=str(ROOT), capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert out.returncode == 0, out.stderr

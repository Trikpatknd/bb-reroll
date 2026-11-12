"""The map as a picture: Pillow draws mapdraw's geometry, so it shows what the Show map window shows."""
import ctypes
import sys

import pytest
from PIL import Image, ImageColor

from bbreroll import map_picture
from bbseed import mapdraw


def rgb(colour):
    return ImageColor.getrgb(colour)


def small_map(w=30, h=40, **extra):
    """Land in the south, sea in the north, a southern port, a northern port and a fort."""
    def town(x, y, **kw):
        base = {"name": "Town %d/%d" % (x, y), "script": "small_farming_village", "size": 2, "x": x, "y": y,
                "southern": False, "military": False, "port": False, "faction": None}
        return dict(base, **kw)
    return dict({"size": [w, h], "layout": "even-q-up", "attempts": 1,
                 "terrain": "L" * (w * (h // 2)) + "O" * (w * (h - h // 2)),
                 "towns": [town(3, 2, port=True, southern=True, size=3, script="city_state"), town(20, h - 3, port=True),
                           town(10, 20, military=True, script="legends_fort")]}, **extra)


def with_road(summary):
    """One road tile in the land, going north (bit 1 = "1"), away from the towns."""
    w, h = summary["size"]
    roads = ["."] * (w * h)
    roads[5 * w + 25] = "1"
    return dict(summary, roads="".join(roads))


@pytest.mark.core
def test_each_town_is_drawn_at_its_mark_in_its_colour():
    summary = small_map()
    image = map_picture.render(summary, verified=True)
    assert image.mode == "RGB"
    marks = mapdraw.town_marks(summary, 2, True)
    assert len(marks) == 3
    for cx, cy, _r, fill, _port, _label in marks:
        assert image.getpixel((int(cx), int(cy))) == rgb(fill)


@pytest.mark.core
def test_the_terrain_colour_is_where_the_svg_puts_it():
    summary = small_map()
    summary["terrain"] = summary["terrain"][:-1] + "N"
    image = map_picture.render(summary, verified=False, scale=3)
    assert image.size == mapdraw.picture_size(summary, 3)
    out = mapdraw.cells(summary, 3)
    for i in (0, 29, 30, 31, 600, len(out) - 1):       # both kinds of column, land, sea, the one snow tile
        x0, y0, x1, y1, colour = out[i]
        assert image.getpixel(((x0 + x1) // 2, (y0 + y1) // 2)) == rgb(colour), i
    assert out[-1][4] == mapdraw.TERRAIN_COLOURS["N"]


@pytest.mark.core
def test_roads_and_star_only_on_a_verified_setup():
    summary = with_road(small_map(start=[12, 8]))
    (x0, y0, x1, y1), = mapdraw.road_segments(summary, True, 2)
    road = (int((x0 + x1) / 2), int((y0 + y1) / 2))
    star = mapdraw.start_mark(summary, True, 2)
    centre = (int(star[0]), int(star[1]))
    yes = map_picture.render(summary, verified=True)
    no = map_picture.render(summary, verified=False)
    assert yes.getpixel(road) == rgb(mapdraw.ROAD_COLOUR) and yes.getpixel(centre) == rgb(mapdraw.START_FILL)
    land = rgb(mapdraw.TERRAIN_COLOURS["L"])
    assert no.getpixel(road) == land and no.getpixel(centre) == land


@pytest.mark.core
def test_the_band_line_is_where_mapdraw_puts_it():
    summary = small_map()
    y = int(mapdraw.band_y(summary, 33, 2))
    line = map_picture.render(summary, verified=True, north_band=33)
    plain = map_picture.render(summary, verified=True)
    assert line.getpixel((2, y)) == rgb(mapdraw.BAND_COLOUR)
    assert plain.getpixel((2, y)) != rgb(mapdraw.BAND_COLOUR)


@pytest.mark.edge
def test_a_summary_without_roads_still_draws():
    summary = small_map()
    assert "roads" not in summary
    assert map_picture.render(summary, verified=True).size == mapdraw.picture_size(summary, 2)


@pytest.mark.core
def test_the_footer_adds_height_and_the_seed_text_fits():
    summary = small_map(w=30)
    plain = map_picture.render(summary, verified=True)
    text = map_picture.footer_text("1234567890", "A very long origin name from another mod, longer than the map is wide")
    assert "1234567890" in text
    image = map_picture.render(summary, verified=True, footer=text)
    width, height = plain.size
    assert image.width == width and image.height > height
    assert image.crop((0, 0, width, height)).tobytes() == plain.tobytes(), "the footer leaves the map as it was"
    strip = image.crop((0, height, width, image.height))
    colours = strip.getcolors(maxcolors=100000)
    assert len(colours) > 1, "the footer has text"
    right = strip.crop((width - 2, 0, width, strip.height))
    assert len(right.getcolors(maxcolors=100000)) == 1, "the text ends inside the picture"


@pytest.mark.dirty
def test_a_damaged_summary_raises_valueerror():
    summary = small_map()
    with pytest.raises(ValueError):
        map_picture.render(dict(summary, terrain=summary["terrain"][:-1]), verified=True)
    with pytest.raises(ValueError):
        map_picture.render(dict(summary, terrain="?" * len(summary["terrain"])), verified=True)


@pytest.mark.core
def test_a_saved_picture_can_be_read_back(tmp_path):
    image = map_picture.render(small_map(), verified=True)
    path = tmp_path / "map.png"
    assert map_picture.save_png(image, path) is None
    with Image.open(path) as back:
        assert back.format == "PNG" and back.size == image.size
    assert [p.name for p in tmp_path.iterdir()] == ["map.png"]


@pytest.mark.dirty
def test_a_folder_that_refuses_writes_leaves_no_file(tmp_path, monkeypatch):
    image = map_picture.render(small_map(), verified=True)
    path = tmp_path / "map.png"

    def refuse(*_a, **_k):
        raise PermissionError("the folder refuses writes")
    monkeypatch.setattr(map_picture.os, "replace", refuse)
    message = map_picture.save_png(image, path)
    assert message and "Cannot save" in message and "refuses writes" in message
    assert list(tmp_path.iterdir()) == [], "no half-written picture stays"
    monkeypatch.undo()

    def half_a_file(fp, *_a, **_k):
        fp.write(b"half")
        raise OSError("the disk is full")
    monkeypatch.setattr(Image.Image, "save", lambda self, fp, *a, **k: half_a_file(fp))
    assert "disk is full" in map_picture.save_png(image, path)
    assert list(tmp_path.iterdir()) == []
    monkeypatch.undo()
    assert "Cannot save" in map_picture.save_png(image, tmp_path / "no such folder" / "map.png")


@pytest.mark.dirty
def test_a_picture_kept_from_before_stays_when_a_save_fails(tmp_path, monkeypatch):
    image = map_picture.render(small_map(), verified=True)
    path = tmp_path / "map.png"
    path.write_bytes(b"the old picture")
    monkeypatch.setattr(map_picture.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("no")))
    assert map_picture.save_png(image, path)
    assert path.read_bytes() == b"the old picture"


windows = pytest.mark.skipif(sys.platform != "win32", reason="the Windows clipboard")


@windows
@pytest.mark.core
@pytest.mark.xdist_group("gui")     # one clipboard: not at the same time as the window's tests that copy text
def test_the_clipboard_holds_the_picture():
    image = map_picture.render(small_map(), verified=True, footer="Seed 1")
    assert map_picture.copy_to_clipboard(image) is None
    assert map_picture.clipboard_picture_size() == image.size


@windows
@pytest.mark.dirty
def test_a_locked_clipboard_gives_a_message_not_a_crash(monkeypatch):
    image = map_picture.render(small_map(), verified=True)
    monkeypatch.setattr(map_picture, "_USER32", _Locked())
    monkeypatch.setattr(map_picture, "CLIPBOARD_TRIES", 2)
    message = map_picture.copy_to_clipboard(image)
    assert message and "Cannot copy" in message and "clipboard" in message
    assert message.isascii()


class _Locked:
    """user32 with the clipboard held by another program."""

    @staticmethod
    def OpenClipboard(_owner):
        ctypes.set_last_error(5)
        return 0


@windows
@pytest.mark.dirty
def test_a_clipboard_that_refuses_the_data_frees_it_and_closes(monkeypatch):
    image = map_picture.render(small_map(), verified=True)
    closed, freed = [], []

    class Refuses:
        OpenClipboard = staticmethod(lambda _owner: 1)
        EmptyClipboard = staticmethod(lambda: 1)
        SetClipboardData = staticmethod(lambda _format, _handle: None)
        CloseClipboard = staticmethod(lambda: closed.append(1) or 1)
    real_free = map_picture._KERNEL32.GlobalFree

    class Kernel:
        GlobalAlloc = staticmethod(map_picture._KERNEL32.GlobalAlloc)
        GlobalLock = staticmethod(map_picture._KERNEL32.GlobalLock)
        GlobalUnlock = staticmethod(map_picture._KERNEL32.GlobalUnlock)
        GlobalFree = staticmethod(lambda handle: freed.append(handle) or real_free(handle))
    monkeypatch.setattr(map_picture, "_USER32", Refuses())
    monkeypatch.setattr(map_picture, "_KERNEL32", Kernel())
    assert "Cannot copy" in map_picture.copy_to_clipboard(image)
    assert closed == [1] and len(freed) == 1


# ---------------------------------------------------------------- trade routes
def route_map():
    summary = with_road(small_map())
    summary["trade"] = {}
    route = {"towns": [2, 1], "ships": [False, False], "paths": [[(10, 20), (11, 20), (12, 21)], [(12, 21), (10, 20)]],
             "lap_days": 2.0, "fares": 0, "per_lap": 900.0, "per_day": 300.0,
             "deals": [{"good": "Silk", "buy_in": 2, "sell_in": 1, "each": 150, "count": 2.0}]}
    return summary, route


@pytest.mark.core
def test_render_without_trade_is_unchanged():
    summary, _route = route_map()
    plain = map_picture.render(summary, verified=True, footer="Seed 1. Trader.")
    assert map_picture.render(summary, verified=True, footer="Seed 1. Trader.", routes=None).tobytes() == plain.tobytes()
    del summary["trade"]
    assert map_picture.render(summary, verified=True, footer="Seed 1. Trader.").tobytes() == plain.tobytes()


@pytest.mark.core
def test_render_with_routes_grows_footer():
    summary, route = route_map()
    plain = map_picture.render(summary, verified=True, footer="Seed 1. Trader.")
    image = map_picture.render(summary, verified=True, footer="Seed 1. Trader.", routes=[route, dict(route), dict(route)])
    assert image.width == plain.width and image.height > plain.height
    colours = {c for _n, c in image.getcolors(1 << 20)}
    assert rgb(mapdraw.ROUTE_COLOURS[0]) in colours
    width, height = mapdraw.picture_size(summary, 2)
    line = mapdraw.route_lines(summary, [route], True, 2)[0]
    (x0, y0), (x1, y1) = line["polylines"][0][1], line["polylines"][0][2]      # (the first step is under the fort)
    one = map_picture.render(summary, verified=True, footer="Seed 1. Trader.", routes=[route])
    assert one.getpixel((round((x0 + x1) / 2), round((y0 + y1) / 2))) == rgb(mapdraw.ROUTE_COLOURS[0])
    assert one.height < image.height                # fewer legend lines
    # the towns are drawn above the routes
    cx, cy, _r, fill, _port, _label = mapdraw.town_marks(summary, 2, True)[2]
    assert image.getpixel((int(cx), int(cy))) == rgb(fill)
    # no routes at all: the line that says so, under the map
    none = map_picture.render(summary, verified=True, footer="Seed 1. Trader.", routes=[])
    assert none.height > plain.height and none.crop((0, 0, width, height)).tobytes() == \
        plain.crop((0, 0, width, height)).tobytes()


@pytest.mark.edge
def test_render_with_routes_on_an_unverified_setup_draws_none():
    summary, route = route_map()
    plain = map_picture.render(summary, verified=False)
    image = map_picture.render(summary, verified=False, routes=[route])
    width, height = mapdraw.picture_size(summary, 2)
    assert image.crop((0, 0, width, height)).tobytes() == plain.crop((0, 0, width, height)).tobytes()
    assert image.height > plain.height              # the line that says why

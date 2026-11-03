"""The map of a result as a picture, to copy or to save: Pillow draws bbseed/mapdraw's geometry, so it shows what the Show
map window and the SVG show, layer for layer. No tkinter: the window only calls this.

    render(summary, verified=, north_band=, footer=, scale=)   -> an RGB image
    footer_text(seed, origin)      -> the line that says which seed the picture is of, when it is shared alone
    copy_to_clipboard(image)       -> None when done, else the text that says why not
    save_png(image, path)          -> None when done, else the text that says why not; never leaves half a file
    clipboard_picture_size()       -> (width, height) of the picture on the clipboard, or None (for tests, the self-test)
"""
import ctypes
import io
import os
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from bbreroll.map_conditions import map_line
from bbreroll.map_view import DEFAULT_NORTH_BAND
from bbseed import mapdraw

BACKGROUND = "#f4f1ea"      # the corners the columns' half-row offset leaves, and the footer
FOOTER_TEXT = "#222222"
FOOTER_PAD = 6              # pixels at scale 1
FOOTER_FONT = 11            # font size at scale 1, the most it can be; a long line takes a smaller one
FOOTER_FONT_LEAST = 8
TOWN_OUTLINE = "#111111"

CF_DIB = 8
GMEM_MOVEABLE = 0x0002
CLIPBOARD_TRIES = 10        # another program often holds the clipboard for a moment
CLIPBOARD_WAIT = 0.05       # seconds between two tries
NO_CLIPBOARD = "Cannot copy the map picture. Another program uses the clipboard. Try again."
COPY_FAILED = "Cannot copy the map picture. Windows did not accept it on the clipboard."
ONLY_WINDOWS = "Cannot copy the map picture. This works only on Windows. Save the picture."


def footer_text(seed, origin):
    return "Seed %s. %s. North is at the top." % (seed, origin)


def _footer_layout(lines, width, scale):
    """(font, size, lines): the biggest font in which every line fits `width`. When none does, the smallest one, and a
    line too long for it goes on over the next lines (word by word): the seed must stay readable."""
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for size in range(FOOTER_FONT * scale, FOOTER_FONT_LEAST * scale - 1, -1):
        font = ImageFont.load_default(size=size)
        if all(measure.textlength(line, font=font) <= width for line in lines):
            return font, size, lines
    wrapped = []
    for line in lines:
        current = ""
        for word in line.split():
            joined = (current + " " + word).strip()
            if current and measure.textlength(joined, font=font) > width:
                wrapped.append(current)
                current = word
            else:
                current = joined
        wrapped.append(current)
    return font, size, wrapped


def render(summary, *, verified, north_band=None, footer="", scale=2):
    """The picture, north at the top: terrain, roads, north band, towns, ports, star (the Tk canvas's order). No text on
    the map. With a `footer`: a strip under the map with the map line and the footer's text.
    `verified`: the setup's maps are checked against the game (mapdraw: roads and start only then). `scale` is a whole
    number. ValueError for a damaged summary (mapdraw._checked's rule)."""
    width, height = mapdraw.picture_size(summary, scale)
    font, size, lines, strip = None, 0, [], 0
    if footer:
        pad = FOOTER_PAD * scale
        lines = [map_line(summary, DEFAULT_NORTH_BAND if north_band is None else north_band), footer]
        font, size, lines = _footer_layout(lines, width - 2 * pad, scale)
        strip = len(lines) * round(size * 1.3) + 2 * pad
    image = Image.new("RGB", (width, height + strip), BACKGROUND)
    draw = ImageDraw.Draw(image)
    for x0, y0, x1, y1, colour in mapdraw.cells(summary, scale):
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=colour)          # (Pillow's corners are inside the rectangle)
    for segment in mapdraw.road_segments(summary, verified, scale):
        draw.line(segment, fill=mapdraw.ROAD_COLOUR, width=max(1, round(mapdraw.ROAD_WIDTH * scale)))
    if north_band is not None:
        _dashed_line(draw, mapdraw.band_y(summary, north_band, scale), width, scale)
    marks = mapdraw.town_marks(summary, scale, verified)
    for cx, cy, r, fill, _port, _label in marks:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=TOWN_OUTLINE, width=max(1, round(scale)))
    for cx, cy, r, _fill, port, _label in marks:
        if port:
            ring = r + 2.5 * scale
            draw.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=mapdraw.PORT_RING,
                         width=max(1, round(1.5 * scale)))
    start = mapdraw.start_mark(summary, verified, scale)
    if start is not None:
        cx, cy, r, fill, _label = start
        draw.polygon(mapdraw.star_points(cx, cy, r), fill=fill, outline=mapdraw.START_OUTLINE, width=max(1, round(scale)))
    y = height + FOOTER_PAD * scale
    for line in lines:
        draw.text((FOOTER_PAD * scale, y), line, fill=FOOTER_TEXT, font=font)
        y += round(size * 1.3)
    return image


def _dashed_line(draw, y, width, scale):
    dash, gap = max(2, round(8 * scale)), max(2, round(5 * scale))
    for x in range(0, width, dash + gap):
        draw.line((x, y, min(x + dash, width), y), fill=mapdraw.BAND_COLOUR, width=max(1, round(1.5 * scale)))


# ---------------------------------------------------------------------- saving
def save_png(image, path):
    """Writes a temporary file beside `path`, then replaces `path` with it: a save that fails leaves no half-written
    picture, and a picture that was there stays."""
    path = Path(path)
    temp = None
    try:
        handle, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        with os.fdopen(handle, "wb") as out:
            image.save(out, "PNG")
        os.replace(temp, path)
        return None
    except (OSError, ValueError) as e:
        if temp is not None:
            try:
                os.unlink(temp)
            except OSError:
                pass
        return "Cannot save the map picture: %s" % e


# ---------------------------------------------------------------------- the clipboard (Windows)
def _windows_api():
    """user32 and kernel32 with the types of 64-bit handles (ctypes would cut a handle to 32 bits). Instances of their
    own: the types set here reach no other code in this process."""
    from ctypes import wintypes as w
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for function, argtypes, restype in (
            (user32.OpenClipboard, (w.HWND,), w.BOOL),
            (user32.CloseClipboard, (), w.BOOL),
            (user32.EmptyClipboard, (), w.BOOL),
            (user32.SetClipboardData, (w.UINT, w.HANDLE), w.HANDLE),
            (user32.GetClipboardData, (w.UINT,), w.HANDLE),
            (kernel32.GlobalAlloc, (w.UINT, ctypes.c_size_t), w.HGLOBAL),
            (kernel32.GlobalLock, (w.HGLOBAL,), w.LPVOID),
            (kernel32.GlobalUnlock, (w.HGLOBAL,), w.BOOL),
            (kernel32.GlobalFree, (w.HGLOBAL,), w.HGLOBAL)):
        function.argtypes, function.restype = argtypes, restype
    return user32, kernel32


_USER32, _KERNEL32 = _windows_api() if sys.platform == "win32" else (None, None)


def _open_clipboard():
    for attempt in range(CLIPBOARD_TRIES):
        if attempt:
            time.sleep(CLIPBOARD_WAIT)
        if _USER32.OpenClipboard(None):
            return True
    return False


def _dib(image):
    """The picture as a device-independent bitmap: a BMP file without its 14-byte file header."""
    data = io.BytesIO()
    image.convert("RGB").save(data, "BMP")
    return data.getvalue()[14:]


def copy_to_clipboard(image):
    if _USER32 is None:
        return ONLY_WINDOWS
    data = _dib(image)
    handle = _KERNEL32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        return COPY_FAILED
    memory = _KERNEL32.GlobalLock(handle)
    if not memory:
        _KERNEL32.GlobalFree(handle)
        return COPY_FAILED
    ctypes.memmove(memory, data, len(data))
    _KERNEL32.GlobalUnlock(handle)
    if not _open_clipboard():
        _KERNEL32.GlobalFree(handle)
        return NO_CLIPBOARD
    try:
        _USER32.EmptyClipboard()
        if _USER32.SetClipboardData(CF_DIB, handle):
            return None                 # the clipboard owns the memory now
        _KERNEL32.GlobalFree(handle)
        return COPY_FAILED
    finally:
        _USER32.CloseClipboard()


def clipboard_picture_size():
    """(width, height) of the bitmap on the clipboard, or None when it holds no bitmap or is held by another program."""
    if _USER32 is None or not _open_clipboard():
        return None
    try:
        handle = _USER32.GetClipboardData(CF_DIB)
        if not handle:
            return None
        memory = _KERNEL32.GlobalLock(handle)
        if not memory:
            return None
        try:
            head = ctypes.string_at(memory, 12)             # BITMAPINFOHEADER: size, width, height (bottom-up: positive)
        finally:
            _KERNEL32.GlobalUnlock(handle)
        return int.from_bytes(head[4:8], "little", signed=True), abs(int.from_bytes(head[8:12], "little", signed=True))
    finally:
        _USER32.CloseClipboard()

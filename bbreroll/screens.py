"""The monitors of this computer: the main window starts on one of them (start_geometry), and the windows of tests and
self-tests open on the second monitor, when there is one, and not over the work on the main one. No tkinter."""
import ctypes
import re
from ctypes import wintypes

MARGIN = 40         # from the corner of the monitor
TITLE_BAR = 40      # the title bar and frame Windows adds above and around the size Tk is given


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def monitors():
    """Each monitor as {"left", "top", "right", "bottom", "work", "primary", "scale"}, in the pixels of this process ("work":
    (left, top, right, bottom) without the taskbar). [] when they cannot be read."""
    found = []
    try:        # own instances: the 64-bit types set here must not reach other users of ctypes.windll
        user32, shcore = ctypes.WinDLL("user32"), ctypes.WinDLL("shcore")
        callback = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        user32.EnumDisplayMonitors.argtypes = (wintypes.HDC, ctypes.POINTER(wintypes.RECT), callback, wintypes.LPARAM)
        user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo))
        shcore.GetDpiForMonitor.argtypes = (wintypes.HMONITOR, ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint))

        def one(handle, _dc, _rect, _data):
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(_MonitorInfo)
            dpi_x, dpi_y = ctypes.c_uint(96), ctypes.c_uint(96)
            user32.GetMonitorInfoW(handle, ctypes.byref(info))
            shcore.GetDpiForMonitor(handle, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
            area, work = info.rcMonitor, info.rcWork
            found.append({"left": area.left, "top": area.top, "right": area.right, "bottom": area.bottom,
                          "work": (work.left, work.top, work.right, work.bottom),
                          "primary": bool(info.dwFlags & 1), "scale": dpi_x.value / 96})
            return 1
        user32.EnumDisplayMonitors(None, None, callback(one), 0)
    except (AttributeError, OSError):       # (only the place of a test window depends on it)
        return []
    return found


def window_position(found=None):
    """The place of a test window, as Tk's geometry text: on the first monitor that is not the main one, else near the corner
    of the main one. Not above row 0 when the monitor goes there: the map window does not go above it."""
    found = monitors() if found is None else found
    other = next((m for m in found if not m["primary"]), None)
    if other is None:
        return "+%d+%d" % (MARGIN, MARGIN)
    top = max(other["top"], 0) if other["bottom"] > 0 else other["top"]
    return "+%d+%d" % (other["left"] + MARGIN, top + MARGIN)


def start_geometry(saved, size, found=None):
    """The main window's start place as Tk's geometry text "WxH+X+Y", all of it on one monitor's work area. saved: the
    geometry the settings kept ("1000x960+200+500"; None or another form: not used); size: (width, height) without it. The
    monitor is the one under the middle of the title bar, else the main one; a window that does not fit moves onto it, and
    shrinks to it when it is larger. With no saved place it is centred on the main monitor. No monitor found: saved as it is,
    else the size alone (Windows places it)."""
    found = monitors() if found is None else found
    parsed = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", saved or "")
    width, height, x, y = map(int, parsed.groups()) if parsed else (size[0], size[1], None, None)
    if not found:
        return saved if parsed else "%dx%d" % (width, height)
    main = next((m for m in found if m["primary"]), found[0])
    screen = main
    if x is not None:
        screen = next((m for m in found if m["left"] <= x + width // 2 < m["right"] and m["top"] <= y + TITLE_BAR // 2 < m["bottom"]),
                      main)
    left, top, right, bottom = screen.get("work") or (screen["left"], screen["top"], screen["right"], screen["bottom"])
    width, height = min(width, right - left), min(height, bottom - top - TITLE_BAR)
    if x is None:
        x, y = left + (right - left - width) // 2, top + (bottom - top - TITLE_BAR - height) // 2
    x, y = min(max(x, left), right - width), min(max(y, top), bottom - TITLE_BAR - height)
    return "%dx%d+%d+%d" % (width, height, x, y)


def scale_at(x, y, found=None):
    """How many screen pixels one pixel of a process that is not DPI aware is, at this point of its screen. 1.0 when no
    monitor has the point."""
    found = monitors() if found is None else found
    return next((m["scale"] for m in found if m["left"] <= x < m["right"] and m["top"] <= y < m["bottom"]), 1.0)

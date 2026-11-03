"""The monitors of this computer, for the windows of tests and self-tests: they open on the second monitor, when there is
one, and not over the work on the main one. No tkinter."""
import ctypes
from ctypes import wintypes

MARGIN = 40         # from the corner of the monitor


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def monitors():
    """Each monitor as {"left", "top", "right", "bottom", "primary", "scale"}, in the pixels of this process. [] when they
    cannot be read."""
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
            area = info.rcMonitor
            found.append({"left": area.left, "top": area.top, "right": area.right, "bottom": area.bottom,
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


def scale_at(x, y, found=None):
    """How many screen pixels one pixel of a process that is not DPI aware is, at this point of its screen. 1.0 when no
    monitor has the point."""
    found = monitors() if found is None else found
    return next((m["scale"] for m in found if m["left"] <= x < m["right"] and m["top"] <= y < m["bottom"]), 1.0)

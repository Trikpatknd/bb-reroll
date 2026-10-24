"""The Map Options the player saved in Battle Brothers' Mod Options, read from MSU's save file.

MSU (the mod that gives every mod its Mod Options menu) saves the player's settings in
<Documents>\\Battle Brothers\\savegames\\MSU#mod_msu#ModSettings.sav: one serialized Squirrel value, an array that
holds {mod id: {setting id: value}}. This module only reads that file (stdlib, no writes). The map search takes the
seven Legends Map Options from it, so a search builds the maps the player's own settings give.
"""
import ctypes
import struct
from pathlib import Path

# The seven Legends Map Options (mod_legends), as MSU stores them.
MAP_OPTION_KEYS = ("LandRatio", "Water", "Snowline", "Settlements", "Factions", "StackCitadels", "AllTradeLocations")
MOD_ID = "mod_legends"
SAVE_FILE = "MSU#mod_msu#ModSettings.sav"
SAVE_NAME = b"MSU#mod_msu#ModSettings"          # the name MSU writes into the header
HEADER_START = b"\xbb\x00\x02"                  # the first three bytes of the serialization header

# MSU's DataType tags (msu/utils/serialization.nut). Read: Null (no payload), Bool, String, Table, Array and the
# numbers U8 U16 U32 I8 I16 I32 F32. Not read: None 0, Unknown 1, SerializationData 14, and any other tag.
TAG_NULL, TAG_BOOL, TAG_STRING, TAG_TABLE, TAG_ARRAY = 2, 3, 4, 12, 13
NUMBER_TAGS = {5: "<B", 6: "<H", 7: "<I", 8: "<b", 9: "<h", 10: "<i", 11: "<f"}
MAX_DEPTH = 16                                  # the file nests three levels; deeper input is refused


class SettingsFormatError(ValueError):
    """The file is not MSU's Mod Options: cut short, a tag this reader does not know, or bytes after the value."""


class _Reader:
    """A cursor over the bytes. A read past the end raises SettingsFormatError."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, n):
        end = self.pos + n
        if end > len(self.data):
            raise SettingsFormatError("the file ends inside a value (at byte %d)" % len(self.data))
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def unpack(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def count(self, depth):
        n = self.value(depth + 1)
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise SettingsFormatError("a count is not a whole number")
        return n

    def value(self, depth=0):
        if depth > MAX_DEPTH:
            raise SettingsFormatError("nested deeper than %d levels" % MAX_DEPTH)
        at = self.pos
        tag = self.take(1)[0]
        if tag == TAG_NULL:
            return None
        if tag == TAG_BOOL:
            flag = self.take(1)[0]
            if flag > 1:
                raise SettingsFormatError("a bool with the value %d at byte %d" % (flag, at + 1))
            return bool(flag)
        if tag == TAG_STRING:                               # another mod's text may not be UTF-8: keep the rest
            return self.take(self.unpack("<H")).decode("utf-8", errors="replace")
        if tag in NUMBER_TAGS:
            return self.unpack(NUMBER_TAGS[tag])
        if tag == TAG_TABLE:
            count = self.count(depth)                       # two values per entry: key, value
            if count % 2:
                raise SettingsFormatError("a table at byte %d has an odd count" % at)
            table = {}
            for _ in range(count // 2):
                key = self.value(depth + 1)
                if not isinstance(key, str):
                    raise SettingsFormatError("a table key at byte %d is not a string" % at)
                table[key] = self.value(depth + 1)
            return table
        if tag == TAG_ARRAY:
            return [self.value(depth + 1) for _ in range(self.count(depth))]
        raise SettingsFormatError("the tag %d at byte %d is unknown" % (tag, at))


def parse(data):
    """{mod id: {setting id: value}} from the bytes of MSU's file. Null is None, bools are bool, whole numbers int,
    floats float, strings str. Raises SettingsFormatError on anything it cannot read."""
    reader = _Reader(data)
    if reader.take(3) != HEADER_START:
        raise SettingsFormatError("no MSU header")
    reader.take(20)                                         # five 4-byte words: zeros, two u32 times, zeros
    if reader.take(reader.unpack("<H")) != SAVE_NAME:
        raise SettingsFormatError("the header does not name MSU's Mod Options")
    reader.take(4)                                          # 00 00 bb 00, then the data
    top = reader.value()
    if reader.pos != len(data):
        raise SettingsFormatError("%d bytes after the settings" % (len(data) - reader.pos))
    if not (isinstance(top, list) and len(top) == 1 and isinstance(top[0], dict)):
        raise SettingsFormatError("the data is not one table of mods")
    for mod, settings in top[0].items():
        if not isinstance(settings, dict):
            raise SettingsFormatError("the settings of %s are not a table" % mod)
    return top[0]


def read_map_options(path=None):
    """The Map Options the player saved, as {key: value} for the keys the file holds: numbers as int (a whole float
    too), booleans as bool. Missing keys and nulls are left out. None when the file is missing or unreadable or holds
    no mod_legends settings. The default path is the player's own save file. Never raises: the GUI starts with it."""
    try:
        if path is None:
            path = settings_path()
        mods = parse(Path(path).read_bytes())
    except Exception:                                       # any failure means: no saved options
        return None
    settings = mods.get(MOD_ID)
    if settings is None:
        return None
    options = {}
    for key in MAP_OPTION_KEYS:
        value = settings.get(key)
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, (bool, int, float)):
            options[key] = value
    return options


def settings_path(documents=None):
    """The save file in <documents>\\Battle Brothers\\savegames. The documents folder is the player's own by default."""
    if documents is None:
        documents = documents_dir()
    return Path(documents) / "Battle Brothers" / "savegames" / SAVE_FILE


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_uint8 * 8)]


def documents_dir():
    """Windows' Documents folder (FOLDERID_Documents, so a redirected folder is found). The home folder's Documents
    when Windows does not answer; the home folder is looked up only then."""
    try:
        folder = _shell_documents()
    except Exception:                                       # no Windows API here, or the call failed
        folder = ""
    if folder:
        return Path(folder)
    return Path.home() / "Documents"


def _shell_documents():
    """SHGetKnownFolderPath(FOLDERID_Documents) as text, "" when the call fails or gives no path."""
    folder = _GUID(0xFDD39AD0, 0x238F, 0x46AF,
                   (ctypes.c_uint8 * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
    out = ctypes.c_void_p()
    hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.pointer(out))
    if hr != 0 or not out.value:
        return ""
    try:
        return ctypes.wstring_at(out.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)

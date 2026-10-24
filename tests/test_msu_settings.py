"""bbseed/msu_settings.py: MSU's saved Mod Options, read from files written here in MSU's format (no game needed).
The check against the Map Options the game itself logged is bb_seedlab's tests/test_msu_settings_log.py."""
import struct
from pathlib import Path

import pytest

from bbseed import msu_settings as M

NAME = b"MSU#mod_msu#ModSettings"
USER_SHAPED = {
    "mod_legends": {"LandRatio": 55, "Water": 38, "Snowline": 85, "Settlements": 24, "Factions": 4,
                    "StackCitadels": True, "AllTradeLocations": True, "DebugMap": False},
    "mod_elite_few": {"multiplier": 2},
}
SEVEN = {"LandRatio": 55, "Water": 38, "Snowline": 85, "Settlements": 24, "Factions": 4,
         "StackCitadels": True, "AllTradeLocations": True}


def encode(value):
    """One value in MSU's tagged format. The bool test comes first: True is an int in Python."""
    if isinstance(value, bool):
        return b"\x03" + (b"\x01" if value else b"\x00")
    if isinstance(value, int):
        if 0 <= value <= 255:
            return b"\x05" + bytes([value])                     # U8
        return b"\x0a" + struct.pack("<i", value)               # I32
    if isinstance(value, float):
        return b"\x0b" + struct.pack("<f", value)               # F32
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return b"\x04" + struct.pack("<H", len(raw)) + raw      # String
    if isinstance(value, dict):                                 # Table: a count of 2 x entries, then key, value...
        body = b"".join(encode(k) + encode(v) for k, v in value.items())
        return b"\x0c" + encode(2 * len(value)) + body
    if isinstance(value, list):                                 # Array: a count, then the values
        return b"\x0d" + encode(len(value)) + b"".join(encode(v) for v in value)
    raise TypeError(type(value))


def file_bytes(tree):
    """The file MSU writes for `tree` ({mod id: {setting id: value}}): the header (times 0), then Array[1] of it."""
    header = (b"\xbb\x00\x02\x00\x00\x00\x00" + struct.pack("<I", 0) + b"\x00" * 4 + struct.pack("<I", 0)
              + b"\x00" * 4 + struct.pack("<H", len(NAME)) + NAME + b"\x00\x00\xbb\x00")
    return header + encode([tree])


def write(tmp_path, data):
    path = tmp_path / "MSU#mod_msu#ModSettings.sav"
    path.write_bytes(data)
    return path


def test_parse_reads_the_user_shaped_file():
    assert M.parse(file_bytes(USER_SHAPED)) == USER_SHAPED


def test_read_map_options_keeps_only_the_seven(tmp_path):
    options = M.read_map_options(write(tmp_path, file_bytes(USER_SHAPED)))
    assert options == SEVEN
    assert "DebugMap" not in options


def test_missing_keys_are_left_out(tmp_path):
    assert M.read_map_options(write(tmp_path, file_bytes({"mod_legends": {"Settlements": 21}}))) == {"Settlements": 21}


def test_float_and_wide_numbers(tmp_path):
    tree = {"mod_legends": {"LandRatio": 55.0, "Settlements": 300, "Water": 12.5}}
    options = M.read_map_options(write(tmp_path, file_bytes(tree)))
    assert options == {"LandRatio": 55, "Settlements": 300, "Water": 12.5}
    assert type(options["LandRatio"]) is int
    assert type(options["Settlements"]) is int
    assert type(options["Water"]) is float


def test_unreadable_files_give_none(tmp_path):
    good = file_bytes(USER_SHAPED)
    tagged = good.replace(b"\x05\x37", b"\x63\x37", 1)          # LandRatio 55 (U8) with tag 99 in its place
    assert good.count(b"\x05\x37") == 1 and tagged != good
    assert M.read_map_options(tmp_path / "missing.sav") is None
    cases = {
        "ten bytes": bytes([0x9f, 0x03, 0x77, 0xc1, 0x00, 0x5a, 0xee, 0x21, 0x84, 0x6d]),
        "cut in half": good[:len(good) // 2],
        "tag 99": tagged,
    }
    for name, data in cases.items():
        assert M.read_map_options(write(tmp_path, data)) is None, name


def test_parse_raises_on_unreadable_data():
    with pytest.raises(M.SettingsFormatError):
        M.parse(bytes([1, 2, 3]))


def test_parse_refuses_bytes_after_the_value():
    with pytest.raises(M.SettingsFormatError):
        M.parse(file_bytes(USER_SHAPED) + b"\x00")


def test_no_legends_gives_none(tmp_path):
    assert M.read_map_options(write(tmp_path, file_bytes({"mod_msu": {"X": 1}}))) is None


def test_settings_path_uses_the_documents_folder():
    assert M.settings_path(Path("D:/Docs")) == Path("D:/Docs/Battle Brothers/savegames/MSU#mod_msu#ModSettings.sav")


def test_default_settings_path_is_the_save_file():
    assert M.settings_path().parts[-3:] == ("Battle Brothers", "savegames", "MSU#mod_msu#ModSettings.sav")

"""bbseed/msu_settings.py: MSU's saved Mod Options, read from files written here in MSU's format (no game needed).
The check against the Map Options the game itself logged is bb_seedlab's tests/test_msu_settings_log.py."""
import ctypes
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
    if value is None:
        return b"\x02"                                          # Null: the tag and nothing else
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


def test_null_values_elsewhere_do_not_lose_the_options(tmp_path):
    tree = {"mod_other": {"Anything": None}, "mod_legends": {"Settlements": 24}}
    assert M.parse(file_bytes(tree)) == tree
    assert M.read_map_options(write(tmp_path, file_bytes(tree))) == {"Settlements": 24}


def test_a_null_map_option_is_left_out(tmp_path):
    tree = {"mod_legends": {"Settlements": 24, "Water": None}}
    assert M.read_map_options(write(tmp_path, file_bytes(tree))) == {"Settlements": 24}


@pytest.mark.parametrize("tag", [0, 1, 14, 99])     # None, Unknown, SerializationData, a tag MSU does not have
def test_unknown_tags_stay_unreadable(tmp_path, tag):
    good = file_bytes({"mod_legends": {"Settlements": 24}})
    assert good.count(b"\x05\x18") == 1                 # Settlements 24 (U8)
    data = good.replace(b"\x05\x18", bytes([tag, 0x18]))
    with pytest.raises(M.SettingsFormatError):
        M.parse(data)
    assert M.read_map_options(write(tmp_path, data)) is None


def test_a_latin1_string_elsewhere_keeps_the_options(tmp_path):
    tree = {"mod_other": {"Note": "Xq1"}, "mod_legends": {"Settlements": 24}}
    data = file_bytes(tree).replace(b"Xq1", b"Ca\xe9")          # the same length in Latin-1, not valid UTF-8
    assert data != file_bytes(tree)
    assert M.parse(data)["mod_other"]["Note"] == "Ca\ufffd"
    assert M.read_map_options(write(tmp_path, data)) == {"Settlements": 24}


class _FakeShell32:
    """Stands in for ctypes.windll.shell32: SHGetKnownFolderPath answers `hr` and, when that is 0, `folder`."""

    def __init__(self, folder=None, hr=0, error=None):
        self.folder, self.hr, self.error = folder, hr, error
        self.keep = []                                  # the wide string must outlive the call

    def SHGetKnownFolderPath(self, guid, flags, token, out):
        if self.error is not None:
            raise self.error
        if self.hr == 0:
            buf = ctypes.create_unicode_buffer(self.folder)
            self.keep.append(buf)
            out.contents.value = ctypes.addressof(buf)
        return self.hr


class _FakeOle32:
    def CoTaskMemFree(self, ptr):
        pass


class _FakeWindll:
    def __init__(self, shell32):
        self.shell32 = shell32
        self.ole32 = _FakeOle32()


def fake_windows(monkeypatch, **answer):
    monkeypatch.setattr(ctypes, "windll", _FakeWindll(_FakeShell32(**answer)), raising=False)


def test_documents_dir_is_the_folder_windows_gives(monkeypatch):
    fake_windows(monkeypatch, folder="D:\\OneDrive\\Docs")
    assert M.documents_dir() == Path("D:\\OneDrive\\Docs")


def test_documents_dir_falls_back_when_windows_refuses(monkeypatch):
    fake_windows(monkeypatch, hr=-2147024894)           # E_FAIL
    assert M.documents_dir() == Path.home() / "Documents"


def test_documents_dir_falls_back_without_windll(monkeypatch):
    monkeypatch.delattr(ctypes, "windll", raising=False)
    assert M.documents_dir() == Path.home() / "Documents"


def test_documents_dir_falls_back_when_the_call_raises(monkeypatch):
    fake_windows(monkeypatch, error=ctypes.ArgumentError("bad argument"))
    assert M.documents_dir() == Path.home() / "Documents"


def test_a_windows_answer_needs_no_home_folder(monkeypatch):
    def no_home(cls):
        raise RuntimeError("no home folder")
    fake_windows(monkeypatch, folder="D:\\OneDrive\\Docs")
    monkeypatch.setattr(Path, "home", classmethod(no_home))
    assert M.documents_dir() == Path("D:\\OneDrive\\Docs")


def test_read_map_options_never_raises(tmp_path, monkeypatch):
    def broken_documents(documents=None):
        raise RuntimeError("no home folder")
    monkeypatch.setattr(M, "documents_dir", broken_documents)
    assert M.read_map_options() is None
    assert M.read_map_options(tmp_path) is None         # a folder, not a file
    assert M.read_map_options(write(tmp_path, file_bytes({"mod_legends": {"Settlements": 24}}))) == {"Settlements": 24}

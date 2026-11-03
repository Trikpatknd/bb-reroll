"""Builds the optional PyPy download of a release: bb_reroll_pypy-<version>.zip, with the folder bb_reroll_pypy that the exe finds
next to itself (bbreroll/pypy_addon.py): PyPy with its licence, this repo's bbseed, and VERSION.

    python tools/build_pypy_addon.py [--zip PYPY_ZIP] [--out FOLDER]

Without --zip it downloads the PyPy zip. The zip must have the SHA-256 that pypy.org/checksums.html gives, whichever way it came.
Prints the SHA-256 of the result: the release notes name it.
"""
import argparse
import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPY_NAME = "pypy3.11-v8.0.1-win64"
PYPY_URL = "https://downloads.python.org/pypy/%s.zip" % PYPY_NAME
PYPY_SHA256 = "cba5f9e9543c679ea5d31b6c81b7a6667d836e3c18bf3eb6cb8c72147f829896"     # pypy.org/checksums.html
FOLDER = "bb_reroll_pypy"
# Parts of PyPy no search reads. The licence stays: pypy\LICENSE.
LEFT_OUT = ("Lib/test/", "Lib/idlelib/", "Lib/turtledemo/", "Lib/tkinter/", "tcl/", "include/", "libs/")
BBSEED_SUFFIXES = (".py", ".json")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(target):
    with urllib.request.urlopen(PYPY_URL, timeout=300) as answer, open(target, "wb") as out:
        shutil.copyfileobj(answer, out)
    return target


def build(pypy_zip, out_dir, source=ROOT):
    """The add-on zip from a checked PyPy zip and the bbseed of `source`; returns its path. ValueError for a wrong checksum."""
    found = sha256(pypy_zip)
    if found != PYPY_SHA256:
        raise ValueError("%s has SHA-256 %s, pypy.org gives %s" % (pypy_zip, found, PYPY_SHA256))
    version = (Path(source) / "VERSION").read_text(encoding="utf-8").strip()
    target = Path(out_dir) / ("%s-%s.zip" % (FOLDER, version))
    temp = target.with_suffix(".tmp")
    with zipfile.ZipFile(pypy_zip) as pypy, zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as out:
        prefix = PYPY_NAME + "/"
        names = [n for n in pypy.namelist() if n.startswith(prefix) and not n.endswith("/")]
        if prefix + "LICENSE" not in names:
            raise ValueError("%s has no LICENSE" % pypy_zip)
        for name in names:
            inner = name[len(prefix):]
            if not inner.startswith(LEFT_OUT):
                out.writestr("%s/pypy/%s" % (FOLDER, inner), pypy.read(name))
        bbseed = Path(source) / "bbseed"
        for path in sorted(bbseed.rglob("*")):
            if path.suffix in BBSEED_SUFFIXES and path.is_file() and "__pycache__" not in path.parts:
                out.write(path, "%s/bbseed/%s" % (FOLDER, path.relative_to(bbseed).as_posix()))
        out.writestr("%s/VERSION" % FOLDER, version + "\n")
    temp.replace(target)
    return target


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", help="the PyPy zip, when it is here already")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="where the result goes (default: dist)")
    args = ap.parse_args(argv)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        pypy_zip = args.zip or fetch(Path(temp) / (PYPY_NAME + ".zip"))
        result = build(pypy_zip, args.out)
    print("%s  SHA-256 %s  %d bytes" % (result, sha256(result), result.stat().st_size))


if __name__ == "__main__":
    sys.exit(main())

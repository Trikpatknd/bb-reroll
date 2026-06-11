"""Build-tooling tests: version stamping, embedded template, and the deploy
zip's contents + manifest."""
import json
import zipfile
from pathlib import Path

import buildutil
import build_zip

ROOT = Path(__file__).resolve().parent.parent


def test_version_file_matches_nut():
    version = buildutil.read_version()
    nut = (ROOT / "mod" / "bb_reroll_dump.nut").read_text(encoding="utf-8")
    assert f'Version    = "{version}"' in nut or f'Version = "{version}"' in nut


def test_stamp_nut_version_replaces_slot():
    src = 'foo\n    Version = "0.0.0",\nbar'
    out = buildutil.stamp_nut_version(src, "9.9.9")
    assert 'Version = "9.9.9"' in out
    assert "0.0.0" not in out


def test_stamp_nut_version_raises_without_slot():
    try:
        buildutil.stamp_nut_version("no version here", "1.2.3")
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError when no Version slot present")


def test_build_zip_contents_and_manifest():
    manifest = build_zip.build_zip()
    version = buildutil.read_version()
    assert manifest["version"] == version

    with zipfile.ZipFile(build_zip.DST) as z:
        names = z.namelist()
        assert "scripts/!mods_preload/bb_reroll_dump.nut" in names
        assert "BBRR_MANIFEST.json" in names
        on_disk = json.loads(z.read("BBRR_MANIFEST.json"))
        assert on_disk["version"] == version
        assert on_disk["mod"] == "bb_reroll_dump"
        # The packaged .nut carries the stamped version.
        nut = z.read("scripts/!mods_preload/bb_reroll_dump.nut").decode("utf-8")
        assert f'"{version}"' in nut


def test_embed_template_has_matching_version():
    # mod_template.py is generated; regenerate-and-import would be heavier, so
    # just assert that if it exists, its NUT_VERSION matches VERSION.
    tmpl = ROOT / "mod_template.py"
    if not tmpl.exists():
        return
    ns = {}
    exec(tmpl.read_text(encoding="utf-8"), ns)
    if "NUT_VERSION" in ns:
        assert ns["NUT_VERSION"] == buildutil.read_version()

"""Is there a newer BB Reroll? One request to GitHub's releases API when the window starts, at most once a day; the player
can turn it off. No tkinter. fetch_latest never raises: no network, no answer or an answer it cannot read is None."""
import json
import re
import urllib.request

LATEST_URL = "https://api.github.com/repos/Trikpatknd/bb-reroll/releases/latest"     # (drafts and pre-releases are left out)
RELEASES_URL = "https://github.com/Trikpatknd/bb-reroll/releases"
CHECK_SECONDS = 24 * 3600
TIMEOUT = 10

CHECKBOX = "Check for updates"
CHECKBOX_TIP = ("One time each day, BB Reroll asks GitHub for the newest version when it starts. GitHub then sees your IP "
                "address. Clear the box to stop the check.")
BUTTON_TIP = "Open the BB Reroll releases on GitHub."
NEWER_BUTTON = "Update to %s"
NEWER_TIP = "BB Reroll %s is available. You have %s. Click to open the releases page."
NEWER_NOTICE = "BB Reroll %s is available. You have %s."
OPEN_RELEASES = "Open releases"


def parse_version(text):
    """(4, 5, 1) for "4.5.1" or "v4.5.1", else None."""
    found = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(text or "").strip())
    return tuple(int(n) for n in found.groups()) if found else None


def newer(latest, current):
    """Is the release `latest` newer than this version? False when either is not a version."""
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def plain(version):
    """The version as the window shows it: "4.6.0" for "v4.6.0"."""
    return str(version).strip().lstrip("v")


def due(last_check, now):
    """Is a check due? Yes with no last check, after CHECK_SECONDS, and when the clock went back."""
    if isinstance(last_check, bool) or not isinstance(last_check, (int, float)):
        return True
    return not 0 <= now - last_check < CHECK_SECONDS


def fetch_latest(current, timeout=TIMEOUT, opener=urllib.request.urlopen):
    """The tag of the newest release ("v4.6.0"), or None."""
    request = urllib.request.Request(LATEST_URL, headers={"Accept": "application/vnd.github+json",
                                                          "User-Agent": "BB-Reroll/%s" % plain(current)})
    try:
        with opener(request, timeout=timeout) as answer:
            tag = json.loads(answer.read().decode("utf-8")).get("tag_name")
    except Exception:       # (no network, a proxy page, a rate limit: the check says nothing)
        return None
    return tag if parse_version(tag) else None

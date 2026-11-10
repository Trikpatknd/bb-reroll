"""The update check without the window or the network (bbreroll/update_check.py)."""
import io
import json
import urllib.error

import pytest

from bbreroll import update_check as U


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_of(body, seen=None):
    def opener(request, timeout):
        if seen is not None:
            seen.append((request, timeout))
        if isinstance(body, Exception):
            raise body
        return Answer(body if isinstance(body, bytes) else json.dumps(body).encode())
    return opener


@pytest.mark.core
def test_a_newer_release_is_newer():
    assert U.newer("v4.6.0", "4.5.1") and U.newer("4.5.10", "4.5.9") and U.newer("v5.0.0", "4.99.99")


@pytest.mark.edge
def test_the_same_or_an_older_release_is_not_newer():
    assert not U.newer("v4.5.1", "4.5.1") and not U.newer("v4.5.0", "4.5.1")


@pytest.mark.dirty
def test_a_text_that_is_no_version_is_never_newer():
    for latest, current in (("latest", "4.5.1"), ("v4.6", "4.5.1"), (None, "4.5.1"), ("v4.6.0", "dev")):
        assert not U.newer(latest, current)


@pytest.mark.core
def test_a_check_is_due_once_a_day():
    assert U.due(None, 1000.0)
    assert not U.due(1000.0, 1000.0 + U.CHECK_SECONDS - 1)
    assert U.due(1000.0, 1000.0 + U.CHECK_SECONDS)


@pytest.mark.dirty
def test_a_clock_that_went_back_or_a_bad_saved_time_makes_it_due():
    assert U.due(5000.0, 4000.0)
    assert U.due("yesterday", 1000.0) and U.due(True, 1000.0)


@pytest.mark.core
def test_the_latest_release_is_its_tag():
    seen = []
    assert U.fetch_latest("4.5.1", opener=opener_of({"tag_name": "v4.6.0", "name": "BB Reroll 4.6.0"}, seen)) == "v4.6.0"
    request, timeout = seen[0]
    assert request.full_url == U.LATEST_URL and timeout == U.TIMEOUT
    assert request.get_header("User-agent") == "BB-Reroll/4.5.1"


@pytest.mark.dirty
@pytest.mark.parametrize("body", [urllib.error.URLError("no network"), OSError("timed out"), b"<html>proxy</html>",
                                  {"message": "API rate limit exceeded"}, {"tag_name": "nightly"}, [1, 2]])
def test_no_answer_or_a_bad_answer_is_none(body):
    assert U.fetch_latest("4.5.1", opener=opener_of(body)) is None


@pytest.mark.core
def test_the_window_shows_the_version_without_the_v():
    assert U.plain("v4.6.0") == "4.6.0" and U.NEWER_BUTTON % U.plain("v4.6.0") == "Update to 4.6.0"

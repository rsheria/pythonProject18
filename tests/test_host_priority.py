import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from utils.host_priority import get_highest_priority_host, filter_direct_links_for_host


class DummySettings:
    def __init__(self, priority):
        self._priority = priority

    def get_current_priority(self):
        return self._priority


def test_get_highest_priority_from_settings():
    settings = DummySettings(["rapidgator.net", "nitroflare.com"])
    assert get_highest_priority_host(settings, {}) == "rapidgator.net"


def test_get_highest_priority_fallback_config():
    config = {"download_hosts_priority": ["nitroflare.com", "rapidgator.net"]}
    assert get_highest_priority_host(None, config) == "nitroflare.com"


def test_get_highest_priority_none():
    assert get_highest_priority_host(None, {}) is None


def test_filter_direct_links_for_host_basic():
    direct = [
        "https://rapidgator.net/file/AAA",
        "https://nitroflare.com/view/BBB",
        "https://rapidgator.net/file/CCC",
    ]
    scope = {
        "row:0": {
            "urls": direct,
            "hosts": ["rapidgator.net", "nitroflare.com"],
            "row": 0,
        },
        "row:1": {
            "urls": ["https://ddownload.com/f/DDD"],
            "hosts": ["ddownload.com"],
            "row": 1,
        },
    }
    filtered_urls, filtered_scope = filter_direct_links_for_host(
        direct, scope, "rapidgator.net"
    )
    assert filtered_urls == [
        "https://rapidgator.net/file/AAA",
        "https://rapidgator.net/file/CCC",
    ]
    assert "row:0" in filtered_scope and "row:1" not in filtered_scope
    assert filtered_scope["row:0"]["urls"] == [
        "https://rapidgator.net/file/AAA",
        "https://rapidgator.net/file/CCC",
    ]
    assert filtered_scope["row:0"]["hosts"] == ["rapidgator.net"]


def test_filter_direct_links_for_host_no_match():
    direct = ["https://nitroflare.com/view/BBB"]
    scope = {
        "row:0": {"urls": direct, "hosts": ["nitroflare.com"], "row": 0}
    }
    filtered_urls, filtered_scope = filter_direct_links_for_host(
        direct, scope, "rapidgator.net"
    )
    assert filtered_urls == []
    assert filtered_scope == {}
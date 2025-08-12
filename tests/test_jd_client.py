import sys
import types
from pathlib import Path

import pytest


class DummyMyjdapi:
    def __init__(self, *args, **kwargs):
        pass


sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("myjdapi", types.SimpleNamespace(Myjdapi=DummyMyjdapi))

from integrations.jd_client import JDClient


class DummyLinkgrabber:
    def __init__(self, fail=False):
        self.fail = fail

    def query_links(self, q):  # pragma: no cover - simple stub
        return [{"uuid": "1"}]

    def remove_links(self, uuids):
        if self.fail:
            raise Exception("fail")


class DummyDevice:
    def __init__(self, fail=False):
        self.linkgrabberv2 = DummyLinkgrabber(fail=fail)


def test_remove_all_from_linkgrabber_success():
    jd = JDClient("e", "p")
    jd.device = DummyDevice()
    assert jd.remove_all_from_linkgrabber() is True


def test_remove_all_from_linkgrabber_failure():
    jd = JDClient("e", "p")
    jd.device = DummyDevice(fail=True)
    assert jd.remove_all_from_linkgrabber() is False


def test_remove_all_from_linkgrabber_no_device():
    jd = JDClient("e", "p")
    assert jd.remove_all_from_linkgrabber() is False
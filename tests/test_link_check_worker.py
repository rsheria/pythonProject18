import importlib.util
import pathlib
import threading
import types
import sys
import logging

# Provide minimal PyQt5 stubs so link_check_worker can be imported without Qt.
class _DummySignal:
    def connect(self, *args, **kwargs):
        pass

    def emit(self, *args, **kwargs):
        pass


class _DummyQThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


def _pyqtSignal(*args, **kwargs):
    return _DummySignal()


def _pyqtSlot(*args, **kwargs):
    def decorator(fn):
        return fn

    return decorator


qtcore_stub = types.SimpleNamespace(
    QThread=_DummyQThread, pyqtSignal=_pyqtSignal, pyqtSlot=_pyqtSlot
)
sys.modules["PyQt5"] = types.SimpleNamespace(QtCore=qtcore_stub)
sys.modules["PyQt5.QtCore"] = qtcore_stub

spec = importlib.util.spec_from_file_location(
    "link_check_worker", pathlib.Path(__file__).resolve().parents[1] / "workers" / "link_check_worker.py"
)
link_check_worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(link_check_worker)
LinkCheckWorker = link_check_worker.LinkCheckWorker


class DummyJD:
    def __init__(self):
        self.sent = None
        self.start_check = None
        self.checked = None

    def connect(self):
        return True

    def add_links_to_linkgrabber(self, urls, start_check=True):
        self.sent = list(urls)
        self.start_check = start_check
        return True

    def query_links(self):
        return []

    def start_online_check(self, ids):  # pragma: no cover - default stub
        self.checked = list(ids)
        return True

    def remove_links(self, ids):
        pass


def test_container_urls_only_added(monkeypatch):
    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = DummyJD()
    worker = LinkCheckWorker(jd, ["d1", "d2"], ["c1", "c2"], threading.Event(), poll_timeout_sec=0)
    worker.run()
    assert jd.sent == ["c1", "c2"]
    assert jd.start_check is False


def test_direct_urls_when_no_container(monkeypatch):
    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = DummyJD()
    worker = LinkCheckWorker(jd, ["d1", "d2"], [], threading.Event(), poll_timeout_sec=0)
    worker.run()
    assert jd.sent == ["d1", "d2"]
    assert jd.start_check is True


def test_container_polling_logs(monkeypatch, caplog):
    class PollJD(DummyJD):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def query_links(self):
            self.calls += 1
            if self.calls < 3:
                return []
            return [{"availability": "ONLINE"}]

    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = PollJD()
    caplog.set_level(logging.DEBUG)
    worker = LinkCheckWorker(jd, [], ["c"], threading.Event(), poll_timeout_sec=1, poll_interval=0)
    worker.run()
    assert jd.calls >= 3
    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "status=queued" in msgs
    assert "status=solving" in msgs
    assert "status=decrypted" in msgs


def test_container_polling_cancel(monkeypatch):
    class CancelJD(DummyJD):
        def __init__(self, cancel_evt):
            super().__init__()
            self.cancel_evt = cancel_evt
            self.calls = 0

        def query_links(self):
            self.calls += 1
            self.cancel_evt.set()
            return []

    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    cancel_evt = threading.Event()
    jd = CancelJD(cancel_evt)
    worker = LinkCheckWorker(jd, [], ["c"], cancel_evt, poll_timeout_sec=5, poll_interval=0)
    worker.run()
    assert jd.calls == 1


def test_container_keeps_only_chosen_host(monkeypatch):
    class JD(DummyJD):
        def query_links(self):
            return [
                {
                    "url": "https://rapidgator.net/file/abc",
                    "host": "rapidgator.net",
                    "availability": "ONLINE",
                    "containerURL": "c",
                    "uuid": "1",
                },
                {
                    "url": "https://nitroflare.com/view/xyz",
                    "host": "nitroflare.com",
                    "availability": "ONLINE",
                    "containerURL": "c",
                    "uuid": "2",
                },
            ]

    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = JD()
    worker = LinkCheckWorker(jd, [], ["c"], threading.Event(), poll_timeout_sec=0)
    worker.set_host_priority(["rapidgator.net", "nitroflare.com"])
    worker.chosen_host = "rapidgator.net"
    events = []
    worker.progress = types.SimpleNamespace(emit=lambda payload: events.append(payload))
    worker.run()
    assert events
    chosen = events[0]["chosen"]
    assert chosen["host"] == "rapidgator.net"
    assert "rapidgator.net" in chosen["url"]


def test_container_fallback_logs(monkeypatch, caplog):
    class JD(DummyJD):
        def query_links(self):
            return [
                {
                    "url": "https://nitroflare.com/view/xyz",
                    "host": "nitroflare.com",
                    "availability": "ONLINE",
                    "containerURL": "c",
                    "uuid": "1",
                },
            ]

    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = JD()
    caplog.set_level(logging.DEBUG)
    worker = LinkCheckWorker(jd, [], ["c"], threading.Event(), poll_timeout_sec=0)
    worker.set_host_priority(["rapidgator.net", "nitroflare.com"])
    worker.chosen_host = "rapidgator.net"
    events = []
    worker.progress = types.SimpleNamespace(emit=lambda payload: events.append(payload))
    worker.run()
    assert events[0]["chosen"]["host"] == "nitroflare.com"
    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "HOST FALLBACK" in msgs


def test_direct_availability_check_only_kept_links(monkeypatch):
    class JD(DummyJD):
        def __init__(self):
            super().__init__()
            self.items = [
                {
                    "url": "https://rapidgator.net/file/abc",
                    "host": "rapidgator.net",
                    "availability": "UNKNOWN",
                    "uuid": "1",
                },
                {
                    "url": "https://nitroflare.com/view/xyz",
                    "host": "nitroflare.com",
                    "availability": "UNKNOWN",
                    "uuid": "2",
                },
            ]

        def query_links(self):
            return self.items

        def start_online_check(self, ids):
            super().start_online_check(ids)
            for it in self.items:
                if it["uuid"] in ids:
                    it["availability"] = "ONLINE"
            return True

    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = JD()
    worker = LinkCheckWorker(
        jd,
        ["https://rapidgator.net/file/abc"],
        [],
        threading.Event(),
        poll_timeout_sec=0,
    )
    worker.chosen_host = "rapidgator.net"
    events: list = []
    worker.progress = types.SimpleNamespace(emit=lambda payload: events.append(payload))
    worker.run()
    assert jd.checked == ["1"]
    assert events and events[0]["status"] == "ONLINE"


def test_container_availability_check_only_kept_links(monkeypatch):
    class JD(DummyJD):
        def __init__(self):
            super().__init__()
            self.calls = 0
            self.items = [
                {
                    "url": "https://rapidgator.net/file/abc",
                    "host": "rapidgator.net",
                    "availability": "UNKNOWN",
                    "uuid": "1",
                    "containerURL": "c",
                },
                {
                    "url": "https://nitroflare.com/view/xyz",
                    "host": "nitroflare.com",
                    "availability": "UNKNOWN",
                    "uuid": "2",
                    "containerURL": "c",
                },
            ]

        def query_links(self):
            self.calls += 1
            if self.calls < 2:
                return []
            return self.items

        def start_online_check(self, ids):
            super().start_online_check(ids)
            for it in self.items:
                if it["uuid"] in ids:
                    it["availability"] = "ONLINE"
            return True

    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = JD()
    worker = LinkCheckWorker(jd, [], ["c"], threading.Event(), poll_timeout_sec=1, poll_interval=0)
    worker.set_host_priority(["rapidgator.net", "nitroflare.com"])
    worker.chosen_host = "rapidgator.net"
    events: list = []
    worker.progress = types.SimpleNamespace(emit=lambda payload: events.append(payload))
    worker.run()
    assert jd.checked == ["1"]
    assert events and events[0]["chosen"]["status"] == "ONLINE"


def test_container_payload_replaces_and_lists_siblings(monkeypatch):
    class JD(DummyJD):
        def __init__(self):
            super().__init__()
            self.calls = 0
            self.items = [
                {
                    "url": "https://rapidgator.net/file/abc",
                    "host": "rapidgator.net",
                    "availability": "UNKNOWN",
                    "uuid": "1",
                    "containerURL": "c",
                },
                {
                    "url": "https://rapidgator.net/file/def",
                    "host": "rapidgator.net",
                    "availability": "UNKNOWN",
                    "uuid": "2",
                    "containerURL": "c",
                },
            ]

        def query_links(self):
            self.calls += 1
            if self.calls < 2:
                return []
            return self.items

        def start_online_check(self, ids):
            super().start_online_check(ids)
            for it in self.items:
                if it["uuid"] == "1":
                    it["availability"] = "ONLINE"
                elif it["uuid"] == "2":
                    it["availability"] = "OFFLINE"
            return True

    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = JD()
    worker = LinkCheckWorker(jd, [], ["c"], threading.Event(), poll_timeout_sec=1, poll_interval=0)
    worker.set_host_priority(["rapidgator.net"])
    worker.chosen_host = "rapidgator.net"
    events: list = []
    worker.progress = types.SimpleNamespace(emit=lambda payload: events.append(payload))
    worker.run()
    assert jd.checked == ["1", "2"]
    assert events and events[0]["replace"] is True
    assert events[0]["chosen"]["url"].endswith("/abc")
    assert events[0]["chosen"]["status"] == "ONLINE"
    assert events[0]["siblings"] == [{"url": "https://rapidgator.net/file/def", "status": "OFFLINE"}]


def test_ack_removes_only_non_chosen(monkeypatch):
    class JD(DummyJD):
        def __init__(self):
            super().__init__()
            self.calls = 0
            self.items = [
                {
                    "url": "https://rapidgator.net/file/abc",
                    "host": "rapidgator.net",
                    "availability": "ONLINE",
                    "uuid": "1",
                    "containerURL": "c",
                },
                {
                    "url": "https://nitroflare.com/view/xyz",
                    "host": "nitroflare.com",
                    "availability": "ONLINE",
                    "uuid": "2",
                    "containerURL": "c",
                },
            ]
            self.removed = []

        def query_links(self):
            self.calls += 1
            if self.calls < 2:
                return []
            return self.items

        def remove_links(self, ids):
            self.removed.append(list(ids))

    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = JD()
    worker = LinkCheckWorker(jd, [], ["c"], threading.Event(), poll_timeout_sec=1, poll_interval=0)
    worker.set_host_priority(["rapidgator.net", "nitroflare.com"])
    worker.chosen_host = "rapidgator.net"
    events: list = []
    worker.progress = types.SimpleNamespace(emit=lambda payload: events.append(payload))
    worker.run()
    assert events and events[0]["group_id"]
    group_id = events[0]["group_id"]
    worker.ack_replaced(events[0]["container_url"], worker.session_id, group_id)
    assert jd.removed == [["2"]]
    # second ack should be a no-op
    worker.ack_replaced(events[0]["container_url"], worker.session_id, group_id)
    assert jd.removed == [["2"]]


def test_detection_and_enqueue_logging(monkeypatch, caplog):
    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = DummyJD()
    caplog.set_level(logging.DEBUG)
    worker = LinkCheckWorker(jd, ["d1"], [], threading.Event(), poll_timeout_sec=0)
    worker.chosen_host = "rapidgator.net"
    worker.run()
    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "DETECT | session=" in msgs
    assert "CHOSEN HOST" in msgs
    assert "JD ENQUEUE" in msgs


def test_jd_cleanup_logging(caplog):
    jd = DummyJD()
    worker = LinkCheckWorker(jd, [], [], threading.Event())
    worker._start_time = 0.0
    caplog.set_level(logging.DEBUG)
    key = (worker.session_id, "gid")
    worker.awaiting_ack[key] = {"remove_ids": ["1"]}
    worker.ack_replaced("http://container", worker.session_id, "gid")
    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "JD CLEANUP" in msgs
    assert "group=gid" in msgs


def test_single_host_mode_off_keeps_all_links(monkeypatch):
    class JD(DummyJD):
        def query_links(self):
            return [
                {
                    "url": "https://rapidgator.net/file/abc",
                    "host": "rapidgator.net",
                    "availability": "ONLINE",
                    "containerURL": "c",
                    "uuid": "1",
                },
                {
                    "url": "https://nitroflare.com/view/xyz",
                    "host": "nitroflare.com",
                    "availability": "OFFLINE",
                    "containerURL": "c",
                    "uuid": "2",
                },
            ]

    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = JD()
    worker = LinkCheckWorker(
        jd,
        [],
        ["c"],
        threading.Event(),
        poll_timeout_sec=0,
        single_host_mode=False,
        auto_replace=True,
    )
    events = []
    worker.progress = types.SimpleNamespace(emit=lambda payload: events.append(payload))
    worker.run()
    assert jd.checked == ["1", "2"]
    assert events and events[0]["replace"] is True
    assert len(events[0]["siblings"]) == 1


def test_auto_replace_flag_off(monkeypatch):
    class JD(DummyJD):
        def __init__(self):
            super().__init__()
            self.items = [
                {
                    "url": "https://rapidgator.net/file/abc",
                    "host": "rapidgator.net",
                    "availability": "UNKNOWN",
                    "uuid": "1",
                    "containerURL": "c",
                },
                {
                    "url": "https://rapidgator.net/file/def",
                    "host": "rapidgator.net",
                    "availability": "UNKNOWN",
                    "uuid": "2",
                    "containerURL": "c",
                },
            ]

        def query_links(self):
            return self.items

        def start_online_check(self, ids):
            super().start_online_check(ids)
            for it in self.items:
                if it["uuid"] in ids:
                    it["availability"] = "ONLINE"
            return True

    monkeypatch.setattr(link_check_worker.time, "sleep", lambda _=None: None)
    jd = JD()
    worker = LinkCheckWorker(
        jd,
        [],
        ["c"],
        threading.Event(),
        poll_timeout_sec=0,
        auto_replace=False,
    )
    worker.set_host_priority(["rapidgator.net"])
    worker.chosen_host = "rapidgator.net"
    events = []
    worker.progress = types.SimpleNamespace(emit=lambda payload: events.append(payload))
    worker.run()
    assert jd.checked == ["1", "2"]
    assert events and events[0]["replace"] is False
    assert worker.awaiting_ack == {}
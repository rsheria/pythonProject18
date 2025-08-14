import json
from utils.link_cache import persist_link_replacement


class DummyUserManager:
    def __init__(self):
        self.data = {}

    def save_user_data(self, filename, data):
        # simulate disk persistence with deep copy
        self.data[filename] = json.loads(json.dumps(data))
        return True

    def load_user_data(self, filename, default=None):
        return json.loads(json.dumps(self.data.get(filename, default)))


class Item:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text

    def setData(self, *args, **kwargs):  # pragma: no cover - no-op for compatibility
        pass


class Table:
    def __init__(self, rows, cols):
        self.data = [[None for _ in range(cols)] for _ in range(rows)]

    def setItem(self, r, c, item):
        self.data[r][c] = item

    def item(self, r, c):
        return self.data[r][c]

    def rowCount(self):
        return len(self.data)

    def columnCount(self):
        return len(self.data[0]) if self.data else 0


def apply_cached_statuses(table, cache, status_col=8):
    import re

    for r in range(table.rowCount()):
        for c in range(table.columnCount()):
            cell = table.item(r, c)
            if not cell:
                continue
            text = cell.text() or ""
            for url in re.findall(r"https?://\S+", text, flags=re.IGNORECASE):
                url = url.strip().strip('.,);]')
                if url in cache:
                    status_item = table.item(r, status_col)
                    if not status_item:
                        status_item = Item()
                        table.setItem(r, status_col, status_item)
                    status_item.setText(cache[url]["status"])
                    break
            else:
                continue
            break


def test_persist_replacement_and_restore_status():
    um = DummyUserManager()
    process_threads = {
        "cat": {"thr": {"links": {"keeplinks": ["http://container"]}}}
    }

    status_map = {
        "http://direct": "ONLINE",
        "http://direct2": "OFFLINE",
    }

    def save_pt():
        um.save_user_data("process_threads.json", process_threads)

    cache = persist_link_replacement(
        process_threads,
        "cat",
        "thr",
        "rapidgator.net",
        status_map,
        save_pt,
        um,
    )

    assert process_threads["cat"]["thr"]["links"]["rapidgator.net"] == [
        "http://direct",
        "http://direct2",
    ]
    saved_pt = um.load_user_data("process_threads.json")
    assert saved_pt["cat"]["thr"]["links"]["rapidgator.net"] == [
        "http://direct",
        "http://direct2",
    ]
    cache_file = um.load_user_data("link_status.json")
    assert cache_file["http://direct"]["status"] == "ONLINE"
    assert cache_file["http://direct2"]["status"] == "OFFLINE"
    assert cache == cache_file

    # Simulate restart and apply cached statuses
    table = Table(1, 9)
    table.setItem(0, 0, Item("thr"))
    table.setItem(0, 1, Item("cat"))
    table.setItem(
        0, 3, Item("\n".join(saved_pt["cat"]["thr"]["links"]["rapidgator.net"]))
    )
    table.setItem(0, 8, Item(""))
    apply_cached_statuses(table, cache)

    assert table.item(0, 3).text() == "http://direct\nhttp://direct2"
    assert table.item(0, 8).text() == "ONLINE"
import os
import pathlib
import importlib
import sys
import types
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import QTreeView, QVBoxLayout, QWidget

# Allow running in the tests directory without installing the package
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# provide dummy requests/bs4 modules for isolated environment
if 'requests' not in sys.modules:
    req = types.ModuleType('requests')
    adapters = types.ModuleType('adapters')
    class HTTPAdapter: ...
    adapters.HTTPAdapter = HTTPAdapter
    req.adapters = adapters
    exc = types.ModuleType('exceptions')
    class SSLError(Exception): ...
    class ConnectionError(Exception): ...
    exc.SSLError = SSLError
    exc.ConnectionError = ConnectionError
    req.exceptions = exc
    class Session: ...
    class Response: ...
    req.Session = Session
    req.Response = Response
    sys.modules['requests'] = req
    sys.modules['requests.adapters'] = adapters
    sys.modules['requests.exceptions'] = exc
if 'bs4' not in sys.modules:
    bs4 = types.ModuleType('bs4')
    class BeautifulSoup: ...
    bs4.BeautifulSoup = BeautifulSoup
    sys.modules['bs4'] = bs4
import templab_manager
from core.user_manager import get_user_manager


class TemplatesWidget(QWidget):
    """Tree view displaying tracked Template Lab users by category.

    The widget maintains an in-memory mapping of the form
    ``{category: {username: {threads: [...], last_seen: str}}}`` and updates
    itself when a delta is applied.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.view = QTreeView()
        layout.addWidget(self.view)

        self.model = QStandardItemModel(self.view)
        self.model.setHorizontalHeaderLabels(["Template Lab Users"])
        self.view.setModel(self.model)

        # Internal stores
        self.users: dict = {}
        self._cat_items: dict = {}
        self._user_items: dict = {}

        # Reload whenever a user logs in or switches
        get_user_manager().register_login_listener(lambda _u: self.reload_from_disk())

    # ------------------------------------------------------------------
    def reload_from_disk(self) -> None:
        """Reload the user mapping from disk and refresh the tree."""
        self.users = templab_manager.load_users() or {}

        # Clear existing model
        self.model.removeRows(0, self.model.rowCount())
        self._cat_items.clear()
        self._user_items.clear()

        for category, users in sorted(self.users.items()):
            cat_item = QStandardItem(category)
            self.model.appendRow(cat_item)
            self._cat_items[category] = cat_item
            self._user_items[category] = {}
            for username, info in sorted(users.items()):
                text = f"{username} ({len(info.get('threads', []))})"
                user_item = QStandardItem(text)
                user_item.setData(info, Qt.UserRole)
                cat_item.appendRow(user_item)
                self._user_items[category][username] = user_item

        self.view.expandAll()

    # ------------------------------------------------------------------
    def apply_user_delta(self, delta: dict) -> None:
        """Merge *delta* into the in-memory store and refresh affected rows."""
        if not delta:
            return

        for category, users in delta.items():
            cat_map = self.users.setdefault(category, {})
            if category not in self._cat_items:
                cat_item = QStandardItem(category)
                self.model.appendRow(cat_item)
                self._cat_items[category] = cat_item
                self._user_items[category] = {}
            else:
                cat_item = self._cat_items[category]

            for username, info in users.items():
                entry = cat_map.setdefault(
                    username, {"threads": [], "last_seen": info.get("last_seen")}
                )
                entry["last_seen"] = info.get("last_seen")

                existing_ids = {t.get("id") for t in entry.get("threads", []) if t.get("id")}
                for thread in info.get("threads", []):
                    tid = thread.get("id")
                    if tid and tid not in existing_ids:
                        entry["threads"].append(thread)
                        existing_ids.add(tid)

                text = f"{username} ({len(entry.get('threads', []))})"
                user_item = self._user_items[category].get(username)
                if user_item is None:
                    user_item = QStandardItem(text)
                    user_item.setData(entry, Qt.UserRole)
                    cat_item.appendRow(user_item)
                    self._user_items[category][username] = user_item
                else:
                    user_item.setText(text)
                    user_item.setData(entry, Qt.UserRole)
                    self.model.dataChanged.emit(
                        user_item.index(), user_item.index()
                    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_template_inheritance(tmp_path, monkeypatch):
    monkeypatch.setenv('FORUMBOT_DATA_DIR', str(tmp_path))
    tm_mod = importlib.import_module('core.template_manager')
    importlib.reload(tm_mod)

    mapping = {
        'Alben': {
            'template': '{CONTENT}\n{LINKS_BLOCK}',
            'children': ['Rock/Alben', 'Metal/Alben'],
        },
        'Singles': {'template': 'S {CONTENT}', 'children': []},
    }
    tm_mod.save_mapping(mapping)

    loaded = tm_mod.load_mapping()
    assert loaded['Alben']['children'] == ['Rock/Alben', 'Metal/Alben']

    for child in ['Rock/Alben', 'Metal/Alben']:
        assert tm_mod.get_template_for_category(child) == '{CONTENT}\n{LINKS_BLOCK}'

    tpl = tm_mod.get_template_for_category('Rock/Alben')
    final = tpl.replace('{CONTENT}', 'X').replace('{LINKS_BLOCK}', 'Y')
    assert '{CONTENT}' not in final and '{LINKS_BLOCK}' not in final
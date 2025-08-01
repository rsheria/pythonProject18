import os
import pathlib
import importlib
import sys
import types
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
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

class TemplatesWidget(QWidget):
    """Minimal placeholder widget used in tests and headless mode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Templates widget placeholder"))
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
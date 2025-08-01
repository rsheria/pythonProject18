import sys
import types
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
# provide dummy requests module if missing
if 'requests' not in sys.modules:
    req = types.ModuleType('requests')
    adapters = types.ModuleType('adapters')
    class HTTPAdapter:
        pass
    adapters.HTTPAdapter = HTTPAdapter
    req.adapters = adapters
    exc = types.ModuleType('exceptions')
    class SSLError(Exception):
        pass
    class ConnectionError(Exception):
        pass
    exc.SSLError = SSLError
    exc.ConnectionError = ConnectionError
    req.exceptions = exc
    class Session:
        def __init__(self):
            pass
    class Response:
        pass
    req.Session = Session
    req.Response = Response
    sys.modules['requests'] = req
    sys.modules['requests.adapters'] = req.adapters
    sys.modules['requests.exceptions'] = req.exceptions
if 'bs4' not in sys.modules:
    bs4 = types.ModuleType('bs4')
    class BeautifulSoup:
        pass
    bs4.BeautifulSoup = BeautifulSoup
    sys.modules['bs4'] = bs4

from core.template_manager import TemplateManager


def test_template_manager_persistence(tmp_path):
    path = tmp_path / "templates.json"
    tm = TemplateManager(path)
    tm.set_template("Movies", "Template 1")
    tm2 = TemplateManager(path)
    assert tm2.get_template("Movies") == "Template 1"


def test_template_apply_links_block(tmp_path):
    path = tmp_path / "templates.json"
    tm = TemplateManager(path)
    tm.set_template("Games", "{CONTENT}\n{LINKS_BLOCK}")
    content = "Body"
    links_block = "Links"
    tpl = tm.get_template("Games")
    final = tpl.replace("{CONTENT}", content).replace("{LINKS_BLOCK}", links_block)
    assert "Body" in final and "Links" in final
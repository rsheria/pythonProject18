import sys
import pathlib
import pytest
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ModuleNotFoundError:
    BeautifulSoup = None
    BS4_AVAILABLE = False
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import types

rt = types.ModuleType("requests_toolbelt")
rt.multipart = types.ModuleType("requests_toolbelt.multipart")
rt.multipart.encoder = types.SimpleNamespace(MultipartEncoder=object, MultipartEncoderMonitor=object)
sys.modules['requests_toolbelt'] = rt
sys.modules['requests_toolbelt.multipart'] = rt.multipart
sys.modules['requests_toolbelt.multipart.encoder'] = rt.multipart.encoder

req = types.ModuleType("requests")
sys.modules['requests'] = req

selenium = types.ModuleType("selenium")
selenium.webdriver = types.ModuleType("selenium.webdriver")
selenium.common = types.SimpleNamespace(WebDriverException=Exception,
                                       TimeoutException=Exception,
                                       NoSuchElementException=Exception)
selenium.webdriver.common = types.ModuleType("selenium.webdriver.common")
selenium.webdriver.common.by = types.SimpleNamespace(By=object)
selenium.webdriver.common.keys = types.SimpleNamespace(Keys=object)
selenium.webdriver.chrome = types.ModuleType("selenium.webdriver.chrome")
selenium.webdriver.chrome.options = types.SimpleNamespace(Options=object)
selenium.webdriver.chrome.service = types.SimpleNamespace(Service=object)
selenium.webdriver.support = types.ModuleType("selenium.webdriver.support")
selenium.webdriver.support.ui = types.SimpleNamespace(WebDriverWait=object)
selenium.webdriver.support.expected_conditions = types.SimpleNamespace(EC=object)
sys.modules['selenium'] = selenium
sys.modules['selenium.webdriver'] = selenium.webdriver
sys.modules['selenium.common'] = selenium.common
sys.modules['selenium.webdriver.common'] = selenium.webdriver.common
sys.modules['selenium.webdriver.common.by'] = selenium.webdriver.common.by
sys.modules['selenium.webdriver.common.keys'] = selenium.webdriver.common.keys
sys.modules['selenium.webdriver.chrome'] = selenium.webdriver.chrome
sys.modules['selenium.webdriver.chrome.options'] = selenium.webdriver.chrome.options
sys.modules['selenium.webdriver.chrome.service'] = selenium.webdriver.chrome.service
sys.modules['selenium.webdriver.support'] = selenium.webdriver.support
sys.modules['selenium.webdriver.support.ui'] = selenium.webdriver.support.ui
sys.modules['selenium.webdriver.support.expected_conditions'] = selenium.webdriver.support.expected_conditions

webdriver_manager = types.ModuleType("webdriver_manager")
webdriver_manager.chrome = types.SimpleNamespace(ChromeDriverManager=object)
sys.modules['webdriver_manager'] = webdriver_manager
sys.modules['webdriver_manager.chrome'] = webdriver_manager.chrome

pyqt5 = types.ModuleType("PyQt5")
pyqt5.QtCore = types.SimpleNamespace(QThread=object, pyqtSignal=lambda *a, **k: None, QTimer=object)
sys.modules['PyQt5'] = pyqt5
sys.modules['PyQt5.QtCore'] = pyqt5.QtCore

sys.modules['deathbycaptcha'] = types.ModuleType('deathbycaptcha')

if BS4_AVAILABLE:
    from core.selenium_bot import ForumBotSelenium
else:
    ForumBotSelenium = object

@pytest.mark.skipif(not BS4_AVAILABLE, reason="bs4 not installed")
def test_anchor_image_uses_img_src(monkeypatch):
    bot = ForumBotSelenium.__new__(ForumBotSelenium)
    bot.forum_url = "https://forum.example"
    bot.driver = None

    monkeypatch.setattr("core.selenium_bot.fix_all_image_tags", lambda driver, bbcode: bbcode)

    html = (
        '<a href="https://www.directupload.eu" target="_blank">'
        '<img src="https://s1.directupload.eu/images/250715/wtl9hlez.jpg">'
        '</a>'
    )

    bbcode = bot.convert_post_html_to_bbcode(html)
    assert (
            "[IMG]https://s1.directupload.eu/images/250715/wtl9hlez.jpg[/IMG]" in bbcode
    )
    assert "https://www.directupload.eu" not in bbcode


@pytest.mark.skipif(not BS4_AVAILABLE, reason="bs4 not installed")
def test_megathread_anchor_image_uses_img_src(monkeypatch):
    bot = ForumBotSelenium.__new__(ForumBotSelenium)
    bot.forum_url = "https://forum.example"
    bot.driver = None

    html = (
        '<div id="post_message_1">'
        '<a href="https://www.directupload.eu" target="_blank">'
        '<img src="https://s1.directupload.eu/images/250715/wtl9hlez.jpg">'
        '</a>'
        '</div>'
    )

    soup = BeautifulSoup(html, 'html.parser')
    post_element = soup.find('div')

    bbcode = bot.convert_megathread_post_to_bbcode(html, post_element)
    assert (
        "[IMG]https://s1.directupload.eu/images/250715/wtl9hlez.jpg[/IMG]" in bbcode
    )
    assert "https://www.directupload.eu" not in bbcode
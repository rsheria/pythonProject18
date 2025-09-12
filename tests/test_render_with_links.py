import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.template_manager import render_with_links


class DummyTM:
    def get_template(self, category):
        return ""


def test_render_with_links_single_audio():
    tm = DummyTM()
    host_results = {
        "keeplinks": {"urls": ["https://keep/link"]},
        "rapidgator.net": {"by_type": {"audio": {"mp3": ["https://rg/song.mp3"]}}},
        "nitroflare.com": {"by_type": {"audio": {"mp3": ["https://nf/song.mp3"]}}},
    }
    result = render_with_links(tm, "Music", host_results, template_text="")
    expected = (
        "[url=https://keep/link]Keeplinks[/url] ‖ "
        "Rapidgator: [url=https://rg/song.mp3]1[/url] ‖ "
        "Nitroflare: [url=https://nf/song.mp3]1[/url]"
    )
    assert result == expected
    assert "\n" not in result


def test_render_with_links_single_book_single_format():
    tm = DummyTM()
    host_results = {
        "keeplinks": {"urls": ["https://keep/abc"]},
        "ddownload.com": {"by_type": {"book": {"epub": ["https://ddl/book.epub"]}}},
        "rapidgator.net": {"by_type": {"book": {"epub": ["https://rg/book.epub"]}}},
    }
    result = render_with_links(tm, "Books", host_results, template_text="")
    expected = (
        "[url=https://keep/abc]Keeplinks[/url] ‖ "
        "DDownload: [url=https://ddl/book.epub]1[/url] ‖ "
        "Rapidgator: [url=https://rg/book.epub]1[/url]"
    )
    assert result == expected
    assert "\n" not in result

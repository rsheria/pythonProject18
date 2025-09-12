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
        "rapidgator-backup": {
            "by_type": {"audio": {"mp3": ["https://rg/backup.mp3"]}},
            "is_backup": True,
        },
    }
    result = render_with_links(tm, "Music", host_results, template_text="")
    expected = (
        "[url=https://keep/link]Keeplinks[/url] ‖ "
        "Rapidgator: [url=https://rg/song.mp3]Rapidgator[/url] ‖ "
        "Nitroflare: [url=https://nf/song.mp3]Nitroflare[/url]"
    )
    assert result == expected
    assert "backup.mp3" not in result
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
        "DDownload: [url=https://ddl/book.epub]DDownload[/url] ‖ "
        "Rapidgator: [url=https://rg/book.epub]Rapidgator[/url]"
    )
    assert result == expected
    assert "\n" not in result


def test_render_with_links_mixed_types_strip_host_placeholders():
    tm = DummyTM()
    host_results = {
        "keeplinks": {"urls": ["https://keep/link"]},
        "rapidgator.net": {
            "by_type": {
                "audio": {"mp3": ["https://rg/song.mp3"]},
                "book": {"epub": ["https://rg/book.epub"]},
            }
        },
        "nitroflare.com": {
            "by_type": {
                "audio": {"mp3": ["https://nf/song.mp3"]},
                "book": {"epub": ["https://nf/book.epub"]},
            }
        },
    }
    template = "[url={LINK_RG}]RG[/url] ‖ {LINKS}"
    result = render_with_links(tm, "Mixed", host_results, template_text=template)
    assert "{LINK_RG}" not in result
    assert "[url={LINK_RG}]" not in result
    assert "[b]Links – Hörbücher[/b]" in result
    assert "[b]Links – eBooks[/b]" in result
    assert "[url=https://rg/song.mp3]Rapidgator[/url]" in result
    assert "[url=https://rg/book.epub]Rapidgator[/url]" in result

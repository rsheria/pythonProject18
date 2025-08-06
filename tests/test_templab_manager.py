import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import templab_manager
from templab_manager import _apply_template_regex



def test_apply_template_partial_match():
    bbcode = """[b]header[/b]\nSome body text\nLinks: none"""
    template = "{TITLE}\n{BODY}"
    regexes = {
        "header_regex": r"\[b\](.+?)\[/b\]",
        "body_regex": r"Some (.+) text",
        "links_regex": r"Link:\\s+(.*)"  # will not match
    }
    result = _apply_template_regex(bbcode, template, regexes)
    assert result.startswith("header")
    assert "body" in result
    assert "Links: none" in result



def test_apply_template_no_match_returns_original():
    text = "plain text"
    template = "{TITLE}{BODY}"
    regexes = {"header_regex": r"nope", "body_regex": r"missing"}
    assert _apply_template_regex(text, template, regexes) == text


def test_apply_template_empty_regexes():
    text = "[b]header[/b]"
    template = "{TITLE}"
    regexes = {}
    assert _apply_template_regex(text, template, regexes) == text


def test_apply_template_desc_regex_fewer_groups():
    bbcode = "Format: PDF\nGröße: 1 MB\nbody"
    template = "{DESC}\n{BODY}"
    regexes = {
        "desc_regex": r"(Format:.*?Größe:.*)",
        "body_regex": r"(body)",
    }
    result = _apply_template_regex(bbcode, template, regexes)
    assert "Format: pdf" in result
    assert "Größe: 1 MB" in result


def test_apply_template_returns_filled_string(monkeypatch):
    monkeypatch.setattr(
        templab_manager,
        "parse_bbcode_ai",
        lambda bbcode, prompt: {
            "title": "T",
            "cover": "C",
            "desc": "D",
            "body": "B",
            "links": ["L1", "L2"],
        },
    )

    monkeypatch.setattr(
        templab_manager,
        "_load_cfg",
        lambda category, author: {"template": "{TITLE}-{COVER}-{DESC}-{BODY}-{LINKS}"},
    )

    result = templab_manager.apply_template("bb", "cat", "auth")

    assert isinstance(result, str)
    assert "T" in result
    assert "{LINKS}" in result
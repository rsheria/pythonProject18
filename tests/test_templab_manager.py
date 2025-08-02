import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from templab_manager import apply_template


def test_apply_template_partial_match():
    bbcode = """[b]header[/b]\nSome body text\nLinks: none"""
    template = "{TITLE}\n{BODY}"
    regexes = {
        "header_regex": r"\[b\](.+?)\[/b\]",
        "body_regex": r"Some (.+) text",
        "links_regex": r"Link:\\s+(.*)"  # will not match
    }
    result = apply_template(bbcode, template, regexes)
    assert result.startswith("header")
    assert "body" in result
    assert "Links: none" in result


def test_apply_template_no_match_returns_original():
    text = "plain text"
    template = "{TITLE}{BODY}"
    regexes = {"header_regex": r"nope", "body_regex": r"missing"}
    assert apply_template(text, template, regexes) == text


def test_apply_template_empty_regexes():
    text = "[b]header[/b]"
    template = "{TITLE}"
    regexes = {}
    assert apply_template(text, template, regexes) == text
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import templab_manager
from templab_manager import _apply_template_regex



def test_apply_template_regex_noop():
    text = "[b]header[/b]\nbody"
    template = "{TITLE}{BODY}"
    regexes = {"header_regex": "pattern"}
    assert _apply_template_regex(text, template, regexes) == text

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


def test_global_prompt_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(templab_manager, "TEMPLAB_DIR", tmp_path)
    monkeypatch.setattr(templab_manager, "USERS_DIR", tmp_path / "users")
    (tmp_path / "users").mkdir()

    # No prompt saved yet -> falls back to default
    assert templab_manager.load_global_prompt() == templab_manager.DEFAULT_PROMPT

    templab_manager.save_global_prompt("MY PROMPT")
    assert templab_manager.load_global_prompt() == "MY PROMPT"

    cfg = templab_manager._load_cfg("cat", "author")
    assert cfg["prompt"] == "MY PROMPT"
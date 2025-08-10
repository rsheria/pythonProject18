import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import json
import templab_manager

class DummyClient:
    def __init__(self, content: str):
        class Msg:
            def __init__(self, c):
                self.content = c

        class Choice:
            def __init__(self, c):
                self.message = Msg(c)

        class Rsp:
            def __init__(self, c):
                self.choices = [Choice(c)]

        class Completions:
            def __init__(self, c):
                self._c = c

            def create(self, model, temperature, messages):
                return Rsp(self._c)

        class Chat:
            def __init__(self, c):
                self.completions = Completions(c)

        self.chat = Chat(content)


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

def test_category_template_prompt_propagation(tmp_path, monkeypatch):
    monkeypatch.setattr(templab_manager, "TEMPLAB_DIR", tmp_path)
    monkeypatch.setattr(templab_manager, "USERS_DIR", tmp_path / "users")
    (tmp_path / "users" / "cat").mkdir(parents=True)

    # create some author files
    for name in ["a1", "a2"]:
        (tmp_path / "users" / "cat" / f"{name}.json").write_text(
            json.dumps({"template": "old", "prompt": "old", "threads": {}}),
            encoding="utf-8",
        )

    templab_manager.save_category_template_prompt("cat", "TPL", "PRM")

    for name in ["a1", "a2"]:
        data = json.loads((tmp_path / "users" / "cat" / f"{name}.json").read_text("utf-8"))
        assert data["template"] == "TPL"
        assert data["prompt"] == "PRM"

    cfg = templab_manager._load_cfg("cat", "new")
    assert cfg["template"] == "TPL"
    assert cfg["prompt"] == "PRM"
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


def test_parse_bbcode_ai_replaces_size_line_total_gb(monkeypatch):
    ai_js = {
        "title": "T",
        "cover": "",
        "desc": "Genre: X\nFormat: Y\nGröße: 1 MB",
        "body": "",
        "links": [],
    }
    monkeypatch.setattr(
        templab_manager, "_OPENAI_CLIENT", DummyClient(json.dumps(ai_js))
    )
    monkeypatch.setattr(templab_manager, "_OPENAI_KEY", "k")

    bbcode = "file1 1.5 GB\nfile2 500MB\nquality 128 kbps"
    result = templab_manager.parse_bbcode_ai(bbcode, "prompt")
    assert result["desc"].splitlines() == [
        "Genre: X",
        "Format: Y",
        "Größe: 2.0 GB",
    ]


def test_parse_bbcode_ai_replaces_size_line_total_mb(monkeypatch):
    ai_js = {
        "title": "T",
        "cover": "",
        "desc": "Genre: X\nFormat: Y\nGröße: 1 MB",
        "body": "",
        "links": [],
    }
    monkeypatch.setattr(
        templab_manager, "_OPENAI_CLIENT", DummyClient(json.dumps(ai_js))
    )
    monkeypatch.setattr(templab_manager, "_OPENAI_KEY", "k")

    bbcode = "part1 400MB\npart2 512MB\nspeed 256 kbps"
    result = templab_manager.parse_bbcode_ai(bbcode, "prompt")
    assert result["desc"].splitlines() == [
        "Genre: X",
        "Format: Y",
        "Größe: 912 MB",
    ]


def test_parse_bbcode_ai_keeps_desc_when_no_sizes(monkeypatch):
    ai_js = {
        "title": "T",
        "cover": "",
        "desc": "Genre: X\nFormat: Y\nGröße: 5 MB",
        "body": "",
        "links": [],
    }
    monkeypatch.setattr(
        templab_manager, "_OPENAI_CLIENT", DummyClient(json.dumps(ai_js))
    )
    monkeypatch.setattr(templab_manager, "_OPENAI_KEY", "k")

    bbcode = "just text 128 kbps"
    result = templab_manager.parse_bbcode_ai(bbcode, "prompt")
    assert result["desc"] == ai_js["desc"]
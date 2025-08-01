import json
import re
from pathlib import Path
from config.config import DATA_DIR
from utils.utils import sanitize_filename

# ------------------------------------------------------------------
# Directories
# ------------------------------------------------------------------

def _ensure_dir(sub: str) -> Path:
    base = Path(DATA_DIR)
    path = base / sub
    try:
        path.mkdir(parents=True, exist_ok=True)
        test = path / "._w"
        with open(test, "w"):
            pass
        test.unlink()
    except Exception:
        path = Path.home() / sub
        path.mkdir(parents=True, exist_ok=True)
    return path

USERS_DIR = _ensure_dir("users")
TEMPLAB_DIR = _ensure_dir("templab")

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def get_unified_template(category: str) -> str:
    path = TEMPLAB_DIR / f"{sanitize_filename(category)}.template"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def save_unified_template(category: str, text: str) -> None:
    path = TEMPLAB_DIR / f"{sanitize_filename(category)}.template"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_regex(author: str, category: str) -> dict:
    path = TEMPLAB_DIR / f"{sanitize_filename(category)}.{sanitize_filename(author)}.json"
    if path.exists():
        try:
            return json.load(open(path, "r", encoding="utf-8"))
        except Exception:
            pass
    return {"header_regex": "", "desc_regex": "", "links_regex": "", "body_regex": ""}


def save_regex(author: str, category: str, data: dict) -> None:
    path = TEMPLAB_DIR / f"{sanitize_filename(category)}.{sanitize_filename(author)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def store_post(author: str, category: str, thread: dict) -> None:
    dir_path = USERS_DIR / sanitize_filename(category)
    dir_path.mkdir(parents=True, exist_ok=True)
    file = dir_path / f"{sanitize_filename(author)}.json"
    if file.exists():
        try:
            posts = json.load(open(file, "r", encoding="utf-8"))
        except Exception:
            posts = []
    else:
        posts = []
    if isinstance(posts, dict):
        posts = posts.get("posts", [])
    posts.append(thread)
    with open(file, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def _test_regex(pattern: str, text: str) -> bool:
    if not pattern:
        return False
    try:
        m = re.search(pattern, text, re.S | re.I)
        return bool(m and m.lastindex == 1)
    except re.error:
        return False


def apply_template(bbcode: str, template: str, regexes: dict) -> str:
    groups = {}
    spans = []
    for key, pattern in regexes.items():
        if not pattern:
            continue
        try:
            m = re.search(pattern, bbcode, re.S | re.I)
        except re.error:
            # ignore invalid patterns
            continue
        if not m or m.lastindex != 1:
            return bbcode
        groups[key] = m.group(1)
        spans.append(m.span(1))
        if not template:
            continue
    if not template or not spans:
        return bbcode

    start = min(s for s, _ in spans)
    end = max(e for _, e in spans)
    prefix = bbcode[:start]
    suffix = bbcode[end:]
    result = template
    result = result.replace("{HEADER}", groups.get("header_regex", ""))
    result = result.replace("{DESC}", groups.get("desc_regex", ""))
    result = result.replace("{LINKS}", groups.get("links_regex", ""))
    result = result.replace("{BODY}", groups.get("body_regex", ""))
    return prefix + result + suffix


def convert(thread: dict) -> str:
    category = str(thread.get("category", "")).lower()
    author = thread.get("author", "")
    bbcode = thread.get("bbcode_original", "")
    template = get_unified_template(category)
    regexes = load_regex(author, category)
    return apply_template(bbcode, template, regexes)
# ★ Dual DESC mode: supports 1-group legacy & 2-group modern ★
import json
import re
from pathlib import Path
from config.config import DATA_DIR
from utils.utils import sanitize_filename
import logging
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

_HOOKS = {"rewrite_images": None, "rewrite_links": None, "reload_tree": None}


def set_hooks(hooks: dict) -> None:
    """Set optional hooks for rewriting and GUI updates."""
    if not isinstance(hooks, dict):
        return
    _HOOKS.update(hooks)
# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _compile(rx_dict: dict) -> dict:
    """Compile regex patterns with flags re.S | re.I."""
    compiled = {}
    for key, pattern in rx_dict.items():
        if pattern:
            try:
                compiled[key] = re.compile(pattern, re.S | re.I)
            except re.error:
                compiled[key] = None
        else:
            compiled[key] = None
    return compiled


def _grab(pattern, text: str):
    """Search text using compiled regex pattern."""
    if not pattern:
        return None
    if hasattr(pattern, "search"):
        try:
            return pattern.search(text)
        except re.error:
            return None
    try:
        pat = re.compile(pattern, re.S | re.I)
    except re.error:
        return None
    return pat.search(text)

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
            data = json.load(open(path, "r", encoding="utf-8"))
            data = {
                "header_regex": data.get("header_regex", ""),
                "cover_regex": data.get("cover_regex", ""),
                "desc_regex": data.get("desc_regex", ""),
                "links_regex": data.get("links_regex", ""),
                "body_regex": data.get("body_regex", ""),
            }
            return _compile(data)
        except Exception:
            pass
    return _compile({
        "header_regex": "",
        "cover_regex": "",
        "desc_regex": "",
        "links_regex": "",
        "body_regex": "",
    })



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
    cb = _HOOKS.get("reload_tree")
    if cb:
        try:
            cb()
        except Exception:
            pass

def _test_regex(pattern: str, text: str) -> bool:
    m = _grab(pattern, text) if pattern else None
    return bool(m and m.lastindex == 1)


def apply_template(bbcode: str, template: str, regexes: dict) -> str:
    groups = {}
    spans = []
    for key, pattern in regexes.items():
        if not pattern:
            continue
        m = _grab(pattern, bbcode)
        if m is None:
            # ignore invalid patterns
            continue
        if key == "desc_regex":
            if not m:
                continue
            if m.lastindex == 2:  # new style → (1)=format  (2)=size
                groups["format"] = m.group(1)
                groups["size"] = m.group(2)
                spans.append(m.span(0))      # remove whole block
            elif m.lastindex == 1:  # legacy whole block
                groups["desc_block"] = m.group(1)
                spans.append(m.span(0))
            continue   # skip default one-group handling
        if not m or m.lastindex != 1:
            return bbcode
        groups[key] = m.group(1)  # ما زلنا نحتاج النص الداخلى
        # لو كان المفتاح body_regex أو cover_regex احذف المقطع كله (span(0))
        if key in ("body_regex", "cover_regex"):
            spans.append(m.span(0))  # احذف المقطع كله (السطر وما بعده)
        else:
            spans.append(m.span(1))  # احذف النصّ الداخلى فقط
        if not template:
            continue

    if not template or not spans:
        return bbcode

    # احذف كل المقاطع التي التقطتها الـ regex
    for s, e in sorted(spans, key=lambda t: t[0], reverse=True):
        bbcode = bbcode[:s] + bbcode[e:]

    if "format" in groups and "size" in groups:
        desc_text = f"Genre: Sachbuch\nFormat: {groups['format'].lower()}\nGröße: {groups['size']}"
    elif "desc_block" in groups:
        desc_text = groups["desc_block"]
    else:
        desc_text = ""

    # املأ القالب بالبيانات
    filled = (
        template
        .replace("{TITLE}",  groups.get("header_regex", ""))
        .replace("{COVER}",  groups.get("cover_regex", ""))
        .replace("{DESC}",   desc_text)
        .replace("{BODY}",   groups.get("body_regex", ""))
    )

    # أدخِل القالب في أول موضع حُذِف
    insert_at = min(s for s, _ in spans) if spans else len(bbcode)
    return bbcode[:insert_at] + filled + bbcode[insert_at:]




def convert(thread: dict, apply_hooks: bool = True) -> str:
    category = str(thread.get("category", "")).lower()
    title = thread.get("title", "")
    logging.debug(f"templab_manager.convert: {category}/{title}")
    author = thread.get("author", "")
    bbcode = thread.get("bbcode_original") or ""
    template = get_unified_template(category)
    if not template:
        logging.warning(f"Unified template missing for category '{category}'")
        return bbcode
    regexes = load_regex(author, category)
    cover_found = bool(regexes.get("cover_regex") and _grab(regexes.get("cover_regex"), bbcode))
    bbcode = apply_template(bbcode, template, regexes)

    # ------------------------------------------------------------------
    # Replace common placeholders before applying hooks
    # ------------------------------------------------------------------
    if "{TITLE}" in bbcode:
        bbcode = bbcode.replace("{TITLE}", title)

    if "{COVER}" in bbcode:
        if cover_found:
            logging.info("Cover regex matched")

    if apply_hooks:
        img_hook = _HOOKS.get("rewrite_images")
        if img_hook:
            bbcode = img_hook(bbcode)
        link_hook = _HOOKS.get("rewrite_links")
        if link_hook:
            bbcode = link_hook(bbcode)
    return bbcode

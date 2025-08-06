# ★ header merged (author-title) & desc flexible (size/format order) ★
import json
import os
import re
from pathlib import Path
from config.config import DATA_DIR
from utils.utils import sanitize_filename
import logging
from dotenv import load_dotenv, find_dotenv

# ``openai`` is an optional dependency.  Older versions (<1.0) exposed a
# ``ChatCompletion`` class, while newer releases use an ``OpenAI`` client
# instance.  Import and configure the module if available, but tolerate its
# absence for test environments.
try:  # pragma: no cover - optional dependency
    import openai  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    openai = None
# Ensure environment variables from .env are loaded before accessing them
load_dotenv(find_dotenv())

_OPENAI_KEY = os.getenv("OPENAI_API_KEY")
# In the new API a client object is required.  Keep a module level reference so
# ``parse_bbcode_ai`` can decide which interface to use.
_OPENAI_CLIENT = None
if openai and _OPENAI_KEY:
    if hasattr(openai, "OpenAI"):
        try:  # pragma: no cover - network config handled elsewhere
            _OPENAI_CLIENT = openai.OpenAI(api_key=_OPENAI_KEY)
        except Exception:
            _OPENAI_CLIENT = None
    else:  # Legacy <1.0 style
        openai.api_key = _OPENAI_KEY
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

DEFAULT_PROMPT = """
You are a deterministic BBCode extractor.
Return ONLY pure JSON with these exact keys:
{ "title":"","cover":"","desc":"","body":"","links":[] }
• title         – full title, no BBCode
• cover         – direct image URL or empty
• desc          – three lines: Genre / Format / Größe
• body          – summary text, no BBCode tags
• links         – list of raw download URLs
Never wrap the JSON in markdown, code-fences, or prose.
"""


def set_hooks(hooks: dict) -> None:
    """Set optional hooks for rewriting and GUI updates."""
    if not isinstance(hooks, dict):
        return
    _HOOKS.update(hooks)

# Config helpers
# ------------------------------------------------------------------
def _cfg_path(category: str, author: str) -> Path:
    cat_dir = USERS_DIR / sanitize_filename(category)
    cat_dir.mkdir(parents=True, exist_ok=True)
    return cat_dir / f"{sanitize_filename(author)}.json"


def _load_cfg(category: str, author: str) -> dict:
    path = _cfg_path(category, author)
    if path.exists():
        try:
            data = json.load(open(path, "r", encoding="utf-8"))
            if isinstance(data, list):  # backward compatibility
                data = {"template": "", "prompt": DEFAULT_PROMPT, "threads": data}
            data.setdefault("template", "")
            data.setdefault("prompt", DEFAULT_PROMPT)
            data.setdefault("threads", {})
            return data
        except Exception:
            pass
    return {"template": "", "prompt": DEFAULT_PROMPT, "threads": {}}


def _save_cfg(category: str, author: str, data: dict) -> None:
    path = _cfg_path(category, author)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
# ------------------------------------------------------------------
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

def parse_bbcode_ai(bbcode: str, prompt: str) -> dict:
    """Use OpenAI to extract structured data from BBCode."""
    if (not openai and not _OPENAI_CLIENT) or not _OPENAI_KEY:
        raise json.JSONDecodeError("missing api key", bbcode, 0)

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": bbcode[:12000]},
    ]

    # Use the new client-based API when available.  Fallback to the legacy
    # ``ChatCompletion`` class for older versions.
    if _OPENAI_CLIENT is not None:
        rsp = _OPENAI_CLIENT.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0,
            messages=messages,
        )
    else:  # pragma: no cover - requires legacy openai package
        rsp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            temperature=0,
            messages=messages,
        )

    msg = rsp.choices[0].message
    if isinstance(msg, dict):
        content = msg.get("content", "")
    else:  # ``ChatCompletionMessage`` object in modern SDK
        content = getattr(msg, "content", "")
    js = json.loads(content)
    assert all(k in js for k in ("title", "cover", "desc", "body", "links"))
    return js

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
    data = _load_cfg(category, author)
    threads = data.setdefault("threads", {})
    key = (
            thread.get("thread_id")
            or thread.get("title")
            or thread.get("thread_title")
            or thread.get("version_title")
            or str(len(threads) + 1)
    )
    threads[key] = thread
    _save_cfg(category, author, data)
    cb = _HOOKS.get("reload_tree")
    if cb:
        try:
            cb()
        except Exception:
            pass

def _test_regex(pattern: str, text: str) -> bool:
    m = _grab(pattern, text) if pattern else None
    return bool(m and m.lastindex == 1)


def _apply_template_regex(bbcode: str, template: str, regexes: dict) -> str:
    """Return bbcode with `template` applied using `regexes`."""
    groups: dict[str, str] = {}
    spans: list[tuple[int, int]] = []

    # ---------- 1. اجمع القيم واحذف المقاطع الأصلية ----------
    for key, pattern in regexes.items():
        if not pattern:
            continue

        m = _grab(pattern, bbcode)
        if m is None:
            # نمط غير صالح
            continue

        # ---- header: مؤلِّف + عنوان (مجموعتـان) ---------------
        if key == "header_regex":
            if m.lastindex == 2:
                groups["header_regex"] = f"{m.group(1).strip()} - {m.group(2).strip()}"
            else:
                groups["header_regex"] = m.group(1).strip()
            spans.append(m.span(0))        # احذف السطرين الأصليَّين
            continue
        # ابحث عن Format و Größe منفصلين – يعمل مهما كان ترتيبهما أو وجود |
        fmt = re.search(r"(?i)Format:\s*([^\r\n|]+)", bbcode)
        siz = re.search(r"(?i)Gr(?:ö|o)ße:\s*([\d\.,]+\s*[kmg]?b)", bbcode)
        if fmt:
            groups["format"] = fmt.group(1).strip()
        if siz:
            groups["size"] = siz.group(1).strip()
        # ---- description: Format / Size (أى ترتيب) ------------
        if key == "desc_regex":
            # قد لا يوفّر النمط جميع المجموعات؛ التقط المتاح منها بأمان
            fmt1 = m.group(1).strip() if m.lastindex and m.lastindex >= 1 and m.group(1) else None
            size1 = m.group(2).strip() if m.lastindex and m.lastindex >= 2 and m.group(2) else None
            size2 = m.group(3).strip() if m.lastindex and m.lastindex >= 3 and m.group(3) else None
            fmt2 = m.group(4).strip() if m.lastindex and m.lastindex >= 4 and m.group(4) else None

            if fmt1 or fmt2:
                groups["format"] = fmt1 or fmt2
            if size1 or size2:
                groups["size"] = size1 or size2
            spans.append(m.span(0))        # احذف الكتلة الأصلية
            continue

        # ---- الأنماط الأخرى (مطلوب مجموعة واحدة) -------------
        if not m or m.lastindex != 1:
            return bbcode                   # نرجع النص الأصلى لو فشل
        groups[key] = m.group(1)

        # احذف الكتلة كلها لبعض المفاتيح
        if key in ("body_regex", "cover_regex", "links_regex"):
            spans.append(m.span(0))
        else:
            spans.append(m.span(1))

    if not template or not spans:
        return bbcode

    # ---------- 2. احذف المقاطع فى ترتيب عكسى ----------
    for s, e in sorted(spans, key=lambda t: t[0], reverse=True):
        bbcode = bbcode[:s] + bbcode[e:]

    # ---------- 3. بِنِى الوصف ----------
    if "format" in groups and "size" in groups:
        desc_text = (
            "Genre: Sachbuch\n"
            f"Format: {groups['format'].strip().lower()}\n"
            f"Größe: {groups['size'].upper()}"
        )
    elif "desc_block" in groups:
        desc_text = groups["desc_block"]
    else:
        desc_text = ""

    # ---------- 4. املأ القالب ----------
    filled = (
        template
        .replace("{TITLE}", groups.get("header_regex", ""))
        .replace("{COVER}", groups.get("cover_regex", ""))
        .replace("{DESC}",  desc_text)
        .replace("{BODY}",  groups.get("body_regex", ""))
    )

    # أدخِل القالب فى أول موضعٍ حُذِف
    insert_at = min(s for s, _ in spans) if spans else len(bbcode)
    return bbcode[:insert_at] + filled + bbcode[insert_at:]

def apply_template(
    bbcode: str,
    category: str,
    author: str,
    *,
    thread_title: str = "",
) -> str:
    """Fill the template with parsed data.

    thread_title: Optional title from the GUI overriding the parsed one.
    """
    cfg = _load_cfg(category, author)
    data = parse_bbcode_ai(bbcode, cfg.get("prompt", DEFAULT_PROMPT))

    final_title = thread_title or data["title"]

    filled = (
        cfg["template"]
        .replace("{TITLE}", final_title)
        .replace("{COVER}", data["cover"])
        .replace("{DESC}", data["desc"])
        .replace("{BODY}", data["body"])
    )

    # Leave the {LINKS} placeholder untouched so that the caller can insert
    # freshly uploaded links (via the SettingsWidget template) later on.
    if "{LINKS}" not in cfg["template"]:
        links_block = "\n".join(data.get("links", []))
        if links_block:
            if filled and not filled.endswith("\n"):
                filled += "\n"
            filled += links_block

def convert(thread: dict, apply_hooks: bool = True) -> str:
    category = str(thread.get("category", "")).lower()
    author = thread.get("author", "")
    bbcode = thread.get("bbcode_original") or ""
    if not category or not author:
        return bbcode
    bbcode = apply_template(bbcode, category, author)

    # Replace the {LINKS} placeholder using the user's template and the
    # uploaded links associated with this thread.  If no links exist yet,
    # insert a placeholder so that the caller can update it later.
    if "{LINKS}" in bbcode:
        try:
            from utils import apply_links_template, LINK_TEMPLATE_PRESETS
            from core.user_manager import get_user_manager

            links_dict = thread.get("links", {}) or {}
            user_mgr = get_user_manager()
            template = user_mgr.get_user_setting("links_template", LINK_TEMPLATE_PRESETS[0])
            links_block = apply_links_template(template, links_dict).strip()
        except Exception:
            links_block = ""

        if not links_block:
            links_block = "[LINKS TBD]"
        bbcode = bbcode.replace("{LINKS}", links_block)

    if apply_hooks:
        img_hook = _HOOKS.get("rewrite_images")
        if img_hook:
            bbcode = img_hook(bbcode)
        link_hook = _HOOKS.get("rewrite_links")
        if link_hook:
            bbcode = link_hook(bbcode)
    return bbcode

# ★ header merged (author-title) & desc flexible (size/format order) ★
import json
import os
from pathlib import Path
from config.config import DATA_DIR
from utils.utils import sanitize_filename
import logging
from dotenv import load_dotenv, find_dotenv
import re

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

def _collect_file_sizes(text: str) -> list:
    """Extract all file sizes from ``text``.

    Recognizes numbers followed by KB, MB or GB (case-insensitive) and returns
    a list of sizes normalized to megabytes.  Bitrate indicators such as
    ``kbps`` or ``MB/s`` are ignored.
    """
    pattern = re.compile(r"(\d+(?:[.,]\d+)?)\s*(KB|MB|GB)(?!\s*(?:ps|/s))", re.IGNORECASE)
    sizes = []
    for num, unit in pattern.findall(text):
        try:
            value = float(num.replace(',', '.'))
            unit = unit.upper()
            if unit == "KB":
                value /= 1024
            elif unit == "GB":
                value *= 1024
            sizes.append(value)
        except Exception:
            continue
    return sizes


def _inject_total_size(bbcode: str, desc: str) -> str:
    """Replace the ``Größe:`` line in ``desc`` with the total size from ``bbcode``.

    The total is expressed in megabytes if below one gigabyte, otherwise in
    gigabytes with one decimal place.  When no file sizes are detected the
    original description is returned unchanged.
    """
    sizes = _collect_file_sizes(bbcode)
    if not sizes:
        return desc

    total_mb = sum(sizes)
    if total_mb >= 1024:
        total = f"{total_mb / 1024:.1f} GB"
    else:
        total = f"{int(round(total_mb))} MB"

    lines = desc.splitlines()
    out = []
    replaced = False
    for line in lines:
        if not replaced and line.strip().lower().startswith("größe:"):
            out.append(f"Größe: {total}")
            replaced = True
        else:
            out.append(line)
    return "\n".join(out)
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

def _prompt_path() -> Path:
    return TEMPLAB_DIR / "prompt.txt"


def load_global_prompt() -> str:
    """Return the saved global prompt or the built-in default."""
    try:
        txt = _prompt_path().read_text(encoding="utf-8")
        return txt or DEFAULT_PROMPT
    except Exception:
        return DEFAULT_PROMPT


def save_global_prompt(prompt: str) -> None:
    """Persist a new global prompt to disk."""
    path = _prompt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(prompt)
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
    cat_template = get_unified_template(category)
    cat_prompt = load_category_prompt(category)
    if path.exists():
        try:
            data = json.load(open(path, "r", encoding="utf-8"))
            if isinstance(data, list):  # backward compatibility
                data = {"template": cat_template, "prompt": cat_prompt, "threads": data}
            data.setdefault("template", cat_template)
            data.setdefault("prompt", cat_prompt)
            data.setdefault("threads", {})
            return data
        except Exception:
            pass
    return {"template": cat_template, "prompt": cat_prompt, "threads": {}}


def _save_cfg(category: str, author: str, data: dict) -> None:
    path = _cfg_path(category, author)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    cb = _HOOKS.get("reload_tree")
    if cb:
        try:
            cb()
        except Exception:
            pass
# ------------------------------------------------------------------
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
    js["desc"] = _inject_total_size(bbcode, js["desc"])
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

def _category_prompt_path(category: str) -> Path:
    return TEMPLAB_DIR / f"{sanitize_filename(category)}.prompt"

def load_category_prompt(category: str) -> str:
    path = _category_prompt_path(category)
    if path.exists():
        try:
            txt = path.read_text(encoding="utf-8")
            return txt or load_global_prompt()
        except Exception:
            pass
        return load_global_prompt()

    return load_global_prompt()

def save_category_prompt(category: str, prompt: str) -> None:
    path = _category_prompt_path(category)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt, encoding="utf-8")


def save_category_template_prompt(category: str, template: str, prompt: str) -> None:
    """Persist a template/prompt for a whole category and propagate to all authors."""

    save_unified_template(category, template)
    save_category_prompt(category, prompt)

    cat_dir = USERS_DIR / sanitize_filename(category)
    if not cat_dir.exists():
        return
    for file in cat_dir.glob("*.json"):
        try:
            data = json.load(open(file, "r", encoding="utf-8"))
        except Exception:
            data = {}
        if isinstance(data, list):
            data = {"threads": data}
        data["template"] = template
        data["prompt"] = prompt
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    cb = _HOOKS.get("reload_tree")
    if cb:
        try:
            cb()
        except Exception:
            pass

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


def apply_template(
    bbcode: str,
    category: str,
    author: str,
    *,
    thread_title: str = "",
) -> str:
    """Fill the template with parsed data, then sanitize output for forum safety."""
    cfg = _load_cfg(category, author)
    prompt = cfg.get("prompt", load_global_prompt())
    data = parse_bbcode_ai(bbcode, prompt)

    final_title = thread_title or data["title"]

    # Build header (author + title if available)
    header = final_title.strip()
    author_name = cfg.get("author_name") or author or ""
    if author_name and author_name.lower() not in header.lower():
        header = f"{author_name} — {header}".strip(" —")

    # Compose description/body with flexible order (keep existing behavior)
    desc = data.get("desc", "").strip()
    body = data.get("body", "").strip()

    # Load template for this (category, author)
    template: str = cfg.get("template", "") or "{TITLE}\n\n{COVER}\n\n{DESC}\n\n{BODY}\n\n{LINKS}"

    # Fill basic placeholders (leave {LINKS} for later replacement by caller/convert)
    filled = (
        template.replace("{TITLE}", header)
        .replace("{COVER}", data.get("cover", "").strip())
        .replace("{DESC}", desc)
        .replace("{BODY}", body)
    )

    # If template does not contain {LINKS}, but AI parsed links, append them as raw fallback
    if "{LINKS}" not in filled:
        raw_links = "\n".join(data.get("links", []) or [])
        if raw_links:
            filled += "\n\n" + raw_links

    # Forum safety & cosmetics:
    #  - replace forbidden/special characters (e.g. ‖) with safe dash
    #  - normalize BBCode font size: [size=2] → [size=3]
    #  - never mutate URLs inside [url]...[/url] or bare http(s):// links
    def _protect_urls(text: str) -> tuple[str, dict]:
        repl = {}
        idx = 0

        def _stash(s: str) -> str:
            nonlocal idx
            key = f"__URL_PLACEHOLDER_{idx}__"
            repl[key] = s
            idx += 1
            return key

        # [url]...[/url] blocks
        text = re.sub(r"\[url(?:=[^\]]+)?\].*?\[/url\]", lambda m: _stash(m.group(0)), text, flags=re.I | re.S)
        # Bare http(s)://… sequences
        text = re.sub(r"https?://[^\s\]]+", lambda m: _stash(m.group(0)), text, flags=re.I)
        return text, repl

    def _restore_urls(text: str, repl: dict) -> str:
        for k, v in repl.items():
            text = text.replace(k, v)
        return text

    def _sanitize_specials(text: str) -> str:
        mapping = {
            "‖": "-", "–": "-", "—": "-", "−": "-",
            "•": "-", "●": "-", "►": "-", "▪": "-",
            "│": "|", "¦": "|",
            "…": "...", "⋯": "...",
            "\u00A0": " ",  # non-breaking space
        }
        for bad, good in mapping.items():
            text = text.replace(bad, good)
        # collapse multiple spaces/dashes
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"-{3,}", "--", text)
        return text

    def _bump_font_sizes(text: str) -> str:
        # [size=2] or [size="2"] → [size=3]
        text = re.sub(r"\[size\s*=\s*['\"]?2['\"]?\s*\]", "[size=3]", text, flags=re.I)
        text = re.sub(r"\[/size\]", "[/size]", text)  # idempotent, keeps tag
        return text

    tmp, stash = _protect_urls(filled)
    tmp = _sanitize_specials(tmp)
    tmp = _bump_font_sizes(tmp)
    filled = _restore_urls(tmp, stash)

    return filled


def convert(thread: dict, apply_hooks: bool = True) -> str:
    import re

    category = str(thread.get("category", "")).lower()
    author = thread.get("author", "")
    bbcode = thread.get("bbcode_original") or ""
    if not category or not author:
        return bbcode

    bbcode = apply_template(bbcode, category, author, thread_title=thread.get("title", ""))

    # احذف أى بلوكات روابط قديمة لتجنب التكرار
    def _strip_old_links(text: str) -> str:
        patterns = [
            r"\[LINKS START\][\s\S]*?\[LINKS END\]",
            r"\n\[b\]\s*(?:links|download links|روابط التحميل)\s*\[/b\][\s\S]*?$",
            r"\n\[center\]\s*\[size=\d+\]\s*\[b\]\s*(?:links|download links|روابط التحميل)\s*\[/b\]\s*\[/size\]\s*\[/center\][\s\S]*?$",
        ]
        for pat in patterns:
            text = re.sub(pat, "", text, flags=re.I | re.M)
        return text

    # أعد بناء كتلة الروابط فقط من المضيفين اللى ليهم URLs فعلاً
    links_block = ""
    try:
        # prune أى فراغات فى الداتا
        def _prune(o):
            if isinstance(o, dict):
                d = {k: _prune(v) for k, v in o.items()}
                return {k: v for k, v in d.items() if v not in (None, "", [], {})}
            if isinstance(o, (list, tuple, set)):
                return [x for x in o if x]
            return o

        links_dict = _prune(thread.get("links", {}) or {})
    except Exception:
        links_dict = {}

    has_grouped = isinstance(links_dict, dict) and any(
        k in links_dict for k in ("audio", "ebook")
    )
    if "{LINKS}" in bbcode or has_grouped:
        try:
            from utils import apply_links_template, LINK_TEMPLATE_PRESETS  # :contentReference[oaicite:0]{index=0}
            from core.user_manager import get_user_manager
            user_mgr = get_user_manager()
            template = user_mgr.get_user_setting("links_template", LINK_TEMPLATE_PRESETS[0])
            raw_block = apply_links_template(template, links_dict) or ""
        except Exception:
            raw_block = ""

        # تنظيف بسيط: إزالة [url=] الفارغة/الفواصل اليتيمة + تكبير حجم الخط
        def _strip_empty_urls(t: str) -> str:
            t = re.sub(r"\[url=\s*\](.*?)\[/url\]", r"\1", t, flags=re.I | re.S)
            t = re.sub(r"\[url\]\s*\[/url\]", "", t, flags=re.I | re.S)
            return t
        def _bump(t: str) -> str:
            return re.sub(r"(?i)\[size\s*=\s*2\]", "[size=3]", t)

        lb = _strip_old_links(raw_block)
        lb = _strip_empty_urls(lb)
        lb = _bump(lb).strip()
        links_block = lb or "[LINKS TBD]"

        bbcode = _strip_old_links(bbcode)
        if "{LINKS}" in bbcode:
            bbcode = bbcode.replace("{LINKS}", links_block)
        elif links_block:
            bbcode = bbcode.rstrip() + ("\n\n" + links_block)

    if apply_hooks:
        img_hook = _HOOKS.get("rewrite_images")
        if img_hook:
            bbcode = img_hook(bbcode)
        link_hook = _HOOKS.get("rewrite_links")
        if link_hook:
            bbcode = link_hook(bbcode)

    # تعقيم عام لسلامة المنتدى
    def _protect_urls(text: str) -> tuple[str, dict]:
        repl = {}
        idx = 0
        def _stash(m):
            nonlocal idx
            key = f"__URL_PLACEHOLDER_{idx}__"
            repl[key] = m.group(0)
            idx += 1
            return key
        text = re.sub(r"\[url(?:=[^\]]+)?\].*?\[/url\]", _stash, text, flags=re.I | re.S)
        text = re.sub(r"https?://[^\s\]]+", _stash, text, flags=re.I)
        return text, repl
    def _restore_urls(text: str, repl: dict) -> str:
        for k, v in repl.items():
            text = text.replace(k, v)
        return text
    def _sanitize_specials(text: str) -> str:
        text = text.replace("‖", "-").replace("\u00A0", " ")
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"(\s*[\|\–—]+\s*){2,}", " - ", text)
        text = re.sub(r"\s*-\s*", " - ", text)
        text = re.sub(r"(?:\s*-\s*){2,}", " - ", text)
        text = re.sub(r"\s*-\s*$", "", text)
        return text
    def _bump_sizes(text: str) -> str:
        return re.sub(r"(?i)\[size\s*=\s*['\"]?2['\"]?\s*\]", "[size=3]", text)

    tmp, stash = _protect_urls(bbcode)
    tmp = _sanitize_specials(tmp)
    tmp = _bump_sizes(tmp)
    bbcode = _restore_urls(tmp, stash)
    return bbcode





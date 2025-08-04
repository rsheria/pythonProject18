# ★ header merged (author-title) & desc flexible (size/format order) ★
import json
import os, json, re
from pathlib import Path
from config.config import DATA_DIR
from utils.utils import sanitize_filename
import logging
from dotenv import load_dotenv, find_dotenv

# Ensure environment variables from .env are loaded before accessing them
load_dotenv(find_dotenv())

# ------------------------------------------------------------------
# Directories
# OpenAI client (handles both legacy and new SDKs)
# ------------------------------------------------------------------
_OPENAI_CLIENT = None
_API_KEY = os.getenv("OPENAI_API_KEY")
try:
    from openai import OpenAI  # type: ignore

    if _API_KEY:
        _OPENAI_CLIENT = OpenAI(api_key=_API_KEY)
except Exception:  # pragma: no cover - fallback for missing dependency
    try:  # legacy `openai` package (<1.x)
        import openai  # type: ignore

        if _API_KEY:
            openai.api_key = _API_KEY
            _OPENAI_CLIENT = openai
    except Exception:
        _OPENAI_CLIENT = None

# ------------------------------------------------------------------
# Directories
# ------------------------------------------------------------------

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

def parse_bbcode_ai(raw: str) -> dict:
    """Return dict with keys title, cover, desc, body, links."""
    # Truncate excessively long posts after the download section
    if len(raw) > 28000:
        idx = raw.lower().find('[download')
        if idx != -1:
            raw = raw[:idx]

    if not _OPENAI_CLIENT:
        raise json.JSONDecodeError('missing api key', raw, 0)

    sys = (
        'You are a strict BBCode parser. '
        'Return ONLY valid JSON that matches this schema: '
        '{"title":string,"cover":string|null,"desc":string|null,'
        '"body":string|null,"links":[string]}'
        ' If a field does not exist use null or [] accordingly.'
    )

    messages = [
        {"role": "system", "content": sys},
        {"role": "user", "content": raw},
    ]
    logging.info('🧠 Parsing BBCode via OpenAI')
    try:
        if hasattr(_OPENAI_CLIENT, 'chat'):
            rsp = _OPENAI_CLIENT.chat.completions.create(
                model='gpt-4o-mini',
                temperature=0,
                max_tokens=300,
                messages=messages,
            )
            content = rsp.choices[0].message.content
        else:
            rsp = _OPENAI_CLIENT.ChatCompletion.create(
                model='gpt-3.5-turbo-0125',
                temperature=0,
                max_tokens=300,
                messages=messages,
            )
            choice = rsp.choices[0]
            message = choice['message'] if isinstance(choice, dict) else choice.message
            content = message['content'] if isinstance(message, dict) else message.content
    except Exception as e:
        raise json.JSONDecodeError(str(e), raw, 0)

    return json.loads(content)
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
            # النمط يعيد أربع مجموعات؛ اثنتان منهما None حسب الترتيب
            groups["format"] = m.group(1) or m.group(4)
            groups["size"] = m.group(2) or m.group(3)
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

def apply_template(bbcode: str, template: str, regexes: dict) -> str:
    """Parse BBCode via AI and fill the template. Fallback to regex."""
    try:
        ai = parse_bbcode_ai(bbcode)
    except Exception:
        logging.exception("AI parsing failed; using regex fallback")
        return _apply_template_regex(bbcode, template, regexes)

    filled = (
        template
        .replace("{TITLE}", ai.get("title", ""))
        .replace("{COVER}", f"[IMG]{ai['cover']}[/IMG]" if ai.get("cover") else "")
        .replace("{DESC}", ai.get("desc", ""))
        .replace("{BODY}", ai.get("body", ""))
        .replace("{LINKS}", "\n".join(ai.get("links", [])))
    ).strip()

    return filled
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
    bbcode = apply_template(bbcode, template, regexes)

    # ------------------------------------------------------------------
    # Replace common placeholders before applying hooks
    # ------------------------------------------------------------------
    if "{TITLE}" in bbcode:
        bbcode = bbcode.replace("{TITLE}", title)

    if apply_hooks:
        img_hook = _HOOKS.get("rewrite_images")
        if img_hook:
            bbcode = img_hook(bbcode)
        link_hook = _HOOKS.get("rewrite_links")
        if link_hook:
            bbcode = link_hook(bbcode)
    return bbcode

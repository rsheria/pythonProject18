# ★ header merged (author-title) & desc flexible (size/format order) ★
import json
import os
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
    """Fill the template with parsed data.

    thread_title: Optional title from the GUI overriding the parsed one.
    """
    cfg = _load_cfg(category, author)
    prompt = cfg.get("prompt", load_global_prompt())
    data = parse_bbcode_ai(bbcode, prompt)

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
    return filled
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

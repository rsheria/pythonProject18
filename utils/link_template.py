"""Utilities for applying user-defined link templates."""
from typing import Any, List, Dict
import re

# ---------------------------------------------------------------------------
# Built-in link template presets that can be selected from the settings UI.
# "{PART}" (لو مستخدمه) مش بنستعملها هنا، لكن سايبينها في الـ presets للرجوع.
# ---------------------------------------------------------------------------
LINK_TEMPLATE_PRESETS: List[str] = [
    (
        "[center][size=3][b]DOWNLOAD LINKS[/b][/size]\n\n"
        "[url={LINK_KEEP}]Keeplinks[/url] ‖ "
        "[url={LINK_DDL}]DDownload[/url] ‖ "
        "[url={LINK_RG}]Rapidgator[/url] ‖ "
        "[url={LINK_KF}]Katfile[/url] ‖ "
        "[url={LINK_NF}]Nitroflare[/url]\n"
        "[/center]"
    ),
    "RG: {LINK_RG}\nNF: {LINK_NF}\nDDL: {LINK_DDL}\nKF: {LINK_KF}\nKeep: {LINK_KEEP}",
    "[url={LINK_RG}]RG[/url] | [url={LINK_NF}]NF[/url] | {LINK_DDL}",
    "RG {PART}: {LINK_RG}\nNF {PART}: {LINK_NF}\nDDL {PART}: {LINK_DDL}",
    "{LINK_RG}\n{LINK_NF}\n{LINK_DDL}\n{LINK_KF}",
    "[b]RG[/b]: {LINK_RG}\n[b]NF[/b]: {LINK_NF}",
    "[url={LINK_KEEP}]Keep[/url]\n[url={LINK_RG}]RG {PART}[/url]\n[url={LINK_NF}]NF {PART}[/url]",
    "Download:\n{LINK_RG}\n{LINK_NF}\n{LINK_MEGA}",
    "[center]{LINK_KEEP}\n{LINK_RG}\n{LINK_NF}\n{LINK_DDL}[/center]",
    "RG: {LINK_RG} | NF: {LINK_NF} | KF: {LINK_KF} | MEGA: {LINK_MEGA}",
]

# ----------------------------- helpers -------------------------------------

def _as_list(v: Any) -> List[str]:
    """يحّول أى مدخل لقائمة URLs نصّية (يدعم dict {'urls': [...]})."""
    if not v:
        return []
    # dict: التكوين الجديد من الرفع
    if isinstance(v, dict):
        v = v.get("urls") or v.get("url") or v.get("link") or []
    # list/tuple/set: فلّط أى عناصر داخلها برضه dict
    if isinstance(v, (list, tuple, set)):
        out: List[str] = []
        for x in v:
            if isinstance(x, dict):
                out.extend(_as_list(x))
            elif x:
                out.append(str(x))
        return out
    # عنصر مفرد
    return [str(v)]

def _uniq_keep_order(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

# بنسمّي التوكنز الثابتة اللي التيمبلت بيعتمد عليها
HOST_TOKENS = {
    "ddownload":  "DDL",
    "rapidgator": "RG",
    "katfile":    "KF",
    "nitroflare": "NF",
    "mega":       "MEGA",
    "keeplinks":  "KEEP",
}

HOST_LABELS = {
    "ddownload":  "DDownload",
    "rapidgator": "Rapidgator",
    "katfile":    "Katfile",
    "nitroflare": "Nitroflare",
    "mega":       "MEGA",
    "keeplinks":  "Keeplinks",
}

HOST_ORDER = ["ddownload", "rapidgator", "katfile", "nitroflare", "mega"]

def _guess_host_from_url(url: str) -> str:
    u = url.lower()
    if "rapidgator" in u: return "rapidgator"
    if "ddownload"  in u or "//ddl" in u: return "ddownload"
    if "katfile"    in u: return "katfile"
    if "nitroflare" in u: return "nitroflare"
    if "mega.nz"    in u or "mega.co.nz" in u: return "mega"
    if "keeplinks"  in u: return "keeplinks"
    return ""

def _normalize_links_dict(links_dict: Dict[Any, Any]) -> Dict[str, List[str]]:
    """
    يوحّد المفاتيح ويستخرج الروابط مع تجاهل Rapidgator الباك-أب.
    يقبل شكل: {'rapidgator': {'urls':[...], 'is_backup': False}, 'rapidgator_backup': {...}, ...}
    أو أى مفاتيح/قيم قديمة.
    """
    out: Dict[str, List[str]] = {k: [] for k in HOST_TOKENS.keys()}  # ddownload/rapidgator/katfile/nitroflare/mega/keeplinks

    for k, vals in (links_dict or {}).items():
        key = str(k).lower()
        # فلتر باك-أب RG من المصدر
        is_rg_backup = ("rapidgator" in key and ("backup" in key or key.endswith("_bak") or key.endswith("_backup")))
        # اسحب urls بصرف النظر عن الشكل
        urls = _as_list(vals)

        # صنّف كل URL حسب الدومين
        classified_any = False
        for url in urls:
            host = _guess_host_from_url(url)
            if not host:
                continue
            # تجاهل RG الباك-أب
            if host == "rapidgator":
                # لو val dict فيه is_backup=True أو المفتاح بيدل على backup → تجاهل
                v_is_backup = isinstance(vals, dict) and bool(vals.get("is_backup"))
                if is_rg_backup or v_is_backup:
                    continue
            out[host].append(url)
            classified_any = True

        # لو ما قدرناش نصنّف من الURLs (نادر)؛ جرّب من اسم المفتاح
        if not classified_any and urls:
            def add(host_name: str):
                if host_name == "rapidgator" and is_rg_backup:
                    return
                out[host_name].extend(urls)

            if "rapidgator" in key or key in ("rg", "link_rg"):
                add("rapidgator")
            elif "ddownload" in key or key in ("ddl", "link_ddl", "dd"):
                add("ddownload")
            elif "katfile" in key or key in ("kf", "link_kf"):
                add("katfile")
            elif "nitroflare" in key or key in ("nf", "link_nf"):
                add("nitroflare")
            elif "mega" in key:
                add("mega")
            elif "keeplink" in key or "keeplinks" in key or key in ("keep", "link_keep"):
                add("keeplinks")

    # نظّف تكرارات مع الحفاظ على الترتيب
    for h in out:
        out[h] = _uniq_keep_order(out[h])
    return out

def _strip_host_placeholder(line: str, token: str) -> str:
    """
    يشيل [url={LINK_TOKEN}]...[/url] + أي فواصل شائعة حواليها (‖ أو | أو - أو •).
    """
    sep = r"[‖\|\-•·]"
    pat = r"\s*(?:%s\s*)?\[url=\{LINK_%s\}\][^\[]*?\[/url\]\s*(?:%s\s*)?" % (sep, token, sep)
    line = re.sub(pat, " ", line)
    # ولو placeholder جيه لوحده من غير [url=...] (نادر)
    line = line.replace("{LINK_%s}" % token, "")
    return line

def _cleanup_separators(s: str) -> str:
    # وحّد الفواصل المتكررة أو المتبقية
    s = re.sub(r"(?:\s*[‖\|\-•·]\s*){2,}", " ‖ ", s)
    s = re.sub(r"^\s*[‖\|\-•·]\s*|\s*[‖\|\-•·]\s*$", "", s)
    # مسافات زيادة
    return re.sub(r"[ \t]+\n", "\n", s).strip()

def _append_multi_block(blocks: List[str], label: str, urls: List[str]) -> None:
    parts = " ‖ ".join("[url=%s]%02d[/url]" % (u, i + 1) for i, u in enumerate(urls))
    blocks.append(f"[center][size=3][b]{label}:[/b] {parts}[/size][/center]")

# ----------------------------- main API ------------------------------------

def apply_links_template(template: str, links: dict) -> str:
    """
    ذكي لتجهيز كتلة الروابط مع احترام التيمبلت المحفوظ:

      • يدعم وضعين للتيمبلت:
        (أ) وضع التوكنز البسيط: يستبدل {LINK_RG}/{LINK_DDL}/... داخل
            وسوم [url=...] ويشيل المضيفين اللى مفيش لهم روابط بالكامل.
        (ب) وضع الأقسام: {AUDIO}/{EBOOK}/{EPISODES} + {LINKS} المجمّع.

      • يرتّب المضيفين حسب utils/host_priority.py
      • يخفى أى مضيف مفيهوش روابط فعلية.
      • لا يلمس عناوين الـ URLs إطلاقاً (يحميها أثناء التعقيم).
      • يستبدل الرموز الممنوعة (‖ → -) ويرفع [size=2] إلى [size=3].
      • يتعامل مع Keeplinks كرابط واحد (من غير ترقيم أحرف!).

    يقبل أشكال links المختلفة (المسطّح/المجمّع/الكانوني).
    """
    import re
    from collections import defaultdict

    # ---------- إعدادات ورموز المضيفين ----------
    HOST_TOKENS = {
        "ddownload":  "DDL",
        "rapidgator": "RG",
        "katfile":    "KF",
        "nitroflare": "NF",
        "mega":       "MEGA",
        "keeplinks":  "KEEP",
    }
    HOST_LABELS = {
        "ddownload":  "DDownload",
        "rapidgator": "Rapidgator",
        "katfile":    "Katfile",
        "nitroflare": "Nitroflare",
        "mega":       "MEGA",
    }

    # ترتيب المضيفين (لو متاح)
    HOST_ORDER: list[str] = []
    try:
        from .host_priority import get_host_priority  # type: ignore
        try:
            HOST_ORDER = list(get_host_priority())
        except Exception:
            HOST_ORDER = []
    except Exception:
        try:
            from .host_priority import HOST_PRIORITY  # type: ignore
            HOST_ORDER = list(HOST_PRIORITY)
        except Exception:
            HOST_ORDER = []
    HOST_INDEX = {h: i for i, h in enumerate(HOST_ORDER)}
    def _norm_host(h: str) -> str:
        h = (h or "").lower()
        if "rapidgator" in h: return "rapidgator"
        if "ddownload"  in h or h == "ddl": return "ddownload"
        if "katfile"    in h: return "katfile"
        if "nitroflare" in h: return "nitroflare"
        if "mega"       in h: return "mega"
        if "keeplink"   in h or "keeplinks" in h: return "keeplinks"
        return h
    def _sort_hosts(keys: list[str]) -> list[str]:
        return sorted(keys, key=lambda k: HOST_INDEX.get(_norm_host(k), 10_000))

    # ---------- حماية الروابط أثناء التعقيم ----------
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
        mapping = {"‖": "-", "–": "-", "—": "-", "−": "-", "\u00A0": " "}
        for bad, good in mapping.items():
            text = text.replace(bad, good)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"(\s*[\|\-]\s*){2,}", " - ", text)
        text = re.sub(r"\s*-\s*", " - ", text)
        text = re.sub(r"(?:\s*-\s*){2,}", " - ", text)
        text = re.sub(r"\s*-\s*$", "", text)
        return text
    def _bump_font_sizes(text: str) -> str:
        return re.sub(r"(?i)\[size\s*=\s*['\"]?2['\"]?\s*\]", "[size=3]", text)

    # ---------- توحيد links إلى شكل مفهوم ----------
    # نحاول أولاً الاستفادة من الشكل الكانوني لو متوفر (rapidgator.net…)
    canon: dict[str, list[str]] = {}
    if isinstance(links, dict):
        for k, v in links.items():
            key = _norm_host(str(k))
            if key == "keeplinks":
                # نخزّنه منفصل (سلسلة واحدة)
                canon["keeplinks"] = [v] if v else []
                continue
            # v ممكن يكون list/tuple/dict/str
            urls: list[str] = []
            if isinstance(v, (list, tuple, set)):
                for x in v:
                    if isinstance(x, dict):
                        for kk in ("urls", "url", "link"):
                            if kk in x and x[kk]:
                                val = x[kk]
                                if isinstance(val, (list, tuple, set)):
                                    urls += [str(u) for u in val if u]
                                elif val:
                                    urls.append(str(val))
                    elif x:
                        urls.append(str(x))
            elif isinstance(v, dict):
                val = v.get("urls") or v.get("url") or v.get("link")
                if isinstance(val, (list, tuple, set)):
                    urls += [str(u) for u in val if u]
                elif val:
                    urls.append(str(val))
            elif v:
                urls.append(str(v))
            if urls:
                canon.setdefault(key, [])
                canon[key] += [u for u in urls if u]

    # ---------- وضع (أ): استبدال توكنز {LINK_*} إن وُجدت ----------
    has_token_mode = any(("{LINK_" in template) for _ in (0,))
    if has_token_mode:
        host_values: dict[str, list[str]] = {}
        for host, tok in HOST_TOKENS.items():
            if host == "keeplinks":
                host_values[host] = canon.get("keeplinks") or []
            else:
                host_values[host] = canon.get(host) or []

        def _strip_host_placeholder(line: str, token: str) -> str:
            sep = r"[‖\|\-•·]"
            pat = r"\s*(?:%s\s*)?\[url=\{LINK_%s\}\][^\[]*?\[/url\]\s*(?:%s\s*)?" % (sep, token, sep)
            line = re.sub(pat, " ", line, flags=re.I)
            line = line.replace("{LINK_%s}" % token, "")
            line = re.sub(r"(?:\s*%s\s*){2,}" % sep, " - ", line)
            line = re.sub(r"^\s*%s\s*|\s*%s\s*$" % (sep, sep), "", line)
            return re.sub(r"[ \t]{2,}", " ", line).strip()

        out_lines: list[str] = []
        if "{PART}" in template:
            max_parts = max(
                [len(v) for h, v in host_values.items() if h != "keeplinks"]
                or [1]
            )
            for part in range(max_parts):
                for ln in template.splitlines():
                    changed = ln.replace("{PART}", str(part + 1))
                    for host, tok in HOST_TOKENS.items():
                        placeholder = "{LINK_%s}" % tok
                        if placeholder in changed:
                            urls = host_values.get(host, [])
                            if part < len(urls):
                                changed = changed.replace(placeholder, urls[part])
                            else:
                                changed = _strip_host_placeholder(changed, tok)
                    out_lines.append(changed)
        else:
            token_value = {
                tok: (vals[0] if vals else "")
                for host, tok in HOST_TOKENS.items()
                for vals in (host_values.get(host, []),)
            }
            for ln in template.splitlines():
                changed = ln
                for host, tok in HOST_TOKENS.items():
                    placeholder = "{LINK_%s}" % tok
                    if placeholder in changed:
                        val = token_value.get(tok, "")
                        if val:
                            changed = changed.replace(placeholder, val)
                        else:
                            changed = _strip_host_placeholder(changed, tok)
                out_lines.append(changed)

        result = "\n".join(out_lines)

        tmp, stash = _protect_urls(result)
        tmp = _sanitize_specials(tmp)
        tmp = _bump_font_sizes(tmp)
        result = _restore_urls(tmp, stash)
        return result.strip()

    # ---------- وضع (ب): الأقسام الذكية ----------
    # نبنى هيكل مجمّع: Audio/E-Book/Episodes/Other (لو مستخدم بيبعته)
    def _render_host_block(host: str, url_list: list[str]) -> str:
        if not url_list:
            return ""
        token = HOST_TOKENS.get(_norm_host(host), host)
        parts = []
        for i, u in enumerate(url_list, 1):
            label = token if i == 1 else f"{token}-{i}"
            parts.append(f"[url={u}]{label}[/url]")
        return " ‖ ".join(parts)

    # نحاول قراءة الصيغ/الأجزاء إن كانت موجودة
    def _normalize_grouped(src: dict) -> dict:
        out = {
            "audio": defaultdict(list),
            "ebook": defaultdict(lambda: defaultdict(list)),
            "episodes": defaultdict(lambda: defaultdict(list)),
            "other": defaultdict(list),
        }
        have_grouped = False
        if isinstance(src, dict):
            if any(k in src for k in ("audio", "ebook", "episodes", "mirrors")):
                have_grouped = True
        if not have_grouped:
            # fallback: اعرض كل المضيفين المتاحة كمرايات "other"
            for host, urls in (canon or {}).items():
                if host == "keeplinks":
                    continue
                if urls:
                    out["other"][host].extend(urls)
            return out

        # Grouped paths (لو اتبعت بهذا الشكل)
        audio = (src.get("audio") or {}) if isinstance(src, dict) else {}
        for host, urls in (audio.items() if isinstance(audio, dict) else []):
            if urls:
                out["audio"][host].extend([u for u in urls if u])

        ebook = (src.get("ebook") or {}) if isinstance(src, dict) else {}
        for fmt, by_host in (ebook.items() if isinstance(ebook, dict) else []):
            for host, urls in (by_host.items() if isinstance(by_host, dict) else []):
                if urls:
                    out["ebook"][str(fmt).upper()][host].extend([u for u in urls if u])

        episodes = (src.get("episodes") or {}) if isinstance(src, dict) else {}
        for label, by_host in (episodes.items() if isinstance(episodes, dict) else []):
            for host, urls in (by_host.items() if isinstance(by_host, dict) else []):
                if urls:
                    out["episodes"][label][host].extend([u for u in urls if u])

        mirrors = (src.get("mirrors") or {}) if isinstance(src, dict) else {}
        for host, urls in (mirrors.items() if isinstance(mirrors, dict) else []):
            if urls:
                out["other"][host].extend([u for u in urls if u])

        return out

    grouped = _normalize_grouped(links or {})

    def _render_section(title: str, mapping: dict) -> str:
        lines = [f"[size=3][b]{title}[/b][/size]"]
        any_line = False
        for host in _sort_hosts(list(mapping.keys())):
            block = _render_host_block(host, mapping[host])
            if block:
                lines.append(f"[center]{block}[/center]")
                any_line = True
        return "\n".join(lines) if any_line else ""

    audio_block = _render_section("Hörbuch", grouped["audio"])
    # E-Book مع كل صيغة على حدة
    ebook_block = ""
    if grouped["ebook"]:
        parts = ["[size=3][b]E-Book[/b][/size]"]
        for fmt in sorted(grouped["ebook"].keys()):
            parts.append(f"[b]{fmt}[/b]")
            by_host = grouped["ebook"][fmt]
            for host in _sort_hosts(list(by_host.keys())):
                block = _render_host_block(host, by_host[host])
                if block:
                    parts.append(f"[center]{block}[/center]")
        ebook_block = "\n".join(parts)

    episodes_block = ""
    if grouped["episodes"]:
        parts = ["[size=3][b]Episoden[/b][/size]"]
        for label in sorted(grouped["episodes"].keys()):
            parts.append(f"[b]{label}[/b]")
            by_host = grouped["episodes"][label]
            for host in _sort_hosts(list(by_host.keys())):
                block = _render_host_block(host, by_host[host])
                if block:
                    parts.append(f"[center]{block}[/center]")
        episodes_block = "\n".join(parts)

    mirrors_block = ""
    if grouped["other"]:
        # لو مفيش Audio/Ebook/Episodes استعمل المرايات كبديل
        parts = []
        for host in _sort_hosts(list(grouped["other"].keys())):
            block = _render_host_block(host, grouped["other"][host])
            if block:
                parts.append(f"[center]{block}[/center]")
        mirrors_block = "\n".join(parts)

    result = template
    has_explicit = any(p in template for p in ("{AUDIO}", "{EBOOK}", "{EPISODES}", "{LINKS}"))
    if has_explicit:
        result = result.replace("{AUDIO}", audio_block)
        result = result.replace("{EBOOK}", ebook_block)
        result = result.replace("{EPISODES}", episodes_block)
        combined = "\n\n".join([b for b in (audio_block, ebook_block, episodes_block) if b.strip()]) or mirrors_block
        result = result.replace("{LINKS}", combined)
    else:
        combined = "\n\n".join([b for b in (audio_block, ebook_block, episodes_block) if b.strip()]) or mirrors_block
        if combined.strip():
            header_lines = []
            keepl = canon.get("keeplinks") or []
            if keepl:
                header_lines.append(
                    f"[center][size=3][url={keepl[0]}]Keeplinks[/url][/size][/center]"
                )
            header_lines.append("[center][size=3][b]Download-Links[/b][/size][/center]")
            header_lines.append(combined)
            combined = "\n".join(header_lines)
        result = result.rstrip() + ("\n\n" + combined if combined.strip() else "")

    # تنظيف أخير
    tmp, stash = _protect_urls(result)
    tmp = re.sub(r"\[center\]\s*\[/center\]", "", tmp, flags=re.I)
    tmp = re.sub(r"(\n\s*){3,}", "\n\n", tmp)
    tmp = _sanitize_specials(tmp)
    tmp = _bump_font_sizes(tmp)
    result = _restore_urls(tmp, stash)
    result = result.replace("Download - Links", "Download-Links")
    result = result.replace("E - Book", "E-Book")
    return result.strip()

# ---------------------------------------------------------------------------
def render_links_german(links: dict, keeplinks: str | None = None) -> str:
    """Render final BBCode blocks for audio/book links in German.

    ``links`` should contain ``audio`` and/or ``book`` dictionaries using the
    normalized host keys (``rapidgator``, ``ddownload`` …).  The resulting BBCode
    uses ``[size=3]`` everywhere and host abbreviations as link texts.
    """

    lines: list[str] = []
    if keeplinks:
        lines.append(f"[center][size=3][url={keeplinks}]Keeplinks[/url][/size][/center]")

    lines.append("[center][size=3][b]Download-Links[/b][/size][/center]")

    audio = links.get("audio", {}) if isinstance(links, dict) else {}
    if audio:
        lines.append("[center][size=3][b]Hörbuch-Teile[/b][/size][/center]")
        for host in HOST_ORDER + ["mega"]:
            urls = audio.get(host) or []
            if not urls:
                continue
            if len(urls) == 1:
                part = f"[url={urls[0]}]{HOST_TOKENS[host]}[/url]"
            else:
                part = " ".join(
                    f"[url={u}]{i:02d}[/url]" for i, u in enumerate(urls, 1)
                )
            lines.append(
                f"[center][size=3]{HOST_TOKENS[host]}: {part}[/size][/center]"
            )

    book = links.get("book", {}) if isinstance(links, dict) else {}
    if book:
        lines.append("[center][size=3][b]Buchdateien[/b][/size][/center]")
        fmt_parts: list[str] = []
        fmt_order = ["pdf", "epub", "azw3", "mobi", "djvu"]
        for fmt in fmt_order:
            host_map = book.get(fmt)
            if not host_map:
                continue
            host_parts = []
            for host in HOST_ORDER + ["mega"]:
                urls = host_map.get(host)
                if not urls:
                    continue
                url = urls[0] if isinstance(urls, list) else urls
                host_parts.append(f"[url={url}]{HOST_TOKENS[host]}[/url]")
            if host_parts:
                fmt_parts.append(f"{fmt.upper()}: {'-'.join(host_parts)}")
        if fmt_parts:
            lines.append(
                "[center][size=3]" + " — ".join(fmt_parts) + "[/size][/center]"
            )

    return "\n".join(lines).strip()


__all__ = ["apply_links_template", "LINK_TEMPLATE_PRESETS", "render_links_german"]

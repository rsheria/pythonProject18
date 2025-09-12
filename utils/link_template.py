"""Utilities for applying user-defined link templates."""
from typing import Any, List, Dict, Tuple
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



def _invert_host_results_by_type_format(host_results: Dict) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
    """
    يعكس بنية host_results (المجمعة تحت كل مضيف) إلى:
      by_type[type][format][host] = [urls...]
    - يتحمل حالات نقص المفاتيح (fallbacks).
    - يمنع التكرارات ويحافظ على ترتيب الإدراج.
    """
    def _uniq(seq: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for x in seq or []:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    out: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
    if not isinstance(host_results, dict):
        return out

    for host, bucket in (host_results or {}).items():
        if not host or not isinstance(bucket, dict):
            continue

        key = str(host).lower()
        is_rg_backup = False
        if "rapidgator" in key:
            is_rg_backup = (
                "backup" in key
                or key.endswith("-bak")
                or key.endswith("_bak")
                or key.endswith("-backup")
                or key.endswith("_backup")
                or bool(bucket.get("is_backup"))
            )
        if is_rg_backup:
            continue

        by_type = (bucket.get("by_type") or {}) if isinstance(bucket.get("by_type"), dict) else {}
        # نتعامل مع book/audio فقط، وأى أنواع أخرى نتجاهلها فى هذه المرحلة
        for t in ("book", "audio"):
            tmap = by_type.get(t) or {}
            if not isinstance(tmap, dict):
                continue
            for fmt, urls in tmap.items():
                if not fmt:
                    continue
                urls = _uniq([u for u in (urls or []) if isinstance(u, str) and u.strip()])
                if not urls:
                    continue
                out.setdefault(t, {}).setdefault(fmt, {}).setdefault(host, [])
                # دمج بدون تكرار مع الحفاظ على الترتيب
                merged = out[t][fmt][host] + [u for u in urls if u not in out[t][fmt][host]]
                out[t][fmt][host] = merged
    return out


def strip_legacy_link_blocks(template_text: str) -> str:
    """
    يحذف أى بلوكات/Placeholders قديمة خاصة بعرض اللينكات لمنع التكرار قبل الحقن.
    لا يغيّر أى نص آخر أو URLs.
    القواعد العامة:
      - مسح بلوكات placeholders قديمة مثل {AUDIOBOOK_LINKS_BLOCK} وما شابه.
      - مسح بلوكات CENTER بعنوان DOWNLOAD LINKS إذا كانت تحوى روابط فعلية فقط.
    """
    import re
    if not isinstance(template_text, str) or not template_text:
        return template_text or ""
    txt = template_text

    # أمسح placeholders قديمة لكن اترك أى أسطر فيها {LINKS} أو {LINK_*}
    tokens = [
        r"\{AUDIOBOOK_LINKS_BLOCK\}",
        r"\{EBOOK_LINKS_BLOCK\}",
        r"\{MUSIC_LINKS_BLOCK\}",
    ]
    pattern_tokens = re.compile("|".join(tokens))
    lines = []
    for line in txt.splitlines():
        if pattern_tokens.search(line or ""):
            continue
        lines.append(line)
    txt = "\n".join(lines)

    # إزالة بلوك DOWNLOAD LINKS فقط إذا لم يحتوِ على placeholders
    def _strip_block(m: re.Match) -> str:
        block = m.group(0)
        return block if re.search(r"\{LINK(?:S|_[A-Z_]+)\}", block) else ""

    txt = re.sub(
        r"\[center\][^\[]*?DOWNLOAD\s+LINKS[^\]]*?\[/center\]\s*",
        _strip_block,
        txt,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return txt

def build_type_format_host_blocks(
    host_results: Dict,
    host_order: List[str] = None,
    host_labels: Dict[str, str] = None,
    # معامل جديد للتحكم في السلوك
    force_build: bool = False
) -> Tuple[str, Dict[str, str]]:
    """
    يبنى بلوكات BBCode مفصّلة حسب النوع ثم الصيغة ثم المضيف.
    الآن، لن يتم تفعيل هذا المنطق الهرمي إلا إذا كانت force_build=True.
    """
    from .link_template import HOST_ORDER as DEFAULT_HOST_ORDER, HOST_LABELS as DEFAULT_HOST_LABELS
    from .link_template import _normalize_links_dict

    inv = _invert_host_results_by_type_format(host_results)

    # لو الاستدعاء مش مجبور عليه، مافيش داعى نبنى أى بلوك
    if not force_build:
        return "", {}

    order = list(host_order) if (host_order and isinstance(host_order, list)) else list(DEFAULT_HOST_ORDER)
    labels = dict(host_labels) if (host_labels and isinstance(host_labels, dict)) else dict(DEFAULT_HOST_LABELS)

    # --------- حالة ملف واحد أو عدم وجود بيانات مصنفة ---------
    types_present = [t for t, fmts in inv.items() if fmts]
    single_type = len(types_present) == 1
    single_fmt = False
    if single_type:
        fmt_map = inv[types_present[0]]
        fmts_present = [f for f, hosts in fmt_map.items() if hosts]
        single_fmt = len(fmts_present) == 1

    if not inv or (single_type and single_fmt):
        norm = _normalize_links_dict(host_results)
        keep = norm.get("keeplinks", [])
        if not inv:
            host_map = {h: u for h, u in norm.items() if h != "keeplinks" and u}
        else:
            fmt_map = inv[types_present[0]]
            fmts_present = [f for f, hosts in fmt_map.items() if hosts]
            raw_host_map = fmt_map[fmts_present[0]] if fmts_present else {}
            host_map = {h.split(".")[0]: urls for h, urls in raw_host_map.items()}
        if not host_map and not keep:
            return "", {}
        parts: List[str] = []
        if keep:
            parts.append(f"[url={keep[0]}]Keeplinks[/url]")
        for host in order:
            urls = host_map.get(host)
            if not urls:
                continue
            label = labels.get(host, host.capitalize())
            link_text = lambda i: f"{label}{i+1 if len(urls) > 1 else ''}"
            links_str = " | ".join(
                f"[url={u}]{link_text(i)}[/url]" for i, u in enumerate(urls)
            )
            parts.append(f"{label}: {links_str}")
        return " ‖ ".join(parts), {}
    # --------- نهاية حالة الملف الواحد ---------

    def _sorted_hosts(d: Dict[str, List[str]]) -> List[str]:
        present = list(d.keys())
        in_order = [h for h in order if h in present]
        rest = [h for h in present if h not in in_order]
        return in_order + rest

    parts: List[str] = []
    parts_by_type: Dict[str, List[str]] = {"book": [], "audio": []}

    type_headers = {
        "book": "[b]Links – eBooks[/b]",
        "audio": "[b]Links – Hörbücher[/b]",
    }

    for t in ("book", "audio"):
        tmap = inv.get(t) or {}
        if not tmap:
            continue
        t_parts: List[str] = [type_headers.get(t, f"[b]Links – {t}[/b]")]
        for fmt in sorted(tmap.keys()):
            hmap = tmap.get(fmt) or {}
            if not hmap:
                continue
            t_parts.append(f"[u]{fmt}[/u]")
            for host in _sorted_hosts(hmap):
                urls = [u for u in (hmap.get(host) or []) if u]
                if not urls:
                    continue
                host_display = labels.get(host.split(".")[0], labels.get(host, host))
                link_text = lambda i: f"{host_display}{i+1 if len(urls) > 1 else ''}"
                t_parts.append(
                    f"{host_display}: "
                    + " | ".join(
                        f"[url={u}]{link_text(i)}[/url]" for i, u in enumerate(urls)
                    )
                )
            if t_parts and not t_parts[-1].endswith("\n"):
                t_parts.append("")

        block_text = "\n".join([x for x in t_parts if x is not None]).strip()
        if block_text:
            parts_by_type[t].append(block_text)
            parts.append(block_text)

    full_text = "\n\n".join([p for p in parts if p]).strip()
    per_type_text = {
        k: ("\n\n".join(v).strip() if v else "")
        for k, v in parts_by_type.items()
    }
    return full_text, per_type_text

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
    blocks.append(f"[center][size=2][b]{label}:[/b] {parts}[/size][/center]")

# ----------------------------- main API ------------------------------------

def apply_links_template(template: str, links_dict: dict) -> str:
    """
    يطبّق التيمبلت بذكاء:
      - {LINK_KEEP} يتبدّل بأول Keeplinks لو موجود (مرة واحدة فقط).
      - لباقي المضيفين {LINK_DDL}/{LINK_RG}/{LINK_KF}/{LINK_NF}/{LINK_MEGA}:
          * 0 لينك  => يمسح العنصر بالكامل.
          * 1 لينك  => يستبدل الـ placeholder بالرابط (لو داخل [url=...] هيفضل التنسيق).
          * +1 لينك => يمسح العنصر من السطر الرئيسي ويضيف بلوك منفصل مرقّم 01..N تحت.
    """
    # 1) طبّع وفهرس الروابط
    jd = _normalize_links_dict(links_dict)

    if "{PART}" in template:
        lines: List[str] = []
        tmpl_lines = template.splitlines()
        max_parts = max((len(jd.get(h, [])) for h in jd if h != "keeplinks"), default=0)
        for idx in range(max_parts):
            for line in tmpl_lines:
                skip = False
                out_line = line
                for host, token in HOST_TOKENS.items():
                    placeholder = "{LINK_%s}" % token
                    if placeholder in out_line:
                        urls = jd.get(host, [])
                        if idx < len(urls):
                            out_line = out_line.replace(placeholder, urls[idx])
                            out_line = out_line.replace("{PART}", str(idx + 1))
                        else:
                            skip = True
                        break
                if not skip:
                    out_line = out_line.replace("{PART}", str(idx + 1))
                    lines.append(out_line)
        return "\n".join(lines).strip()

    # 2) Keeplinks: استخدم أول واحد فقط
    keep_urls = jd.get("keeplinks", [])
    if keep_urls:
        template = template.replace("{LINK_KEEP}", keep_urls[0])
    else:
        template = template.replace("{LINK_KEEP}", "")

    # 3) باقي المضيفين
    template_lines = template.splitlines()
    multi_blocks: List[str] = []
    for host in HOST_ORDER:
        token = HOST_TOKENS[host]
        label = HOST_LABELS[host]
        urls = jd.get(host, []) or []

        new_lines: List[str] = []
        for line in template_lines:
            if not urls:
                line = _strip_host_placeholder(line, token)
            elif len(urls) == 1:
                line = line.replace("{LINK_%s}" % token, urls[0])
                line = line.replace("[url={LINK_%s}]" % token, f"[url={urls[0]}]")
            else:
                line = _strip_host_placeholder(line, token)
            line = _cleanup_separators(line)
            new_lines.append(line)
        template_lines = new_lines
        if urls and len(urls) > 1:
            _append_multi_block(multi_blocks, label, urls)

    template = "\n".join(template_lines)

    # 4) نظافة عامة + إضافة بلوكات متعددة بعد أول [/center] لو موجود
    template = re.sub(r"\{LINK_[A-Z_]+\}", "", template)  # أي placeholders متبقية
    template = "\n".join(_cleanup_separators(l) for l in template.splitlines())

    lower_t = template.lower()
    if "[/center]" in lower_t and lower_t.strip().startswith("[center"):
        idx = lower_t.rfind("[/center]")
        idx = template.lower().rfind("[/center]")
        head = template[: idx + len("[/center]")]
        tail = template[idx + len("[/center]") :]
        extra = ("\n" + "\n".join(multi_blocks) + "\n") if multi_blocks else ""
        return (head + extra + tail).strip()
    else:
        extra = ("\n" + "\n".join(multi_blocks)) if multi_blocks else ""
        return (template + extra).strip()


# ---------------------------------------------------------------------------
def render_links_german(links: dict, keeplinks: str | None = None) -> str:
    """Render final BBCode blocks for audio/book links in German.

    Parameters
    ----------
    links: dict
        Structure with optional ``audio`` and ``book`` mappings.  Each host
        key should use the normalized host names (rapidgator, ddownload, etc.).
    keeplinks: str | None
        Optional Keeplinks URL to show above other links.
    """

    lines: list[str] = []
    if keeplinks:
        lines.append(f"[size=3][url={keeplinks}]Keeplinks[/url][/size]")

    lines.append("[size=3][b]Download-Links[/b][/size]")

    audio = links.get("audio", {}) if isinstance(links, dict) else {}
    if audio:
        lines.append("[size=3][b]Hörbuch-Teile[/b][/size]")
        for host in HOST_ORDER:
            urls = audio.get(host) or []
            if not urls:
                continue
            parts = " ".join(f"[url={u}]{i:02d}[/url]" for i, u in enumerate(urls, 1))
            lines.append(f"[size=3]{HOST_TOKENS[host]}: {parts}[/size]")

    book = links.get("book", {}) if isinstance(links, dict) else {}
    if book:
        lines.append("[size=3][b]Buchdateien[/b][/size]")
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
                fmt_parts.append(f"{fmt.upper()}: {' - '.join(host_parts)}")
        if fmt_parts:
            lines.append("[size=3]" + " — ".join(fmt_parts) + "[/size]")

    return "\n".join(lines).strip()


__all__ = ["apply_links_template", "LINK_TEMPLATE_PRESETS", "render_links_german"]

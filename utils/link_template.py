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
    if not v:
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v if x]
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
    يوحّد المفاتيح مهما كانت جاية إزاي:
    - اسم المضيف كدومين (rapidgator.net)
    - اختصار (RG / DDL / NF / KF / MEGA / KEEP)
    - {LINK_RG} / link_rg / rg_links ..الخ
    - أو حتى key generics مع URLs جواها
    """
    out: Dict[str, List[str]] = {k: [] for k in HOST_TOKENS.keys()}

    for k, vals in (links_dict or {}).items():
        key = str(k).lower()
        urls = _as_list(vals)

        # 1) صنّف من الURLs نفسها
        for url in urls:
            host = _guess_host_from_url(url)
            if host:
                out[host].append(url)

        # 2) لو مفيش تحديد من الURLs، جرّب من المفتاح نفسه
        if any(out[h] for h in HOST_TOKENS.keys()):
            # already added from urls; still try to add leftovers if key says so
            pass
        else:
            if "rapidgator" in key or key in ("rg", "link_rg", "rapidgator"):
                out["rapidgator"].extend(urls)
            elif "ddownload" in key or key in ("ddl", "link_ddl", "dd"):
                out["ddownload"].extend(urls)
            elif "katfile" in key or key in ("kf", "link_kf"):
                out["katfile"].extend(urls)
            elif "nitroflare" in key or key in ("nf", "link_nf"):
                out["nitroflare"].extend(urls)
            elif "mega" in key:
                out["mega"].extend(urls)
            elif "keeplink" in key or "keeplinks" in key or key in ("keep", "link_keep"):
                out["keeplinks"].extend(urls)

    # اشيل التكرار مع الحفاظ على الترتيب
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

    # 2) Keeplinks: استخدم أول واحد فقط
    keep_urls = jd.get("keeplinks", [])
    if keep_urls:
        template = template.replace("{LINK_KEEP}", keep_urls[0])
    else:
        template = _strip_host_placeholder(template, HOST_TOKENS["keeplinks"])

    # 3) باقي المضيفين
    multi_blocks: List[str] = []
    for host in HOST_ORDER:
        token = HOST_TOKENS[host]
        label = HOST_LABELS[host]
        urls = jd.get(host, []) or []

        if not urls:
            template = _strip_host_placeholder(template, token)
            continue

        if len(urls) == 1:
            # استبدل الـ placeholder لو موجود
            placeholder = "{LINK_%s}" % token
            if placeholder in template:
                template = template.replace(placeholder, urls[0])
            else:
                # لو التيمبلت بيستخدم [url={LINK_TOKEN}]..[/url] هتتم المعالجة تلقائيًا
                template = template.replace("{LINK_%s}" % token, urls[0])
                template = template.replace("[url={LINK_%s}]" % token, "[url=%s]" % urls[0])
        else:
            # شيل من السطر الرئيسي وأضِف بلوك مرقّم
            template = _strip_host_placeholder(template, token)
            _append_multi_block(multi_blocks, label, urls)

    # 4) نظافة عامة + إضافة بلوكات متعددة بعد أول [/center] لو موجود
    template = _cleanup_separators(template)
    template = re.sub(r"\{LINK_[A-Z_]+\}", "", template)  # أي placeholders متبقية

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

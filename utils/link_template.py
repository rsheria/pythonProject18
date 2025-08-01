"""Utilities for applying user-defined link templates."""
from typing import Dict, Any, List


# ---------------------------------------------------------------------------
# Built-in link template presets that can be selected from the settings UI.
# ``{PART}`` will be replaced with a sequential number when multiple links are
# available for a given host.
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



def _ensure_list(val: Any) -> List[str]:
    """Return *val* as a list of strings."""
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return [str(v) for v in val]
    return [str(val)]


def apply_links_template(template: str, links: Dict[str, Any]) -> str:
    """Replace placeholders in *template* with URLs from *links*.

    Known placeholders:
        {LINK_KEEP} - Keeplinks short link
        {LINK_RG}   - Rapidgator link
        {LINK_NF}   - Nitroflare link
        {LINK_DDL}  - DDownload link
        {LINK_KF}   - Katfile link
        {LINK_MEGA} - Mega link

    Missing placeholders are replaced with an empty string.
    """
    if not template:
        return ""

    placeholders = {
        "LINK_KEEP": "keeplinks",
        "LINK_RG": "rapidgator.net",
        "LINK_NF": "nitroflare.com",
        "LINK_DDL": "ddownload.com",
        "LINK_KF": "katfile.com",
        "LINK_MEGA": "mega",
    }

    lists = {ph: _ensure_list(links.get(site)) for ph, site in placeholders.items()}
    max_parts = max((len(v) for v in lists.values()), default=1)

    result_lines: List[str] = []
    for idx in range(max_parts):
        part = template
        has_any = False
        for ph, values in lists.items():
            val = values[idx] if idx < len(values) else ""
            if val:
                has_any = True
            part = part.replace(f"{{{ph}}}", val)
        part = part.replace("{PART}", str(idx + 1))
        if not has_any:
            continue

        for line in part.splitlines():
            stripped = line.strip()
            if stripped and not stripped.endswith(":"):
                result_lines.append(line)

    return "\n".join(result_lines)
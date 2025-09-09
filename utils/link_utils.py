"""Link grouping and persistence helpers.

This module provides a high level ``save_links`` function used by the
application to normalise raw host/url mappings and persist the grouped
representation inside the ``process_threads`` structure.  The grouped
representation separates links for the audiobook and the ebook formats in
order to render them later via :func:`utils.link_template.apply_links_template`.

Only the pieces required for the tests are implemented – this is not a full
port of the production module.
"""

from __future__ import annotations

from typing import Any, Dict, List
import logging
import re

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Host normalisation helpers
# ---------------------------------------------------------------------------

_CANON_HOSTS = {
    "rapidgator": "rapidgator",
    "rapidgator.net": "rapidgator",
    "rg": "rapidgator",
    "ddownload": "ddownload",
    "ddownload.com": "ddownload",
    "ddl": "ddownload",
    "katfile": "katfile",
    "katfile.com": "katfile",
    "kf": "katfile",
    "nitroflare": "nitroflare",
    "nitroflare.com": "nitroflare",
    "nf": "nitroflare",
    "mega": "mega",
    "mega.nz": "mega",
    "mega.co.nz": "mega",
    "keeplinks": "keeplinks",
    "keeplink": "keeplinks",
    "keeplinks.org": "keeplinks",
}

_FMT_ORDER = [
    "PDF",
    "EPUB",
    "AZW3",
    "MOBI",
    "DJVU",
    "FB2",
    "CBZ",
    "CBR",
    "TXT",
]


def _as_list(v: Any) -> List[str]:
    if v is None or v is False:
        return []
    if isinstance(v, dict):
        for k in ("urls", "url", "link"):
            if k in v:
                return _as_list(v[k])
        return []
    if isinstance(v, (list, tuple, set)):
        out: List[str] = []
        for x in v:
            out.extend(_as_list(x))
        return out
    return [str(v)]


def _dedup(seq: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for s in seq:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _guess_host_from_url(url: str) -> str:
    u = url.lower()
    if "rapidgator" in u:
        return "rapidgator"
    if "ddownload" in u or "//ddl" in u:
        return "ddownload"
    if "katfile" in u:
        return "katfile"
    if "nitroflare" in u:
        return "nitroflare"
    if "mega.nz" in u or "mega.co.nz" in u:
        return "mega"
    if "keeplinks" in u:
        return "keeplinks"
    return ""


def _ext_from_url(url: str) -> str:
    """Return lowercase file extension (without dot) inferred from *url*.

    Query strings or fragments are stripped before the extension is
    determined.  If no extension can be determined an empty string is
    returned.
    """
    try:
        path = url.split("?", 1)[0].split("#", 1)[0]
        m = re.search(r"\.([a-z0-9]{1,5})$", path.lower())
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _canonicalize_host(key: str) -> str:
    return _CANON_HOSTS.get(key.lower().strip(), "")


def _normalize_flat_map(src: Dict[Any, Any]) -> Dict[str, List[str]]:
    """Return flat host->urls mapping from an arbitrary ``src`` mapping."""

    out: Dict[str, List[str]] = {}
    if not isinstance(src, dict):
        return out

    for raw_key, val in src.items():
        key = str(raw_key).lower()
        if key == "episodes":
            # handled separately; don't mix with audio/ebook
            continue
        canon = _canonicalize_host(key)
        urls = _as_list(val)
        if canon:
            if canon == "keeplinks":
                if urls:
                    out["keeplinks"] = [urls[0]]
            else:
                out.setdefault(canon, []).extend(urls)
            continue

        # grouped structures like {"audio": {host: [...]}}
        if key == "audio":
            for h, u in (val or {}).items():
                host = _canonicalize_host(str(h)) or _guess_host_from_url(str(h))
                if host and host != "keeplinks":
                    out.setdefault(host, []).extend(_as_list(u))
            continue
        if key == "ebook":
            for by_host in (val or {}).values():
                for h, u in (by_host or {}).items():
                    host = _canonicalize_host(str(h)) or _guess_host_from_url(str(h))
                    if host and host != "keeplinks":
                        out.setdefault(host, []).extend(_as_list(u))
            continue
        if key == "keeplinks":
            if urls:
                out["keeplinks"] = [urls[0]]
            continue

        # Unknown key – try to guess from the URLs themselves
        for u in urls:
            host = _guess_host_from_url(u)
            if host:
                out.setdefault(host, []).append(u)

    for h in list(out.keys()):
        out[h] = _dedup(out[h])
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_links(main_window: Any, category: str, title: str, links: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise *links*, group them using ``group_hints`` and persist.

    Returns
    -------
    dict
        The grouped structure that was persisted. Keys include ``audio`` and ``ebook``
        (bucketed links), ``episodes`` (episodic content), ``keeplinks`` (single short-link),
        and ``mirrors`` (leftover direct links that don’t fit other buckets).
    """
    flat = _normalize_flat_map(links or {})

    keeplink = ""
    if flat.get("keeplinks"):
        keeplink = flat.pop("keeplinks")[0]

    # ---- Locate thread record & grouping hints safely ----
    try:
        cat_map = (getattr(main_window, "process_threads", None) or {}).get(category, {})
        root_rec = cat_map.get(title)
        if not root_rec:
            return {}
        versions = root_rec.get("versions")
        latest = versions[-1] if isinstance(versions, list) and versions else root_rec
    except Exception:
        log.exception("save_links: thread not found for %s/%s", category, title)
        return {}

    hints = (latest.get("group_hints") or {}) if isinstance(latest, dict) else {}
    audio_parts = int(hints.get("audio_parts") or 0)
    ebook_counts = {str(k).upper(): int(v) for k, v in (hints.get("ebook_counts") or {}).items()}

    # Deterministic order for formats (preserve _FMT_ORDER then append any extras)
    extras = [k for k in ebook_counts.keys() if k not in _FMT_ORDER]
    fmt_order = _FMT_ORDER + extras

    grouped: Dict[str, Any] = {}
    if keeplink:
        grouped["keeplinks"] = keeplink

    audio_map: Dict[str, List[str]] = {}
    ebook_map: Dict[str, Dict[str, List[str]]] = {}
    mirrors_map: Dict[str, List[str]] = {}

    for host, urls in flat.items():
        if not urls:
            continue

        remaining = list(urls)

        # ---- AUDIO bucketing (by parts) ----
        if audio_parts > 0:
            picked: List[str] = []
            # Prefer archive-like extensions for audio packs
            for u in list(remaining):
                if _ext_from_url(u) in {"rar", "zip", "7z"}:
                    picked.append(u)
                    remaining.remove(u)
                    if len(picked) == audio_parts:
                        break
            # Fallback fill if hints > available archives
            while len(picked) < audio_parts and remaining:
                picked.append(remaining.pop(0))
            if picked:
                audio_map[host] = picked

        # ---- EBOOK bucketing (by format counts) ----
        for fmt in fmt_order:
            need = int(ebook_counts.get(fmt, 0) or 0)
            if need <= 0:
                continue
            fmt_lower = fmt.lower()
            picked: List[str] = []
            for u in list(remaining):
                if _ext_from_url(u) == fmt_lower:
                    picked.append(u)
                    remaining.remove(u)
                    if len(picked) == need:
                        break
            # Fallback fill if not enough exact matches
            while len(picked) < need and remaining:
                picked.append(remaining.pop(0))
            if picked:
                ebook_map.setdefault(fmt, {})[host] = picked

        # ---- Anything left goes to MIRRORS (avoid dropping direct links) ----
        if remaining:
            mirrors_map.setdefault(host, []).extend(_dedup(remaining))

    if audio_map:
        grouped["audio"] = audio_map
    if ebook_map:
        grouped["ebook"] = ebook_map
    if mirrors_map:
        grouped["mirrors"] = mirrors_map

    # ---- Pass-through of EPISODES (if provided in grouped source) ----
    episodes_src = links.get("episodes") if isinstance(links, dict) else {}
    episodes_grouped: Dict[str, Dict[str, List[str]]] = {}
    if isinstance(episodes_src, dict):
        for label, by_host in (episodes_src or {}).items():
            if not isinstance(by_host, dict):
                continue
            for h, u in (by_host or {}).items():
                canon = _canonicalize_host(str(h)) or _guess_host_from_url(str(h))
                url_list = _dedup(_as_list(u))
                if canon and url_list:
                    episodes_grouped.setdefault(str(label), {})[canon] = url_list
    if episodes_grouped:
        grouped["episodes"] = episodes_grouped

    # ---- Persist back into process_threads ----
    try:
        root_rec["links"] = grouped
        if latest is not root_rec and isinstance(latest, dict):
            latest["links"] = grouped
        # Force persistence so process_threads survives restarts
        if hasattr(main_window, "save_process_threads_data"):
            try:
                main_window.save_process_threads_data(force=True)  # type: ignore[call-arg]
            except TypeError:
                main_window.save_process_threads_data()  # backward compatibility
    except Exception:
        log.exception("Failed to save links for %s/%s", category, title)

    return grouped





__all__ = ["save_links"]


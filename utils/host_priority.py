from __future__ import annotations
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit


def _clean_host(host: str) -> str:
    host = (host or "").lower().strip()
    return host[4:] if host.startswith("www.") else host


def get_highest_priority_host(settings: Any = None, config: Optional[dict] = None) -> Optional[str]:
    """Return the highest priority host from user settings.

    Parameters
    ----------
    settings: Any, optional
        Object that may provide ``get_current_priority`` returning an iterable
        of hosts.
    config: dict, optional
        Mapping used as fallback source. ``download_hosts_priority`` should
        contain an iterable of hosts.

    Returns
    -------
    Optional[str]
        The first host in the resolved priority list or ``None`` if no
        priority is defined.
    """
    priority: Iterable[str] | None = None
    if settings and hasattr(settings, "get_current_priority"):
        try:
            priority = settings.get_current_priority() or []
        except Exception:
            priority = []
    if (not priority) and config:
        priority = config.get("download_hosts_priority") or []
    priority = priority or []
    priority_list = [h for h in priority if isinstance(h, str)]
    return priority_list[0].strip().lower() if priority_list else None


def filter_direct_links_for_host(
    direct_urls: Iterable[str], visible_scope: dict, host: Optional[str]
) -> tuple[list[str], dict]:
    """Filter *direct_urls* and *visible_scope* to the specified *host*.

    Parameters
    ----------
    direct_urls: Iterable[str]
        URLs collected for direct link checking.
    visible_scope: dict
        Mapping of scope information as produced by
        ``collect_visible_scope_for_selected_threads``.
    host: str, optional
        Hostname to keep. If ``None`` the inputs are returned unchanged.

    Returns
    -------
    tuple[list[str], dict]
        The filtered list of URLs and corresponding scope mapping.
    """

    if not host:
        return list(direct_urls), dict(visible_scope or {})

    host = _clean_host(host)
    filtered_urls = [
        u
        for u in direct_urls
        if _clean_host(urlsplit(u).hostname or "") == host
    ]

    filtered_scope: dict = {}
    for key, info in (visible_scope or {}).items():
        urls = info.get("urls", [])
        kept = [
            u
            for u in urls
            if _clean_host(urlsplit(u).hostname or "") == host
        ]
        if kept:
            new_info = dict(info)
            new_info["urls"] = kept
            new_info["hosts"] = [host]
            filtered_scope[key] = new_info

    return filtered_urls, filtered_scope
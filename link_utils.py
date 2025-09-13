"""
Utility functions for working with thread download/upload links.

This module defines a canonical representation for links associated with
threads and provides helper functions to normalise arbitrary link
structures into this canonical form, locate thread records within the
process_threads data structure and persist updates to disk.  The goal
is to ensure that all parts of the application operate on a single
source of truth for link data, avoiding stale or mismatched formats.

Canonical Schema
----------------
The canonical schema is a flat dictionary with the following keys:

    - ``rapidgator.net``: ``list[str]`` – direct Rapidgator download links
    - ``nitroflare.com``: ``list[str]`` – direct Nitroflare download links
    - ``ddownload.com``: ``list[str]`` – direct DDownload links
    - ``katfile.com``: ``list[str]`` – direct Katfile links
    - ``uploady.io``: ``list[str]`` – direct Uploady.io links
    - ``rapidgator-backup``: ``list[str]`` – backup Rapidgator links (if any)
    - ``keeplinks``: ``str`` – the Keeplinks short URL

Any unknown keys or values are ignored during normalisation.

These helpers are intentionally free of any PyQt dependencies so they
can be reused by both GUI and worker threads.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Mapping of known synonyms to canonical keys.  All keys in this map
# should be lowercase.  Unknown keys will be skipped.
_KEY_ALIASES = {
    "rapidgator": "rapidgator.net",
    "rapidgator.net": "rapidgator.net",
    "rg": "rapidgator.net",
    # backup synonyms
    "rapidgator-bak": "rapidgator-backup",
    "rapidgator_bak": "rapidgator-backup",
    # support underscore variant used in some payloads
    "rapidgator_backup": "rapidgator-backup",
    "rapidgatorbak": "rapidgator-backup",
    "rg_bak": "rapidgator-backup",
    "rapidgatorbackup": "rapidgator-backup",
    "rapidgator-backup": "rapidgator-backup",
    # other hosts
    "nitroflare": "nitroflare.com",
    "nitroflare.com": "nitroflare.com",
    "ddownload": "ddownload.com",
    "ddownload.com": "ddownload.com",
    "katfile": "katfile.com",
    "katfile.com": "katfile.com",
    "uploady": "uploady.io",
    "uploady.io": "uploady.io",
    # keeplinks
    "keeplinks": "keeplinks",
}


def _flatten(value: Any) -> List[str]:
    """Flatten arbitrary nested link structures into a flat list of strings.

    Values may be lists, tuples, sets, dicts or scalars.  Dicts are
    searched for common keys like ``'urls'``, ``'url'`` or ``'link'`` and
    flattened recursively.  Falsy values are ignored.

    Args:
        value: The raw value extracted from an input mapping.

    Returns:
        A list of strings representing individual URLs.
    """
    if value is None or value is False or value is True:
        return []
    # If the value is already a list/tuple/set, flatten each element
    if isinstance(value, (list, tuple, set)):
        result: List[str] = []
        for item in value:
            result.extend(_flatten(item))
        return result
    # If it's a dict, look for common url-containing keys
    if isinstance(value, dict):
        for k in ("urls", "url", "link"):
            if k in value:
                return _flatten(value[k])
        # If no known key, ignore this dict
        return []
    # If it's a string, return as single element if non-empty
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    # Fallback: convert to string
    return [str(value)]


def normalize_links(src: Any) -> Dict[str, Any]:
    """Normalise an arbitrary collection of host links into the canonical schema.

    The input may be a mapping of host keys to lists/strings/dicts or any
    other structure.  Keys are coerced to their canonical form using
    ``_KEY_ALIASES``.  Unknown keys are ignored.  Host values are
    flattened into lists of strings.  The special key ``'keeplinks'`` is
    kept as a single string – if a list is provided, it will be joined
    using newlines.

    Args:
        src: The raw links mapping (typically from the upload worker).

    Returns:
        A new dictionary following the canonical schema.  Keys will only
        include known hosts and ``'keeplinks'``.
    """
    out: Dict[str, Any] = {}
    if not isinstance(src, dict):
        return out
    for raw_key, raw_val in src.items():
        if raw_key is None:
            continue
        key_lower = str(raw_key).lower().strip()
        canonical_key = _KEY_ALIASES.get(key_lower)
        if not canonical_key:
            # Skip unknown keys (e.g. 'thread_id')
            continue
        if canonical_key == "keeplinks":
            # Keep Keeplinks as a single string; join lists into a newline-separated string
            if isinstance(raw_val, (list, tuple, set)):
                flattened: List[str] = []
                for v in raw_val:
                    flattened.extend(_flatten(v))
                out["keeplinks"] = "\n".join(flattened).strip()
            else:
                # Convert scalars or dicts to string
                if isinstance(raw_val, dict):
                    # Some older formats might wrap keeplinks in a dict
                    for kk in ("url", "link", "urls"):
                        if kk in raw_val:
                            raw_val = raw_val[kk]
                            break
                out["keeplinks"] = str(raw_val).strip() if raw_val else ""
            continue
        # Normal host: flatten into list
        urls = _flatten(raw_val)
        if not urls:
            continue
        existing = out.get(canonical_key, [])
        existing.extend(urls)
        out[canonical_key] = existing
    return out


def get_thread_record(process_threads: Dict[str, Dict[str, Dict[str, Any]]],
                       category: str,
                       title: str) -> Optional[Dict[str, Any]]:
    """Return the most recent record for a thread, preferring the latest version.

    Args:
        process_threads: The nested mapping of categories to thread info.
        category: The category name.
        title: The thread title.

    Returns:
        The thread record dictionary corresponding to the latest version if
        available, otherwise the root record.  Returns ``None`` if the
        thread cannot be found.
    """
    cat = process_threads.get(category)
    if not cat:
        return None
    rec = cat.get(title)
    if not rec:
        return None
    versions = rec.get("versions")
    if isinstance(versions, list) and versions:
        latest = versions[-1]
        if isinstance(latest, dict):
            return latest
    return rec


def save_links(main_window: Any, category: str, title: str, links: Dict[str, Any]) -> None:
    """Persist updated links for a thread and write to disk.

    This helper writes the provided ``links`` into both the root thread
    record and the latest version (if any) within ``main_window.process_threads``.
    It then invokes ``main_window.save_process_threads_data()`` to flush
    changes to disk.

    Args:
        main_window: The ``MainWindow`` instance that owns the ``process_threads``
            mapping and persistence methods.
        category: Category name of the thread.
        title: Thread title.
        links: Canonical links dictionary to persist.
    """
    try:
        if not hasattr(main_window, "process_threads"):
            return
        cat = main_window.process_threads.get(category)
        if not cat:
            return
        root_rec = cat.get(title)
        if not root_rec:
            return
        # Update both root and latest version
        root_rec["links"] = links
        versions = root_rec.get("versions")
        if isinstance(versions, list) and versions:
            latest = versions[-1]
            if isinstance(latest, dict):
                latest["links"] = links
        # Persist to disk
        if hasattr(main_window, "save_process_threads_data"):
            main_window.save_process_threads_data()
    except Exception:
        log.exception("Failed to save links for %s/%s", category, title)
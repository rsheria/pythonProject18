"""Utilities for persisting link replacements and statuses."""
from __future__ import annotations

from typing import Callable, Dict


def persist_link_replacement(
    process_threads: Dict,
    category: str,
    thread_title: str,
    host: str,
    link_statuses: Dict[str, str],
    save_process_threads: Callable[[], None],
    user_manager,
    status_filename: str = "link_status.json",
) -> Dict:
    """Persist replaced links and their statuses.

    This helper updates the ``process_threads`` mapping with the provided
    ``link_statuses`` for ``host`` and stores both the updated mapping and the
    status cache using ``user_manager``.  The provided ``save_process_threads``
    callback is invoked to write the modified ``process_threads`` structure to
    disk using the application's existing persistence logic.

    Parameters
    ----------
    process_threads:
        The current process threads mapping.
    category:
        Category name of the thread row being updated.
    thread_title:
        Title of the thread row being updated.
    host:
        Host for which the direct links belong.
    link_statuses:
        Mapping of direct link URLs to their last known status.
    save_process_threads:
        Callback that persists ``process_threads`` to disk.
    user_manager:
        Object providing ``load_user_data`` and ``save_user_data`` methods for
        per-user storage.
    status_filename:
        Filename used for the link-status cache. Defaults to ``link_status.json``.

    Returns
    -------
    Dict
        The updated link-status cache.
    """

    try:
        thread = process_threads.get(category, {}).get(thread_title)
        if thread is not None:
            links_dict = thread.setdefault("links", {})
            links_dict[host] = list(link_statuses.keys())
            # Remove legacy container placeholder if present
            links_dict.pop("keeplinks", None)
            save_process_threads()
    except Exception:
        # Fail silently – persistence issues are logged by the caller.
        pass

    cache = user_manager.load_user_data(status_filename, {}) or {}
    for url, status in (link_statuses or {}).items():
        if url:
            cache.setdefault(url, {}).update({"status": status})
    try:
        user_manager.save_user_data(status_filename, cache)
    except Exception:
        pass
    return cache
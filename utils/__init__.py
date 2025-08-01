
"""Utility functions and helpers used across the project."""
from .sanitize import sanitize_filename
try:
    from .legacy_tls import DDownloadAdapter
except Exception:  # pragma: no cover - dependency might be missing in tests
    class DDownloadAdapter:  # type: ignore
        """Fallback stub if requests is unavailable."""
        pass
from .link_template import apply_links_template, LINK_TEMPLATE_PRESETS



def get_rapidgator_stats(*args, **kwargs):
    from .rapidgator_stats import get_rapidgator_stats as _impl
    return _impl(*args, **kwargs)


def get_nitroflare_stats(*args, **kwargs):
    from .nitroflare_stats import get_nitroflare_stats as _impl
    return _impl(*args, **kwargs)

__all__ = [
    "sanitize_filename",
    "get_rapidgator_stats",
    "get_nitroflare_stats",
    "DDownloadAdapter",
    "apply_links_template",
    "LINK_TEMPLATE_PRESETS",
]
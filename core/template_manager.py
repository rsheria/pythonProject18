import json
import logging
from pathlib import Path
from typing import Dict, Optional

from config.config import DATA_DIR
from core.user_manager import UserManager, get_user_manager


class TemplateManager:
    """Manage per-category BBCode templates."""

    def __init__(self, path: Optional[Path] = None, user_manager: Optional[UserManager] = None):
        self.user_manager = user_manager or get_user_manager()
        self._custom_path = Path(path) if path else None
        self.templates: Dict[str, str] = {}
        self._update_path()
        self.load()

    def _update_path(self) -> None:
        if self._custom_path is not None:
            self.path = self._custom_path
            return
        if self.user_manager and self.user_manager.get_current_user():
            folder = Path(self.user_manager.get_user_folder())
            self.path = folder / "templates.json"
        else:
            self.path = Path(DATA_DIR) / "templates.json"

    def load(self) -> None:
        self._update_path()
        if self.path.exists():
            try:
                self.templates = json.load(open(self.path, "r", encoding="utf-8"))
            except Exception as e:
                logging.error("Failed to load templates: %s", e)
                self.templates = {}
        else:
            self.templates = {}

    def save(self) -> None:
        self._update_path()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.templates, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error("Failed to save templates: %s", e)

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------
    def get_template(self, category: str) -> str:
        return self.templates.get(category, "")

    def set_template(self, category: str, template: str) -> None:
        self.templates[category] = template
        self.save()

    def remove_template(self, category: str) -> None:
        if category in self.templates:
            self.templates.pop(category)
            self.save()

    def all_templates(self) -> Dict[str, str]:
        return dict(self.templates)

    def render_with_links(
        self,
        category: str,
        host_results: dict,
        template_text: Optional[str] = None,
        host_labels: dict | None = None,
        host_order: list[str] | None = None,
    ) -> str:
        """
        Build final BBCode by injecting link blocks grouped by type/format/host into the template for *category*.

        The ``host_results`` structure should mirror the data stored by the upload pipeline, typically a nested
        mapping of host → {all, by_type}. If ``template_text`` is not provided, the method will load the
        template for ``category`` using ``get_template``.

        The method performs the following steps:

        1. Load the base template and remove any legacy link placeholders or panels.
        2. Use ``utils.link_template`` helpers to build a hierarchical link block respecting host order and labels.
        3. Replace the first occurrence of ``{LINKS}``/``{links}``/``[LINKS]``/``[links]`` in the cleaned template with
           the generated block. If none of these placeholders are found, append the block at the end.

        In case of any error, the original template is returned unchanged.
        """
        base = template_text if template_text is not None else (self.get_template(category) or "")
        try:
            # Import helpers locally to avoid altering module-level imports
            from utils import link_template as lt  # type: ignore
            cleaned = lt.strip_legacy_link_blocks(base)
            block_text, _ = lt.build_type_format_host_blocks(
                host_results or {},
                host_order=host_order,
                host_labels=host_labels,
            )
            if not block_text:
                return cleaned
            # Replace placeholders if present
            placeholders = ["{LINKS}", "{links}", "[LINKS]", "[links]"]
            for ph in placeholders:
                if ph in cleaned:
                    return cleaned.replace(ph, block_text)
            # Otherwise append the block
            if cleaned and not cleaned.endswith("\n"):
                cleaned += "\n"
            return f"{cleaned}\n{block_text}\n"
        except Exception:
            # Fallback to original base if anything goes wrong
            return base


# Global instance used across the application
_template_manager = TemplateManager()

def get_template_manager() -> TemplateManager:
    return _template_manager

    # ---------------------------------------------------------------------------
    # New hierarchical templates mapping helpers
    # ---------------------------------------------------------------------------


_MAPPING_PATH = Path(DATA_DIR) / "my_templates.json"


def load_mapping() -> Dict[str, Dict[str, object]]:
    """Load templates mapping from ``my_templates.json``.

    Automatically migrates legacy formats where the value was a plain string.
    """
    if not _MAPPING_PATH.exists():
        return {}

    try:
        data = json.load(open(_MAPPING_PATH, "r", encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - corruption shouldn't crash
        logging.error("Failed to load template mapping: %s", exc)
        return {}

    changed = False
    for key, val in list(data.items()):
        if isinstance(val, str):
            data[key] = {"template": val, "children": []}
            changed = True
    if changed:
        save_mapping(data)
    return data


def save_mapping(mapping: Dict[str, Dict[str, object]]) -> None:
    """Persist *mapping* to ``my_templates.json``."""
    try:
        _MAPPING_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_MAPPING_PATH, "w", encoding="utf-8") as fh:
            json.dump(mapping, fh, ensure_ascii=False, indent=2)
    except Exception as exc:  # pragma: no cover - file system errors
        logging.error("Failed to save template mapping: %s", exc)


def get_template_for_category(category: str) -> Optional[str]:
    """Return template for *category* resolving inheritance."""
    mapping = load_mapping()
    if category in mapping:
        return mapping[category].get("template", "")
    for parent, info in mapping.items():
        if category in info.get("children", []):
            return info.get("template", "")
    return None
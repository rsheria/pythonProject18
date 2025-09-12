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


# ضعه في core/template_manager.py بدلاً من الدالة render_with_links الحالية

# ضعه في core/template_manager.py بدلاً من الدالة render_with_links الحالية

def render_with_links(
        self,
        category: str,
        host_results: dict,
        template_text: Optional[str] = None,
        host_labels: dict | None = None,
        host_order: list[str] | None = None,
) -> str:
    """
    Builds the final BBCode. This version correctly uses the appropriate link building
    strategy based on the placeholders found in the user-defined template. It ensures
    that templates with generic {LINKS} placeholders are correctly processed using
    the legacy templating engine.
    """
    base = template_text if template_text is not None else (self.get_template(category) or "")
    try:
        from utils import link_template as lt
        import logging

        # Clean the base template from any PREVIOUSLY generated link blocks to avoid duplication
        # This does NOT remove placeholders like {LINKS}
        cleaned_template = lt.strip_legacy_link_blocks(base)

        # --- Strategy Detection ---

        # Strategy A: New hierarchical placeholders (for future use cases)
        new_placeholders = ["{AUDIOBOOK_LINKS_BLOCK}", "{EBOOK_LINKS_BLOCK}", "{MUSIC_LINKS_BLOCK}"]
        use_hierarchical_builder = any(ph in cleaned_template for ph in new_placeholders)

        # Strategy B: Legacy placeholders OR the generic {LINKS} placeholder
        legacy_placeholders = ["{LINK_RG}", "{LINK_DDL}", "{LINK_KF}", "{LINK_NF}", "{LINK_MEGA}", "{LINK_KEEP}",
                               "{PART}"]
        generic_placeholders = ["{LINKS}", "[LINKS]", "{links}", "[links]", "{LINKS_BLOCK}"]
        use_legacy_builder = any(ph in cleaned_template for ph in legacy_placeholders) or any(
            ph in cleaned_template for ph in generic_placeholders)

        # --- Execution ---

        if use_hierarchical_builder:
            logging.debug("Using hierarchical link builder strategy.")
            block_text, per_type = lt.build_type_format_host_blocks(
                host_results, host_order=host_order, host_labels=host_labels, force_build=True  # <-- Force build
            )
            # (The rest of the logic for this case is fine)
            host_results_copy = dict(host_results or {})
            keeplinks_val = host_results_copy.pop("keeplinks", None)
            keeplink_url = ""
            if isinstance(keeplinks_val, dict):
                urls = keeplinks_val.get("urls") or keeplinks_val.get("url") or []
                keeplink_url = urls[0] if isinstance(urls, list) and urls else (urls if isinstance(urls, str) else "")
            elif isinstance(keeplinks_val, str):
                keeplink_url = keeplinks_val

            if keeplink_url:
                keep_line = f"[url={keeplink_url}]Keeplinks[/url]"
                block_text = keep_line + ("\n\n" + block_text if block_text else "")
                per_type = {k: (keep_line + ("\n\n" + v if v else "")) for k, v in per_type.items()}

            if not block_text: return cleaned_template

            injector = getattr(lt, "inject_links_blocks", None)
            if callable(injector): return injector(cleaned_template, block_text, per_type)

            for ph, blk in [
                ("{AUDIOBOOK_LINKS_BLOCK}", per_type.get("audio")),
                ("{EBOOK_LINKS_BLOCK}", per_type.get("book")),
                ("{LINKS}", block_text),
            ]:
                if blk and ph in cleaned_template:
                    cleaned_template = cleaned_template.replace(ph, blk, 1)
            return cleaned_template

        elif use_legacy_builder:
            logging.debug("Using legacy/generic link builder strategy.")
            template_to_process = cleaned_template

            # Default sub-template for the {LINKS} placeholder
            default_links_sub_template = (
                "[center][size=3][b]DOWNLOAD LINKS[/b][/size]\n\n"
                "[url={LINK_KEEP}]Keeplinks[/url] ‖ "
                "[url={LINK_DDL}]DDownload[/url] ‖ "
                "[url={LINK_RG}]Rapidgator[/url] ‖ "
                "[url={LINK_KF}]Katfile[/url] ‖ "
                "[url={LINK_NF}]Nitroflare[/url]\n"
                "[/center]"
            )

            for ph in generic_placeholders:
                if ph in template_to_process:
                    template_to_process = template_to_process.replace(ph, default_links_sub_template, 1)
                    logging.debug(f"Replaced generic placeholder '{ph}' with default sub-template.")
                    break

            return lt.apply_links_template(template_to_process, host_results or {})

        else:
            logging.debug("No known placeholders found. Appending a default link block.")
            block_text, _ = lt.build_type_format_host_blocks(host_results, force_build=True)
            if not block_text:
                from utils.link_template import _normalize_links_dict, HOST_ORDER, HOST_LABELS
                simple_parts = []
                direct_map = _normalize_links_dict(host_results)
                for host in HOST_ORDER:
                    if host in direct_map and direct_map[host]:
                        urls = direct_map[host]
                        label = HOST_LABELS.get(host, host.capitalize())
                        links_str = " | ".join(f"[url={u}]{i + 1}[/url]" for i, u in enumerate(urls))
                        simple_parts.append(f"{label}: {links_str}")
                block_text = "\n".join(simple_parts)

            if cleaned_template and not cleaned_template.endswith("\n"):
                cleaned_template += "\n"
            return f"{cleaned_template}\n{block_text}".strip()

    except Exception as e:
        logging.error("Failed to render links, returning base template. Error: %s", e, exc_info=True)
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

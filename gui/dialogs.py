import os

from PyQt5.QtWidgets import (
    QDialog,
    QLabel,
    QDialogButtonBox,
    QTextEdit,
    QVBoxLayout,
    QCheckBox,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QHBoxLayout,
)
from PyQt5.QtCore import Qt

# ====================================
# LinksDialog: عرْض الروابط بعد الرفع
# ====================================
class LinksDialog(QDialog):
    """Dialog to display uploaded links and tolerate old/new formats.

    تقبل:
      - قيم list[str] أو str عادى
      - dict فيه {'urls': [...], 'is_backup': bool}
      - نص ممثل لقائمة/قاموس (مثلا "{'urls': [...]}") ويتم تفريغه بأمان
      - مفاتيح مضيفين قديمة (rapidgator) أو جديدة (rapidgator.net, rapidgator-backup)
    """
    def __init__(self, thread_title, links_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Links for {thread_title}")
        layout = QVBoxLayout(self)

        flat = self._normalize_links(links_dict or {})

        # 1) Keeplinks أولًا كسطر واحد
        keeplinks_url = flat.get("keeplinks", "")
        if keeplinks_url:
            layout.addWidget(QLabel("<b>Keeplinks URL:</b>"))
            keeplinks_edit = QTextEdit()
            keeplinks_edit.setPlainText(str(keeplinks_url))
            keeplinks_edit.setReadOnly(True)
            layout.addWidget(keeplinks_edit)

        # 2) ترتيب الهوستات: RG, DDL, KF, NF, RG_BAK ثم أى مفاتيح أخرى
        preferred = [
            "rapidgator.net",
            "ddownload.com",
            "katfile.com",
            "nitroflare.com",
            "uploady.io",
            "rapidgator-backup",
        ]
        order, seen = [], set()
        for h in preferred:
            if flat.get(h):
                order.append(h); seen.add(h)
        for h, v in flat.items():
            if h in seen or h == "keeplinks":
                continue
            if v:
                order.append(h)

        # 3) عرض الروابط
        for host in order:
            urls = flat.get(host)
            if not urls:
                continue
            layout.addWidget(QLabel(f"<b>{host} URLs:</b>"))
            edit = QTextEdit()
            if isinstance(urls, (list, tuple)):
                edit.setPlainText("\n".join(str(u) for u in urls if u))
            else:
                edit.setPlainText(str(urls))
            edit.setReadOnly(True)
            layout.addWidget(edit)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject, type=Qt.QueuedConnection)
        layout.addWidget(button_box)

    # -------- Helpers --------
    def _normalize_links(self, src: dict) -> dict:
        """ترجع خريطة مسطحة: host -> list[str] + 'keeplinks': str"""
        import ast

        def try_eval(s):
            # يحاول يفك نص ممثل لـ list/dict بأمان؛ وإلا يرجّع s كما هو
            if not isinstance(s, str):
                return s
            s_strip = s.strip()
            if (s_strip.startswith("{") and s_strip.endswith("}")) or (s_strip.startswith("[") and s_strip.endswith("]")):
                try:
                    return ast.literal_eval(s_strip)
                except Exception:
                    return s
            return s

        def as_list(v):
            v = try_eval(v)
            if v is None or v is True or v is False:
                return []
            if isinstance(v, dict):
                v = v.get("urls") or v.get("url") or v.get("link") or []
            if isinstance(v, str):
                return [v] if v else []
            if isinstance(v, (list, tuple, set)):
                out = []
                for x in v:
                    x = try_eval(x)
                    if isinstance(x, dict):
                        out.extend(as_list(x))
                    elif isinstance(x, (list, tuple, set)):
                        out.extend([str(i) for i in x if i])
                    elif x:
                        out.append(str(x))
                return out
            return []

        def norm_key(k: str) -> str:
            k = (k or "").lower().strip()
            if k == "rapidgator":
                return "rapidgator.net"
            if k in ("rg_bak", "rapidgator_bak", "rapidgatorbackup"):
                return "rapidgator-backup"
            if k in ("uploady", "uploady.io"):  # إصلاح المشكلة - دعم uploady و uploady.io
                return "uploady.io"
            return k

        out = {}

        # keeplinks كنص واحد (لو قائمة نجمعها كسطور)
        klinks = src.get("keeplinks")
        klinks = try_eval(klinks)
        if isinstance(klinks, (list, tuple)):
            klinks = "\n".join([str(x) for x in klinks if x])
        elif not isinstance(klinks, str):
            klinks = str(klinks) if klinks else ""
        out["keeplinks"] = klinks.strip()

        for raw_k, raw_v in (src or {}).items():
            k = norm_key(raw_k)
            if k in ("keeplinks", ""):
                continue
            vals = as_list(raw_v)
            if not vals:
                continue
            out[k] = vals

        return out


# ====================================
# ReplaceLinksDialog: manage link replacement
# ====================================
class ReplaceLinksDialog(QDialog):
    """Dialog to handle link replacement actions.

    Provides legacy buttons for adding a manual link or creating a download
    folder, plus an optional checkbox allowing the user to select a local
    directory and treat the thread as already downloaded.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Replace Links")
        layout = QVBoxLayout(self)

        # Buttons for legacy actions (manual link / create folder)
        btn_layout = QHBoxLayout()
        self.add_link_btn = QPushButton("Add Manual Link")
        self.create_folder_btn = QPushButton("Create Download Folder")
        btn_layout.addWidget(self.add_link_btn)
        btn_layout.addWidget(self.create_folder_btn)
        layout.addLayout(btn_layout)

        # Local folder option
        self.use_local_cb = QCheckBox("Use local folder (pretend downloaded)")
        layout.addWidget(self.use_local_cb)

        folder_layout = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.select_btn = QPushButton("Select Folder…")
        folder_layout.addWidget(self.folder_edit)
        folder_layout.addWidget(self.select_btn)
        layout.addLayout(folder_layout)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(button_box)

        # Connections
        self.select_btn.clicked.connect(self._select_folder, type=Qt.QueuedConnection)
        button_box.accepted.connect(self.accept, type=Qt.QueuedConnection)
        button_box.rejected.connect(self.reject, type=Qt.QueuedConnection)

    # ------------------------------------------------------------------
    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.folder_edit.setText(os.path.normpath(folder))
            self.use_local_cb.setChecked(True)

    # ------------------------------------------------------------------
    def use_local_folder(self) -> bool:
        return self.use_local_cb.isChecked() and bool(self.folder_edit.text())

    # ------------------------------------------------------------------
    def selected_folder(self) -> str:
        return self.folder_edit.text()


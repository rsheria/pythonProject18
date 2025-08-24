from PyQt5.QtWidgets import QDialog, QLabel, QDialogButtonBox, QTextEdit, QVBoxLayout
from PyQt5.QtCore import Qt
# ====================================
# LinksDialog: عرْض الروابط بعد الرفع
# ====================================
class LinksDialog(QDialog):
    """Simple dialog to display uploaded links."""
    def __init__(self, thread_title, links_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Links for {thread_title}")
        layout = QVBoxLayout(self)

        # Display Keeplinks URL first if present
        keeplinks_url = links_dict.get("keeplinks")
        if keeplinks_url:
            layout.addWidget(QLabel("<b>Keeplinks URL:</b>"))
            keeplinks_edit = QTextEdit()
            if isinstance(keeplinks_url, (list, tuple)):
                keeplinks_edit.setPlainText("\n".join(str(u) for u in keeplinks_url))
            else:
                keeplinks_edit.setPlainText(str(keeplinks_url))
            keeplinks_edit.setReadOnly(True)
            layout.addWidget(keeplinks_edit)

        # Order hosts: mega/mega.nz, then others alphabetically
        order = []
        if "mega" in links_dict:
            order.append("mega")
        elif "mega.nz" in links_dict:
            order.append("mega.nz")
        for host in sorted(h for h in links_dict if h not in order and h != "keeplinks"):
            order.append(host)

        for host in order:
            urls = links_dict.get(host)
            if not urls:
                continue
            layout.addWidget(QLabel(f"<b>{host.capitalize()} URLs:</b>"))
            edit = QTextEdit()
            if isinstance(urls, (list, tuple)):
                edit.setPlainText("\n".join(urls))
            else:
                edit.setPlainText(str(urls))
            edit.setReadOnly(True)
            layout.addWidget(edit)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject, type=Qt.QueuedConnection)
        layout.addWidget(button_box)



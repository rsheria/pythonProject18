from __future__ import annotations

import json
import logging
import os
from datetime import datetime

import requests
from PyQt5.QtCore import (QDate, QThreadPool, QRunnable, QObject, pyqtSignal,
                          Qt)
from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QDateEdit, QPushButton, QTableView, QProgressBar)

from core.user_manager import get_user_manager


class _WorkerSignals(QObject):
    finished = pyqtSignal(str, dict)


class _StatsWorker(QRunnable):
    def __init__(self, site: str, session: requests.Session, date_from: str, date_to: str, signals: _WorkerSignals):
        super().__init__()
        self.site = site
        self.session = session
        self.date_from = date_from
        self.date_to = date_to
        self.signals = signals

    def run(self) -> None:
        stats = {}
        try:
            if self.site == "rapidgator":
                url = (
                    f"https://rapidgator.net/api/v2/user/premium_stats?date_from={self.date_from}&date_to={self.date_to}"
                )
                resp = self.session.get(url, timeout=20)
                data = resp.json().get("response", {})
                stats = {
                    "dl": int(data.get("total_downloads", 0)),
                    "dl_rev": float(data.get("downloads_money", 0)),
                    "sales": int(data.get("sales", 0)),
                    "sales_rev": float(data.get("sales_money", 0)),
                }
            elif self.site == "nitroflare":
                params = {
                    "action": "fetchPPS",
                    "from": self.date_from,
                    "to": self.date_to,
                }
                resp = self.session.get(
                    "https://nitroflare.com/ajax/affiliates.php",
                    params=params,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                    timeout=20,
                )
                data = resp.json() if resp.content else []
                dl = dl_rev = sales = sales_rev = 0.0
                if isinstance(data, list):
                    import re
                    for row in data:
                        ppd = row.get("ppd", "0/0")
                        m = re.search(r"(\d+)\s*/\s*\$?([\d.,]+)", ppd)
                        if m:
                            dl += int(m.group(1))
                            dl_rev += float(m.group(2).replace(",", ""))
                        sales_str = row.get("sales", "0/0")
                        m = re.search(r"(\d+)\s*/\s*\$?([\d.,]+)", sales_str)
                        if m:
                            sales += int(m.group(1))
                            sales_rev += float(m.group(2).replace(",", ""))
                stats = {
                    "dl": int(dl),
                    "dl_rev": float(dl_rev),
                    "sales": int(sales),
                    "sales_rev": float(sales_rev),
                }
            elif self.site == "dddownload":
                url = (
                    f"https://ddownload.com/?op=my_reports&ajax=1&date1={self.date_from}&date2={self.date_to}"
                )
                r = self.session.get(url, timeout=20)
                data = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
                stats = {
                    "dl": int(data.get("downloads", 0)),
                    "dl_rev": float(data.get("profit_dl", 0)),
                    "sales": int(data.get("sales", 0)),
                    "sales_rev": float(data.get("profit_sales", 0)),
                }
            elif self.site == "katfile":
                url = f"https://katfile.com/?op=my_reports&ajax=1&date1={self.date_from}&date2={self.date_to}"
                r = self.session.get(url, timeout=20)
                data = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
                stats = {
                    "dl": int(data.get("downloads", 0)),
                    "dl_rev": float(data.get("profit_dl", 0)),
                    "sales": int(data.get("sales", 0)),
                    "sales_rev": float(data.get("profit_sales", 0)),
                }
            elif self.site == "keeplinks":
                r = self.session.get("https://www.keeplinks.org/earnings", timeout=20)
                import re

                m = re.search(r"table.table-bordered.*?<tr>.*?<td[^>]*>([^<]+)", r.text, re.S)
                val = m.group(1) if m else "0"
                stats = {"dl": 0, "dl_rev": 0.0, "sales": 0, "sales_rev": 0.0, "revenue": float(val.replace("$", "").replace("€", ""))}
        except Exception as exc:
            logging.error(f"Stats fetch failed for {self.site}: {exc}")
        self.signals.finished.emit(self.site, stats)


class StatsWidget(QWidget):
    data_loaded = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.user_manager = get_user_manager()
        self.thread_pool = QThreadPool()
        self.results: list[tuple[str, dict]] = []

        self._init_ui()
        self.data_loaded.connect(self._append_history)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("From"))
        self.from_date = QDateEdit(QDate.currentDate())
        self.from_date.setCalendarPopup(True)
        range_row.addWidget(self.from_date)
        range_row.addWidget(QLabel("To"))
        self.to_date = QDateEdit(QDate.currentDate())
        self.to_date.setCalendarPopup(True)
        range_row.addWidget(self.to_date)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        range_row.addWidget(self.refresh_btn)
        layout.addLayout(range_row)

        self.table = QTableView()
        self.model = QStandardItemModel(0, 4, self)
        self.model.setHorizontalHeaderLabels(["Site", "Downloads", "Sales", "Revenue"])
        self.table.setModel(self.model)
        layout.addWidget(self.table)

        bars = QHBoxLayout()
        bars.addWidget(QLabel("Downloads"))
        self.dl_bar = QProgressBar()
        self.dl_bar.setTextVisible(True)
        bars.addWidget(self.dl_bar)
        bars.addWidget(QLabel("Revenue"))
        self.rev_bar = QProgressBar()
        self.rev_bar.setTextVisible(True)
        bars.addWidget(self.rev_bar)
        layout.addLayout(bars)

    def start_auto_refresh(self) -> None:
        self.refresh()

    def clear(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        self.dl_bar.reset()
        self.rev_bar.reset()

    # --------------------------------------------------------------
    def refresh(self) -> None:
        sites = self.user_manager.get_user_setting("sites", {})
        sites = {k: v for k, v in sites.items() if v}
        if not sites:
            logging.info("StatsWidget: No site accounts configured")
            self.model.removeRows(0, self.model.rowCount())
            self.model.appendRow([
                QStandardItem("No accounts"),
                QStandardItem("-"),
                QStandardItem("-"),
                QStandardItem("-"),
            ])
            self.dl_bar.reset()
            self.rev_bar.reset()
            return

        self.results = []
        self._pending = len(sites)
        date_from = self.from_date.date().toString("yyyy-MM-dd")
        date_to = self.to_date.date().toString("yyyy-MM-dd")

        for site in sites.keys():
            session = self.user_manager.get_session(site)
            if not session:
                self._pending -= 1
                continue
            signals = _WorkerSignals()
            signals.finished.connect(self._on_worker_finished)
            worker = _StatsWorker(site, session, date_from, date_to, signals)
            self.thread_pool.start(worker)

    def _on_worker_finished(self, site: str, data: dict) -> None:
        self.results.append((site, data))
        self._pending -= 1
        if self._pending <= 0:
            self._update_view()

    def _update_view(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        total_dl = 0
        total_sales = 0
        total_rev = 0.0
        for site, data in self.results:
            dl = int(data.get("dl", 0))
            sales = int(data.get("sales", 0))
            revenue = float(data.get("dl_rev", 0)) + float(data.get("sales_rev", 0)) + float(data.get("revenue", 0))
            total_dl += dl
            total_sales += sales
            total_rev += revenue
            self.model.appendRow([
                QStandardItem(site.title()),
                QStandardItem(str(dl)),
                QStandardItem(str(sales)),
                QStandardItem(f"{revenue:.2f}"),
            ])
            record = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "site": site,
                "dl": dl,
                "dl_rev": float(data.get("dl_rev", 0)),
                "sales": sales,
                "sales_rev": float(data.get("sales_rev", 0)),
            }
            self.data_loaded.emit(record)
        # totals
        self.model.appendRow([
            QStandardItem("Total"),
            QStandardItem(str(total_dl)),
            QStandardItem(str(total_sales)),
            QStandardItem(f"{total_rev:.2f}"),
        ])

        target = self.user_manager.get_user_setting("stats_target", {"daily_downloads": 0, "daily_revenue": 0})
        self.dl_bar.setMaximum(int(target.get("daily_downloads", 0)))
        self.dl_bar.setValue(total_dl)
        self.rev_bar.setMaximum(int(target.get("daily_revenue", 0)))
        self.rev_bar.setValue(int(total_rev))

    def _append_history(self, record: dict) -> None:
        try:
            path = self.user_manager.get_user_data_path("stats_history.json")
            history = []
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    history = json.load(fh)
            history.append(record)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(history, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            logging.error(f"Failed to append stats history: {exc}")
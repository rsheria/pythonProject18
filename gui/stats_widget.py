from __future__ import annotations

"""StatsWidget – fetches & displays per-site earnings/downloads in the background.
   v3.1 – fixes Rapidgator None, Kat/DDDownload empty list, SSL fallback, and
   merges KeepLinks revenue into total revenue column.
"""

import json
import logging
import os
import re
import warnings
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List

import requests
from PyQt5.QtCore import QDate, QRunnable, QThreadPool, QObject, pyqtSignal
from PyQt5.QtGui import QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.user_manager import get_user_manager

_LOG = logging.getLogger(__name__)
_PAIR_RE = re.compile(r"(\d+)\s*/\s*[\$€]?\s*([\d.,]+)")

def _as_decimal(val: str) -> Decimal:
    """Return Decimal without thousands separators."""
    val = (val or "").strip()
    val = val.replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    if "," in val and "." in val:
        val = val.replace(",", "")
    else:
        val = val.replace(",", ".")
    try:
        return Decimal(val)
    except Exception:
        return Decimal("0")

# ignore InsecureRequestWarning when we fall back to verify=False
warnings.filterwarnings("ignore", message="Unverified HTTPS request*")


# --------------------------------------------------------------------------- #
#                               Worker classes                                #
# --------------------------------------------------------------------------- #
class _WorkerSignals(QObject):
    finished = pyqtSignal(str, dict)


class _StatsWorker(QRunnable):
    """Background worker that fetches stats for a single site."""

    def __init__(
        self,
        site: str,
        session: requests.Session,
        date_from: str,
        date_to: str,
        signals: _WorkerSignals,
    ) -> None:
        super().__init__()
        self.site = site
        self.session = session
        self.date_from = date_from
        self.date_to = date_to
        self.signals = signals

    # ------------------------- helpers ---------------------------------- #
    def _safe_json(self, resp: requests.Response) -> Any:
        """Return resp.json() with graceful fallback."""
        try:
            return resp.json()
        except ValueError:
            _LOG.debug("%s raw: %s", self.site, resp.text[:200])
            return [] if resp.text.strip().startswith("[") else {}

    def _parse_pair(self, s: str) -> tuple[int, float]:
        """'15 / $3.20' → (15, 3.20)"""
        m = _PAIR_RE.search(s or "")
        return (int(m.group(1)), float(_as_decimal(m.group(2)))) if m else (0, 0.0)

    def _safe_get(self, url: str, **kw) -> requests.Response:
        """GET with retry over HTTP+verify=False if SSL handshake fails."""
        try:
            return self.session.get(url, timeout=20, **kw)
        except requests.exceptions.SSLError:
            _LOG.warning("SSL handshake failed for %s – retrying insecure", url)
            insecure_url = url.replace("https://", "http://", 1)
            return self.session.get(insecure_url, timeout=20, verify=False, **kw)

    def _safe_post(self, url: str, **kw) -> requests.Response:
        """POST with retry over HTTP+verify=False if SSL handshake fails."""
        try:
            return self.session.post(url, timeout=20, **kw)
        except requests.exceptions.SSLError:
            _LOG.warning("SSL handshake failed for %s – retrying insecure", url)
            insecure_url = url.replace("https://", "http://", 1)
            return self.session.post(insecure_url, timeout=20, verify=False, **kw)


    # ------------------------- main run ---------------------------------- #
    def run(self) -> None:  # noqa: D401
        stats: Dict[str, Any] = {"dl": 0, "dl_rev": 0.0, "sales": 0, "sales_rev": 0.0}
        try:
            # ------- Rapidgator -------------------------------------------------
            if self.site == "rapidgator":
                payload = {
                    "from": self.date_from,
                    "to": self.date_to,
                    "draw": "1",
                    "start": "0",
                    "length": "1000",
                    "search[value]": "",
                    "order[0][column]": "0",
                    "order[0][dir]": "asc",
                }
                resp = self._safe_post(
                    "https://rapidgator.net/stat/statfiles",
                    data=payload,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                try:
                    data = resp.json()
                except Exception:
                    _LOG.debug("%s raw: %s", self.site, resp.text[:300])
                    data = {}
                if isinstance(data, dict):
                    for row in data.get("data", []):
                        if isinstance(row, list) and row and row[0] == self.date_from:
                            stats = {
                                "dl": int(row[1]),
                                "dl_rev": float(_as_decimal(str(row[2]))),
                                "sales": int(row[3]),
                                "sales_rev": float(_as_decimal(str(row[4]))),
                            }
                            break

            # ------- Nitroflare -------------------------------------------------
            elif self.site == "nitroflare":
                #
                # Step 1 – warm‑up: visit the affiliate page once to let the
                #          server set any extra cookies / CSRF token
                #
                self.session.get(
                    "https://nitroflare.com/member?s=affiliates",
                    timeout=15,
                )

                #
                # Step 2 – call the JSON endpoint with an explicit Referer
                #
                body = (
                    f"action=fetchPPS&from={self.date_from}&to={self.date_to}"
                )
                resp = self._safe_post(
                    "https://nitroflare.com/ajax/affiliates.php",
                    data=body,
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": "https://nitroflare.com/member?s=affiliates",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    },
                    timeout=20,
                )

                try:
                    rows = resp.json()
                except Exception:
                    _LOG.debug("%s raw: %s", self.site, resp.text[:300])
                    rows = []

                dl = dl_rev = sales = sales_rev = 0.0


                for row in rows:
                    row_date = str(row.get("date") or row.get("day") or "")
                    if row_date and not (self.date_from <= row_date <= self.date_to):
                        continue

                    dl_i, rev_i = self._parse_pair(row.get("ppd", "0/0"))
                    dl += dl_i
                    dl_rev += rev_i

                    sales_i, sales_rev_i = self._parse_pair(row.get("sales", "0/0"))
                    sales += sales_i
                    sales_rev += sales_rev_i

                stats = {
                    "dl": int(dl),
                    "dl_rev": float(dl_rev),
                    "sales": int(sales),
                    "sales_rev": float(sales_rev),
                }

            # ------- DDDownload & KatFile ---------------------------------------
            elif self.site in {"dddownload", "katfile"}:
                base = "dddownload.com" if self.site == "dddownload" else "katfile.com"
                url = (
                    f"https://{base}/?op=my_reports&ajax=1"
                    f"&date1={self.date_from}&date2={self.date_to}"
                )
                rows = self._safe_json(self._safe_get(url))
                row: Dict[str, Any] = {}
                if isinstance(rows, list) and rows:
                    row = next((r for r in rows if r.get("day") == self.date_from), rows[-1])
                elif isinstance(rows, dict):
                    row = rows
                stats.update(
                    dl=int(row.get("downloads", 0)),
                    dl_rev=float(row.get("profit_dl", 0)),
                    sales=int(row.get("sales", 0)),
                    sales_rev=float(row.get("profit_sales", 0)),
                )

            # ------- KeepLinks ---------------------------------------------------
            elif self.site == "keeplinks":
                html = self._safe_get("https://www.keeplinks.org/earnings").text
                m = re.search(r"Today's Earnings</th>.*?<td[^>]*>([\d.]+)", html, re.S)
                today_rev = float(m.group(1)) if m else 0.0
                stats = {"dl": 0, "dl_rev": today_rev, "sales": 0, "sales_rev": 0.0}

        except Exception as exc:  # pragma: no cover
            _LOG.error("Stats fetch failed for %s: %s", self.site, exc, exc_info=False)
        finally:
            self.signals.finished.emit(self.site, stats)


# --------------------------------------------------------------------------- #
#                                StatsWidget UI                               #
# --------------------------------------------------------------------------- #
class StatsWidget(QWidget):
    data_loaded = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.user_manager = get_user_manager()
        self.thread_pool = QThreadPool.globalInstance()
        self.results: List[tuple[str, Dict[str, Any]]] = []
        self._pending = 0

        self._build_ui()
        self.data_loaded.connect(self._save_history)

    # ------------------------- UI ---------------------------------------- #
    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)

        # date pickers row
        row = QHBoxLayout()
        self.from_date = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.to_date = QDateEdit(QDate.currentDate(), calendarPopup=True)
        row.addWidget(QLabel("From"))
        row.addWidget(self.from_date)
        row.addWidget(QLabel("To"))
        row.addWidget(self.to_date)
        self.refresh_btn = QPushButton("Refresh", clicked=self.refresh)
        row.addWidget(self.refresh_btn)
        lay.addLayout(row)

        # table
        self.table = QTableView()
        self.model = QStandardItemModel(0, 4, self)
        self.model.setHorizontalHeaderLabels(["Site", "Downloads", "Sales", "Revenue"])
        self.table.setModel(self.model)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)

        # progress bars
        bars = QHBoxLayout()
        bars.addWidget(QLabel("Downloads"))
        self.dl_bar = QProgressBar(textVisible=True)
        bars.addWidget(self.dl_bar)
        bars.addWidget(QLabel("Revenue"))
        self.rev_bar = QProgressBar(textVisible=True)
        bars.addWidget(self.rev_bar)
        lay.addLayout(bars)

    # ------------------------- external API ------------------------------ #
    def start_auto_refresh(self) -> None:
        self.refresh()

    def clear(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        self.dl_bar.reset()
        self.rev_bar.reset()

    # ------------------------- refresh logic ----------------------------- #
    def refresh(self) -> None:
        site_cfg = self.user_manager.get_user_setting("sites", {}) or {}
        if not site_cfg:
            self._show_row("No accounts configured")
            return

        self.results.clear()
        self.model.removeRows(0, self.model.rowCount())
        self._pending = len(site_cfg)

        d_from = self.from_date.date().toString("yyyy-MM-dd")
        d_to = self.to_date.date().toString("yyyy-MM-dd")

        for site in site_cfg.keys():
            sess = self.user_manager.get_session(site)
            if not sess:
                _LOG.warning("No session for %s", site)
                self._pending -= 1
                continue
            sig = _WorkerSignals()
            sig.finished.connect(self._on_worker_done)
            self.thread_pool.start(_StatsWorker(site, sess, d_from, d_to, sig))

    # ------------------------- call-backs -------------------------------- #
    def _show_row(self, msg: str) -> None:
        self.model.appendRow([QStandardItem(msg)] + [QStandardItem("-") for _ in range(3)])

    def _on_worker_done(self, site: str, data: Dict[str, Any]) -> None:
        self.results.append((site, data))
        self._pending -= 1
        if self._pending == 0:
            self._render()

    # ------------------------- rendering --------------------------------- #
    def _render(self) -> None:
        total_dl = total_sales = 0
        total_rev = Decimal("0")
        self.model.removeRows(0, self.model.rowCount())

        for site, d in self.results:
            dl = int(d.get("dl", 0))
            sales = int(d.get("sales", 0))
            rev = Decimal(str(d.get("dl_rev", 0))) + Decimal(str(d.get("sales_rev", 0)))
            total_dl += dl
            total_sales += sales
            total_rev += rev
            self.model.appendRow(
                [
                    QStandardItem(site.title()),
                    QStandardItem(str(dl)),
                    QStandardItem(str(sales)),
                    QStandardItem(f"{rev:.3f}"),
                ]
            )
            # emit for history
            self.data_loaded.emit(
                {
                    "date": date.today().isoformat(),
                    "site": site,
                    "dl": dl,
                    "dl_rev": float(d.get("dl_rev", 0)),
                    "sales": sales,
                    "sales_rev": float(d.get("sales_rev", 0)),
                }
            )

        # total row
        self.model.appendRow(
            [
                QStandardItem("TOTAL"),
                QStandardItem(str(total_dl)),
                QStandardItem(str(total_sales)),
                QStandardItem(f"{total_rev:.3f}"),
            ]
        )

        target = self.user_manager.get_user_setting("stats_target", {})
        self.dl_bar.setMaximum(int(target.get("daily_downloads", 0)))
        self.dl_bar.setValue(total_dl)
        self.rev_bar.setMaximum(int(target.get("daily_revenue", 0)))
        self.rev_bar.setValue(int(total_rev))

    # ------------------------- persistence ------------------------------- #
    def _save_history(self, record: dict) -> None:
        """Append a single stats record to stats_history.json safely."""
        try:
            path = self.user_manager.get_user_data_path("stats_history.json")
            history: List[dict] = []
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    history = json.load(fh)
            history.append(record)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(history, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            _LOG.error("Failed to save stats history: %s", exc, exc_info=False)

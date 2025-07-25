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
from bs4 import BeautifulSoup
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
                # Build URL e.g. /stat/statfiles?start_date=2025-07-24&end_date=2025-07-24
                url = (
                    "https://rapidgator.net/stat/statfiles"
                    f"?start_date={self.date_from}&end_date={self.date_to}"
                )
                resp = self._safe_get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )

                soup = BeautifulSoup(resp.text, "html.parser")
                first_row = soup.select_one("table.items tbody tr.odd")
                if not first_row:
                    raise RuntimeError("Rapidgator: stats row not found")

                cells = first_row.find_all("td")
                # cells layout:
                # 0=date  1=downloads  2=sales  7=earned
                def _num(txt):
                    m = re.search(r"\\d+", txt)
                    return int(m.group()) if m else 0

                def _money(txt):
                    m = re.search(r"[\\d.]+", txt)
                    return float(m.group()) if m else 0.0

                _stats = {
                    "dl": _num(cells[1].text),
                    "dl_rev": _money(cells[1].text.split("(")[-1]),
                    "sales": _num(cells[2].text),
                    "sales_rev": _money(cells[2].text.split("(")[-1]),
                }

                # Fallback: if both rev fields are 0 take value from total earned
                if not _stats["dl_rev"] and not _stats["sales_rev"]:
                    _stats["dl_rev"] = _stats["sales_rev"] = _money(cells[7].text)

                stats = _stats

            # ------- Nitroflare -------------------------------------------------
            elif self.site == "nitroflare":
                # -----------------------------------------------------------------
                # New HTML/AJAX workflow – call the backend used by affiliate.js
                # -----------------------------------------------------------------
                # Warm-up: ensure cookies/csrf tokens are set
                self.session.get(
                    "https://nitroflare.com/member?s=affiliates",
                    timeout=15,
                )
                headers = {
                    "User-Agent": "Mozilla/5.0",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": "https://nitroflare.com/member?s=affiliates",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                }

                # Pre-flight request to set CSRF randHash
                self._safe_post(
                    "https://nitroflare.com/ajax/randHash.php",
                    data={"randHash": "0"},
                    headers=headers,
                )

                url = "https://nitroflare.com/member/ajax/affiliate.php"
                payload = {
                    "type": "fetchPPS",
                    "from": self.date_from,   # YYYY-MM-DD
                    "to":   self.date_to,     # YYYY-MM-DD
                }

                resp = self._safe_post(url, data=payload, headers=headers)

                if resp.status_code == 404 or not resp.text.strip():
                    _LOG.warning("NitroFlare: stats row not found")
                else:
                    # The endpoint returns plain <tr> rows, NOT full HTML
                    soup = BeautifulSoup("<table>%s</table>" % resp.text, "html.parser")
                    row = soup.select_one("tr")
                    if not row:
                        raise RuntimeError("NitroFlare: stats row not found")

                    cells = row.find_all("td")

                    def _num(s):
                        m = re.search(r"\\d+", s)
                        return int(m.group()) if m else 0

                    def _money(s):
                        m = re.search(r"([\\d.]+)\\$?", s)
                        return float(m.group(1)) if m else 0.0

                    sales_str = cells[1].text
                    ppd_dl_str = cells[2].text
                    total_dl_str = cells[3].text
                    total_rev_str = cells[6].text

                    sales_cnt = _num(sales_str.split("/")[0])
                    sales_rev = _money(sales_str)

                    unique_dl_cnt = _num(ppd_dl_str.split("/")[0])
                    unique_dl_rev = _money(ppd_dl_str)

                    total_dl = _num(total_dl_str)
                    total_rev = _money(total_rev_str)

                    stats.update(
                        dl=unique_dl_cnt, # Assuming 'total unique downloads' refers to PPD Unique DLs
                        dl_rev=unique_dl_rev, # Assuming 'revenue from downloads' refers to PPD Unique DLs revenue
                        sales=sales_cnt,
                        sales_rev=sales_rev,
                    )
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
                    row = next((r for r r in rows if r.get("day") == self.date_from), rows[-1])
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
                m = re.search(r"Today's Earnings</th>.*?<td[^>]*>([\\d.]+)", html, re.S)
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


# New function for Nitroflare scraping
def scrape_nitroflare_stats(session: requests.Session, date_from: str, date_to: str):
    stats = {"dl": 0, "dl_rev": 0.0, "sales": 0, "sales_rev": 0.0}
    try:
        # Warm-up: ensure cookies/csrf tokens are set
        session.get(
            "https://nitroflare.com/member?s=affiliates",
            timeout=15,
        )
        headers = {
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://nitroflare.com/member?s=affiliates",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

        # Pre-flight request to set CSRF randHash
        session.post(
            "https://nitroflare.com/ajax/randHash.php",
            data={"randHash": "0"},
            headers=headers,
        )

        url = "https://nitroflare.com/member/ajax/affiliate.php"
        payload = {
            "type": "fetchPPS",
            "from": date_from,   # YYYY-MM-DD
            "to":   date_to,     # YYYY-MM-DD
        }

        resp = session.post(url, data=payload, headers=headers)

        if resp.status_code == 404 or not resp.text.strip():
            print("NitroFlare: stats row not found")
        else:
            # The endpoint returns plain <tr> rows, NOT full HTML
            soup = BeautifulSoup("<table>%s</table>" % resp.text, "html.parser")
            row = soup.select_one("tr")
            if not row:
                raise RuntimeError("NitroFlare: stats row not found")

            cells = row.find_all("td")

            def _num(s):
                m = re.search(r"\\d+", s)
                return int(m.group()) if m else 0

            def _money(s):
                m = re.search(r"([\\d.]+)\\$?", s)
                return float(m.group(1)) if m else 0.0

            sales_str = cells[1].text
            ppd_dl_str = cells[2].text
            total_dl_str = cells[3].text
            total_rev_str = cells[6].text

            sales_cnt = _num(sales_str.split("/")[0])
            sales_rev = _money(sales_str)

            unique_dl_cnt = _num(ppd_dl_str.split("/")[0])
            unique_dl_rev = _money(ppd_dl_str)

            total_dl = _num(total_dl_str)
            total_rev = _money(total_rev_str)

            stats.update(
                dl=unique_dl_cnt, # Assuming 'total unique downloads' refers to PPD Unique DLs
                dl_rev=unique_dl_rev, # Assuming 'revenue from downloads' refers to PPD Unique DLs revenue
                sales=sales_cnt,
                sales_rev=sales_rev,
            )
    except Exception as exc:
        print(f"Stats fetch failed for Nitroflare: {exc}")
    return stats




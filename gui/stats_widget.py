from __future__ import annotations

"""StatsWidget – fetches & displays per-site earnings/downloads in the background.
   v3.1 – fixes Rapidgator None, Kat/DDownload empty list, SSL fallback, and
   merges KeepLinks revenue into total revenue column.
"""

import json
import logging
import os
import re
import warnings
import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List
from bs4 import BeautifulSoup
import requests
from requests.exceptions import SSLError, ConnectionError
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
# Mapping of alternate site identifiers to canonical names
SITE_ALIASES = {
    "dddownload": "ddownload",
}

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
        self.site = SITE_ALIASES.get(site.lower(), site.lower())
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
        """GET with retry disabling SSL verification, then downgrading to HTTP."""
        try:
            return self.session.get(url, timeout=20, **kw)
        except (SSLError, ConnectionError):
            if "ddownload.com" in url:
                _LOG.warning("TLS error for %s – retrying with verify=False", url)
                return self.session.get(url, timeout=20, verify=False, **kw)
            _LOG.warning("HTTPS failed for %s – retrying over HTTP", url)
            insecure_url = url.replace("https://", "http://", 1)
            return self.session.get(insecure_url, timeout=20, verify=False, **kw)


    def _safe_post(self, url: str, **kw) -> requests.Response:
        """POST with retry disabling SSL verification, then downgrading to HTTP."""
        try:
            return self.session.post(url, timeout=20, **kw)
        except (SSLError, ConnectionError):
            if "ddownload.com" in url:
                _LOG.warning(
                    "SSL handshake failed for %s – retrying with verify=False", url
                )
                return self.session.post(url, timeout=20, verify=False, **kw)
            _LOG.warning("HTTPS failed for %s – retrying over HTTP", url)
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
                rows = soup.select("table.items tbody tr")
                if not rows:
                    raise RuntimeError("Rapidgator: stats rows not found")

                def _num(txt: str) -> int:
                    m = re.search(r"\d+", txt)
                    return int(m.group()) if m else 0

                def _money(txt: str) -> float:
                    m = re.search(r"[\d.]+", txt)
                    return float(m.group()) if m else 0.0

                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) < 8:
                        continue

                    # skip total row to avoid double-counting
                    date_text = cells[0].get_text(strip=True).lower()
                    if not re.match(r"\d{4}-\d{2}-\d{2}", date_text):
                        continue

                    dl = _num(cells[1].text)
                    dl_rev = _money(cells[1].text.split("(")[-1])
                    sales = _num(cells[2].text)
                    sales_rev = _money(cells[2].text.split("(")[-1])


                    # Fallback: if both rev fields are 0 take value from total earned
                    if not dl_rev and not sales_rev:
                        fallback = _money(cells[7].text)
                        dl_rev = sales_rev = fallback

                    stats["dl"] += dl
                    stats["dl_rev"] += dl_rev
                    stats["sales"] += sales
                    stats["sales_rev"] += sales_rev


            # ------- Nitroflare -------------------------------------------------
            elif self.site == "nitroflare":
                from utils.nitroflare_stats import get_nitroflare_stats
                nf_stats = get_nitroflare_stats(self.session, self.date_from, self.date_to)
                stats.update(nf_stats)

            # ------- DDownload & KatFile ---------------------------------------
            elif self.site == "ddownload":

                base_url = (
                    "https://ddownload.com/"
                    f"?op=my_reports&date1={self.date_from}&date2={self.date_to}&show=Show"
                )
                resp = self._safe_get(
                    base_url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Referer": "https://ddownload.com/",
                    },
                )
                m = re.search(r"var\s+data\s*=\s*(\[[^\]]+\])", resp.text)
                if not m:
                    raise RuntimeError("DDownload: data array not found")

                rows = json.loads(m.group(1))
                for row in rows:
                    stats["dl"] += int(row.get("downloads", 0))
                    stats["dl_rev"] += float(row.get("profit_dl", 0))
                    stats["sales"] += int(row.get("sales", 0))
                    stats["sales_rev"] += float(row.get("profit_sales", 0))

            elif self.site == "katfile":
                base_url = (
                    "https://katfile.com/"
                    f"?op=my_reports&date1={self.date_from}&date2={self.date_to}&show=Show"

                )
                resp = self._safe_get(
                    base_url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Referer": "https://katfile.com/",
                    },
                )

                m = re.search(r"var\s+data\s*=\s*(\[[^\]]+\])", resp.text)
                if not m:
                    raise RuntimeError("KatFile: data array not found")

                rows = json.loads(m.group(1))
                for row in rows:
                    stats["dl"] += int(row.get("downloads", 0))
                    stats["dl_rev"] += float(row.get("profit_dl", 0))
                    stats["sales"] += int(row.get("sales", 0))
                    stats["sales_rev"] += float(row.get("profit_sales", 0))

            # ------- KeepLinks ---------------------------------------------------
            # ------- Keeplinks -------------------------------------------------
            elif self.site == "keeplinks":
                stats = {"dl": 0, "dl_rev": 0.0, "sales": 0, "sales_rev": 0.0}

                start = date.fromisoformat(self.date_from)
                end   = date.fromisoformat(self.date_to)
                month_cache: dict[tuple[int, int], dict[int, float]] = {}

                cur = start
                while cur <= end:
                    ym = (cur.year, cur.month)

                    if ym not in month_cache:
                        url = (
                            "https://www.keeplinks.org/newgraph.php"
                            f"?act=dailyearnings&month={ym[1]:02d}"
                            f"&year={ym[0]}&rand={random.random()}"
                        )

                        # نفس الـ headers بتاعة الـ cURL
                        resp = self._safe_get(
                            url,
                            headers={
                                "Accept": "text/html, */*; q=0.01",
                                "Accept-Language": "en-US,en;q=0.9",
                                "Referer": (
                                    "https://www.keeplinks.org/earnings"
                                    f"?month={ym[1]:02d}&year={ym[0]}"
                                ),
                                "User-Agent": (
                                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                                    "Chrome/138.0.0.0 Safari/537.36"
                                ),
                                "X-Requested-With": "XMLHttpRequest",
                            },
                        )

                        # regex أوسع: يلتقط اليوم والقيمة أياً كان عدد المسافات
                        pattern = re.compile(
                            r"""\[
                                 '(\d{2})-\d{2}-\d{4}\s*\([^']*\)'\s*,      # اليوم
                                 \s*([\d.]+)                                # القيمة
                               \]""",
                            re.VERBOSE,
                        )
                        daily_data = {
                            int(day): float(val) for day, val in pattern.findall(resp.text)
                        }
                        month_cache[ym] = daily_data
                        _LOG.debug("Keeplinks %s‑%02d → %d days parsed",
                                   ym[0], ym[1], len(daily_data))

                    # اجمع ربح اليوم لو موجود
                    stats["dl_rev"] += month_cache[ym].get(cur.day, 0.0)
                    cur += timedelta(days=1)




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

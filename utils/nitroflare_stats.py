import re
import requests
from bs4 import BeautifulSoup
from typing import Dict


def get_nitroflare_stats(session: requests.Session, date_from: str, date_to: str) -> Dict[str, float | int]:
    """Fetch NitroFlare affiliate stats between two dates."""
    stats = {"dl": 0, "dl_rev": 0.0, "sales": 0, "sales_rev": 0.0}
    try:
        # Warm-up to establish session cookies
        session.get(
            "https://nitroflare.com/member?s=affiliates",
            timeout=15,
        )

        headers = {
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://nitroflare.com/member?s=affiliates",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        rand_hash = session.cookies.get("randHash", "0")
        session.post(
            "https://nitroflare.com/ajax/randHash.php",
            data={"randHash": rand_hash},
            headers=headers,
        )

        url = "https://nitroflare.com/ajax/affiliate/reports.php"
        payload = {
            "method": "fetchPPS",
            "from": date_from,
            "to": date_to,
            "page": 1,
        }

        resp = session.post(url, data=payload, headers=headers)
        if resp.status_code != 200:
            return stats

        data = resp.json()
        # New API returns JSON like:
        # {"days":0,"data":{"2025-07-25":{"profAmount":0,"profCount":0,
        #   "refAmount":0,"refCount":0,"bnrAmount":0,"bnrCount":0,
        #   "ppdCount":"6","ppdAmount":0.018,"dlsCount":8}}}

        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            day_data = next(iter(data["data"].values()), {})
            sales_cnt = int(day_data.get("profCount", 0))
            sales_rev = float(day_data.get("profAmount", 0))
            unique_dl_cnt = int(day_data.get("ppdCount", 0))
            unique_dl_rev = float(day_data.get("ppdAmount", 0))
            stats.update(
                dl=unique_dl_cnt,
                dl_rev=unique_dl_rev,
                sales=sales_cnt,
                sales_rev=sales_rev,
            )
            return stats

        html = data.get("html") if isinstance(data, dict) else resp.text
        if not html:
            return stats

        soup = BeautifulSoup("<table>%s</table>" % html, "html.parser")
        row = soup.select_one("tr")
        if not row:
            return stats

        cells = row.find_all("td")

        def _num(s: str) -> int:
            m = re.search(r"\d+", s)
            return int(m.group()) if m else 0

        def _money(s: str) -> float:
            m = re.search(r"([\d.]+)\$?", s)
            return float(m.group(1)) if m else 0.0

        sales_str = cells[1].text
        ppd_dl_str = cells[2].text
        total_dl_str = cells[3].text
        total_rev_str = cells[6].text

        sales_cnt = _num(sales_str.split("/")[0])
        sales_rev = _money(sales_str)

        unique_dl_cnt = _num(ppd_dl_str.split("/")[0])
        unique_dl_rev = _money(ppd_dl_str)

        stats.update(
            dl=unique_dl_cnt,
            dl_rev=unique_dl_rev,
            sales=sales_cnt,
            sales_rev=sales_rev,
        )
    except Exception:
        pass
    return stats
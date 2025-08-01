from typing import Dict
import re
import requests
from bs4 import BeautifulSoup


def get_rapidgator_stats(session: requests.Session, day: str):
    url = (
        "https://rapidgator.net/stat/statfiles"
        f"?start_date={day}&end_date={day}"
    )

    resp = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9"
        },
        timeout=30            # هنا timeout واحد بس
    )
    resp.raise_for_status()
    # ... بقية الـ Parsing زى ما اتفقنا

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.select_one("table.items tbody")
    if not table:
        raise RuntimeError("stats table not found")

    first_row = table.find("tr", class_="odd")
    if not first_row:
        return {"downloads": 0, "sales": 0, "earned": 0.0}

    cells = first_row.find_all("td")
    downloads = int(re.search(r"\d+", cells[1].text).group())
    sales = int(re.search(r"\d+", cells[2].text).group())
    earned = float(re.search(r"[\d.]+", cells[7].text).group())

    return {"downloads": downloads, "sales": sales, "earned": earned}
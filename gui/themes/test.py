
from requests import Session
from utils.legacy_tls import DDownloadAdapter
s = Session()
s.mount("https://dddownload.com", DDownloadAdapter())
r = s.get("https://dddownload.com/?op=my_reports&date1=2025-07-25&date2=2025-07-25&show=Show", timeout=20)
print(r.status_code, len(r.content))


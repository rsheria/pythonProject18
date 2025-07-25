import pycurl, io, bs4, csv, json

REPORT_URL = ("https://www.dddownload.com/?op=my_reports"
              "&date1=2025-07-25&date2=2025-07-25&show=Show")
COOKIES = "login=rareclubsmovies@gmail.com; xfss=e4unyt61po30qx85; lang=english"

buf = io.BytesIO()
c = pycurl.Curl()
c.setopt(c.URL, REPORT_URL.encode())
c.setopt(c.COOKIE, COOKIES.encode())
c.setopt(c.USERAGENT, b"Mozilla/5.0")
c.setopt(c.SSLVERSION, c.SSLVERSION_TLSv1_2)
c.setopt(c.SSL_CIPHER_LIST, b"AES128-SHA")
c.setopt(c.WRITEDATA, buf)
c.perform()
c.close()

html = buf.getvalue().decode("utf-8", "ignore")
soup = bs4.BeautifulSoup(html, "lxml")
rows = [[td.text.strip() for td in tr.select("td")]
        for tr in soup.select("table[name='reports'] tbody tr") if tr.select("td")[0].text.strip()]

print(json.dumps(rows, indent=2, ensure_ascii=False))

# utils/sanitize.py
import unicodedata
import re

def sanitize_filename(text: str) -> str:
    """
    يُزيل الأحرف غير الصالحة من اسم الملف ويحوّله لأحرف ASCII،
    ثم يستبدل الفراغات بـ "_" ويقصّ الأطراف.
    """
    nf = unicodedata.normalize('NFKD', text)
    b  = nf.encode('ascii', 'ignore')
    s  = b.decode('ascii', 'ignore')
    s  = re.sub(r'[<>:"/\\|?*]', '', s)
    return s.replace(' ', '_').strip()

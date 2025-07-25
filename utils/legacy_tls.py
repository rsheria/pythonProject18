import ssl
from requests.adapters import HTTPAdapter

class DDownloadAdapter(HTTPAdapter):
    """Adapter يخلّى Requests يكلّم ddownload بنجاح."""

    def _ctx(self):
        # سياق مبنى يدوياً لتفعيل TLS‑1.2 أو أقل، و السماح بخوارزميات قديمة
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS)       # يسمح بكل النسخ ≤ 1.2
        ctx.options |= getattr(ssl, "OP_NO_TLSv1_3", 0)   # أقفل TLS‑1.3
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")       # ↓↓ أهم سطر ↓↓
        ctx.check_hostname = False                   # لتفادى clash مع verify=False
        return ctx

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ctx()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ctx()
        return super().proxy_manager_for(*args, **kwargs)

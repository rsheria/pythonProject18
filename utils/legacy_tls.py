import ssl
from urllib3.util.ssl_ import create_urllib3_context
from requests.adapters import HTTPAdapter

class DDownloadAdapter(HTTPAdapter):
    """Adapter يفرض استخدام Ciphers أضعف لـ ddownload فقط."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.check_hostname = False
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.check_hostname = False
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
        kwargs["ssl_context"] = ctx
        return super().proxy_manager_for(*args, **kwargs)

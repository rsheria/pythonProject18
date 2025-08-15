# integrations/jd_client.py
# -*- coding: utf-8 -*-
import time
import logging
import os
from typing import List, Iterable, Optional

try:
    from myjdapi import Myjdapi
except Exception as e:
    raise ImportError("myjdapi is required. Install via: pip install myjdapi") from e

log = logging.getLogger(__name__)

class JDClient:
    """
    Drop-in client that matches the old GUI expectations:
      - __init__(email, password, device_name="", app_key="PyForumBot")
      - connect()
      - add_links_to_linkgrabber(urls: list[str], start_check: bool = True) -> bool
      - query_links() -> list[dict]
      - start_online_check(link_ids) -> bool
      - remove_links(link_ids) -> bool
      - remove_all_from_linkgrabber() -> bool
      - abort_linkgrabber() -> bool  <-- جديد لإيقاف الفحص ومسح كل شيء

    Internally uses `myjdapi`, so you don't deal with signatures/HMAC.
    """
    def __init__(self, email: str, password: str, device_name: str = "", app_key: str = "PyForumBot"):
        self.api = Myjdapi()
        self.email = (email or "").strip()
        self.password = (password or "").strip()
        self.device_name = (device_name or "").strip()
        self.app_key = (app_key or "PyForumBot").strip()
        self.device = None

    def connect(self) -> bool:
        try:
            if not self.email or not self.password:
                log.error("JD.connect: missing email/password")
                return False

            try:
                self.api.set_app_key(self.app_key)
            except Exception:
                pass

            log.debug("JD.connect: logging in to My.JDownloader (myjdapi)")
            self.api.connect(self.email, self.password)

            # pick device
            try:
                self.api.update_devices()
            except Exception:
                pass

            sel = None
            if self.device_name:
                try:
                    sel = self.api.get_device(self.device_name)
                except Exception:
                    sel = None
            if not sel:
                devices = getattr(self.api, "devices", {}) or {}
                if devices:
                    sel = list(devices.values())[0]
            if not sel:
                log.error("JD.connect: no devices")
                return False

            self.device = sel
            log.debug("JD.connect: selected device=%s", getattr(self.device, "name", None))
            return True
        except Exception as e:
            log.exception("JD.connect failed: %s", e)
            return False

    def add_links_to_linkgrabber(self, urls: List[str], start_check: bool = True) -> bool:
        try:
            if not self.device:
                log.error("JD.add_links: device not ready")
                return False
            urls = [u.strip() for u in (urls or []) if isinstance(u, str) and u.strip()]
            if not urls:
                log.error("JD.add_links: empty url list")
                return False

            payload = {
                "autostart": False,
                "links": "\n".join(urls),
                "deepDecrypt": True,
                "checkAvailability": True,
            }
            # /linkgrabberv2/* expects a LIST of params
            self.device.action("/linkgrabberv2/addLinks", [payload])
            log.debug("JD.add_links (raw): %d urls sent", len(urls))
            if start_check:
                try:
                    self.device.action("/linkgrabberv2/startOnlineCheck", [])
                except Exception:
                    try:
                        self.device.linkgrabberv2.start_online_check([])
                    except Exception:
                        pass
            return True
        except Exception as e:
            log.exception("JD.add_links failed: %s", e)
            return False

    def start_online_check(self, link_ids) -> bool:
        try:
            if not self.device:
                log.error("JD.start_online_check: device not ready")
                return False
            ids = []
            for uid in link_ids or []:
                if uid is None:
                    continue
                try:
                    ids.append(int(uid))
                except Exception:
                    ids.append(uid)
            self.device.action("/linkgrabberv2/startOnlineCheck", [ids])
            return True
        except Exception as e:
            log.exception("JD.start_online_check: failed: %s", e)
            return False

    def query_links(self) -> list:
        try:
            if not self.device:
                return []
            query = {
                "bytesTotal": True,
                "status": True,
                "host": True,
                "name": True,
                "availability": True,
                "size": True,
                "url": True,
                "contentURL": True,
                "pluginURL": True,
                "containerURL": True,
                "origin": True,
                "variant": True,
                "packageUUID": True,
                "uuid": True,
            }
            try:
                res = self.device.action("/linkgrabberv2/queryLinks", [query]) or []
            except Exception:
                try:
                    res = self.device.linkgrabberv2.query_links(query) or []
                except Exception:
                    res = []
            if isinstance(res, dict):
                res = [res]
            log.debug("JD.query_links (raw): %d items", len(res))
            return res
        except Exception as e:
            log.exception("JD.query_links failed: %s", e)
            return []

    def remove_links(self, link_ids: Iterable) -> bool:
        try:
            if not self.device:
                log.error("JD.remove_links: device not ready")
                return False
            ids = []
            for uid in link_ids or []:
                if uid is None:
                    continue
                try:
                    ids.append(int(uid))
                except Exception:
                    ids.append(uid)
            if not ids:
                return True
            # Try several variants to maximize compatibility
            try:
                self.device.action("/linkgrabberv2/removeLinks", [{"linkIds": ids}])
                log.debug("JD.remove_links: removed %d items via {'linkIds': [...]}",
                          len(ids))
                return True
            except Exception:
                pass
            try:
                self.device.linkgrabberv2.remove_links(ids)
                log.debug("JD.remove_links: removed %d items via wrapper.remove_links",
                          len(ids))
                return True
            except Exception:
                pass
            # Fallback: remove by packages
            pkg_query = {"packageUUIDs": True}
            pkgs = self.device.action("/linkgrabberv2/queryPackages", [pkg_query]) or []
            pkg_ids = [p.get("packageUUID") for p in pkgs if p.get("packageUUID")]
            if pkg_ids:
                self.device.action("/linkgrabberv2/removePackages", [{"packageIds": pkg_ids}])
                log.debug("JD.remove_links: removed by packages: %d", len(pkg_ids))
                return True
            return False
        except Exception as e:
            log.exception("JD.remove_links failed: %s", e)
            return False

    def remove_all_from_linkgrabber(self) -> bool:
        try:
            if not self.device:
                return False
            # Try new API first
            try:
                self.device.action("/linkgrabberv2/clearList", [])
                log.debug("JD.clear: cleared via /linkgrabberv2/clearList")
                return True
            except Exception:
                pass
            # Fallback: enumerate and remove
            items = self.query_links() or []
            ids = [it.get("uuid") for it in items if it.get("uuid")]
            if not ids:
                log.debug("JD.clear: nothing to remove (no items)")
                return True
            return self.remove_links(ids)
        except Exception as e:
            log.exception("JD.clear failed: %s", e)
            return False

    # ====== جديد: إيقاف أى فحص جارٍ ومسح القائمة فورًا ======
    def abort_linkgrabber(self) -> bool:
        """
        حاول إيقاف أي فحص/فك تشفير جارٍ في LinkGrabber، وبعدين امسح القائمة.
        بنجرّب كذا endpoint علشان التوافق بين نسخ JDownloader.
        """
        if not self.device:
            return False
        ok = False
        # جرّب شوية endpoints محتملة للإلغاء
        for ep, body in [
            ("/linkgrabberv2/cancel", []),
            ("/linkgrabberv2/abort", []),
            ("/linkgrabberv2/stopOnlineCheck", []),
            ("/linkgrabberv2/abortLinkGrabberTasks", []),
        ]:
            try:
                self.device.action(ep, body)
                log.debug("JD.abort: called %s", ep)
                ok = True
            except Exception:
                pass
        # في كل الأحوال امسح القائمة
        try:
            self.device.action("/linkgrabberv2/clearList", [])
            log.debug("JD.abort: cleared linkgrabber list")
            ok = True
        except Exception:
            # fallback قديم: إزالة بما هو متاح
            items = self.query_links() or []
            ids = [it.get("uuid") for it in items if it.get("uuid")]
            if ids:
                self.remove_links(ids)
                ok = True
        return ok
    # ====== إيقاف التحميلات ومسح قوائم التحميل والـ LinkGrabber ======
    def stop_all_downloads(self) -> bool:
        """حاول إيقاف كل التحميلات الجارية."""
        if not self.device:
            return False
        ok = False
        for ep, body in [
            ("/downloadsV2/stop", []),
            ("/downloadsV2/abort", []),
            ("/downloadcontroller/stop", []),
            ("/downloadcontroller/abort", []),
            ("/toolbar/stopDownloads", []),
        ]:
            try:
                self.device.action(ep, body)
                log.debug("JD.stop_downloads: called %s", ep)
                ok = True
            except Exception:
                pass

        # تأكد من تعطيل كل الحزم حتى لا تستمر التحميلات
        pkg_ids: List[str] = []
        try:
            pkgs = self.device.action("/downloadsV2/queryPackages", [{"uuid": True}]) or []
        except Exception:
            try:
                pkgs = self.device.downloads.query_packages() or []
            except Exception:
                pkgs = []
        for p in pkgs:
            uid = p.get("uuid") or p.get("packageUUID")
            if uid:
                pkg_ids.append(uid)
        if pkg_ids:
            try:
                self.device.action(
                    "/downloadsV2/setEnabled",
                    [{"packageUUIDs": pkg_ids, "enabled": False}],
                )
                log.debug("JD.stop_downloads: disabled %d packages", len(pkg_ids))
                ok = True
            except Exception:
                pass
        return ok

    def clear_download_list(self) -> bool:
        """إزالة كل العناصر من قائمة التحميلات."""
        if not self.device:
            return False
        pkg_ids = []
        ok = False
        pkg_ids: List[str] = []
        try:
            pkgs = self.device.action("/downloadsV2/queryPackages", [{"uuid": True}]) or []
        except Exception:
            try:
                pkgs = self.device.downloads.query_packages() or []
            except Exception:
                pkgs = []
        for p in pkgs:
            uid = p.get("uuid") or p.get("packageUUID")
            if uid:
                pkg_ids.append(uid)
        if pkg_ids:
            try:
                self.device.action(
                    "/downloadsV2/setEnabled",
                    [{"packageUUIDs": pkg_ids, "enabled": False}],
                )
                log.debug("JD.clear_downloads: disabled %d packages", len(pkg_ids))
                ok = True
            except Exception:
                pass

        try:
            self.device.action("/downloadsV2/clearList", [])
            log.debug("JD.clear_downloads: cleared via /downloadsV2/clearList")
            return True
        except Exception:
            pass

        if pkg_ids:
            try:
                self.device.action("/downloadsV2/removePackages", [{"packageUUIDs": pkg_ids}])
                log.debug("JD.clear_downloads: removed %d packages", len(pkg_ids))
                return True
            except Exception:
                try:
                    self.device.downloads.remove_packages(pkg_ids)
                    return True
                except Exception:
                    pass
        log.debug("JD.clear_downloads: nothing to remove")
        return ok

    def stop_and_clear(self) -> bool:
        """أوقف التحميلات ونظف قوائم التحميل و الـ LinkGrabber"""
        ok = False
        try:
            if self.stop_all_downloads():
                ok = True
        except Exception:
            pass
        try:
            if self.clear_download_list():
                ok = True
        except Exception:
            pass
        try:
            if self.remove_all_from_linkgrabber():
                ok = True
        except Exception:
            pass
        try:
            self.device.downloads.cleanup(
                "DELETE_FINISHED", "REMOVE_LINKS_AND_DELETE_FILES", "ALL"
            )
            ok = True
        except Exception:
            pass

        try:
            self.device.downloads.cleanup(
                "DELETE_FINISHED", "REMOVE_LINKS_AND_DELETE_FILES", "ALL"
            )
            ok = True
        except Exception:
            pass
        return ok


def stop_and_clear_jdownloader(config: Optional[dict] = None) -> None:
    """Helper to stop running downloads and clear all JD lists."""
    cfg = config or {}
    email = (
        cfg.get("myjd_email")
        or cfg.get("jdownloader_email")
        or os.getenv("MYJD_EMAIL")
        or os.getenv("JDOWNLOADER_EMAIL", "")
    )
    password = (
        cfg.get("myjd_password")
        or cfg.get("jdownloader_password")
        or os.getenv("MYJD_PASSWORD")
        or os.getenv("JDOWNLOADER_PASSWORD", "")
    )
    device = (
        cfg.get("myjd_device")
        or cfg.get("jdownloader_device")
        or os.getenv("MYJD_DEVICE")
        or os.getenv("JDOWNLOADER_DEVICE", "")
    )
    app_key = (
        cfg.get("myjd_app_key")
        or cfg.get("jdownloader_app_key")
        or os.getenv("MYJD_APP_KEY")
        or os.getenv("JDOWNLOADER_APP_KEY", "PyForumBot")
    )

    if not email or not password:
        return

    jd = JDClient(email, password, device, app_key)
    if jd.connect():
        try:
            jd.stop_and_clear()
        except Exception:
            pass

# === ضع الدالة التالية بعد تعريف كلاس JDClient مباشرة (خارج الكلاس) ===
def stop_and_clear_jdownloader(cfg_or_client=None, wait_timeout=7.0):
    """
    يوقف كل التحميلات فى JDownloader ويمسح Download List و LinkGrabber.
    يقبل:
      - JDClient جاهز
      - dict من الإعدادات فيه مفاتيح myjd_email / myjd_password / myjd_device / myjd_app_key
    """
    log = logging.getLogger(__name__)

    # 1) جهّز عميل JD
    if isinstance(cfg_or_client, JDClient):
        jd = cfg_or_client
    else:
        jd = None
        if isinstance(cfg_or_client, dict):
            email = cfg_or_client.get("myjd_email") or cfg_or_client.get("jdownloader_email") or ""
            password = cfg_or_client.get("myjd_password") or cfg_or_client.get("jdownloader_password") or ""
            device_name = cfg_or_client.get("myjd_device") or cfg_or_client.get("jdownloader_device") or ""
            app_key = cfg_or_client.get("myjd_app_key") or cfg_or_client.get("jdownloader_app_key") or "PyForumBot"
            if email and password:
                jd = JDClient(email=email, password=password, device_name=device_name, app_key=app_key)

        if jd is None:
            log.debug("stop_and_clear_jdownloader: no client/credentials supplied")
            return False

    if not getattr(jd, "device", None):
        if not jd.connect():
            log.debug("stop_and_clear_jdownloader: connect() failed")
            return False

    dev = jd.device

    # 2) أوقف أى تحميلات + Pause كمان للاحتياط
    for path, payload in [
        ("/downloadcontroller/stop", []),
        ("/downloadsV2/stop", []),
        ("/downloads/stop", []),
        ("/downloadcontroller/pause", [True]),
        ("/downloads/pause", [True]),
    ]:
        try:
            dev.action(path, payload)
            log.debug("JD stop via %s", path)
        except Exception:
            pass

    # 3) ألغِ أى كراول/ديكربت فى LinkGrabber
    try:
        dev.action("/linkgrabberv2/abort", [])
    except Exception:
        pass

    # 4) امسح قائمة التحميلات (Downloads)
    try:
        pkgs = dev.action("/downloadsV2/queryPackages", [{"packageUUIDs": True}]) or []
    except Exception:
        pkgs = dev.action("/downloads/queryPackages", [{"packageUUIDs": True}]) or []
    pids = [p.get("packageUUID") for p in pkgs if p.get("packageUUID")]

    if pids:
        removed = False
        for path, payload in [
            ("/downloadsV2/removePackages", [{"packageIds": pids}]),
            ("/downloadsV2/removeLinks", [[], pids]),
            ("/downloads/removeLinks", [[], pids]),
        ]:
            try:
                dev.action(path, payload)
                log.debug("JD removed downloads via %s", path)
                removed = True
                break
            except Exception:
                pass
        if not removed:
            log.debug("could not remove downloads packages (may already be empty)")

    # 5) امسح الـ LinkGrabber بالكامل
    try:
        dev.action("/linkgrabberv2/clearList", [])
        log.debug("LinkGrabber cleared via /linkgrabberv2/clearList")
    except Exception:
        try:
            lpkgs = dev.action("/linkgrabberv2/queryPackages", [{"packageUUIDs": True}]) or []
            lpids = [p.get("packageUUID") for p in lpkgs if p.get("packageUUID")]
            if lpids:
                for path, payload in [
                    ("/linkgrabberv2/removeLinks", [[], lpids]),
                    ("/linkgrabberv2/removePackages", [{"packageIds": lpids}]),
                ]:
                    try:
                        dev.action(path, payload)
                        log.debug("LinkGrabber cleared via %s", path)
                        break
                    except Exception:
                        pass
        except Exception:
            pass

    # 6) انتظر لحد ما يبقى مفيش أى باكدجز فى القائمتين (تفريغ فعلى)
    deadline = time.time() + float(wait_timeout)
    while time.time() < deadline:
        try:
            dpkgs = dev.action("/downloadsV2/queryPackages", [{"packageUUIDs": True}]) or []
        except Exception:
            try:
                dpkgs = dev.action("/downloads/queryPackages", [{"packageUUIDs": True}]) or []
            except Exception:
                dpkgs = []
        try:
            lpkgs = dev.action("/linkgrabberv2/queryPackages", [{"packageUUIDs": True}]) or []
        except Exception:
            lpkgs = []
        if not dpkgs and not lpkgs:
            break
        time.sleep(0.2)

    log.info("✅ JDownloader controller stopped & lists cleared.")
    return True

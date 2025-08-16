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

def hard_cancel(post, logger=None):
    """
    post: دالة تستدعي JD endpoint: post(path:str, payload:list|dict|None) -> dict|list|None
    """
    import time
    log = (logger.info if logger else print)
    warn = (logger.warning if logger else print)

    def _safe(path, payload=None):
        try:
            return post(path, [] if payload is None else payload)
        except Exception as e:
            warn(f"JD POST failed: {path} -> {e}")
            return None

    log("🛑 Hard-cancel JD: stop/abort/remove/clear")

    # ✅ نفس اللي أثبت نجاحه في لوج الـ Link Checker
    _safe("downloadcontroller/stop", [])
    _safe("toolbar/stopDownloads", [])

    # محاولات قديمة (بعض النسخ بترجع 404، لا مشكلة)
    _safe("downloadsV2/stop", [])
    _safe("downloadsV2/abort", [])

    # لم اللينكات الشغالة وشيلها فعليًا
    pkgs = _safe("downloadsV2/queryPackages", [{
        "maxResults": -1, "bytesTotal": True, "status": True
    }]) or []
    pkg_ids = [p.get("uuid") for p in pkgs if p.get("uuid")]

    link_ids = []
    if pkg_ids:
        links = _safe("downloadsV2/queryLinks", [{
            "packageUUIDs": pkg_ids, "maxResults": -1,
            "name": True, "url": True, "enabled": True, "status": True
        }]) or []
        for l in links:
            st = str(l.get("status", "")).lower()
            if l.get("uuid") and (l.get("enabled") or st in ("running", "downloading")):
                link_ids.append(l["uuid"])

    if link_ids:
        # ⚠️ payload لازم يبقى فلات (مش [link_ids])
        _safe("downloadsV2/removeLinks", link_ids)
        log(f"🧹 Removed {len(link_ids)} active JD links")

    # نظّف وامسح الـ LinkGrabber
    _safe("linkgrabberv2/clearList", [])
    _safe("downloadsV2/cleanup", [])
    time.sleep(0.2)
    _safe("downloadsV2/cleanup", [])

    log("✅ JD hard-cancel done")
    return True

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


def stop_and_clear_jdownloader(cfg_or_client=None, wait_timeout: float = 8.0):
    """
    إيقاف فورى و"مسح كامل" لكل ما يخص التحميل داخل JDownloader (Downloads + LinkGrabber)،
    مع التوافق مع اختلافات أسماء الحقول بين إصدارات الـ API.

    يقبل:
      - cfg_or_client: إمّا JDClient متصل، أو dict فيه مفاتيح:
           myjd_email / myjd_password / myjd_device / myjd_app_key (أو نظائر jdownloader_*)
      - wait_timeout: وقت الانتظار الأقصى لتفريغ القوائم (ثوانى)

    يرجّع: True عند النجاح، False لو فشل الاتصال أو التنفيذ.
    """
    import logging, os, time
    log = logging.getLogger(__name__)

    # 1) جهز جهاز JD
    jd = None
    try:
        JDClientRef = JDClient  # لو الكلاس فى نفس الملف
    except Exception:
        JDClientRef = None

    if JDClientRef and isinstance(cfg_or_client, JDClientRef):
        jd = cfg_or_client
    else:
        cfg = cfg_or_client or {}
        if not isinstance(cfg, dict):
            cfg = {}

        email = (
            cfg.get("myjd_email")
            or cfg.get("jdownloader_email")
            or os.getenv("MYJD_EMAIL")
            or os.getenv("JDOWNLOADER_EMAIL")
            or ""
        )
        password = (
            cfg.get("myjd_password")
            or cfg.get("jdownloader_password")
            or os.getenv("MYJD_PASSWORD")
            or os.getenv("JDOWNLOADER_PASSWORD")
            or ""
        )
        device_name = (
            cfg.get("myjd_device")
            or cfg.get("jdownloader_device")
            or os.getenv("MYJD_DEVICE")
            or os.getenv("JDOWNLOADER_DEVICE")
            or ""
        )
        app_key = (
            cfg.get("myjd_app_key")
            or cfg.get("jdownloader_app_key")
            or os.getenv("MYJD_APP_KEY")
            or os.getenv("JDOWNLOADER_APP_KEY")
            or "PyForumBot"
        )

        if not email or not password:
            log.warning("stop_and_clear_jdownloader: missing My.JD credentials.")
            return False

        try:
            api = Myjdapi()
            api.connect(email, password)
            api.update_devices()
            dev = None
            if device_name:
                try:
                    dev = api.get_device(device_name)
                except Exception:
                    dev = None
            if not dev:
                devices = api.list_devices() or []
                if devices:
                    dev = devices[0]
            jd = type("TmpJD", (), {"device": dev, "is_connected": True})()
        except Exception as e:
            log.exception(f"stop_and_clear_jdownloader: connect failed: {e}")
            return False

    dev = getattr(jd, "device", None)
    if not dev:
        try:
            # عندك JDClient حقيقى؟ جرّب connect()
            if hasattr(jd, "connect") and callable(jd.connect):
                if not getattr(jd, "is_connected", False):
                    if not jd.connect():
                        log.error("stop_and_clear_jdownloader: connect() returned False.")
                        return False
                dev = getattr(jd, "device", None)
        except Exception:
            dev = getattr(jd, "device", None)

    if not dev:
        log.error("stop_and_clear_jdownloader: no device to act upon.")
        return False

    # 2) أوقف الكنترولر + Pause فورى (نجرّب مسارات متعددة للتوافق)
    for path, payload in [
        ("/downloadsV2/stop", []),
        ("/downloadcontroller/stop", []),
        ("/downloads/stop", []),
        ("/downloadsV2/pause", [True]),
        ("/downloadcontroller/pause", [True]),
    ]:
        try:
            dev.action(path, payload)
        except Exception:
            pass

    # 3) LinkGrabber: أوقف أى Tasks
    for path in ["/linkgrabberv2/abort", "/linkgrabberv2/cancel", "/linkgrabberv2/stopOnlineCheck"]:
        try:
            dev.action(path, [])
        except Exception:
            pass

    # 4) امسح الـ Downloads (نجيب UUIDs وبعدين نستخدم الاسم الصحيح للحقل)
    def _query_download_package_uuids():
        try:
            pkgs = dev.action("/downloadsV2/queryPackages", [{"packageUUIDs": True}]) or []
        except Exception:
            try:
                pkgs = dev.action("/downloads/queryPackages", [{"packageUUIDs": True}]) or []
            except Exception:
                pkgs = []
        uuids = []
        for p in pkgs:
            uid = p.get("packageUUID") or p.get("uuid") or p.get("id")
            if uid is not None:
                uuids.append(uid)
        return uuids

    d_pkg_uuids = _query_download_package_uuids()

    if d_pkg_uuids:
        removed = False
        # المحاولة الصحيحة الشائعة: packageUUIDs
        for path, payload in [
            ("/downloadsV2/removePackages", [{"packageUUIDs": d_pkg_uuids}]),
            ("/downloads/removePackages", [{"packageUUIDs": d_pkg_uuids}]),
            ("/downloadsV2/removeLinks", [[], d_pkg_uuids]),
            ("/downloads/removeLinks", [[], d_pkg_uuids]),
            ("/downloadsV2/setEnabled", [{"packageUUIDs": d_pkg_uuids, "enabled": False}]),
        ]:
            try:
                dev.action(path, payload)
                removed = True
                break
            except Exception:
                continue
        if not removed:
            # فولباك أخير: clearList (قد يمسح المُكتمل فقط)
            try:
                dev.action("/downloadsV2/clearList", [])
            except Exception:
                pass

    # 5) LinkGrabber: امسح الباكدجات/اللينكات (packageIds غالبًا فى LG)
    def _query_lg_package_ids():
        try:
            pkgs = dev.action("/linkgrabberv2/queryPackages", [{"packageUUIDs": True}]) or []
        except Exception:
            pkgs = []
        ids = []
        for p in pkgs:
            uid = p.get("packageUUID") or p.get("uuid") or p.get("id")
            if uid is not None:
                ids.append(uid)
        return ids

    lg_pkg_ids = _query_lg_package_ids()

    if lg_pkg_ids:
        cleared = False
        for path, payload in [
            ("/linkgrabberv2/removePackages", [{"packageIds": lg_pkg_ids}]),
            ("/linkgrabberv2/removeLinks", [[], lg_pkg_ids]),
        ]:
            try:
                dev.action(path, payload)
                cleared = True
                break
            except Exception:
                continue
        if not cleared:
            try:
                dev.action("/linkgrabberv2/clearList", [])
                cleared = True
            except Exception:
                pass
    else:
        # مفيش باكدجز؟ جرّب clearList مباشرة
        try:
            dev.action("/linkgrabberv2/clearList", [])
        except Exception:
            pass

    # 6) انتظر لحد القائمتين يفضوا فعلاً
    deadline = time.time() + float(wait_timeout)
    while time.time() < deadline:
        try:
            d_left = dev.action("/downloadsV2/queryPackages", [{"packageUUIDs": True}]) or []
        except Exception:
            try:
                d_left = dev.action("/downloads/queryPackages", [{"packageUUIDs": True}]) or []
            except Exception:
                d_left = []
        try:
            lg_left = dev.action("/linkgrabberv2/queryPackages", [{"packageUUIDs": True}]) or []
        except Exception:
            lg_left = []
        if not d_left and not lg_left:
            break
        time.sleep(0.2)

    log.info("✅ stop_and_clear_jdownloader: controller stopped & lists cleared.")
    return True




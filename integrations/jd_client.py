import logging
from myjdapi import Myjdapi

class JDClient:
    """
    My.JDownloader client with compatibility for both linkgrabberv2 and linkgrabber.
    """
    def __init__(self, email: str, password: str, device_name: str = "", app_key: str = "PyForumBot"):
        self.api = Myjdapi()
        self.email = (email or "").strip()
        self.password = (password or "").strip()
        self.device_name = (device_name or "").strip()
        self.app_key = (app_key or "PyForumBot").strip()
        self.device = None
        self.lg = None          # resolved linkgrabber proxy
        self.lg_mode = "none"   # "v2" | "v1" | "none"

    def connect(self) -> bool:
        try:
            if not self.email or not self.password:
                logging.error("JD.connect: missing email/password")
                return False

            try:
                self.api.set_app_key(self.app_key)
            except Exception:
                pass

            logging.debug("JD.connect: logging in to My.JDownloader (via connect)")
            self.api.connect(self.email, self.password)

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
                    sel = next(iter(devices.values()))
            if not sel:
                logging.error("JD.connect: no devices found on account")
                return False

            self.device = sel
            logging.debug("JD.connect: selected device=%s", getattr(sel, "name", None) or "UNKNOWN")

            # حاول نجيب linkgrabberv2 ثم ارجع لـ linkgrabber
            self._resolve_linkgrabber()

            try:
                # معلومة الاتصال المباشر (اختياري)
                self.device.update_direct_connection_info()
            except Exception:
                pass

            if not self.lg:
                logging.error("JD.connect: linkgrabber API not available on device")
                return False

            return True
        except Exception as e:
            logging.exception("JD.connect: failed: %s", e)
            return False

    def _resolve_linkgrabber(self):
        # v2 أولاً
        lg = getattr(self.device, "linkgrabberv2", None)
        if lg:
            self.lg = lg
            self.lg_mode = "v2"
            logging.debug("JD.connect: using linkgrabberv2")
            return
        # fallback: v1
        lg = getattr(self.device, "linkgrabber", None)
        if lg:
            self.lg = lg
            self.lg_mode = "v1"
            logging.debug("JD.connect: using linkgrabber (v1)")
            return
        self.lg = None
        self.lg_mode = "none"

    def add_links_to_linkgrabber(self, urls: list[str]) -> bool:
        try:
            if not self.device:
                logging.error("JD.add_links: device not ready")
                return False
            urls = [u.strip() for u in (urls or []) if isinstance(u, str) and u.strip()]
            if not urls:
                logging.error("JD.add_links: empty url list")
                return False

            payload = {
                "autostart": False,
                "links": "\n".join(urls),
                "deepDecrypt": True,
                "checkAvailability": True,
            }
            # NOTE: لازم List بالقيم مش dict بالمفاتيح
            self.device.action("/linkgrabberv2/addLinks", [payload])
            logging.debug("JD.add_links (raw): %d urls sent", len(urls))

            try:
                self.device.action("/linkgrabberv2/startOnlineCheck", [])
            except Exception:
                pass
            return True
        except Exception as e:
            logging.exception("JD.add_links: failed: %s", e)
            return False

    def query_links(self) -> list[dict]:
        try:
            if not self.device:
                logging.error("JD.query_links: device not ready")
                return []

            q = {
                "bytesTotal": True,
                "status": True,
                "host": True,
                "name": True,
                "availability": True,
                "size": True,
                "url": True,
                "contentURL": True,
                "pluginURL": True,
                "startAt": 0,
                "maxResults": -1
            }
            # NOTE: List بالقيمة
            resp = self.device.action("/linkgrabberv2/queryLinks", [q]) or []
            out = []
            for it in resp:
                url = it.get("url") or it.get("contentURL") or it.get("pluginURL") or ""
                it["url"] = url
                out.append(it)
            logging.debug("JD.query_links (raw): %d items", len(out))
            return out
        except Exception as e:
            logging.exception("JD.query_links: failed: %s", e)
            return []

    def remove_all_from_linkgrabber(self) -> bool:
        try:
            if not self.device:
                logging.error("JD.clear: device not ready")
                return False
            items = self.query_links()
            uuids = [i.get("uuid") for i in items if i.get("uuid")]
            if not uuids:
                logging.debug("JD.clear: nothing to remove")
                return True

            # NOTE: List بالقيمة
            self.device.action("/linkgrabberv2/removeLinks", [uuids])
            logging.debug("JD.clear: removed %d items", len(uuids))
            return True
        except Exception as e:
            logging.exception("JD.clear: failed: %s", e)
            return False

    def remove_all_from_linkgrabber(self) -> bool:
        """
        يمسح كل اللينكات (وأيضاً يحاول يمسح الباكيدجات) من الـ LinkGrabber.
        بيفضّل IDs كأرقام، ويجرّب أكتر من فورمات للبارامز لضمان التوافق.
        """
        try:
            if not self.device:
                logging.error("JD.clear: device not ready")
                return False

            # 1) هات كل الروابط الحالية
            items = self.query_links()
            if not items:
                logging.debug("JD.clear: nothing to remove (no items)")
                return True

            # 2) حضّر الـ IDs كأرقام (مش سترينج)
            link_ids = []
            for i in items:
                uid = i.get("uuid")
                if uid is None:
                    continue
                try:
                    link_ids.append(int(uid))
                except Exception:
                    # لو مش رقم، سيبه زي ما هو
                    link_ids.append(uid)

            if not link_ids:
                logging.debug("JD.clear: nothing to remove (no ids)")
                return True

            # 3) جرّب أكثر من طريقة لمسح الروابط

            # (أ) الشكل المباشر: مصفوفة IDs فقط
            try:
                self.device.action("/linkgrabberv2/removeLinks", [link_ids])
                logging.debug("JD.clear: removed %d items via [linkIds]", len(link_ids))
                return True
            except Exception as e:
                logging.debug("JD.clear: first attempt failed (%s), trying dict payload", e)

            # (ب) شكل ديكت: {"linkIds":[...]}
            try:
                self.device.action("/linkgrabberv2/removeLinks", [{"linkIds": link_ids}])
                logging.debug("JD.clear: removed %d items via {'linkIds': [...]} ", len(link_ids))
                return True
            except Exception as e:
                logging.debug("JD.clear: second attempt failed (%s), trying wrapper/fallback", e)

            # (ج) لو فيه wrapper متاح (v1/v2)، خلّيه يحاول
            try:
                if hasattr(self, "lg") and self.lg and hasattr(self.lg, "remove_links"):
                    self.lg.remove_links(link_ids)
                    logging.debug("JD.clear: removed %d items via wrapper.remove_links", len(link_ids))
                    return True
            except Exception as e:
                logging.debug("JD.clear: wrapper attempt failed (%s)", e)

            # 4) كمل تنظيف: امسح الباكيدجات لو لسة فيه بواقي
            try:
                # استعلام الباكيدجات، ثم removePackages
                pkg_query = {
                    "bytesTotal": True,
                    "status": True,
                    "hosts": True,
                    "saveTo": True,
                    "packageUUIDs": True,
                    "childCount": True,
                    "startAt": 0,
                    "maxResults": -1
                }
                pkgs = self.device.action("/linkgrabberv2/queryPackages", [pkg_query]) or []
                pkg_ids = []
                for p in pkgs:
                    puid = p.get("packageUUID")
                    if puid is None:
                        continue
                    try:
                        pkg_ids.append(int(puid))
                    except Exception:
                        pkg_ids.append(puid)

                if pkg_ids:
                    # جرّب الليست مباشرة
                    try:
                        self.device.action("/linkgrabberv2/removePackages", [pkg_ids])
                        logging.debug("JD.clear: removed %d packages via [pkgIds]", len(pkg_ids))
                        return True
                    except Exception:
                        # جرّب ديكت
                        try:
                            self.device.action("/linkgrabberv2/removePackages", [{"packageIds": pkg_ids}])
                            logging.debug("JD.clear: removed %d packages via {'packageIds': [...]} ", len(pkg_ids))
                            return True
                        except Exception:
                            pass
            except Exception:
                pass

            logging.error("JD.clear: all removal attempts failed")
            return False

        except Exception as e:
            logging.exception("JD.clear: failed: %s", e)
            return False


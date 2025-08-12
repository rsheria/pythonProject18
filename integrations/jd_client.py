from myjdapi import Myjdapi

class JDClient:
    def __init__(self, email, password, device_name="", app_key=""):
        self.api = Myjdapi()
        self.email = email
        self.password = password
        self.device_name = device_name
        self.app_key = app_key
        self.device = None

    def connect(self):
        """Connect to My.JDownloader and select a device.

        If ``device_name`` is empty or not found, the first available device
        is used as a fallback so that link checking works even when the user
        hasn't specified a device explicitly.
        """
        try:
            if self.app_key:
                try:
                    self.api.set_app_key(self.app_key)
                except Exception:
                    pass
            self.api.connect(self.email, self.password)
            self.api.update_devices()
            if self.device_name:
                self.device = self.api.get_device(self.device_name)
            if not self.device:
                devices = self.api.list_devices()
                if devices:
                    self.device = self.api.get_device(devices[0]['name'])
            return self.device is not None
        except Exception:
            return False

    def add_links_to_linkgrabber(self, urls):
        if not urls:
            return True
        try:
            self.device.linkgrabberv2.add_links({
                "autostart": False,
                "links": "\n".join(urls),
                "deepDecrypt": True
            })
            return True
        except Exception:
            return False

    def query_links(self):
        try:
            q = {
                "packageUUIDs": None,
                "linkUUIDs": None,
                "startAt": 0,
                "maxResults": -1,
                "bytesTotal": True,
                "availableOfflineCount": True,
                "availableOnlineCount": True,
                "status": True,
                "host": True,
                "name": True,
                "availability": True,
                "size": True,
                "url": True,
                "contentURL": True,
                "pluginURL": True
            }
            items = self.device.linkgrabberv2.query_links(q) or []
            for it in items:
                link_url = it.get("url") or it.get("contentURL") or it.get("pluginURL")
                it["url"] = link_url
            return items
        except Exception:
            return []

    def remove_all_from_linkgrabber(self):
        try:
            links = self.query_links()
            uuids = [l.get("uuid") for l in links if l.get("uuid")]
            if uuids:
                self.device.linkgrabberv2.remove_links(uuids)
            return True
        except Exception:
            return False
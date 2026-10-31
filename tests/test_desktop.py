"""Native navigation policy and loopback backend lifecycle tests."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import server
from desktop_policy import navigation_policy


class DesktopTests(unittest.TestCase):
    def test_navigation_policy(self):
        origin = "http://127.0.0.1:42001"
        self.assertEqual(navigation_policy(origin + "/?desktop=1", origin, False, False), "allow")
        self.assertEqual(navigation_policy("blob:" + origin + "/export", origin, False, True), "download")
        for url in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,bad", "http://127.0.0.1:42002/", "https://example.com"):
            self.assertEqual(navigation_policy(url, origin, False, False), "cancel")
        self.assertEqual(navigation_policy("https://example.com", origin, True, False), "external")

    def test_dynamic_origin_token_settings_and_owned_shutdown(self):
        with tempfile.TemporaryDirectory() as folder, patch("socket.getfqdn", side_effect=AssertionError("reverse lookup")), patch.object(server, "seed_demo"):
            preferences = Path(folder) / "preferences.json"
            with patch.object(server, "PREFERENCES", preferences):
                backend = server.make_server(port=0)
                port = backend.server_port
                worker = threading.Thread(target=backend.serve_forever, daemon=True)
                worker.start()
                origin = f"http://127.0.0.1:{port}"
                try:
                    self.assertEqual(backend.server_name, "127.0.0.1")
                    with urlopen(origin + "/", timeout=3) as response:
                        page = response.read().decode()
                    token = page.split('name="request-token" content="', 1)[1].split('"', 1)[0]
                    with self.assertRaises(HTTPError) as bad_host:
                        urlopen(Request(origin + "/", headers={"Host": "evil.test"}), timeout=3)
                    self.assertEqual(bad_host.exception.code, 403)
                    bad_host.exception.close()
                    payload = json.dumps({"compact": True, "reduceMotion": True}).encode()
                    base_headers = {"Origin": origin, "Content-Type": "application/json"}
                    with self.assertRaises(HTTPError) as missing_token:
                        urlopen(Request(origin + "/api/settings", data=payload, headers=base_headers), timeout=3)
                    self.assertEqual(missing_token.exception.code, 403)
                    missing_token.exception.close()
                    headers = {**base_headers, "X-Request-Token": token}
                    bad_origin_headers = {**headers, "Origin": "http://evil.test"}
                    with self.assertRaises(HTTPError) as bad_origin:
                        urlopen(Request(origin + "/api/settings", data=payload, headers=bad_origin_headers), timeout=3)
                    self.assertEqual(bad_origin.exception.code, 403)
                    bad_origin.exception.close()
                    with urlopen(Request(origin + "/api/settings", data=payload, headers=headers), timeout=3) as response:
                        self.assertEqual(json.load(response)["preferences"], {"compact": True, "reduceMotion": True})
                    with urlopen(origin + "/api/settings", timeout=3) as response:
                        self.assertEqual(json.load(response)["preferences"], {"compact": True, "reduceMotion": True})
                    invalid = json.dumps({"compact": 1, "reduceMotion": True}).encode()
                    with self.assertRaises(HTTPError) as invalid_settings:
                        urlopen(Request(origin + "/api/settings", data=invalid, headers=headers), timeout=3)
                    self.assertEqual(invalid_settings.exception.code, 400)
                    invalid_settings.exception.close()
                finally:
                    backend.shutdown()
                    backend.server_close()
                    worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(backend.fileno(), -1)
                reopened = server.make_server(port=0)
                next_worker = threading.Thread(target=reopened.serve_forever, daemon=True)
                next_worker.start()
                try:
                    with urlopen(f"http://127.0.0.1:{reopened.server_port}/api/settings", timeout=3) as response:
                        self.assertEqual(json.load(response)["preferences"], {"compact": True, "reduceMotion": True})
                finally:
                    reopened.shutdown()
                    reopened.server_close()
                    next_worker.join(timeout=3)
                self.assertFalse(next_worker.is_alive())


if __name__ == "__main__":
    unittest.main()

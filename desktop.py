"""Native macOS shell for Payment Matching."""
from __future__ import annotations

import threading
import sys

import webview
from webview.menu import Menu, MenuAction

import server
from desktop_policy import install_policy


def run() -> None:
    if sys.platform != "darwin":
        raise SystemExit("Payment Matching desktop runs on macOS.")
    backend = server.make_server(port=0)
    worker = threading.Thread(target=backend.serve_forever, name="workflow-ledger-http", daemon=True)
    worker_started = False
    window = None
    try:
        worker.start()
        worker_started = True
        origin = f"http://127.0.0.1:{backend.server_port}"
        url = origin + "/?desktop=1"
        menu = [Menu("Payment Matching", [MenuAction("Settings", lambda _w=None: window.evaluate_js("document.getElementById('settingsOpen').click()") if window else None), MenuAction("Quit", lambda _w=None: window.destroy() if window else None)])]
        window = webview.create_window("Payment Matching", url, width=1080, height=760, min_size=(820, 600), menu=menu)
        install_policy(origin)
        webview.start()
    finally:
        if worker_started:
            backend.shutdown()
        backend.server_close()
        if worker_started:
            worker.join(timeout=3)


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception:
        import AppKit

        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("Payment Matching could not start")
        alert.setInformativeText_("The local app could not open. Quit it and try again.")
        alert.addButtonWithTitle_("OK")
        alert.runModal()
        raise SystemExit(1)

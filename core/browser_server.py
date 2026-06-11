import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable, Optional


class BrowserIntegrationHandler(BaseHTTPRequestHandler):

    # Injected by factory
    on_download_request: Optional[Callable] = None

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        body = json.dumps({
            "app": "SE Downloader",
            "version": "1.0.0",
            "status": "running"
        }).encode("utf-8")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            raw_str = raw.decode("utf-8").strip()
            import logging
            log = logging.getLogger("browser_server")
            log.info("POST received, length=%d, body=%s", length, raw_str[:200])
            data = json.loads(raw_str)
            log.info("POST parsed OK, url=%s", data.get("url","")[:80])
            if self.on_download_request:
                log.info("Calling on_download_request callback")
                self.on_download_request(data)
                log.info("on_download_request callback returned")
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode("utf-8")
            self.send_response(200)   # Always 200 to avoid XHR treating as error
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age",       "86400")

    def log_message(self, fmt, *args):
        import logging
        logging.getLogger("browser_server").debug(fmt, *args)


class BrowserIntegrationServer:
    def __init__(self, port: int = 26339, on_download_request: Callable = None):
        self.port = port
        self.on_download_request = on_download_request
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> bool:
        if self._running:
            return True
        try:
            cb = self.on_download_request

            class Handler(BrowserIntegrationHandler):
                on_download_request = cb

            self._server = HTTPServer(("127.0.0.1", self.port), Handler)
            self._thread = threading.Thread(
                target=self._server.serve_forever, daemon=True,
                name="browser-server"
            )
            self._thread.start()
            self._running = True
            return True
        except Exception as e:
            self._running = False
            return False

    def stop(self):
        if self._server:
            self._server.shutdown()
        self._running = False

    def restart(self, new_port: int = None):
        self.stop()
        if new_port:
            self.port = new_port
        return self.start()

    @property
    def is_running(self) -> bool:
        return self._running

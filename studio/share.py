"""
"Send to phone": a tiny download server for finished reels.

The studio itself only listens on 127.0.0.1. When you share a render, this
starts a separate listener on your home network that serves exactly that
file behind a random, expiring link, so you can scan a QR code and download
the reel on your phone. Nothing else is reachable through it.
"""

import html
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

CHUNK = 1 << 20


class Shares:
    def __init__(self, port=3010, ttl=3600):
        self.port = port
        self.ttl = ttl
        self.links = {}          # token -> (path, title, expires_at)
        self._server = None
        self._lock = threading.Lock()

    def add(self, path, title):
        """Share one file; returns (url, expires_at). Starts the listener if needed."""
        ip = lan_ip()
        if not ip:
            raise RuntimeError("This Mac doesn't seem to be on a network. Connect it to Wi-Fi.")
        self._start()
        token = secrets.token_urlsafe(16)
        expires = time.time() + self.ttl
        with self._lock:
            self._prune()
            self.links[token] = (Path(path), title, expires)
        return f"http://{ip}:{self.port}/v/{token}", expires

    def get(self, token):
        with self._lock:
            self._prune()
            return self.links.get(token)

    def _prune(self):
        now = time.time()
        for t in [t for t, (_, _, exp) in self.links.items() if exp < now]:
            del self.links[t]

    def _start(self):
        with self._lock:
            if self._server:
                return
            shares = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_GET(self):
                    parts = self.path.split("?")[0].strip("/").split("/")
                    if len(parts) not in (2, 3) or parts[0] != "v":
                        return self._missing()
                    link = shares.get(parts[1])
                    if not link or not link[0].exists():
                        return self._missing()
                    path, title, _ = link
                    if len(parts) == 2:
                        return self._page(parts[1], path, title)
                    if parts[2] == "file":
                        return self._file(path, title)
                    return self._missing()

                def _missing(self):
                    body = b"This link has expired or doesn't exist. Share it again from Footage Studio."
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def _page(self, token, path, title):
                    size = path.stat().st_size / 1e6
                    name = html.escape(title)
                    body = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<style>
  body {{ margin: 0; font-family: system-ui, sans-serif; background: #15181b; color: #e4e7ea;
         display: grid; place-items: center; min-height: 100vh; text-align: center; }}
  main {{ padding: 24px; }}
  h1 {{ font-size: 22px; margin: 0 0 6px; }}
  p {{ color: #98a0a8; margin: 0 0 28px; }}
  a {{ display: inline-block; padding: 16px 28px; border-radius: 14px; background: #a9c49a;
       color: #10140f; font-weight: 700; font-size: 18px; text-decoration: none; }}
</style></head><body><main>
<h1>{name}</h1><p>{size:.1f} MB · Footage Studio</p>
<a href="/v/{token}/file">Download reel</a>
</main></body></html>""".encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def _file(self, path, title):
                    fname = f"{title}.mp4"
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(path.stat().st_size))
                    self.send_header("Content-Disposition",
                                     f"attachment; filename=\"{safe_ascii(fname)}\"; "
                                     f"filename*=UTF-8''{quote(fname)}")
                    self.end_headers()
                    with open(path, "rb") as f:
                        while chunk := f.read(CHUNK):
                            self.wfile.write(chunk)

            self._server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
            self._server.daemon_threads = True
            threading.Thread(target=self._server.serve_forever, daemon=True).start()


def lan_ip():
    """This machine's address on the local network (no packets are sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))   # TEST-NET address; connect() on UDP sends nothing
            ip = s.getsockname()[0]
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def safe_ascii(name):
    return "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in name)

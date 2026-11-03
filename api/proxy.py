from http.server import BaseHTTPRequestHandler
import urllib.request
import urllib.parse
import urllib.error
import ssl

ALLOWED_DOMAINS = [
    "static-db.appx.co.in",
    "appx-content-v2.classx.co.in",
    "static-trans-v2.appx.co.in",
    "static-trans.appx.co.in",
    "cdn.appx.co.in",
    "akamai.net.in",
    "static-wsb.appx.co.in",
    "static-db-v2.appx.co.in",
    "appxcontent.kaxa.in",
    "appx-content.classx.co.in",
    "appxcontentcdn.classx.co.in",
]

FORWARD_HEADERS = {
    "Referer":         "https://player-strict.akamai.net.in/",
    "Origin":          "https://player-strict.akamai.net.in",
    "User-Agent":      "Dalvik/2.1.0 (Linux; U; Android 11; RMX2001 Build/RP1A.200720.011)",
    "Accept":          "*/*",
    "Accept-Encoding": "identity",
    "Connection":      "keep-alive",
    "X-Forwarded-For": "49.36.52.100",
    "X-Real-IP":       "49.36.52.100",
}

CHUNK_SIZE = 2 * 1024 * 1024  # 2MB per range request — mimics HLS segment size

def make_ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def is_mp4(url):
    path = urllib.parse.urlparse(url).path
    return path.endswith(".mp4")

class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        target_url = params.get("url", [None])[0]

        if not target_url:
            self._error(400, "Missing ?url= parameter")
            return

        target_parsed = urllib.parse.urlparse(target_url)
        if not any(d in target_parsed.netloc for d in ALLOWED_DOMAINS):
            self._error(403, f"Domain not allowed: {target_parsed.netloc}")
            return

        ctx = make_ssl_ctx()

        # For MP4 files: use chunked Range requests to mimic HLS player behaviour
        if is_mp4(target_url):
            self._proxy_mp4_chunked(target_url, ctx)
        else:
            self._proxy_direct(target_url, ctx)

    def _proxy_mp4_chunked(self, target_url, ctx):
        """
        Fetch MP4 in small Range chunks so Akamai sees a video-player
        seeking pattern instead of a single bulk download (which it blocks).
        """
        req_headers = dict(FORWARD_HEADERS)

        # ── Step 1: probe total size with a 1-byte range request ──
        req_headers["Range"] = "bytes=0-0"
        try:
            probe_req = urllib.request.Request(target_url, headers=req_headers)
            with urllib.request.urlopen(probe_req, timeout=30, context=ctx) as probe:
                cr = probe.headers.get("Content-Range", "")   # bytes 0-0/TOTAL
                ct = probe.headers.get("Content-Type", "video/mp4")
                if "/" in cr:
                    total = int(cr.split("/")[-1])
                else:
                    # Server returned 200 instead of 206 — fall back to direct
                    cl = probe.headers.get("Content-Length", "")
                    total = int(cl) if cl else None
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            self._error(e.code, f"CDN probe error: {e.reason} — {body[:300]}")
            return
        except Exception as e:
            self._error(502, f"Probe error: {str(e)}")
            return

        if not total:
            # Can't determine size — fall back to direct proxy
            self._proxy_direct(target_url, ctx)
            return

        # ── Step 2: stream back to client chunk by chunk ──
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(total))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        start = 0
        while start < total:
            end = min(start + CHUNK_SIZE - 1, total - 1)
            h = {**FORWARD_HEADERS, "Range": f"bytes={start}-{end}"}
            try:
                req = urllib.request.Request(target_url, headers=h)
                with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                    while True:
                        data = resp.read(65536)
                        if not data:
                            break
                        self.wfile.write(data)
                        self.wfile.flush()
            except Exception as e:
                # Can't send an error mid-stream; just stop
                break
            start = end + 1

    def _proxy_direct(self, target_url, ctx):
        """Standard passthrough for non-MP4 or fallback."""
        req_headers = dict(FORWARD_HEADERS)
        range_val = self.headers.get("Range")
        if range_val:
            req_headers["Range"] = range_val

        try:
            req = urllib.request.Request(target_url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=280, context=ctx) as resp:
                status = resp.status
                ct = resp.headers.get("Content-Type", "application/octet-stream")
                cl = resp.headers.get("Content-Length", "")
                cr = resp.headers.get("Content-Range", "")
                ar = resp.headers.get("Accept-Ranges", "bytes")

                self.send_response(status)
                self.send_header("Content-Type", ct)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Accept-Ranges", ar)
                if cl:
                    self.send_header("Content-Length", cl)
                if cr:
                    self.send_header("Content-Range", cr)
                self.end_headers()

                while True:
                    chunk = resp.read(1048576)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()

        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            self._error(e.code, f"CDN error: {e.reason} — {body[:300]}")
        except Exception as e:
            self._error(502, f"Proxy error: {str(e)}")

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        target_url = params.get("url", [None])[0]

        if not target_url:
            self._error(400, "Missing ?url=")
            return

        target_parsed = urllib.parse.urlparse(target_url)
        if not any(d in target_parsed.netloc for d in ALLOWED_DOMAINS):
            self._error(403, "Domain not allowed")
            return

        ctx = make_ssl_ctx()
        try:
            req = urllib.request.Request(
                target_url, headers=FORWARD_HEADERS, method="HEAD")
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                self.send_response(resp.status)
                cl = resp.headers.get("Content-Length", "")
                ct = resp.headers.get("Content-Type", "video/mp4")
                self.send_header("Content-Type", ct)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Access-Control-Allow-Origin", "*")
                if cl:
                    self.send_header("Content-Length", cl)
                self.end_headers()
        except Exception as e:
            self._error(502, str(e))

    def _error(self, code, msg):
        body = msg.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

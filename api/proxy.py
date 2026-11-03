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
    "transcoded-videos.classx.co.in",
]

def make_ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def build_headers(target_url, range_val=None):
    parsed = urllib.parse.urlparse(target_url)
    host = parsed.netloc  # dynamic Host header per domain
    headers = {
        "Referer":         "https://player-strict.akamai.net.in/",
        "Icy-MetaData":    "1",
        "Accept-Encoding": "identity",
        "User-Agent":      "Dalvik/2.1.0 (Linux; U; Android 11; RMX2001 Build/RP1A.200720.011)",
        "Host":            host,
        "Connection":      "Keep-Alive",
    }
    if range_val:
        headers["Range"] = range_val
    return headers

class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        # Extract everything after ?url= as the raw target URL
        # This preserves & and ? inside the target URL without requiring pre-encoding
        raw_path = self.path
        marker = "?url="
        idx = raw_path.find(marker)
        if idx == -1:
            self._error(400, "Missing ?url= parameter")
            return
        target_url = raw_path[idx + len(marker):]

        if not target_url:
            self._error(400, "Missing ?url= parameter")
            return

        # Decode percent-encoding if client encoded the URL
        target_url = urllib.parse.unquote(target_url)

        target_parsed = urllib.parse.urlparse(target_url)
        if not any(d in target_parsed.netloc for d in ALLOWED_DOMAINS):
            self._error(403, f"Domain not allowed: {target_parsed.netloc}")
            return

        ctx = make_ssl_ctx()

        # Pass through client Range header, default to bytes=0- (required by CDN)
        range_val = self.headers.get("Range") or "bytes=0-"
        req_headers = build_headers(target_url, range_val)

        try:
            req = urllib.request.Request(target_url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=280, context=ctx) as resp:
                status = resp.status
                ct = resp.headers.get("Content-Type", "video/mp4")
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
            self._error(e.code, f"CDN error {e.code}: {e.reason} | {body[:500]}")
        except Exception as e:
            self._error(502, f"Proxy error: {str(e)}")

    def do_HEAD(self):
        raw_path = self.path
        marker = "?url="
        idx = raw_path.find(marker)
        if idx == -1:
            self._error(400, "Missing ?url=")
            return
        target_url = raw_path[idx + len(marker):]

        if not target_url:
            self._error(400, "Missing ?url=")
            return

        # Decode percent-encoding if client encoded the URL
        target_url = urllib.parse.unquote(target_url)

        target_parsed = urllib.parse.urlparse(target_url)
        if not any(d in target_parsed.netloc for d in ALLOWED_DOMAINS):
            self._error(403, "Domain not allowed")
            return

        ctx = make_ssl_ctx()
        req_headers = build_headers(target_url)

        try:
            req = urllib.request.Request(target_url, headers=req_headers, method="HEAD")
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

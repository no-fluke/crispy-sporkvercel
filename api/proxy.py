from http.server import BaseHTTPRequestHandler
import urllib.request
import urllib.parse
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
    "User-Agent":      "Dalvik/2.1.0 (Linux; U; Android 11; RMX2001 Build/RP1A.200720.011)",
    "Accept-Encoding": "identity",
    "Connection":      "keep-alive",
}

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

        # Range header passthrough (for chunked downloading)
        req_headers = dict(FORWARD_HEADERS)
        range_val = self.headers.get("Range")
        if range_val:
            req_headers["Range"] = range_val

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            req = urllib.request.Request(target_url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=280, context=ctx) as resp:
                status = resp.status
                ct     = resp.headers.get("Content-Type", "video/mp4")
                cl     = resp.headers.get("Content-Length", "")
                cr     = resp.headers.get("Content-Range", "")
                ar     = resp.headers.get("Accept-Ranges", "bytes")

                self.send_response(status)
                self.send_header("Content-Type", ct)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Accept-Ranges", ar)
                if cl:
                    self.send_header("Content-Length", cl)
                if cr:
                    self.send_header("Content-Range", cr)
                self.end_headers()

                # Stream in 1MB chunks
                while True:
                    chunk = resp.read(1048576)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()

        except urllib.error.HTTPError as e:
            self._error(e.code, f"CDN error: {e.reason}")
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

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

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

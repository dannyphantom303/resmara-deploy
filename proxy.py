#!/usr/bin/env python3
"""Simple path-based reverse proxy for Tailscale funnel.

Routes:
  /resmara/* -> localhost:8083 (strip /resmara prefix)
  /* -> localhost:8082
"""
import http.server
import urllib.request
import sys

PROXY_PORT = 8090
ROUTES = {
    "/resmara": "http://127.0.0.1:8083",
}

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_request(self, method):
        path = self.path
        target_base = None
        strip_prefix = ""
        for prefix, base in ROUTES.items():
            if path.startswith(prefix):
                target_base = base
                strip_prefix = prefix
                break
        if target_base is None:
            target_base = "http://127.0.0.1:8082"
        else:
            path = path[len(strip_prefix):] or "/"

        target_url = target_base + path
        print(f"PROXY: {method} {self.path} -> {target_url}", file=sys.stderr, flush=True)

        try:
            req = urllib.request.Request(target_url, method=method)
            for key, val in self.headers.items():
                if key.lower() not in ("host", "connection", "transfer-encoding"):
                    req.add_header(key, val)
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            with urllib.request.urlopen(req, data=body, timeout=30) as resp:
                self.send_response(resp.status)
                for key, val in resp.headers.items():
                    if key.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(key, val)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for key, val in e.headers.items():
                if key.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(key, val)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Bad Gateway: {e}".encode())

    def do_GET(self): self.do_request("GET")
    def do_POST(self): self.do_request("POST")
    def do_PUT(self): self.do_request("PUT")
    def do_PATCH(self): self.do_request("PATCH")
    def do_DELETE(self): self.do_request("DELETE")
    def do_OPTIONS(self): self.do_request("OPTIONS")
    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", PROXY_PORT), ProxyHandler)
    print(f"Proxy running on port {PROXY_PORT}", file=sys.stderr, flush=True)
    server.serve_forever()

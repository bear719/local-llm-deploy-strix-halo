# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""本地预览器：把汉化后的静态目录当站点根，API 路径反代到 8080。
用途：在不重启 8080 主服务的前提下，用无头浏览器验证汉化版能否正常渲染与发请求。
用法：python3 preview_server.py [端口]
"""
import json, sys, urllib.request, urllib.error, pathlib
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = pathlib.Path("/home/<user>/llama-ui-zh")
UPSTREAM = "http://127.0.0.1:8080"
API_PREFIXES = ("/v1", "/props", "/slots", "/health", "/metrics", "/api", "/models", "/tokenize")


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):
        print("%s %s" % (self.command if hasattr(self, "command") else "-", fmt % args), flush=True)

    def _is_api(self):
        p = self.path.split("?")[0]
        return any(p == x or p.startswith(x + "/") for x in API_PREFIXES)

    def _proxy(self):
        url = UPSTREAM + self.path
        body = None
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            body = self.rfile.read(n)
        req = urllib.request.Request(url, data=body, method=self.command)
        for k, v in self.headers.items():
            if k.lower() in ("host", "content-length", "connection", "accept-encoding"):
                continue
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                data = r.read()
                self.send_response(r.status)
                for k, v in r.getheaders():
                    if k.lower() in ("transfer-encoding", "connection", "content-encoding", "content-length"):
                        continue
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def _dispatch(self):
        if self._is_api():
            return self._proxy()
        p = self.path.split("?")[0]
        f = ROOT / p.lstrip("/")
        if p in ("/", "") or (not f.exists() and "." not in p.rsplit("/", 1)[-1]):
            # SPA 兜底
            self.path = "/index.html"
        return SimpleHTTPRequestHandler.do_GET(self)

    do_GET = _dispatch
    do_POST = _dispatch


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

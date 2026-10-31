from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import json, os, secrets, re
from ledger import DB_PATH, ROOT, import_csv, initialize, ledger_state, preview_csv, record_allocation, seed_demo, export_csv

HOST="127.0.0.1"; PORT=8334; TOKEN=secrets.token_urlsafe(24)
seed_demo()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def send_bytes(self,status,data,kind):
        self.send_response(status); self.send_header("Content-Type",kind); self.send_header("Content-Length",str(len(data))); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Content-Security-Policy","default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'"); self.end_headers(); self.wfile.write(data)
    def send_json(self,obj,status=200): self.send_bytes(status,json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode(), "application/json; charset=utf-8")
    def valid_host(self): return self.headers.get("Host") in (f"127.0.0.1:{PORT}",f"localhost:{PORT}")
    def do_GET(self):
        if not self.valid_host(): return self.send_json({"error":"Invalid host"},403)
        route=urlparse(self.path).path
        if route=="/":
            page=(ROOT/"static"/"index.html").read_text(encoding="utf-8").replace("__TOKEN__",TOKEN)
            return self.send_bytes(200,page.encode(),"text/html; charset=utf-8")
        if route in ("/app.css","/app.js"):
            asset=ROOT/"static"/route.lstrip("/")
            return self.send_bytes(200,asset.read_bytes(),"text/css; charset=utf-8" if route.endswith(".css") else "text/javascript; charset=utf-8")
        if route=="/api/state": return self.send_json(ledger_state())
        if route=="/api/export.csv":
            data=export_csv().encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/csv; charset=utf-8"); self.send_header("Content-Disposition",'attachment; filename="workflow-ledger-export.csv"'); self.send_header("Content-Length",str(len(data))); self.send_header("X-Content-Type-Options","nosniff"); self.end_headers(); self.wfile.write(data); return
        match=re.fullmatch(r"/fixtures/(invoices|payments|payments-revised)\.csv",route)
        if match: return self.send_bytes(200,(ROOT/"fixtures"/(match.group(1)+".csv")).read_bytes(),"text/csv; charset=utf-8")
        return self.send_json({"error":"Not found"},404)
    def do_POST(self):
        if not self.valid_host() or self.headers.get("Origin") not in (f"http://127.0.0.1:{PORT}",f"http://localhost:{PORT}"):
            return self.send_json({"error":"Invalid request origin"},403)
        if self.headers.get("X-Request-Token")!=TOKEN: return self.send_json({"error":"Request token required"},403)
        try: size=int(self.headers.get("Content-Length","-1"))
        except ValueError: size=-1
        if size<0 or size>2_000_000: return self.send_json({"error":"Request must be under 2 MB"},413)
        try: body=json.loads(self.rfile.read(size))
        except Exception: return self.send_json({"error":"Invalid JSON"},400)
        if not isinstance(body,dict): return self.send_json({"error":"Request body must be an object"},400)
        route=urlparse(self.path).path
        try:
            if route=="/api/preview":
                return self.send_json(preview_csv(body.get("csv"),body.get("record_type"),body.get("mapping")))
            if route=="/api/import":
                return self.send_json(import_csv(body.get("csv"),body.get("record_type"),body.get("source_name"),body.get("mapping")))
            if route=="/api/allocate":
                result=record_allocation(body.get("payment_row"),body.get("invoice_row"),body.get("amount_text"),body.get("reason"))
                return self.send_json(result)
        except (ValueError,KeyError) as exc: return self.send_json({"error":str(exc)},400)
        return self.send_json({"error":"Not found"},404)

if __name__=="__main__":
    print(f"Workflow Ledger listening at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()

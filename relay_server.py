#!/usr/bin/env python3
"""
Muse Sync relay server v2 - Python standard library only, no pip install needed.
Run:  python3 relay_server.py          (listens on port 8765, or $PORT)
Deploy this file on a public server (SnapDeploy, Dockerfile) so both Muse
and the Android Studio plugin can reach it. The plugin and Muse never talk
directly - they both talk to this relay.

Protocol (all JSON):
  POST /push   {"code": "...", "action": "create"|"update"|"delete",
                "path": "app/src/main/java/.../MainActivity.kt",
                "content_b64": "<base64 of file content, empty for delete>"}
  GET  /poll?code=...&since=0
       -> {"messages": [{"id": 1, "action": ..., "path": ...,
                         "content_b64": ...}], "next": 1}
  POST /error  {"code": "...", "source": "build"|"run",
                "text": "<build/run error output>"}
       -> {"ok": true, "id": 1}   (plugin reports build errors here)
  GET  /errors?code=...&since=0
       -> {"errors": [{"id": 1, "ts": 1731..., "source": "build",
                       "text": "..."}], "next": 1}
  GET  /health -> {"ok": true}

Notes:
  - "code" is the secret pairing code. It is only a namespace key: messages
    are grouped per code, and anyone who knows the code can push/poll it.
    Keep the code private; never commit it to the repo.
  - Paths with ".." are rejected. Keep only the last 500 messages and
    100 error reports per code.
  - State is kept in relay_data.json next to this file. On hosts with an
    ephemeral filesystem (free tiers), a restart wipes old messages -
    the plugin re-polls from its saved position, so re-push if needed.
"""
import base64, json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DATA_FILE = os.path.join(os.path.dirname(__file__), "relay_data.json")
_lock = threading.Lock()
_messages = {}   # code -> list of messages
_next_id = {}    # code -> next id
_errors = {}     # code -> list of error reports
_next_err = {}   # code -> next error id


def _load():
    global _messages, _next_id, _errors, _next_err
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                data = json.load(f)
            _messages = {k: v for k, v in data.get("messages", {}).items()}
            _next_id = {k: int(v) for k, v in data.get("next_id", {}).items()}
            _errors = {k: v for k, v in data.get("errors", {}).items()}
            _next_err = {k: int(v) for k, v in data.get("next_err", {}).items()}
        except Exception:
            pass


def _save():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"messages": _messages, "next_id": _next_id,
                       "errors": _errors, "next_err": _next_err}, f)
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        code = q.get("code", [""])[0]
        try:
            since = int(q.get("since", ["0"])[0])
        except ValueError:
            since = 0
        if parsed.path == "/poll":
            with _lock:
                msgs = [m for m in _messages.get(code, []) if m["id"] > since]
                nxt = _next_id.get(code, 0)
            return self._send({"messages": msgs, "next": nxt})
        if parsed.path == "/errors":
            with _lock:
                errs = [e for e in _errors.get(code, []) if e["id"] > since]
                nxt = _next_err.get(code, 0)
            return self._send({"errors": errs, "next": nxt})
        if parsed.path == "/health":
            return self._send({"ok": True})
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/push":
            payload = self._read_json()
            if payload is None:
                return self._send({"error": "bad json"}, 400)
            code = payload.get("code", "")
            path = payload.get("path", "")
            if not code or not path or ".." in path:
                return self._send({"error": "code and a safe path are required"}, 400)
            with _lock:
                nid = _next_id.get(code, 0) + 1
                _next_id[code] = nid
                _messages.setdefault(code, []).append({
                    "id": nid,
                    "action": payload.get("action", "update"),
                    "path": path,
                    "content_b64": payload.get("content_b64", ""),
                })
                # Keep only the last 500 messages per code.
                _messages[code] = _messages[code][-500:]
                _save()
            return self._send({"ok": True, "id": nid})
        if parsed.path == "/error":
            payload = self._read_json()
            if payload is None:
                return self._send({"error": "bad json"}, 400)
            code = payload.get("code", "")
            text = payload.get("text", "")
            if not code or not text:
                return self._send({"error": "code and error text are required"}, 400)
            with _lock:
                nid = _next_err.get(code, 0) + 1
                _next_err[code] = nid
                _errors.setdefault(code, []).append({
                    "id": nid,
                    "ts": int(time.time()),
                    "source": payload.get("source", "build"),
                    "text": text[:20000],  # cap a single report at 20k chars
                })
                _errors[code] = _errors[code][-100:]
                _save()
            return self._send({"ok": True, "id": nid})
        return self._send({"error": "not found"}, 404)

    def log_message(self, *args):
        pass  # keep the console quiet


if __name__ == "__main__":
    _load()
    port = int(os.environ.get("PORT", "8765"))
    print(f"Muse Sync relay v2 running on port {port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()

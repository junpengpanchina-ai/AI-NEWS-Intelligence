import hmac
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATH = ROOT / "data" / "sitedata-bridge.token"
_SECRET = re.compile(
    r"(?i)(bearer\s+\S+|access_token['\"\s:=]+[A-Za-z0-9._\-]{8,}|refresh_token['\"\s:=]+[A-Za-z0-9._\-]{8,}|api[_-]?key['\"\s:=]+[A-Za-z0-9._\-]{8,}|sk-[A-Za-z0-9]+)"
)
_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
_ALLOWED = {"auth", "list", "describe", "rankings"}


def sanitize(value: str) -> str:
    text = _JWT.sub("[redacted]", value or "")
    text = _SECRET.sub("[redacted]", text)
    return text


def token() -> str:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TOKEN_PATH.is_file():
        current = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if current:
            return current
    generated = os.urandom(24).hex()
    TOKEN_PATH.write_text(generated, encoding="utf-8")
    return generated


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/v1/exec":
            self._send(404, {"detail": "not found"})
            return
        given = self.headers.get("X-Bridge-Token", "")
        if not hmac.compare_digest(given, token()):
            self._send(401, {"detail": "bridge unauthorized"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, {"detail": "invalid json"})
            return
        args = payload.get("args")
        if not isinstance(args, list) or not args or args[0] not in _ALLOWED:
            self._send(400, {"detail": "command not allowed"})
            return
        if any(not isinstance(item, str) for item in args):
            self._send(400, {"detail": "command not allowed"})
            return
        try:
            completed = subprocess.run(
                ["sitedata", *args],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._send(200, {"code": 124, "stdout": "", "stderr": "SiteData CLI 超时"})
            return
        except OSError:
            self._send(200, {"code": 127, "stdout": "", "stderr": "SiteData CLI 无法启动"})
            return
        self._send(
            200,
            {
                "code": completed.returncode,
                "stdout": completed.stdout or "",
                "stderr": sanitize(completed.stderr or "")[:500],
            },
        )


def main() -> None:
    token()
    server = ThreadingHTTPServer(("0.0.0.0", 8791), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()

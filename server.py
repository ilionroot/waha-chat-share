"""Read-only viewer that exposes a single WhatsApp chat from a local WAHA instance."""

import base64
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
WAHA_URL = "http://127.0.0.1:3000"
WAHA_SESSION = "default"
MESSAGE_LIMIT = 500
MEDIA_CHUNK_SIZE = 64 * 1024
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
PROXIED_MEDIA_HEADERS = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges")
ALLOWED_MEDIA: set[str] = set()


def load_env(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE .env file."""
    env = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


ENV = load_env(BASE_DIR / ".env")


def waha_get(path: str) -> object:
    """GET a WAHA endpoint and decode the JSON body."""
    request = urllib.request.Request(f"{WAHA_URL}{path}", headers={"X-Api-Key": ENV["WAHA_API_KEY"]})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def waha_post(path: str, payload: dict) -> object:
    """POST JSON to a WAHA endpoint and decode the JSON body."""
    request = urllib.request.Request(
        f"{WAHA_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"X-Api-Key": ENV["WAHA_API_KEY"], "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def send_message(chat_id: str, text: str, reply_to: str | None, image: dict | None) -> object:
    """Send a text or an image with caption to the chat, optionally quoting a message."""
    payload = {"session": WAHA_SESSION, "chatId": chat_id}
    if reply_to:
        payload["reply_to"] = reply_to
    if image:
        payload["caption"] = text
        payload["file"] = {"mimetype": image["mimetype"], "filename": image.get("filename") or "imagem", "data": image["data"]}
        return waha_post("/api/sendImage", payload)
    payload["text"] = text
    return waha_post("/api/sendText", payload)


def expose_media(media: dict | None) -> dict | None:
    """Map a WAHA media entry to a viewer URL and whitelist its file."""
    if not media or not media.get("url"):
        return None
    name = media["url"].rsplit("/", 1)[-1]
    ALLOWED_MEDIA.add(name)
    return {"url": f"/media/{name}", "mimetype": media.get("mimetype") or "", "filename": media.get("filename")}


def fetch_messages(chat_id: str) -> list[dict]:
    """Fetch the chat messages, keeping only the fields the page renders."""
    quoted_id = urllib.parse.quote(chat_id, safe="")
    raw = waha_get(f"/api/{WAHA_SESSION}/chats/{quoted_id}/messages?limit={MESSAGE_LIMIT}&downloadMedia=true")
    messages = [
        {
            "id": m.get("id"),
            "replyTo": (m.get("replyTo") or {}).get("body"),
            "timestamp": m.get("timestamp"),
            "fromMe": m.get("fromMe", False),
            "author": (m.get("_data") or {}).get("pushName")
            or (m.get("_data") or {}).get("notifyName")
            or m.get("participant")
            or m.get("from"),
            "body": m.get("body") or "",
            "hasMedia": m.get("hasMedia", False),
            "media": expose_media(m.get("media")),
        }
        for m in raw
    ]
    return sorted(messages, key=lambda m: m["timestamp"] or 0)


class ViewerHandler(BaseHTTPRequestHandler):
    """Serves the page and the messages of the configured chat, behind basic auth."""

    def authorized(self) -> bool:
        """Check the basic auth header against the viewer credentials."""
        expected = base64.b64encode(f"{ENV['VIEWER_USER']}:{ENV['VIEWER_PASSWORD']}".encode()).decode()
        return hmac.compare_digest(self.headers.get("Authorization", ""), f"Basic {expected}")

    def send(self, status: int, body: bytes, content_type: str) -> None:
        """Write a complete response."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        """Route the page and the messages endpoint."""
        if not self.authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="chat"')
            self.end_headers()
            return
        if self.path == "/":
            self.send(200, (BASE_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/messages":
            try:
                body = json.dumps(fetch_messages(ENV["CHAT_ID"])).encode()
                self.send(200, body, "application/json")
            except Exception as error:  # noqa: BLE001
                self.send(502, json.dumps({"error": str(error)}).encode(), "application/json")
        elif self.path.startswith("/media/"):
            self.proxy_media(self.path.removeprefix("/media/"))
        else:
            self.send(404, b"", "text/plain")

    def proxy_media(self, name: str) -> None:
        """Stream a media file of the configured chat from WAHA, honoring Range."""
        if name not in ALLOWED_MEDIA:
            self.send(404, b"", "text/plain")
            return
        headers = {"X-Api-Key": ENV["WAHA_API_KEY"]}
        if self.headers.get("Range"):
            headers["Range"] = self.headers["Range"]
        request = urllib.request.Request(f"{WAHA_URL}/api/files/{WAHA_SESSION}/{name}", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                self.send_response(response.status)
                for header in PROXIED_MEDIA_HEADERS:
                    if response.headers.get(header):
                        self.send_header(header, response.headers[header])
                self.send_header("Cache-Control", "private, max-age=3600")
                self.end_headers()
                while chunk := response.read(MEDIA_CHUNK_SIZE):
                    self.wfile.write(chunk)
        except urllib.error.HTTPError as error:
            self.send(error.code, b"", "text/plain")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:
        """Send a message to the configured chat."""
        if not self.authorized():
            self.send(401, b"", "text/plain")
            return
        if self.path != "/api/send" or self.headers.get("Content-Type") != "application/json":
            self.send(404, b"", "text/plain")
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_UPLOAD_BYTES:
            self.send(413, json.dumps({"error": "arquivo grande demais"}).encode(), "application/json")
            return
        try:
            data = json.loads(self.rfile.read(length))
            text = str(data.get("text", "")).strip()
            image = data.get("image")
            if image and not str(image.get("mimetype", "")).startswith("image/"):
                self.send(400, json.dumps({"error": "só imagens"}).encode(), "application/json")
                return
            if not text and not image:
                self.send(400, json.dumps({"error": "mensagem vazia"}).encode(), "application/json")
                return
            send_message(ENV["CHAT_ID"], text, data.get("replyTo"), image)
            self.send(200, b"{}", "application/json")
        except Exception as error:  # noqa: BLE001
            self.send(502, json.dumps({"error": str(error)}).encode(), "application/json")


def main() -> None:
    """Start the viewer server."""
    if not ENV.get("CHAT_ID"):
        sys.exit("CHAT_ID vazio no .env; rode ./list-chats.sh e preencha.")
    port = int(ENV.get("VIEWER_PORT", "8088"))
    print(f"Servindo o chat em http://0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), ViewerHandler).serve_forever()


if __name__ == "__main__":
    main()

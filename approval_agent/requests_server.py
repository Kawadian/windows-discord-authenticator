"""Loopback-only inlet for a standard-user desktop agent.

This inlet only submits evidence to the Discord owner. It cannot issue passwords.
The evidence is not authenticated and must never be represented as proof of an EXE.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from PIL import Image

MAX_BODY = 2_500_000
MAX_IMAGE = 1_500_000
FIELDS = ("trigger", "computer", "user", "window", "process", "captured_at")


def validate(body: bytes) -> tuple[dict, bytes | None]:
    if len(body) > MAX_BODY:
        raise ValueError("request too large")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("expected object")
    clean = {}
    for field in FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or len(value) > 180:
            raise ValueError(f"invalid {field}")
        clean[field] = value.replace("`", "'").replace("<", "(").replace(">", ")")
    if clean["trigger"] not in ("UAC 自動検知", "ホットキー"):
        raise ValueError("unknown trigger")
    image_b64 = payload.get("jpeg")
    if image_b64 is None:
        return clean, None
    if not isinstance(image_b64, str) or len(image_b64) > MAX_IMAGE * 2:
        raise ValueError("image too large")
    try:
        jpeg = base64.b64decode(image_b64, validate=True)
    except binascii.Error as exc:
        raise ValueError("invalid image encoding") from exc
    if len(jpeg) > MAX_IMAGE:
        raise ValueError("image too large")
    try:
        with Image.open(io.BytesIO(jpeg)) as image:
            if image.format != "JPEG" or image.width > 8000 or image.height > 8000:
                raise ValueError("invalid JPEG")
            image.verify()
    except (OSError, SyntaxError) as exc:
        raise ValueError("invalid JPEG") from exc
    return clean, jpeg


class RequestServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int, dispatch: Callable[[dict, bytes | None], None]):
        self.dispatch = dispatch
        self.last_request = 0.0
        self.rate_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), RequestHandler)


class RequestHandler(BaseHTTPRequestHandler):
    server: RequestServer

    def do_POST(self) -> None:
        if self.path != "/request":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0 or length > MAX_BODY:
                self.send_error(413)
                return
            payload, jpeg = validate(self.rfile.read(length))
            with self.server.rate_lock:
                if time.monotonic() - self.server.last_request < 8:
                    self.send_error(429)
                    return
                self.server.last_request = time.monotonic()
            self.server.dispatch(payload, jpeg)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error(400, str(exc))
            return
        except Exception:
            self.send_error(503, "Discord is unavailable")
            return
        self.send_response(202)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        # No screenshots, credentials, or request bodies in logs.
        pass

"""Capture ownership and privacy barrier, independent of the Windows UI.

No camera is constructed while screenshots=False. The same lock covers capture,
serialization and delivery: apply() returning is the barrier after which no old
frame can be captured or handed to the transport. Already delivered messages
cannot be recalled.
"""
from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, fields
from typing import Callable


@dataclass(frozen=True)
class Privacy:
    screenshots: bool = False
    computer: bool = False
    user: bool = False
    window: bool = False
    process: bool = False
    captured_at: bool = False
    automatic: bool = False

    @classmethod
    def parse(cls, data: dict) -> "Privacy":
        return cls(**{f.name: data.get(f.name) is True for f in fields(cls)})


class CaptureGate:
    def __init__(self, camera_factory: Callable, metadata: Callable, encode: Callable,
                 privacy: Privacy = Privacy()):
        self.lock = threading.RLock()
        self.privacy = privacy
        self.camera_factory = camera_factory
        self.metadata = metadata
        self.encode = encode
        self.camera = None
        self.latest = None
        self.latest_info = None
        self.closed = False

    def _discard(self):
        self.latest_info = None
        if self.latest is not None:
            self.latest.close()
            self.latest = None
        if self.camera is not None:
            camera, self.camera = self.camera, None
            camera.close()

    def apply(self, privacy: Privacy):
        with self.lock:
            # Dispose on every change, including metadata-only changes.
            self.privacy = privacy
            self._discard()

    def sample(self):
        with self.lock:
            if self.closed or not self.privacy.screenshots:
                return
            try:
                if self.camera is None:
                    self.camera = self.camera_factory()
                frame = self.camera.grab()
                if frame is not None:
                    if self.latest is not None:
                        self.latest.close()
                    self.latest = frame
                    self.latest_info = self.metadata(self.privacy)
            except Exception:
                self._discard()

    def deliver(self, trigger: str, immediate: bool, transport: Callable):
        with self.lock:
            if self.closed or (trigger == "UAC 自動検知" and not self.privacy.automatic):
                return
            if immediate and self.privacy.screenshots:
                self.sample()
            enabled = asdict(self.privacy)
            # Metadata collector must consult these flags before accessing OS data.
            values = self.latest_info if self.latest is not None else self.metadata(self.privacy)
            payload = {key: str(values.get(key, "取得不可"))[:180] if enabled[key] else "非共有"
                       for key in ("computer", "user", "window", "process", "captured_at")}
            payload["trigger"] = trigger
            payload["jpeg"] = (self.encode(self.latest)
                               if self.privacy.screenshots and self.latest is not None else None)
            transport(payload)

    def close(self):
        with self.lock:
            self.closed = True
            self._discard()

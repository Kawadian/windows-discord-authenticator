"""Standard-user process in the interactive Windows session.

No administrator password, Discord token, or privileged operation is available here.
"""
from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import queue
import threading
import time
import urllib.request
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

import psutil
from PIL import Image, ImageGrab
import dxcam

from .config import DATA_DIR

user32 = ctypes.windll.user32
EVENT_SYSTEM_DESKTOPSWITCH = 0x0020
WM_HOTKEY = 0x0312
HOTKEY_ID = 4371
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_F12 = 0x7B

WinEventProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD,
                                  wintypes.HWND, wintypes.LONG, wintypes.LONG,
                                  wintypes.DWORD, wintypes.DWORD)
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
                                    WinEventProc, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", POINT)]


def foreground() -> tuple[str, str]:
    hwnd = user32.GetForegroundWindow()
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        process = psutil.Process(pid.value).name()
    except (psutil.Error, OSError):
        process = "取得不可"
    return buffer.value[:180] or "取得不可", process[:180]


class DesktopAgent:
    def __init__(self, port: int, interval_ms: int):
        self.port = port
        self.interval = interval_ms / 1000
        self.latest: tuple[Image.Image, tuple[str, str], str] | None = None
        self.lock = threading.Lock()
        self.outbox: queue.Queue[tuple[str, bool]] = queue.Queue(maxsize=3)
        self.last_auto = 0.0
        self.last_consent = 0.0
        self.consent_pids: set[int] = set()
        self.hook_callback = WinEventProc(self._desktop_switch)

    def _sample(self) -> tuple[Image.Image, tuple[str, str], str]:
        info = foreground()
        image = ImageGrab.grab(all_screens=True)
        return image, info, datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _capture_loop(self) -> None:
        camera = None
        while True:
            started = time.monotonic()
            try:
                if camera is None:
                    camera = dxcam.create(output_color="RGB", processor_backend="numpy",
                                          backend="dxgi", max_buffer_len=2)
                frame = camera.grab()
                if frame is not None:
                    sample = (Image.fromarray(frame, "RGB").copy(), foreground(),
                              datetime.now(timezone.utc).isoformat(timespec="seconds"))
                    with self.lock:
                        self.latest = sample  # only one retained uncompressed frame
            except Exception:
                # Secure Desktop / monitor changes can invalidate DXGI duplication.
                if camera is not None:
                    try:
                        camera.release()
                    except Exception:
                        pass
                camera = None
            time.sleep(max(.05, self.interval - (time.monotonic() - started)))

    def _consent_loop(self) -> None:
        while True:
            try:
                current = {p.pid for p in psutil.process_iter(["name"])
                           if (p.info["name"] or "").lower() == "consent.exe"}
                if current - self.consent_pids:
                    self.last_consent = time.monotonic()
                    self._enqueue("UAC 自動検知", immediate=False)
                self.consent_pids = current
            except (psutil.Error, OSError):
                pass
            time.sleep(1.0)

    def _desktop_switch(self, hook, event, hwnd, id_object, id_child, thread, event_time) -> None:
        # The event also fires for non-UAC desktop switches. Require consent.exe.
        if time.monotonic() - self.last_consent < 3:
            self._enqueue("UAC 自動検知", immediate=False)

    def _enqueue(self, trigger: str, immediate: bool) -> None:
        now = time.monotonic()
        if trigger == "UAC 自動検知":
            if now - self.last_auto < 15:
                return
            self.last_auto = now
        try:
            self.outbox.put_nowait((trigger, immediate))
        except queue.Full:
            pass

    @staticmethod
    def _jpeg(image: Image.Image) -> str:
        image = image.copy()
        image.thumbnail((1920, 1200))
        if image.mode != "RGB":
            image = image.convert("RGB")
        stream = io.BytesIO()
        image.save(stream, format="JPEG", quality=78, optimize=True)
        return base64.b64encode(stream.getvalue()).decode("ascii")

    def _send_loop(self) -> None:
        while True:
            trigger, immediate = self.outbox.get()
            try:
                if immediate:
                    try:
                        sample = self._sample()
                    except Exception:
                        with self.lock:
                            sample = self.latest
                else:
                    with self.lock:
                        sample = self.latest
                if sample:
                    image, (window, process), captured = sample
                    jpeg = self._jpeg(image)
                else:
                    window, process, captured, jpeg = "取得不可", "取得不可", "取得不可", None
                payload = {
                    "trigger": trigger,
                    "computer": os.environ.get("COMPUTERNAME", "Windows-PC")[:180],
                    "user": os.environ.get("USERNAME", "Windows user")[:180],
                    "window": window,
                    "process": process,
                    "captured_at": captured,
                    "jpeg": jpeg,
                }
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/request",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=18) as response:
                    response.read()
            except Exception:
                # No sensitive material is written to disk from this process.
                pass
            finally:
                self.outbox.task_done()

    def run(self) -> None:
        for target in (self._capture_loop, self._consent_loop, self._send_loop):
            threading.Thread(target=target, daemon=True).start()
        hook = user32.SetWinEventHook(EVENT_SYSTEM_DESKTOPSWITCH,
                                      EVENT_SYSTEM_DESKTOPSWITCH, None,
                                      self.hook_callback, 0, 0, 0)
        if not user32.RegisterHotKey(None, HOTKEY_ID,
                                     MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_F12):
            user32.MessageBoxW(None, "Ctrl + Alt + F12 を登録できませんでした。",
                               "UAC Approval", 0x10)
            raise RuntimeError("RegisterHotKey failed")
        try:
            message = MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                    self._enqueue("ホットキー", immediate=True)
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            if hook:
                user32.UnhookWinEvent(hook)


def main() -> None:
    client = json.loads((DATA_DIR / "tray.json").read_text(encoding="utf-8"))
    DesktopAgent(int(client["port"]), int(client["capture_interval_ms"])).run()


if __name__ == "__main__":
    main()

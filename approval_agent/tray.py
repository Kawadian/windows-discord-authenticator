"""Interactive, unprivileged desktop agent. Credentials are never loaded here."""
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

import psutil
from PIL import Image

from .privacy import CaptureGate, Privacy

user32 = ctypes.windll.user32
EVENT_SYSTEM_DESKTOPSWITCH = 0x0020
WM_HOTKEY = 0x0312
HOTKEY_ID = 4371
WinEventProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD,
                                wintypes.HWND, wintypes.LONG, wintypes.LONG,
                                wintypes.DWORD, wintypes.DWORD)
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
                                 WinEventProc, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def metadata(privacy: Privacy) -> dict:
    result = {}
    if privacy.computer:
        result['computer'] = os.environ.get('COMPUTERNAME', 'Windows-PC')
    if privacy.user:
        result['user'] = os.environ.get('USERNAME', 'Windows user')
    if privacy.captured_at:
        result['captured_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if privacy.window or privacy.process:
        hwnd = user32.GetForegroundWindow()
        if privacy.window:
            buffer = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buffer, len(buffer))
            result['window'] = buffer.value or '取得不可'
        if privacy.process:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                result['process'] = psutil.Process(pid.value).name()
            except (psutil.Error, OSError):
                result['process'] = '取得不可'
    return result


class Camera:
    def __init__(self):
        # Import and initialize DXGI only after explicit opt-in.
        import dxcam
        self.camera = dxcam.create(output_color='RGB', processor_backend='numpy',
                                   backend='dxgi', max_buffer_len=2)

    def grab(self):
        frame = self.camera.grab()
        return Image.fromarray(frame, 'RGB').copy() if frame is not None else None

    def close(self):
        self.camera.release()


def jpeg(image):
    with image.copy() as reduced:
        reduced.thumbnail((1920, 1200))
        stream = io.BytesIO()
        reduced.save(stream, format='JPEG', quality=78, optimize=True)
        return base64.b64encode(stream.getvalue()).decode('ascii')


class DesktopAgent:
    def __init__(self, port: int, interval_ms: int, privacy: Privacy):
        self.port = port
        self.interval = interval_ms / 1000
        self.gate = CaptureGate(Camera, metadata, jpeg, privacy)
        self.stop = threading.Event()
        self.outbox = queue.Queue(maxsize=3)  # Only triggers, never images or metadata.
        self.last_auto = 0.0
        self.status = '待機中'
        self.hook_callback = WinEventProc(self._desktop_switch)
        self.last_consent = 0.0
        self.hook = None
        self.message_thread_id = None

    def _capture_loop(self):
        while not self.stop.is_set():
            self.gate.sample()
            self.stop.wait(self.interval)

    def _consent_loop(self):
        previous = set()
        while not self.stop.wait(1):
            if not self.gate.privacy.automatic:
                previous.clear()
                continue
            try:
                current = {p.pid for p in psutil.process_iter(['name'])
                           if (p.info['name'] or '').lower() == 'consent.exe'}
                if current - previous:
                    self.last_consent = time.monotonic()
                    self.enqueue('UAC 自動検知', False)
                previous = current
            except (psutil.Error, OSError):
                pass

    def _desktop_switch(self, *args):
        if time.monotonic() - self.last_consent < 3:
            self.enqueue('UAC 自動検知', False)

    def enqueue(self, trigger='ホットキー', immediate=True):
        if trigger == 'UAC 自動検知':
            if not self.gate.privacy.automatic or time.monotonic() - self.last_auto < 15:
                return
            self.last_auto = time.monotonic()
        try:
            self.outbox.put_nowait((trigger, immediate))
        except queue.Full:
            pass

    def _transport(self, payload):
        request = urllib.request.Request(
            f'http://127.0.0.1:{self.port}/request', data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=18) as response:
            response.read()
        self.status = 'Discord へ送信しました'

    def _send_loop(self):
        while not self.stop.is_set():
            try:
                trigger, immediate = self.outbox.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                self.gate.deliver(trigger, immediate, self._transport)
            except Exception:
                self.status = '送信できませんでした。認証設定・接続・Service を確認してください'
            finally:
                self.outbox.task_done()

    def _windows_loop(self):
        self.message_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self.hook = user32.SetWinEventHook(EVENT_SYSTEM_DESKTOPSWITCH,
                    EVENT_SYSTEM_DESKTOPSWITCH, None, self.hook_callback, 0, 0, 0)
        if not user32.RegisterHotKey(None, HOTKEY_ID, 0x4003, 0x7B):
            self.status = 'ホットキー登録失敗。画面の申請ボタンは利用できます'
        try:
            message = wintypes.MSG()
            while not self.stop.is_set() and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY:
                    self.enqueue()
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            if self.hook:
                user32.UnhookWinEvent(self.hook)

    def start(self):
        for target in (self._capture_loop, self._consent_loop, self._send_loop, self._windows_loop):
            threading.Thread(target=target, daemon=True).start()

    def close(self):
        self.stop.set()
        self.gate.close()
        if self.message_thread_id is not None:
            user32.PostThreadMessageW(self.message_thread_id, 0x0012, 0, 0)


def main():
    from .desktop_ui import main as ui_main
    ui_main()


if __name__ == '__main__':
    main()

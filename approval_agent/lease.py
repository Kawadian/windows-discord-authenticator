"""Persistent expiry record and cross-process lock for Service and watchdog."""
from __future__ import annotations

import contextlib
import json
import os
import secrets
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from .config import DATA_DIR

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def password(length: int = 40) -> str:
    if length < 12:
        raise ValueError("password too short")
    # A mixed-case letter and digit even with a restrictive local password policy.
    chars = [secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"),
             secrets.choice("abcdefghijkmnopqrstuvwxyz"),
             secrets.choice("23456789")]
    chars.extend(secrets.choice(_ALPHABET) for _ in range(length - 3))
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


@contextlib.contextmanager
def file_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "lease.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


class LeaseStore:
    def __init__(self, set_password: Callable[[str], None], directory: Path = DATA_DIR,
                 now: Callable[[], float] = time.time):
        self.set_password = set_password
        self.directory = directory
        self.now = now
        self.path = directory / "state.json"

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, state: dict) -> None:
        # State never contains the temporary or randomized password.
        fd, tmp = tempfile.mkstemp(prefix="lease-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def issue(self, seconds: int) -> tuple[str, float]:
        if not 30 <= seconds <= 1800:
            raise ValueError("TTL must be 30..1800 seconds")
        with file_lock(self.directory):
            state = self._read()
            if state.get("active"):
                if state["expires_at"] > self.now():
                    raise RuntimeError("A password is already active")
                self._rotate_locked()
            secret = password(16)
            expires_at = self.now() + seconds
            # Write first: if a crash happens during the account change, watchdog
            # still has the expiry deadline and can rotate it.
            self._write({"active": True, "expires_at": expires_at,
                         "lease_id": uuid.uuid4().hex})
            try:
                self.set_password(secret)
            except BaseException:
                # A password update may have succeeded even if the caller failed.
                # Rotate to a new random value before reporting failure.
                self._rotate_locked()
                raise
            return secret, expires_at

    def _rotate_locked(self) -> None:
        self.set_password(password())
        self._write({"active": False, "expires_at": None})

    def rotate(self) -> None:
        with file_lock(self.directory):
            self._rotate_locked()

    def expire_if_due(self) -> bool:
        with file_lock(self.directory):
            state = self._read()
            if state.get("active") and state["expires_at"] <= self.now():
                self._rotate_locked()
                return True
            return False

    def active_until(self) -> float | None:
        with file_lock(self.directory):
            state = self._read()
            return state["expires_at"] if state.get("active") else None

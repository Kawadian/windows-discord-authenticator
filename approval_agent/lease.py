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

from .config import DATA_DIR, Config

LOWER = "abcdefghijkmnopqrstuvwxyz"
UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
DIGITS = "23456789"
SYMBOLS = "!@#%_-+="


def password(length: int = 10, *, digits: bool = True, letters: bool = True,
             letter_case: str = "lower", symbols: bool = False) -> str:
    if type(length) is not int or not 8 <= length <= 64 or letter_case not in ("lower", "upper", "both"):
        raise ValueError("invalid password format")
    pools = []
    if digits:
        pools.append(DIGITS)
    if letters:
        if letter_case in ("lower", "both"):
            pools.append(LOWER)
        if letter_case in ("upper", "both"):
            pools.append(UPPER)
    if symbols:
        pools.append(SYMBOLS)
    if not pools or length < len(pools):
        raise ValueError("no password character sets selected")
    chars = [secrets.choice(pool) for pool in pools]
    alphabet = "".join(pools)
    chars.extend(secrets.choice(alphabet) for _ in range(length - len(chars)))
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def rotation_password() -> str:
    # Rotation is independent of the display policy and remains hard to guess.
    return password(40, digits=True, letters=True, letter_case="both", symbols=True)


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
                 now: Callable[[], float] = time.time, config: Config | None = None):
        self.set_password = set_password
        self.directory = directory
        self.now = now
        self.path = directory / "state.json"
        self.config = config

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
            options = self.config or Config("", 0, 0)
            options.validate()
            secret = password(options.password_length, digits=options.password_digits,
                              letters=options.password_letters,
                              letter_case=options.password_letter_case,
                              symbols=options.password_symbols)
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
        self.set_password(rotation_password())
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

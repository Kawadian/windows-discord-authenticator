from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


DATA_DIR = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "UacApproval"


@dataclass(frozen=True)
class Config:
    bot_token: str
    channel_id: int
    owner_id: int
    admin_account: str = "UacApproval"
    port: int = 53927
    capture_interval_ms: int = 750
    request_lifetime_seconds: int = 300
    password_length: int = 10
    password_digits: bool = True
    password_letters: bool = True
    password_letter_case: str = "lower"
    password_symbols: bool = False
    ttl_change_public: bool = False
    password_public: bool = False
    expiry_public: bool = False

    def validate(self) -> None:
        if type(self.password_length) is not int or not 8 <= self.password_length <= 64:
            raise ValueError("password_length must be 8..64")
        switches = (self.password_digits, self.password_letters, self.password_symbols,
                    self.ttl_change_public, self.password_public, self.expiry_public)
        if any(type(value) is not bool for value in switches):
            raise ValueError("password and visibility switches must be boolean")
        if not any((self.password_digits, self.password_letters, self.password_symbols)):
            raise ValueError("select at least one password character set")
        if self.password_letter_case not in ("lower", "upper", "both"):
            raise ValueError("invalid password letter case")

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        data = json.loads((path or DATA_DIR / "config.json").read_text(encoding="utf-8"))
        config = cls(**data)
        if not config.bot_token or config.channel_id <= 0 or config.owner_id <= 0:
            raise ValueError("Discord bot token, channel ID and owner ID are required")
        if not 200 <= config.capture_interval_ms <= 5000:
            raise ValueError("capture_interval_ms must be 200..5000")
        if not 1024 <= config.port <= 65535:
            raise ValueError("port must be 1024..65535")
        if not config.admin_account or "\\" in config.admin_account or "@" in config.admin_account:
            raise ValueError("admin_account must be a local user name")
        config.validate()
        return config

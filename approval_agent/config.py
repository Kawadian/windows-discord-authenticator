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
        return config

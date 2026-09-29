"""Run by SYSTEM task every minute, independently of the Windows Service."""
from __future__ import annotations

from .account import set_local_password
from .config import Config, DATA_DIR
from .lease import LeaseStore


def main() -> None:
    if not (DATA_DIR / 'config.json').exists():
        return
    config = Config.load()
    store = LeaseStore(lambda value: set_local_password(config.admin_account, value))
    store.expire_if_due()


if __name__ == "__main__":
    main()

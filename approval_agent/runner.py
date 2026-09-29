from __future__ import annotations

import asyncio
import logging
import threading

from .account import set_local_password
from .config import Config
from .discord_ui import ApprovalBot
from .lease import LeaseStore
from .requests_server import RequestServer

log = logging.getLogger(__name__)


async def run(stop: threading.Event) -> None:
    config = Config.load()
    store = LeaseStore(lambda value: set_local_password(config.admin_account, value))
    # Any password from a prior Service lifetime is revoked before listening.
    await asyncio.to_thread(store.rotate)
    bot = ApprovalBot(config, store)
    loop = asyncio.get_running_loop()

    def dispatch(payload: dict, jpeg: bytes | None) -> None:
        if not bot.ready_for_requests.is_set():
            raise RuntimeError("Discord Gateway has not connected")
        future = asyncio.run_coroutine_threadsafe(bot.post_request(payload, jpeg), loop)
        future.result(timeout=15)

    server = RequestServer(config.port, dispatch)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    bot_task = asyncio.create_task(bot.start(config.bot_token, reconnect=True))
    try:
        while not stop.is_set():
            if bot_task.done():
                await bot_task
                raise RuntimeError("Discord Gateway stopped")
            try:
                if await asyncio.to_thread(store.expire_if_due):
                    log.info("Expired the temporary administrator password")
            except Exception:
                log.exception("Password expiry failed; watchdog will retry")
            await asyncio.sleep(.5)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3)
        await bot.close()
        bot_task.cancel()
        await asyncio.gather(bot_task, return_exceptions=True)
        # Graceful stop revokes an active lease; a crash is covered by watchdog.
        await asyncio.to_thread(store.rotate)

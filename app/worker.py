import asyncio
import logging
import signal
from contextlib import suppress

from app.core.config import settings
from app.services.iiko import run_iiko_token_refresher
from app.services.menu import run_iiko_menu_refresher
from app.services.orders import (
    run_iiko_order_dispatcher,
    run_iiko_order_status_poller,
    run_tbank_payment_state_poller,
)


logger = logging.getLogger(__name__)


async def run_worker() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is None:
            continue
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_value, stop_event.set)

    tasks = (
        asyncio.create_task(run_iiko_token_refresher(stop_event), name="iiko-token-refresher"),
        asyncio.create_task(run_iiko_menu_refresher(stop_event), name="iiko-menu-refresher"),
        asyncio.create_task(run_iiko_order_dispatcher(stop_event), name="iiko-order-dispatcher"),
        asyncio.create_task(run_iiko_order_status_poller(stop_event), name="iiko-order-status-poller"),
        asyncio.create_task(run_tbank_payment_state_poller(stop_event), name="tbank-payment-state-poller"),
    )

    logger.info("%s worker started with %s background tasks", settings.app_name, len(tasks))
    try:
        await stop_event.wait()
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        logger.info("%s worker stopped", settings.app_name)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

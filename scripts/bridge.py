#!/usr/bin/env -S uv run --script

# L. Burke, M. Mashhour, T. Music 10/2026

# A helper script to enable communication between the smartcard web portal
# and attached cards.


import asyncio
import json
import logging
import time

import websockets
from aes_smartcard import SmartCard
from smartcard.Exceptions import CardConnectionException
from smartcard.util import toHexString

IDLE_TIMEOUT = 0  # timeout in seconds, 0 to disable

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
logging.getLogger("websockets").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class SmartCardBridge:
    def __init__(self) -> None:
        self.connection = None
        self.card = None
        self.last_activity = time.monotonic()

    def connect(self):
        self.last_activity = time.monotonic()
        try:
            self.card = SmartCard()
            self.card.connect(enter_app=False)
            assert self.card._connection is not None
            return {
                "status": "connected",
                "reader": str(self.card._connection.getReader()),
                "atr": toHexString(self.card._atr),
            }
        except SmartCard.SmartCardError as err:
            return {"error": str(err)}

    def disconnect(self):
        if self.card is not None:
            self.card.disconnect()
            self.card = None
        return {"status": "Disconnected"}

    def transmit(self, apdu):
        self.last_activity = time.monotonic()
        if self.card is None:
            return {"error": "Not connected"}
        try:
            assert self.card._connection is not None
            response, sw1, sw2 = self.card._connection.transmit(apdu)
            self.card._check_status_words(sw1, sw2)
            return {"data": response, "sw1": sw1, "sw2": sw2}
        except (SmartCard.SmartCardError, CardConnectionException) as err:
            return {"error": str(err)}


bridge = SmartCardBridge()


async def idle_watchdog():
    """Disconnect card reader after IDLE_TIMEOUT seconds of inactivity."""
    while True:
        await asyncio.sleep(30)
        if (
            bridge.card is not None
            and bridge.last_activity
            and (time.monotonic() - bridge.last_activity) > IDLE_TIMEOUT
        ):
            logger.info(
                "Idle timeout %s seconds passed - disconnecting reader", IDLE_TIMEOUT
            )
            bridge.disconnect()


async def handler(websocket):
    logger.info("Client connected: %s", websocket.remote_address)
    try:
        async for message in websocket:
            req = json.loads(message)
            cmd = req.get("cmd")

            if cmd == "connect":
                res = bridge.connect()
                await websocket.send(json.dumps(res))

            elif cmd == "transmit":
                apdu = req.get("apdu")
                res = bridge.transmit(apdu)
                await websocket.send(json.dumps(res))

            elif cmd == "reset":
                bridge.disconnect()
                res = bridge.connect()
                await websocket.send(json.dumps(res))

            elif cmd == "disconnect":
                res = bridge.disconnect()
                await websocket.send(json.dumps(res))

            elif cmd == "ping":
                await websocket.send(json.dumps({"status": "pong"}))

    except websockets.exceptions.ConnectionClosedOK:
        logger.info("Client disconnected normally")
    except Exception:
        logger.exception("Unexpected error:")


async def main():
    logger.info("APDU Bridge started on ws://localhost:8080")
    logger.info("Keep this running while using the Web Flasher.")

    if IDLE_TIMEOUT > 0:
        logger.info(
            "Reader will auto-disconnect after %s seconds of inactivity.", IDLE_TIMEOUT
        )
        asyncio.create_task(idle_watchdog())
    else:
        logger.info("Reader will not auto-disconnect due to inactivity.")

    async with websockets.serve(handler, "localhost", 8080):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())

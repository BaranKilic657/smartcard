#!/usr/bin/env -S uv run --script

"""
    Bridge.py

    A helper script to enable communication between the smartcard web portal
    and attached cards.

    Version 0.1

    M. Mashhour, T. Music 05/2026

"""

import asyncio
import json
import time

import websockets
from smartcard.System import readers
from smartcard.util import toHexString

IDLE_TIMEOUT = 300  # 5 minutes


class SmartCardBridge:
    def __init__(self):
        self.connection = None
        self.reader = None
        self.last_activity = 0

    def connect_reader(self):
        r = readers()
        if not r:
            return {"error": "No readers found"}
        self.reader = r[0]
        try:
            self.connection = self.reader.createConnection()
            self.connection.connect()
            atr = self.connection.getATR()
            self.last_activity = time.monotonic()
            return {"status": "connected", "reader": str(self.reader), "atr": toHexString(atr)}
        except Exception as e:
            return {"error": str(e)}

    def disconnect(self):
        if self.connection:
            try:
                self.connection.disconnect()
            except Exception:
                pass
            self.connection = None
        return {"status": "disconnected"}

    def transmit(self, apdu):
        if not self.connection:
            return {"error": "Not connected"}
        try:
            self.last_activity = time.monotonic()
            data, sw1, sw2 = self.connection.transmit(apdu)
            return {"data": data, "sw1": sw1, "sw2": sw2}
        except Exception as e:
            return {"error": str(e)}


bridge = SmartCardBridge()


async def idle_watchdog():
    """Disconnect card reader after IDLE_TIMEOUT seconds of inactivity."""
    while True:
        await asyncio.sleep(30)
        if (bridge.connection and bridge.last_activity and
                (time.monotonic() - bridge.last_activity) > IDLE_TIMEOUT):
            print(f"Idle timeout ({IDLE_TIMEOUT}s) - disconnecting reader")
            bridge.disconnect()


async def handler(websocket):
    print(f"Client connected: {websocket.remote_address}")
    try:
        async for message in websocket:
            req = json.loads(message)
            cmd = req.get("cmd")
            # print(f"Request {req}")

            if cmd == "connect":
                res = bridge.connect_reader()
                await websocket.send(json.dumps(res))

            elif cmd == "transmit":
                apdu = req.get("apdu")
                res = bridge.transmit(apdu)
                await websocket.send(json.dumps(res))

            elif cmd == "reset":
                res = bridge.connect_reader()
                await websocket.send(json.dumps(res))

            elif cmd == "disconnect":
                res = bridge.disconnect()
                await websocket.send(json.dumps(res))

            elif cmd == "ping":
                await websocket.send(json.dumps({"status": "pong"}))

    except websockets.exceptions.ConnectionClosedOK:
        print("Client disconnected normally")
    except Exception as e:
        print(f"Error: {e}")


async def main():
    print("APDU Bridge started on ws://localhost:8080")
    print("Keep this running while using the Web Flasher.")
    print(f"Reader will auto-disconnect after {IDLE_TIMEOUT}s of inactivity.")
    asyncio.create_task(idle_watchdog())
    async with websockets.serve(handler, "localhost", 8080):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())

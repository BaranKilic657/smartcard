#!/usr/bin/env -S uv run --script

import sys
import requests
import subprocess
from time import sleep
from Crypto.Cipher import AES
from smartcard.CardType import ATRCardType
from smartcard.ATR import ATR
from smartcard.CardConnection import CardConnection
from smartcard.CardRequest import CardRequest
from smartcard.util import toHexString, toBytes, toASCIIString, bs2hl

URL = "https://sigltv.sec.ei.tum.de/stream"
start = 0
CHUNK_SIZE = 1024 * 1024  # 1 MB

def fetch_chunk(start, end):
    headers = {
        "Range": f"bytes={start}-{end}",
        "TeamCode": team_code
    }
    response = requests.get(URL, headers=headers)
    if response.status_code not in (200, 206):
        if response.status_code == 404:
            raise Exception("404: Could not identify card key, most likely the group tag does not exist")
        if response.status_code == 500:
            raise Exception("500: Internal error. Please contact tutor!")
        raise Exception(f"Received status code {response.status_code}. Allowed is (200, 206). Exiting.")

    return response

# Check team code
if len(sys.argv) < 2:
    print("This script needs your team code as first parameter.")
    print(f"Example: {sys.argv[0]} ABCDEF")
    sys.exit(1)

if len(sys.argv[1]) != 6:
    print("Your team code must be six digits alphanumeric")
    sys.exit(1)

team_code = sys.argv[1].upper()
print(f"Using team code {team_code}")

# Open connection to card
cardrequest = CardRequest(timeout=5)
## Wait for the card to be present:
## In case the card is in the reader, this command will return immediately.
print("Waiting for card....")
cardservice = cardrequest.waitforcard()

key_valid = False
for i in range(3):
    try:
        cardservice.connection.connect()
        atr = ATR(cardservice.connection.getATR())
        print(f"ATR: {atr}")
        print("Connected to card with T0 protocol")
        if not atr.isT0Supported():
            raise Exception("Error: Card does not support T0 protocol.")

        # Fetch empty chunk to get test vectors
        response = fetch_chunk(0, 15)
        tv_enc   = bytes.fromhex(response.headers.get("TestVectorEnc", None))
        tv_plain = bytes.fromhex(response.headers.get("TestVectorPlain", None))
        print("First frame: verifying key using test vectors from response")
        print(f"Expected test vector plaintext: {tv_plain.hex()}")
        print(f"Decrypting test vector {tv_enc.hex()} -> ", end='')
        sc_response, sw1, sw2 = cardservice.connection.transmit(
            [0x88, 0x10, 0, 0, len(tv_enc)] + list(tv_enc))
        print(f"Status words: {sw1:02x} {sw2:02x}")

        sc_response, sw1, sw2 = cardservice.connection.transmit([0x88, 0xc0, 0x00, 0x00, 0x10])
        if sw1 != 0x90 or sw2 != 0x00:
            raise Exception(f"-> Failed! status words: {sw1:02x} {sw2:02x}")

        if bytes(sc_response) == tv_plain:
            print(f"Responses match!")
            key_valid = True
        else:
            raise Exception("Response Mismatch. Incorrect key. Exiting.")

        # Leave loop
        break
    except Exception as e:
        print("Error during card connection or key verification. Retrying.")
        print(e)
        print("\n")

if key_valid == False:
    print("Exiting...")
    sys.exit(0)

print("\n\nAttempting to start the stream")

# VLC reads from stdin
vlc = subprocess.Popen(
   ["vlc", "--play-and-exit", "-"],
   stdin=subprocess.PIPE,
   pipesize=CHUNK_SIZE
)

sleep(2)

try:
    while True:
        end = start + CHUNK_SIZE - 1
        response = fetch_chunk(start, end)
        data = response.content
        if not data:
            print("Empty data chunk. Exiting.")
            break

        kek_enc = bytes.fromhex(response.headers.get("Key-Encryption-Key"))
        print(f"Received {len(data)} bytes")
        print("AES CTR Nonce:", response.headers.get("CTR-Nonce"))
        print("Encrypted chunk key", kek_enc.hex())

        print(f"Decrypting chunk key {kek_enc.hex()} -> ", end='')
        sc_response, sw1, sw2 = cardservice.connection.transmit(
            [0x88, 0x10, 0, 0, len(kek_enc)] + list(kek_enc))
        print(f"Status words: {sw1:02x} {sw2:02x}")

        kek, sw1, sw2 = cardservice.connection.transmit([0x88, 0xc0, 0x00, 0x00, 0x10])
        if sw1 != 0x90 or sw2 != 0x00:
            print(f"-> Failed! status words: {sw1:02x} {sw2:02x}")
            break

        kek = bytes(kek)
        print (f"{kek.hex()} status words: {sw1:02x} {sw2:02x}")

        cipher = AES.new(
            kek,
            AES.MODE_CTR,
            nonce = bytes.fromhex(response.headers.get("CTR-Nonce"))
        )
        decrypted = cipher.decrypt(data)

        vlc.stdin.write(decrypted)
        vlc.stdin.flush()

        start += len(data)

        # Last chunk
        if len(data) < CHUNK_SIZE:
            break

except KeyboardInterrupt:
    print("Received CTRL-C, exiting...")

except BrokenPipeError:
    print("VLC exited. Stopping stream")

finally:
    vlc.stdin.close()
    print("Stream done. Waiting for vlc to exit.")
    vlc.wait()

print("Exited.")

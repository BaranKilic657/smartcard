#!/usr/bin/env -S uv run --script

import subprocess
import sys
import time

import Crypto.Cipher.AES
import requests
from aes_smartcard import SmartCard

URL = "https://sigltv.sec.ei.tum.de/stream"
CHUNK_SIZE = 1024 * 1024  # 1 MB


def fetch_chunk(start, end, team_code):
    headers = {"Range": f"bytes={start}-{end}", "TeamCode": team_code}
    response = requests.get(URL, headers=headers)
    if response.status_code not in (200, 206):
        if response.status_code == 404:
            raise requests.HTTPError(
                "404: Could not identify card key, most likely the group tag does not exist"
            )
        if response.status_code == 500:
            raise requests.HTTPError("500: Internal error. Please contact tutor!")
        raise requests.HTTPError(
            f"Received status code {response.status_code}. Allowed is (200, 206). Exiting."
        )

    return response


if len(sys.argv) < 2:
    print("This script needs your team code as first parameter.")
    print(f"Example: {sys.argv[0]} ABCDEF")
    sys.exit(1)

if len(sys.argv[1]) != 6:
    print("Your team code must be six digits alphanumeric")
    sys.exit(1)

team_code = sys.argv[1].upper()
print(f"Using team code {team_code}")

card = SmartCard()
card.connect()

print("Verifying key")
response = fetch_chunk(0, 15, team_code)
vector_encrypted = response.headers.get("TestVectorEnc", None)
vector_plain = response.headers.get("TestVectorPlain", None)
assert vector_encrypted is not None and vector_plain is not None

tv_encrypted = bytes.fromhex(vector_encrypted)
tv_plain = bytes.fromhex(vector_plain)
sc_plain = bytes(card.decrypt(list(tv_encrypted)))

assert sc_plain == tv_plain

print("\nAttempting to start the stream")

# VLC reads from stdin
vlc = subprocess.Popen(
    ["vlc", "--play-and-exit", "-"], stdin=subprocess.PIPE, pipesize=CHUNK_SIZE
)

time.sleep(2)
start = 0

try:
    while True:
        end = start + CHUNK_SIZE - 1
        response = fetch_chunk(start, end, team_code)
        data = response.content
        if not data:
            print("Empty data chunk. Exiting.")
            break

        hex_enc_kek = response.headers.get("Key-Encryption-Key")
        hex_nonce = response.headers.get("CTR-Nonce")
        assert hex_enc_kek is not None and hex_nonce is not None

        kek_enc = bytes.fromhex(hex_enc_kek)

        print(f"Received {len(data)} bytes")
        print("AES CTR Nonce:", hex_nonce)
        print(f"Decrypting chunk key {hex_enc_kek}")

        kek = bytes(card.decrypt(list(kek_enc)))
        nonce = bytes.fromhex(hex_nonce)
        aes_device = Crypto.Cipher.AES.new(kek, Crypto.Cipher.AES.MODE_CTR, nonce=nonce)
        decrypted = aes_device.decrypt(data)

        assert vlc.stdin is not None
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
    assert vlc.stdin is not None
    vlc.stdin.close()
    print("Stream done. Waiting for vlc to exit.")
    vlc.wait()

print("Exited.")

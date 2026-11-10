#!/usr/bin/env -S uv run --script

# T. Music, L.Burke 10/2026

# This script attempts to perform a decryption with a random ciphertext and checks
# whether the card works correctly.

import secrets

import Crypto.Cipher.AES
from aes_smartcard import SmartCard

key_ascii = "00 11 22 33 44 55 66 77 88 99 AA BB CC DD EE FF"
key = bytes.fromhex(key_ascii)

ciphertext = secrets.token_bytes(16)
aes_device = Crypto.Cipher.AES.new(key, Crypto.Cipher.AES.MODE_ECB)
expected_plaintext = aes_device.decrypt(ciphertext)

card = SmartCard()
card.connect()
card_plaintext = bytes(card.decrypt(list(ciphertext)))
card.disconnect()

if card_plaintext == expected_plaintext:
    print("Responses match.")
    print(f"Got plaintext: {card_plaintext.hex()}")
else:
    print("Response MISMATCH. Please check key")
    print(f"Expected plaintext: {expected_plaintext.hex()}")
    print(f"     Got plaintext: {card_plaintext.hex()}")

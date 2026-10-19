#!/usr/bin/env -S uv run --script

# L.Burke 10/2026

# This script attempts to perform a decryption with a random ciphertext and checks
# whether the card works correctly.

import secrets
import time

import Crypto.Cipher.AES
import numpy as np
from aes_smartcard import SmartCard
from picoscope import CHANNEL, TRIGGER, Picoscope, Timebase
from utils import compute_timings

key_ascii = "00 11 22 33 44 55 66 77 88 99 AA BB CC DD EE FF"
key = bytes.fromhex(key_ascii)


card = SmartCard()
card.connect()


capture_time_s = 10
sample_rate = 10e3
preSamples = 100
postSamples = int(capture_time_s * sample_rate)
tb = Timebase.from_freq(sample_rate)
scope = Picoscope(preSamples, postSamples, tb, TRIGGER.RISING, 1000)

aes_device = Crypto.Cipher.AES.new(key, Crypto.Cipher.AES.MODE_ECB)


ct_list = []
pt_list = []

start = time.monotonic()
scope.arm()
while (time.monotonic() - start) < capture_time_s:
    ciphertext = list(secrets.token_bytes(16))
    plaintext = card.decrypt(ciphertext)
    ct_list.append(ciphertext)
    pt_list.append(plaintext)

scope.capture([CHANNEL.B])
signal = scope.get_data(CHANNEL.B)
aes_times, comm_times = compute_timings(signal, sample_rate)

print(
    f"          AES performance: {np.mean(aes_times) * 1000:6.2f} mean, {np.max(aes_times) * 1000:6.2f} max"
)
print(
    f"Communication performance: {np.mean(comm_times) * 1000:6.2f} mean, {np.max(comm_times) * 1000:6.2f} max"
)
print(len(aes_times))
print(len(comm_times))
for idx in range(len(ct_list)):
    if aes_device.decrypt(bytes(ct_list[idx])) != bytes(pt_list[idx]):
        print("AES ERROR")
        break

card.disconnect()
scope.close()


import json
import sys

import h5py
import numpy as np

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


# AES S-box: fixed lookup table defined by the AES standard.
SBOX = np.array(list(bytes.fromhex("""
    637c777bf26b6fc53001672bfed7ab76
    ca82c97dfa5947f0add4a2af9ca472c0
    b7fd9326363ff7cc34a5e5f171d83115
    04c723c31896059a071280e2eb27b275
    09832c1a1b6e5aa0523bd6b329e32f84
    53d100ed20fcb15b6acbbe394a4c58cf
    d0efaafb434d338545f9027f503c9fa8
    51a3408f929d38f5bcb6da2110fff3d2
    cd0c13ec5f974417c4a77e3d645d1973
    60814fdc222a908846eeb814de5e0bdb
    e0323a0a4906245cc2d3ac629195e479
    e7c8376d8dd54ea96c56f4ea657aae08
    ba78252e1ca6b4c6e8dd741f4bbd8b8a
    703eb5664803f60e613557b986c11d9e
    e1f8981169d98e949b1e87e9ce5528df
    8ca1890dbfe6426841992d0fb054bb16
""")), dtype=np.uint8)

HAMMING_WEIGHT = np.array(
    [bin(i).count("1") for i in range(256)],
    dtype=np.uint8
)


def load_traces(filename: str):
    with h5py.File(filename, "r") as file:
        traces = file["traces"][:].astype(np.float32)
        plaintexts = file["plaintexts"][:]
        ciphertexts = file["ciphertexts"][:]

    return traces, plaintexts, ciphertexts


def predict_power(plaintexts: np.ndarray) -> np.ndarray:
    # Calculate the expected Hamming weight for every key guess.
    key_guesses = np.arange(256, dtype=np.uint8)

    xored = plaintexts[:, None] ^ key_guesses[None, :]
    sbox_output = SBOX[xored]
    predictions = HAMMING_WEIGHT[sbox_output]

    return predictions.T.astype(np.float32)


def recover_key(traces: np.ndarray, plaintexts: np.ndarray):
    # Center the measured traces and calculate their norms.
    traces = traces.copy()
    traces -= traces.mean(axis=0)

    trace_norm = np.sqrt(np.sum(traces * traces, axis=0))
    trace_norm += 1e-12

    key = []
    results = []

    for byte_index in range(16):
        predictions = predict_power(plaintexts[:, byte_index])

        # Center the predictions for each candidate key.
        predictions -= predictions.mean(axis=1, keepdims=True)

        prediction_norm = np.sqrt(np.sum(predictions * predictions, axis=1))
        prediction_norm += 1e-12

        # Pearson correlation between predictions and measurements.
        correlation = predictions @ traces
        correlation /= prediction_norm[:, None]
        correlation /= trace_norm[None, :]

        # Find the strongest absolute correlation for every key guess.
        scores = np.max(np.abs(correlation), axis=1)
        best_guess = int(np.argmax(scores))

        key.append(best_guess)

        best_candidates = np.argsort(scores)[-5:][::-1]
        results.append([
            (int(guess), float(scores[guess]))
            for guess in best_candidates
        ])

        print(f"Byte {byte_index:2d}: 0x{best_guess:02x} (score: {scores[best_guess]:.3f})")

    return key, results


def verify_key(key: list[int], plaintexts: np.ndarray, ciphertexts: np.ndarray) -> bool:
    cipher = Cipher(algorithms.AES(bytes(key)), modes.ECB())
    decryptor = cipher.decryptor()

    ciphertext = ciphertexts.tobytes()
    decrypted = decryptor.update(ciphertext) + decryptor.finalize()

    return decrypted == plaintexts.tobytes()


def save_results(filename: str, key: list[int], results: list, verified: bool):
    data = {
        "file": filename,
        "key": bytes(key).hex(),
        "verified": verified,
        "candidates": results
    }

    with open("dpa_results.json", "w") as file:
        json.dump(data, file, indent=2)


def main():
    filename = sys.argv[1] if len(sys.argv) > 1 else "example_2000.h5"

    traces, plaintexts, ciphertexts = load_traces(filename)
    print(f"Loaded {len(traces)} traces with {traces.shape[1]} samples each.")

    key, results = recover_key(traces, plaintexts)

    key_hex = bytes(key).hex()
    verified = verify_key(key, plaintexts, ciphertexts)

    print(f"\nRecovered key: {key_hex}")
    print(f"Verified: {verified}")

    save_results(filename, key, results, verified)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
DPA (Differential Power Analysis) attack on AES-128 smart card power traces.

Leakage model: Hamming weight of SBOX(plaintext XOR key_guess)
  - This targets the SubBytes operation in the first AES round.

Method:
  For each key byte position i (0-15):
    For each key guess k (0-255):
      prediction[t] = HW(SBOX(plaintext[t, i] XOR k))   for all traces t
      correlation[k] = max over all time points s of |corr(prediction, trace[t, s])|
    key[i] = argmax over k of correlation[k]

Verification:
  AES-128-ECB decrypt of ciphertexts should yield plaintexts for all blocks.

Performance notes (pure NumPy — no Python-level inner loops):
  - HW(x) = popcount is a 256-entry lookup table; HW(SBOX(x)) is fused into a
    single second table (_HW_SBOX), so computing HW(SBOX(pt ^ k)) for ALL key
    guesses is one broadcast XOR + one fancy-index call (was: a 256-iteration
    Python list comprehension plus a per-element bin(v).count('1') loop).
  - Trace centering/subtraction is done in place on the cast copy (no second
    (N, S) temporary), and norms use einsum (no (N, S) squared-value temp —
    that temporary is 1 GB at 2000 traces x 62,500 samples in float64).
  - Correlation normalization and abs() run in place on the (256, S) matrix.
  - The heavy (256, N) @ (N, S) product is a single BLAS call, unchanged.
  - Verification decrypts ALL blocks with one decryptor instance.

Usage:
  python3 dpa_attack.py [traces_file.h5]
"""

import json
import os
import sys

import h5py
import numpy as np


# ---------------------------------------------------------------------------
# AES S-box construction (GF(2^8) inverse + affine transform).
# Runs once at import; equivalent to a hardcoded 256-byte table.
# ---------------------------------------------------------------------------

def gf_mul(a, b, poly=0x11b):
    """Multiply a*b in GF(2^8) with reduction polynomial x^8+x^4+x^3+x+1 (0x11b)."""
    result = 0
    while b:
        if b & 1:
            result ^= a
        b >>= 1
        a <<= 1
        if a & 0x100:
            a ^= poly
    return result & 0xFF


def gf_inv(x):
    """Multiplicative inverse in GF(2^8). x=0 maps to 0."""
    if x == 0:
        return 0
    result = 1
    base = x
    exp = 254  # x^(-1) = x^(254) since x^255 = 1
    while exp:
        if exp & 1:
            result = gf_mul(result, base)
        base = gf_mul(base, base)
        exp >>= 1
    return result


def rotl8(x, n):
    """Rotate left by n bits in GF(2^8)."""
    n %= 8
    return ((x << n) & 0xFF) | (x >> (8 - n))


def build_aes_sbox():
    """Generate AES S-box algorithmically (GF(2^8) inverse + affine transform)."""
    sbox = []
    for x in range(256):
        inv = gf_inv(x)
        # AES affine transformation: y = inv ^ rot1 ^ rot2 ^ rot3 ^ rot4 ^ 0x63
        y = inv ^ rotl8(inv, 1) ^ rotl8(inv, 2) ^ rotl8(inv, 3) ^ rotl8(inv, 4) ^ 0x63
        sbox.append(y)
    return np.array(sbox, dtype=np.uint8)


SBOX = build_aes_sbox()

# Popcount lookup table: HW_TABLE[x] == bin(x).count('1') for every byte x.
HW_TABLE = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)

# HW(SBOX(x)) fused into one table: HW(SBOX(pt ^ k)) == HW_SBOX[pt ^ k].
# One composite lookup replaces the two-step table walk per trace.
HW_SBOX = HW_TABLE[SBOX]

# All key byte guesses 0..255 as uint8 (uint8 XOR wraps; no & 0xFF mask needed).
KEY_GUESSES = np.arange(256, dtype=np.uint8)


def prediction_matrix(pt_byte_column, dtype=np.float64):
    """
    Build the prediction matrix for one key byte position, fully vectorized.

        pred[k, t] = HW(SBOX(plaintext[t] XOR k))     for k = 0..255, t = 0..N-1

    Composed of one broadcast XOR (N, 256) and one lookup; returns (256, N).
    """
    ptb = np.asarray(pt_byte_column, dtype=np.uint8)
    xors = ptb[:, None] ^ KEY_GUESSES[None, :]          # (N, 256): pt ^ k for all k
    hw_out = HW_SBOX[xors]                              # (N, 256): HW(SBOX(pt^k))
    return hw_out.T.astype(dtype)                       # (256, N)


def dpa_attack(traces, plaintexts, dtype=np.float64):
    """
    Perform CPA/DPA attack on AES-128 first-round SubBytes.

    For each byte position, correlate predicted Hamming weights against every
    trace sample; the guess with the highest |corr| at any sample point wins.

    Args:
        traces:     (N, S) float array of power traces
        plaintexts: (N, 16) uint8 array of known plaintext bytes
        dtype:      compute dtype for the correlation math. np.float64 matches
                    the original floats exactly; np.float32 is ~2x faster and
                    halves memory with a negligible effect on ranking.

    Returns:
        key_guess: 16 best key bytes
        per_byte:  list of 16 lists, each with top-10 (key_guess, score) tuples
    """
    N, S = traces.shape

    # Cast once, then center traces in place (subtracts the per-sample mean).
    # Done a single time — reused for all 16 byte positions.
    Tc = traces.astype(dtype)
    Tc -= Tc.mean(axis=0, keepdims=True)                 # (N, S)
    # einsum avoids the (N, S) squared-value temporary of (Tc**2).sum(axis=0).
    Tnorm = np.sqrt(np.einsum("ts,ts->s", Tc, Tc)) + 1e-12  # (S,)

    per_byte = []

    for b in range(16):
        # Predicted Hamming weights for all 256 key guesses: (256, N).
        pred = prediction_matrix(plaintexts[:, b], dtype=dtype)

        # Center predictions across traces.
        pc = pred - pred.mean(axis=1, keepdims=True)     # (256, N)
        pn = np.sqrt(np.einsum("kn,kn->k", pc, pc)) + 1e-12  # (256,)

        # Pearson correlation of each guess against every sample point.
        # The (256, N) @ (N, S) product is the heavy part — one BLAS call.
        M = pc @ Tc                                      # (256, S)
        M /= pn[:, None]                                 # normalize prediction
        M /= Tnorm[None, :]                              # normalize trace
        np.abs(M, out=M)                                 # absolute correlation

        # For each guess, take max |corr| over all time points.
        scores = M.max(axis=1)                           # (256,)
        order = np.argsort(scores)[::-1]

        top10 = [(int(order[i]), float(scores[order[i]])) for i in range(10)]
        per_byte.append(top10)

    key_guess = [per_byte[b][0][0] for b in range(16)]
    return key_guess, per_byte


def verify_key(key_bytes, plaintexts, ciphertexts):
    """
    Verify a candidate key by AES-128-ECB decryption of ALL blocks in one call.

    Returns True iff Dec(ciphertext_i, key) == plaintext_i for every block.
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    decryptor = Cipher(algorithms.AES(bytes(key_bytes)), modes.ECB()).decryptor()
    flat_ct = bytes(np.asarray(ciphertexts, dtype=np.uint8).ravel())
    out = decryptor.update(flat_ct) + decryptor.finalize()

    pt_ref = np.asarray(plaintexts, dtype=np.uint8).ravel()
    return np.array_equal(np.frombuffer(out, dtype=np.uint8), pt_ref)


def main():
    default_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "sample_traces", "sample_traces", "example_2000.h5",
    )
    file_path = sys.argv[1] if len(sys.argv) > 1 else default_file

    print(f"Loading {file_path} ...")
    with h5py.File(file_path, "r") as f:
        traces = f["traces"][:].astype(np.float32)  # float32: 2x BLAS, half RAM
        pt = f["plaintexts"][:]
        ct = f["ciphertexts"][:]

    N, S = traces.shape
    print(f"Loaded {N} traces x {S} samples")

    print("Running DPA attack (16 bytes x 256 key guesses)...")
    key_guess, per_byte = dpa_attack(
        traces, pt, dtype=np.float32,
        # (pass dtype=np.float64 to reproduce the original floats exactly)
    )

    print("\nPer-byte top-5 CPA candidates:")
    for b in range(16):
        line = f"  byte {b:2d}: "
        line += "  ".join(f"0x{k:02x}({s:.3f})" for k, s in per_byte[b][:5])
        print(line)

    key_hex = "".join(f"{b:02x}" for b in key_guess)
    print(f"\nTop-1 key guess: {key_hex}")

    print("Verifying against AES-128-ECB decryption...")
    try:
        verified = verify_key(key_guess, pt, ct)
    except ImportError:
        print("  (cryptography package not installed — skipping verification)")
        verified = False
    if verified:
        print(f"*** VERIFIED: {key_hex} ***")
    else:
        print("Top-1 key NOT verified.")

    results_path = "dpa_results.json"
    with open(results_path, "w") as out:
        json.dump({
            "file": file_path,
            "traces": N,
            "top1_hex": key_hex,
            "top1": [f"{b:02x}" for b in key_guess],
            "per_byte": [[[k, round(s, 4)] for k, s in per_byte[b]] for b in range(16)],
        }, out, indent=2)
    print(f"Results saved to {results_path}")


if __name__ == "__main__":
    main()

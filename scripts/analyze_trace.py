#!/usr/bin/env python3
"""Recover an AES-128 key from the lab's power-trace HDF5 files.

This CPA attack targets the final AddRoundKey operation during AES decryption.
At that point the implementation handles ``plaintext_byte XOR key_byte``. The
Hamming weight of that value is used as the power-leakage model.

Run against the labelled reference first, then capture more traces if the
candidate for an unlabelled file does not validate:

    uv run python scripts/analyze_trace.py scripts/traces/traces.h5
    uv run python scripts/analyze_trace.py scripts/traces/example.h5 \
        --profile scripts/traces/traces.h5
"""

from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

import numpy as np
import tables
from Crypto.Cipher import AES


DEFAULT_WINDOW = (46_000, 55_000)


def load_measurements(filename: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    """Load either the supplied (singular names) or captured HDF5 layout."""
    with tables.open_file(filename, mode="r") as h5:
        traces = h5.root.traces.read().astype(np.float32)
        if hasattr(h5.root, "ciphertexts"):
            ciphertexts = h5.root.ciphertexts.read()
            plaintexts = h5.root.plaintexts.read()
        else:
            ciphertexts = h5.root.ciphertext.read()
            plaintexts = h5.root.plaintext.read()
        known_key = h5.root.key.read()[0] if hasattr(h5.root, "key") else None

    if traces.ndim != 2 or plaintexts.shape != ciphertexts.shape or plaintexts.shape[1] != 16:
        raise ValueError("Expected AES traces and N x 16 plaintext/ciphertext datasets")
    if traces.shape[0] != plaintexts.shape[0]:
        raise ValueError("Trace and plaintext row counts do not match")
    return traces, ciphertexts, plaintexts, known_key


def preprocess_traces(traces: np.ndarray) -> np.ndarray:
    """Remove each capture's DC offset without changing AES-dependent variation."""
    return traces - traces.mean(axis=1, keepdims=True)


def hamming_weight(values: np.ndarray) -> np.ndarray:
    """Return the number of set bits for every uint8 value in ``values``."""
    table = np.fromiter((value.bit_count() for value in range(256)), dtype=np.float32)
    return table[values]


def correlation_matrix(predictions: np.ndarray, traces: np.ndarray) -> np.ndarray:
    """Correlate every prediction column with every trace sample position."""
    predictions = predictions.astype(np.float32, copy=False)
    predictions -= predictions.mean(axis=0, keepdims=True)
    prediction_norm = np.sqrt(np.sum(predictions * predictions, axis=0))
    prediction_norm[prediction_norm == 0] = 1.0

    centered = traces.astype(np.float32, copy=True)
    centered -= centered.mean(axis=0, keepdims=True)
    trace_norm = np.sqrt(np.sum(centered * centered, axis=0))
    trace_norm[trace_norm == 0] = 1.0

    return (predictions.T @ centered) / (prediction_norm[:, None] * trace_norm[None, :])


def leakage_predictions(plaintext_byte: np.ndarray) -> np.ndarray:
    """Predict HW(plaintext_byte XOR candidate_key_byte) for all 256 guesses."""
    guesses = np.arange(256, dtype=np.uint8)
    internal_values = np.bitwise_xor(plaintext_byte[:, None], guesses[None, :])
    return hamming_weight(internal_values)


def parse_window(value: str, trace_length: int) -> tuple[int, int]:
    """Parse START:END and keep it within a trace's valid sample range."""
    try:
        start_text, end_text = value.split(":", maxsplit=1)
        start, end = int(start_text), int(end_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("window must use START:END, e.g. 46000:55000") from error
    start = max(0, start)
    end = min(trace_length, end)
    if start >= end:
        raise ValueError("window must overlap the captured trace")
    return start, end


def profile_windows(
    traces: np.ndarray, plaintexts: np.ndarray, known_key: np.ndarray, half_width: int
) -> list[tuple[int, int, float]]:
    """Locate ordered final-round leakage peaks from a labelled capture.

    AES implementations normally process the final sixteen bytes in sequence.
    Restricting each byte to its portion of that sequence avoids selecting an
    unrelated, but statistically large, peak elsewhere in a long trace.
    """
    final_start = min(DEFAULT_WINDOW[0], traces.shape[1] - 1)
    final_end = min(DEFAULT_WINDOW[1], traces.shape[1])
    if final_start >= final_end:
        final_start, final_end = 0, traces.shape[1]

    def true_correlation(byte_index: int) -> np.ndarray:
        prediction = hamming_weight(
            np.bitwise_xor(plaintexts[:, byte_index], known_key[byte_index])
        )[:, None]
        return correlation_matrix(prediction, traces)[0]

    first = true_correlation(0)
    last = true_correlation(15)
    first_peak = final_start + int(np.argmax(np.abs(first[final_start:final_end])))
    last_peak = final_start + int(np.argmax(np.abs(last[final_start:final_end])))

    windows: list[tuple[int, int, float]] = []
    search_radius = max(250, half_width * 12)
    for byte_index in range(16):
        correlation = true_correlation(byte_index)
        expected = round(first_peak + (last_peak - first_peak) * byte_index / 15)
        search_start = max(final_start, expected - search_radius)
        search_end = min(final_end, expected + search_radius + 1)
        peak = search_start + int(np.argmax(np.abs(correlation[search_start:search_end])))
        sign = float(np.sign(correlation[peak]) or 1.0)
        windows.append((max(0, peak - half_width), min(traces.shape[1], peak + half_width + 1), sign))
    return windows


def recover_key_byte(
    traces: np.ndarray,
    plaintext_byte: np.ndarray,
    window: tuple[int, int],
    expected_sign: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Rank all 256 guesses for one AES key byte using correlation power analysis."""
    start, end = window
    correlations = correlation_matrix(leakage_predictions(plaintext_byte), traces[:, start:end])
    scores = (correlations * expected_sign).mean(axis=1)
    ranking = np.argsort(scores)[::-1]
    peak = int(np.argmax(np.abs(correlations[ranking[0]]))) + start
    return ranking, scores, peak


def validate_key(key: np.ndarray, ciphertexts: np.ndarray, plaintexts: np.ndarray) -> int:
    """Return how many recorded AES-ECB decryptions match a proposed key."""
    cipher = AES.new(key.tobytes(), AES.MODE_ECB)
    return sum(
        cipher.decrypt(bytes(ciphertext)) == bytes(plaintext)
        for ciphertext, plaintext in zip(ciphertexts, plaintexts, strict=True)
    )


def find_valid_key(
    rankings: list[np.ndarray], ciphertexts: np.ndarray, plaintexts: np.ndarray, depth: int
) -> np.ndarray | None:
    """Test the best few byte guesses and return only a fully validated key.

    Statistical attacks can place a correct byte second rather than first.
    With the default depth of two this examines at most 2**16 complete keys.
    A single known plaintext pair filters candidates quickly; any survivor is
    then checked against every recorded pair.
    """
    candidates = [ranking[:depth] for ranking in rankings]
    total = int(np.prod([len(values) for values in candidates]))
    if total > 1_000_000:
        raise ValueError(f"Refusing to test {total:,} keys; reduce --search-depth")

    first_ciphertext = bytes(ciphertexts[0])
    first_plaintext = bytes(plaintexts[0])
    for values in product(*candidates):
        key = np.asarray(values, dtype=np.uint8)
        if AES.new(key.tobytes(), AES.MODE_ECB).decrypt(first_ciphertext) != first_plaintext:
            continue
        if validate_key(key, ciphertexts, plaintexts) == len(plaintexts):
            return key
    return None


def plot_traces(traces: np.ndarray, destination: Path) -> None:
    """Save a preview instead of opening a GUI window (works in WSL/headless use)."""
    import matplotlib.pyplot as pyplot

    figure, axis = pyplot.subplots()
    for trace_index in range(min(5, len(traces))):
        axis.plot(traces[trace_index], alpha=0.65, label=f"Trace {trace_index}")
    axis.set(xlabel="Sample position", ylabel="Measured signal", title="Smartcard power traces")
    axis.legend()
    figure.tight_layout()
    figure.savefig(destination, dpi=150)
    pyplot.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filename", type=Path, help="HDF5 trace file to attack")
    parser.add_argument("--window", default=f"{DEFAULT_WINDOW[0]}:{DEFAULT_WINDOW[1]}")
    parser.add_argument("--profile", type=Path, help="labelled HDF5 file used to locate byte timings")
    parser.add_argument("--half-width", type=int, default=20, help="half-width of a profiled window")
    parser.add_argument("--top", type=int, default=5, help="number of candidates to print per byte")
    parser.add_argument(
        "--search-depth",
        type=int,
        default=2,
        help="top guesses per byte to combine and AES-validate (default: %(default)s)",
    )
    parser.add_argument("--plot", type=Path, help="save a PNG preview of the first five traces")
    args = parser.parse_args()

    traces, ciphertexts, plaintexts, known_key = load_measurements(args.filename)
    traces = preprocess_traces(traces)
    if args.plot:
        plot_traces(traces, args.plot)
        print(f"Saved trace preview: {args.plot}")

    fallback_window = parse_window(args.window, traces.shape[1])
    windows = [(*fallback_window, -1.0)] * 16
    if args.profile:
        profile_traces, _, profile_plaintexts, profile_key = load_measurements(args.profile)
        if profile_key is None:
            parser.error("--profile requires an HDF5 file containing /key")
        if profile_traces.shape[1] != traces.shape[1]:
            parser.error("profile and target traces must use the same sample count")
        windows = profile_windows(preprocess_traces(profile_traces), profile_plaintexts, profile_key, args.half_width)
        print(f"Using timing/polarity profile from {args.profile}")

    print(f"Loaded {traces.shape[0]} traces with {traces.shape[1]} samples each")
    candidate_key = np.empty(16, dtype=np.uint8)
    rankings: list[np.ndarray] = []
    ranks_of_known: list[int] = []
    for byte_index in range(16):
        start, end, sign = windows[byte_index]
        ranking, scores, peak = recover_key_byte(traces, plaintexts[:, byte_index], (start, end), sign)
        rankings.append(ranking)
        candidate_key[byte_index] = ranking[0]
        top = " ".join(f"{guess:02X}({scores[guess]:.4f})" for guess in ranking[: args.top])
        print(f"byte {byte_index:02d} window={start}:{end} peak={peak}: {top}")
        if known_key is not None:
            ranks_of_known.append(int(np.flatnonzero(ranking == known_key[byte_index])[0]) + 1)

    print("\nTop-ranked key:", candidate_key.tobytes().hex(" ").upper())
    matches = validate_key(candidate_key, ciphertexts, plaintexts)
    print(f"Top-ranked AES validation: {matches}/{len(plaintexts)} plaintexts match")
    validated_key = find_valid_key(rankings, ciphertexts, plaintexts, args.search_depth)
    if validated_key is None:
        print(f"No valid key found among the top {args.search_depth} candidate(s) per byte.")
    else:
        print("Recovered key: ", validated_key.tobytes().hex(" ").upper())
    if known_key is not None:
        print("Known key:     ", known_key.tobytes().hex(" ").upper())
        print("Known-key ranks:", " ".join(map(str, ranks_of_known)))
    elif validated_key is None:
        print("Candidate did not validate. Capture more traces (typically 500-2000), then retry.")


if __name__ == "__main__":
    main()

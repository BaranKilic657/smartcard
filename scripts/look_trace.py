import numpy as np
import tables
import matplotlib.pyplot as pyplot

FILENAME = "scripts/traces/traces.h5"


def load_measurements(filename):
    with tables.open_file(filename) as h5:

        traces = h5.root.traces.read().astype(np.float32)

        # Two different names for those .h5 files
        if hasattr(h5.root, "ciphertexts"):
            ciphertexts = h5.root.ciphertexts.read()
            plaintexts = h5.root.plaintexts.read()
        else:
            ciphertexts = h5.root.ciphertext.read()
            plaintexts = h5.root.plaintext.read()

        if hasattr(h5.root, "key"):
            known_key = h5.root.key.read()[0]
        else:
            known_key = None

    return traces, ciphertexts, plaintexts, known_key



def preprocess_traces(traces):
    traces = traces - traces.mean(axis=1, keepdims=True)

    return traces



def plot_traces(traces):
    for i in range(5):
        pyplot.plot(traces[i], alpha=0.6, label=f"Trace {i}")

    pyplot.xlabel("Sample position")
    pyplot.ylabel("Measured signal")
    pyplot.title("Smartcard power traces")
    pyplot.legend()
    pyplot.show()


def main():

    traces, ciphertexts, plaintexts, known_key = load_measurements(FILENAME)

    print("Traces shape:", traces.shape)
    print("Ciphertexts shape:", ciphertexts.shape)
    print("Plaintexts shape:", plaintexts.shape)

    if known_key is not None:
        print("Known key:", known_key.tobytes().hex())
    else:
        print("Known key: Not available")

    traces = preprocess_traces(traces)

    plot_traces(traces=traces)


if __name__ == "__main__":
    main()
import logging
import os
from typing import ClassVar

import numpy as np
import tables as pt


class ColorFormatter(logging.Formatter):
    okblue: ClassVar[str] = "\033[94m"
    okcyan: ClassVar[str] = "\033[96m"
    okgreen: ClassVar[str] = "\033[92m"
    warning: ClassVar[str] = "\033[93m"
    fail: ClassVar[str] = "\033[91m"
    endc: ClassVar[str] = "\033[0m"

    log_format: ClassVar[str] = "%(asctime)s : %(name)s : %(levelname)s: %(message)s"

    FORMATS: ClassVar[dict] = {
        logging.DEBUG: okblue + log_format + endc,
        logging.INFO: log_format,
        logging.WARNING: warning + log_format + endc,
        logging.ERROR: fail + log_format + endc,
        logging.CRITICAL: fail + log_format + endc,
    }

    def format(self, record: logging.LogRecord) -> str:
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


class H5File:
    def open(
        self, filename: str, n_traces, n_samples: int, overwrite: bool = False
    ) -> None:
        if os.path.isfile(filename) and not overwrite:
            raise FileExistsError()

        self.file = pt.open_file(filename, "w")
        text_shape = (n_traces, 16)
        traces_shape = (n_traces, n_samples)

        self.traces = self.file.create_carray(
            self.file.root, "traces", pt.Float16Atom(), traces_shape
        )
        self.cipher = self.file.create_carray(
            self.file.root, "ciphertexts", pt.UInt8Atom(), text_shape
        )
        self.plain = self.file.create_carray(
            self.file.root, "plaintexts", pt.UInt8Atom(), text_shape
        )

    def add_data(
        self, trace: list[float], plaintext: bytes, ciphertext: bytes, line: int
    ) -> None:
        self.traces[line] = np.array(trace, dtype=np.float16)
        self.cipher[line] = np.frombuffer(ciphertext, dtype=np.uint8)
        self.plain[line] = np.frombuffer(plaintext, dtype=np.uint8)

    def close(self) -> None:
        self.file.close()


def compute_timings(trig_trace, frequency) -> tuple[list[float], list[float]]:
    # calculates card performance from high and low periods in trigger signal
    trig_trace = np.asarray(trig_trace)
    high = trig_trace > 1000

    # find rising and falling edges
    rising = np.flatnonzero(~high[:-1] & high[1:]) + 1
    falling = np.flatnonzero(high[:-1] & ~high[1:]) + 1

    if high[0]:
        falling = falling[1:]
    if high[-1]:
        rising = rising[:-1]

    high_durations = falling - rising
    low_durations = rising[1:] - falling[:-1]

    return high_durations / frequency, low_durations / frequency

#!/usr/bin/env -S uv run --script

# pyright: reportAttributeAccessIssue=false

# The output is a hdf5 file with three datasets (plaintext, ciphertext and traces)
# Each value of plain- and ciphertext is stored as a np.uint8-value
# Each value of the trace is stored as a np.int16-value

import ctypes
import logging
import os
import secrets
import signal
import sys
import time
from dataclasses import dataclass
from functools import partial
from typing import ClassVar

import h5py
import numpy as np
from picosdk.functions import adc2mV, assert_pico_ok, mV2adc
from picosdk.ps5000 import ps5000 as ps
from smartcard.ATR import ATR
from smartcard.CardRequest import CardRequest
from smartcard.System import readers
from tqdm import tqdm

###################################################################################################
# configuration start

# consider enabling compression and reducing chunksize when recording very large datasets
# https://docs.h5py.org/en/stable/high/dataset.html
n_traces = 200  # number of traces to capture
n_samples = 62500  # number of samples per trace (before falling trigger edge)
sample_rate = 250e6  # oscilloscope sample rate [S/sec]


out_file = "./traces.h5"  # output file name
overwrite_file = False

# defines the chunksize of the traces dataset in the hdf5 file
chunksize_traces = (n_traces, n_samples)

# configuration end
###################################################################################################


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


# create a logger
logger = logging.getLogger(os.path.basename(__file__))
formatter = ColorFormatter()
if logger.hasHandlers():
    logger.handlers.clear()
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)
logger.setLevel(logging.DEBUG)

###################################################################################################
# calculate timebase configuration values according to programmers guide:
# https://www.picotech.com/download/manuals/ps5000pg-en-1.pdf
# this will default to the higher frequency if no perfect match is available


@dataclass
class Timebase:
    value: int

    @classmethod
    def from_interval_ns(cls, interval_ns: float):
        if interval_ns < 2:
            value = 0
        elif interval_ns < 4:
            value = 1
        elif interval_ns < 8:
            value = 2
        else:
            value = int(interval_ns / 8 + 2)
        return cls(value)

    @classmethod
    def from_frequency(cls, freqency_hz: float):
        interval_ns = 1e9 / abs(freqency_hz)
        return cls.from_interval_ns(interval_ns)


###################################################################################################
class SmartCard:
    def connect(self):
        # detect the smart card based on the content of the ATR (card-centric approach)
        logger.info("Initializing card connection...")
        try:
            r = readers()
            if not r:
                print("No readers found")
                return False

            # Cardrequest returns a cardservice
            self.cs = CardRequest(readers=r, timeout=5).waitforcard()
            assert self.cs is not None
            self.connection = self.cs.connection
            self.connection.connect()
            atr = ATR(self.connection.getATR())
            print(f"Connected, ATR: {atr}")
            if not atr.isT0Supported():
                raise ConnectionError("Card does not support T0 protocol.")
            logger.info("Card connection established correctly")
        except TimeoutError:
            logger.warning("ERROR: Timeout exceeded")
            sys.exit(0)

    def decrypt(self, key):
        # format the command to be sent to the card:
        DECRYPT_KEY = [0x88, 0x10, 0, 0, len(key)] + key
        GET_RESPONSE = [0x88, 0xC0, 0x00, 0x00, 0x10]
        # send the commands and retrieve the responses
        # detecting a transmission error
        # signal.alarm(2)
        try:
            time.sleep(0.01)  # this can prevent the transmission error
            # This function doesn't terminate sometimes
            response, _sw1, _sw2 = self.connection.transmit(DECRYPT_KEY)

        # wait and try again after a transmission error
        except Exception as exc:
            print(exc)
            response, _sw1, _sw2 = self.connection.transmit(DECRYPT_KEY)
        response, _sw1, _sw2 = self.connection.transmit(GET_RESPONSE)
        return response


###################################################################################################
class HDF5File:
    def init(self, o_file, n_traces, n_samples, chunksize_traces):
        if os.path.isfile(o_file):
            logger.warning("File " + o_file + " already exists")
            if overwrite_file:
                os.remove(o_file)
                logger.warning("Overwriting")
            else:
                sys.exit()
        self.filehandle = h5py.File(o_file, mode="a")

        self.FHplaintext = self.filehandle.create_dataset(
            "plaintext",
            (n_traces, 16),
            dtype=np.uint8,
        )
        self.FHciphertext = self.filehandle.create_dataset(
            "ciphertext",
            (n_traces, 16),
            dtype=np.uint8,
        )
        self.FHtraces = self.filehandle.create_dataset(
            "traces",
            (n_traces, n_samples),
            chunks=chunksize_traces,
            dtype=np.float16,
        )

    def file_close(self):
        self.filehandle.close()

    def add_data(self, plaintext, ciphertext, trace_number, trace_data):
        self.FHplaintext[trace_number, :] = plaintext
        self.FHciphertext[trace_number, :] = ciphertext
        self.FHtraces[trace_number, :] = trace_data


###################################################################################################


class Oscilloscope:
    def __init__(self, nSamples, timebase: Timebase):

        # Create chandle and status ready for use
        self.chandle = ctypes.c_int16()
        self.status = {}

        # Open 5000 series PicoScope
        # Returns handle to chandle for use in future API functions
        self.status["openunit"] = ps.ps5000OpenUnit(ctypes.byref(self.chandle))
        assert_pico_ok(self.status["openunit"])

        # Set up channel A
        # handle = chandle
        self.chA = ps.PS5000_CHANNEL["PS5000_CHANNEL_A"]
        # enabled = 1
        self.couple_AC = 0  # AC=0, DC=1
        self.chARange = ps.PS5000_RANGE["PS5000_500MV"]
        # analogue offset = 0 V
        self.status["setChA"] = ps.ps5000SetChannel(
            self.chandle, self.chA, 1, self.couple_AC, self.chARange
        )
        assert_pico_ok(self.status["setChA"])

        # Set up channel B
        self.chB = ps.PS5000_CHANNEL["PS5000_CHANNEL_B"]
        # enabled = 1
        self.couple_DC = 1  # AC=0, DC=1
        self.chBRange = ps.PS5000_RANGE["PS5000_5V"]
        self.status["setChB"] = ps.ps5000SetChannel(
            self.chandle, self.chB, 1, self.couple_DC, self.chBRange
        )
        assert_pico_ok(self.status["setChB"])

        # Enable channel B as single trigger
        self.maxADC = ctypes.c_int16(32512)
        threshold = int(mV2adc(500, self.chBRange, self.maxADC))
        direction = 3  # rising 2; falling 3
        # delay = 0 s
        # auto Trigger = 5000 ms

        self.status["trigger"] = ps.ps5000SetSimpleTrigger(
            self.chandle, 1, self.chB, threshold, direction, 0, 5000
        )
        assert_pico_ok(self.status["trigger"])

        # Set number of pre and post trigger samples to be collected
        self.preTriggerSamples = nSamples
        self.postTriggerSamples = 0
        self.maxSamples = self.preTriggerSamples + self.postTriggerSamples

        # Get timebase information
        # handle = chandle
        self.timebase = timebase.value
        # noSamples = maxSamples
        # pointer to timeIntervalNanoseconds = ctypes.byref(timeIntervalns)
        self.oversample = 1
        # pointer to maxSamples = ctypes.byref(returnedMaxSamples)
        # segment index = 0
        timeIntervalns = ctypes.c_float()
        self.returnedMaxSamples = ctypes.c_int32()
        self.status["getTimebase"] = ps.ps5000GetTimebase(
            self.chandle,
            self.timebase,
            self.maxSamples,
            ctypes.byref(timeIntervalns),
            self.oversample,
            ctypes.byref(self.returnedMaxSamples),
            0,
        )
        assert_pico_ok(self.status["getTimebase"])

    def arm(self):
        # Run block capture
        # handle = chandle
        # number of pre-trigger samples = preTriggerSamples
        # number of post-trigger samples = PostTriggerSamples
        # timebase = 8 = 80 ns (see Programmer's guide for mre information on timebases)
        # oversample = 1
        # time indisposed ms = None (not needed in the example)
        # segment index = 0
        # lpReady = None (using ps5000IsReady rather than ps5000BlockReady)
        # pParameter = None
        self.status["runBlock"] = ps.ps5000RunBlock(
            self.chandle,
            self.preTriggerSamples,
            self.postTriggerSamples,
            self.timebase,
            self.oversample,
            None,
            0,
            None,
            None,
        )
        assert_pico_ok(self.status["runBlock"])

    def capture(self):
        # Check for data collection to finish using ps5000IsReady
        ready = ctypes.c_int16(0)
        while not ready.value:
            self.status["isReady"] = ps.ps5000IsReady(self.chandle, ctypes.byref(ready))

        # Create buffers ready for assigning pointers for data collection
        bufferAMax = (ctypes.c_int16 * self.maxSamples)()
        # bufferAMin = (ctypes.c_int16 * self.maxSamples)()  # used for downsampling

        # Set data buffer location for data collection from channel A
        # handle = chandle
        source = ps.PS5000_CHANNEL["PS5000_CHANNEL_A"]
        # pointer to buffer max = ctypes.byref(bufferAMax)
        # pointer to buffer min = ctypes.byref(bufferAMin)  # required only for downsampling
        # buffer length = maxSamples
        self.status["setDataBuffersA"] = ps.ps5000SetDataBuffers(
            self.chandle,
            source,
            ctypes.byref(bufferAMax),
            None,  # ctypes.byref(bufferAMin),
            self.maxSamples,
        )
        assert_pico_ok(self.status["setDataBuffersA"])

        # create overflow loaction
        overflow = ctypes.c_int16(0)
        # create converted type maxSamples
        cmaxSamples = ctypes.c_int32(self.maxSamples)

        # Retrieve data from scope to buffers assigned above
        # handle = chandle
        # start index = 0
        # pointer to number of samples = ctypes.byref(cmaxSamples)
        # downsample ratio = 1
        # downsample ratio mode = PS5000_RATIO_MODE_NONE
        # pointer to overflow = ctypes.byref(overflow))
        self.status["getValues"] = ps.ps5000GetValues(
            self.chandle, 0, ctypes.byref(cmaxSamples), 1, 0, 0, ctypes.byref(overflow)
        )
        assert_pico_ok(self.status["getValues"])

        overflow_chA = bool(overflow.value & (1 << 0))
        overflow_chB = bool(overflow.value & (1 << 1))
        if overflow_chA:
            logger.warning("Measurement overshoot change channel range for Channel A")
        if overflow_chB:
            logger.warning("Measurement overshoot change channel range for Channel B")

        # return ADC counts data converted to mV
        return adc2mV(bufferAMax, self.chARange, self.maxADC)

        # return raw adc count
        # return np.array(bufferAMax, np.int16)

    def stop(self):
        # Stop the scope
        # handle = chandle
        self.status["stop"] = ps.ps5000Stop(self.chandle)
        assert_pico_ok(self.status["stop"])

    def close(self):
        # Close unit Disconnect the scope
        # handle = chandle
        self.status["close"] = ps.ps5000CloseUnit(self.chandle)
        assert_pico_ok(self.status["close"])


###################################################################################################
def signal_handler(start_time, signal, frame):
    logger.warning("\nClosing connections...")
    hdf5file.file_close()
    oscilloscope.close()
    end_time = time.time()
    logger.info("Elapsed time: %f seconds" % (end_time - start_time))
    logger.info("Done!")
    sys.exit(0)


###################################################################################################
logger.info("Starting")
start_time = time.time()

logger.info("Initialization of hdf file")
hdf5file = HDF5File()
hdf5file.init(
    out_file,
    n_traces,
    n_samples,
    chunksize_traces,
)
logger.info("Initialization of smartcard")
smartcard = SmartCard()
smartcard.connect()
logger.info("Initialization of oscilloscope")
oscilloscope = Oscilloscope(n_samples, Timebase.from_frequency(sample_rate))

# connect signal handler
signal.signal(signal.SIGINT, partial(signal_handler, start_time))

# dummy measurements to warm up setup
logger.info("Taking few dummy measurements")
for i in range(3):
    oscilloscope.arm()
    smartcard.decrypt([0 for i in range(16)])
    oscilloscope.capture()

# start collecting power traces
logger.info("Starting capture... ")
for i in tqdm(range(n_traces), "Capturing: "):
    # generate a new random data vector
    ciphertext_data = list(secrets.token_bytes(16))

    # arm the oscilloscope
    oscilloscope.arm()
    # send data to the card to be decrypted
    plaintext_data = smartcard.decrypt(ciphertext_data)
    # plaintext_data = ciphertext_data

    # get the power trace
    trace_data = oscilloscope.capture()

    # save trace, plain-text and cipher-text into an hdf5 file
    hdf5file.add_data(plaintext_data, ciphertext_data, i, trace_data)

# close and exit
logger.info("Closing hdf5 file")
hdf5file.file_close()
logger.info("Closing smartcard connection")
# smartcard.close()
logger.info("Closing oscilloscope connection")
oscilloscope.close()
end_time = time.time()
logger.info("Elapsed time: %f seconds" % (end_time - start_time))
logger.info("Done!")
sys.exit(0)

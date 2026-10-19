import logging
import secrets
import signal
import sys
import time
from functools import partial

from aes_smartcard import SmartCard
from picoscope import CHANNEL, TRIGGER, Picoscope, Timebase
from tqdm import tqdm
from utils import ColorFormatter, H5File

# consider enabling compression and reducing chunksize for creating very large datasets
# https://docs.h5py.org/en/stable/high/dataset.html
n_traces = 100  # number of traces to capture
n_samples = 62500  # number of samples per trace (before falling trigger edge)
sample_rate = 250e6  # oscilloscope sample rate [S/sec]


filename = "example.h5"  # output file name
out_file = f"./traces/{filename}"
overwrite_file = False

# defines the chunksize of the traces dataset in the hdf5 file
chunksize_traces = (n_traces, n_samples)


# create a logger
logger = logging.getLogger(__name__)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(ColorFormatter())
logger.addHandler(ch)
logger.setLevel(logging.DEBUG)


start_time = time.time()
logger.info("Initialization")


# Configure Picoscope with only pretrigger samples, trigger when signal falls below 1V
timebase = Timebase.from_freq(sample_rate)
scope = Picoscope(n_samples, 0, timebase, TRIGGER.FALLING, 1000)

# Initialise smartcard
card = SmartCard()
card.connect()


# Check setup works before creating file
for i in range(3):
    scope.arm()
    card.decrypt([0 for i in range(16)])
    scope.capture([CHANNEL.A])
    trace = scope.get_data(CHANNEL.A)
    assert len(trace) == n_samples

h5file = H5File()
h5file.open(out_file, n_traces, n_samples)


# Signal handler enables gracefully stopping the script
def signal_handler(start_time, signal, frame):
    logger.warning("\nClosing connections...")
    h5file.close()
    scope.close()
    card.disconnect()
    end_time = time.time()
    logger.info("Elapsed time: %f seconds" % (end_time - start_time))
    logger.info("Done!")
    sys.exit(0)


# connect signal handler
signal.signal(signal.SIGINT, partial(signal_handler, start_time))


for i in tqdm(range(n_traces), "Capturing: "):
    ciphertext = secrets.token_bytes(16)
    scope.arm()
    plaintext = bytes(card.decrypt(list(ciphertext)))
    scope.capture([CHANNEL.A])
    trace = scope.get_data(CHANNEL.A)
    h5file.add_data(trace, plaintext, ciphertext, i)


logger.info("Closing File, Card and Scope")
h5file.close()
scope.close()
card.disconnect()
logger.info("Elapsed time: %f seconds" % (time.time() - start_time))

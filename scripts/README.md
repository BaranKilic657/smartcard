Scripts
==============

This folder contains a set of scripts for interacting with the web portal,
SiglTV and taking side-channel measurements.

## Bridge

Whenever the communication between card and web portal `sigltv.sec.ei.tum.de`
is necessary, the bridge.py script must run on a terminal. Relaying commands
between browser and smart card, it allows executing challenges and flashing
new firmware.

## Measurement

A basic example for how to capture traces using the provided card readers and
picoscopes is provided in `measure_traces.py`. The default parameters are
intended as a starting point.

Connect the cards left SMB connector (J3, signal output) to CH A of the picoscope
and the right SMB connector (J4, trigger output) to CH B.

## SiglTV

One of the challenges will be to clone your reference card in order to watch
the exclusive SiglTV. Executing the script `receiver.py` with your cloned
smart card attached will play the video.

In order for the script to know your card key, you must execute it with your
six digit team code, which you can either find in your repository name or
on the web portal.

Launch the script on the terminal as such: `./receiver.py <team-code>`.

Please note that to access SiglTV you first have to create your own
smartcard firmware as well as perform a successful DPA attack.
To prove this, provide your smartcard with a specific secret key,
derived by inverting each bit of the reference implementations key.

## Test Decryption

The python script `test_decryption.py` can be used to trigger a single decryption on the
card in order to ensure proper functioning of the interface. It can also be used
to test the AES implementation on the card by comparing the result with a
decryption performed with the provided key.

## Test Timing

To check if your card obeys the timing restrictions `test_timing.py` is available.


### Install requirements for measurement scripts

Install Picoscope drivers from https://www.picotech.com/downloads/linux:
   - `sudo bash -c 'echo "deb https://labs.picotech.com/debian/ picoscope main" >/etc/apt/sources.list.d/picoscope.list'`
   - `wget -O - https://labs.picotech.com/debian/dists/picoscope/Release.gpg.key | sudo apt-key add -`
   - `sudo apt-get update`
   - `sudo apt-get install picoscope`

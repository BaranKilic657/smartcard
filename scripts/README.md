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

See the dedicated readme in the measurement folder.

## SiglTV

One of the challenges will be to clone your reference card in order to watch
the exclusive SiglTV. Executing the script `receiver.py` with your cloned
smart card attached will play the video.

In order for the script to know your card key, you must execute it with your
six digit team code, which you can either find in your repository name or
on the web portal.

Launch the script on the terminal as such: `./receiver.py <team-code>`.

Please note that the reference card will _not_ work for SiglTV, as to prove
you have successfully cloned the card, you have to invert your secret key.

## Test Decryption

The python script `test_decryption.py` can be used to trigger a single decryption on the
card in order to ensure proper functioning of the interface. It can also be used
to test the AES implementation on the card by comparing the result with a
decryption performed with the key given in the file.
In order to run it, execute:

```
./test_decryption.py
```

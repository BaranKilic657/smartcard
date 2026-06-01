# Welcome to the Smart Card Laboratory!

## Resources for the Lab

For all documentation, such as the lab script, datasheets, reference manuals, reference implementations, please
visit the course's moodle page. Large PDFs and powerpoint slides are not destined to live in git repositories.

## Useful (external) resources

 * Smart Card Handbook (online) - can be found [here](https://opac.ub.tum.de/search?bvnr=BV019271999)
 * Power analysis attacks - revealing the secrets of smart cards - can be found [here](https://opac.ub.tum.de/search?bvnr=BV036480550)
 * Understanding cryptography -a textbook for students and practitioners- can be found [here](https://opac.ub.tum.de/search?bvnr=BV039865382)


## Initializing submodules in this Repository

In order to compile the demo smartcard os in `demo_os_stm32f051`, you need the Open source ARM
Cortex-M microcontroller library `libopencm3` (https://github.com/libopencm3/libopencm3).
It is already included as a submodule in the git repository. In order to use it, please execute the
following steps.

### Initialize the submodule

As first step, in your shell execute the following command in the directory of this Readme.

```
$ git submodule init
```
### Update the submodule

As soon as the submodule is initialized, download it.

```
$ git submodule update
```

### Build the libopencm3 lib

Build the necessary libopencm3 libraries for the stm32f0 to be linked to your binaries.

```
$ cd demo_os_stm32f051/libopencm3
$ make TARGETS=stm32/f0
```

### Build the test program

Lastly, you can use the Makefile in `demo_os_stm32f051` to build the demo program.
For flashing use either one of the flash scripts in the `scripts` directory.

By default `make` will compile your implementation to run standalone on your development card.
At a later point in the lab, you will give your peers the chance to attack your own implementations.
In order to do that, you will upload an app binary, which can be flashed onto reference cards. To build it,
simply enter `make app` in the os folder.

When working on your implementation, please put your desired aes key into the predefined variable in `keys.c`
and use the `get_application_aes_key()` function from `keys.h` to load it. As long as you are working on
your student card, you'll get the key you entered in `keys.c`. When competing against other teams, the web
portal will inject a newly generated key into your application binary, superseding the key from `keys.c`.
Thus, it is **important** to not use your own way to load the key!

### Developing with VSCode

If you prefer a graphical IDE, you can use the preinstalled Visual Studio Code together with the C/C++
and Cortex Debug extension. The required files are included already, but may require additional tweaking.
To debug using the current configuration, the openocd debug server must run in the background for GDB to
attach to.

### Running the Python Scripts

It is recommended to install uv, lightweight python package manager. You can do this locally by executing the
following script on the terminal; for more information please see https://docs.astral.sh/uv/getting-started/installation

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Your first Lab Challenge: Getting online with the Smartcard Bridge

After installing `uv`, pull your projects dependencies by executing `uv sync` in this folder.
Afterwards start the bridge script in `/scripts/bridge/bridge.py`. The bridge connects the smartcard
website to the card reader. Whenever you need to upload new application firmware to your reference card,
make sure to have it running.

The solution to the first challenge is `Ich bin smarter als die smarte Karte!`.


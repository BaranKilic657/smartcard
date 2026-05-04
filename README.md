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

**Important Notice:**  
If you experience problems debugging on the student lab PCs, you can try using a different openocd version,
provided by the SEC nas. In order to enable this config, execute the following
on every fresh terminal you want to use openOCD on. This should not be necessary on new Ubuntu 24.04 machines.

```
module use /nas/ei/share/sec/tools/modulefiles
module load openocd/latest
```

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








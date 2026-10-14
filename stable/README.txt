WetMeat 1.0 Stable — building the supplied source
================================================

This is the complete source of the stable Stockfish-derived engine, its
project tools and the model used by the supplied binaries. Stockfish authors
and copyright notices are preserved in AUTHORS, Copying.txt and the source.

Linux
-----
Install a C++17 compiler, GNU Make and Bash. From this stable folder:
  bash tools/build.sh native

The helper uses two build jobs by default and writes bin/wetmeat-local.
For a general AVX2 build, use x86-64-avx2 instead of native. For an older
x86-64 CPU, use x86-64. Select an architecture your machine actually supports.

Windows
-------
Use a suitable MSYS2/MinGW-w64 toolchain and its MinGW shell. From src/:
  make -j2 profile-build ARCH=x86-64-avx2 COMP=gcc EXE=wetmeat.exe GIT_SHA=49ea5ded GIT_DATE=20260930 GIT_DIFFINDEX=1

The release binaries were built with GCC/MinGW GCC 14 and profile optimisation.
Rebuilding with another compiler or training run can change the binary hash.
This package supplies the corresponding source, not a promise of byte-identical
output from every toolchain. Makefile lists the available target architectures.

The actual official network file is already in src/nn-252f33942263.nnue.
Normal source builds do not require a separate model download. This source
uses Stockfish's search, evaluation and network; it is not an independent core.

Historical test tools
---------------------
Python tools use the dependencies listed in requirements-test.txt. Some of
the later study scripts preserve original absolute paths and frozen hashes.
Configure an isolated study environment before running them. They are not
part of the end-user engine installation and are not started automatically.

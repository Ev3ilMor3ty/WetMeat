WetMeat 1.0 Stable — Linux
=========================

What to download
----------------
WetMeat-Linux.zip contains two ready-to-use Linux x86-64 builds:
  bin/wetmeat-linux-avx2     — the usual choice
  bin/wetmeat-linux-avx512   — for CPUs with the required AVX-512-ICL features

WetMeat-Source.zip contains the complete corresponding source, the actual NNUE
network, project tools and the earlier research versions.

The AVX2 build needs AVX2, BMI1, POPCNT and SSE4.1.
The AVX-512 build also needs the AVX-512-ICL/VNNI instruction set and BMI2.
Compatible Ice Lake or Zen 4-class CPUs are examples; a generic "AVX-512"
label alone does not establish compatibility. Use AVX2 if you are unsure.
These are Linux x86-64 programs, not macOS, ARM, Android or iOS applications.

Quick setup
-----------
1. Download WetMeat-Linux.zip and extract it with your archive manager.
2. Open a terminal in the extracted WetMeat-Linux folder.
3. Run:

   bash install.sh

The installer verifies the files, copies them to your user installation folder
and prints the exact engine path to use. It does not require sudo for the
default location: ~/.local/share/wetmeat/1.0-stable

To choose another folder:
   bash install.sh --prefix "$HOME/Chess/WetMeat"

For a portable setup without copying anything:
   chmod +x bin/wetmeat-linux-avx2 bin/wetmeat-linux-avx512
   ./bin/wetmeat-linux-avx2

At the UCI console, enter uci, then isready, then quit on separate lines.
The replies include the WetMeat name, uciok and readyok.

Use a chess interface
---------------------
Add the installed or extracted engine to a graphical chess application.
In Cute Chess: Tools > Settings > Engines > Add. Select the full path to
wetmeat-linux-avx2, choose UCI and save the entry.

Official Cute Chess downloads:
https://github.com/cutechess/cutechess/releases
Choose the graphical application. The interface is a separate download.

Engine settings
---------------
Skill Level: 20. UCI_LimitStrength: false. MultiPV: 1 for games.
Start with Threads = 2 and Hash = 256 MB. Use more cores or memory only when
they are available. Leave EvalFile at its default: the network is embedded.
Ponder can stay off. Leave SyzygyPath empty without installed tablebases.

Longer thinking time allows a deeper search. A useful starting time control
for games is 10 minutes plus 5 seconds per move.

Troubleshooting
---------------
Permission denied: run chmod +x on the selected engine file.
Illegal instruction: use the AVX2 build if AVX-512 is unsupported. A CPU
without the AVX2 requirements needs a compatible build from source.
No board: install the engine inside a UCI chess interface.
No unzip command: use your desktop archive manager or install unzip using
your distribution's package manager.

Source and licence
------------------
WetMeat Stable is a Stockfish-based project, licensed under GPL v3 or later.
Stockfish supplies the search, evaluation and official NNUE weights. See
CREDITS.txt, AUTHORS and Copying.txt for attribution and licence terms.
Full corresponding source and model: WetMeat-Source.zip, supplied alongside
this package. Keep access to that source when redistributing the engine.

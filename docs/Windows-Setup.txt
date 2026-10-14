WetMeat 1.0 Stable — Windows
===========================

What to download
----------------
WetMeat-Windows.zip is the ready-to-use Windows package.
WetMeat-Source.zip contains the complete corresponding engine source, the
actual NNUE network, project tools and the earlier research versions.

You need a 64-bit Windows 10/11 PC with AVX2, BMI1, POPCNT and SSE4.1 support.
These PC programs do not run on an iPhone, iPad, Mac or Windows on ARM.

Quick setup
-----------
1. Download WetMeat-Windows.zip and choose Extract All in File Explorer.
2. Open the extracted WetMeat-Windows folder.
3. You can use bin\wetmeat-windows-avx2.exe directly. Alternatively,
   double-click Install-WetMeat.cmd to copy it to your user installation folder.
   The script prints the exact engine path to select in your chess interface.
4. Install a chess interface with UCI support, such as Cute Chess or Arena.
5. Add the EXE as a UCI engine, then start a game or an analysis session.

Cute Chess: Tools > Settings > Engines > Add. Select the EXE and choose UCI.
Arena: Engines > Install New Engine. Select the EXE and choose UCI if asked.
Menu names can vary slightly between versions.

Official Cute Chess downloads:
https://github.com/cutechess/cutechess/releases
Choose the graphical application, not just cutechess-cli. The chess interface
is a separate download; it is not included in this engine package.

The optional installer uses:
%LOCALAPPDATA%\WetMeat\1.0-stable
You can also run Install-WetMeat.cmd "D:\Chess\WetMeat" to choose a folder.
Installing the engine in your own user folder does not need administrator rights.

Engine settings
---------------
Skill Level:       20
UCI_LimitStrength: false
MultiPV:           1 for games or one main analysis line
Threads:           Start with 2; increase only if more CPU cores are available
Hash:              Start with 256 MB; 512 MB is fine with enough free memory
Ponder:            Off for a simple setup
Move Overhead:     30 ms as a starting value
SyzygyPath:        Leave empty unless you already have endgame tablebases

The neural network is embedded in the EXE. Leave EvalFile at its default.
You do not need to download a model to play. For longer games, 10 minutes
plus 5 seconds per move is a useful starting time control.

If you see a text window
-----------------------
That is the engine's UCI console. The board and mouse controls belong to the
chess interface. Select WetMeat inside Cute Chess or Arena to play against it.
If the program will not start, check the CPU requirements and use a Windows PC.

Source and licence
------------------
WetMeat Stable is based on Stockfish. The search, evaluation and NNUE weights
come from the Stockfish project; WetMeat includes protocol and compatibility
fixes, builds and project tools. See CREDITS.txt, AUTHORS and Copying.txt.
The stable engine is GPL version 3 or later.

Complete corresponding source and the real model file are in WetMeat-Source.zip.
When sharing the binary, also provide access to that source package from the
same release or Discord channel. Do not replace the Stockfish copyright notices.

SHA256SUMS.txt covers the files in this extracted package. Release checksums
are supplied alongside the downloads.

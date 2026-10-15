WetMeat — complete project source collection
===========================================

stable/                      The Stockfish-derived WetMeat 1.0 source and tools
research/timing/             Earlier timing-budget experiment; not adopted
research/draw-aversion/      Draw-aversion experiment; not adopted
research/independent/        Separate independently written prototype
research/aurora/             Earlier standalone engine and tests
research/aurora-lab/         Earlier evaluation/training experiments
study-snapshots/             Versioned study tools, guards and report helpers
release-tools/              Packaging, installation and distribution helpers

The stable C++ source and official model are preserved exactly. Each project
keeps its licence. Stockfish's authors are listed under stable/AUTHORS and
its licence is stable/Copying.txt. Earlier Aurora code keeps its MIT licence;
the independent WetMeat prototype keeps its GPL licence.

The complete NNUE file is stable/src/nn-252f33942263.nnue. Its SHA256 is:
252f33942263bc8b8f740ba8aec3fed5a159ff148113c47a55c18c33d6627ab3
It is the actual model used by the stable release, not a download placeholder.
Run `python prepare-research.py` if you also want to populate the model file
in the two Stockfish-derived experimental source folders. This only copies
the supplied model; it does not download, train or change it.

Build the stable engine
-----------------------
You need GNU Make, Bash and a C++17 compiler. From stable/:
  bash tools/build.sh native

For a general older x86-64 CPU, use x86-64 instead of native. On Windows,
use an appropriate MSYS2/MinGW toolchain. Full build options and provenance
are described in stable/README.txt. A fresh build has its own file hash;
byte-identical reproduction of the profile-optimised release is not claimed.

About the research files
------------------------
These files preserve the project code, including historical versions of the
testing tools. They are separate from the release installer. Some study tools
refer to the original workspace paths, source fingerprints and frozen plans.
They need a deliberately configured study environment; the installer does
not start them. Research outputs, logs and private runtime checkpoints are
not included in this source collection.

The independent rewrite is not the stable Stockfish-based engine and does
not inherit its scores. None of the archived experiments is advertised as
stronger than the release. Use the stable Windows/Linux download to play.

CODE-INVENTORY.json identifies every collected source file and its SHA256.
Compiled build trees, virtual environments, caches, logs and private runtime
checkpoints are excluded. Required source files, licence notices and model
weights are included. The licence and attribution files explain which parts
come from Stockfish and which parts belong to the separate project tools.

WetMeat release tools
=====================

These scripts preserve the release preparation and publication workflow.
Most expect the original distribution workspace, including staging folders
and the saved manifests. They are not needed to install or play the engine.
The stable engine build instructions are in the main README and stable/.

To rerun the public ZIP content checker, copy docs/Package-file-manifest.json
next to verify_public_downloads.py as git-downloads-prepared.json, then run
that checker with Python 3. It downloads all four packages and compares every
file. This is roughly 646 MB of downloads and requires no GitHub token.

The numeric release ID and owner in the publishing scripts identify this
project release. Do not run publishing tools against another repository
without deliberately configuring and reviewing their targets first.
